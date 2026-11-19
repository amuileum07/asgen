"""Seeded street furniture and grass sites with pedestrian clearance."""

import math
import random
from dataclasses import dataclass
from itertools import product

from terrain_rules import (
    TerrainSampler,
    boundary_distance,
    inside_polygon,
    rectangle_distance,
    segment_projection,
    smoothstep,
    terrain_outline,
    value_noise,
)


@dataclass(frozen=True)
class CivicAsset:
    id: str
    kind: str
    position: tuple
    heading: float
    radius: float
    scale: float
    size: tuple
    variant: str
    parameters: dict


class CivicPlanner:
    def __init__(self, plan):
        self.plan = plan
        self.sampler = TerrainSampler(plan)
        self.assets = []
        self.rng = random.Random(f"{plan.config.seed}:civic-style")
        self.family = self.rng.choice(("OCTAGONAL", "ROUND", "FACETED"))
        self.segments = {"OCTAGONAL": 8, "ROUND": 20, "FACETED": 12}[
            self.family
        ]
        self.roof = self.rng.choice(("GABLE", "PYRAMID_4"))
        self.arms = self.rng.choice((1, 1, 2))
        self.tiers = self.rng.choice((2, 3))

    def clear(self, point, radius, *, road_gap=0.55):
        plan = self.plan
        if not inside_polygon(point, plan.boundary):
            return False
        if boundary_distance(point, plan.boundary) < radius + 1.1:
            return False
        if plan.castle and math.dist(point, plan.castle.centre[:2]) < (
            plan.castle.radius + radius + 2
        ):
            return False
        for i in self.sampler.pads.query(point, radius + 8):
            b = plan.buildings[i]
            if (
                rectangle_distance(
                    point, b.position, b.width + 0.4, b.depth + 0.4, b.heading
                )
                < radius + 0.35
            ):
                return False
        for i in self.sampler.roads.query(point, radius + 7):
            a, b, width, _ = self.sampler.segments[i]
            if (
                segment_projection(point, a, b)[0]
                < width / 2 + radius + road_gap
            ):
                return False
        return not any(
            math.dist(point, a.position[:2]) < radius + a.radius + 0.8
            for a in self.assets
        )

    def add(self, kind, point, radius, scale, heading=0):
        if not self.clear(point, radius):
            return False
        x, y = point
        z = self.sampler.height(x, y)
        if kind != "STREET_LAMP":
            samples = [
                self.sampler.height(
                    x + radius * math.cos(i * math.tau / 8),
                    y + radius * math.sin(i * math.tau / 8),
                )
                for i in range(8)
            ]
            if max(samples) - min(samples) > 0.14 * scale:
                return False
        size = {
            "WELL": (3.4, 2.9, 3.15),
            "FOUNTAIN": (3.4, 3.4, 3.05),
            "STREET_LAMP": (2.6 if self.arms == 2 else 1.6, 0.7, 4.05),
            "STATUE_ANCHOR": (1.8, 1.8, 3.2),
        }[kind]
        self.assets.append(
            CivicAsset(
                f"civic_{len(self.assets):04d}",
                kind,
                (x, y, z),
                heading,
                radius,
                scale,
                tuple(v * scale for v in size),
                self.family,
                {
                    "segments": self.segments,
                    "roof": self.roof,
                    "arms": self.arms,
                    "tiers": self.tiers,
                    "lantern_sides": 4 if self.family == "OCTAGONAL" else 6,
                },
            )
        )
        return True

    def square_asset(self, kind, market, radius, scale):
        phase = self.rng.uniform(0, math.tau)
        for ring in (0.35, 0.58, 0.76, 1.05, 1.35, 1.65):
            for i in range(32):
                angle = phase + i * math.tau / 32
                point = tuple(
                    market.centre[j] + ring * market.radius * f(angle)
                    for j, f in enumerate((math.cos, math.sin))
                )
                if self.add(kind, point, radius, scale, angle):
                    return True
        return False


