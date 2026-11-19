"""Shared height fields and water bodies for the world and its towns."""

import math
from dataclasses import dataclass
from functools import lru_cache

from terrain_rules import (
    SpatialHash,
    segment_projection,
    smoothstep,
    value_noise,
)

REGION_KINDS = ("MOUNTAIN", "HILLS", "VALLEY", "PLAIN")
SEA_SIDES = ("WEST", "EAST", "SOUTH", "NORTH")


def _coordinates(values, size, name):
    if len(values) != size or any(
        type(v) not in (int, float) or not math.isfinite(v) for v in values
    ):
        raise ValueError(f"{name} needs {size} finite coordinates")
    return tuple(values)


@dataclass(frozen=True)
class Region:
    kind: str
    centre: tuple
    radii: tuple
    elevation: float | None = None
    max_elevation: float | None = None
    heading: float = 0.0

    def __post_init__(self):
        object.__setattr__(
            self, "centre", _coordinates(self.centre, 2, "region centre")
        )
        object.__setattr__(
            self, "radii", _coordinates(self.radii, 2, "region radii")
        )
        if self.kind not in REGION_KINDS or min(self.radii) < 12:
            raise ValueError(f"Invalid region kind or radii: {self.kind}")
        if self.elevation is None and self.max_elevation is None:
            raise ValueError("A region needs elevation or max_elevation")
        _coordinates(
            tuple(
                v
                for v in (self.heading, self.elevation, self.max_elevation)
                if v is not None
            ),
            1
            + (self.elevation is not None)
            + (self.max_elevation is not None),
            "region elevations and heading",
        )

    def distance(self, x, y):
        dx, dy = x - self.centre[0], y - self.centre[1]
        angle = math.radians(self.heading)
        c, s = math.cos(angle), math.sin(angle)
        return math.hypot(
            (dx * c + dy * s) / self.radii[0],
            (-dx * s + dy * c) / self.radii[1],
        )


@dataclass(frozen=True)
class Coast:
    side: str
    position: float
    level: float = 0.0
    waviness: float = 36.0
    depth: float = 24.0

    def __post_init__(self):
        _coordinates(
            (self.position, self.level, self.waviness, self.depth), 4, "coast"
        )
        if self.side not in SEA_SIDES or self.waviness < 0 or self.depth <= 0:
            raise ValueError("Invalid coast side, waviness or depth")

    def distance(self, x, y, seed):
        cross, along = (x, y) if self.side in ("WEST", "EAST") else (y, x)
        shore = self.position + self.waviness * (
            math.sin(along / 108 + seed % 30) * 0.48
            + value_noise(along / 126, 0.45, seed + 943) * 0.52
        )
        sign = 1 if self.side in ("WEST", "SOUTH") else -1
        return (cross - shore) * sign

    def nearest_water(self, x, y, seed):
        delta = self.distance(x, y, seed)
        if self.side == "WEST":
            return x - delta - 1, y
        if self.side == "EAST":
            return x + delta + 1, y
        if self.side == "SOUTH":
            return x, y - delta - 1
        return x, y + delta + 1


@dataclass(frozen=True)
class Lake:
    id: str
    centre: tuple
    radii: tuple
    level: float
    depth: float = 10.0

    def __post_init__(self):
        object.__setattr__(
            self, "centre", _coordinates(self.centre, 2, "lake centre")
        )
        object.__setattr__(
            self, "radii", _coordinates(self.radii, 2, "lake radii")
        )
        _coordinates((self.level, self.depth), 2, "lake levels")
        if min(self.radii) < 12 or self.depth <= 0:
            raise ValueError(
                "Lake radii must be at least 12m and depth positive"
            )

    def distance(self, x, y, seed):
        u = (x - self.centre[0]) / self.radii[0]
        v = (y - self.centre[1]) / self.radii[1]
        angle = math.atan2(v, u)
        shore = 1 + 0.10 * value_noise(
            math.cos(angle) * 3, math.sin(angle) * 3, seed + 751
        )
        return (math.hypot(u, v) - shore) * min(self.radii)


@dataclass(frozen=True)
class River:
    id: str
    points: tuple
    width: float
    depth: float = 3.0

    def __post_init__(self):
        points = tuple(_coordinates(p, 3, "river point") for p in self.points)
        object.__setattr__(self, "points", points)
        _coordinates((self.width, self.depth), 2, "river size")
        if len(points) < 2 or self.width <= 0 or self.depth <= 0:
            raise ValueError("A river needs a polyline, width and depth")
        if any(
            math.dist(a[:2], b[:2]) < self.width / 2 or a[2] < b[2]
            for a, b in zip(points, points[1:], strict=False)
        ):
            raise ValueError(
                "River points must be spaced apart and flow downhill"
            )


