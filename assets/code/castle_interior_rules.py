"""Castle rooms, openings, stairs and traversable furniture layouts."""

import math
import random
from collections import defaultdict, deque
from dataclasses import dataclass, replace
from functools import lru_cache

from castle_geometry import (
    boundary_segments,
    circle,
    edges,
    owner_at,
    planar_regions,
    rectangle,
)
from castle_roof_rules import window_under_roof
from house_rules import clip_polygon, polygon_area
from interior_rules import DEFAULT_CATALOG, FurnitureSpec
from terrain_rules import (
    SpatialHash,
    inside_polygon,
    oriented_corners,
    polygons_overlap,
    rectangle_distance,
    segment_projection,
)

BASE = 0.12
SLAB = 0.22
AGENT_RADIUS = 0.35
WALL = 0.36
PARTITION = 0.16
GRID = 0.25

CATALOG = {
    **DEFAULT_CATALOG,
    "banquet_table": FurnitureSpec("banquet_table", (3.0, 1.0, 0.78)),
    "bench": FurnitureSpec("bench", (2.0, 0.45, 0.48)),
    "hearth": FurnitureSpec("hearth", (1.35, 0.65, 1.25)),
    "barrel": FurnitureSpec("barrel", (0.65, 0.65, 0.9)),
    "shelf": FurnitureSpec("shelf", (1.35, 0.45, 1.7)),
    "altar": FurnitureSpec("altar", (1.5, 0.75, 1.0)),
    "pew": FurnitureSpec("pew", (1.8, 0.45, 0.9)),
    "weapon_rack": FurnitureSpec("weapon_rack", (1.35, 0.45, 1.65)),
    "chest": FurnitureSpec("chest", (0.9, 0.5, 0.6)),
}
PROGRAM = {
    "palas": ("GREAT_HALL", "COUNCIL", "GUEST_CHAMBER", "SOLAR"),
    "donjon": (
        "STOREROOM",
        "ARMOURY",
        "LORD_BEDROOM",
        "STUDY",
        "TREASURY",
        "WATCH_ROOM",
    ),
    "forewing": ("KITCHEN", "BARRACKS", "SERVANT_CHAMBER"),
    "chapel": ("CHAPEL", "LIBRARY", "SCRIBE_ROOM"),
}
FURNISHINGS = {
    "GREAT_HALL": ("banquet_table", "bench", "bench", "hearth"),
    "COUNCIL": ("banquet_table", "chair", "chair", "shelf"),
    "GUEST_CHAMBER": ("bed", "wardrobe", "desk", "lamp"),
    "SOLAR": ("sofa", "desk", "chair", "shelf"),
    "STOREROOM": ("barrel", "barrel", "shelf", "chest"),
    "ARMOURY": ("weapon_rack", "weapon_rack", "chest"),
    "LORD_BEDROOM": ("bed", "wardrobe", "desk", "lamp"),
    "STUDY": ("desk", "chair", "shelf"),
    "TREASURY": ("chest", "chest", "shelf"),
    "WATCH_ROOM": ("desk", "chair", "weapon_rack"),
    "KITCHEN": ("hearth", "dining_table", "shelf", "barrel"),
    "BARRACKS": ("bed", "bed", "weapon_rack", "chest"),
    "SERVANT_CHAMBER": ("bed", "wardrobe", "chest"),
    "CHAPEL": ("altar", "pew", "pew"),
    "LIBRARY": ("shelf", "shelf", "desk"),
    "SCRIBE_ROOM": ("desk", "chair", "shelf"),
    "GUARDROOM": ("weapon_rack", "chest"),
}
FURNISHINGS.update(
    {
        "PANTRY": ("shelf", "barrel", "barrel", "chest"),
        "VESTRY": ("wardrobe", "chest", "desk", "chair"),
        "LADY_BEDROOM": ("bed", "lamp", "wardrobe", "chest"),
    }
)
FURNISHINGS["GREAT_HALL"] = (
    "banquet_table",
    "bench",
    "bench",
    "banquet_table",
    "bench",
    "bench",
    "hearth",
)
FURNISHINGS["CHAPEL"] = ("altar", "pew", "pew", "pew", "pew")


@dataclass(frozen=True)
class Opening:
    start: float
    end: float
    bottom: float
    top: float
    kind: str


@dataclass(frozen=True)
class InteriorWall:
    id: str
    a: tuple
    b: tuple
    z: float
    height: float
    thickness: float
    sides: tuple
    openings: tuple


@dataclass(frozen=True)
class CastleRoom:
    id: str
    kind: str
    level: str
    regions: tuple
    position: tuple = ()
    zone: str = ""
    privacy: int = 0
    area: float = 0.0


@dataclass(frozen=True)
class InteriorLevel:
    id: str
    index: int
    z: float
    height: float
    shapes: tuple
    regions: tuple
    holes: tuple
    walls: tuple


@dataclass(frozen=True)
class CastleStair:
    id: str
    kind: str
    lower: str
    upper: str
    bottom: float
    top: float
    polygon: tuple
    start: tuple
    end: tuple
    steps: int
    width: float
    tread: float = 0.0
    landing: float = 0.0
    centre: tuple = ()
    inner: float = 0.0
    outer: float = 0.0
    angle: float = 0.0


@dataclass(frozen=True)
class CastleFurniture:
    id: str
    kind: str
    room_id: str
    level: str
    position: tuple
    size: tuple
    heading: float
    anchor_id: str = ""
    approach: tuple = ()


@dataclass(frozen=True)
class CastleInterior:
    floor_height: float
    levels: tuple
    rooms: tuple
    stairs: tuple
    furniture: tuple
    navigation: dict
    warnings: tuple


