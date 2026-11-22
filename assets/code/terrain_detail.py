"""Refine natural slopes without splitting roads or boundary edges."""

import math
from collections import Counter

from terrain_rules import smoothstep, value_noise


def refine_slopes(points, triangles, codes, height_at, seed, allowed=None):
    """Add shared relief samples between natural triangles."""
    edges = Counter()
    for (a, b, c), code in zip(triangles, codes, strict=True):
        if code:
            continue
        p, q, r = points[a], points[b], points[c]
        dx, dy, dz = (q[i] - p[i] for i in range(3))
        ex, ey, ez = (r[i] - p[i] for i in range(3))
        area = abs(dx * ey - dy * ex)
        if (
            area < 0.45
            or math.hypot(dy * ez - dz * ey, dz * ex - dx * ez) < 0.10 * area
        ):
            continue
        if allowed and not allowed(
            (p[0] + q[0] + r[0]) / 3, (p[1] + q[1] + r[1]) / 3
        ):
            continue
        for i, j in ((a, b), (b, c), (c, a)):
            edges[min(i, j), max(i, j)] += 1

    mids = {}
    for (a, b), count in edges.items():
        if count != 2:
            continue
        p, q = points[a], points[b]
        run = math.dist(p[:2], q[:2])
        if run < 1.0:
            continue
        x, y, z = ((p[i] + q[i]) / 2 for i in range(3))
        grade = abs(p[2] - q[2]) / run
        # Skewed strata break up the slope at two physical wavelengths.
        ridge = 0.5 - abs(value_noise(x / 3.7, y / 3.7 + z / 1.7, seed))
        grit = value_noise(x / 1.6, y / 1.6, seed + 43)
        relief = (ridge + 0.38 * grit) * (0.08 + smoothstep(0.1, 0.9, grade))
        limit = min(0.72, run * 0.095)
        dz = max(-limit, min(limit, height_at(x, y) - z + relief))
        mids[a, b] = len(points)
        points.append((x, y, z + dz))

    faces, kinds = [], []
    for face, code in zip(triangles, codes, strict=True):
        a, b, c = face
        cuts = [
            mids.get((min(i, j), max(i, j)))
            for i, j in ((a, b), (b, c), (c, a))
        ]
        n = sum(v is not None for v in cuts)
        if n == 3:
            u, v, w = cuts
            pieces = ((a, u, w), (u, b, v), (w, v, c), (u, v, w))
        elif n:
            # Rotate to put the first consecutive split edge at a-b.
            i = next(
                i
                for i in range(3)
                if cuts[i] is not None and cuts[i - 1] is None
            )
            a, b, c = face[i], face[(i + 1) % 3], face[(i + 2) % 3]
            u, v = cuts[i], cuts[(i + 1) % 3]
            pieces = (
                ((a, u, c), (u, b, c))
                if n == 1
                else ((a, u, c), (u, v, c), (u, b, v))
            )
        else:
            pieces = (face,)
        faces.extend(pieces)
        kinds.extend([code] * len(pieces))
    return faces, kinds