@dataclass(frozen=True)
class Water:
    id: str
    kind: str
    distance: float
    level: float
    depth: float
    bed_width: float
    bank_width: float

    def shape(self, ground):
        if self.distance <= 0:
            return self.level - self.depth * smoothstep(
                0, self.bed_width, -self.distance
            )
        weight = 1 - smoothstep(0, self.bank_width, self.distance)
        slope = 0.075 if self.kind == "SEA" else 0.12
        shoulder = self.level + self.distance * slope
        return ground + (shoulder - ground) * weight


class RiverChannel:
    def __init__(self, river):
        self.river = river
        self.path = self._path(river.points)
        self.segments = tuple(zip(self.path, self.path[1:], strict=False))
        self.index = SpatialHash(48)
        for i, (a, b) in enumerate(self.segments):
            self.index.insert(
                i,
                (
                    min(a[0], b[0]),
                    min(a[1], b[1]),
                    max(a[0], b[0]),
                    max(a[1], b[1]),
                ),
            )

    @staticmethod
    def _path(points):
        """Round the bends, preserving the monotone water levels."""
        result = [points[0]]
        for i, (a, b) in enumerate(zip(points, points[1:], strict=False)):
            before = points[max(0, i - 1)]
            after = points[min(len(points) - 1, i + 2)]
            length = math.dist(a[:2], b[:2])
            count = math.ceil(length / 12)
            for sample in range(1, count + 1):
                t = sample / count
                xy = []
                for axis in (0, 1):
                    p, q, r, s = (
                        point[axis] for point in (before, a, b, after)
                    )
                    xy.append(
                        0.5
                        * (
                            2 * q
                            + (r - p) * t
                            + (2 * p - 5 * q + 4 * r - s) * t**2
                            + (3 * q - p - 3 * r + s) * t**3
                        )
                    )
                result.append((*xy, a[2] + (b[2] - a[2]) * t))
        return tuple(result)

    def nearest(self, x, y, reach=None):
        candidates = (
            range(len(self.segments))
            if reach is None
            else self.index.query((x, y), reach)
        )
        result = None
        for i in candidates:
            a, b = self.segments[i]
            distance, t, point = segment_projection((x, y), a, b)
            if result is None or (distance, i) < result[:2]:
                result = distance, i, point, a[2] + (b[2] - a[2]) * t
        if result is not None:
            distance, _, point, level = result
            return distance - self.river.width / 2, point, level
        return None