def stair_path(stair):
    """Walking-height samples follow the actual treads and landings."""
    points = [stair.start]
    rise = (stair.top - stair.bottom) / stair.steps
    if stair.kind == "SPIRAL":
        radius = (stair.inner + stair.outer) / 2
        for i in range(stair.steps):
            angle = stair.angle + math.radians(
                30 + (i + 0.5) * 300 / stair.steps
            )
            points.append(
                (
                    stair.centre[0] + radius * math.cos(angle),
                    stair.centre[1] + radius * math.sin(angle),
                    stair.bottom + (i + 1) * rise,
                )
            )
    else:
        n = stair.steps // 2
        x1, y1 = stair.polygon[0]
        x2, y2 = stair.polygon[2]
        points += [
            (
                x1 + stair.width / 2,
                y1 + (i + 0.5) * stair.tread,
                stair.bottom + (i + 1) * rise,
            )
            for i in range(n)
        ]
        points += [
            (
                x1 + stair.width / 2,
                y2 - stair.landing / 2,
                stair.bottom + n * rise,
            ),
            (
                x2 - stair.width / 2,
                y2 - stair.landing / 2,
                stair.bottom + n * rise,
            ),
        ]
        points += [
            (
                x2 - stair.width / 2,
                y2 - stair.landing - (i + 0.5) * stair.tread,
                stair.bottom + (n + i + 1) * rise,
            )
            for i in range(n)
        ]
    return tuple(points + [stair.end])


def block_polygon(block):
    x, y = block.centre
    w, d = block.size
    return rectangle(x - w / 2, y - d / 2, x + w / 2, y + d / 2)


def defensive_towers(architecture):
    s = architecture.scale
    result = [
        (f"wall_tower_{i}", architecture.outline[i], max(1.65, 1.7 * s))
        for i in range(2, len(architecture.outline), 2)
    ]
    distance = architecture.gate_width / 2 + 1.8 * s
    result += [
        (
            f"gate_tower_{side}",
            (side * distance, architecture.outline[0][1]),
            max(1.65, 1.65 * s),
        )
        for side in (-1, 1)
    ]
    return tuple(result)


def _u_stair(identifier, lower, upper, bottom, top, left, back, scale):
    flight = max(1.0, 1.05 * scale)
    landing = max(1.1, flight)
    count = math.ceil((top - bottom) / 0.36)
    tread = max(0.26, 0.26 * scale)
    width, depth = flight * 2 + 0.10, count * tread + landing
    front = back - depth
    polygon = rectangle(left, front, left + width, back)
    return CastleStair(
        identifier,
        "U",
        lower,
        upper,
        bottom,
        top,
        polygon,
        (left + flight / 2, front - 0.65, bottom),
        (left + width - flight / 2, front - 0.65, top),
        count * 2,
        flight,
        tread,
        landing,
    )


def _merge_segments(segments):
    result = list(segments)
    changed = True
    while changed:
        changed = False
        for i, (a, b, left, right) in enumerate(result):
            for j in range(i + 1, len(result)):
                c, d, other_left, other_right = result[j]
                if (left, right) != (other_left, other_right):
                    continue
                if math.dist(b, c) < 1e-5:
                    start, middle, end = a, b, d
                elif math.dist(d, a) < 1e-5:
                    start, middle, end = c, d, b
                else:
                    continue
                cross = (middle[0] - start[0]) * (end[1] - middle[1]) - (
                    middle[1] - start[1]
                ) * (end[0] - middle[0])
                if abs(cross) < 1e-5:
                    result[i] = (start, end, left, right)
                    result.pop(j)
                    changed = True
                    break
            if changed:
                break
    return result


def _portal_spaces(shapes, segments, height):
    walls = tuple(
        InteriorWall(
            f"probe_{i}",
            a,
            b,
            0,
            height,
            PARTITION if left and right else WALL,
            (left, right),
            (),
        )
        for i, (a, b, left, right) in enumerate(segments)
    )
    level = InteriorLevel(
        "portal_probe", 0, 0, height, tuple(shapes), (), (), walls
    )
    grid = WalkGrid(level)
    components = {}
    for cell in sorted(grid.free):
        if cell not in components:
            visited = grid.flood(cell)
            index = len(components)
            components.update((c, index) for c in visited)
    return grid, components


def _portal_cell(grid, point, owner):
    ix, iy = (round(v / GRID) for v in point)
    candidates = [
        (ix + dx, iy + dy)
        for dx in range(-2, 3)
        for dy in range(-2, 3)
        if (ix + dx, iy + dy) in grid.free
        and grid.owners[ix + dx, iy + dy] == owner
    ]
    if not candidates:
        return None
    nearest = min(candidates, key=lambda c: math.dist(grid.point(c), point))
    return nearest if math.dist(grid.point(nearest), point) < 0.35 else None


def _door_side_cell(grid, segment, own):
    if grid is None:
        return None
    a, b, left, right = segment
    length = math.dist(a, b)
    sign = -1 if own == left else 1
    nx, ny = -(b[1] - a[1]) / length, (b[0] - a[0]) / length
    point = (
        (a[0] + b[0]) / 2 + sign * nx * 0.6,
        (a[1] + b[1]) / 2 + sign * ny * 0.6,
    )
    return _portal_cell(grid, point, right if own == left else left)


