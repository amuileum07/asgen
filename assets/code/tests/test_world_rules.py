"""Check geographic controls, dry town sites and landmark navigation."""

import json
import math
import sys
import unittest
from collections import defaultdict
from dataclasses import replace
from itertools import combinations, pairwise
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE))

from world_rules import WorldConfig, make_world, world_navigation  # noqa: E402
from world_terrain import Region  # noqa: E402


class WorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = WorldConfig.from_dict(
            json.loads((CODE / "presets" / "world_example.json").read_text())
        )
        cls.plan = make_world(cls.config)

    def test_region_caps_and_water_levels(self):
        terrain = self.plan.terrain
        for region in self.config.regions:
            if region.max_elevation is None:
                continue
            for x in range(-750, 775, 25):
                for y in range(-575, 600, 25):
                    if region.distance(x, y) <= 1:
                        self.assertLessEqual(
                            terrain.height(x, y), region.max_elevation + 1e-7
                        )
        summit = self.config.regions[0]
        isolated = make_world(WorldConfig(regions=(summit,)))
        self.assertAlmostEqual(isolated.terrain.height(*summit.centre), 224.0)
        lake = self.config.lakes[0]
        self.assertAlmostEqual(
            terrain.height(*lake.centre), lake.level - lake.depth
        )
        river = terrain.rivers[self.config.rivers[0].id]
        self.assertTrue(all(a[2] >= b[2] for a, b in pairwise(river.path)))
        self.assertTrue(terrain.wet(*river.path[34][:2]))
        self.assertTrue(terrain.wet(-760, 50))
        _, outlet_level = terrain.water_distance(
            river.river.id, *river.path[-1][:2]
        )
        self.assertAlmostEqual(outlet_level, self.config.coast.level)

    def test_frontier_selects_dry_distinct_profiles(self):
        self.assertEqual(
            [s.landmark.kind for s in self.plan.sites],
            ["QUAY", "LOOKOUT", "LANDING", "BRIDGE"],
        )
        for site in self.plan.sites:
            district = site.settlement
            x, y = site.centre
            self.assertTrue(district.buildings)
            self.assertFalse(self.plan.terrain.wet(*site.landmark.start))
            self.assertEqual(district.site_style, site.profile)
            self.assertEqual(
                len(district.surface_boundary),
                len(self.plan.grid.ring(site.bounding_cells)),
            )
            for house in district.buildings:
                self.assertTrue(
                    all(
                        not self.plan.terrain.wet(x + a, y + b)
                        for a, b in house.corners
                    )
                )
        for first, second in combinations(self.plan.sites, 2):
            ax, ay, bx, by = first.bounding_cells
            cx, cy, dx, dy = second.bounding_cells
            self.assertTrue(bx < cx or dx < ax or by < cy or dy < ay)
        port, mountain, lake, river = self.plan.sites
        self.assertTrue(self.plan.terrain.wet(*port.landmark.end))
        self.assertTrue(self.plan.terrain.wet(*lake.landmark.end))
        self.assertFalse(self.plan.terrain.wet(*river.landmark.end))
        mid = tuple(
            (a + b) / 2
            for a, b in zip(
                river.landmark.start, river.landmark.end, strict=True
            )
        )
        self.assertTrue(self.plan.terrain.wet(*mid))
        self.assertTrue(
            any(
                t.config.wall_style == "BRICK"
                for t in mountain.settlement.templates
            )
        )
        self.assertIn(
            "WAREHOUSE", {b.business for b in port.settlement.buildings}
        )
        self.assertIn(
            "BOATHOUSE", {b.business for b in lake.settlement.buildings}
        )

    def test_each_landmark_is_reachable_from_its_streets(self):
        nav = world_navigation(self.plan.sites)
        adjacency = defaultdict(set)
        for edge in nav["edges"]:
            adjacency[edge["a"]].add(edge["b"])
            adjacency[edge["b"]].add(edge["a"])
        for site, spawn in zip(
            self.plan.sites, nav["suggested_spawns"], strict=True
        ):
            visited, queue = {spawn}, [spawn]
            while queue:
                for other in adjacency[queue.pop()] - visited:
                    visited.add(other)
                    queue.append(other)
            self.assertEqual(
                visited,
                {n["id"] for n in nav["nodes"] if n["site"] == site.id},
            )
            self.assertTrue(
                any(
                    poi["kind"] == site.landmark.kind
                    and poi["node"] in visited
                    for poi in nav["points_of_interest"]
                )
            )
            for a, b in pairwise(site.deck_path):
                self.assertLessEqual(
                    abs(a[2] - b[2]) / math.dist(a[:2], b[:2]), 0.21
                )

    def test_plan_is_reproducible_and_serializable(self):
        duplicate = make_world(self.config)
        self.assertEqual(self.plan.as_dict(), duplicate.as_dict())
        json.dumps(self.plan.as_dict())
        alternate = make_world(replace(self.config, seed=19, settlements=()))
        self.assertNotEqual(
            alternate.terrain.height(45, 32), self.plan.terrain.height(45, 32)
        )

    def test_invalid_scale_and_impossible_landmark_report_context(self):
        with self.assertRaisesRegex(ValueError, "terrain_step"):
            replace(self.config, terrain_step=20).validate()
        with self.assertRaisesRegex(ValueError, "west_port"):
            make_world(
                replace(
                    self.config,
                    coast=None,
                    settlements=self.config.settlements[:1],
                )
            )
        with self.assertRaisesRegex(ValueError, "max_elevation"):
            Region("VALLEY", (0, 0), (30, 70))

    def test_monumental_realistic_world_preset_builds_cleanly(self):
        preset = CODE / "presets" / "world_monumental_realistic.json"
        cfg = WorldConfig.from_dict(json.loads(preset.read_text()))
        plan = make_world(cfg)
        self.assertEqual(len(plan.sites), 4)
        self.assertTrue(plan.config.caves)
        self.assertTrue(any(r.kind == "STREAM" for r in plan.config.rivers))
        self.assertTrue(any(lk.kind == "POND" for lk in plan.config.lakes))
        self.assertTrue(
            any(reg.kind == "PLATEAU" for reg in plan.config.regions)
        )
        self.assertTrue(
            any(reg.kind == "FOREST" for reg in plan.config.regions)
        )
        capital = next(s for s in plan.sites if s.id == "citadel_ford")
        self.assertEqual(capital.settlement.config.scale, "CAPITAL")
        self.assertTrue(capital.settlement.castle.architecture.imperial)
        for site in plan.sites:
            self.assertTrue(site.settlement.buildings)
            if site.settlement.markets:
                self.assertTrue(
                    any(
                        a.kind == "BELL_TOWER"
                        for a in site.settlement.civic_assets
                    ),
                    site.id,
                )


if __name__ == "__main__":
    unittest.main()
