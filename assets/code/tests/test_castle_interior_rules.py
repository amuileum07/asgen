"""Check castle room programs, physical apertures and walking paths."""

import math
import sys
import unittest
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from castle_geometry import (
    edges,
    owner_at,
    planar_regions,
    rectangle,
    subtract_prism,
)
from castle_interior_rules import (
    AGENT_RADIUS,
    make_castle_interior,
    stair_path,
)
from castle_rules import make_castle_architecture
from terrain_rules import (
    inside_polygon,
    oriented_corners,
    polygons_overlap,
    rectangle_distance,
)


def area(polygon):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in edges(polygon))) / 2


class CastleInteriorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.architecture = make_castle_architecture(42, 26)
        cls.plan = make_castle_interior(cls.architecture, 42)

    def test_program_has_living_service_sacred_and_defensive_spaces(self):
        required = {
            "GREAT_HALL",
            "LORD_BEDROOM",
            "KITCHEN",
            "STOREROOM",
            "BARRACKS",
            "CHAPEL",
            "LIBRARY",
            "GUARDROOM",
            "TOWER_LANDING",
        }
        self.assertTrue(required <= {r.kind for r in self.plan.rooms})
        self.assertGreaterEqual(len(self.plan.levels), 8)
        self.assertEqual(
            self.plan, make_castle_interior(self.architecture, 42)
        )

    def test_every_room_and_stair_is_reachable_from_the_gate(self):
        nav = self.plan.navigation
        adjacent = defaultdict(set)
        for edge in nav["edges"]:
            adjacent[edge["a"]].add(edge["b"])
            adjacent[edge["b"]].add(edge["a"])
        visited, queue = {nav["gate_node"]}, [nav["gate_node"]]
        while queue:
            for node in adjacent[queue.pop()] - visited:
                visited.add(node)
                queue.append(node)
        self.assertEqual(len(visited), len(nav["nodes"]))
        self.assertTrue(
            {r.id for r in self.plan.rooms}
            <= {n["name"] for n in nav["nodes"]}
        )

    def test_stair_risers_and_real_upper_floor_holes(self):
        levels = {f.id: f for f in self.plan.levels}
        for stair in self.plan.stairs:
            path = stair_path(stair)
            self.assertLessEqual(
                (stair.top - stair.bottom) / stair.steps, 0.18 + 1e-8
            )
            self.assertGreaterEqual(stair.width, 0.90)
            self.assertTrue(
                all(
                    b[2] >= a[2] - 1e-8
                    for a, b in zip(path, path[1:], strict=False)
                )
            )
            if stair.kind == "U":
                point = (
                    (stair.polygon[0][0] + stair.polygon[2][0]) / 2,
                    (stair.polygon[0][1] + stair.polygon[2][1]) / 2,
                )
            else:
                angle = stair.angle + math.pi
                radius = (stair.inner + stair.outer) / 2
                point = (
                    stair.centre[0] + radius * math.cos(angle),
                    stair.centre[1] + radius * math.sin(angle),
                )
                self.assertGreaterEqual(
                    radius * math.radians(300) / stair.steps, 0.20
                )
            upper = levels[stair.upper]
            self.assertTrue(
                any(inside_polygon(point, h) for h in upper.holes), stair.id
            )
            self.assertFalse(
                any(inside_polygon(point, p) for _, p in upper.regions),
                stair.id,
            )

    def test_furniture_is_inside_its_room_and_does_not_overlap(self):
        rooms = {r.id: r for r in self.plan.rooms}
        levels = {f.id: f for f in self.plan.levels}
        for i, item in enumerate(self.plan.furniture):
            corners = oriented_corners(
                item.position, *item.size[:2], item.heading
            )
            self.assertTrue(
                all(
                    any(
                        inside_polygon(p, r)
                        for r in rooms[item.room_id].regions
                    )
                    for p in corners
                ),
                item.id,
            )
            self.assertEqual(item.position[2], levels[item.level].z)
            for other in self.plan.furniture[i + 1 :]:
                if other.level == item.level:
                    self.assertFalse(
                        polygons_overlap(
                            corners,
                            oriented_corners(
                                other.position, *other.size[:2], other.heading
                            ),
                        ),
                        (item.id, other.id),
                    )
        kinds = {(rooms[i.room_id].kind, i.kind) for i in self.plan.furniture}
        self.assertTrue(
            {
                ("LORD_BEDROOM", "bed"),
                ("GREAT_HALL", "banquet_table"),
                ("KITCHEN", "hearth"),
                ("CHAPEL", "altar"),
            }
            <= kinds
        )

    def test_corridors_keep_clearance_from_furniture(self):
        for edge in self.plan.navigation["edges"]:
            if edge["kind"] != "CORRIDOR":
                continue
            level = self.plan.navigation["nodes"][edge["a"]]["level"]
            for point in edge["path"]:
                for item in self.plan.furniture:
                    if item.level == level:
                        self.assertGreaterEqual(
                            rectangle_distance(
                                point,
                                item.position,
                                *item.size[:2],
                                item.heading,
                            ),
                            AGENT_RADIUS,
                        )

    def test_related_furniture_has_an_anchor_in_the_same_room(self):
        by_id = {item.id: item for item in self.plan.furniture}
        relations = {
            "bench": "banquet_table",
            "lamp": "bed",
            "chair": "desk",
            "pew": "altar",
        }
        linked = [item for item in by_id.values() if item.anchor_id]
        self.assertTrue(linked)
        for item in linked:
            parent = by_id[item.anchor_id]
            self.assertEqual(parent.room_id, item.room_id)
            self.assertEqual(parent.kind, relations[item.kind])

    def test_union_has_no_duplicate_floor_area_and_holes_stay_open(self):
        shapes = (("a", rectangle(0, 0, 4, 4)), ("b", rectangle(2, 2, 6, 6)))
        pieces = planar_regions(shapes, (rectangle(1, 1, 2, 2),))
        self.assertAlmostEqual(sum(area(p) for _, p in pieces), 27)
        for i, (_, p) in enumerate(pieces):
            for _, q in pieces[i + 1 :]:
                self.assertFalse(polygons_overlap(p, q))

    def test_roof_clipping_removes_faces_inside_taller_rooms(self):
        face = ((-2, -2, 1), (2, -2, 1), (2, 2, 1), (-2, 2, 1))
        pieces = subtract_prism(face, rectangle(-1, -1, 1, 1), 0, 2)
        self.assertAlmostEqual(sum(area(p) for p in pieces), 12)

    def test_furniture_switch_preserves_rooms_stairs_and_doors(self):
        plain = make_castle_interior(self.architecture, 42, furnish=False)
        self.assertFalse(plain.furniture)
        self.assertEqual(self.plan.stairs, plain.stairs)
        self.assertEqual(self.plan.levels, plain.levels)

    def test_service_rooms_private_rooms_and_galleries_have_clear_roles(self):
        kinds = {r.kind for r in self.plan.rooms}
        self.assertTrue(
            {
                "PANTRY",
                "VESTRY",
                "SCREEN_PASSAGE",
                "LANDING_GALLERY",
                "LADY_BEDROOM",
            }
            <= kinds
        )
        self.assertEqual(
            {r.zone for r in self.plan.rooms if r.kind == "LORD_BEDROOM"},
            {"PRIVATE"},
        )
        self.assertTrue(
            all(
                r.area > 0
                for r in self.plan.rooms
                if r.level.startswith("core_")
            )
        )

    def test_public_routes_do_not_use_bedrooms_as_shortcuts(self):
        private = {r.id for r in self.plan.rooms if r.privacy == 2}
        levels = {level.id: level for level in self.plan.levels}
        nav = self.plan.navigation
        for e in nav["edges"]:
            if e["kind"] != "CORRIDOR":
                continue
            a, b = nav["nodes"][e["a"]], nav["nodes"][e["b"]]
            if a["name"] in private or b["name"] in private:
                continue
            self.assertFalse(
                any(
                    owner_at(p[:2], levels[a["level"]].shapes) in private
                    for p in e["path"]
                ),
                (a["name"], b["name"]),
            )

    def test_furniture_keeps_an_accessible_use_position(self):
        for item in self.plan.furniture:
            if not item.approach:
                continue
            for other in self.plan.furniture:
                if item.id == other.id or item.level != other.level:
                    continue
                self.assertGreaterEqual(
                    rectangle_distance(
                        item.approach,
                        other.position,
                        *other.size[:2],
                        other.heading,
                    ),
                    AGENT_RADIUS,
                    (item.id, other.id),
                )

    def test_minimum_radius_and_non_overlapping_openings(self):
        min_arch = make_castle_architecture(42, 19.2)
        min_plan = make_castle_interior(min_arch, 42, furnish=False)
        self.assertTrue(min_plan.levels)
        big_arch = make_castle_architecture(42, 34.0)
        big_plan = make_castle_interior(big_arch, 42, furnish=False)
        for level in big_plan.levels:
            for wall in level.walls:
                ordered = sorted(wall.openings, key=lambda o: o.start)
                for a, b in zip(ordered, ordered[1:], strict=False):
                    self.assertLessEqual(a.end, b.start, (level.id, wall.id))


if __name__ == "__main__":
    unittest.main()