def _walls(
    identifier,
    shapes,
    z,
    height,
    scale,
    main_entry=None,
    rampart=False,
    architecture=None,
    with_portal_grid=False,
):
    segments = _merge_segments(boundary_segments(shapes))
    pairs = defaultdict(list)
    for index, (_a, _b, left, right) in enumerate(segments):
        if left and right:
            pairs[tuple(sorted((left, right)))].append(index)
    doors = set()
    portal_grid, components = (
        _portal_spaces(shapes, segments, height)
        if any(name.startswith("passage_") for name, _ in shapes)
        else (None, {})
    )
    portal_centres = {}
    for candidates in pairs.values():
        candidates = [
            i for i in candidates if math.dist(*segments[i][:2]) > 1.0
        ]
        if not candidates:
            continue
        names = segments[candidates[0]][2:]
        if "stairwell" in names:
            polygon = next(p for name, p in shapes if name == "stairwell")
            front = min(p[1] for p in polygon)
            selected = min(
                candidates,
                key=lambda i: (
                    abs((segments[i][0][1] + segments[i][1][1]) / 2 - front),
                    -math.dist(*segments[i][:2]),
                ),
            )
            doors.add(selected)
        elif any("tower" in name for name in names):
            tower = next(name for name in names if "tower" in name)
            public_portal = any(
                tower in pair
                and any(n.startswith("passage_") for n in pair)
                and any(
                    math.dist(*segments[i][:2]) > 1.0
                    and _door_side_cell(portal_grid, segments[i], tower)
                    is not None
                    for i in indices
                )
                for pair, indices in pairs.items()
            )
            if not public_portal or any(
                n.startswith("passage_") for n in names
            ):
                doors.update(
                    i
                    for i in candidates
                    if portal_grid is None
                    or _door_side_cell(portal_grid, segments[i], tower)
                    is not None
                )
        elif any(name.startswith("passage_") for name in names) or {
            n.rsplit("_", 1)[0] for n in names
        } in ({"forewing", "pantry"}, {"chapel", "vestry"}):
            choices = {}
            for i in candidates:
                a, b, left, right = segments[i]
                length = math.dist(a, b)
                nx, ny = -(b[1] - a[1]) / length, (b[0] - a[0]) / length
                width = min(max(1.05, 1.2 * scale), length - 0.10)
                low, high = width / 2 + 0.04, length - width / 2 - 0.04
                probes = [length / 2] + [
                    low + (high - low) * j / 8 for j in range(9)
                ]
                for u in probes:
                    centre = (
                        a[0] + (b[0] - a[0]) * u / length,
                        a[1] + (b[1] - a[1]) * u / length,
                    )
                    cells = [
                        _portal_cell(
                            portal_grid,
                            (
                                centre[0] + sign * nx * 0.6,
                                centre[1] + sign * ny * 0.6,
                            ),
                            name,
                        )
                        for sign, name in ((1, left), (-1, right))
                    ]
                    if any(c is None for c in cells):
                        continue
                    tx, ty = (b[0] - a[0]) / length, (b[1] - a[1]) / length
                    if any(
                        abs(
                            (portal_grid.point(c)[0] - centre[0]) * tx
                            + (portal_grid.point(c)[1] - centre[1]) * ty
                        )
                        > width / 2 - AGENT_RADIUS - 0.035
                        for c in cells
                    ):
                        continue
                    key = tuple(components[c] for c in cells)
                    score = length - abs(u - length / 2) * 0.1
                    if key not in choices or score > choices[key][0]:
                        choices[key] = score, i, u
            for _, i, u in choices.values():
                doors.add(i)
                portal_centres[i] = u
    result = []
    for i, (a, b, left, right) in enumerate(segments):
        length = math.dist(a, b)
        both = left is not None and right is not None
        if rampart and both:
            continue
        low_wall = rampart and not both and (left or right) == "wallwalk"
        wall_height = 1.0 if low_wall else height
        openings = []
        if i in doors:
            width = min(max(1.05, 1.2 * scale), length - 0.10)
            if "stairwell" in (left, right):
                # Both U-stair flights meet this one broad landing door.
                width = length - 0.08
            openings.append(
                Opening(
                    portal_centres.get(i, length / 2) - width / 2,
                    portal_centres.get(i, length / 2) + width / 2,
                    0,
                    min(2.4, height - 0.2),
                    "DOOR",
                )
            )
        if main_entry and not both:
            distance, t, _ = segment_projection(main_entry, a, b)
            if distance < 0.05:
                width = max(1.5, 1.9 * scale)
                openings = [
                    Opening(
                        t * length - width / 2,
                        t * length + width / 2,
                        0,
                        min(3.0, height - 0.2),
                        "ENTRY",
                    )
                ]
        if not both and not low_wall:
            tx, ty = (b[0] - a[0]) / length, (b[1] - a[1]) / length
            nx, ny = (ty, -tx) if left else (-ty, tx)
            count = (
                max(1, round(length / max(2.2, 2.7 * scale)))
                if length > 0.65
                else 0
            )
            for n in range(count):
                centre = (n + 0.5) * length / count
                width = min(0.85 * scale, length / count * 0.35)
                win_start, win_end = centre - width / 2, centre + width / 2
                if any(
                    o.start - 0.25 < win_end and win_start < o.end + 0.25
                    for o in openings
                ):
                    continue
                win_bot = 1.15
                win_top = min(2.7, height - 0.35)
                if architecture:
                    p, q = [
                        tuple(
                            a[j] + (b[j] - a[j]) * u / length for j in (0, 1)
                        )
                        for u in (win_start - 0.16, win_end + 0.16)
                    ]
                    out_p = (
                        p[0] + nx * (WALL / 2 + 0.20),
                        p[1] + ny * (WALL / 2 + 0.20),
                    )
                    out_q = (
                        q[0] + nx * (WALL / 2 + 0.20),
                        q[1] + ny * (WALL / 2 + 0.20),
                    )
                    if window_under_roof(
                        architecture, p, q, z + win_bot, z + win_top
                    ) or window_under_roof(
                        architecture, out_p, out_q, z + win_bot, z + win_top
                    ):
                        continue
                    if any(
                        t.base > 0
                        and BASE + t.base - 1.25 * scale - 0.15 < z + win_top
                        and z + win_bot < BASE + t.base + 0.15
                        and segment_projection(t.centre, p, q)[0]
                        < t.radius + 0.15
                        for t in architecture.towers
                    ):
                        continue
                openings.append(
                    Opening(win_start, win_end, win_bot, win_top, "WINDOW")
                )
        result.append(
            InteriorWall(
                f"{identifier}_wall_{i}",
                a,
                b,
                z,
                wall_height,
                PARTITION if both else WALL,
                (left, right),
                tuple(openings),
            )
        )
    return (tuple(result), portal_grid) if with_portal_grid else tuple(result)


