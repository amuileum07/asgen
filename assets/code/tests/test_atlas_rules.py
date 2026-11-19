"""Check custom blueprints, runoff, routes and building reservations."""

import json
import math
import sys
import unittest
from collections import defaultdict
from itertools import pairwise
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE))

from atlas_places import dry_footprint, furnish_atlas, overlaps  # noqa: E402
from atlas_rules import Atlas, plan_atlas, site_gate  # noqa: E402

BLUEPRINT = json.loads((CODE / "presets/atlas_example.json").read_text())


class AtlasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.atlas, cls.plan = plan_atlas(BLUEPRINT)
        furnish_atlas(cls.atlas, cls.plan)

    def test_example_blueprint_and_mixed_climate(self):
        world = self.plan
        self.assertEqual(world["size_m"], (4096, 4096))
        self.assertEqual(len(world["tiles"]), 256)
        self.assertEqual(world["report"]["capitals"], 2)
        self.assertEqual(world["report"]["settlements"], 5)
        self.assertEqual(len(world["themes"]), 2)
        self.assertEqual(world["report"]["dungeons"], 2)
        climate = [t["climate"] for t in world["tiles"]]
        self.assertEqual(len({c["biome"] for c in climate}), 4)
        for c in climate:
            self.assertAlmostEqual(sum(w for _, w in c["weights"]), 1)
            self.assertEqual(len(c["monthly_c"]), 12)
            self.assertEqual(len(c["snow_mm"]), 12)
        copy, duplicate = plan_atlas(BLUEPRINT)
        furnish_atlas(copy, duplicate)
        self.assertEqual(world, duplicate)

    def test_all_season_routes_are_connected_and_graded(self):
        sites = {s["id"]: s for s in self.plan["sites"]}
        graph = defaultdict(set)
        for route in self.plan["routes"]:
            a, b = route["from"], route["to"]
            graph[a].add(b)
            graph[b].add(a)
            self.assertEqual(route["points"][0], sites[a]["centre"])
            self.assertEqual(route["points"][-1], sites[b]["centre"])
            self.assertEqual(route["points"][1], site_gate(sites[a]))
            self.assertEqual(route["points"][-2], site_gate(sites[b]))
            for p, q in pairwise(route["points"]):
                self.assertLessEqual(
                    abs(p[2] - q[2]), 0.18001 * math.dist(p[:2], q[:2])
                )
        seen = set()
        frontier = ["central_capital"]
        while frontier:
            node = frontier.pop()
            if node not in seen:
                seen.add(node)
                frontier.extend(graph[node] - seen)
        self.assertEqual(set(sites), seen)
        self.assertEqual(
            {r["condition"] for r in self.plan["seasonal_links"]},
            {"FERRY"},
        )

    def test_reserved_buildings_fit_and_seals_stay_under_ground(self):
        for site in self.plan["sites"]:
            places = site["places"]
            self.assertTrue(any(p["kind"] == "HOUSE" for p in places))
            for index, place in enumerate(places):
                self.assertTrue(
                    dry_footprint(self.atlas, place["bounds"]), place["id"]
                )
                self.assertFalse(
                    overlaps(place["bounds"], site["plaza"]["bounds"])
                )
                for other in places[:index]:
                    self.assertFalse(
                        overlaps(place["bounds"], other["bounds"])
                    )
        for d in self.plan["dungeons"]:
            self.assertLess(d["cellar_z"], d["entrance"][2] - 4)
            x, y, z = d["entrance"]
            self.assertFalse(self.atlas.water_at(x, y))
            self.assertEqual(d["trail"][-1], (x, y, z))
            self.assertAlmostEqual(d["shaft"][3], y)

    def test_drainage_is_acyclic(self):
        rows = {t["id"]: t["drainage"] for t in self.plan["tiles"]}
        done = set()
        for name in rows:
            path = set()
            while name is not None and name not in done:
                self.assertNotIn(name, path)
                path.add(name)
                self.assertEqual(len(rows[name]["discharge_m3s"]), 12)
                name = rows[name]["downstream"]
            done.update(path)

    def test_minimal_landlocked_custom_map(self):
        minimal = {
            "blueprint_version": 2,
            "title": "Minimal Valley",
            "seed": 7,
            "size_m": [2048, 2048],
            "terrain": {
                "base_elevation_m": 30,
                "peaks": [
                    {
                        "centre_uv": [0.8, 0.8],
                        "radii_uv": [0.18, 0.18],
                        "height_m": 160,
                    }
                ],
            },
            "regions": [
                {
                    "id": "meadow",
                    "biome": "PLAIN",
                    "centre_uv": [0.5, 0.5],
                    "radii_m": [1200, 1200],
                }
            ],
            "realms": [
                {
                    "id": "valley_realm",
                    "biome": "PLAIN",
                    "centre_uv": [0.5, 0.5],
                }
            ],
            "sites": [
                {
                    "id": "north_town",
                    "realm_id": "valley_realm",
                    "rank": "CITY",
                    "near_uv": [0.35, 0.65],
                },
                {
                    "id": "south_village",
                    "realm_id": "valley_realm",
                    "rank": "VILLAGE",
                    "near_uv": [0.65, 0.35],
                },
            ],
        }
        atlas, plan = plan_atlas(minimal)
        furnish_atlas(atlas, plan)
        self.assertEqual(plan["size_m"], (2048, 2048))
        self.assertEqual(plan["report"]["settlements"], 2)
        self.assertEqual(plan["report"]["dungeons"], 0)
        self.assertEqual(len(plan["routes"]), 1)
        self.assertTrue(all(t["fog"] == 0.0 for t in plan["tiles"]))

    def test_extends_override_caps_and_invalid_outlet(self):
        derived = {
            "blueprint_version": 2,
            "extends": "atlas_example.json",
            "region_overrides": [
                {
                    "id": "east_highlands",
                    "max_elevation_m": 180,
                }
            ],
        }
        a = Atlas(derived)
        x, y = a.xy((0.80, 0.62))
        self.assertLessEqual(a.terrain(x, y), 180)
        wrong = {
            **BLUEPRINT,
            "feature_overrides": [
                {
                    "id": "high_lake",
                    "outlet_id": "absent",
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "outlet"):
            Atlas(wrong)
