"""Small planar operations for overlapping castle footprints."""

import math

from terrain_rules import inside_polygon, segment_projection

EPSILON = 1e-7


def rectangle(x1, y1, x2, y2):
    return ((x1, y1), (x2, y1), (x2, y2), (x1, y2))


def circle(centre, radius, count=16):
    return tuple(
        (
            centre[0] + radius * math.cos(i * math.tau / count),
            centre[1] + radius * math.sin(i * math.tau / count),
        )
        for i in range(count)
    )


def edges(polygon):
    return tuple(zip(polygon, polygon[1:] + polygon[:1], strict=True))


def owner_at(point, shapes):
    return next(
        (name for name, polygon in shapes if inside_polygon(point, polygon)),
        None,
    )


def intersection(a, b, c, d):
    dx, dy = b[0] - a[0], b[1] - a[1]
    ex, ey = d[0] - c[0], d[1] - c[1]
    denominator = dx * ey - dy * ex
    if abs(denominator) < EPSILON:
        return None
    cx, cy = c[0] - a[0], c[1] - a[1]
    t = (cx * ey - cy * ex) / denominator
    u = (cx * dy - cy * dx) / denominator
    if -EPSILON <= t <= 1 + EPSILON and -EPSILON <= u <= 1 + EPSILON:
        return t, (a[0] + dx * t, a[1] + dy * t)
    return None


def planar_regions(shapes, holes=()):
    """Disjoint trapezoids of a labelled union minus polygon holes."""
    segments = [edge for _, polygon in shapes for edge in edges(polygon)]
    segments += [edge for polygon in holes for edge in edges(polygon)]
    ys = {round(p[1], 8) for edge in segments for p in edge}
    for index, (a, b) in enumerate(segments):
        for c, d in segments[index + 1 :]:
            hit = intersection(a, b, c, d)
            if hit:
                ys.add(round(hit[1][1], 8))
    ys = sorted(ys)
    result = []
    for bottom, top in zip(ys, ys[1:], strict=False):
        if top - bottom < EPSILON:
            continue
        middle = (bottom + top) / 2
        crossings = []
        for a, b in segments:
            if (a[1] > middle) == (b[1] > middle):
                continue
            slope = (b[0] - a[0]) / (b[1] - a[1])
            offset = a[0] - slope * a[1]
            crossings.append((slope * middle + offset, slope, offset))
        crossings.sort()
        for left, right in zip(crossings, crossings[1:], strict=False):
            if right[0] - left[0] < EPSILON:
                continue
            point = ((left[0] + right[0]) / 2, middle)
            owner = owner_at(point, shapes)
            if owner is None or any(inside_polygon(point, p) for p in holes):
                continue
            points = (
                (left[1] * bottom + left[2], bottom),
                (right[1] * bottom + right[2], bottom),
                (right[1] * top + right[2], top),
                (left[1] * top + left[2], top),
            )
            polygon = []
            for p in points:
                if not polygon or math.dist(p, polygon[-1]) > 1e-5:
                    polygon.append(p)
            if len(polygon) > 1 and math.dist(polygon[0], polygon[-1]) < 1e-5:
                polygon.pop()
            area = (
                abs(
                    sum(
                        a[0] * b[1] - b[0] * a[1]
                        for a, b in edges(tuple(polygon))
                    )
                )
                / 2
            )
            if len(polygon) > 2 and area > 1e-6:
                result.append((owner, tuple(polygon)))
    return tuple(result)


def boundary_segments(shapes):
    """Find exterior walls and interfaces between labelled rooms."""
    segments = [edge for _, polygon in shapes for edge in edges(polygon)]
    result, seen = [], set()
    for a, b in segments:
        length = math.dist(a, b)
        if length < EPSILON:
            continue
        cuts = {0.0, 1.0}
        for c, d in segments:
            hit = intersection(a, b, c, d)
            if hit:
                cuts.add(min(1.0, max(0.0, hit[0])))
            for point in (c, d):
                distance, t, _ = segment_projection(point, a, b)
                if distance < EPSILON:
                    cuts.add(t)
        cuts = sorted(cuts)
        for low, high in zip(cuts, cuts[1:], strict=False):
            if (high - low) * length < EPSILON:
                continue
            p, q = [
                tuple(a[i] + (b[i] - a[i]) * t for i in (0, 1))
                for t in (low, high)
            ]
            key = tuple(sorted(tuple(round(v, 6) for v in r) for r in (p, q)))
            if key in seen:
                continue
            seen.add(key)
            middle = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            nx, ny = -(b[1] - a[1]) / length, (b[0] - a[0]) / length
            left = owner_at(
                (middle[0] + nx * 1e-4, middle[1] + ny * 1e-4), shapes
            )
            right = owner_at(
                (middle[0] - nx * 1e-4, middle[1] - ny * 1e-4), shapes
            )
            if left != right:
                result.append((p, q, left, right))
    return tuple(result)


def subtract_prism(face, polygon, bottom, top):
    """Clip a planar 3D face outside a convex vertical room volume."""
    planes = []
    for a, b in edges(polygon):
        dx, dy = b[0] - a[0], b[1] - a[1]
        planes.append((-dy, dx, 0, dy * a[0] - dx * a[1]))
    planes.extend(((0, 0, 1, -bottom), (0, 0, -1, top)))
    return subtract_convex(face, planes)


def subtract_convex(face, planes):
    """Subtract an intersection of positive 3D half-spaces."""
    pending, outside = list(face), []
    for nx, ny, nz, offset in planes:
        if len(pending) < 3:
            break
        inside, removed = [], []
        for a, b in zip(pending, pending[1:] + pending[:1], strict=True):
            va = nx * a[0] + ny * a[1] + nz * a[2] + offset
            vb = nx * b[0] + ny * b[1] + nz * b[2] + offset
            (inside if va >= -1e-8 else removed).append(a)
            if (va < -1e-8) != (vb < -1e-8):
                t = va / (va - vb)
                p = tuple(a[i] + (b[i] - a[i]) * t for i in range(3))
                inside.append(p)
                removed.append(p)
        if len(removed) >= 3:
            outside.append(tuple(removed))
        pending = inside
    return tuple(outside)