def _spiral(tower, lower, upper, z, top, angle):
    outer = tower.radius - WALL - 0.08
    inner = max(0.22, outer - max(0.90, tower.radius * 0.62))
    polygon = tuple(
        (
            tower.centre[0] + r * math.cos(angle + math.radians(a)),
            tower.centre[1] + r * math.sin(angle + math.radians(a)),
        )
        for r, angles in (
            (outer, range(30, 331, 10)),
            (inner, range(330, 29, -10)),
        )
        for a in angles
    )
    radius = (inner + outer) / 2
    p = (
        tower.centre[0] + radius * math.cos(angle),
        tower.centre[1] + radius * math.sin(angle),
    )
    return CastleStair(
        f"{tower.id}_{lower}",
        "SPIRAL",
        lower,
        upper,
        z,
        top,
        polygon,
        (*p, z),
        (*p, top),
        math.ceil((top - z) / 0.18),
        outer - inner,
        centre=tower.centre,
        inner=inner,
        outer=outer,
        angle=angle,
    )


def _circulation_shapes(shapes, architecture, index, landing_y):
    s = architecture.scale
    blocks = {b.id: b for b in architecture.blocks}
    palas, donjon, fore, chapel = (
        blocks[n] for n in ("palas", "donjon", "forewing", "chapel")
    )
    px1, py1 = block_polygon(palas)[0]
    px2, py2 = block_polygon(palas)[2]
    fx1, fy1 = block_polygon(fore)[0]
    fx2, fy2 = block_polygon(fore)[2]
    cx1, cy1 = block_polygon(chapel)[0]
    cx2, cy2 = block_polygon(chapel)[2]
    _, dy1 = block_polygon(donjon)[0]
    w = max(1.5, 1.6 * s)
    front = architecture.entry[1]
    west, east = px1 + w / 2, px2 - w / 2
    back_top = py2 if index < palas.storeys else landing_y + w / 2
    strips = [rectangle(fx1, dy1, cx2 + s, back_top)]
    if index < palas.storeys:
        strips += [
            rectangle(west - w / 2, front, west + w / 2, py2),
            rectangle(east - w / 2, front, east + w / 2, py2),
            rectangle(px1, front, cx2, front + w),
        ]
    if index < fore.storeys:
        strips += [
            rectangle(fx1, fy2 - w, west + w / 2, fy2),
            rectangle(fx1, fy1, fx1 + w, fy2),
            rectangle(fx1, fy1 + s, fx1 + 3.5 * s, fy1 + 5 * s),
        ]
    if index < chapel.storeys:
        strips += [
            rectangle(cx2 - w, cy1, cx2, cy2),
            rectangle(cx2 - 3.1 * s, cy1, cx2, cy1 + 4.2 * s),
        ]
    corridors = []
    for strip in strips:
        for name, polygon in shapes:
            if name == "stairwell":
                continue
            clipped = clip_polygon(strip, polygon)
            if polygon_area(clipped) > 0.02:
                corridors.append((f"passage_{index}", tuple(clipped)))
    special = []
    if index == 0:
        special += [
            (
                "pantry_0",
                rectangle(fx2 - 2.5 * s, fy1, fx2, fy1 + 3.0 * s),
            ),
            ("vestry_0", rectangle(cx1, cy1 + 8.2 * s, cx2 - w, cy2)),
        ]
    if index in (2, 3):
        special.append(
            (
                f"guest_chamber_{index}"
                if index == 2
                else f"lady_chamber_{index}",
                rectangle(palas.centre[0], py1, px2, py2),
            )
        )
    stairwell = [(n, p) for n, p in shapes if n == "stairwell"]
    towers = [(n, p) for n, p in shapes if "tower" in n]
    return (
        stairwell
        + towers
        + corridors
        + special
        + [(n, p) for n, p in shapes if n != "stairwell" and "tower" not in n]
    )


def _room_kind(name, index):
    prefix = name.rsplit("_", 1)[0]
    extra = {
        "passage": "SCREEN_PASSAGE" if index == 0 else "LANDING_GALLERY",
        "pantry": "PANTRY",
        "vestry": "VESTRY",
        "guest_chamber": "GUEST_CHAMBER",
        "lady_chamber": "LADY_BEDROOM",
    }
    return extra.get(
        prefix,
        PROGRAM[prefix][index] if prefix in PROGRAM else "TOWER_LANDING",
    )


def _room_zone(kind):
    if kind in ("LORD_BEDROOM", "LADY_BEDROOM", "SOLAR", "TREASURY", "STUDY"):
        return "PRIVATE", 2
    if kind in ("KITCHEN", "PANTRY", "STOREROOM", "SERVANT_CHAMBER", "VESTRY"):
        return "SERVICE", 1
    if kind in (
        "TOWER_LANDING",
        "BARRACKS",
        "ARMOURY",
        "GUARDROOM",
        "WATCH_ROOM",
    ):
        return "DEFENCE", 1
    if kind in ("SCREEN_PASSAGE", "LANDING_GALLERY"):
        return "CIRCULATION", 0
    return "PUBLIC", 0


