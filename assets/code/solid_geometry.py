"""Convex solid clipping with closed caps and shared edge vertices."""

import math


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def convex_planes(vertices, faces):
    result = []
    for face in faces:
        a, b, c = (vertices[i] for i in face[:3])
        u, v = (tuple(p[j] - a[j] for j in range(3)) for p in (b, c))
        n = _cross(u, v)
        size = math.sqrt(_dot(n, n))
        n = tuple(x / size for x in n)
        result.append((*n, _dot(n, a)))
    return tuple(result)


def _clean(points):
    result = []
    for p in points:
        if not result or math.dist(result[-1], p) > 1e-8:
            result.append(tuple(p))
    if len(result) > 1 and math.dist(result[0], result[-1]) < 1e-8:
        result.pop()
    while len(result) > 3:
        remove = None
        for i, b in enumerate(result):
            a, c = result[i - 1], result[(i + 1) % len(result)]
            u = tuple(b[j] - a[j] for j in range(3))
            v = tuple(c[j] - b[j] for j in range(3))
            if math.sqrt(_dot(_cross(u, v), _cross(u, v))) < 1e-10:
                remove = i
                break
        if remove is None:
            break
        result.pop(remove)
    if len(result) < 3:
        return ()
    a = result[0]
    area = (0, 0, 0)
    for b, c in zip(result[1:-1], result[2:], strict=True):
        u = tuple(b[j] - a[j] for j in range(3))
        v = tuple(c[j] - a[j] for j in range(3))
        n = _cross(u, v)
        area = tuple(area[j] + n[j] for j in range(3))
    return tuple(result) if _dot(area, area) > 1e-18 else ()


def clip_solid(vertices, faces, planes):
    """Keep n dot p <= d; each plane is (nx, ny, nz, d)."""
    polygons = [tuple(vertices[i] for i in f) for f in faces]
    for nx, ny, nz, d in planes:
        normal = (nx, ny, nz)
        if all(_dot(normal, p) <= d + 1e-8 for f in polygons for p in f):
            continue
        kept, cuts = [], {}
        for face in polygons:
            clipped = []
            for a, b in zip(face, face[1:] + face[:1], strict=True):
                va, vb = d - _dot(normal, a), d - _dot(normal, b)
                if va >= -1e-8:
                    clipped.append(a)
                if (va < -1e-8) != (vb < -1e-8):
                    t = va / (va - vb)
                    p = tuple(a[i] + (b[i] - a[i]) * t for i in range(3))
                    clipped.append(p)
                    cuts[tuple(round(v, 8) for v in p)] = p
            cleaned = _clean(clipped)
            if cleaned:
                kept.append(cleaned)
        if len(cuts) >= 3:
            centre = tuple(
                sum(p[i] for p in cuts.values()) / len(cuts) for i in range(3)
            )
            reference = (0, 0, 1) if abs(nz) < 0.9 else (1, 0, 0)
            u = _cross(reference, normal)
            size = math.sqrt(_dot(u, u))
            u = tuple(v / size for v in u)
            v = _cross(normal, u)
            cap = sorted(
                cuts.values(),
                key=lambda p: math.atan2(
                    _dot(v, tuple(p[i] - centre[i] for i in range(3))),
                    _dot(u, tuple(p[i] - centre[i] for i in range(3))),
                ),
            )
            cleaned = _clean(cap)
            if cleaned:
                kept.append(cleaned)
        polygons = kept
        if not polygons:
            return (), ()
    result, indices, lookup = [], [], {}
    for face in polygons:
        row = []
        for p in face:
            key = tuple(round(v, 8) for v in p)
            if key not in lookup:
                lookup[key] = len(result)
                result.append(tuple(p))
            row.append(lookup[key])
        indices.append(tuple(row))
    return tuple(result), tuple(indices)
