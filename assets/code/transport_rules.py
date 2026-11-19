"""Continuous road footprints and junction elevations."""

import math
from collections import defaultdict
from dataclasses import replace

from castle_geometry import intersection
from terrain_rules import SpatialHash


def resample(points, spacing=1.25):
    result = [points[0]]
    for a, b in zip(points, points[1:], strict=False):
        count = max(1, math.ceil(math.dist(a[:2], b[:2]) / spacing))
        result.extend(
            tuple(a[j] + (b[j] - a[j]) * i / count for j in range(len(a)))
            for i in range(1, count + 1)
        )
    return tuple(result)


def road_footprints(road):
    """A continuous offset corridor without internal segment seams."""
    points = [p[:2] for p in road.points]
    radius = road.width / 2
    closed = math.dist(points[0], points[-1]) < 1e-5
    if closed:
        points.pop()
    normals = []
    pairs = zip(
        points, points[1:] + (points[:1] if closed else []), strict=False
    )
    for a, b in pairs:
        length = math.dist(a, b)
        normals.append((-(b[1] - a[1]) / length, (b[0] - a[0]) / length))
    left, right = [], []
    for i, p in enumerate(points):
        a = normals[i - 1] if i or closed else normals[0]
        b = normals[min(i, len(normals) - 1)]
        nx, ny = a[0] + b[0], a[1] + b[1]
        length = max(1e-8, math.hypot(nx, ny))
        nx, ny = nx / length, ny / length
        extent = min(radius * 1.5, radius / max(0.1, nx * b[0] + ny * b[1]))
        left.append((p[0] + nx * extent, p[1] + ny * extent))
        right.append((p[0] - nx * extent, p[1] - ny * extent))
    if closed:
        return tuple(left), tuple(reversed(right))

    def cap(p, normal):
        angle = math.atan2(normal[1], normal[0])
        return [
            (
                p[0] + radius * math.cos(angle - math.pi * j / 8),
                p[1] + radius * math.sin(angle - math.pi * j / 8),
            )
            for j in range(1, 8)
        ]

    return (
        tuple(
            left
            + cap(points[-1], normals[-1])
            + list(reversed(right))
            + cap(points[0], (-normals[0][0], -normals[0][1]))
        ),
    )


def conform_junctions(roads, terrain, max_grade):
    """Split all geometric crossings and make their height identical."""
    segments, index = [], SpatialHash(10)
    for ri, road in enumerate(roads):
        for si, (a, b) in enumerate(
            zip(road.points, road.points[1:], strict=False)
        ):
            index.insert(
                len(segments),
                (
                    min(a[0], b[0]),
                    min(a[1], b[1]),
                    max(a[0], b[0]),
                    max(a[1], b[1]),
                ),
            )
            segments.append((ri, si, a, b))
    splits = defaultdict(list)
    values = defaultdict(list)

    def key(p):
        return tuple(round(v, 5) for v in p[:2])

    for i, (ri, si, a, b) in enumerate(segments):
        for p, t in ((a, 0), (b, 1)):
            splits[ri, si].append((t, key(p)))
            values[key(p)].append(p[2])
        middle = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        for j in sorted(index.query(middle, math.dist(a[:2], b[:2]) / 2 + 1)):
            if j <= i:
                continue
            rj, sj, c, d = segments[j]
            hit = intersection(a, b, c, d)
            if not hit:
                continue
            t, p = hit
            other = intersection(c, d, a, b)
            u = other[0]
            k = key(p)
            splits[ri, si].append((t, k))
            splits[rj, sj].append((u, k))
            values[k].extend(
                (a[2] + (b[2] - a[2]) * t, c[2] + (d[2] - c[2]) * u)
            )
    heights = {k: sum(v) / len(v) for k, v in values.items()}
    paths = []
    for ri, road in enumerate(roads):
        points = []
        for si in range(len(road.points) - 1):
            for _, p in sorted(splits[ri, si]):
                if not points or math.dist(points[-1], p) > 1e-5:
                    points.append(p)
        paths.append(points)
    links = {
        tuple(sorted((a, b))): max_grade * 0.999 * math.dist(a, b)
        for path in paths
        for a, b in zip(path, path[1:], strict=False)
        if a != b
    }
    # Nearby road beds must also agree across their full paved width.
    # Longitudinal limits alone allow overlaps at two different levels.
    neighbours = SpatialHash(8)
    for p in sorted(heights):
        for other in sorted(neighbours.query(p, 10)):
            distance = math.dist(p, other)
            if distance <= 10:
                pair = tuple(sorted((p, other)))
                limit = (max_grade + 0.10) * distance
                links[pair] = min(limit, links.get(pair, math.inf))
        neighbours.insert(p, (*p, *p))
    links = [(a, b, limit) for (a, b), limit in sorted(links.items())]
    fixed = set()
    for p in heights:
        if any(
            math.dist(p, (x, y)) < radius - 0.2
            for x, y, radius, _ in terrain.plazas
        ):
            fixed.add(p)
        if terrain.castle_pad:
            x, y, radius, _ = terrain.castle_pad
            if math.dist(p, (x, y)) < radius:
                fixed.add(p)
    for _ in range(1200):
        worst = 0
        for a, b, limit in links:
            difference = heights[b] - heights[a]
            excess = abs(difference) - limit
            if excess < 1e-7:
                continue
            worst = max(worst, excess)
            sign = 1 if difference > 0 else -1
            if a in fixed and b in fixed:
                if excess > 1e-4:
                    raise ValueError(
                        "Two fixed road levels violate the grade limit"
                    )
            elif a in fixed:
                heights[b] -= sign * excess
            elif b in fixed:
                heights[a] += sign * excess
            else:
                heights[a] += sign * excess / 2
                heights[b] -= sign * excess / 2
        if worst < 1e-6:
            break
    return [
        replace(road, points=tuple((*p, heights[p]) for p in path))
        for road, path in zip(roads, paths, strict=True)
    ]