def _core_levels(architecture):
    s, fh = architecture.scale, architecture.floor_height
    donjon = next(b for b in architecture.blocks if b.id == "donjon")
    left = donjon.centre[0] - donjon.size[0] / 2 + 0.5
    back = donjon.centre[1] + donjon.size[1] / 2 - 0.5
    main = [
        _u_stair(
            f"main_stair_{i}",
            f"core_{i}",
            f"core_{i + 1}",
            BASE + i * fh,
            BASE + (i + 1) * fh,
            left,
            back,
            s,
        )
        for i in range(donjon.storeys - 1)
    ]
    levels, rooms, spirals, tower_angles = [], [], [], {}
    count = max(
        donjon.storeys,
        max(
            math.floor((t.base + t.height - 1.8) / fh) + 1
            for t in architecture.towers
        ),
    )
    for index in range(count):
        identifier, z = f"core_{index}", BASE + index * fh
        active_towers = [
            t
            for t in architecture.towers
            if t.base - 0.01 <= index * fh < t.base + t.height - 1.8
        ]
        shapes = (
            [("stairwell", main[0].polygon)] if index < donjon.storeys else []
        )
        shapes += [
            (
                f"donjon_{index}" if t.base > 0 else f"{t.id}_{index}",
                circle(t.centre, t.radius, 8),
            )
            for t in sorted(active_towers, key=lambda t: -t.base)
        ]
        blocks = sorted(architecture.blocks, key=lambda b: b.id != "donjon")
        shapes += [
            (f"{b.id}_{index}", block_polygon(b))
            for b in blocks
            if index < b.storeys
        ]
        shapes = _circulation_shapes(
            shapes, architecture, index, main[0].start[1]
        )
        walls, portal_grid = _walls(
            identifier,
            shapes,
            z,
            fh,
            s,
            architecture.entry[:2] if index == 0 else None,
            architecture=architecture,
            with_portal_grid=True,
        )
        holes = [main[0].polygon] if 0 < index < donjon.storeys else []
        for tower in active_towers:
            if tower.base > 0:
                continue
            name = f"{tower.id}_{index}"
            portals = [
                (wall, opening)
                for wall in walls
                if name in wall.sides
                for opening in wall.openings
                if opening.kind == "DOOR"
            ]
            if tower.id not in tower_angles:
                if not portals:
                    raise ValueError(
                        f"Tower has no interior connection: {name}"
                    )
                wall, opening = max(
                    portals,
                    key=lambda pair: (
                        _door_side_cell(
                            portal_grid,
                            (pair[0].a, pair[0].b, *pair[0].sides),
                            name,
                        )
                        is not None,
                        any(
                            n and n.startswith("passage_")
                            for n in pair[0].sides
                        ),
                        pair[1].end - pair[1].start,
                    ),
                )
                t = (
                    (opening.start + opening.end)
                    / 2
                    / math.dist(wall.a, wall.b)
                )
                door = tuple(
                    wall.a[i] + (wall.b[i] - wall.a[i]) * t for i in (0, 1)
                )
                tower_angles[tower.id] = math.atan2(
                    door[1] - tower.centre[1], door[0] - tower.centre[0]
                )
            angle = tower_angles[tower.id]
            spiral = _spiral(
                tower, identifier, f"core_{index + 1}", z, z + fh, angle
            )
            holes.append(circle(tower.centre, spiral.inner, 12))
            if (index + 1) * fh < tower.height - 1.8:
                spirals.append(spiral)
            if index:
                holes.append(
                    _spiral(
                        tower, "unused", identifier, z - fh, z, angle
                    ).polygon
                )
        regions = planar_regions(tuple(shapes), tuple(holes))
        for name in dict.fromkeys(name for name, _ in shapes):
            if name == "stairwell":
                continue
            kind = _room_kind(name, index)
            owned = tuple(p for owner, p in regions if owner == name)
            if owned:
                zone, privacy = _room_zone(kind)
                rooms.append(
                    CastleRoom(
                        name,
                        kind,
                        identifier,
                        owned,
                        zone=zone,
                        privacy=privacy,
                        area=sum(polygon_area(p) for p in owned),
                    )
                )
        levels.append(
            InteriorLevel(
                identifier,
                index,
                z,
                fh,
                tuple(shapes),
                regions,
                tuple(holes),
                walls,
            )
        )
    return levels, rooms, main + spirals


def _defences(architecture):
    s, z = architecture.scale, BASE + architecture.wall_height
    width = max(2.2, 2.0 * s)
    height = max(2.8, 3.2 * s)
    shapes = [
        (name, circle(centre, radius, 8))
        for name, centre, radius in defensive_towers(architecture)
    ]
    y = architecture.outline[0][1]
    gx = architecture.gate_width / 2 + 1.8 * s
    shapes.append(("gatehouse", rectangle(-gx, y - 1.8 * s, gx, y + 1.8 * s)))
    for a, b in edges(architecture.outline):
        length = math.dist(a, b)
        nx, ny = -(b[1] - a[1]) / length, (b[0] - a[0]) / length
        shapes.append(
            (
                "wallwalk",
                tuple(
                    (
                        p[0] + nx * width / 2 * side,
                        p[1] + ny * width / 2 * side,
                    )
                    for p, side in ((a, -1), (b, -1), (b, 1), (a, 1))
                ),
            )
        )
    shapes += [
        ("wallwalk", circle(p, width * 0.65, 12)) for p in architecture.outline
    ]
    wall_stair = _u_stair(
        "courtyard_wall_stair",
        "courtyard",
        "rampart",
        BASE,
        z,
        -architecture.scale * 7.8,
        0,
        s,
    )
    depth = wall_stair.polygon[2][1] - wall_stair.polygon[0][1]
    back = y + 3.2 + depth
    wall_stair = _u_stair(
        "courtyard_wall_stair",
        "courtyard",
        "rampart",
        BASE,
        z,
        -architecture.scale * 7.8,
        back,
        s,
    )
    ex = wall_stair.end[0]
    shapes.insert(
        len(defensive_towers(architecture)) + 1,
        (
            "wallwalk",
            rectangle(ex - 0.7, y, ex + 0.7, wall_stair.end[1] + 0.75),
        ),
    )
    shapes.append(("wallwalk", wall_stair.polygon))
    walls = _walls("rampart", shapes, z, height, s, rampart=True)
    regions = planar_regions(tuple(shapes), (wall_stair.polygon,))
    rooms = [
        CastleRoom(
            name,
            "GUARDROOM",
            "rampart",
            tuple(p for owner, p in regions if owner == name),
        )
        for name in dict(shapes)
        if name != "wallwalk"
    ]
    level = InteriorLevel(
        "rampart",
        1,
        z,
        height,
        tuple(shapes),
        regions,
        (wall_stair.polygon,),
        walls,
    )
    return level, rooms, wall_stair


