"""Buildable districts, door-connected buildings and dungeon layouts."""

import math
import random
from itertools import pairwise

from atlas_rules import DISTRICT_EDGE, _grade_route, site_gate, stable_seed
from terrain_rules import (
    SpatialHash,
    segment_projection,
    smoothstep,
    value_noise,
)

HOUSING = {
    "COAST": ("COASTAL", "WOOD_HORIZONTAL", "GABLE", 36, 0.42),
    "FOREST": ("WARM", "WOOD_VERTICAL", "GABLE", 44, 0.78),
    "PLAIN": ("WARM", "PLASTER", "GABLE", 39, 0.52),
    "MOUNTAIN": ("PASTEL", "BRICK", "GABLE", 45, 0.42),
    "SNOW": ("WARM", "WOOD_HORIZONTAL", "GABLE", 49, 0.64),
    "DESERT": ("WARM", "PLASTER", "FLAT", 12, 0.31),
    "MARSH": ("COASTAL", "WOOD_HORIZONTAL", "HIP", 32, 0.58),
    "MEDITERRANEAN": ("WARM", "PLASTER", "HIP", 25, 0.75),
}
TRADE_KINDS = (
    "ARMOURER",
    "BUTCHER",
    "CLOTHIER",
    "FISHMONGER",
    "BAKER",
)
SHOP_DISPLAY = {
    "ARMOURER": ("WEAPON_DISPLAY", "SHIELD_HOOK"),
    "BUTCHER": ("HANGING_GOODS", "MEAT_BLOCK"),
    "CLOTHIER": ("GARMENT_RAIL", "FABRIC_ROLL"),
    "FISHMONGER": ("FISH_CRATE", "NET_RACK"),
    "BAKER": ("BREAD_SHELF", "FLOUR_SACK"),
    "SAILMAKER": ("SAIL_RACK", "PULLEY"),
    "HERBALIST": ("HERB_RACK", "SPECIMEN_DRAWER"),
    "CARTOGRAPHER": ("MAP_STAND", "CHART_ROLL"),
    "SNOWGEAR": ("SNOWSHOE_RACK", "GEAR_BENCH"),
    "POTTER": ("AMPHORA_SHELF", "LANTERN_HOOK"),
}
FACILITIES = {
    "CATHEDRAL": (
        9,
        17,
        11,
        (("AISLE", "NAVE", "AISLE"), ("SACRISTY", "CHOIR", "CHAPTER")),
    ),
    "CHAPEL": (4.8, 9, 5.4, (("ENTRY",), ("SANCTUARY",))),
    "FRIDAY_MOSQUE": (
        8,
        9,
        6.8,
        (
            ("ABLUTION", "COURTYARD", "ARCADE"),
            ("PRAYER", "PRAYER", "PRAYER"),
        ),
    ),
    "MAGE_TOWER": (13, 15, 3.2, (("RECEPTION",),)),
    "TRAINING_YARD": (
        12,
        10,
        4.2,
        (
            ("COURTYARD", "COURTYARD", "COURTYARD"),
            ("ARMOURY", "ENTRY", "MESS"),
        ),
    ),
    "SAWMILL": (8, 9, 4.6, (("TIMBER_STORE", "WORKSHOP"),)),
    "CARAVANSERAI": (
        8,
        10,
        4.6,
        (("STABLE", "COURTYARD", "STORE"), ("GUEST", "HALL", "GUEST")),
    ),
    "CISTERN": (7, 9, 3.5, (("CATCHMENT", "PUMP_ROOM"),)),
    "ROYAL_HALL": (
        18,
        15,
        10.0,
        (("AUDIENCE",), ("GREAT_HALL",), ("GREAT_HALL",)),
    ),
    "ROYAL_SERVICE": (7, 9, 4.1, (("KITCHEN", "DELIVERY", "LAUNDRY"),)),
}
TOWER_LEVELS = ("RECEPTION", "LIBRARY", "LABORATORY", "ARCHIVE", "OBSERVATORY")


