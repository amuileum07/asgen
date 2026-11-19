"""Check furniture, circulation, partitions and floor connections."""

import json
import math
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from house_rules import HouseConfig, make_plan
from interior_rules import (
    DEFAULT_CATALOG,
    PARTITION_THICKNESS,
    SLAB_THICKNESS,
    FurnitureSpec,
    Rect,
    floor_z,
    load_catalog,
    make_interior_plan,
    reachable,
)


class InteriorTests(unittest.TestCase):
    def test_default_house_has_complete_requested_furniture(self):
        config = HouseConfig()
        layout = make_interior_plan(config, make_plan(config))
        self.assertEqual(
            {item.kind for item in layout.furniture}, set(DEFAULT_CATALOG)
        )
        self.assertFalse(layout.unplaced)
        self.assertEqual(len(layout.stairs), config.floors - 1)
        self.assertEqual(
            {room.kind for room in layout.rooms}, {"living", "bedroom", "hall"}
        )

    def test_seed_reproducibility_and_independence(self):
        config = HouseConfig()
        baseline = make_interior_plan(config, make_plan(config))
        self.assertEqual(
            baseline, make_interior_plan(config, make_plan(config))
        )
        cosmetic = replace(config, detail_seed=99, palette="COASTAL")
        self.assertEqual(
            baseline, make_interior_plan(cosmetic, make_plan(cosmetic))
        )
        changed = replace(config, interior_seed=18)
        variant = make_interior_plan(changed, make_plan(changed))
        self.assertEqual(baseline.rooms, variant.rooms)
        self.assertEqual(baseline.stairs, variant.stairs)
        self.assertNotEqual(baseline.furniture, variant.furniture)

    def test_furniture_fit_routes_and_windows_across_seeds(self):
        for seed in range(12):
            config = HouseConfig(
                seed=seed, interior_seed=seed, floors=1 + seed % 3
            )
            house = make_plan(config)
            layout = make_interior_plan(config, house)
            for room in layout.rooms:
                items = [
                    item
                    for item in layout.furniture
                    if item.room_id == room.id
                ]
                self.assertTrue(reachable(room, items, config.walkway_width))
                for index, item in enumerate(items):
                    self.assertTrue(room.bounds.contains(item.footprint))
                    self.assertLessEqual(
                        item.size[2], house.floor_height - SLAB_THICKNESS
                    )
                    self.assertAlmostEqual(
                        item.position[2], floor_z(house, room.floor)
                    )
                    if item.clearance:
                        self.assertTrue(room.bounds.contains(item.clearance))
                    for zone in layout.zones:
                        if zone.floor != room.floor:
                            continue
                        if zone.kind == "window" and item.size[2] <= zone.sill:
                            continue
                        self.assertFalse(
                            item.footprint.overlaps(zone.bounds),
                            (seed, item.id, zone.kind),
                        )
                    for other in items[index + 1 :]:
                        self.assertFalse(
                            item.footprint.overlaps(other.footprint)
                        )
                        if item.clearance:
                            self.assertFalse(
                                item.clearance.overlaps(other.footprint)
                            )

    def test_stairs_match_floor_height_and_fit_reserved_hole(self):
        config = HouseConfig(floors=3)
        house = make_plan(config)
        layout = make_interior_plan(config, house)
        for stair in layout.stairs:
            self.assertEqual(stair.upper_floor, stair.lower_floor + 1)
            self.assertAlmostEqual(
                stair.rise * stair.steps_per_flight * 2, house.floor_height
            )
            self.assertAlmostEqual(
                stair.landing_depth + stair.tread * stair.steps_per_flight,
                stair.bounds.depth,
            )
            self.assertTrue(layout.bounds.contains(stair.bounds))
            self.assertGreater(stair.tread, 0.1)
            self.assertEqual(stair.lower_entry[1], stair.upper_exit[1])
            self.assertNotEqual(stair.lower_entry[0], stair.upper_exit[0])

    def test_partition_door_has_agent_clearance(self):
        config = HouseConfig()
        layout = make_interior_plan(config, make_plan(config))
        for wall in layout.partitions:
            self.assertGreater(wall.door_width, config.walkway_width)
            self.assertGreater(wall.door_y - wall.door_width / 2, wall.y1)
            self.assertLess(wall.door_y + wall.door_width / 2, wall.y2)
        for room in layout.rooms:
            self.assertTrue(
                room.bounds.contains(Rect(*room.entry, *room.entry))
            )
        self.assertGreater(PARTITION_THICKNESS, 0)

    def test_bed_lamp_and_table_chair_relationships(self):
        config = HouseConfig()
        layout = make_interior_plan(config, make_plan(config))
        by_id = {item.id: item for item in layout.furniture}
        for item in layout.furniture:
            if item.kind in ("chair", "lamp"):
                self.assertIn(item.anchor_id, by_id)
                parent = by_id[item.anchor_id]
                self.assertEqual(item.room_id, parent.room_id)
                self.assertEqual(item.floor, parent.floor)
                if item.kind == "lamp":
                    self.assertEqual(parent.kind, "bed")
                    self.assertLess(
                        math.dist(item.position, parent.position), 1.5
                    )
                else:
                    self.assertIn(parent.kind, ("desk", "dining_table"))
                    front = (
                        math.sin(math.radians(item.rotation_z)),
                        -math.cos(math.radians(item.rotation_z)),
                    )
                    delta = (
                        parent.position[0] - item.position[0],
                        parent.position[1] - item.position[1],
                    )
                    self.assertGreater(
                        sum(a * b for a, b in zip(front, delta, strict=True)),
                        0,
                    )

    def test_oversized_furniture_is_reported_without_forced_placement(self):
        catalog = dict(DEFAULT_CATALOG)
        catalog["bed"] = FurnitureSpec("bed", (30, 30, 1))
        config = HouseConfig()
        layout = make_interior_plan(config, make_plan(config), catalog)
        self.assertNotIn("bed", {item.kind for item in layout.furniture})
        self.assertNotIn("lamp", {item.kind for item in layout.furniture})
        self.assertTrue(
            {"bed", "lamp"} <= {item.kind for item in layout.unplaced}
        )

    def test_switches_disable_geometry_or_only_furniture(self):
        config = HouseConfig(interior=False)
        empty = make_interior_plan(config, make_plan(config))
        self.assertFalse(empty.rooms or empty.stairs or empty.furniture)
        config = replace(config, interior=True, furnish=False)
        empty = make_interior_plan(config, make_plan(config))
        self.assertTrue(empty.rooms and empty.stairs)
        self.assertFalse(empty.furniture or empty.unplaced)

    def test_catalog_json_overrides_sizes_and_rejects_bad_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "furniture.json"
            path.write_text(
                json.dumps({"desk": {"size": [1.3, 0.7, 0.8]}}),
                encoding="utf-8",
            )
            self.assertEqual(load_catalog(path)["desk"].size, (1.3, 0.7, 0.8))
            for values in (
                {"unknown": {}},
                {"bed": {"size": [0, 2, 1]}},
                {"lamp": {"size": [True, 1, 1]}},
                {"chair": {"clearance": -1}},
                {"desk": {"surprise": 1}},
            ):
                path.write_text(json.dumps(values), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_catalog(path)

    def test_layout_is_serializable_with_asset_contract(self):
        config = HouseConfig()
        data = json.loads(
            json.dumps(make_interior_plan(config, make_plan(config)).as_dict())
        )
        self.assertEqual(data["asset_origin"], "BOTTOM_CENTER")
        self.assertEqual(data["coordinate_space"], "house_local")
        self.assertEqual(data["asset_front"], "-Y")
        self.assertTrue(data["furniture"])

    def test_partition_and_stairs_clear_openings_across_dimensions(self):
        for floors in (1, 2, 3):
            for width in (4.0, 5.1, 6.4, 8.0, 10.6):
                for depth in (4.0, 5.4):
                    for spacing in (1.7, 2.0, 2.5):
                        for walkway in (0.6, 0.8, 1.0):
                            config = HouseConfig(
                                width=width,
                                depth=depth,
                                floors=floors,
                                window_spacing=spacing,
                                walkway_width=walkway,
                                variation=0.0,
                                furnish=False,
                            )
                            house = make_plan(config)
                            layout = make_interior_plan(config, house)
                            for part in layout.partitions:
                                px1 = part.x - PARTITION_THICKNESS / 2
                                px2 = part.x + PARTITION_THICKNESS / 2
                                for wall in (house.walls[0], house.walls[2]):
                                    for opening in wall.openings:
                                        a = (
                                            wall.start[0]
                                            + wall.tangent[0] * opening.x1
                                        )
                                        b = (
                                            wall.start[0]
                                            + wall.tangent[0] * opening.x2
                                        )
                                        lo, hi = min(a, b), max(a, b)
                                        self.assertFalse(
                                            px2 > lo - 0.075
                                            and px1 < hi + 0.075,
                                            (config, wall.name, part, opening),
                                        )
                                for stair in layout.stairs:
                                    if stair.lower_floor == part.floor:
                                        self.assertLessEqual(
                                            part.door_y + part.door_width / 2,
                                            stair.bounds.y1,
                                        )
                            for stair in layout.stairs:
                                sb = stair.bounds
                                back = house.walls[2]
                                for opening in back.openings:
                                    a = (
                                        back.start[0]
                                        + back.tangent[0] * opening.x1
                                    )
                                    b = (
                                        back.start[0]
                                        + back.tangent[0] * opening.x2
                                    )
                                    lo, hi = min(a, b), max(a, b)
                                    self.assertFalse(
                                        sb.x2 > lo and sb.x1 < hi,
                                        (config, opening),
                                    )


if __name__ == "__main__":
    unittest.main()