class WalkGrid:
    """Check clearance against the polygons used by the meshes."""

    def __init__(self, level, extra_holes=()):
        self.level = level
        self.holes = level.holes + tuple(extra_holes)
        self.wall_index = SpatialHash(4)
        for index, wall in enumerate(level.walls):
            self.wall_index.insert(
                index,
                (
                    min(wall.a[0], wall.b[0]),
                    min(wall.a[1], wall.b[1]),
                    max(wall.a[0], wall.b[0]),
                    max(wall.a[1], wall.b[1]),
                ),
            )
        points = [p for _, polygon in level.shapes for p in polygon]
        self.free = set()
        self.owners = {}
        self.furniture_bounds = []
        self.furniture_context = {}
        self.furniture_access = []
        for ix in range(
            math.floor(min(p[0] for p in points) / GRID),
            math.ceil(max(p[0] for p in points) / GRID) + 1,
        ):
            for iy in range(
                math.floor(min(p[1] for p in points) / GRID),
                math.ceil(max(p[1] for p in points) / GRID) + 1,
            ):
                point = (ix * GRID, iy * GRID)
                owner = owner_at(point, level.shapes)
                if not owner or owner == "stairwell" or self.blocked(point):
                    continue
                self.free.add((ix, iy))
                self.owners[(ix, iy)] = owner

    def blocked(self, point):
        if any(
            inside_polygon(point, p)
            or min(segment_projection(point, a, b)[0] for a, b in edges(p))
            < AGENT_RADIUS
            for p in self.holes
        ):
            return True
        for index in self.wall_index.query(point, 1):
            wall = self.level.walls[index]
            distance, t, _ = segment_projection(point, wall.a, wall.b)
            if distance > AGENT_RADIUS + wall.thickness / 2 + 0.025:
                continue
            u = t * math.dist(wall.a, wall.b)
            if not any(
                o.bottom < 0.1
                and o.top > 1.8
                and o.start + AGENT_RADIUS < u < o.end - AGENT_RADIUS
                for o in wall.openings
            ):
                return True
        return False

    def nearest(self, point, owner=None):
        candidates = [
            cell
            for cell in self.free
            if owner is None or self.owners[cell] == owner
        ]
        if not candidates:
            raise ValueError(f"No walkable floor in {self.level.id}: {owner}")
        return min(
            candidates,
            key=lambda cell: (math.dist(self.point(cell), point[:2]), cell),
        )

    @staticmethod
    def point(cell):
        return cell[0] * GRID, cell[1] * GRID

    def flood(self, root, free=None):
        free = self.free if free is None else free
        parents, queue = {root: None}, deque([root])
        while queue:
            x, y = queue.popleft()
            for cell in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if cell in free and cell not in parents:
                    parents[cell] = (x, y)
                    queue.append(cell)
        return parents


def _room_entry(room, level, centre):
    portals = []
    for wall in level.walls:
        if room.id not in wall.sides:
            continue
        length = math.dist(wall.a, wall.b)
        tx, ty = (
            (wall.b[0] - wall.a[0]) / length,
            (wall.b[1] - wall.a[1]) / length,
        )
        sign = 1 if room.id == wall.sides[0] else -1
        for opening in wall.openings:
            if opening.bottom > 0.1:
                continue
            u = (opening.start + opening.end) / 2
            p = (
                wall.a[0] + tx * u - ty * sign * 0.7,
                wall.a[1] + ty * u + tx * sign * 0.7,
            )
            priority = (
                0
                if any(n and n.startswith("passage_") for n in wall.sides)
                else 1
            )
            portals.append((priority, math.dist(p, centre), p))
    return min(portals)[2] if portals else centre


def _furniture_score(room, grid, kind, spec, cell):
    p = grid.point(cell)
    if room.id not in grid.furniture_context:
        points = [p for polygon in room.regions for p in polygon]
        centre = (
            sum(p[0] for p in points) / len(points),
            sum(p[1] for p in points) / len(points),
        )
        walls = [wall for wall in grid.level.walls if room.id in wall.sides]
        grid.furniture_context[room.id] = points, centre, walls
    points, centre, walls = grid.furniture_context[room.id]
    gap = min((segment_projection(p, w.a, w.b)[0] for w in walls), default=2)
    if kind in ("bed", "wardrobe", "shelf", "chest", "hearth", "weapon_rack"):
        return (
            abs(gap - spec.size[1] / 2 - 0.25) * 4
            + math.dist(p, centre) * 0.02
        )
    if kind == "altar":
        target = (centre[0], max(p[1] for p in points) - 0.8)
        return math.dist(p, target)
    if kind == "desk":
        windows = [
            w for w in walls if any(o.kind == "WINDOW" for o in w.openings)
        ]
        return min(
            (segment_projection(p, w.a, w.b)[0] for w in windows),
            default=math.dist(p, centre),
        )
    return math.dist(p, centre)


