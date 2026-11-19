"""Plan rooms, stairs and furniture without importing Blender."""

import json
import math
import random
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path

from house_rules import (
    FOUNDATION_HEIGHT,
    PARTITION_THICKNESS,
    WALL_THICKNESS,
    plan_interior_division,
)

SLAB_THICKNESS = 0.12
FLOOR_OFFSET = 0.015
EPSILON = 1e-7


@dataclass(frozen=True)
class Rect:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self):
        return self.x2 - self.x1

    @property
    def depth(self):
        return self.y2 - self.y1

    @property
    def centre(self):
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    def contains(self, other):
        return (
            self.x1 - EPSILON <= other.x1
            and self.y1 - EPSILON <= other.y1
            and self.x2 + EPSILON >= other.x2
            and self.y2 + EPSILON >= other.y2
        )

    def overlaps(self, other):
        return (
            self.x1 < other.x2 - EPSILON
            and self.x2 > other.x1 + EPSILON
            and self.y1 < other.y2 - EPSILON
            and self.y2 > other.y1 + EPSILON
        )

    def expanded(self, amount):
        return Rect(
            self.x1 - amount,
            self.y1 - amount,
            self.x2 + amount,
            self.y2 + amount,
        )


@dataclass(frozen=True)
class FurnitureSpec:
    kind: str
    size: tuple
    clearance: float = 0.8

    def validate(self):
        if len(self.size) != 3 or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
            for value in self.size
        ):
            raise ValueError(
                f"{self.kind}: size must contain 3 positive numbers"
            )
        if (
            isinstance(self.clearance, bool)
            or not isinstance(self.clearance, (int, float))
            or not math.isfinite(self.clearance)
            or self.clearance < 0
        ):
            raise ValueError(f"{self.kind}: clearance must be nonnegative")
        return self


DEFAULT_CATALOG = {
    "bed": FurnitureSpec("bed", (1.45, 2.0, 0.55)),
    "lamp": FurnitureSpec("lamp", (0.28, 0.28, 0.65), 0),
    "wardrobe": FurnitureSpec("wardrobe", (1.2, 0.6, 1.85)),
    "sofa": FurnitureSpec("sofa", (1.75, 0.8, 0.85)),
    "chair": FurnitureSpec("chair", (0.5, 0.5, 0.85)),
    "dining_table": FurnitureSpec("dining_table", (1.2, 0.75, 0.75), 0),
    "desk": FurnitureSpec("desk", (1.1, 0.6, 0.75), 0),
}


def load_catalog(path=""):
    """Merge a furniture JSON catalog with the built-in defaults."""
    catalog = dict(DEFAULT_CATALOG)
    if path:
        values = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(values, dict):
            raise ValueError("Furniture catalog must be a JSON object")
        for kind, value in values.items():
            if kind not in catalog or not isinstance(value, dict):
                raise ValueError(
                    f"Unknown furniture kind or invalid entry: {kind}"
                )
            if set(value) - {"size", "clearance"}:
                raise ValueError(f"Unsupported furniture fields: {kind}")
            default = catalog[kind]
            size = value.get("size", default.size)
            if not isinstance(size, (list, tuple)):
                raise ValueError(f"{kind}: size must be a list")
            catalog[kind] = FurnitureSpec(
                kind, tuple(size), value.get("clearance", default.clearance)
            ).validate()
    return catalog


@dataclass(frozen=True)
class Room:
    id: str
    kind: str
    floor: int
    bounds: Rect
    entry: tuple


@dataclass(frozen=True)
class Partition:
    floor: int
    x: float
    y1: float
    y2: float
    door_y: float
    door_width: float
    door_height: float = 2.08


@dataclass(frozen=True)
class Zone:
    floor: int
    kind: str
    bounds: Rect
    sill: float = 0.0


@dataclass(frozen=True)
class Stair:
    id: str
    lower_floor: int
    upper_floor: int
    bounds: Rect
    flight_width: float
    landing_depth: float
    steps_per_flight: int
    rise: float
    tread: float

    @property
    def lower_entry(self):
        return (self.bounds.x1 + self.flight_width / 2, self.bounds.y1)

    @property
    def upper_exit(self):
        return (self.bounds.x2 - self.flight_width / 2, self.bounds.y1)


@dataclass(frozen=True)
class Placement:
    id: str
    kind: str
    room_id: str
    floor: int
    position: tuple
    size: tuple
    rotation_z: int
    footprint: Rect
    clearance: Rect | None
    access_point: tuple | None
    anchor_id: str = ""


@dataclass(frozen=True)
class Unplaced:
    room_id: str
    kind: str
    reason: str