def make_civic_assets(plan):
    if not plan.config.civic:
        return ()
    planner = CivicPlanner(plan)
    large = plan.config.scale in ("CITY", "CAPITAL")
    if large:
        count = 2 if plan.config.scale == "CAPITAL" else 1
        for market in plan.markets[:count]:
            scale = (1.22 if count == 2 else 1.0) * planner.rng.uniform(
                0.95, 1.04
            )
            planner.square_asset("FOUNTAIN", market, 1.7 * scale, scale)
    well_count = 2 if plan.config.scale == "CAPITAL" else 1
    for market in plan.markets[-well_count:]:
        scale = planner.rng.uniform(0.93, 1.05)
        planner.square_asset("WELL", market, 1.75 * scale, scale)
    if large:
        for market in plan.markets[
            : 2 if plan.config.scale == "CAPITAL" else 1
        ]:
            planner.square_asset("STATUE_ANCHOR", market, 1.3, 1.0)
        spacing = 13 if plan.config.scale == "CAPITAL" else 18
        for road in plan.roads:
            if road.kind not in ("PRIMARY", "SECONDARY"):
                continue
            length = sum(
                math.dist(a[:2], b[:2])
                for a, b in zip(road.points, road.points[1:], strict=False)
            )
            wanted, travelled, number = min(spacing * 0.30, length * 0.5), 0, 0
            for a, b in zip(road.points, road.points[1:], strict=False):
                segment = math.dist(a[:2], b[:2])
                while wanted < travelled + segment and wanted < length - 1:
                    t = (wanted - travelled) / segment
                    dx, dy = (b[0] - a[0]) / segment, (b[1] - a[1]) / segment
                    nx, ny = -dy, dx
                    for side in (1, -1) if number % 2 else (-1, 1):
                        scale = planner.rng.uniform(0.96, 1.04)
                        radius = (1.05 if planner.arms == 2 else 0.65) * scale
                        distance = road.width / 2 + radius + 0.85
                        p = (
                            a[0] + (b[0] - a[0]) * t + nx * side * distance,
                            a[1] + (b[1] - a[1]) * t + ny * side * distance,
                        )
                        if any(
                            math.dist(p, v.position[:2]) < spacing * 0.65
                            for v in planner.assets
                            if v.kind == "STREET_LAMP"
                        ):
                            continue
                        if planner.add(
                            "STREET_LAMP",
                            p,
                            radius,
                            scale,
                            math.atan2(ny * side, nx * side),
                        ):
                            break
                    number += 1
                    wanted += spacing
                travelled += segment
    return tuple(planner.assets)


def civic_navigation(navigation, assets):
    pois = list(navigation["points_of_interest"])
    for asset in assets:
        if asset.kind == "STREET_LAMP":
            continue
        nearest = min(
            navigation["nodes"],
            key=lambda n: math.dist(n["position"][:2], asset.position[:2]),
        )["id"]
        pois.append(
            {
                "id": asset.id,
                "kind": asset.kind,
                "node": nearest,
                "position": asset.position,
            }
        )
    return {
        **navigation,
        "points_of_interest": pois,
        "obstacles": [
            {
                "id": a.id,
                "kind": a.kind,
                "position": a.position,
                "radius": a.radius,
                "height": a.size[2],
                "reserved": a.kind == "STATUE_ANCHOR",
            }
            for a in assets
        ],
    }


def grass_cells(bounds, spacing):
    """Use a common lattice so adjoining sampling areas share cells."""
    left, bottom, right, top = bounds
    return product(
        range(math.floor(left / spacing), math.ceil(right / spacing)),
        range(math.floor(bottom / spacing), math.ceil(top / spacing)),
    )


