"""Bound road triangle slopes, including narrow junction faces."""

import heapq
import math
from collections import defaultdict


class SurfaceGradeError(ValueError):
    """The authored road levels cannot be resolved on this surface."""


def _envelope(graph, seeds):
    result = dict.fromkeys(graph, math.inf)
    result.update(seeds)
    queue = [(value, i) for i, value in seeds.items()]
    heapq.heapify(queue)
    while queue:
        value, i = heapq.heappop(queue)
        if value > result[i] + 1e-12:
            continue
        for j, weight in graph[i]:
            candidate = value + weight
            if candidate < result[j] - 1e-12:
                result[j] = candidate
                heapq.heappush(queue, (candidate, j))
    return result


def _edge_projector(edges, heights, fixed):
    graph = defaultdict(list)
    for a, b, weight in edges:
        graph[a].append((b, weight))
        graph[b].append((a, weight))
    seeds = {i: heights[i] for i in graph if i in fixed}
    upper = _envelope(graph, seeds)
    lower = _envelope(graph, {i: -v for i, v in seeds.items()})
    if any(-lower[i] > upper[i] + 1e-6 for i in graph):
        raise SurfaceGradeError("Fixed road endpoints are too steep")

    def project():
        values = {i: min(upper[i], max(-lower[i], heights[i])) for i in graph}
        high = _envelope(graph, values)
        low = _envelope(graph, {i: -v for i, v in values.items()})
        change = 0
        for i in graph:
            value = (high[i] - low[i]) / 2
            change = max(change, abs(value - heights[i]))
            heights[i] = value
        return change

    return project


def limit_road_slopes(
    vertices,
    triangles,
    codes,
    limit,
    *,
    fixed=(),
    centre_edges=(),
    longitudinal=0.2,
):
    """Project heights onto triangle gradient constraints in place.

    The minimum local correction avoids flattening an entire face when
    its steep normal comes from a very narrow triangle at a junction.
    """
    heights = [p[2] for p in vertices]
    fixed = set(fixed)
    edges = [
        (a, b, math.dist(vertices[a][:2], vertices[b][:2]) * longitudinal)
        for a, b in centre_edges
        if a != b
    ]
    project_edges = _edge_projector(edges, heights, fixed)
    constraints = []
    for indices, code in zip(triangles, codes, strict=True):
        if not code:
            continue
        a, b, c = (vertices[i] for i in indices)
        det = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])
        if abs(det) < 1e-12:
            continue
        gx = ((b[1] - c[1]) / det, (c[1] - a[1]) / det, (a[1] - b[1]) / det)
        gy = ((c[0] - b[0]) / det, (a[0] - c[0]) / det, (b[0] - a[0]) / det)
        constraints.append((indices, gx, gy))
    target = limit * 0.995
    for sweep in range(600):
        worst = 0
        order = constraints if sweep % 2 == 0 else reversed(constraints)
        for indices, gx, gy in order:
            z = [heights[i] for i in indices]
            x = sum(c * v for c, v in zip(gx, z, strict=True))
            y = sum(c * v for c, v in zip(gy, z, strict=True))
            slope = math.hypot(x, y)
            worst = max(worst, slope)
            if slope <= target:
                continue
            derivative = [
                0 if i in fixed else (x * a + y * b) / slope
                for i, a, b in zip(indices, gx, gy, strict=True)
            ]
            norm = sum(d * d for d in derivative)
            if norm < 1e-15:
                if slope > limit + 1e-5:
                    raise SurfaceGradeError(
                        "Fixed road levels form a steep face"
                    )
                continue
            amount = (slope - target) / norm
            for i, d in zip(indices, derivative, strict=True):
                heights[i] -= amount * d
        edge_change = project_edges()
        if worst <= limit:
            final_grade = max(
                (
                    math.hypot(
                        sum(
                            a * heights[i]
                            for i, a in zip(ids, gx, strict=True)
                        ),
                        sum(
                            b * heights[i]
                            for i, b in zip(ids, gy, strict=True)
                        ),
                    )
                    for ids, gx, gy in constraints
                ),
                default=0,
            )
            if final_grade <= limit:
                break
    else:
        raise SurfaceGradeError(
            f"Road surface slope solver did not converge: "
            f"grade={worst:.8f}, edge change={edge_change:.8f}"
        )
    displacement = max(
        abs(z - point[2]) for z, point in zip(heights, vertices, strict=True)
    )
    for i, z in enumerate(heights):
        vertices[i] = (*vertices[i][:2], z)
    return displacement
