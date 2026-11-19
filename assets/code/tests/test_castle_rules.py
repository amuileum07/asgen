"""Check castle silhouette, enclosure and courtyard access."""

import math
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from castle_rules import castle_point, make_castle_architecture
from settlement_rules import SettlementConfig, make_settlement
from terrain_rules import inside_polygon, oriented_corners, rectangle_distance


class CastleTests(unittest.TestCase):
    def test_seed_reproduces_a_varied_castle(self):
        first = make_castle_architecture(42, 24)
        self.assertEqual(first, make_castle_architecture(42, 24))
        other = make_castle_architecture(43, 24)
        self.assertNotEqual(first.outline, other.outline)
        self.assertNotEqual(first.blocks, other.blocks)

    def test_wings_and_towers_fit_inside_the_curtain(self):
        for seed in (0, 7, 42, 199):
            castle = make_castle_architecture(seed, 24)
            for block in castle.blocks:
                corners = oriented_corners(block.centre, *block.size, 0)
                self.assertTrue(
                    all(inside_polygon(p, castle.outline) for p in corners),
                    block.id,
                )
            for tower in castle.towers:
                for i in range(16):
                    angle = i * math.tau / 16
                    point = (
                        tower.centre[0] + tower.radius * math.cos(angle),
                        tower.centre[1] + tower.radius * math.sin(angle),
                    )
                    self.assertTrue(inside_polygon(point, castle.outline))

    def test_keep_dominates_attached_wings_and_has_corbel_turrets(self):
        castle = make_castle_architecture(42, 24)
        heights = {b.id: b.height + b.roof_height for b in castle.blocks}
        self.assertGreater(heights["donjon"], heights["forewing"] * 1.5)
        self.assertGreater(castle.height, 35)
        self.assertTrue(any(t.base > 10 for t in castle.towers))
        self.assertGreater(max(heights.values()) - min(heights.values()), 12)

    def test_gate_to_main_door_corridor_is_unobstructed(self):
        castle = make_castle_architecture(42, 24)
        gate = (0, castle.outline[0][1])
        for index in range(20):
            t = index / 20
            point = tuple(
                a + (b - a) * t
                for a, b in zip(gate, castle.entry[:2], strict=True)
            )
            for block in castle.blocks:
                if block.id == "palas":
                    continue
                self.assertGreater(
                    rectangle_distance(point, block.centre, *block.size, 0),
                    1.0,
                )
            self.assertTrue(
                all(
                    math.dist(point, tower.centre) > tower.radius + 1
                    for tower in castle.towers
                    if tower.base == 0
                )
            )

    def test_site_changes_elevation_and_preserves_gate_alignment(self):
        config = SettlementConfig(scale="CITY", max_buildings=8, radius=100)
        high = make_settlement(config)
        low = make_settlement(replace(config, castle_site="WALLED"))
        self.assertGreater(high.castle.centre[2], low.castle.centre[2] + 5)
        for plan in (high, low):
            castle = plan.castle
            local_gate = (0, castle.architecture.outline[0][1], 0)
            expected = castle_point(
                castle.centre, castle.keep_heading, local_gate
            )
            self.assertLess(math.dist(expected, castle.gate.position), 1e-6)
            self.assertEqual(
                castle.keep_entry,
                castle_point(
                    castle.centre,
                    castle.keep_heading,
                    castle.architecture.entry,
                ),
            )
            self.assertGreater(castle.gate.width, 4.5)

    def test_invalid_parameters_are_rejected(self):
        for seed, radius in ((True, 24), (-1, 24), (1, 0), (1, float("nan"))):
            with self.assertRaises(ValueError):
                make_castle_architecture(seed, radius)


if __name__ == "__main__":
    unittest.main()