def _furniture(room, grid, essential, rng):
    items, warnings = [], []
    candidates = [c for c in grid.free if grid.owners[c] == room.id]
    candidates.sort()
    rng.shuffle(candidates)
    program = FURNISHINGS.get(room.kind, ())
    if room.kind == "GREAT_HALL" and room.area < 75:
        program = ("banquet_table", "bench", "bench", "hearth")
    for kind in program:
        spec = CATALOG[kind]
        anchor_kind = {
            "bench": "banquet_table",
            "lamp": "bed",
            "chair": "desk",
            "pew": "altar",
        }.get(kind)
        anchor = next(
            (
                item
                for item in items
                if item.kind == anchor_kind
                and (
                    kind != "bench"
                    or sum(v.anchor_id == item.id for v in items) < 2
                )
            ),
            None,
        )
        ordered = sorted(
            candidates,
            key=lambda c: _furniture_score(room, grid, kind, spec, c),
        )
        headings = (0, math.pi / 2, math.pi, math.pi * 1.5)
        if anchor:
            x, y = anchor.position[:2]
            angle = anchor.heading
            if kind == "lamp":
                offsets = [
                    (side * (anchor.size[0] / 2 + 0.6), anchor.size[1] * 0.32)
                    for side in (-1, 1)
                ]
            elif kind == "bench":
                offsets = [
                    (0, side * (anchor.size[1] / 2 + spec.size[1] / 2 + 0.8))
                    for side in (-1, 1)
                ]
            else:
                row = sum(item.kind == kind for item in items)
                offsets = [
                    (
                        0,
                        -(
                            anchor.size[1] / 2
                            + spec.size[1] / 2
                            + 0.8
                            + row * 0.95
                        ),
                    )
                ]
            targets = [
                (
                    x + u * math.cos(angle) - v * math.sin(angle),
                    y + u * math.sin(angle) + v * math.cos(angle),
                )
                for u, v in offsets
            ]
            ordered = sorted(
                candidates,
                key=lambda c: min(
                    math.dist(grid.point(c), p) for p in targets
                ),
            )
            facing = angle + math.pi if kind in ("chair", "pew") else angle
            headings = (
                (facing,)
                if kind in ("chair", "pew")
                else tuple(dict.fromkeys((facing, 0, math.pi / 2)))
            )
        placed = False
        for cell in ordered[:180]:
            point = grid.point(cell)
            for heading in headings:
                front = (
                    point[0] + math.sin(heading) * (spec.size[1] / 2 + 0.55),
                    point[1] - math.cos(heading) * (spec.size[1] / 2 + 0.55),
                )
                access_kind = kind in (
                    "bed",
                    "wardrobe",
                    "hearth",
                    "shelf",
                    "chest",
                    "weapon_rack",
                    "altar",
                )
                if access_kind and (
                    owner_at(front, grid.level.shapes) != room.id
                    or grid.blocked(front)
                ):
                    continue
                if access_kind and any(
                    inside_polygon(front, p)
                    or min(
                        segment_projection(front, a, b)[0] for a, b in edges(p)
                    )
                    < 0.25
                    for p in grid.furniture_bounds
                ):
                    continue
                corners = oriented_corners(
                    point, *spec.size[:2], heading, 0.18
                )
                if any(
                    owner_at(p, grid.level.shapes) != room.id for p in corners
                ):
                    continue
                if any(
                    polygons_overlap(corners, other)
                    for other in grid.furniture_bounds
                ):
                    continue
                if any(polygons_overlap(corners, hole) for hole in grid.holes):
                    continue
                if any(
                    segment_projection(p, wall.a, wall.b)[0]
                    < wall.thickness / 2 + 0.02
                    for p in corners
                    for i in grid.wall_index.query(p, 0.6)
                    for wall in (grid.level.walls[i],)
                ):
                    continue
                if any(
                    math.dist(point, grid.point(c))
                    < max(spec.size[:2]) / 2 + 0.8
                    for c in essential
                ):
                    continue
                removed = {
                    c
                    for c in grid.free
                    if rectangle_distance(
                        grid.point(c), point, *spec.size[:2], heading
                    )
                    < AGENT_RADIUS + 0.08
                }
                if removed & essential:
                    continue
                if any(
                    rectangle_distance(p, point, *spec.size[:2], heading)
                    < AGENT_RADIUS + 0.08
                    for p in grid.furniture_access
                ):
                    continue
                free = grid.free - removed
                if (
                    access_kind
                    and min(
                        (math.dist(front, grid.point(c)) for c in free),
                        default=math.inf,
                    )
                    > 0.25
                ):
                    continue
                visited = grid.flood(next(iter(sorted(essential))), free)
                if not essential <= visited.keys():
                    continue
                access_cell = min(
                    free, key=lambda c: math.dist(front, grid.point(c))
                )
                if access_kind and access_cell not in visited:
                    continue
                grid.free = free
                grid.furniture_bounds.append(corners)
                if access_kind:
                    grid.furniture_access.append(front)
                    essential.add(access_cell)
                items.append(
                    CastleFurniture(
                        f"{room.id}_{kind}_{len(items)}",
                        kind,
                        room.id,
                        room.level,
                        (*point, grid.level.z),
                        spec.size,
                        heading,
                        anchor.id if anchor else "",
                        (*front, grid.level.z) if access_kind else (),
                    )
                )
                placed = True
                break
            if placed:
                break
        if not placed:
            warnings.append(f"{room.id}: no clear placement for {kind}")
    return items, warnings


