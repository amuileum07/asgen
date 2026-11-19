"""Check closed, capped solids and complete roof envelopes."""

import math
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from house_rules import ROOF_STYLES, HouseConfig, make_plan, roof_planes
from solid_geometry import clip_solid

BOX = (
    (0, 0, 0),
    (1, 0, 0),
    (1, 1, 0),
    (0, 1, 0),
    (0, 0, 1),
    (1, 0, 1),
    (1, 1, 1),
    (0, 1, 1),
)
FACES = (
    (3, 2, 1, 0),
    (4, 5, 6, 7),
    (0, 1, 5, 4),
    (1, 2, 6, 5),
    (2, 3, 7, 6),
    (3, 0, 4, 7),
)


class SolidTests(unittest.TestCase):
    def test_trimmed_solid_has_caps_and_two_faces_per_edge(self):
        vertices, faces = clip_solid(BOX, FACES, ((1, 0, 1, 1.2),))
        self.assertTrue(vertices and faces)
        self.assertTrue(all(p[0] + p[2] <= 1.200001 for p in vertices))
        edges = Counter(
            tuple(sorted((a, b)))
            for f in faces
            for a, b in zip(f, f[1:] + f[:1], strict=True)
        )
        self.assertTrue(all(n == 2 for n in edges.values()), edges)
        self.assertTrue(
            any(
                all(
                    abs(vertices[i][0] + vertices[i][2] - 1.2) < 1e-6
                    for i in f
                )
                for f in faces
            )
        )

    def test_roof_planes_include_underside_and_all_roof_styles(self):
        for style in ROOF_STYLES:
            plan = make_plan(HouseConfig(roof_style=style))
            for nx, ny, nz, d in roof_planes(plan, 0.15):
                self.assertAlmostEqual(
                    math.sqrt(nx * nx + ny * ny + nz * nz), 1
                )
                self.assertGreater(nz, 0)
                self.assertTrue(math.isfinite(d))

    def test_fully_removed_solid_is_empty(self):
        self.assertEqual(clip_solid(BOX, FACES, ((0, 0, 1, -1),)), ((), ()))
