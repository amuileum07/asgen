"""Check engine buffers, coordinate data and primitive roofs."""

import math
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from castle_roof_rules import RoofSpec, roof_geometry, roof_height_at
from game_asset_format import (
    MeshSection,
    decode_mesh,
    encode_mesh,
    read_collision,
    write_collision,
    write_mesh_xml,
)


class GameFormatTests(unittest.TestCase):
    def test_roof_types_have_a_single_true_apex(self):
        for kind, count in (("PYRAMID_4", 4), ("PYRAMID_8", 8), ("CONE", 40)):
            spec = RoofSpec("test", (2, 3), 5, 4, 4, 3, kind, count)
            vertices, faces = roof_geometry(spec)
            self.assertEqual(len(vertices), count + 1)
            self.assertEqual(len(faces), count + 1)
            self.assertEqual(vertices[-1], (2, 3, 8))
            self.assertTrue(
                all(len(f) == 3 and f[-1] == count for f in faces[1:])
            )
            for vertex in vertices[:-1]:
                self.assertAlmostEqual(
                    roof_height_at(spec, *vertex[:2]), 5, places=6
                )
            self.assertAlmostEqual(roof_height_at(spec, 2, 3), 8)

    def test_engine_buffer_and_xml_round_trip(self):
        section = MeshSection(
            "Proc/stone",
            (
                (0, 0, 0, 0, 1, 0, 0, 0, 1, 1, 1, 1),
                (1, 0, 0, 0, 1, 0, 1, 0, 1, 1, 1, 1),
                (0, 0, -1, 0, 1, 0, 0, 1, 1, 1, 1, 1),
            ),
            (0, 1, 2),
        )
        result = decode_mesh(encode_mesh((section,)))
        self.assertEqual(result, (section,))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mesh.xml"
            write_mesh_xml(path, (section,))
            root = ET.parse(path).getroot()
            sub = root.find("submeshes/submesh")
            self.assertEqual(sub.get("material"), section.material)
            self.assertEqual(sub.find("geometry").get("vertexcount"), "3")
            self.assertEqual(sub.find("faces").get("count"), "1")

    def test_invalid_vertices_indices_and_versions_fail(self):
        with self.assertRaises(ValueError):
            encode_mesh((MeshSection("x", ((math.nan,) * 12,), (0, 0, 0)),))
        with self.assertRaises(ValueError):
            encode_mesh((MeshSection("x", ((0,) * 12,), (0, 1, 2)),))
        with self.assertRaises(ValueError):
            decode_mesh(b"unknown format")

    def test_collision_buffer_is_stable_little_endian_data(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "collision.bin"
            write_collision(
                path, ((1, 2, 3), (4, 5, 6), (7, 8, 9)), ((0, 1, 2),)
            )
            positions, indices = read_collision(path)
            self.assertEqual(list(positions), list(range(1, 10)))
            self.assertEqual(list(indices), [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
