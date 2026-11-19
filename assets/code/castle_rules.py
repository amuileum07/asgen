"""Seeded hill-castle massing in metres, independent of Blender."""

import math
import random
from dataclasses import dataclass, replace

from castle_roof_rules import required_tower_height


@dataclass(frozen=True)
class CastleBlock:
    id: str
    centre: tuple
    size: tuple
    height: float
    roof_height: float
    roof: str
    storeys: int
    timber: bool = False


@dataclass(frozen=True)
class CastleTower:
    id: str
    centre: tuple
    radius: float
    height: float
    roof_height: float
    base: float = 0.0
    roof: str = "CONE"


@dataclass(frozen=True)
class CastleArchitecture:
    scale: float
    outline: tuple
    blocks: tuple
    towers: tuple
    wall_height: float
    gate_width: float
    entry: tuple
    floor_height: float

    @property
    def height(self):
        return max(
            [b.height + b.roof_height for b in self.blocks]
            + [t.base + t.height + t.roof_height for t in self.towers]
        )


def castle_point(centre, heading, point):
    """Transform castle coordinates into settlement coordinates."""
    cosine, sine = math.cos(heading), math.sin(heading)
    return (
        centre[0] + point[0] * cosine - point[1] * sine,
        centre[1] + point[0] * sine + point[1] * cosine,
        centre[2] + (point[2] if len(point) > 2 else 0),
    )


def make_castle_architecture(seed, radius):
    """Cluster a donjon, palas, chapel and forewing inside a bailey."""
    if type(seed) is not int or seed < 0:
        raise ValueError("Castle seed must be a nonnegative integer")
    if (
        isinstance(radius, bool)
        or not isinstance(radius, (int, float))
        or not math.isfinite(radius)
        or not 9 <= radius <= 45
    ):
        raise ValueError("Castle radius must be between 9 and 45 metres")
    rng = random.Random(f"{seed}:ridge-castle")
    scale = radius / 24
    floor_height = max(3.2, rng.uniform(4.05, 4.35) * scale)
    blocks = []
    for identifier, x, y, width, depth, _height, _roof, storeys, timber in (
        ("palas", -2.5, 3.8, 11.5, 12, 18, "GABLE", 4, True),
        ("donjon", 3.0, 10.5, 8.0, 8.0, 27, "HIP", 6, False),
        ("forewing", -9.0, -4.0, 6.5, 10, 11, "GABLE", 3, True),
        ("chapel", 7.0, 3.0, 7.5, 13, 15, "GABLE", 3, False),
    ):
        blocks.append(
            CastleBlock(
                identifier,
                (x * scale, y * scale),
                (width * scale, depth * scale),
                storeys * floor_height,
                width * rng.uniform(0.61, 0.68) * scale,
                "PYRAMID_4",
                storeys,
                timber,
            )
        )
    towers = []
    for identifier, x, y, radius_, height in (
        ("west_tower", -8.3, 7.8, 2.7, 23),
        ("high_tower", 7.0, 10.3, 2.8, 28),
        ("chapel_tower", 10.3, -2.8, 2.0, 17),
        ("fore_tower", -11.5, -7.5, 2.2, 14),
    ):
        towers.append(
            CastleTower(
                identifier,
                (x * scale, y * scale),
                max(1.9, radius_ * scale),
                max(2, round(height * scale / floor_height)) * floor_height,
                radius_ * rng.uniform(2.15, 2.55) * scale,
            )
        )
    towers = [
        replace(
            t, height=required_tower_height(t, blocks, scale, floor_height)
        )
        for t in towers
    ]
    donjon = blocks[1]
    for side in (-1, 1):
        base = 5 * floor_height
        towers.append(
            CastleTower(
                f"oriel_{side}",
                ((3 + side * 4) * scale, 5.7 * scale),
                1.15 * scale,
                donjon.height - base,
                3.2 * scale,
                base,
                "PYRAMID_8",
            )
        )
    outline = []
    for index, (x, y) in enumerate(
        (
            (-0.43, -0.84),
            (0.43, -0.84),
            (0.78, -0.59),
            (0.94, -0.15),
            (0.91, 0.34),
            (0.60, 0.78),
            (0.14, 0.96),
            (-0.36, 0.89),
            (-0.72, 0.62),
            (-0.94, 0.15),
            (-0.87, -0.40),
        )
    ):
        variation = 1 if index < 2 else rng.uniform(0.96, 1.03)
        outline.append((x * radius * variation, y * radius * variation))
    return CastleArchitecture(
        scale,
        tuple(outline),
        tuple(blocks),
        tuple(towers),
        max(6.2, 6.4 * scale),
        max(4.8, 5 * scale),
        (-1.0 * scale, -2.2 * scale, 0.12),
        floor_height,
    )
