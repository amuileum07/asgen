"""Roof primitives, envelopes and wall-junction exclusions."""

import math
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class RoofSpec:
    id: str
    centre: tuple
    z: float
    width: float
    depth: float
    height: float
    kind: str
    segments: int

    @property
    def top(self):
        return self.z + self.height


def roof_height_at(roof, x, y):
    """Closed roof envelope; return None outside its eaves."""
    u = (x - roof.centre[0]) / (roof.width / 2)
    v = (y - roof.centre[1]) / (roof.depth / 2)
    if roof.kind == "PYRAMID_4":
        radius = max(abs(u), abs(v))
    elif roof.kind == "PYRAMID_8":
        # Gauge of the same regular octagon used by the mesh.
        radius = max(
            (
                u * math.cos((i + 0.5) * math.tau / 8)
                + v * math.sin((i + 0.5) * math.tau / 8)
            )
            / math.cos(math.pi / 8)
            for i in range(8)
        )
    else:
        radius = math.hypot(u, v)
    return None if radius > 1 + 1e-8 else roof.z + roof.height * (1 - radius)


def block_roofs(architecture, base=0.12):
    s = architecture.scale
    return tuple(
        RoofSpec(
            b.id,
            b.centre,
            base + b.height,
            b.size[0] + 0.56 * s,
            b.size[1] + 0.56 * s,
            b.roof_height,
            "PYRAMID_4",
            4,
        )
        for b in architecture.blocks
    )


def tower_roof(tower, scale, base=0.12):
    kind = getattr(tower, "roof", "CONE")
    segments = 8 if kind == "PYRAMID_8" else 40
    diameter = (tower.radius + 0.27 * scale) * 2
    return RoofSpec(
        tower.id,
        tower.centre,
        base + tower.base + tower.height,
        diameter,
        diameter,
        tower.roof_height,
        kind,
        segments,
    )


def roof_geometry(roof):
    """One real apex and exactly four/eight/forty triangular sides."""
    x, y = roof.centre
    if roof.kind == "PYRAMID_4":
        ring = [
            (x + u * roof.width / 2, y + v * roof.depth / 2, roof.z)
            for u, v in ((-1, -1), (1, -1), (1, 1), (-1, 1))
        ]
    else:
        ring = [
            (
                x + roof.width / 2 * math.cos(i * math.tau / roof.segments),
                y + roof.depth / 2 * math.sin(i * math.tau / roof.segments),
                roof.z,
            )
            for i in range(roof.segments)
        ]
    vertices = tuple(ring + [(x, y, roof.top)])
    n = len(ring)
    faces = [tuple(reversed(range(n)))]
    faces += [(i, (i + 1) % n, n) for i in range(n)]
    return vertices, tuple(faces)


def window_under_roof(architecture, a, b, z1, z2, *, margin=0.25):
    """Reject the whole opening and its trim in a roof/wall junction."""
    for roof in architectural_roofs(architecture):
        for t in (0, 0.25, 0.5, 0.75, 1):
            x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            top = roof_height_at(roof, x, y)
            if top is not None and z1 - margin < top and z2 + margin > roof.z:
                return True
    return False


@lru_cache(maxsize=32)
def architectural_roofs(architecture):
    return block_roofs(architecture) + tuple(
        tower_roof(t, architecture.scale) for t in architecture.towers
    )


def required_tower_height(tower, blocks, scale, floor_height):
    """A tower cap clears every attached lower roof, in whole floors."""
    highest = tower.height
    radius = tower.radius + 0.27 * scale
    for block in blocks:
        roof = RoofSpec(
            block.id,
            block.centre,
            block.height,
            block.size[0] + 0.56 * scale,
            block.size[1] + 0.56 * scale,
            block.roof_height,
            "PYRAMID_4",
            4,
        )
        for i in range(40):
            angle = i * math.tau / 40
            z = roof_height_at(
                roof,
                tower.centre[0] + radius * math.cos(angle),
                tower.centre[1] + radius * math.sin(angle),
            )
            if z is not None:
                highest = max(highest, z + 0.35 * scale)
    return math.ceil((highest - 1e-6) / floor_height) * floor_height
