"""Deterministic terrain and geometry without Blender."""

import math
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache


def smoothstep(low, high, value):
    t = min(1.0, max(0.0, (value - low) / (high - low)))
    return t * t * (3 - 2 * t)


def value_noise(x, y, seed):
    def value(a, b):
        number = (
            a * 374761393 + b * 668265263 + seed * 1442695041
        ) & 0xFFFFFFFF
        number = ((number ^ (number >> 13)) * 1274126177) & 0xFFFFFFFF
        return ((number ^ (number >> 16)) & 0xFFFFFFFF) / 2147483647.5 - 1

    ix, iy = math.floor(x), math.floor(y)
    tx, ty = x - ix, y - iy
    tx, ty = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
    a = value(ix, iy) * (1 - tx) + value(ix + 1, iy) * tx
    b = value(ix, iy + 1) * (1 - tx) + value(ix + 1, iy + 1) * tx
    return a * (1 - ty) + b * ty


def ground_gradient(height, x, y, delta):
    return (
        (height(x + delta, y) - height(x - delta, y)) / (2 * delta),
        (height(x, y + delta) - height(x, y - delta)) / (2 * delta),
    )


@dataclass(frozen=True)
class TerrainSpec:
    seed: int
    radius: float
    relief: float
    aspect: tuple
    hill: tuple = ()
    castle_pad: tuple = ()
    castle_blend: tuple = ()
    plazas: tuple = ()
    ground: Callable[[float, float], float] | None = None


def natural_height(spec, x, y):
    if spec.ground is None:
        height = _local_relief(spec, x, y)
    else:
        height = spec.ground(x, y)
    if spec.hill:
        hx, hy, spread, rise = spec.hill
        height += rise * math.exp(-((x - hx) ** 2 + (y - hy) ** 2) / spread**2)
    return height


def _local_relief(spec, x, y):
    distance = math.hypot(x / spec.aspect[0], y / spec.aspect[1]) / spec.radius
    amplitude = 0.22 + 0.78 * smoothstep(0.55, 1.4, distance)
    height = 1.0
    for octave, weight in enumerate((0.65, 0.23, 0.09, 0.03)):
        scale = spec.radius * 1.15 / (2**octave)
        height += (
            value_noise(
                x / scale + 3.7, y / scale - 5.1, spec.seed + octave * 73
            )
            * spec.relief
            * weight
            * amplitude
        )
    return height


@lru_cache(maxsize=262144)
def terrain_height(spec, x, y):
    height = natural_height(spec, x, y)
    if spec.castle_pad:
        px, py, radius, z = spec.castle_pad
        distance = math.hypot(x - px, y - py)
        width = 14
        if spec.castle_blend:
            nx, ny, front, back = spec.castle_blend
            facing = ((x - px) * nx + (y - py) * ny) / max(distance, 1e-6)
            width = back + (front - back) * smoothstep(0.15, 0.85, facing)
        blend = 1 - smoothstep(radius, radius + width, distance)
        height = height * (1 - blend) + z * blend
    for px, py, radius, z in spec.plazas:
        blend = 1 - smoothstep(radius, radius + 6, math.hypot(x - px, y - py))
        height = height * (1 - blend) + z * blend
    return height


def segment_projection(point, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    denominator = dx * dx + dy * dy
    t = (
        0
        if denominator < 1e-12
        else min(
            1.0,
            max(
                0.0,
                ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy)
                / denominator,
            ),
        )
    )
    closest = (a[0] + dx * t, a[1] + dy * t)
    return math.dist(point[:2], closest), t, closest


def inside_polygon(point, polygon):
    x, y = point
    inside = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        if (a[1] > y) != (b[1] > y):
            crossing = (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]
            if x < crossing:
                inside = not inside
    return inside


def boundary_distance(point, polygon):
    return min(
        segment_projection(point, a, b)[0]
        for a, b in zip(polygon, polygon[1:] + polygon[:1], strict=True)
    )


def oriented_corners(centre, width, depth, heading, margin=0):
    cosine, sine = math.cos(heading), math.sin(heading)
    return tuple(
        (centre[0] + x * cosine - y * sine, centre[1] + x * sine + y * cosine)
        for x, y in (
            (-width / 2 - margin, -depth / 2 - margin),
            (width / 2 + margin, -depth / 2 - margin),
            (width / 2 + margin, depth / 2 + margin),
            (-width / 2 - margin, depth / 2 + margin),
        )
    )


def polygons_overlap(first, second):
    for polygon in (first, second):
        for a, b in zip(polygon, polygon[1:] + polygon[:1], strict=True):
            axis = (a[1] - b[1], b[0] - a[0])
            left = [x * axis[0] + y * axis[1] for x, y in first]
            right = [x * axis[0] + y * axis[1] for x, y in second]
            if (
                max(left) <= min(right) + 1e-7
                or max(right) <= min(left) + 1e-7
            ):
                return False
    return True


