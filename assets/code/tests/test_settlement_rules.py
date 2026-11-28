"""Check city morphology, parcels, terrain and player routes."""

import json
import math
import sys
import unittest
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from settlement_generator import layout_svg
from settlement_rules import PROFILES, SettlementConfig, make_settlement
from terrain_rules import (
    TerrainSampler,
    inside_polygon,
    polygons_overlap,
    terrain_height,
)


class SettlementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plans = {
            scale: make_settlement(SettlementConfig(scale=scale))
            for scale in PROFILES
        }

    def test_seed_is_reproducible(self):
        config = SettlementConfig(scale="TOWN")
        self.assertEqual(self.plans["TOWN"], make_settlement(config))
        self.assertNotEqual(
            self.plans["TOWN"].boundary,
            make_settlement(replace(config, seed=43)).boundary,
        )

    def test_scales_change_structure_not_just_building_counts(self):
        plans = list(self.plans.values())
        self.assertEqual([len(p.markets) for p in plans], [1, 1, 2, 3])
        self.assertEqual(
            [p.has_walls for p in plans], [False, True, True, True]
        )
        self.assertEqual(
            [p.castle is not None for p in plans], [False, False, True, True]
        )
        self.assertEqual([len(p.gates) for p in plans], [2, 3, 4, 5])
        self.assertEqual(
            sorted(len(p.buildings) for p in plans),
            [len(p.buildings) for p in plans],
        )
        self.assertGreater(
            len(plans[-1].buildings), len(plans[0].buildings) * 10
        )

    def test_irregular_boundary_and_parcels_stay_inside(self):
        for plan in self.plans.values():
            radii = [math.hypot(*point) for point in plan.boundary]
            self.assertGreater(max(radii) / min(radii), 1.12)
            for building in plan.buildings:
                self.assertTrue(
                    all(
                        inside_polygon(point, plan.boundary)
                        for point in building.corners
                    )
                )

    def test_all_entry_gates_castles_and_markets_are_connected(self):
        for plan in self.plans.values():
            nav = plan.navigation
            adjacent = defaultdict(set)
            for edge in nav["edges"]:
                adjacent[edge["a"]].add(edge["b"])
                adjacent[edge["b"]].add(edge["a"])
            visited, queue = {nav["spawn_node"]}, [nav["spawn_node"]]
            while queue:
                for neighbour in adjacent[queue.pop()] - visited:
                    visited.add(neighbour)
                    queue.append(neighbour)
            self.assertEqual(len(visited), len(nav["nodes"]))
            self.assertTrue(
                all(
                    poi["node"] in visited for poi in nav["points_of_interest"]
                )
            )

    def test_parcels_and_access_paths_do_not_overlap_houses(self):
        plan = self.plans["TOWN"]
        for index, building in enumerate(plan.buildings):
            for other in plan.buildings[index + 1 :]:
                self.assertFalse(
                    polygons_overlap(building.corners, other.corners)
                )
            road = next(
                r for r in plan.roads if r.id == building.id + "_access"
            )
            self.assertEqual(road.points[-1], building.entry)
            for other in plan.buildings:
                if other.id != building.id:
                    self.assertFalse(
                        inside_polygon(road.points[-1][:2], other.corners)
                    )

    def test_road_grades_and_widths_are_walkable(self):
        for plan in self.plans.values():
            for road in plan.roads:
                self.assertGreater(
                    road.width, plan.navigation["agent_radius"] * 2
                )
                for a, b in zip(road.points, road.points[1:], strict=False):
                    distance = math.dist(a[:2], b[:2])
                    self.assertGreater(distance, 1e-6)
                    self.assertLessEqual(
                        abs(a[2] - b[2]) / distance,
                        plan.config.max_road_grade + 1e-5,
                        (plan.config.scale, road.id),
                    )

    def test_commercial_clusters_and_alley_shops(self):
        plan = self.plans["CAPITAL"]
        core = [b for b in plan.buildings if b.zone == "COMMERCIAL"]
        homes = [b for b in plan.buildings if b.zone == "RESIDENTIAL"]
        self.assertGreater(len(core), 8)
        self.assertGreater(len(homes), 8)
        core_rate = sum(b.business != "RESIDENCE" for b in core) / len(core)
        home_rate = sum(b.business != "RESIDENCE" for b in homes) / len(homes)
        self.assertGreater(core_rate, home_rate + 0.20)
        alleys = {road.id for road in plan.roads if road.kind == "ALLEY"}
        self.assertTrue(
            any(
                b.street_id in alleys and b.business != "RESIDENCE"
                for b in plan.buildings
            )
        )

    def test_terrain_matches_flat_foundation_pads(self):
        plan = self.plans["TOWN"]
        sampler = TerrainSampler(plan)
        for building in plan.buildings:
            self.assertAlmostEqual(
                sampler.height(*building.position[:2]), building.position[2]
            )
        self.assertTrue(
            all(
                math.isfinite(terrain_height(plan.terrain, x, y))
                for x, y in plan.boundary
            )
        )

    def test_castle_has_gate_courtyard_and_matching_keep_entry(self):
        for scale in ("CITY", "CAPITAL"):
            plan = self.plans[scale]
            castle = plan.castle
            self.assertTrue(inside_polygon(castle.centre[:2], plan.boundary))
            self.assertTrue(
                inside_polygon(castle.keep_entry[:2], castle.outline)
            )
            self.assertGreater(castle.gate.width, 3.6)
            self.assertTrue(
                any(b.id == "donjon" for b in castle.architecture.blocks)
            )
            self.assertTrue(
                any(
                    poi["kind"] == "CASTLE_GATE"
                    for poi in plan.navigation["points_of_interest"]
                )
            )

    def test_forced_switches_and_invalid_parameters(self):
        plan = make_settlement(
            SettlementConfig(
                scale="TOWN", walls="OFF", castle="ON", max_buildings=8
            )
        )
        self.assertFalse(plan.has_walls)
        self.assertIsNotNone(plan.castle)
        for values in (
            {"scale": "UNKNOWN"},
            {"density": float("nan")},
            {"seed": True},
            {"radius": 10},
            {"max_buildings": -1},
            {"castle_site": "UNKNOWN"},
            {"season": "MONSOON"},
        ):
            with self.assertRaises(ValueError):
                make_settlement(SettlementConfig(**values))

    def test_export_is_json_and_svg_serializable(self):
        plan = self.plans["VILLAGE"]
        data = json.loads(json.dumps(plan.as_dict()))
        self.assertEqual(data["coordinate_space"], "settlement_local")
        self.assertTrue(data["navigation"]["points_of_interest"])
        self.assertIn("<svg", layout_svg(plan))


if __name__ == "__main__":
    unittest.main()
