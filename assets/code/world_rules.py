"""Find dry sites and connect their landmarks to town streets."""

import math
import re
from dataclasses import asdict, dataclass, field, replace
from functools import partial
from random import Random

from art_style import validate_art_style, validate_season
from settlement_rules import (
    SITE_ASPECTS,
    LocalSite,
    SettlementConfig,
    SettlementPlan,
    _boundary,
    make_settlement,
)
from terrain_rules import TerrainSampler, smoothstep, value_noise
from transport_rules import resample
from world_terrain import Cave, Coast, Grid, Lake, Region, River, WorldTerrain

FEATURES = {
    "HARBOR": "QUAY",
    "LAKESIDE": "LANDING",
    "RIVERSIDE": "BRIDGE",
    "MOUNTAIN": "LOOKOUT",
}
WATERSIDE = ("HARBOR", "LAKESIDE", "RIVERSIDE")


@dataclass(frozen=True)
class SettlementRequest:
    id: str
    near: tuple
    profile: str = "AUTO"
    search_radius: float = 105.0
    settlement: SettlementConfig = field(default_factory=SettlementConfig)


@dataclass(frozen=True)
class WorldConfig:
    seed: int = 42
    size: tuple = (1600.0, 1280.0)
    terrain_step: float = 8.0
    base_elevation: float = 24.0
    relief: float = 11.0
    snowline: float = 192.0
    grass_density: float = 0.8
    regions: tuple = ()
    coast: Coast | None = None
    lakes: tuple = ()
    rivers: tuple = ()
    caves: tuple = ()
    settlements: tuple = ()
    art_style: str = "CARTOON"
    season: str = "SUMMER"

    @classmethod
    def from_dict(cls, values):
        values = dict(values)
        values["size"] = tuple(values.get("size", cls.size))
        for key, kind in (
            ("regions", Region),
            ("lakes", Lake),
            ("rivers", River),
            ("caves", Cave),
        ):
            values[key] = tuple(kind(**item) for item in values.get(key, ()))
        if values.get("coast") is not None:
            values["coast"] = Coast(**values["coast"])
        values["settlements"] = tuple(
            SettlementRequest(
                **{
                    **item,
                    "near": tuple(item["near"]),
                    "settlement": SettlementConfig(
                        **item.get("settlement", {})
                    ),
                }
            )
            for item in values.get("settlements", ())
        )
        return cls(**values).validate()

    def validate(self):
        validate_art_style(self.art_style)
        validate_season(self.season)
        if type(self.seed) is not int or not 0 <= self.seed <= 2_000_000_000:
            raise ValueError(
                "World seed must be an integer in [0, 2000000000]"
            )
        if len(self.size) != 2 or any(
            not _in_range(v, 300, 8000) for v in self.size
        ):
            raise ValueError("World size must be [width, length] in 300–8000m")
        if not _in_range(self.terrain_step, 3, 24):
            raise ValueError("terrain_step must be in [3, 24] metres")
        if math.prod(Grid(self.size, self.terrain_step).shape) > 240_000:
            raise ValueError(
                "Terrain grid exceeds 240000 cells; increase terrain_step"
            )
        if not _in_range(self.relief, 0, 100) or not _in_range(
            self.grass_density, 0, 1.5
        ):
            raise ValueError(
                "Use relief in [0, 100] and grass_density in [0, 1.5]"
            )
        if not all(
            _in_range(v, -500, 5000)
            for v in (self.base_elevation, self.snowline)
        ):
            raise ValueError(
                "base_elevation and snowline must be in [-500, 5000]m"
            )
        if len(self.settlements) > 12 or len(self.regions) > 24:
            raise ValueError(
                "Use at most 12 settlements and 24 terrain regions"
            )
        bodies = (*self.lakes, *self.rivers)
        if len(bodies) > 24:
            raise ValueError("Use at most 24 lakes, ponds, rivers and streams")
        _validate_ids([b.id for b in bodies], reserved=("sea",))
        _validate_ids([c.id for c in self.caves])
        _validate_ids([site.id for site in self.settlements])
        for lake in self.lakes:
            factor = 0.5 if lake.kind in ("POND", "MARSH_POOL") else 1.5
            if min(lake.radii) < self.terrain_step * factor:
                raise ValueError(f"Reduce terrain_step around lake {lake.id}")
        for river in self.rivers:
            factor = 0.5 if river.kind == "STREAM" else 2.5
            if river.width < self.terrain_step * factor:
                raise ValueError(
                    f"Reduce terrain_step or widen river {river.id}"
                )
        for site in self.settlements:
            site.settlement.validate()
            if site.profile not in (*SITE_ASPECTS, "AUTO"):
                raise ValueError(f"Unknown settlement profile: {site.profile}")
            if len(site.near) != 2 or not all(
                _in_range(v, -size / 2, size / 2)
                for v, size in zip(site.near, self.size, strict=True)
            ):
                raise ValueError(
                    f"Settlement {site.id} must be inside the map"
                )
            if not _in_range(site.search_radius, 0, 800):
                raise ValueError("search_radius must be in [0, 800] metres")
        return self


