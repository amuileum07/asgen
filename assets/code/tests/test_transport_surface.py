"""Check surface constraints that centreline-only tests cannot see."""

import math
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from settlement_rules import Road
from surface_quality import limit_road_slopes
from terrain_detail import refine_slopes
from terrain_rules import TerrainSpec, inside_polygon, terrain_height
from transport_rules import conform_junctions, road_footprints


class TransportSurfaceTests(unittest.TestCase):
    def test_rock_relief_shares_edges_and_preserves_pavement(self):
        points = [(x, y, x / 2) for y in (0, 2, 4) for x in (0, 2, 4)]
        original = points.copy()
        triangles = [
            face
            for a in (0, 1, 3, 4)
            for face in ((a, a + 1, a + 4), (a, a + 4, a + 3))
        ]
        codes = [3] + [0] * 7
        faces, kinds = refine_slopes(
            points, triangles, codes, lambda x, y: x / 2, 42
        )
        self.assertEqual(points[:9], original)
        self.assertEqual(
            [f for f, k in zip(faces, kinds, strict=True) if k], triangles[:1]
        )
        self.assertGreater(len(points), 9)
        self.assertTrue(any(abs(z - x / 2) > 0.001 for x, y, z in points[9:]))
        counts = {}
        for a, b, c in faces:
            p, q, r = points[a], points[b], points[c]
            self.assertGreater(
                (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]),
                0,
            )
            for i, j in ((a, b), (b, c), (c, a)):
                edge = tuple(sorted((i, j)))
                counts[edge] = counts.get(edge, 0) + 1
        boundary = {
            (0, 1),
            (1, 2),
            (2, 5),
            (5, 8),
            (7, 8),
            (6, 7),
            (3, 6),
            (0, 3),
        }
        self.assertEqual({e for e, n in counts.items() if n == 1}, boundary)
        self.assertEqual(set(counts.values()), {1, 2})

    def test_plaza_height_has_priority_over_castle_approach(self):
        spec = TerrainSpec(
            42,
            100,
            0,
            (1, 1),
            castle_pad=(0, 0, 8, 12),
            castle_blend=(1, 0, 40, 8),
            plazas=((20, 0, 4, 3),),
        )
        for point in ((20, 0), (17, 0), (20, 3)):
            self.assertEqual(terrain_height(spec, *point), 3)
        self.assertEqual(terrain_height(spec, 0, 0), 12)

    def test_stroke_has_continuous_sides_and_round_caps(self):
        road = SimpleNamespace(
            points=((0, 0, 0), (4, 0, 0), (8, 0, 0)), width=2
        )
        (polygon,) = road_footprints(road)
        for point in ((-0.5, 0), (8.5, 0), (2, 0.9), (6, -0.9)):
            self.assertTrue(inside_polygon(point, polygon))
        self.assertFalse(inside_polygon((4, 1.5), polygon))

    def test_sliver_grade_is_fixed_with_a_small_height_correction(self):
        vertices = [(0, 0, 0), (1, 0, 0.15), (0.5, 0.001, 0.076)]
        change = limit_road_slopes(vertices, [(0, 1, 2)], [3], 0.35)
        a, b, c = vertices
        gx = b[2] - a[2]
        gy = (c[2] - a[2] - gx * 0.5) / 0.001
        self.assertLessEqual(math.hypot(gx, gy), 0.35)
        self.assertLess(change, 0.001)
        self.assertAlmostEqual(sum(p[2] for p in vertices), 0.226)

    def test_unpaved_cliffs_are_preserved(self):
        vertices = [(0, 0, 0), (1, 0, 10), (0, 1, 0)]
        before = vertices.copy()
        self.assertEqual(
            limit_road_slopes(vertices, [(0, 1, 2)], [0], 0.35), 0
        )
        self.assertEqual(vertices, before)

    def test_edge_projection_preserves_fixed_doorsteps(self):
        vertices = [(0, 0, 0), (1, 0, 4), (2, 0, -2), (3, 0, 0.3)]
        edges = [(0, 1), (1, 2), (2, 3)]
        limit_road_slopes(
            vertices,
            [],
            [],
            0.35,
            fixed=(0, 3),
            centre_edges=edges,
        )
        self.assertEqual(vertices[0][2], 0)
        self.assertAlmostEqual(vertices[3][2], 0.3)
        for a, b in edges:
            self.assertLessEqual(
                abs(vertices[b][2] - vertices[a][2]), 0.200001
            )

    def test_impossible_fixed_levels_are_rejected(self):
        with self.assertRaises(ValueError):
            limit_road_slopes(
                [(0, 0, 0), (1, 0, 1)],
                [],
                [],
                0.35,
                fixed=(0, 1),
                centre_edges=((0, 1),),
            )

    def test_nearby_parallel_roads_share_a_feasible_height_field(self):
        roads = [
            Road("a", "PRIMARY", 5, ((0, 0, 0), (10, 0, 0))),
            Road("b", "PRIMARY", 5, ((0, 1, 2), (10, 1, 2))),
        ]
        spec = TerrainSpec(42, 100, 0, (1, 1))
        a, b = conform_junctions(roads, spec, 0.2)
        for p, q in zip(a.points, b.points, strict=True):
            self.assertLessEqual(abs(p[2] - q[2]), 0.300001)


if __name__ == "__main__":
    unittest.main()