@dataclass(frozen=True)
class InteriorPlan:
    bounds: Rect
    rooms: tuple
    partitions: tuple
    stairs: tuple
    zones: tuple
    furniture: tuple
    unplaced: tuple
    walkway_width: float

    def as_dict(self):
        return {
            "schema_version": 1,
            "units": "metres",
            "coordinate_space": "house_local",
            "asset_origin": "BOTTOM_CENTER",
            "asset_front": "-Y",
            **asdict(self),
        }


def floor_z(house, floor):
    return FOUNDATION_HEIGHT + FLOOR_OFFSET + floor * house.floor_height


def _rotate(x, y, angle):
    return ((x, y), (-y, x), (-x, -y), (y, -x))[angle // 90 % 4]


def _placement(spec, room, identifier, xy, angle, z, walkway, anchor=""):
    width, depth, height = spec.size
    half_x, half_y = (
        (width / 2, depth / 2) if angle % 180 == 0 else (depth / 2, width / 2)
    )
    x, y = xy
    footprint = Rect(x - half_x, y - half_y, x + half_x, y + half_y)
    clearance, access = None, None
    if spec.clearance > 0:
        distance = max(spec.clearance, walkway)
        # Chairs face their table; access is behind the chair.
        side = 1 if spec.kind == "chair" else -1
        offset = side * (depth + distance) / 2
        dx, dy = _rotate(0, offset, angle)
        access = (x + dx, y + dy)
        access_width = max(width, walkway)
        half_w, half_d = (
            (access_width / 2, distance / 2)
            if angle % 180 == 0
            else (distance / 2, access_width / 2)
        )
        clearance = Rect(
            access[0] - half_w,
            access[1] - half_d,
            access[0] + half_w,
            access[1] + half_d,
        )
    return Placement(
        identifier,
        spec.kind,
        room.id,
        room.floor,
        (x, y, z),
        spec.size,
        angle,
        footprint,
        clearance,
        access,
        anchor,
    )


def _group(kind, room, xy, angle, catalog, z, walkway, lamp_side=1):
    identifier = f"{room.id}_{kind}"
    parent = _placement(catalog[kind], room, identifier, xy, angle, z, walkway)
    items = [parent]
    width, depth, _ = parent.size
    if kind == "bed":
        lamp = catalog["lamp"]
        offset = (
            lamp_side * (width / 2 + lamp.size[0] / 2 + 0.10),
            depth / 2 - lamp.size[1] / 2 - 0.12,
        )
        dx, dy = _rotate(*offset, angle)
        items.append(
            _placement(
                lamp,
                room,
                identifier + "_lamp",
                (xy[0] + dx, xy[1] + dy),
                angle,
                z,
                walkway,
                identifier,
            )
        )
    elif kind in ("desk", "dining_table"):
        chair = catalog["chair"]
        distance = (depth + chair.size[1]) / 2 + 0.12
        for index, side in enumerate(
            (-1, 1) if kind == "dining_table" else (-1,)
        ):
            dx, dy = _rotate(0, side * distance, angle)
            facing = (angle + (180 if side == -1 else 0)) % 360
            items.append(
                _placement(
                    chair,
                    room,
                    f"{identifier}_chair_{index}",
                    (xy[0] + dx, xy[1] + dy),
                    facing,
                    z,
                    walkway,
                    identifier,
                )
            )
    return items


def _candidates(room, spec, rng):
    bounds = room.bounds
    candidates = []
    margin = 0.08
    for angle in (0, 90, 180, 270):
        width, depth = spec.size[:2]
        half_x, half_y = (
            (width / 2, depth / 2)
            if angle % 180 == 0
            else (depth / 2, width / 2)
        )
        left, right = bounds.x1 + half_x + margin, bounds.x2 - half_x - margin
        bottom = bounds.y1 + half_y + margin
        top = bounds.y2 - half_y - margin
        if left > right or bottom > top:
            continue
        for fraction in (0, 0.25, 0.5, 0.75, 1):
            x, y = (
                left + fraction * (right - left),
                bottom + fraction * (top - bottom),
            )
            if spec.kind == "dining_table":
                for second in (0.25, 0.5, 0.75):
                    candidates.append(
                        ((x, bottom + second * (top - bottom)), angle)
                    )
            else:
                xy = ((x, top), (left, y), (x, bottom), (right, y))[
                    angle // 90
                ]
                candidates.append((xy, angle))
    rng.shuffle(candidates)
    return candidates


def reachable(room, placements, walkway):
    """Check routes from the door to each furniture access point."""
    goals = [item.access_point for item in placements if item.access_point]
    if not goals:
        return True
    radius = walkway / 2
    bounds = room.bounds.expanded(-radius)
    if bounds.width <= 0 or bounds.depth <= 0:
        return False
    obstacles = [
        item.footprint.expanded(radius - EPSILON) for item in placements
    ]

    def free(point):
        x, y = point
        return (
            bounds.x1 - EPSILON <= x <= bounds.x2 + EPSILON
            and bounds.y1 - EPSILON <= y <= bounds.y2 + EPSILON
            and not any(r.x1 < x < r.x2 and r.y1 < y < r.y2 for r in obstacles)
        )

    # Include exact door and access coordinates in the grid.
    xs = {bounds.x1, bounds.x2, room.entry[0]}
    ys = {bounds.y1, bounds.y2, room.entry[1]}
    xs.update(point[0] for point in goals)
    ys.update(point[1] for point in goals)
    xs.update(
        bounds.x1 + i * 0.25 for i in range(math.ceil(bounds.width / 0.25))
    )
    ys.update(
        bounds.y1 + i * 0.25 for i in range(math.ceil(bounds.depth / 0.25))
    )
    xs, ys = sorted(xs), sorted(ys)
    start = (xs.index(room.entry[0]), ys.index(room.entry[1]))
    if not free(room.entry):
        return False
    visited, queue = {start}, deque([start])
    while queue:
        i, j = queue.popleft()
        for a, b in ((i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1)):
            if (a, b) in visited or not (
                0 <= a < len(xs) and 0 <= b < len(ys)
            ):
                continue
            if not free((xs[a], ys[b])):
                continue
            # A grid edge must not skip over a narrow inflated obstacle.
            segment = Rect(
                min(xs[i], xs[a]),
                min(ys[j], ys[b]),
                max(xs[i], xs[a]),
                max(ys[j], ys[b]),
            )
            if any(segment.overlaps(obstacle) for obstacle in obstacles):
                continue
            visited.add((a, b))
            queue.append((a, b))
    return all((xs.index(x), ys.index(y)) in visited for x, y in goals)


def _valid_group(group, previous, room, zones, config, house):
    for item in group:
        if item.size[2] > house.floor_height - SLAB_THICKNESS:
            return False
        if not room.bounds.contains(item.footprint):
            return False
        if item.clearance and not room.bounds.contains(item.clearance):
            return False
        for zone in zones:
            if zone.floor != room.floor:
                continue
            if zone.kind == "window" and item.size[2] <= zone.sill:
                continue
            if item.footprint.overlaps(zone.bounds):
                return False
        for other in previous:
            if item.footprint.overlaps(other.footprint):
                return False
            if other.clearance and item.footprint.overlaps(other.clearance):
                return False
            if item.clearance and item.clearance.overlaps(other.footprint):
                return False
    for index, item in enumerate(group):
        for other in group[index + 1 :]:
            if item.footprint.overlaps(other.footprint):
                return False
            if item.clearance and item.clearance.overlaps(other.footprint):
                return False
            if other.clearance and other.clearance.overlaps(item.footprint):
                return False
    return reachable(room, previous + group, config.walkway_width)


def _furnish(room, catalog, config, house, zones):
    if room.kind == "hall":
        return [], []
    kinds = {
        "bedroom": ("bed", "wardrobe", "desk"),
        "living": ("sofa", "dining_table", "desk"),
        "studio": ("bed", "wardrobe", "sofa", "dining_table", "desk"),
    }[room.kind]
    rng = random.Random(f"{config.interior_seed}:{room.id}")
    placements, unplaced = [], []
    for kind in kinds:
        found = None
        for xy, angle in _candidates(room, catalog[kind], rng):
            for side in (-1, 1) if kind == "bed" else (1,):
                group = _group(
                    kind,
                    room,
                    xy,
                    angle,
                    catalog,
                    floor_z(house, room.floor),
                    config.walkway_width,
                    side,
                )
                if _valid_group(group, placements, room, zones, config, house):
                    found = group
                    break
            if found:
                break
        if found:
            placements.extend(found)
        else:
            unplaced.append(
                Unplaced(
                    room.id, kind, "No space for the size and access rules"
                )
            )
            related = {
                "bed": ("lamp",),
                "desk": ("chair",),
                "dining_table": ("chair", "chair"),
            }.get(kind, ())
            unplaced.extend(
                Unplaced(room.id, child, f"Requires placed {kind}")
                for child in related
            )
    return placements, unplaced


def _window_zones(house, floor):
    zones = []
    for wall in house.walls:
        for opening in wall.openings:
            if opening.kind != "WINDOW":
                continue
            sill = opening.z1 - floor * house.floor_height
            if not 0 <= sill < house.floor_height:
                continue
            points = [
                (
                    wall.start[0] + wall.tangent[0] * u - wall.normal[0] * d,
                    wall.start[1] + wall.tangent[1] * u - wall.normal[1] * d,
                )
                for u in (opening.x1, opening.x2)
                for d in (WALL_THICKNESS, WALL_THICKNESS + 0.3)
            ]
            bounds = Rect(
                min(p[0] for p in points),
                min(p[1] for p in points),
                max(p[0] for p in points),
                max(p[1] for p in points),
            )
            zones.append(Zone(floor, "window", bounds, sill))
    return zones


def make_interior_plan(config, house, catalog=None):
    """Reserve circulation before arranging related furniture groups."""
    config.validate()
    bounds = Rect(
        -house.width / 2 + WALL_THICKNESS,
        -house.depth / 2 + WALL_THICKNESS,
        house.width / 2 - WALL_THICKNESS,
        house.depth / 2 - WALL_THICKNESS,
    )
    if not config.interior:
        return InteriorPlan(
            bounds, (), (), (), (), (), (), config.walkway_width
        )
    catalog = dict(DEFAULT_CATALOG if catalog is None else catalog)
    if set(catalog) != set(DEFAULT_CATALOG):
        raise ValueError("Catalog must define all supported furniture kinds")
    for kind, spec in catalog.items():
        if spec.kind != kind:
            raise ValueError(f"Catalog kind mismatch: {kind}")
        spec.validate()
    front, back = house.walls[0], house.walls[2]
    entrance = next(o for o in front.openings if o.kind == "DOOR")
    entry_x = front.start[0] + (entrance.x1 + entrance.x2) / 2
    walk = config.walkway_width
    door_width = walk + 0.12
    door_y = bounds.y1 + door_width / 2 + 0.04
    rooms, partitions, stairs, zones = [], [], [], []
    placements, unplaced = [], []
    split, hall_right, stair_box = plan_interior_division(
        house.width,
        house.depth,
        house.floor_height,
        config.floors,
        walk,
        front,
        back,
    )
    stair_bounds = None
    if config.floors > 1:
        if stair_box is None:
            raise ValueError(
                "House is too small for connected stairs and a room"
            )
        flight = max(0.72, walk)
        count = math.ceil(house.floor_height / 0.36)
        stair_bounds = Rect(*stair_box)
        length = stair_bounds.depth
        for floor in range(config.floors - 1):
            stairs.append(
                Stair(
                    f"stairs_{floor}_{floor + 1}",
                    floor,
                    floor + 1,
                    stair_bounds,
                    flight,
                    flight,
                    count,
                    house.floor_height / (count * 2),
                    (length - flight) / count,
                )
            )
    for floor in range(config.floors):
        zones.extend(_window_zones(house, floor))
        zones.append(
            Zone(
                floor,
                "circulation",
                Rect(bounds.x1, bounds.y1, bounds.x2, bounds.y1 + walk + 0.25),
            )
        )
        if stair_bounds:
            zones.append(Zone(floor, "stairs", stair_bounds))
            zones.append(
                Zone(
                    floor,
                    "landing",
                    Rect(
                        stair_bounds.x1,
                        stair_bounds.y1 - walk,
                        stair_bounds.x2,
                        stair_bounds.y1,
                    ),
                )
            )
        if split is None:
            rooms.append(
                Room(
                    f"f{floor}_studio",
                    "studio",
                    floor,
                    bounds,
                    (entry_x, bounds.y1 + walk / 2 + 0.02),
                )
            )
            continue
        left = Rect(
            bounds.x1, bounds.y1, split - PARTITION_THICKNESS / 2, bounds.y2
        )
        right = Rect(
            split + PARTITION_THICKNESS / 2, bounds.y1, bounds.x2, bounds.y2
        )
        partitions.append(
            Partition(floor, split, bounds.y1, bounds.y2, door_y, door_width)
        )
        main_kind = "living" if floor == 0 else "bedroom"
        if config.floors == 1:
            kinds = ("bedroom", "living")
        else:
            kinds = (main_kind, "hall") if hall_right else ("hall", main_kind)
        for side, (room_bounds, kind) in enumerate(
            zip((left, right), kinds, strict=True)
        ):
            direction = -1 if side == 0 else 1
            entry = (
                split
                + direction * (PARTITION_THICKNESS / 2 + walk / 2 + 0.02),
                door_y,
            )
            rooms.append(
                Room(f"f{floor}_{kind}", kind, floor, room_bounds, entry)
            )
    if config.furnish:
        for room in rooms:
            items, missing = _furnish(room, catalog, config, house, zones)
            placements.extend(items)
            unplaced.extend(missing)
    return InteriorPlan(
        bounds,
        tuple(rooms),
        tuple(partitions),
        tuple(stairs),
        tuple(zones),
        tuple(placements),
        tuple(unplaced),
        walk,
    )