def _navigation(levels, rooms, stairs, architecture, furnish, seed):
    nodes, edges_, by_id, grids = [], [], {}, {}
    rooms = list(rooms)
    targets = defaultdict(list)
    for room in rooms:
        points = [p for polygon in room.regions for p in polygon]
        centre = (
            sum(p[0] for p in points) / len(points),
            sum(p[1] for p in points) / len(points),
        )
        targets[room.level].append((room.id, centre))
    for stair in stairs:
        targets[stair.lower].append((stair.id + "_lower", stair.start[:2]))
        targets[stair.upper].append((stair.id + "_upper", stair.end[:2]))
    entry = architecture.entry
    targets["core_0"].append(("interior_entry", (entry[0], entry[1] + 0.75)))
    targets["courtyard"] += [
        ("courtyard_entry", (entry[0], entry[1] - 0.75)),
        ("castle_gate_inside", (0, architecture.outline[0][1] + 2.0)),
    ]
    items, warnings = [], []
    rng = random.Random(f"{seed}:castle-furniture")
    for level in levels:
        extra = tuple(
            stair.polygon for stair in stairs if stair.lower == level.id
        )
        grid = WalkGrid(level, extra)
        grids[level.id] = grid
        essential, cells = set(), {}
        room_ids = {r.id for r in rooms if r.level == level.id}
        room_map = {r.id: r for r in rooms if r.level == level.id}
        for name, point in targets[level.id]:
            if name in room_map and room_map[name].zone != "CIRCULATION":
                point = _room_entry(room_map[name], level, point)
            cell = grid.nearest(point, name if name in room_ids else None)
            if (
                name not in room_ids
                and math.dist(grid.point(cell), point) > 1.1
            ):
                raise ValueError(f"Blocked stair/entry landing: {name}")
            cells[name] = cell
            essential.add(cell)
        components, by_cell = [], {}
        for cell in cells.values():
            if cell not in by_cell:
                visited = grid.flood(cell)
                component = essential & visited.keys()
                components.append(component)
                by_cell.update((c, component) for c in component)
        for i, component in enumerate(components):
            visited = grid.flood(min(component))
            circulation = [
                c for c in visited if grid.owners[c].startswith("passage_")
            ]
            if circulation:
                hub = min(
                    circulation,
                    key=lambda c: (
                        min(
                            math.dist(grid.point(c), grid.point(p))
                            for p in component
                        ),
                        c,
                    ),
                )
                name = f"circulation_hub_{level.id}_{i}"
                cells[name] = hub
                essential.add(hub)
                component.add(hub)
        if furnish:
            for room in rooms:
                if room.level == level.id:
                    component = by_cell[cells[room.id]]
                    furniture, notes = _furniture(room, grid, component, rng)
                    items.extend(furniture)
                    warnings.extend(notes)
        for component in components:
            members = [
                (name, c) for name, c in cells.items() if c in component
            ]
            members.sort(
                key=lambda item: not item[0].startswith("circulation_hub")
            )
            root, root_id = members[0][1], len(nodes)
            parents = grid.flood(root)
            for name, cell in members:
                position = (*grid.point(cell), level.z)
                by_id[name] = len(nodes)
                nodes.append(
                    {
                        "id": len(nodes),
                        "name": name,
                        "position": position,
                        "level": level.id,
                    }
                )
                path, cursor = [cell], cell
                while cursor != root:
                    cursor = parents[cursor]
                    path.append(cursor)
                points = tuple(
                    (*grid.point(c), level.z) for c in reversed(path)
                )
                if by_id[name] != root_id:
                    edges_.append(
                        {
                            "a": root_id,
                            "b": by_id[name],
                            "kind": "CORRIDOR",
                            "width": AGENT_RADIUS * 2,
                            "path": points,
                            "length": (len(points) - 1) * GRID,
                        }
                    )
        for i, room in enumerate(rooms):
            if room.level == level.id:
                rooms[i] = replace(
                    room, position=nodes[by_id[room.id]]["position"]
                )
    for stair in stairs:
        a, b = by_id[stair.id + "_lower"], by_id[stair.id + "_upper"]
        path = (nodes[a]["position"], *stair_path(stair), nodes[b]["position"])
        edges_.append(
            {
                "a": a,
                "b": b,
                "kind": "STAIR",
                "stairs_id": stair.id,
                "width": stair.width,
                "length": sum(
                    math.dist(p, q)
                    for p, q in zip(path, path[1:], strict=False)
                ),
                "path": path,
            }
        )
    a, b = by_id["courtyard_entry"], by_id["interior_entry"]
    edges_.append(
        {
            "a": a,
            "b": b,
            "kind": "DOOR",
            "width": 1.5,
            "length": math.dist(nodes[a]["position"], nodes[b]["position"]),
            "path": (nodes[a]["position"], nodes[b]["position"]),
        }
    )
    navigation = {
        "nodes": nodes,
        "edges": edges_,
        "entry_node": by_id["interior_entry"],
        "gate_node": by_id["castle_gate_inside"],
        "agent_radius": AGENT_RADIUS,
        "agent_height": 1.7,
    }
    adjacent = defaultdict(set)
    for edge in edges_:
        adjacent[edge["a"]].add(edge["b"])
        adjacent[edge["b"]].add(edge["a"])
    visited, queue = {navigation["entry_node"]}, [navigation["entry_node"]]
    while queue:
        for node in adjacent[queue.pop()] - visited:
            visited.add(node)
            queue.append(node)
    if len(visited) != len(nodes):
        missing = [n["name"] for n in nodes if n["id"] not in visited]
        raise ValueError(f"Unreachable castle spaces: {missing}")
    return tuple(rooms), tuple(items), navigation, tuple(warnings)


@lru_cache(maxsize=24)
def make_castle_interior(architecture, seed, *, furnish=True):
    """Design every core floor and the defended wall circuit."""
    if architecture.scale < 0.80 - 1e-6:
        raise ValueError(
            "성 실내에는 성 반경 19.2m 이상이 필요합니다. "
            "도시 크기를 늘리세요."
        )
    levels, rooms, stairs = _core_levels(architecture)
    rampart, guards, wall_stair = _defences(architecture)
    stairs.append(wall_stair)
    core_shapes = tuple(
        (name, p) for name, p in levels[0].shapes if name != "stairwell"
    )
    holes = tuple(p for _, p in core_shapes)
    courtyard_regions = planar_regions(
        (("courtyard", architecture.outline),), holes
    )
    outer_walls = _walls(
        "courtyard",
        (("courtyard", architecture.outline),),
        BASE,
        architecture.wall_height,
        architecture.scale,
        (0, architecture.outline[0][1]),
    )
    courtyard = InteriorLevel(
        "courtyard",
        0,
        BASE,
        architecture.wall_height,
        (("courtyard", architecture.outline),),
        courtyard_regions,
        holes + (wall_stair.polygon,),
        outer_walls + levels[0].walls,
    )
    levels.extend((rampart, courtyard))
    rooms.extend(guards)
    rooms = [
        replace(
            room,
            zone=_room_zone(room.kind)[0],
            privacy=_room_zone(room.kind)[1],
            area=sum(polygon_area(p) for p in room.regions),
        )
        for room in rooms
    ]
    rooms, furniture, navigation, warnings = _navigation(
        levels, rooms, stairs, architecture, furnish, seed
    )
    return CastleInterior(
        architecture.floor_height,
        tuple(levels),
        rooms,
        tuple(stairs),
        furniture,
        navigation,
        warnings,
    )