def meadow_growth(x, y, seed):
    """Blend broad growth bands with shorter changes in exposure."""
    broad = value_noise(x / 24, y / 24, seed + 751)
    streak = value_noise(
        (0.8 * x + 0.6 * y) / 14, (0.8 * y - 0.6 * x) / 5, seed + 752
    )
    return smoothstep(-0.58, 0.68, broad * 0.68 + streak * 0.32)


def grass_samples(cells, spacing, seed):
    rng = random.Random()
    prefix = f"{seed}:meadow:{spacing:.6f}"
    for i, j in cells:
        rng.seed(f"{prefix}:{i}:{j}")
        x = (i + rng.uniform(0.06, 0.94)) * spacing
        y = (j + rng.uniform(0.06, 0.94)) * spacing
        growth = meadow_growth(x, y, seed)
        yield x, y, growth, rng.uniform(0, math.tau), rng.random()


def grass_sites(plan):
    if not plan.config.grass or not plan.config.grass_density:
        return
    outline = terrain_outline(plan)
    left, right = min(p[0] for p in outline), max(p[0] for p in outline)
    bottom, top = min(p[1] for p in outline), max(p[1] for p in outline)
    density = plan.config.grass_density
    seed = plan.config.seed
    sampler = TerrainSampler(plan)
    road_reach = max((s[2] / 2 for s in sampler.segments), default=0) + 6.0

    def _clear(p):
        if not inside_polygon(p, outline):
            return False
        if (
            plan.castle
            and math.dist(p, plan.castle.centre[:2]) < plan.castle.radius + 1
        ):
            return False
        if any(
            math.dist(p, m.centre[:2]) < m.radius + 0.5 for m in plan.markets
        ):
            return False
        if any(
            math.dist(p, a.position[:2]) < a.radius + 0.4
            for a in plan.civic_assets
        ):
            return False
        if plan.has_walls and boundary_distance(p, plan.boundary) < 1.1:
            return False
        return not any(
            rectangle_distance(
                p, b.position, b.width + 0.4, b.depth + 0.4, b.heading
            )
            < 0.4
            for i in sampler.pads.query(p, 8)
            for b in (plan.buildings[i],)
        )

    def road_clearance(p):
        return min(
            (
                segment_projection(p, a, b)[0] - width / 2
                for i in sampler.roads.query(p, road_reach)
                for a, b, width, _ in (sampler.segments[i],)
            ),
            default=math.inf,
        )

    area = (right - left) * (top - bottom)
    spacing = max(0.82, math.sqrt(area / 24_000)) / math.sqrt(density)
    cells = grass_cells((left, bottom, right, top), spacing)
    for x, y, growth, angle, chance in grass_samples(cells, spacing, seed):
        if (
            chance < 0.86 + growth * 0.13
            and road_clearance((x, y)) >= 0.58
            and _clear((x, y))
        ):
            yield x, y, 0.16 + growth * 0.15, angle

    # Refine grassy verges along roads and access lanes.
    length = sum(math.dist(a[:2], b[:2]) for a, b, _, _ in sampler.segments)
    spacing = max(0.40, math.sqrt(length / 2500)) / math.sqrt(density)
    verge = set()
    for a, b, width, _ in sampler.segments:
        offset = width / 2 + 5.8
        verge.update(
            grass_cells(
                (
                    min(a[0], b[0]) - offset,
                    min(a[1], b[1]) - offset,
                    max(a[0], b[0]) + offset,
                    max(a[1], b[1]) + offset,
                ),
                spacing,
            )
        )
    for x, y, growth, angle, chance in grass_samples(
        sorted(verge), spacing, seed
    ):
        clearance = road_clearance((x, y))
        edge = 2.8 + growth * 2.8
        if (
            0.58 <= clearance < edge
            and chance < 1 - smoothstep(edge - 1.6, edge, clearance)
            and _clear((x, y))
        ):
            height = 0.17 + (0.22 + growth * 0.28) * smoothstep(
                0.58, 2.8, clearance
            )
            yield x, y, height, angle