def rectangle_distance(point, centre, width, depth, heading):
    dx, dy = point[0] - centre[0], point[1] - centre[1]
    cosine, sine = math.cos(heading), math.sin(heading)
    x, y = dx * cosine + dy * sine, -dx * sine + dy * cosine
    return math.hypot(max(abs(x) - width / 2, 0), max(abs(y) - depth / 2, 0))


class SpatialHash:
    def __init__(self, cell_size=12.0):
        self.cell_size = cell_size
        self.cells = defaultdict(list)

    def _keys(self, bounds):
        x1, y1, x2, y2 = (
            math.floor(value / self.cell_size) for value in bounds
        )
        for x in range(x1, x2 + 1):
            for y in range(y1, y2 + 1):
                yield x, y

    def insert(self, index, bounds):
        for key in self._keys(bounds):
            self.cells[key].append(index)

    def query(self, point, radius):
        x, y = point[:2]
        return {
            index
            for key in self._keys(
                (x - radius, y - radius, x + radius, y + radius)
            )
            for index in self.cells.get(key, ())
        }


def terrain_outline(plan):
    if boundary := getattr(plan, "surface_boundary", ()):
        return boundary
    outside = [
        (
            gate.position[0] + gate.outward[0] * 16,
            gate.position[1] + gate.outward[1] * 16,
        )
        for gate in plan.gates
    ]
    scale = 1.55
    while scale < 2.6:
        polygon = tuple((x * scale, y * scale) for x, y in plan.boundary)
        if all(inside_polygon(point, polygon) for point in outside):
            return polygon
        scale += 0.05
    raise ValueError("Unable to cover the gate approach roads with terrain")


class TerrainSampler:
    """Blend terrain into the road and foundation pads."""

    def __init__(self, plan):
        self.spec = plan.terrain
        self.buildings = plan.buildings
        self.markets = plan.markets
        self.cache = {}
        self.segments, self.roads = [], SpatialHash()
        self.pads = SpatialHash()
        for road in plan.roads:
            for a, b in zip(road.points, road.points[1:], strict=False):
                index = len(self.segments)
                self.segments.append((a, b, road.width, road.kind))
                self.roads.insert(
                    index,
                    (
                        min(a[0], b[0]),
                        min(a[1], b[1]),
                        max(a[0], b[0]),
                        max(a[1], b[1]),
                    ),
                )
        for index, building in enumerate(self.buildings):
            corners = building.corners
            self.pads.insert(
                index,
                (
                    min(p[0] for p in corners),
                    min(p[1] for p in corners),
                    max(p[0] for p in corners),
                    max(p[1] for p in corners),
                ),
            )

    def height(self, x, y):
        key = (round(x, 6), round(y, 6))
        if key not in self.cache:
            self.cache[key] = self._height(x, y)
        return self.cache[key]

    def _height(self, x, y):
        base = terrain_height(self.spec, x, y)
        for market in self.markets:
            distance = math.dist((x, y), market.centre[:2])
            weight = 1 - smoothstep(market.radius, market.radius + 3, distance)
            base = base * (1 - weight) + (market.centre[2] + 0.12) * weight
        strongest, total, weighted = 0.0, 0.0, 0.0
        for index in self.pads.query((x, y), 4):
            building = self.buildings[index]
            distance = rectangle_distance(
                (x, y),
                building.position,
                building.width + 0.28,
                building.depth + 0.28,
                building.heading,
            )
            weight = 1 - smoothstep(0.0, 2.2, distance)
            strongest = max(strongest, weight)
            influence = weight / (distance * distance + 0.000025) ** 2
            total += influence
            weighted += building.position[2] * influence
        if total:
            base = base * (1 - strongest) + weighted / total * strongest
        strongest, total, weighted = 0.0, 0.0, 0.0
        for index in sorted(self.roads.query((x, y), 8)):
            a, b, width, kind = self.segments[index]
            distance, t, _ = segment_projection((x, y), a, b)
            shoulder = 0.9 if kind == "ACCESS" else 2.5
            weight = 1 - smoothstep(
                width / 2 + 0.15, width / 2 + shoulder, distance
            )
            if weight <= 0:
                continue
            strongest = max(strongest, weight)
            influence = weight / (distance * distance + 0.000025) ** 2
            target = a[2] + (b[2] - a[2]) * t
            total += influence
            weighted += influence * target
        return (
            base * (1 - strongest) + weighted / total * strongest
            if total
            else base
        )
