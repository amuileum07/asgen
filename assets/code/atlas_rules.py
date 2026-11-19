"""Deterministic regional terrain, climate, routes and tile plans."""

import heapq
import json
import math
import random
from functools import lru_cache
from hashlib import blake2s
from itertools import pairwise
from pathlib import Path

from terrain_rules import (
    inside_polygon,
    segment_projection,
    smoothstep,
    value_noise,
)

TILE = 256
DISTRICT_EDGE = {"CAPITAL": -131, "CITY": -82, "VILLAGE": -42}
SITE_DEFAULTS = {
    "CAPITAL": {
        "search_radius_m": 480,
        "extent_m": (560, 450),
        "plaza_m": (62, 42),
    },
    "CITY": {
        "search_radius_m": 370,
        "extent_m": (310, 244),
        "plaza_m": (42, 30),
    },
    "VILLAGE": {
        "search_radius_m": 280,
        "extent_m": (147, 120),
        "plaza_m": (17, 14),
    },
}
ENVIRONMENTS = {
    "COAST": (12, 810, 0.47, "8ca371"),
    "FOREST": (10, 1400, 0.79, "527a56"),
    "PLAIN": (13, 700, 0.52, "87a561"),
    "MOUNTAIN": (8, 990, 0.40, "898c76"),
    "SNOW": (1, 840, 0.26, "d8e4e6"),
    "DESERT": (22, 120, 0.13, "c6a479"),
    "MARSH": (15, 980, 0.94, "708d64"),
    "MEDITERRANEAN": (17, 600, 0.38, "a4aa71"),
}
DEFAULT_THEME = {
    "id": "default",
    "name": "Default",
    "weather": "CLEAR",
    "trade": "BAKER",
    "spine_uv": ((0.25, 0.50), (0.75, 0.50)),
    "blend_m": 450,
}
DEFAULT_TERRAIN = {
    "base_elevation_m": 24.0,
    "north_slope_m": 0.0,
    "east_slope_m": 0.0,
    "grain_m": 18.0,
    "ledge_m": 4.0,
    "coast": None,
    "ridges": (),
    "peaks": (),
    "plateaus": (),
    "basins": (),
    "dunes": (),
}
DEFAULT_CLIMATE = {
    "temp_offset_c": 1.8,
    "lapse_base_m": 120.0,
    "lapse_rate": 0.0058,
    "rain_shadow": None,
    "windward": None,
}
COAST_SIDES = ("WEST", "EAST", "NORTH", "SOUTH")
LIST_MERGES = (
    ("regions", "region_overrides"),
    ("features", "feature_overrides"),
    ("realms", "realm_overrides"),
    ("themes", "theme_overrides"),
    ("sites", "site_overrides"),
    ("dungeons", "dungeon_overrides"),
)


def stable_seed(*parts):
    return int.from_bytes(
        blake2s(repr(parts).encode(), digest_size=4).digest(), "little"
    )


def default_focus(plan):
    """Return the default settlement ID to frame for an atlas plan."""
    sites = plan.get("sites", ())
    for site in sites:
        if site.get("grand_capital"):
            return site["id"]
    for site in sites:
        if site.get("rank") == "CAPITAL":
            return site["id"]
    return sites[0]["id"] if sites else None


def _rows(defaults, overrides):
    rows = {row["id"]: dict(row) for row in defaults}
    seen = set()
    for row in overrides:
        name = row.get("id")
        if (
            not isinstance(name, str)
            or not name
            or any(
                not (c.isascii() and (c.isalnum() or c == "_")) for c in name
            )
            or name in seen
        ):
            raise ValueError(f"Invalid or repeated blueprint ID: {name!r}")
        seen.add(name)
        if row.get("remove"):
            rows.pop(name, None)
            continue
        rows[name] = {**rows.get(name, {}), **row}
    for row in rows.values():
        if row.get("placement", "GUIDED") not in ("FIXED", "GUIDED", "AUTO"):
            raise ValueError(f"{row['id']}: invalid placement")
    return tuple(rows.values())


def _merge_mapping(base, override):
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_mapping(merged[key], value)
        else:
            merged[key] = value
    return merged


def resolve_blueprint(blueprint, base_dir=None, _seen=None):
    """Resolve optional JSON file inheritance via ``extends``."""
    if "extends" not in blueprint or not blueprint["extends"]:
        return dict(blueprint)
    target = blueprint["extends"]
    if not isinstance(target, str):
        raise ValueError("Blueprint extends must be a JSON file path")
    candidates = []
    rel = Path(target)
    if rel.is_absolute():
        candidates.append(rel)
    else:
        if base_dir is not None:
            candidates.append(Path(base_dir) / rel)
            if rel.suffix != ".json":
                candidates.append(Path(base_dir) / f"{target}.json")
        presets = Path(__file__).resolve().with_name("presets")
        candidates.append(presets / rel)
        if rel.suffix != ".json":
            candidates.append(presets / f"{target}.json")
    path = next((p.resolve() for p in candidates if p.is_file()), None)
    if path is None:
        raise ValueError(f"Unknown blueprint base: {target!r}")
    seen = set() if _seen is None else set(_seen)
    if path in seen:
        raise ValueError(f"Cyclic blueprint extends: {path}")
    seen.add(path)
    parent_raw = json.loads(path.read_text(encoding="utf-8-sig"))
    parent = resolve_blueprint(parent_raw, base_dir=path.parent, _seen=seen)
    merged = dict(parent)
    for key, value in blueprint.items():
        if key == "extends":
            continue
        if key in ("terrain", "climate") and isinstance(value, dict):
            base_block = merged.get(key)
            merged[key] = (
                _merge_mapping(base_block, value)
                if isinstance(base_block, dict)
                else dict(value)
            )
        elif key.endswith("_overrides"):
            merged[key] = [*merged.get(key, ()), *value]
        else:
            merged[key] = value
    return merged