def _in_range(value, low, high):
    return type(value) in (int, float) and low <= value <= high


def _validate_ids(ids, reserved=()):
    if len(set(ids)) != len(ids) or any(
        identifier in reserved
        or not isinstance(identifier, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", identifier)
        for identifier in ids
    ):
        raise ValueError("IDs must be unique and use letters, digits, _ or -")


@dataclass(frozen=True)
class Landmark:
    kind: str
    start: tuple
    end: tuple
    width: float
    water_id: str = ""
    water_level: float = 0.0


class LandmarkGradeError(ValueError):
    """The landmark deck cannot connect to the local terrain."""


@dataclass(frozen=True)
class WorldSite:
    id: str
    profile: str
    centre: tuple
    bounding_cells: tuple
    settlement: SettlementPlan
    landmark: Landmark | None = None
    deck_path: tuple = ()

    def as_dict(self):
        return {
            "id": self.id,
            "profile": self.profile,
            "centre": self.centre,
            "bounding_cells": self.bounding_cells,
            "landmark": asdict(self.landmark) if self.landmark else None,
            "deck_path": self.deck_path,
            "settlement": self.settlement.as_dict(),
        }


@dataclass(frozen=True)
class WorldPlan:
    config: WorldConfig
    terrain: WorldTerrain
    grid: Grid
    sites: tuple

    def as_dict(self):
        return {
            "schema_version": 1,
            "units": "metres",
            "coordinate_space": "blender_world_z_up",
            "config": asdict(self.config),
            "grid_cells": self.grid.shape,
            "sites": [site.as_dict() for site in self.sites],
            "navigation": world_navigation(self.sites),
        }


def _offset(point, direction, amount):
    return tuple(p + d * amount for p, d in zip(point, direction, strict=True))


def _relative(point, centre):
    return tuple(a - b for a, b in zip(point, centre, strict=True))


def _direction(a, b):
    length = math.dist(a, b)
    return tuple((y - x) / length for x, y in zip(a, b, strict=True))


def _shore(terrain, body, dry, wet):
    for _ in range(18):
        middle = tuple((a + b) / 2 for a, b in zip(dry, wet, strict=True))
        if terrain.water_distance(body, *middle)[0] > 0:
            dry = middle
        else:
            wet = middle
    return dry, terrain.water_distance(body, *dry)[1]


def _waterfront(terrain, centre, profile, radius):
    match = terrain.waterside(*centre, profile)
    if match is None:
        return None
    body, water = match
    boundary_distance, _ = terrain.water_distance(body, *centre)
    if not radius * 0.69 < boundary_distance < radius * 1.58 + 28:
        return None
    if terrain.water_distance(body, *water)[0] > 0:
        return None
    direction = _direction(centre, water)
    shore, level = _shore(terrain, body, centre, water)
    distance = math.dist(centre, shore)
    if not radius * 0.78 + 5 < distance < radius * 1.34 + 26:
        return None
    start = _offset(shore, direction, -5.5)
    if profile == "RIVERSIDE":
        across = water
        for offset in range(4, 305, 4):
            opposite = _offset(water, direction, offset)
            if terrain.water_distance(body, *opposite)[0] > 0:
                bank, _ = _shore(terrain, body, opposite, across)
                end = _offset(bank, direction, 6.5)
                break
            across = opposite
        else:
            return None
        if terrain.wet(*end, 3.0):
            return None
    else:
        # Sheltered inlets cannot extend through the far shoreline.
        length = 23.0 if profile == "HARBOR" else 13.5
        end = _offset(shore, direction, length)
        if terrain.water_distance(body, *end)[0] > -2:
            return None
    width = {"HARBOR": 6.0, "RIVERSIDE": 4.6, "LAKESIDE": 3.3}[profile]
    if terrain.wet(*start, width / 2 + 0.7):
        return None
    return direction, Landmark(
        FEATURES[profile], start, end, width, body, level
    )


def _lookout(terrain, centre, radius):
    points = [
        _offset(
            centre,
            (math.cos(i * math.tau / 16), math.sin(i * math.tau / 16)),
            radius * 1.53,
        )
        for i in range(16)
    ]
    levels = [terrain.height(*p) for p in points]
    if (
        max(levels) - min(levels) < 19
        or terrain.height(*centre) < terrain.config.base_elevation + 7
    ):
        return None
    index = min(range(len(points)), key=levels.__getitem__)
    direction = _direction(centre, points[index])
    start = _offset(centre, direction, radius * 1.13 + 8)
    end = _offset(start, direction, 6.5)
    if terrain.wet(*end, 7):
        return None
    return direction, Landmark("LOOKOUT", start, end, 6.2)


def _bench(terrain, centre, radius, direction, profile, x, y):
    wx, wy = centre[0] + x, centre[1] + y
    base = terrain.height(wx, wy)
    dx, dy = direction
    along, across = x * dx + y * dy, x * dy - y * dx
    long, short = SITE_ASPECTS[profile]
    distance = math.hypot(across / (radius * long), along / (radius * short))
    flat = 1.02 if profile == "MOUNTAIN" else 0.91
    weight = 1 - smoothstep(flat, 1.49, distance)
    if not weight:
        return base
    waters = terrain.water_near(wx, wy)
    if waters:
        weight *= smoothstep(3, 20, min(w.distance for w in waters))
    height = terrain.height(*centre)
    if profile == "MOUNTAIN":
        u = along / radius
        lift = radius * 0.031
        height += lift * (1 - smoothstep(-0.74, -0.26, u))
        height -= lift * smoothstep(0.05, 0.58, u)
        height -= across * 0.013
    else:
        sample = radius * 0.45
        high = terrain.height(*_offset(centre, direction, sample))
        low = terrain.height(*_offset(centre, direction, -sample))
        limit = 0.146 if profile == "HARBOR" else 0.085
        grade = min(limit, max(-limit, (high - low) / (2 * sample)))
        height += along * grade
    height += 0.65 * value_noise(x / 25, y / 25, terrain.config.seed + 77)
    return terrain.cap(wx, wy, base + (height - base) * weight)


def _candidate_points(request, grid):
    step = max(10, grid.step * 1.5)
    rings = math.ceil(request.search_radius / step)
    yield request.near
    for i in range(1, rings + 1):
        radius = min(i * step, request.search_radius)
        count = max(8, math.ceil(math.tau * radius / step))
        for j in range(count):
            angle = j * math.tau / count + i * 0.41
            yield _offset(
                request.near, (math.cos(angle), math.sin(angle)), radius
            )


def _site_options(terrain, grid, request):
    """Rank usable shelves near the preferred centre."""
    config = request.settlement
    radius = config.effective_radius
    options = []
    styles = (*WATERSIDE, "MOUNTAIN", "INLAND")
    if request.profile != "AUTO":
        styles = (request.profile,)
    for centre in _candidate_points(request, grid):
        if terrain.wet(*centre, 7):
            continue
        if any(
            abs(c) + radius * 0.9 > s / 2
            for c, s in zip(centre, grid.size, strict=True)
        ):
            continue
        for profile in styles:
            landmark, direction = None, (0, -1)
            if profile != "INLAND":
                result = (
                    _lookout(terrain, centre, radius)
                    if profile == "MOUNTAIN"
                    else _waterfront(terrain, centre, profile, radius)
                )
                if not result:
                    continue
                direction, landmark = result
            bearing = math.atan2(direction[1], direction[0])
            site = LocalSite(
                profile,
                bearing,
                partial(_bench, terrain, centre, radius, direction, profile),
                _relative(landmark.start, centre) if landmark else (),
            )
            boundary, _ = _boundary(config, Random(config.seed), site)
            surroundings = [_offset(centre, p, 1) for p in boundary[::4]]
            if any(terrain.wet(*p, 4.0) for p in surroundings):
                continue
            if landmark and terrain.wet(*landmark.start, 3.5):
                continue
            if landmark and math.dist(centre, landmark.start) < radius * 0.71:
                continue
            step = radius * 0.45
            levels = [
                terrain.height(*_offset(centre, vector, step))
                for vector in ((1, 0), (-1, 0), (0, 1), (0, -1))
            ]
            grade = (max(levels) - min(levels)) / (2 * step)
            max_grade = 0.56 if profile == "MOUNTAIN" else 0.33
            if grade > max_grade:
                continue
            score = math.dist(centre, request.near) + grade * radius * 2
            if profile == "INLAND" and request.profile == "AUTO":
                score += radius * 1.1
            if landmark and profile in WATERSIDE:
                score += abs(math.dist(centre, landmark.start) - radius) * 0.52
            options.append((score, centre, site, landmark))
    return sorted(options, key=lambda item: item[0])


def _window(grid, centre, city, landmark):
    radius = city.config.effective_radius
    points = [
        _offset(centre, point, 1)
        for point in (
            *city.boundary,
            *(p[:2] for r in city.roads for p in r.points),
        )
    ]
    extent = radius * 1.52 * max(SITE_ASPECTS[city.site_style])
    points.extend(
        _offset(centre, vector, extent)
        for vector in ((1, 0), (-1, 0), (0, 1), (0, -1))
    )
    if landmark:
        points.extend((landmark.start, landmark.end))
    return grid.window(points, max(7.0, grid.step))


def _overlaps(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _city_dry(terrain, centre, plan):
    for road in plan.roads:
        if any(
            terrain.wet(*_offset(centre, point, 1), road.width / 2 + 0.25)
            for point in resample(tuple(p[:2] for p in road.points), 3)
        ):
            return False
    return not any(
        terrain.wet(*_offset(centre, point, 1))
        for building in plan.buildings
        for point in building.corners
    )


def choose_site(terrain, grid, request, occupied, *, rejected=()):
    reason = "no dry shelf at the requested geographic feature"
    for _, centre, local, landmark in _site_options(terrain, grid, request)[
        :28
    ]:
        if centre in rejected:
            continue
        radius = request.settlement.effective_radius
        if any(
            math.dist(centre, site.centre)
            < (radius + site.settlement.config.effective_radius) * 1.7
            for site in occupied
        ):
            reason = "too close to another settlement"
            continue
        try:
            config = replace(
                request.settlement,
                art_style=terrain.config.art_style,
                season=terrain.config.season,
            )
            plan = make_settlement(config, site=local)
            if not _city_dry(terrain, centre, plan):
                reason = "a city street or building would enter water"
                continue
            if not plan.buildings:
                reason = "no buildable frontage"
                continue
            box = _window(grid, centre, plan, landmark)
            if any(_overlaps(box, site.bounding_cells) for site in occupied):
                reason = "settlement terrain patches overlap"
                continue
            plan = replace(
                plan,
                surface_boundary=tuple(
                    _relative(point, centre) for point in grid.ring(box)
                ),
            )
            site = WorldSite(
                request.id, local.style, centre, box, plan, landmark
            )
            if landmark:
                sampler = TerrainSampler(plan)
                site = with_deck(
                    site,
                    lambda x, y, origin=centre, sample=sampler: sample.height(
                        *_relative((x, y), origin)
                    ),
                )
            return site
        except ValueError as error:
            reason = str(error)
    raise ValueError(
        f"Cannot place {request.id} ({request.profile}): {reason}. "
        "Adjust near/search_radius, the surroundings or the settlement radius."
    )


def with_deck(site, height):
    feature = site.landmark
    near = _relative(feature.start, site.centre)
    source = min(
        site.settlement.navigation["nodes"],
        key=lambda n: math.dist(n["position"][:2], near),
    )
    if math.dist(source["position"][:2], near) > 0.01:
        raise LandmarkGradeError(f"{site.id}: missing landmark road endpoint")
    start = (*feature.start, source["position"][2])
    if feature.kind == "LOOKOUT":
        stop = (*feature.end, start[2])
        return replace(site, deck_path=(start, stop))
    if feature.kind == "BRIDGE":
        stop = (*feature.end, height(*feature.end) + 0.033)
        crest = max(feature.water_level + 0.95, min(start[2], stop[2]))
        length = math.dist(feature.start, feature.end)
        ramp = min(10.5, length * 0.27)
        u = _direction(feature.start, feature.end)
        a = max(crest, start[2] + (stop[2] - start[2]) * (ramp / length))
        b = max(crest, stop[2] + (start[2] - stop[2]) * (ramp / length))
        points = (
            start,
            (*_offset(feature.start, u, ramp), a),
            (*_offset(feature.end, u, -ramp), b),
            stop,
        )
    else:
        points = (
            start,
            (*feature.end, max(start[2], feature.water_level + 0.74)),
        )
    if any(
        abs(a[2] - b[2]) / math.dist(a[:2], b[:2])
        > site.settlement.config.max_road_grade + 0.01
        for a, b in zip(points, points[1:], strict=False)
    ):
        raise LandmarkGradeError(f"{site.id}: landmark access is too steep")
    return replace(site, deck_path=points)


def world_navigation(sites):
    """Join local graphs with their walkable landmarks in world axes."""
    nodes, edges, pois, obstacles, spawns = [], [], [], [], []
    for site in sites:
        nav = site.settlement.navigation
        offset = len(nodes)

        def position(point, origin=site.centre):
            return (point[0] + origin[0], point[1] + origin[1], point[2])

        nodes.extend(
            {
                **node,
                "id": node["id"] + offset,
                "position": position(node["position"]),
                "site": site.id,
            }
            for node in nav["nodes"]
        )
        for edge in nav["edges"]:
            item = {**edge, "a": edge["a"] + offset, "b": edge["b"] + offset}
            if "path" in edge:
                item["path"] = [position(p) for p in edge["path"]]
            edges.append(item)
        pois.extend(
            {
                **p,
                "id": f"{site.id}/{p['id']}",
                "node": p["node"] + offset,
                "position": position(p["position"]),
            }
            for p in nav["points_of_interest"]
        )
        obstacles.extend(
            {
                **o,
                "id": f"{site.id}/{o['id']}",
                "position": position(o["position"]),
            }
            for o in nav.get("obstacles", ())
        )
        spawns.append(nav["spawn_node"] + offset)
        if not site.deck_path:
            continue
        source = min(
            nodes[offset:],
            key=lambda n: math.dist(n["position"], site.deck_path[0]),
        )["id"]
        for a, b in zip(site.deck_path, site.deck_path[1:], strict=False):
            target = len(nodes)
            nodes.append({"id": target, "position": b, "site": site.id})
            edges.append(
                {
                    "a": source,
                    "b": target,
                    "kind": site.landmark.kind,
                    "length": math.dist(a, b),
                    "width": site.landmark.width,
                }
            )
            source = target
        pois.append(
            {
                "id": f"{site.id}/{site.landmark.kind.lower()}",
                "kind": site.landmark.kind,
                "node": source,
                "position": site.deck_path[-1],
            }
        )
    return {
        "agent_height": 1.8,
        "agent_radius": 0.33,
        "nodes": nodes,
        "edges": edges,
        "points_of_interest": pois,
        "obstacles": obstacles,
        "spawn_node": spawns[0] if spawns else None,
        "suggested_spawns": spawns,
        "surface_conformed": bool(sites)
        and all(
            s.settlement.navigation.get("surface_conformed", False)
            for s in sites
        ),
    }


def make_world(config):
    config.validate()
    terrain = WorldTerrain(config)
    grid = Grid(config.size, config.terrain_step)
    sites = []
    for request in config.settlements:
        sites.append(choose_site(terrain, grid, request, sites))
    return WorldPlan(config, terrain, grid, tuple(sites))