class WorldTerrain:
    def __init__(self, config):
        self.config = config
        self.rivers = {r.id: RiverChannel(r) for r in config.rivers}
        self.lakes = {lake.id: lake for lake in config.lakes}
        coast = config.coast
        self.sea_outlets = {
            river.id
            for river in config.rivers
            if coast and coast.distance(*river.points[-1][:2], config.seed) < 0
        }
        self.water_near = lru_cache(maxsize=120_000)(self.water_near)
        self.height = lru_cache(maxsize=180_000)(self.height)

    def river_level(self, key, point, level):
        if key not in self.sea_outlets:
            return level
        coast = self.config.coast
        distance = coast.distance(*point, self.config.seed)
        fade = smoothstep(0, 54, distance)
        return coast.level + max(0, level - coast.level) * fade

    def cap(self, x, y, height):
        for region in self.config.regions:
            ceiling = region.max_elevation
            if ceiling is None or height <= ceiling:
                continue
            distance = region.distance(x, y)
            fade = 1 - smoothstep(1, 1.18, distance)
            height -= (height - ceiling) * fade
        return height

    def upland(self, x, y):
        seed = self.config.seed
        noise = (
            value_noise(x / 167, y / 167, seed) * 0.65
            + value_noise(x / 59, y / 59, seed + 97) * 0.25
            + value_noise(x / 22, y / 22, seed + 167) * 0.10
        )
        height = self.config.base_elevation + self.config.relief * noise
        for region in self.config.regions:
            distance = region.distance(x, y)
            if distance >= 1:
                continue
            target = region.elevation
            if target is None and region.kind in ("MOUNTAIN", "HILLS"):
                target = region.max_elevation
            if target is None:
                continue
            fade = smoothstep(0, 1, 1 - distance)
            if region.kind == "MOUNTAIN":
                ridge = 1 - abs(value_noise(x / 77, y / 77, seed + 435))
                fade **= 1.15 + 0.55 * (1 - ridge)
                target += 22 * noise * smoothstep(0, 0.45, distance)
            elif region.kind == "HILLS":
                fade = fade**0.72
                target += 9 * noise * smoothstep(0, 0.4, distance)
            elif region.kind == "VALLEY":
                fade = smoothstep(0, 1, min(1.0, (1 - distance) * 1.4))
                target += 3 * noise
            else:
                target += 1.7 * noise
            height += (target - height) * fade
        return height

    def water_near(self, x, y, reach=0.0):
        """Find water bodies by bank width plus a search margin."""
        seed = self.config.seed
        coast = self.config.coast
        result = []
        if coast:
            distance = coast.distance(x, y, seed)
            if distance <= 112 + reach:
                result.append(
                    Water(
                        "sea",
                        "SEA",
                        distance,
                        coast.level,
                        coast.depth,
                        96,
                        112,
                    )
                )
        for lake in self.lakes.values():
            distance = lake.distance(x, y, seed)
            if distance <= 19 + reach:
                result.append(
                    Water(
                        lake.id,
                        "LAKE",
                        distance,
                        lake.level,
                        lake.depth,
                        min(lake.radii) * 0.60,
                        19,
                    )
                )
        for channel in self.rivers.values():
            river = channel.river
            match = channel.nearest(x, y, river.width / 2 + 18 + reach)
            if match and match[0] <= 18 + reach:
                distance, point, level = match
                level = self.river_level(river.id, point, level)
                result.append(
                    Water(
                        river.id,
                        "RIVER",
                        distance,
                        level,
                        river.depth,
                        river.width / 2,
                        18,
                    )
                )
        return tuple(result)

    def wet(self, x, y, margin=0.0):
        return any(w.distance < margin for w in self.water_near(x, y, margin))

    def water_distance(self, key, x, y):
        if key == "sea":
            coast = self.config.coast
            return coast.distance(x, y, self.config.seed), coast.level
        if key in self.lakes:
            lake = self.lakes[key]
            return lake.distance(x, y, self.config.seed), lake.level
        distance, point, level = self.rivers[key].nearest(x, y)
        return distance, self.river_level(key, point, level)

    def height(self, x, y):
        height = self.upland(x, y)
        water = self.water_near(x, y)
        wet = [body for body in water if body.distance <= 0]
        if wet:
            height = min(body.shape(height) for body in wet)
        else:
            for body in water:
                height = body.shape(height)
        return self.cap(x, y, height)

    def waterside(self, x, y, kind):
        """Find the nearest body identifier and a point on the water."""
        if kind == "HARBOR":
            coast = self.config.coast
            if coast:
                return "sea", coast.nearest_water(x, y, self.config.seed)
        elif kind == "LAKESIDE" and self.lakes:
            lake = min(
                self.lakes.values(),
                key=lambda body: abs(body.distance(x, y, self.config.seed)),
            )
            return lake.id, lake.centre
        elif kind == "RIVERSIDE" and self.rivers:
            matches = [
                (channel.nearest(x, y), key)
                for key, channel in self.rivers.items()
            ]
            (_, point, _), key = min(matches, key=lambda entry: entry[0][0])
            return key, point
        return None


@dataclass(frozen=True)
class Grid:
    size: tuple
    step: float

    @property
    def shape(self):
        return tuple(math.ceil(axis / self.step) for axis in self.size)

    def xy(self, i, j):
        return tuple(
            min(index * self.step, length) - length / 2
            for index, length in zip((i, j), self.size, strict=True)
        )

    def window(self, points, margin):
        def interval(axis):
            offset = self.size[axis] / 2
            values = [p[axis] + offset for p in points]
            return (
                math.floor((min(values) - margin) / self.step),
                math.ceil((max(values) + margin) / self.step),
            )

        left, right = interval(0)
        bottom, top = interval(1)
        nx, ny = self.shape
        if left <= 0 or bottom <= 0 or right >= nx or top >= ny:
            raise ValueError("Settlement patch extends beyond the world edge")
        return left, bottom, right, top

    def ring(self, window):
        left, bottom, right, top = window
        return tuple(
            [self.xy(i, bottom) for i in range(left, right)]
            + [self.xy(right, j) for j in range(bottom, top)]
            + [self.xy(i, top) for i in range(right, left, -1)]
            + [self.xy(left, j) for j in range(top, bottom, -1)]
        )
