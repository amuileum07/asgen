"""Closed, profiled clay tiles and segmented ridge caps."""

import math
from itertools import pairwise

from mathutils import Vector

from house_rules import clip_polygon, polygon_area, rectangle


def ridge_caps(batch, a, b, material):
    a, b = Vector(a), Vector(b)
    axis = (b - a).normalized()
    across = axis.cross(Vector((0, 0, 1))).normalized()
    up = across.cross(axis)
    count = max(1, math.ceil((b - a).length / 0.47))
    section = [
        across * (0.155 * math.cos(i * math.pi / 8))
        + up * (0.038 + 0.135 * math.sin(i * math.pi / 8))
        for i in range(9)
    ]
    pitch = (b - a) / count
    for i in range(count):
        start = a + pitch * i
        batch.prism([start + p for p in section], pitch * 0.985, material)


def pan_tile(batch, polygon, left, bottom, width, height, axes, material):
    origin, u, v, normal = axes
    # A channel and rolled edge form the cross section of one tile.
    profile = (
        (0, 0.024),
        (0.22, 0.022),
        (0.54, 0.032),
        (0.69, 0.073),
        (0.83, 0.089),
        (1, 0.050),
    )
    lookup, perimeter = {}, set()
    faces = []
    for (t0, h0), (t1, h1) in pairwise(profile):
        x0, x1 = left + t0 * width, left + t1 * width
        strip = clip_polygon(
            polygon, rectangle(x0, bottom, x1, bottom + height)
        )
        if len(strip) < 3 or polygon_area(strip) < 1e-7:
            continue
        ring = []
        for x, y in strip:
            key = round(x, 7), round(y, 7)
            if key not in lookup:
                h = h0 + (h1 - h0) * ((x - x0) / (x1 - x0))
                lap = (y - bottom) / height
                h += 0.018 * (1 - lap if v.z > 0 else lap)
                point = origin + u * x + v * y + normal * h
                lookup[key] = len(batch.vertices)
                batch.vertices.extend(
                    (tuple(point), tuple(point - normal * 0.017))
                )
            ring.append(lookup[key])
        faces.extend((tuple(ring), tuple(i + 1 for i in reversed(ring))))
        for a, b in zip(ring, ring[1:] + ring[:1], strict=True):
            if (b, a) in perimeter:
                perimeter.remove((b, a))
            else:
                perimeter.add((a, b))
    faces.extend((b, a, a + 1, b + 1) for a, b in sorted(perimeter))
    batch.faces.extend(faces)
    batch.face_materials.extend(
        [batch.material_indices[material]] * len(faces)
    )
