"""Blender-independent layout and clipping rules (metres, Z up)."""

import math
import random
from dataclasses import asdict, dataclass

from art_style import validate_art_style

WALL_STYLES = ("BRICK", "WOOD_HORIZONTAL", "WOOD_VERTICAL", "PLASTER")
ROOF_STYLES = ("GABLE", "HIP", "SHED", "FLAT")
PALETTES = ("WARM", "PASTEL", "COASTAL")
ARCHITECTURES = ("SIMPLE", "MEDIEVAL")
EPSILON = 1e-8
FOUNDATION_HEIGHT = 0.30
WALL_THICKNESS = 0.16
PARTITION_THICKNESS = 0.10


@dataclass(frozen=True)
class HouseConfig:
    seed: int = 42
    detail_seed: int = 7
    width: float = 6.4
    depth: float = 5.4
    floors: int = 2
    floor_height: float = 2.55
    variation: float = 0.08
    wall_style: str = "PLASTER"
    roof_style: str = "GABLE"
    roof_pitch: float = 40.0
    overhang: float = 0.55
    window_width: float = 1.05
    window_height: float = 1.10
    window_spacing: float = 2.0
    brick_width: float = 0.58
    brick_height: float = 0.28
    plank_width: float = 0.26
    bevel: float = 0.018
    palette: str = "WARM"
    roof_tiles: bool = True
    shutters: bool = True
    interior: bool = True
    furnish: bool = True
    interior_seed: int = 17
    walkway_width: float = 0.8
    furniture_catalog: str = ""
    architecture: str = "MEDIEVAL"
    door_open: bool = False
    art_style: str = "CARTOON"

    def validate(self):
        validate_art_style(self.art_style)
        ranges = {
            "width": (4.0, 16.0),
            "depth": (4.0, 16.0),
            "floor_height": (2.4, 3.5),
            "variation": (0.0, 0.20),
            "roof_pitch": (10.0, 50.0),
            "overhang": (0.20, 0.80),
            "window_width": (0.65, 1.50),
            "window_height": (0.65, 1.40),
            "window_spacing": (1.70, 3.20),
            "brick_width": (0.35, 1.20),
            "brick_height": (0.18, 0.50),
            "plank_width": (0.18, 0.50),
            "bevel": (0.0, 0.035),
            "walkway_width": (0.6, 1.0),
        }
        for name, (low, high) in ranges.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a number")
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{name} must be between {low} and {high}")
        for name in ("seed", "detail_seed", "interior_seed"):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 2_000_000_000:
                raise ValueError(
                    f"{name} must be an integer in [0, 2000000000]"
                )
        if type(self.floors) is not int or not 1 <= self.floors <= 3:
            raise ValueError("floors must be an integer in [1, 3]")
        for name, choices in (
            ("wall_style", WALL_STYLES),
            ("roof_style", ROOF_STYLES),
            ("palette", PALETTES),
            ("architecture", ARCHITECTURES),
        ):
            if getattr(self, name) not in choices:
                raise ValueError(f"{name} must be one of {choices}")
        for name in (
            "roof_tiles",
            "shutters",
            "interior",
            "furnish",
            "door_open",
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        if not isinstance(self.furniture_catalog, str):
            raise ValueError("furniture_catalog must be a path string")
        return self

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class Opening:
    kind: str
    x1: float
    z1: float
    x2: float
    z2: float

    @property
    def rectangle(self):
        return (self.x1, self.z1, self.x2, self.z2)


@dataclass(frozen=True)
class Wall:
    name: str
    length: float
    start: tuple
    tangent: tuple
    normal: tuple
    profile: tuple
    openings: tuple


@dataclass(frozen=True)
class HousePlan:
    width: float
    depth: float
    floor_height: float
    height: float
    pitch: float
    walls: tuple
    roof_faces: tuple

    def as_dict(self):
        return asdict(self)


def rectangle(x1, z1, x2, z2):
    return [(x1, z1), (x2, z1), (x2, z2), (x1, z2)]


def polygon_area(points):
    return (
        abs(
            sum(
                a[0] * b[1] - b[0] * a[1]
                for a, b in zip(points, points[1:] + points[:1], strict=True)
            )
        )
        * 0.5
    )


def _clean_polygon(points):
    result = []
    for point in points:
        if not result or math.dist(point, result[-1]) > EPSILON:
            result.append(tuple(point))
    if len(result) > 1 and math.dist(result[0], result[-1]) < EPSILON:
        result.pop()
    return result


def _clip_half_plane(points, a, b, c):
    """Clip a polygon against a*x + b*y + c >= 0."""
    if not points:
        return []
    output = []
    previous = points[-1]
    previous_d = a * previous[0] + b * previous[1] + c
    for current in points:
        current_d = a * current[0] + b * current[1] + c
        inside = current_d >= -EPSILON
        previous_inside = previous_d >= -EPSILON
        if inside != previous_inside:
            t = previous_d / (previous_d - current_d)
            output.append(
                tuple(
                    previous[i] + t * (current[i] - previous[i])
                    for i in range(2)
                )
            )
        if inside:
            output.append(current)
        previous, previous_d = current, current_d
    return _clean_polygon(output)


def clip_polygon(subject, boundary):
    """Intersect convex polygons; boundary must be counterclockwise."""
    result = list(subject)
    boundary = list(boundary)
    for p, q in zip(boundary, boundary[1:] + boundary[:1], strict=True):
        dx, dy = q[0] - p[0], q[1] - p[1]
        result = _clip_half_plane(result, -dy, dx, dy * p[0] - dx * p[1])
    return result


def subtract_rectangle(polygon, hole):
    """Return disjoint convex pieces around a rectangular opening."""
    x1, z1, x2, z2 = hole
    if (
        max(p[0] for p in polygon) <= x1 + EPSILON
        or min(p[0] for p in polygon) >= x2 - EPSILON
        or max(p[1] for p in polygon) <= z1 + EPSILON
        or min(p[1] for p in polygon) >= z2 - EPSILON
    ):
        return [list(polygon)]
    left = _clip_half_plane(polygon, -1, 0, x1)
    right = _clip_half_plane(polygon, 1, 0, -x2)
    middle = _clip_half_plane(polygon, 1, 0, -x1)
    middle = _clip_half_plane(middle, -1, 0, x2)
    bottom = _clip_half_plane(middle, 0, -1, z1)
    top = _clip_half_plane(middle, 0, 1, -z2)
    return [
        piece
        for piece in (left, right, bottom, top)
        if len(piece) >= 3 and polygon_area(piece) > EPSILON
    ]


def without_openings(polygon, openings):
    pieces = [list(polygon)]
    for opening in openings:
        pieces = [
            part
            for piece in pieces
            for part in subtract_rectangle(piece, opening.rectangle)
        ]
    return pieces


def _openings(
    config,
    length,
    floor_height,
    wall_name,
    roof_faces=(),
    start=(0.0, 0.0),
    tangent=(1.0, 0.0),
    normal=(0.0, -1.0),
):
    rng = random.Random(f"{config.seed}:{wall_name}:windows")
    count = max(2, int(length / config.window_spacing))
    bay = length / count
    centres = [
        (i + 0.5) * bay
        + rng.uniform(-0.05, 0.05) * bay * (config.variation / 0.20)
        for i in range(count)
    ]
    door_index = min(range(count), key=lambda i: abs(centres[i] - length / 2))
    result = []
    window_width = min(config.window_width, bay * 0.55)
    window_height = min(config.window_height, floor_height - 1.20)
    planes = _roof_face_planes(roof_faces, 0.128 + 0.035)
    for floor in range(config.floors):
        bottom = floor * floor_height + 0.80
        for index, centre in enumerate(centres):
            if wall_name == "Front" and floor == 0 and index == door_index:
                width = min(1.10, bay * 0.66)
                result.append(
                    Opening(
                        "DOOR",
                        centre - width / 2,
                        0.0,
                        centre + width / 2,
                        2.08,
                    )
                )
            else:
                x1 = centre - window_width / 2
                x2 = centre + window_width / 2
                top = bottom + window_height
                if planes and floor == config.floors - 1:
                    top = _clamp_opening_top(
                        x1, x2, bottom, top, start, tangent, normal, planes
                    )
                if top - bottom >= 0.40:
                    result.append(Opening("WINDOW", x1, bottom, x2, top))
    return tuple(result)


def _roof_face_planes(faces, inset):
    result = []
    for face in faces:
        a, b, c = face[:3]
        u, v = (tuple(p[i] - a[i] for i in range(3)) for p in (b, c))
        n = (
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        )
        size = math.sqrt(sum(x * x for x in n))
        n = tuple(x / size for x in n)
        result.append((*n, sum(n[i] * a[i] for i in range(3)) - inset))
    return tuple(result)


def _clamp_opening_top(x1, x2, bottom, top, start, tangent, normal, planes):
    """Keep the top window frame inside roof clip planes."""
    margin = 0.085
    for u in (x1 - 0.08, x2 + 0.08):
        px = start[0] + tangent[0] * u + normal[0] * 0.16
        py = start[1] + tangent[1] * u + normal[1] * 0.16
        for nx, ny, nz, d in planes:
            if nz > 1e-6:
                limit = (
                    (d - nx * px - ny * py) / nz - FOUNDATION_HEIGHT - margin
                )
                if limit < top:
                    top = limit
    return top


def _roof_faces(config, width, depth, height, pitch):
    slope = math.tan(math.radians(pitch))
    a, b = width / 2 + config.overhang, depth / 2 + config.overhang
    base = FOUNDATION_HEIGHT + height
    if config.roof_style == "FLAT":
        return (((-a, -b, base), (a, -b, base), (a, b, base), (-a, b, base)),)
    if config.roof_style == "SHED":
        z_left = base + (width / 2 + a) * slope
        z_right = base + (width / 2 - a) * slope
        return (
            (
                (-a, -b, z_left),
                (a, -b, z_right),
                (a, b, z_right),
                (-a, b, z_left),
            ),
        )
    low = base - config.overhang * slope
    if config.roof_style == "GABLE":
        high = base + width / 2 * slope
        return (
            ((-a, -b, low), (0, -b, high), (0, b, high), (-a, b, low)),
            ((0, -b, high), (a, -b, low), (a, b, low), (0, b, high)),
        )
    # Hip roof: place the ridge along the longer footprint dimension.
    short, long = min(a, b), max(a, b)
    ridge = long - short
    high = low + short * slope
    faces = [
        [(-short, -long, low), (short, -long, low), (0, -ridge, high)],
        [
            (short, -long, low),
            (short, long, low),
            (0, ridge, high),
            (0, -ridge, high),
        ],
        [(short, long, low), (-short, long, low), (0, ridge, high)],
        [
            (-short, long, low),
            (-short, -long, low),
            (0, -ridge, high),
            (0, ridge, high),
        ],
    ]
    if a > b:
        faces = [[(-y, x, z) for x, y, z in face] for face in faces]
    return tuple(tuple(_clean_polygon(face)) for face in faces)


def roof_planes(plan, inset=0.0):
    """Upward roof planes: n dot p <= d is inside the building."""
    return _roof_face_planes(plan.roof_faces, inset)


def _wall_x_span(wall_start, tangent, opening):
    a = wall_start[0] + tangent[0] * opening.x1
    b = wall_start[0] + tangent[0] * opening.x2
    return min(a, b), max(a, b)


def _wall_y_span(wall_start, tangent, opening):
    a = wall_start[1] + tangent[1] * opening.x1
    b = wall_start[1] + tangent[1] * opening.x2
    return min(a, b), max(a, b)


def _clears_intervals(x, intervals):
    return not any(lo < x < hi for lo, hi in intervals)


def plan_interior_division(
    width, depth, floor_height, floors, walkway_width, front_wall, back_wall
):
    """Choose partition x and stair box clearing front/back openings."""
    bx1 = -width / 2 + WALL_THICKNESS
    bx2 = width / 2 - WALL_THICKNESS
    by1 = -depth / 2 + WALL_THICKNESS
    by2 = depth / 2 - WALL_THICKNESS
    entrance = next(o for o in front_wall.openings if o.kind == "DOOR")
    door_lo, door_hi = _wall_x_span(
        front_wall.start, front_wall.tangent, entrance
    )
    entry_x = (door_lo + door_hi) / 2
    half_part = PARTITION_THICKNESS / 2
    pad = 0.075 + half_part + 0.015
    intervals = [
        (lo - pad, hi + pad)
        for wall in (front_wall, back_wall)
        for o in wall.openings
        for lo, hi in (_wall_x_span(wall.start, wall.tangent, o),)
    ]
    if floors <= 1:
        lo_bound = bx1 + 2.2 + half_part
        hi_bound = bx2 - 2.2 - half_part
        if lo_bound > hi_bound:
            return None, False, None
        centre = (bx1 + bx2) / 2
        candidates = [centre] + [
            edge for a, b in intervals for edge in (a - 1e-4, b + 1e-4)
        ]
        valid = [
            x
            for x in candidates
            if lo_bound - 1e-6 <= x <= hi_bound + 1e-6
            and _clears_intervals(x, intervals)
        ]
        if not valid:
            return None, False, None
        split = min(valid, key=lambda x: abs(x - centre))
        return split, False, None

    flight = max(0.72, walkway_width)
    hall_width = flight * 2 + 0.12 + 0.16
    count = math.ceil(floor_height / 0.36)
    length = min(count * 0.23 + flight, (by2 - by1) - walkway_width - 0.24)
    if length <= flight + count * 0.10 or hall_width >= (bx2 - bx1) - 0.6:
        return None, True, None

    preferred_right = entry_x >= -0.05
    best = None
    for hall_right in (preferred_right, not preferred_right):
        if hall_right:
            nominal = bx2 - hall_width - half_part
            lo_lim = bx1 + 0.60 + half_part
            hi_lim = nominal
        else:
            nominal = bx1 + hall_width + half_part
            lo_lim = nominal
            hi_lim = bx2 - 0.60 - half_part
        if lo_lim > hi_lim + 1e-6:
            continue
        candidates = [nominal] + [
            edge for a, b in intervals for edge in (a - 1e-4, b + 1e-4)
        ]
        valid = [
            x
            for x in candidates
            if lo_lim - 1e-6 <= x <= hi_lim + 1e-6
            and _clears_intervals(x, intervals)
        ]
        if valid:
            split = min(valid, key=lambda x: abs(x - nominal))
            best = (split, hall_right, 0)
            break
        # Fallback: keep the front door clear; drop colliding windows.
        door_interval = (door_lo - pad, door_hi + pad)
        fallback = [
            x
            for x in (
                nominal,
                door_interval[0] - 1e-4,
                door_interval[1] + 1e-4,
            )
            if lo_lim - 1e-6 <= x <= hi_lim + 1e-6
            and not (door_interval[0] < x < door_interval[1])
        ]
        if fallback and best is None:
            split = min(fallback, key=lambda x: abs(x - nominal))
            best = (split, hall_right, 1)

    if best is None:
        split = (
            bx2 - hall_width - half_part
            if preferred_right
            else bx1 + hall_width + half_part
        )
        hall_right = preferred_right
    else:
        split, hall_right, _ = best

    stair_w = flight * 2 + 0.12
    if hall_right:
        sx2 = bx2 - 0.08
        sx1 = sx2 - stair_w
    else:
        sx1 = bx1 + 0.08
        sx2 = sx1 + stair_w
    return split, hall_right, (sx1, by2 - length, sx2, by2)


def _filter_interior_openings(walls, split, hall_right, stair_box):
    half_part = PARTITION_THICKNESS / 2
    result = []
    stair_wall = "Right" if hall_right else "Left"
    for wall in walls:
        kept = []
        for opening in wall.openings:
            if opening.kind == "DOOR":
                kept.append(opening)
                continue
            if split is not None and wall.name in ("Front", "Back"):
                lo, hi = _wall_x_span(wall.start, wall.tangent, opening)
                if (
                    split + half_part + 0.01 > lo - 0.075
                    and split - half_part - 0.01 < hi + 0.075
                ):
                    continue
            if stair_box is not None:
                sx1, sy1, sx2, sy2 = stair_box
                if wall.name == "Back":
                    lo, hi = _wall_x_span(wall.start, wall.tangent, opening)
                    if sx2 + 0.08 > lo - 0.075 and sx1 - 0.08 < hi + 0.075:
                        continue
                elif wall.name == stair_wall:
                    lo, hi = _wall_y_span(wall.start, wall.tangent, opening)
                    if sy2 + 0.08 > lo - 0.075 and sy1 - 0.08 < hi + 0.075:
                        continue
            kept.append(opening)
        result.append(
            Wall(
                wall.name,
                wall.length,
                wall.start,
                wall.tangent,
                wall.normal,
                wall.profile,
                tuple(kept),
            )
        )
    return result


def make_plan(config):
    config.validate()
    rng = random.Random(config.seed)
    width = config.width * (
        1 + rng.uniform(-config.variation, config.variation)
    )
    depth = config.depth * (
        1 + rng.uniform(-config.variation, config.variation)
    )
    floor_height = config.floor_height * (
        1 + rng.uniform(-config.variation, config.variation) * 0.15
    )
    height = config.floors * floor_height
    pitch = config.roof_pitch + rng.uniform(-1, 1) * config.variation * 10
    slope = math.tan(math.radians(pitch))
    roof_faces = _roof_faces(config, width, depth, height, pitch)
    specs = (
        ("Front", width, (-width / 2, -depth / 2), (1, 0), (0, -1)),
        ("Right", depth, (width / 2, -depth / 2), (0, 1), (1, 0)),
        ("Back", width, (width / 2, depth / 2), (-1, 0), (0, 1)),
        ("Left", depth, (-width / 2, depth / 2), (0, -1), (-1, 0)),
    )
    walls = []
    for name, length, start, tangent, normal in specs:
        profile = rectangle(0, 0, length, height)
        if config.roof_style == "GABLE" and name in ("Front", "Back"):
            profile = [
                (0, 0),
                (length, 0),
                (length, height),
                (length / 2, height + width / 2 * slope),
                (0, height),
            ]
        elif config.roof_style == "SHED":
            end_x = start[0] + tangent[0] * length
            left_height = height + (width / 2 - start[0]) * slope
            right_height = height + (width / 2 - end_x) * slope
            profile = [
                (0, 0),
                (length, 0),
                (length, right_height),
                (0, left_height),
            ]
        walls.append(
            Wall(
                name,
                length,
                start,
                tangent,
                normal,
                tuple(profile),
                _openings(
                    config,
                    length,
                    floor_height,
                    name,
                    roof_faces,
                    start,
                    tangent,
                    normal,
                ),
            )
        )
    if config.interior:
        split, hall_right, stair_box = plan_interior_division(
            width,
            depth,
            floor_height,
            config.floors,
            config.walkway_width,
            walls[0],
            walls[2],
        )
        walls = _filter_interior_openings(walls, split, hall_right, stair_box)
    return HousePlan(
        width,
        depth,
        floor_height,
        height,
        pitch,
        tuple(walls),
        roof_faces,
    )


def wall_tiles(wall, config):
    """Yield clipped cladding polygons; no tile covers any opening."""
    if config.wall_style == "PLASTER":
        return
    top = max(p[1] for p in wall.profile)
    if config.wall_style == "BRICK":
        tile_w, tile_h, gap = config.brick_width, config.brick_height, 0.022
    elif config.wall_style == "WOOD_HORIZONTAL":
        tile_w, tile_h, gap = wall.length + 0.1, config.plank_width, 0.016
    else:
        tile_w, tile_h, gap = config.plank_width, top + 0.1, 0.016
    rows = math.ceil(top / tile_h)
    for row in range(rows):
        offset = -tile_w / 2 if config.wall_style == "BRICK" and row % 2 else 0
        columns = math.ceil((wall.length - offset) / tile_w)
        for column in range(columns):
            x1 = offset + column * tile_w + gap / 2
            z1 = row * tile_h + gap / 2
            tile = rectangle(x1, z1, x1 + tile_w - gap, z1 + tile_h - gap)
            tile = clip_polygon(tile, wall.profile)
            if len(tile) >= 3 and polygon_area(tile) > 0.0005:
                for piece in without_openings(tile, wall.openings):
                    if polygon_area(piece) > 0.0005:
                        yield piece
