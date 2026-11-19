"""Check amenities, safe placement and grass reproducibility."""

import math
import sys
import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from castle_geometry import rectangle
from civic_rules import grass_sites, make_civic_assets
from settlement_rules import Road, SettlementConfig
from terrain_rules import TerrainSpec, segment_projection


def sample_plan(scale="CITY", seed=42):
    plan = SimpleNamespace(
        config=SettlementConfig(scale=scale, seed=seed, grass_density=0.04),
        boundary=rectangle(-60, -45, 60, 45),
        terrain=TerrainSpec(42, 65, 0, (1, 1)),
        buildings=(),
        castle=None,
        gates=(),
        has_walls=True,
        civic_assets=(),
        markets=(
            SimpleNamespace(centre=(-10, 0, 1), radius=11),
            SimpleNamespace(centre=(25, 15, 1), radius=9),
        ),
        roads=(
            Road("main", "PRIMARY", 5, ((-55, 0, 1.12), (55, 0, 1.12))),
            Road(
                "cross", "SECONDARY", 3.6, ((-10, -40, 1.12), (-10, 40, 1.12))
            ),
        ),
    )
    plan.civic_assets = make_civic_assets(plan)
    return plan


class CivicTests(unittest.TestCase):
    def test_city_has_lanterns_fountain_well_and_a_statue_marker(self):
        counts = Counter(a.kind for a in sample_plan().civic_assets)
        self.assertEqual(counts["FOUNTAIN"], 1)
        self.assertEqual(counts["WELL"], 1)
        self.assertEqual(counts["STATUE_ANCHOR"], 1)
        self.assertGreater(counts["STREET_LAMP"], 4)
        small = Counter(a.kind for a in sample_plan("VILLAGE").civic_assets)
        self.assertEqual(small, {"WELL": 1})
        capital = Counter(a.kind for a in sample_plan("CAPITAL").civic_assets)
        self.assertEqual(capital["FOUNTAIN"], 2)

    def test_city_style_is_seeded_and_reproducible(self):
        a, b, c = sample_plan(), sample_plan(), sample_plan(seed=43)
        self.assertEqual(a.civic_assets, b.civic_assets)
        self.assertNotEqual(
            [(v.variant, v.scale, v.parameters) for v in a.civic_assets],
            [(v.variant, v.scale, v.parameters) for v in c.civic_assets],
        )

    def test_props_leave_the_full_road_width_and_each_other_clear(self):
        plan = sample_plan()
        for i, asset in enumerate(plan.civic_assets):
            for road in plan.roads:
                for a, b in zip(road.points, road.points[1:], strict=False):
                    self.assertGreaterEqual(
                        segment_projection(asset.position, a, b)[0],
                        road.width / 2 + asset.radius + 0.5,
                    )
            for other in plan.civic_assets[i + 1 :]:
                self.assertGreaterEqual(
                    math.dist(asset.position[:2], other.position[:2]),
                    asset.radius + other.radius + 0.79,
                )

    def test_grass_stays_off_paths_and_has_repeatable_sites(self):
        plan = sample_plan()
        sites = list(grass_sites(plan))
        self.assertEqual(sites, list(grass_sites(plan)))
        self.assertGreater(len(sites), 10)
        for x, y, _, _ in sites:
            for road in plan.roads:
                self.assertGreaterEqual(
                    segment_projection((x, y), *road.points)[0],
                    road.width / 2 + 0.4,
                )

    def test_verges_fill_with_more_grass_than_open_ground(self):
        plan = sample_plan()
        plan.config = replace(plan.config, grass_density=1.0)
        sites = list(grass_sites(plan))
        verge = sum(
            -47 <= x <= 47 and 3.2 <= abs(y) < 7.2 for x, y, _, _ in sites
        )
        open_ground = sum(
            -47 <= x <= 47 and 11 <= abs(y) < 15 for x, y, _, _ in sites
        )
        self.assertGreater(open_ground, 0)
        self.assertGreater(verge, 2 * open_ground)
        plan.config = replace(plan.config, grass_density=0)
        self.assertEqual(list(grass_sites(plan)), [])