class Atlas:
    def __init__(self, blueprint, seed=None, base_dir=None):
        blueprint = resolve_blueprint(blueprint, base_dir=base_dir)
        if blueprint.get("blueprint_version") != 2:
            raise ValueError("Expected blueprint_version 2")
        self.title = str(blueprint.get("title", "Procedural Atlas"))
        self.size = tuple(blueprint.get("size_m", (4096, 4096)))
        if len(self.size) != 2 or any(
            type(n) is not int or n % TILE or not 2048 <= n <= 32768
            for n in self.size
        ):
            raise ValueError(
                "Atlas dimensions must be 2048–32768m, on 256m tiles"
            )
        self.seed = blueprint.get("seed", 42) if seed is None else seed
        if type(self.seed) is not int or not 0 <= self.seed <= 2_000_000_000:
            raise ValueError("Invalid atlas seed")
        self.shape = tuple(n // TILE for n in self.size)
        self.origin = tuple(-n / 2 for n in self.size)
        self.blueprint = blueprint
        self.terrain_cfg = _merge_mapping(
            DEFAULT_TERRAIN, blueprint.get("terrain") or {}
        )
        self.climate_cfg = _merge_mapping(
            DEFAULT_CLIMATE, blueprint.get("climate") or {}
        )
        self._validate_terrain()

        self.regions = self._locate(
            _rows(
                blueprint.get("regions", ()),
                blueprint.get("region_overrides", ()),
            )
        )
        if not self.regions:
            raise ValueError("Atlas requires at least one region")
        self.features = self._locate(
            _rows(
                blueprint.get("features", ()),
                blueprint.get("feature_overrides", ()),
            )
        )
        self.water_features = tuple(
            f for f in self.features if f["kind"] != "FOG_BASIN"
        )
        self.fog_basins = tuple(
            f for f in self.features if f["kind"] == "FOG_BASIN"
        )
        raw_themes = _rows(
            blueprint.get("themes", ()),
            blueprint.get("theme_overrides", ()),
        )
        if not raw_themes:
            raw_themes = (dict(DEFAULT_THEME),)
        default_theme_id = raw_themes[0]["id"]
        raw_realms = _rows(
            blueprint.get("realms", ()),
            blueprint.get("realm_overrides", ()),
        )
        if not raw_realms:
            raise ValueError("Atlas requires at least one realm")
        self.realms = self._locate(
            tuple(
                {
                    "name": row["id"],
                    "target_land_fraction": 1 / len(raw_realms),
                    "theme": default_theme_id,
                    **row,
                }
                for row in raw_realms
            )
        )
        self.themes = self._locate(
            tuple(self._prepare_theme(row, self.realms) for row in raw_themes)
        )
        self.site_specs = _rows(
            blueprint.get("sites", ()),
            blueprint.get("site_overrides", ()),
        )
        self.dungeon_specs = _rows(
            blueprint.get("dungeons", ()),
            blueprint.get("dungeon_overrides", ()),
        )
        self.seasonal_links = tuple(blueprint.get("seasonal_links", ()))

        self.base_height = lru_cache(maxsize=131072)(self.base_height)
        self.water_at = lru_cache(maxsize=131072)(self.water_at)
        self.terrain = lru_cache(maxsize=131072)(self.terrain)
        self._validate_features()

    def _prepare_theme(self, row, realms):
        item = {
            "name": row["id"],
            "weather": "CLEAR",
            "trade": "BAKER",
            "blend_m": 450,
            **row,
        }
        if "spine_uv" not in item:
            members = [
                r["centre_uv"]
                for r in realms
                if r["theme"] == item["id"] and "centre_uv" in r
            ]
            if len(members) >= 2:
                a, b = members[0], members[-1]
                mid = ((a[0] + b[0]) / 2 - 0.025, (a[1] + b[1]) / 2)
                item["spine_uv"] = (a, mid, b)
            elif len(members) == 1:
                u, v = members[0]
                item["spine_uv"] = (
                    (max(0.0, u - 0.033), min(1.0, v + 0.033)),
                    (u, v),
                    (min(1.0, u + 0.044), max(0.0, v - 0.034)),
                )
            else:
                item["spine_uv"] = ((0.25, 0.50), (0.75, 0.50))
        return item

    def _validate_terrain(self):
        coast = self.terrain_cfg.get("coast")
        if coast is not None:
            side = coast.get("side", "WEST")
            if side not in COAST_SIDES:
                raise ValueError(f"Invalid coast side: {side!r}")
            pos = coast.get("position_uv", 0.10)
            if not 0.0 <= pos <= 1.0:
                raise ValueError("Coast position_uv must be in [0, 1]")

    def _locate(self, rows):
        located = []
        for row in rows:
            row = dict(row)
            for key in ("centre", "near"):
                if key + "_uv" in row:
                    row[key] = self.xy(row[key + "_uv"])
            for key in ("axis", "spine", "polygon"):
                if key + "_uv" in row:
                    row[key] = tuple(self.xy(p) for p in row[key + "_uv"])
            if "radii_m" in row:
                radii = row["radii_m"]
                if len(radii) != 2 or any(
                    not math.isfinite(r) or r <= 1 for r in radii
                ):
                    raise ValueError(f"{row['id']}: invalid radii")
            line = row.get("axis") or row.get("spine")
            if line:
                border = row.get("width_m", 0) * 1.7 + row.get("blend_m", 0)
                row["bounds"] = (
                    min(p[0] for p in line) - border,
                    min(p[1] for p in line) - border,
                    max(p[0] for p in line) + border,
                    max(p[1] for p in line) + border,
                )
            located.append(row)
        return tuple(located)

    def _validate_features(self):
        waters = {f["id"]: f for f in self.water_features}
        themes = {t["id"] for t in self.themes}
        for row in self.regions:
            if row.get("biome") not in ENVIRONMENTS:
                raise ValueError(f"{row['id']}: invalid biome")
            if "centre" not in row or "radii_m" not in row:
                raise ValueError(
                    f"{row['id']}: region centre or radii missing"
                )
        for row in self.realms:
            if row.get("biome") not in ENVIRONMENTS:
                raise ValueError(f"{row['id']}: invalid realm biome")
            if row.get("theme") not in themes:
                raise ValueError(f"{row['id']}: unknown theme")
            if "centre" not in row:
                raise ValueError(f"{row['id']}: realm centre_uv is missing")
        for row in self.water_features:
            kind = row.get("kind")
            if kind not in (
                "SEA",
                "RIVER",
                "CANYON",
                "GLACIAL_TROUGH",
                "TARN",
                "OXBOW",
                "TERMINAL",
                "SPRING",
            ):
                raise ValueError(f"{row['id']}: invalid water type")
            if kind != "SEA" and not (
                row.get("axis")
                and row.get("width_m", 0) > 0
                or row.get("centre")
                and row.get("radii_m")
            ):
                raise ValueError(f"{row['id']}: water shape is missing")
            levels = row.get("levels_m")
            if levels is not None and (
                len(levels) != len(row.get("axis", ()))
                or any(a < b for a, b in pairwise(levels))
            ):
                raise ValueError(f"{row['id']}: water must descend downstream")
            if not levels and not math.isfinite(row.get("level_m", math.nan)):
                raise ValueError(f"{row['id']}: water level is missing")
            if "outlet_id" in row and row["outlet_id"] not in waters:
                raise ValueError(f"{row['id']}: unknown outlet")
            if row.get("outlet_id") == row["id"]:
                raise ValueError(f"{row['id']}: outlet points to itself")

    def xy(self, uv):
        if len(uv) != 2 or any(not 0 <= u <= 1 for u in uv):
            raise ValueError(f"Invalid normalized map coordinate: {uv!r}")
        return tuple((u - 0.5) * n for u, n in zip(uv, self.size, strict=True))

    def uv(self, x, y):
        return x / self.size[0] + 0.5, y / self.size[1] + 0.5

    def cell(self, x, y):
        return tuple(
            max(0, min(n - 1, math.floor((p - o) / TILE)))
            for p, o, n in zip((x, y), self.origin, self.shape, strict=True)
        )

    def corner(self, i, j):
        return self.origin[0] + i * TILE, self.origin[1] + j * TILE

    def centre(self, i, j):
        x, y = self.corner(i, j)
        return x + TILE / 2, y + TILE / 2

    def coast_inland(self, x, y):
        """Signed metres inland from the configured sea edge."""
        coast = self.terrain_cfg.get("coast")
        if coast is None:
            return math.inf
        u, v = self.uv(x, y)
        side = coast.get("side", "WEST")
        along = v if side in ("WEST", "EAST") else u
        pos = coast.get("position_uv", 0.10)
        for amp, freq in coast.get("waves", ()):
            pos += amp * math.sin(along * freq)
        for bay in coast.get("bays", ()):
            pos += bay["depth_uv"] * math.exp(
                -(((along - bay["centre"]) / bay["width"]) ** 2)
            )
        if side == "WEST":
            return x - (pos - 0.5) * self.size[0]
        if side == "EAST":
            return (pos - 0.5) * self.size[0] - x
        if side == "SOUTH":
            return y - (pos - 0.5) * self.size[1]
        return (pos - 0.5) * self.size[1] - y

    def base_height(self, x, y):
        cfg = self.terrain_cfg
        u, v = self.uv(x, y)
        coast = cfg.get("coast")
        inland = self.coast_inland(x, y)
        if coast is not None and inland < 0:
            return max(
                -coast.get("max_depth_m", 55.0),
                inland * coast.get("shelf_slope", 0.093),
            )
        grain = value_noise(x / 740, y / 740, self.seed + 19)
        ledges = value_noise(x / 190, y / 190, self.seed + 185)
        depth = (
            cfg.get("base_elevation_m", 24.0)
            + cfg.get("north_slope_m", 0.0) * v
            + cfg.get("east_slope_m", 0.0) * u
        )
        grain_scale = cfg.get("grain_m", 18.0)
        ledge_scale = cfg.get("ledge_m", 4.0)

        for ridge in cfg.get("ridges", ()):
            if "axis_uv" in ridge:
                pts = ridge["axis_uv"]
                dist = min(
                    segment_projection((u, v), a, b)[0]
                    for a, b in pairwise(pts)
                )
                width = ridge.get("width_uv", 0.08)
                weight = math.exp(-((dist / width) ** 2))
            else:
                axis = ridge["axis_u"] + (
                    v - ridge.get("ref_v", 0.5)
                ) * ridge.get("slope_u", 0.0)
                width = ridge.get("width_uv", 0.08) + (1 - v) * ridge.get(
                    "south_width_add_uv", 0.0
                )
                weight = math.exp(-(((u - axis) / width) ** 2))
            height = ridge.get("height_m", 180.0)
            if "north_height_m" in ridge:
                v0, v1 = ridge.get("north_ramp_v", (0.4, 0.9))
                height += ridge["north_height_m"] * smoothstep(v0, v1, v)
            depth += height * weight
            grain_scale += ridge.get("grain_m", 0.0) * weight
            ledge_scale += ridge.get("ledge_m", 0.0) * weight

        for peak in cfg.get("peaks", ()):
            cu, cv = peak["centre_uv"]
            ru, rv = peak["radii_uv"]
            weight = math.exp(-(((u - cu) / ru) ** 2 + ((v - cv) / rv) ** 2))
            depth += peak["height_m"] * weight
            grain_scale += peak.get("grain_m", 0.0) * weight
            ledge_scale += peak.get("ledge_m", 0.0) * weight

        for plateau in cfg.get("plateaus", ()):
            if "centre_uv" in plateau:
                cu, cv = plateau["centre_uv"]
                ru, rv = plateau["radii_uv"]
                weight = math.exp(
                    -(((u - cu) / ru) ** 2 + ((v - cv) / rv) ** 2)
                )
            else:
                weight = math.exp(
                    -(((u - plateau["centre_u"]) / plateau["width_uv"]) ** 2)
                )
            if "ramp_u" in plateau:
                u0, u1 = plateau["ramp_u"]
                weight *= smoothstep(u0, u1, u)
            depth += plateau["height_m"] * weight

        depth += grain * grain_scale + ledges * ledge_scale

        for basin in cfg.get("basins", ()):
            cu, cv = basin["centre_uv"]
            ru, rv = basin["radii_uv"]
            weight = math.exp(-(((u - cu) / ru) ** 2 + ((v - cv) / rv) ** 2))
            if basin.get("mode", "LOWER") == "FLATTEN":
                strength = basin.get("strength", 0.8)
                floor = basin.get("floor_m", 10.0)
                depth = depth * (1 - weight * strength) + weight * floor
            else:
                drop = basin.get("drop_m", 20.0)
                ledge_drop = basin.get("ledge_drop_m", 0.0)
                depth -= weight * (drop + ledges * ledge_drop)

        for dune in cfg.get("dunes", ()):
            u0, u1 = dune["start_u"], dune["end_u"]
            dist = (u - u0) * self.size[0]
            skew = dune.get("skew", 0.27)
            wave = dune.get("wavelength_m", 57.0)
            amp = dune.get("amplitude_m", 7.0)
            depth += smoothstep(u0, u1, u) * (
                math.sin((dist + y * skew) / wave + grain * 0.8) * amp
            )

        if coast is None:
            return max(0.05, depth)
        blend = smoothstep(0, coast.get("transition_m", 760.0), inland)
        return max(0.05, depth * blend + inland * 0.003 * (1 - blend))

    def water_shape(self, feature, x, y):
        kind = feature.get("kind")
        if kind == "SEA":
            inland = self.coast_inland(x, y)
            if math.isinf(inland):
                return math.inf, feature["level_m"]
            return inland / 32 + 1, feature["level_m"]
        if "bounds" in feature:
            left, bottom, right, top = feature["bounds"]
            if not left <= x <= right or not bottom <= y <= top:
                return math.inf, 0
        if "axis" in feature:
            distance, t, i = min(
                (dist, amount, i)
                for i, (a, b) in enumerate(pairwise(feature["axis"]))
                for dist, amount, _ in (segment_projection((x, y), a, b),)
            )
            width = feature["width_m"] / 2
            width *= 1 + 0.18 * value_noise(x / 137, y / 137, self.seed + 56)
            if levels := feature.get("levels_m"):
                level = levels[i] + (levels[i + 1] - levels[i]) * t
            else:
                level = feature["level_m"]
            radius = distance / width
            if kind == "GLACIAL_TROUGH":
                ix, iy = feature["axis"][len(feature["axis"]) // 2]
                island = math.hypot((x - ix - 60) / 103, (y - iy + 47) / 64)
                radius = max(radius, 1.29 - island * 0.84)
            return radius, level
        cx, cy = feature["centre"]
        rx, ry = feature["radii_m"]
        if abs(x - cx) > max(rx, ry) * 1.6 or abs(y - cy) > max(rx, ry) * 1.6:
            return math.inf, 0
        heading = math.radians(feature.get("heading_deg", 0))
        co, si = math.cos(heading), math.sin(heading)
        u = ((x - cx) * co + (y - cy) * si) / rx
        v = ((y - cy) * co - (x - cx) * si) / ry
        radius = math.hypot(u, v)
        ripple = value_noise(u * 2.3, v * 2.3, self.seed + 778) * 0.12
        if kind == "OXBOW":
            radius = max(radius, 1.5 - math.hypot(u + 0.15, v - 0.30) * 0.9)
        return radius + ripple, feature.get("level_m", 0)

    def water_at(self, x, y):
        hits = []
        for feature in self.water_features:
            radius, level = self.water_shape(feature, x, y)
            if radius < 1 and feature["kind"] != "CANYON":
                hits.append((level, feature["id"], feature["kind"]))
        return min(hits, default=None)

    def potential_water(self, x, y):
        if wet := self.water_at(x, y):
            return wet
        for feature in self.water_features:
            if feature["kind"] != "CANYON":
                continue
            radius, level = self.water_shape(feature, x, y)
            if radius < 0.26 and self.terrain(x, y) < level + 2.2:
                return level + 2.2, feature["id"], "CANYON"
        return None

    def region_weights(self, x, y):
        values = []
        fuzz = value_noise(x / 405, y / 405, self.seed + 222) * 0.14
        for row in self.regions:
            cx, cy = row["centre"]
            a = math.radians(row.get("heading_deg", 0))
            u = (x - cx) * math.cos(a) + (y - cy) * math.sin(a)
            v = (y - cy) * math.cos(a) - (x - cx) * math.sin(a)
            rx, ry = row["radii_m"]
            blend = row.get("blend_m", 450) / min(rx, ry)
            dist = max(0.04, math.hypot(u / rx, v / ry) + fuzz)
            weight = 1 / ((dist + max(0.04, blend) + 0.38) ** 5)
            if (polygon := row.get("polygon")) and inside_polygon(
                (x, y), polygon
            ):
                weight *= 10
            values.append((weight, row["biome"], dist, row))
        return sorted(values, key=lambda item: (-item[0], item[3]["id"]))

    def terrain(self, x, y):
        z = self.base_height(x, y)
        for feature in self.water_features:
            radius, level = self.water_shape(feature, x, y)
            if radius > 1.46 or feature["kind"] == "SEA":
                continue
            depth = feature["depth_m"]
            shore = max(0.0, 1 - radius)
            if feature["kind"] == "CANYON":
                floor = level + depth * smoothstep(0.18, 1.05, radius)
                floor += math.sin((z + radius * 22) * 0.17) * 4 * shore
                z = min(
                    z, z + (floor - z) * (1 - smoothstep(1.0, 1.46, radius))
                )
            elif radius <= 1:
                z = level - depth * (0.035 + 0.965 * shore**0.65)
            else:
                z += (max(level + 0.12, z) - z) * (
                    1 - smoothstep(1, 1.46, radius)
                )
        for row in self.regions:
            cap = row.get("max_elevation_m")
            if cap is not None:
                radius, _ = self.water_shape(row, x, y)
                z -= max(0, z - cap) * (1 - smoothstep(1, 1.22, radius))
        return z

    def climate(self, x, y, z):
        ranked = self.region_weights(x, y)[:3]
        total = sum(w for w, *_ in ranked)
        weights = [(biome, w / total) for w, biome, *_ in ranked]
        u, v = self.uv(x, y)
        base = sum(ENVIRONMENTS[b][0] * w for b, w in weights)
        rainfall = sum(ENVIRONMENTS[b][1] * w for b, w in weights)
        reserve = sum(ENVIRONMENTS[b][2] * w for b, w in weights)
        cfg = self.climate_cfg
        lapse = max(0, z - cfg.get("lapse_base_m", 120.0)) * cfg.get(
            "lapse_rate", 0.0058
        )
        median = base + cfg.get("temp_offset_c", 1.8) - lapse
        coast_bonus = 1.0
        if shadow := cfg.get("rain_shadow"):
            coast_bonus = (
                1
                - smoothstep(shadow["start_u"], shadow["end_u"], u)
                * shadow["drop"]
            )
        windward = 1.0
        if wind := cfg.get("windward"):
            windward = (
                1
                + math.exp(-(((u - wind["centre_u"]) / wind["width_u"]) ** 2))
                * wind["boost"]
            )
        season_bias = dict(weights).get("MEDITERRANEAN", 0) * 0.64
        temperatures, rain, snow, evaporation = [], [], [], []
        for month in range(12):
            summer = -math.cos(month * math.tau / 12)
            temp = median + (5.8 + v * 5.2 + u * 2) * summer
            mm = (
                rainfall
                / 12
                * coast_bonus
                * windward
                * (1 - season_bias * summer)
            )
            temperatures.append(round(temp, 2))
            rain.append(round(mm, 2))
            snow.append(round(mm * (1 - smoothstep(-1, 2.5, temp)), 2))
            evaporation.append(
                round(max(1, 19 + temp * 2.9) * (1 + 0.13 * summer), 2)
            )
        wet = self.water_at(x, y)
        lowland = dict(weights).get("MARSH", 0)
        return {
            "biome": weights[0][0],
            "weights": weights,
            "monthly_c": temperatures,
            "monthly_mm": rain,
            "snow_mm": snow,
            "evap_mm": evaporation,
            "retention": round(reserve, 3),
            "groundwater_m": round(
                max(0.16, 3.3 - 2.8 * reserve - lowland * 0.65), 2
            ),
            "flood_days": round(lowland * (49 if z < 37 else 17)),
            "sun": round(
                0.8 + value_noise(x / 690, y / 690, self.seed + 16) * 0.18, 3
            ),
            "exposure": round(0.35 + smoothstep(200, 1400, z) * 0.55, 3),
            "water": wet[1] if wet else "",
        }

    def theme_at(self, x, y):
        scores = []
        for theme in self.themes:
            distance = min(
                segment_projection((x, y), a, b)[0]
                for a, b in pairwise(theme["spine"])
            )
            scores.append((distance / (theme["blend_m"] + 470), theme["id"]))
        scores.sort()
        if len(scores) == 1:
            return scores[0][1], scores[0][1], 1.0
        a, b = scores[:2]
        blend = 0.52 + 0.48 * smoothstep(0, 1.3, b[0] - a[0])
        return a[1], b[1], round(blend, 3)

    def owner(self, x, y):
        noise = value_noise(x / 1040, y / 1040, self.seed + 861)
        ranking = []
        for realm in self.realms:
            if (polygon := realm.get("polygon")) and inside_polygon(
                (x, y), polygon
            ):
                return realm["id"]
            distance = math.dist((x, y), realm["centre"])
            cx, cy = realm["centre"]
            slope = abs(self.terrain(x, y) - self.terrain(cx, cy))
            fraction = max(0.025, realm["target_land_fraction"])
            score = (distance + slope * 3) / math.sqrt(fraction)
            ranking.append(
                (
                    score + noise * 154 * stable_seed(realm["id"]) / 2**32,
                    realm["id"],
                )
            )
        return min(ranking)[1]


def _candidates(near, radius, seed):
    yield tuple(near)
    if radius <= 0:
        return
    angle = random.Random(seed).random() * math.tau
    for fraction in (0.27, 0.53, 0.77, 1.0):
        for k in range(12):
            theta = angle + k * math.tau / 12
            yield (
                near[0] + radius * fraction * math.cos(theta),
                near[1] + radius * fraction * math.sin(theta),
            )


def place_sites(atlas):
    realms = {r["id"]: r for r in atlas.realms}
    prepared = []
    for raw in atlas.site_specs:
        rank = raw.get("rank", "VILLAGE")
        if rank not in SITE_DEFAULTS:
            raise ValueError(f"{raw['id']}: invalid settlement rank {rank!r}")
        rid = raw.get("realm_id", atlas.realms[0]["id"])
        if rid not in realms:
            raise ValueError(f"{raw['id']}: unknown realm_id {rid!r}")
        realm = realms[rid]
        defaults = SITE_DEFAULTS[rank]
        prepared.append(
            {
                "name": raw["id"],
                "realm_id": rid,
                "rank": rank,
                "search_radius_m": defaults["search_radius_m"],
                "extent_m": defaults["extent_m"],
                "plaza_m": defaults["plaza_m"],
                "concepts": (),
                "castle_role": "",
                "biome": realm["biome"],
                "grand_capital": False,
                **raw,
            }
        )
    requested = atlas._locate(prepared)
    sites = []
    order = {"CAPITAL": 0, "CITY": 1, "VILLAGE": 2}
    for row in sorted(requested, key=lambda s: order[s["rank"]]):
        rid = row["realm_id"]
        realm = realms[rid]
        name = row["id"]
        width, depth = row["extent_m"]
        if min(width, depth) < 95:
            raise ValueError(
                f"{name}: extent too small for assigned facilities"
            )
        if "near" not in row:
            raise ValueError(f"{name}: site near_uv is missing")
        near = row["near"]
        fixed = row.get("placement") == "FIXED"
        radius = 0 if fixed else row.get("search_radius_m", 350)
        rs = stable_seed(atlas.seed, name, "site")
        best = None
        collision = "map edge or another settlement"
        for x, y in _candidates(near, radius, rs):
            if (
                abs(x) + width * 0.51 > atlas.size[0] / 2
                or abs(y) + depth * 0.51 > atlas.size[1] / 2
            ):
                continue
            px, py = (v / 2 for v in row["plaza_m"])
            water = next(
                (
                    w
                    for dx in (-px, 0, px)
                    for dy in (-py, 0, py)
                    if (w := atlas.water_at(x + dx, y + dy))
                ),
                None,
            )
            if water:
                collision = water[1]
                continue
            if any(
                abs(x - s["centre"][0])
                < (width + s["extent_m"][0]) * 0.47 + 22
                and abs(y - s["centre"][1])
                < (depth + s["extent_m"][1]) * 0.47 + 22
                for s in sites
            ):
                continue
            z = atlas.terrain(x, y)
            probes = [
                atlas.terrain(x + dx, y + dy)
                for dx, dy in ((38, 0), (-38, 0), (0, 38), (0, -38))
            ]
            cliff = max(abs(h - z) for h in probes)
            score = math.dist((x, y), near) * 0.77 + cliff * 9
            if row["biome"] in ("MARSH", "COAST") and z < 3:
                score += 100
            choice = score, (x, y, z)
            if best is None or choice < best:
                best = choice
        if best is None:
            raise ValueError(f"{name}: site conflicts with {collision}")
        centre = best[1]
        sites.append(
            {
                **row,
                "centre": centre,
                "theme": realm["theme"],
                "seed": rs,
                "tile": atlas.cell(*centre[:2]),
                "moved_m": round(math.dist(centre[:2], near), 2),
                "placement_reason": "dry ground and usable road grade",
                "area_m2": round(width * depth),
            }
        )
    return sites


def _walk_grid(atlas):
    return {
        (i, j): (*atlas.centre(i, j), atlas.terrain(*atlas.centre(i, j)))
        for j in range(atlas.shape[1])
        for i in range(atlas.shape[0])
    }


def _find_route(atlas, grid, start, goal, wet_nodes, districts=()):
    a, b = atlas.cell(*start[:2]), atlas.cell(*goal[:2])
    heap = [(0.0, 0.0, a)]
    costs = {a: 0}
    back = {}
    while heap:
        _, cost, at = heapq.heappop(heap)
        if at == b:
            break
        if cost > costs[at]:
            continue
        for di, dj in (
            (1, 0),
            (-1, 0),
            (0, 1),
            (0, -1),
            (1, 1),
            (-1, 1),
            (1, -1),
            (-1, -1),
        ):
            nxt = at[0] + di, at[1] + dj
            if nxt not in grid:
                continue
            h = abs(grid[nxt][2] - grid[at][2])
            step = TILE * math.hypot(di, dj)
            wet = nxt in wet_nodes
            occupied = nxt in districts and nxt != b
            toll = step * (
                1 + (h / step) ** 1.65 * 15 + wet * 6 + occupied * 9
            )
            new = cost + toll
            if new < costs.get(nxt, math.inf):
                costs[nxt], back[nxt] = new, at
                remain = math.dist(nxt, b) * TILE
                heapq.heappush(heap, (new + remain, new, nxt))
    if b not in costs:
        raise ValueError("Unable to route atlas grid")
    cells = [b]
    while cells[-1] != a:
        cells.append(back[cells[-1]])
    p = [start, *(grid[c] for c in reversed(cells[1:-1])), goal]
    return _grade_route(atlas, p)


def _grade_route(atlas, rough):
    required = abs(rough[0][2] - rough[-1][2]) / 0.175
    segments = [math.dist(a[:2], b[:2]) for a, b in pairwise(rough)]
    if required > sum(segments):
        index = max(range(len(segments)), key=segments.__getitem__)
        a, b = rough[index : index + 2]
        length = segments[index]
        nx, ny = (a[1] - b[1]) / length, (b[0] - a[0]) / length
        width = min(126.0, max(54.0, length * 0.45))
        turns = math.ceil((required - sum(segments)) / (width * 1.85)) + 3
        bend = []
        for i in range(turns):
            t = (i + 1) / (turns + 1)
            off = width * (1 if i % 2 else -1)
            x = a[0] + (b[0] - a[0]) * t + nx * off
            y = a[1] + (b[1] - a[1]) * t + ny * off
            bend.append((x, y, atlas.terrain(x, y)))
        rough = [*rough[: index + 1], *bend, *rough[index + 1 :]]
    samples = [rough[0]]
    for j, (a, b) in enumerate(pairwise(rough), 1):
        d = math.dist(a[:2], b[:2])
        divisions = max(1, math.ceil(d / 22))
        for i in range(1, divisions):
            t = i / divisions
            x, y = (a[k] + (b[k] - a[k]) * t for k in range(2))
            w = atlas.water_at(x, y)
            z = atlas.terrain(x, y)
            samples.append((x, y, max(z, w[0] + 3.8) if w else z))
        water = atlas.water_at(*b[:2]) if j < len(rough) - 1 else None
        samples.append((*b[:2], max(b[2], water[0] + 3.8)) if water else b)
    distance = [0.0]
    for a, b in pairwise(samples):
        distance.append(distance[-1] + math.dist(a[:2], b[:2]))
    if abs(samples[-1][2] - samples[0][2]) > distance[-1] * 0.18 + 1e-6:
        raise ValueError("Route approach is too short for its height change")
    start_z, end_z = samples[0][2], samples[-1][2]
    heights = [
        min(p[2], start_z + 0.18 * d, end_z + 0.18 * (distance[-1] - d))
        for p, d in zip(samples, distance, strict=True)
    ]
    for order in (range(1, len(samples)), range(len(samples) - 2, -1, -1)):
        step = 1 if order.step > 0 else -1
        for i in order:
            d = math.dist(samples[i][:2], samples[i - step][:2])
            heights[i] = max(heights[i], heights[i - step] - 0.18 * d)
    heights[0], heights[-1] = start_z, end_z
    return tuple((*p[:2], h) for p, h in zip(samples, heights, strict=True))


def site_gate(site):
    x, y, z = site["centre"]
    return x, y + DISTRICT_EDGE[site["rank"]] - 17, z


def _gate_approach(atlas, site):
    gate = site_gate(site)
    x, y, _ = gate
    for dx, dy in (
        (0, -64),
        (-65, -48),
        (65, -48),
        (-98, -92),
        (98, -92),
        (0, -146),
    ):
        px = x + dx
        py = max(atlas.origin[1] + 2, y + dy)
        if abs(px) >= atlas.size[0] / 2:
            continue
        z = atlas.terrain(px, py)
        if water := atlas.water_at(px, py):
            z = max(z, water[0] + 3.8)
        path = _grade_route(atlas, [gate, (px, py, z)])
        if all(
            p[2] - w[0] >= 0.25 for p in path if (w := atlas.water_at(*p[:2]))
        ):
            return path
    raise ValueError(f"{site['id']}: no dry or bridgeable gate approach")


def build_routes(atlas, sites):
    if len(sites) < 2:
        return []
    grid = _walk_grid(atlas)
    wet = {i for i, p in grid.items() if atlas.water_at(*p[:2])}
    districts = {s["tile"] for s in sites}
    approaches = {s["id"]: _gate_approach(atlas, s) for s in sites}
    seats = [s for s in sites if s["rank"] == "CAPITAL"]
    hubs = seats or list(sites)
    pairs = []
    connected = hubs[:1]
    pending = hubs[1:]
    while pending:
        _, added, via = min(
            (math.dist(a["centre"], b["centre"]), i, j)
            for i, a in enumerate(pending)
            for j, b in enumerate(connected)
        )
        site = pending.pop(added)
        pairs.append((connected[via], site, "HIGHWAY"))
        connected.append(site)
    if seats:
        main = {s["realm_id"]: s for s in seats}
        for site in sites:
            if site["rank"] != "CAPITAL":
                hub = main.get(site["realm_id"]) or min(
                    seats, key=lambda c: math.dist(c["centre"], site["centre"])
                )
                pairs.append((hub, site, "REGIONAL"))
        for theme in atlas.themes:
            members = [s for s in seats if s["theme"] == theme["id"]]
            if len(members) > 1:
                pairs.extend((a, b, "THEME") for a, b in pairwise(members))
    routes = []
    seen = set()
    for a, b, kind in pairs:
        identity = tuple(sorted((a["id"], b["id"])))
        if identity in seen:
            continue
        seen.add(identity)
        left, right = approaches[a["id"]], approaches[b["id"]]
        crossing = _find_route(
            atlas, grid, left[-1], right[-1], wet, districts
        )
        path = (
            a["centre"],
            *left,
            *crossing[1:-1],
            *reversed(right),
            b["centre"],
        )
        bridges = [
            i
            for i, p in enumerate(path)
            if i not in (0, len(path) - 1) and atlas.water_at(*p[:2])
        ]
        routes.append(
            {
                "id": f"road_{identity[0]}_{identity[1]}",
                "from": a["id"],
                "to": b["id"],
                "kind": kind,
                "width": 6 if kind in ("HIGHWAY", "THEME") else 4,
                "points": path,
                "bridge_points": bridges,
                "condition": "ALWAYS",
                "theme": a["theme"],
                "length_m": round(
                    sum(math.dist(a, b) for a, b in pairwise(path)), 2
                ),
            }
        )
    return routes


def _inside_fog(basins, x, y):
    return any(
        math.hypot(
            (x - b["centre"][0]) / b["radii_m"][0],
            (y - b["centre"][1]) / b["radii_m"][1],
        )
        < 0.96
        for b in basins
    )


def _dungeon_candidates(
    atlas, sites, previous, near, radius, seed, target_basin, all_basins, kind
):
    for x, y in _candidates(near, radius, seed):
        x, y = round(x / 8) * 8, round(y / 8) * 8
        if any(
            abs(v) > n / 2 - 72
            for v, n in zip((x, y), atlas.size, strict=True)
        ):
            continue
        if target_basin is not None:
            cx, cy = target_basin["centre"]
            rx, ry = target_basin["radii_m"]
            inside = math.hypot((x - cx) / rx, (y - cy) / ry) < 0.96
            if inside != (kind == "CATACOMB"):
                continue
        elif all_basins and kind == "VAULT" and _inside_fog(all_basins, x, y):
            continue
        if any(
            abs(x - s["centre"][0]) < s["extent_m"][0] * 0.52 + 26
            and abs(y - s["centre"][1]) < s["extent_m"][1] * 0.52 + 26
            for s in sites
        ) or any(math.dist((x, y), e["entrance"][:2]) < 450 for e in previous):
            continue
        points = [
            (x + dx, y + dy)
            for dx in (-12, 0, 12)
            for dy in (-40, -28, -16, 5)
        ]
        if any(atlas.water_at(*p) for p in points):
            continue
        grade = [atlas.terrain(*p) for p in points]
        z = atlas.terrain(x, y)
        low = min(grade)
        if z < 13 or low < z - 6:
            continue
        u, v = atlas.corner(*atlas.cell(x, y))
        if not (24 <= x - u <= TILE - 24 and 46 <= y - v <= TILE - 16):
            continue
        floor = min(z - 4.1, low - 3.15)
        yield (
            math.dist(near, (x, y)) + (max(grade) - low) * 9,
            (x, y, z),
            floor,
        )


def _resolve_dungeon_near(atlas, spec, fog_map, theme_map):
    if "near_uv" in spec:
        return atlas.xy(spec["near_uv"])
    if "fog_basin_id" in spec:
        fog = fog_map.get(spec["fog_basin_id"])
        if fog is None:
            raise ValueError(
                f"{spec['id']}: unknown fog_basin_id {spec['fog_basin_id']!r}"
            )
        cx, cy = fog["centre"]
        rx, ry = fog["radii_m"]
        ox, oy = spec.get("offset_fraction", (0.0, 0.0))
        return cx + rx * ox, cy + ry * oy
    if "theme_end_offset_m" in spec:
        theme = theme_map.get(spec.get("theme", atlas.themes[0]["id"]))
        if theme is None:
            raise ValueError(f"{spec['id']}: unknown theme")
        ex, ey = theme["spine"][-1]
        dx, dy = spec["theme_end_offset_m"]
        return ex + dx, ey + dy
    raise ValueError(
        f"{spec['id']}: dungeon needs near_uv, fog_basin_id or "
        "theme_end_offset_m"
    )


def place_dungeons(atlas, sites):
    if not atlas.dungeon_specs:
        return []
    fog_map = {f["id"]: f for f in atlas.fog_basins}
    theme_map = {t["id"]: t for t in atlas.themes}
    basin_counts = {}
    dungeons = []
    for spec in atlas.dungeon_specs:
        uid = spec["id"]
        kind = spec.get("kind", "VAULT")
        if kind not in ("CATACOMB", "VAULT"):
            raise ValueError(f"{uid}: invalid dungeon kind {kind!r}")
        basin_id = spec.get("fog_basin_id")
        target_basin = fog_map.get(basin_id) if basin_id else None
        if basin_id and target_basin is None:
            raise ValueError(f"{uid}: unknown fog_basin_id {basin_id!r}")
        if target_basin is not None and kind == "CATACOMB":
            cap = target_basin.get("dungeon_count")
            used = basin_counts.get(basin_id, 0)
            if cap is not None and used >= cap:
                continue
            basin_counts[basin_id] = used + 1
        theme = spec.get("theme", atlas.themes[0]["id"])
        if theme not in theme_map:
            raise ValueError(f"{uid}: unknown dungeon theme {theme!r}")
        near = _resolve_dungeon_near(atlas, spec, fog_map, theme_map)
        seed = stable_seed(atlas.seed, uid, "entrance")
        radii = tuple(
            spec.get(
                "search_radii_m",
                (650, 1050, 1550) if kind == "VAULT" else (390, 520, 670),
            )
        )
        best = None
        for attempt, radius in enumerate(radii):
            best = min(
                _dungeon_candidates(
                    atlas,
                    sites,
                    dungeons,
                    near,
                    radius,
                    seed + attempt,
                    target_basin,
                    atlas.fog_basins,
                    kind,
                ),
                default=None,
            )
            if best is not None:
                break
        if best is None:
            raise ValueError(f"{uid}: no dry, separated entrance candidate")
        _, entry, floor = best
        default_lore = (
            ("FUNERARY_NICHES", "RETURNING_SEAL", "LATE_NEST", "RELIC_SHARD")
            if kind == "CATACOMB"
            else (
                "WORKROOM",
                "CIPHER_STUDY",
                "SEALED_REPOSITORY",
                f"{theme.upper()}_RELIC",
            )
        )
        dungeons.append(
            {
                "id": uid,
                "kind": kind,
                "theme": theme,
                "seed": seed,
                "entrance": entry,
                "tile": atlas.cell(*entry[:2]),
                "lore": tuple(spec.get("lore", default_lore)),
                "cellar_z": floor,
                "seal": spec.get("seal", uid + "_seal"),
            }
        )
    return dungeons


def _drainage(atlas, tiles, closed_indices):
    """Route runoff across filled sinks and preserve terminal lakes."""
    by_cell = {tuple(row["cell"]): row for row in tiles}
    width, height = atlas.shape
    filled, downstream, heap = {}, {}, []
    for cell, row in by_cell.items():
        i, j = cell
        if (
            i not in (0, width - 1)
            and j not in (0, height - 1)
            and row["climate"]["water"] not in closed_indices
        ):
            continue
        z = row["centre_z"]
        filled[cell] = z
        heapq.heappush(heap, (z, cell))
    order = []
    while heap:
        z, (i, j) = heapq.heappop(heap)
        order.append((i, j))
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = i + di, j + dj
            if n in filled or n not in by_cell:
                continue
            elevation = max(z + 0.0001, by_cell[n]["centre_z"])
            downstream[n] = i, j
            filled[n] = elevation
            heapq.heappush(heap, (elevation, n))
    litres = {}
    catchment = dict.fromkeys(by_cell, 1)
    for n, row in by_cell.items():
        sky = row["climate"]
        litres[n] = [
            max(0, rain - snow - evap * 0.48) * TILE**2
            for rain, snow, evap in zip(
                sky["monthly_mm"], sky["snow_mm"], sky["evap_mm"], strict=True
            )
        ]
    for cell in reversed(order):
        row = by_cell[cell]
        target = downstream.get(cell)
        row["drainage"] = {
            "downstream": by_cell[target]["id"] if target else None,
            "catchment_km2": round(catchment[cell] * TILE**2 / 1e6, 3),
            "spill_m": round(max(0, filled[cell] - row["centre_z"]), 2),
            "discharge_m3s": [
                round(v / 2_592_000_000, 4) for v in litres[cell]
            ],
        }
        if target is not None:
            catchment[target] += catchment[cell]
            litres[target] = [
                a + b
                for a, b in zip(litres[target], litres[cell], strict=True)
            ]


def _tile_fog(basins, x, y):
    if not basins:
        return 0.0, False
    best_radius = min(
        math.hypot(
            (x - b["centre"][0]) / b["radii_m"][0],
            (y - b["centre"][1]) / b["radii_m"][1],
        )
        for b in basins
    )
    return round(1 - smoothstep(0.49, 1.04, best_radius), 3), best_radius < 1


def plan_atlas(blueprint, seed=None, base_dir=None):
    atlas = Atlas(blueprint, seed, base_dir=base_dir)
    sites = place_sites(atlas)
    dungeons = place_dungeons(atlas, sites)
    routes = build_routes(atlas, sites)
    grid = _walk_grid(atlas)
    wet = {cell for cell, p in grid.items() if atlas.water_at(*p[:2])}
    for dungeon in dungeons:
        entry = dungeon["entrance"]
        if routes:
            _, point, rid = min(
                (math.dist(p[:2], entry[:2]), p, route["id"])
                for route in routes
                for p in route["points"]
            )
            dungeon["trail"] = _find_route(atlas, grid, point, entry, wet)
            dungeon["trail_from"] = rid
        elif sites:
            nearest = min(
                sites, key=lambda s: math.dist(s["centre"][:2], entry[:2])
            )
            dungeon["trail"] = _find_route(
                atlas, grid, site_gate(nearest), entry, wet
            )
            dungeon["trail_from"] = nearest["id"]
        else:
            dungeon["trail"] = (entry,)
            dungeon["trail_from"] = ""
    tiles = []
    inside, outside = 0, 0
    for j in range(atlas.shape[1]):
        for i in range(atlas.shape[0]):
            x, y = atlas.centre(i, j)
            z = atlas.terrain(x, y)
            climate = atlas.climate(x, y, z)
            fog_val, in_fog = _tile_fog(atlas.fog_basins, x, y)
            if not climate["water"]:
                inside += in_fog
                outside += not in_fog
            realm = "" if climate["water"] else atlas.owner(x, y)
            tiles.append(
                {
                    "id": f"{i}_{j}",
                    "cell": (i, j),
                    "origin": atlas.corner(i, j),
                    "centre_z": round(z, 2),
                    "realm": realm,
                    "theme": atlas.theme_at(x, y),
                    "climate": climate,
                    "fog": fog_val,
                    "sites": [s["id"] for s in sites if s["tile"] == (i, j)],
                    "dungeons": [
                        d["id"] for d in dungeons if d["tile"] == (i, j)
                    ],
                }
            )
    catacombs = sum(d["kind"] == "CATACOMB" for d in dungeons)
    vaults = sum(d["kind"] == "VAULT" for d in dungeons)
    density_ratio = (
        (catacombs / max(1, inside)) / (vaults / max(1, outside))
        if catacombs and vaults and inside
        else 0.0
    )
    _drainage(
        atlas,
        tiles,
        {
            f["id"]
            for f in atlas.water_features
            if f.get("closed") or f["kind"] == "SEA"
        },
    )
    seasonal = []
    seats = {s["id"]: s for s in sites}
    features_by_id = {f["id"]: f for f in atlas.features}
    for link in atlas.seasonal_links:
        start, finish = link["from"], link["to"]
        condition, water_id = link["condition"], link["feature"]
        if start not in seats or finish not in seats:
            continue
        feature = features_by_id.get(water_id)
        if feature is None:
            raise ValueError(f"Unknown seasonal link feature: {water_id!r}")
        anchor = feature.get("centre")
        if anchor is None:
            anchor = feature["axis"][len(feature["axis"]) // 2]
        sample = (*anchor, atlas.terrain(*anchor) + 0.65)
        homes = seats[start]["centre"], seats[finish]["centre"]
        seasonal.append(
            {
                "from": start,
                "to": finish,
                "condition": condition,
                "gate": sample,
                "feature": water_id,
                "length_m": round(
                    math.dist(homes[0], sample) + math.dist(sample, homes[1]),
                    2,
                ),
            }
        )
    return atlas, {
        "blueprint_version": 2,
        "schema_version": 2,
        "title": atlas.title,
        "seed": atlas.seed,
        "units": "metres",
        "coordinate_space": "blender_world_z_up",
        "size_m": atlas.size,
        "tile_size_m": TILE,
        "tile_shape": atlas.shape,
        "realms": atlas.realms,
        "regions": atlas.regions,
        "themes": atlas.themes,
        "features": atlas.features,
        "sites": sites,
        "routes": routes,
        "seasonal_links": seasonal,
        "dungeons": dungeons,
        "tiles": tiles,
        "report": {
            "capitals": sum(s["rank"] == "CAPITAL" for s in sites),
            "settlements": len(sites),
            "dungeons": len(dungeons),
            "fog_land_km2": round(inside * TILE**2 / 1e6, 3),
            "other_land_km2": round(outside * TILE**2 / 1e6, 3),
            "catacomb_density_ratio": round(density_ratio, 3),
        },
    }