def rectangle(point, size):
    x, y = point[:2]
    w, d = (v / 2 for v in size)
    return x - w, y - d, x + w, y + d


def overlaps(a, b, margin=0):
    return (
        a[0] < b[2] + margin
        and b[0] < a[2] + margin
        and a[1] < b[3] + margin
        and b[1] < a[3] + margin
    )


def contains(bounds, x, y):
    return bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]


def dry_footprint(atlas, bounds):
    left, bottom, right, top = bounds
    return not any(
        atlas.water_at(x, y)
        for x in (left, (left + right) * 0.5, right)
        for y in (bottom, (bottom + top) * 0.5, top)
    )


def _module_size(kind):
    w, d, _, rows = FACILITIES[kind]
    if kind == "MAGE_TOWER":
        return w, d
    return len(rows[0]) * w, len(rows) * d


def _site_layout(atlas, site):
    cx, cy, z = site["centre"]
    name = site["id"]
    rng = random.Random(site["seed"])
    rank = site["rank"]
    w, d = site["plaza_m"]
    lower = DISTRICT_EDGE[rank]
    plaza = {
        "id": f"{name}_plaza",
        "centre": (cx, cy, z),
        "bounds": rectangle((cx, cy), (w, d)),
        "size": (w, d),
        "procession_width": 8 if rank == "CAPITAL" else 3,
        "walkway_width": 3.0 if rank != "VILLAGE" else 1.6,
        "service_width": 4.0 if rank == "CAPITAL" else 2.8,
    }
    plots, reserves, paths = [], [plaza["bounds"]], []

    def path(label, a, b, width, *, end_z=None):
        paths.append(
            {
                "id": f"{name}_{label}",
                "points": ((*a, z), (*b, z if end_z is None else end_z)),
                "width": width,
                "bridge_points": (),
                "kind": "STREET",
            }
        )

    def facility(kind, x, y, limit=30):
        size = _module_size(kind)
        for dx, dy in (
            (0, 0),
            (-limit, 0),
            (limit, 0),
            (0, -limit),
            (0, limit),
            (-limit, -limit),
            (limit, limit),
            (0, 2 * limit),
            (-2 * limit, 0),
            (2 * limit, 0),
            (0, -2 * limit),
        ):
            fx, fy = x + dx, y + dy
            bounds = rectangle((fx, fy), size)
            if any(overlaps(bounds, r, 3) for r in reserves):
                continue
            if not dry_footprint(atlas, bounds):
                continue
            uid = f"{name}_{kind.lower()}"
            place = {
                "id": uid,
                "kind": kind,
                "centre": (fx, fy, z),
                "size": size,
                "bounds": bounds,
                "seed": stable_seed(uid),
                "entry": (fx, fy - size[1] / 2, z),
            }
            plots.append(place)
            reserves.append(bounds)
            return place
        raise ValueError(f"{name}: no dry plot for required {kind}")

    # Reserve the public buildings before laying out private parcels.
    for kind in (
        "CATHEDRAL",
        "FRIDAY_MOSQUE",
        "CHAPEL",
        "TRAINING_YARD",
        "MAGE_TOWER",
        "SAWMILL",
        "CARAVANSERAI",
        "CISTERN",
    ):
        if kind not in site["concepts"]:
            continue
        side = 1 if kind in ("TRAINING_YARD", "MAGE_TOWER", "CHAPEL") else -1
        x = cx + side * (w / 2 + _module_size(kind)[0] / 2 + 11)
        lane = 27 if kind == "CHAPEL" else 0
        place = facility(kind, x, cy + lane)
        ex, ey, _ = place["entry"]
        path(f"approach_{kind.lower()}", (cx, ey - 3), (ex, ey - 3), 3.2)
        path(f"entry_{kind.lower()}", (ex, ey - 3), (ex, ey), 2.4)
    grown = bool(site.get("grand_capital", False))
    keep_pad = None
    if role := site["castle_role"]:
        radius = {"FORTRESS": 19, "RESIDENCE": 26, "ROYAL_SEAT": 34}[role]
        y = cy + d / 2 + radius + (91 if grown else 31)
        rise = 9.5 if grown else 4 if role == "FORTRESS" else 2.7
        keep_z = z + rise
        bounds = rectangle((cx, y), (radius * 2.15, radius * 2.2))
        if not dry_footprint(atlas, bounds):
            raise ValueError(f"{name}: castle plot meets a water body")
        keep_pad = bounds, rise
        plots.append(
            {
                "id": f"{name}_keep",
                "kind": "CASTLE",
                "role": role,
                "centre": (cx, y, keep_z),
                "radius": radius,
                "bounds": bounds,
                "size": (radius * 2.15, radius * 2.2),
                "seed": site["seed"],
                "entry": (cx, bounds[1], keep_z),
            }
        )
        reserves.append(bounds)
        path(
            "castle_avenue",
            (cx, cy + d / 2),
            (cx, bounds[1]),
            8 if grown else 4.6,
            end_z=keep_z,
        )
        if grown:
            west = facility("ROYAL_HALL", cx - 44, y - 18, 28)
            east = facility("ROYAL_SERVICE", cx + 49, y - 10, 25)
            for wing in (west, east):
                ex, ey, _ = wing["entry"]
                label = wing["kind"].lower()
                terrace = bounds[1] - 22
                path(label + "_terrace", (cx, terrace), (ex, terrace), 3.6)
                path(label + "_lane", (ex, terrace), (ex, ey - 1.8), 3.6)
                path(
                    label + "_door",
                    (ex, ey - 1.8),
                    (ex, ey),
                    2.6,
                )
    path(
        "main",
        site_gate(site)[:2],
        (cx, cy + d / 2),
        8 if grown else 5,
    )

    theme = next(
        (t for t in atlas.themes if t["id"] == site["theme"]),
        atlas.themes[0],
    )
    streets = 3 if rank == "CAPITAL" else 2 if rank == "CITY" else 1
    row_count = 7 if rank == "CAPITAL" else 5 if rank == "CITY" else 3
    spacing = 16 if rank == "CAPITAL" else 15
    width = row_count * spacing / 2
    shop_types = list(TRADE_KINDS) + [theme["trade"]]
    shops = (
        len(shop_types) if rank == "CAPITAL" else 3 if rank == "CITY" else 1
    )
    for s in range(streets):
        y = cy + lower + s * 29
        path(
            f"market_street_{s}", (cx - width - 6, y), (cx + width + 6, y), 4.8
        )
        for facing in (-1, 1):
            for k in range(row_count):
                x = cx + (k - (row_count - 1) / 2) * spacing
                if abs(x - cx) < 7:
                    continue
                bw = rng.uniform(6.4, 9.1)
                bd = rng.uniform(8.2, 12.6)
                pos = (x, y + facing * (4.7 + bd / 2), z)
                bounds = rectangle(pos, (bw, bd))
                if any(overlaps(bounds, r, 1.1) for r in reserves):
                    continue
                if not dry_footprint(atlas, bounds):
                    continue
                business = ""
                if shops and (s + abs(k - row_count // 2) < 4):
                    business = shop_types[
                        (len(shop_types) - shops) % len(shop_types)
                    ]
                    shops -= 1
                floors = (
                    rng.randint(1, 2)
                    if rank != "CAPITAL"
                    else rng.randint(2, 3)
                )
                uid = (
                    f"{name}_lot_{s}_{'north' if facing > 0 else 'south'}_{k}"
                )
                plots.append(
                    {
                        "id": uid,
                        "kind": "HOUSE",
                        "centre": pos,
                        "size": (bw, bd),
                        "bounds": bounds,
                        "seed": stable_seed(site["seed"], uid),
                        "front": facing,
                        "floors": floors,
                        "business": business,
                        "entry": (x, y + facing * 4.7, z),
                    }
                )
                reserves.append(bounds)
                path(uid + "_access", (x, y), (x, y + facing * 4.7), 1.8)
    if not any(p["kind"] == "HOUSE" for p in plots):
        for dx, dy in (
            (20, -13),
            (-20, -13),
            (24, 0),
            (-24, 0),
            (32, -7),
            (-32, -7),
        ):
            bw, bd = 6.4, 8.4
            pos = cx + dx, cy + dy, z
            bounds = rectangle(pos, (bw, bd))
            if any(
                overlaps(bounds, r, 1.1) for r in reserves
            ) or not dry_footprint(atlas, bounds):
                continue
            uid = f"{name}_waterfront_house"
            entry = pos[0], pos[1] - bd / 2, z
            plots.append(
                {
                    "id": uid,
                    "kind": "HOUSE",
                    "centre": pos,
                    "size": (bw, bd),
                    "bounds": bounds,
                    "seed": stable_seed(site["seed"], uid),
                    "front": 1,
                    "floors": 1,
                    "business": shop_types[0],
                    "entry": entry,
                }
            )
            reserves.append(bounds)
            path(
                uid + "_path",
                (cx, entry[1] - 2),
                (entry[0], entry[1] - 2),
                2.0,
            )
            path(uid + "_entry", (entry[0], entry[1] - 2), entry[:2], 1.8)
            break
        else:
            raise ValueError(f"{name}: no dry housing plots")
    periphery = (
        min(r[0] for r in reserves) - 11,
        min(r[1] for r in reserves) - 11,
        max(r[2] for r in reserves) + 11,
        max(r[3] for r in reserves) + 11,
    )
    return {
        "plaza": plaza,
        "places": plots,
        "streets": paths,
        "graded_bounds": periphery,
        "keep_pad": keep_pad,
    }


def furnish_atlas(atlas, plan):
    for site in plan["sites"]:
        site.update(_site_layout(atlas, site))
        if site["rank"] != "VILLAGE" and (harbour := _waterfront(atlas, site)):
            site["waterfront"] = harbour
            site["streets"].append(harbour["access"])
    for dungeon in plan["dungeons"]:
        dungeon.update(dungeon_layout(dungeon))


def _waterfront(atlas, site):
    concepts = site.get("concepts", ())
    if not concepts:
        return None
    kinds = {
        "HARBOR": ("SEA",),
        "MEDITERRANEAN": ("SEA",),
        "LAKE_TOWN": ("GLACIAL_TROUGH", "TARN"),
        "OASIS": ("SPRING",),
        "WETLAND": ("RIVER", "OXBOW"),
        "ROYAL_PLAZA": ("RIVER",),
        "RIVERSIDE": ("RIVER",),
    }.get(concepts[0], ())
    if not kinds:
        return None
    x, y, z = site["centre"]
    choices = []
    reach = 1350 if site["rank"] == "CAPITAL" else 660
    for k in range(36):
        bearing = k * math.tau / 36
        dx, dy = math.cos(bearing), math.sin(bearing)
        for d in range(24, reach, 16):
            wx, wy = x + dx * d, y + dy * d
            if (
                abs(wx) > atlas.size[0] / 2 - 22
                or abs(wy) > atlas.size[1] / 2 - 22
            ):
                break
            water = atlas.water_at(wx, wy)
            if not water or water[2] not in kinds:
                continue
            level, body, kind = water
            hx, hy = wx - dx * 20, wy - dy * 20
            if atlas.water_at(hx, hy):
                continue
            height = atlas.terrain(hx, hy)
            outer = (wx + dx * 9, wy + dy * 9)
            if not (wet := atlas.water_at(*outer)) or wet[1] != body:
                continue
            use_z = max(
                level + (1.12 if kind == "SEA" else 0.83), height - 0.9
            )
            head, tip = (hx, hy, use_z), (*outer, use_z)
            score = d + max(0, height - level - 3) * 37 + 2 * abs(use_z - z)
            choices.append((score, head, tip, body, kind))
            break
    if not choices:
        return None
    _, head, tip, body, kind = min(choices)
    uid = site["id"] + "_waterfront"
    back_y = min(
        p[1]
        for r in site["streets"]
        if r["id"].endswith("_main")
        for p in r["points"]
    )
    bounds = site["graded_bounds"]
    side_x = bounds[0] - 9 if head[0] < x else bounds[2] + 9
    approach = _grade_route(
        atlas, [(x, y, z), (x, back_y, z), (side_x, back_y, z), head]
    )
    return {
        "id": uid,
        "head": head,
        "tip": tip,
        "water_id": body,
        "kind": kind,
        "width": 6.4 if kind == "SEA" else 3.6,
        "access": {
            "id": uid + "_access",
            "points": approach,
            "width": 4.6,
            "bridge_points": (),
            "kind": "REGIONAL",
        },
    }


def facility_rooms(place):
    kind = place["kind"]
    width, depth, height, rows = FACILITIES[kind]
    x, y, z = place["centre"]
    if kind == "MAGE_TOWER":
        return [
            {
                "id": f"{place['id']}_{level}",
                "kind": name,
                "centre": (x, y, z + level * height),
                "size": (width, depth),
                "height": height,
                "cell": (0, 0),
                "level": level,
            }
            for level, name in enumerate(TOWER_LEVELS)
        ]
    rooms = []
    for i, row in enumerate(rows):
        for j, name in enumerate(row):
            room = (
                x + (j - (len(row) - 1) / 2) * width,
                y + (i - (len(rows) - 1) / 2) * depth,
                z,
            )
            rooms.append(
                {
                    "id": f"{place['id']}_{i}_{j}",
                    "kind": name,
                    "centre": room,
                    "size": (width, depth),
                    "height": height,
                    "cell": (j, i),
                    "level": 0,
                }
            )
    return rooms


def dungeon_layout(dungeon):
    x, y, z = dungeon["entrance"]
    floor = dungeon["cellar_z"]
    shaft = (x - 4, y - 16, x + 4, y)
    if dungeon["kind"] == "CATACOMB":
        rows = (
            ("", "VESTIBULE", ""),
            ("BURIAL", "FUNERARY_GALLERY", "CLUE"),
            ("", "LATE_NEST", "OSSUARY"),
        )
    else:
        rows = (
            ("", "WORKROOM", ""),
            ("RECORDS", "LENS_CHAMBER", "CLUE"),
            ("", "REPOSITORY", ""),
        )
    rooms = []
    for i, row in enumerate(rows):
        for j, name in enumerate(row):
            if name:
                rooms.append(
                    {
                        "id": f"{dungeon['id']}_{i}_{j}",
                        "kind": name,
                        "centre": (x + (j - 1) * 8, y - 20 - i * 8, floor),
                        "size": (8, 8),
                        "height": 2.8,
                        "cell": (j, -i),
                        "level": 0,
                    }
                )
    descent = [(x, y + 1, z), (x, y, z), (x, y - 16, floor)]
    return {"shaft": shaft, "rooms": rooms, "approach": descent}


def atlas_paths(plan):
    return [
        *({**r, "points": r["points"][1:-1]} for r in plan["routes"]),
        *(p for site in plan["sites"] for p in site["streets"]),
        *(
            {
                "id": f"{d['id']}_trail",
                "points": tuple(path),
                "width": 2.1,
                "bridge_points": (),
                "kind": "TRAIL",
            }
            for d in plan["dungeons"]
            if (path := d.get("trail"))
        ),
    ]


def shop_sockets(place, palette):
    if not place["business"]:
        return []
    x, y, z = place["entry"]
    front = place["front"]
    sockets = []
    for side, kind in zip(
        (-1, 1), SHOP_DISPLAY[place["business"]], strict=True
    ):
        sockets.append(
            {
                "id": f"{place['id']}_{kind.lower()}",
                "shop_id": place["id"],
                "kind": kind,
                "position": (x + side * 1.9, y - front * 0.69, z + 0.88),
                "front": (0, -front, 0),
                "bounds_m": (0.95, 0.55, 1.30),
                "access_point": (x + side * 1.9, y - front * 1.65, z),
                "palette": palette,
                "capacity": 2,
            }
        )
    return sockets


def grade_site(site, x, y, natural):
    left, bottom, right, top = site["graded_bounds"]
    d = math.hypot(max(left - x, x - right, 0), max(bottom - y, y - top, 0))
    weight = 1 - smoothstep(0, 26, d)
    z = site["centre"][2]
    h = natural + weight * (z - natural)
    if pad := site["keep_pad"]:
        (x0, y0, x1, y1), rise = pad
        cliff = math.hypot(max(x0 - x, x - x1, 0), max(y0 - y, y - y1, 0))
        if cliff < 16:
            edge = 10 + 3 * value_noise(x / 13, y / 13, site["seed"])
            h += rise * (1 - smoothstep(1.5, edge, cliff))
    return h


def routes_in_bounds(paths, bounds):
    left, bottom, right, top = bounds
    for route in paths:
        width = route["width"]
        for a, b in pairwise(route["points"]):
            if (
                max(a[0], b[0]) + width < left
                or min(a[0], b[0]) - width > right
                or max(a[1], b[1]) + width < bottom
                or min(a[1], b[1]) - width > top
            ):
                continue
            yield route, a, b


def clip_segment(a, b, box):
    lo, hi = 0.0, 1.0
    for k in range(2):
        d = b[k] - a[k]
        if abs(d) < 1e-9:
            if not box[k] <= a[k] < box[k + 2]:
                return None
            continue
        start, end = sorted(((box[k] - a[k]) / d, (box[k + 2] - a[k]) / d))
        lo, hi = max(lo, start), min(hi, end)
    if hi - lo <= 1e-6:
        return None
    return tuple(
        tuple(u + (v - u) * t for u, v in zip(a, b, strict=True))
        for t in (lo, hi)
    )


class Landscape:
    """Use the same terraces, road levels and normals in every tile."""

    def __init__(self, atlas, plan):
        self.atlas = atlas
        self.sites = plan["sites"]
        self.site_index = SpatialHash(256)
        for index, site in enumerate(self.sites):
            x0, y0, x1, y1 = site["graded_bounds"]
            self.site_index.insert(index, (x0 - 26, y0 - 26, x1 + 26, y1 + 26))
        self.path_index = SpatialHash(24)
        self.paths = []
        for road in atlas_paths(plan):
            for a, b in pairwise(road["points"]):
                self.path_index.insert(
                    len(self.paths),
                    (
                        min(a[0], b[0]),
                        min(a[1], b[1]),
                        max(a[0], b[0]),
                        max(a[1], b[1]),
                    ),
                )
                self.paths.append((road["width"], a, b))

    def district(self, x, y):
        for index in sorted(self.site_index.query((x, y), 0)):
            site = self.sites[index]
            if contains(site["graded_bounds"], x, y):
                return site
        return None

    def height(self, x, y):
        z = self.atlas.terrain(x, y)
        if self.atlas.water_at(x, y) is not None:
            return z
        for i in sorted(self.site_index.query((x, y), 0)):
            z = grade_site(self.sites[i], x, y, z)
        ranked = []
        for i in self.path_index.query((x, y), 22):
            width, a, b = self.paths[i]
            d, t, _ = segment_projection((x, y), a, b)
            if d < width / 2 + 11:
                ranked.append((d - width / 2, a[2] + (b[2] - a[2]) * t))
        if ranked:
            distance, grade = min(ranked)
            z += (grade - z) * (1 - smoothstep(0, 11, distance))
        for zone in self.atlas.regions:
            cap = zone.get("max_elevation_m")
            if cap is not None:
                distance, _ = self.atlas.water_shape(zone, x, y)
                if distance <= 1:
                    z = min(z, cap)
        return z
