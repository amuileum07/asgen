"""Profiled clay tiles, overlapping ridge caps, and rafter tails."""

import math
from itertools import pairwise

from mathutils import Vector

from house_rules import clip_polygon, polygon_area, rectangle


def ridge_caps(batch, a, b, material):
    """Build tapered overlapping half-round terracotta ridge tiles."""
    a, b = Vector(a), Vector(b)
    length = (b - a).length
    if length < 1e-6:
        return
    axis = (b - a).normalized()
    across = axis.cross(Vector((0, 0, 1)))
    if across.length < 1e-6:
        across = Vector((1, 0, 0))
    else:
        across.normalize()
    up = across.cross(axis)
    # Mortar bedding strip seals the crest beneath the ridge tiles.
    bed = [
        across * (0.115 * math.cos(i * math.pi / 4))
        + up * (0.015 + 0.078 * math.sin(i * math.pi / 4))
        for i in range(5)
    ]
    batch.prism(
        [a + p for p in bed],
        b - a,
        "stone" if "stone" in batch.material_indices else material,
    )

    count = max(1, math.ceil(length / 0.36))
    pitch = (b - a) / count
    sides = 8
    first_r, last_r = 0.142, 0.126
    first_h, last_h = 0.128, 0.114
    thick = 0.022
    slot = batch.material_indices[material]
    for i in range(count):
        start = a + pitch * i
        end = start + pitch * 1.03
        # Slight upward lap angle overlaps each ridge tile.
        lift_s, lift_e = up * 0.036, up * 0.052
        outer_s, inner_s, outer_e, inner_e = [], [], [], []
        for k in range(sides + 1):
            ang = k * math.pi / sides
            c, s = math.cos(ang), math.sin(ang)
            outer_s.append(
                start + lift_s + across * (first_r * c) + up * (first_h * s)
            )
            inner_s.append(
                start
                + lift_s
                + across * ((first_r - thick) * c)
                + up * ((first_h - thick) * s)
            )
            outer_e.append(
                end + lift_e + across * (last_r * c) + up * (last_h * s)
            )
            inner_e.append(
                end
                + lift_e
                + across * ((last_r - thick) * c)
                + up * ((last_h - thick) * s)
            )
        base = len(batch.vertices)
        ring_s = outer_s + list(reversed(inner_s))
        ring_e = outer_e + list(reversed(inner_e))
        n = len(ring_s)
        batch.vertices.extend(tuple(p) for p in ring_s)
        batch.vertices.extend(tuple(p) for p in ring_e)
        faces = [
            tuple(base + j for j in reversed(range(n))),
            tuple(base + n + j for j in range(n)),
        ]
        for j in range(n):
            jn = (j + 1) % n
            faces.append((base + j, base + jn, base + n + jn, base + n + j))
        batch.faces.extend(faces)
        batch.face_materials.extend([slot] * len(faces))


def eaves_rafters(batch, a, b, normal, material, spacing=0.64):
    """Place exposed timber rafter tails along horizontal eaves."""
    a, b = Vector(a), Vector(b)
    span = (b - a).length
    if span < 0.8 or abs(b.z - a.z) > 1e-4:
        return
    along = (b - a).normalized()
    outward = Vector((normal.x, normal.y, 0.0))
    if outward.length < 1e-4:
        return
    outward.normalize()
    slope_dir = along.cross(normal).normalized()
    if slope_dir.dot(outward) < 0:
        slope_dir = -slope_dir
    count = max(2, round(span / spacing))
    for i in range(1, count):
        t = i / count
        eave_pt = a.lerp(b, t)
        # Tuck rafter beam neatly beneath roof sheathing and trim.
        start = eave_pt - slope_dir * 0.42 - normal * 0.145
        end = eave_pt + slope_dir * 0.03 - normal * 0.145
        batch.beam(start, end, 0.085, material)


def pan_tile(
    batch, polygon, left, bottom, width, height, axes, material, rng=None
):
    """Build one closed curved clay pantile with optional jitter."""
    origin, u, v, normal = axes
    # S-curve channel and rolled crown form an authentic pantile.
    profile = (
        (0.0, 0.024),
        (0.18, 0.017),
        (0.46, 0.020),
        (0.64, 0.042),
        (0.78, 0.072),
        (0.90, 0.076),
        (1.0, 0.044),
    )
    lift_jitter = rng.uniform(-0.0035, 0.0045) if rng else 0.0
    roll_jitter = rng.uniform(-0.003, 0.003) if rng else 0.0
    pitch_jitter = rng.uniform(-0.003, 0.004) if rng else 0.0
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
                u_frac = (x - left) / width
                h += 0.020 * (1 - lap if v.z > 0 else lap)
                h += (
                    lift_jitter
                    + roll_jitter * (u_frac - 0.5)
                    + pitch_jitter * (lap - 0.5)
                )
                point = origin + u * x + v * y + normal * h
                lookup[key] = len(batch.vertices)
                batch.vertices.extend(
                    (tuple(point), tuple(point - normal * 0.024))
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
