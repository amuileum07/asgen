"""Check geometry contracts without Blender or third-party packages."""

import math
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from house_rules import (
    FOUNDATION_HEIGHT,
    ROOF_STYLES,
    WALL_STYLES,
    HouseConfig,
    clip_polygon,
    make_plan,
    polygon_area,
    rectangle,
    roof_planes,
    subtract_rectangle,
    wall_tiles,
    without_openings,
)


class LayoutTests(unittest.TestCase):
    def test_seed_reproduces_layout(self):
        config = HouseConfig()
        self.assertEqual(make_plan(config), make_plan(config))
        self.assertNotEqual(
            make_plan(config), make_plan(replace(config, seed=43))
        )

    def test_material_choices_do_not_change_structure(self):
        config = HouseConfig()
        self.assertEqual(
            make_plan(config),
            make_plan(
                replace(
                    config,
                    detail_seed=999,
                    wall_style="WOOD_VERTICAL",
                    palette="COASTAL",
                )
            ),
        )

    def test_zero_variation_preserves_exact_dimensions(self):
        for seed in (0, 5, 42):
            plan = make_plan(HouseConfig(seed=seed, variation=0))
            self.assertEqual(
                (plan.width, plan.depth, plan.floor_height, plan.pitch),
                (6.4, 5.4, 2.55, 40),
            )

    def test_windows_and_door_fit_and_do_not_overlap(self):
        for seed in range(40):
            config = HouseConfig(
                seed=seed,
                width=4,
                depth=4,
                variation=0.2,
                floor_height=2.4,
                floors=3,
                window_width=1.5,
                window_height=1.4,
                window_spacing=3.2,
            )
            plan = make_plan(config)
            all_openings = [
                opening for wall in plan.walls for opening in wall.openings
            ]
            self.assertEqual(sum(o.kind == "DOOR" for o in all_openings), 1)
            for wall in plan.walls:
                for index, opening in enumerate(wall.openings):
                    self.assertGreater(opening.x1, 0.1)
                    self.assertLess(opening.x2, wall.length - 0.1)
                    self.assertGreaterEqual(opening.z1, 0)
                    self.assertLess(opening.z2, plan.height)
                    for other in wall.openings[index + 1 :]:
                        overlap = clip_polygon(
                            rectangle(*opening.rectangle),
                            rectangle(*other.rectangle),
                        )
                        self.assertLess(polygon_area(overlap), 1e-7)

    def test_variation_stays_within_requested_range(self):
        config = HouseConfig(variation=0.15)
        for seed in range(50):
            plan = make_plan(replace(config, seed=seed))
            self.assertLessEqual(
                abs(plan.width / config.width - 1), config.variation
            )
            self.assertLessEqual(
                abs(plan.depth / config.depth - 1), config.variation
            )

    def test_invalid_parameters_are_rejected(self):
        for values in (
            {"width": 0},
            {"width": float("nan")},
            {"depth": float("inf")},
            {"seed": -1},
            {"seed": True},
            {"floors": 1.5},
            {"floors": 4},
            {"variation": 1},
            {"wall_style": "unknown"},
            {"roof_tiles": "yes"},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                make_plan(replace(HouseConfig(), **values))


class ClippingTests(unittest.TestCase):
    def test_rectangular_hole_preserves_remaining_area(self):
        pieces = subtract_rectangle(rectangle(0, 0, 8, 5), (2, 1, 4, 3))
        self.assertAlmostEqual(
            sum(polygon_area(piece) for piece in pieces), 36
        )
        for index, piece in enumerate(pieces):
            for other in pieces[index + 1 :]:
                self.assertLess(polygon_area(clip_polygon(piece, other)), 1e-7)

    def test_non_intersecting_hole_does_not_fragment_wall(self):
        polygon = rectangle(0, 0, 8, 5)
        self.assertEqual(subtract_rectangle(polygon, (2, 7, 4, 9)), [polygon])

    def test_wall_area_matches_profile_minus_openings(self):
        for roof in ROOF_STYLES:
            plan = make_plan(HouseConfig(roof_style=roof))
            for wall in plan.walls:
                pieces = without_openings(wall.profile, wall.openings)
                expected = polygon_area(list(wall.profile)) - sum(
                    (o.x2 - o.x1) * (o.z2 - o.z1) for o in wall.openings
                )
                self.assertAlmostEqual(
                    sum(polygon_area(p) for p in pieces), expected
                )

    def test_cladding_fits_roofline_and_leaves_real_openings(self):
        for roof in ROOF_STYLES:
            for style in WALL_STYLES:
                config = HouseConfig(
                    width=4,
                    depth=4.3,
                    floors=1,
                    roof_style=roof,
                    wall_style=style,
                )
                for wall in make_plan(config).walls:
                    tiles = list(wall_tiles(wall, config))
                    self.assertEqual(bool(tiles), style != "PLASTER")
                    for tile in tiles:
                        self.assertAlmostEqual(
                            polygon_area(tile),
                            polygon_area(clip_polygon(tile, wall.profile)),
                        )
                        for hole in wall.openings:
                            self.assertLess(
                                polygon_area(
                                    clip_polygon(
                                        tile, rectangle(*hole.rectangle)
                                    )
                                ),
                                1e-7,
                            )


class RoofTests(unittest.TestCase):
    def test_all_roof_faces_are_planar_and_face_up(self):
        for style in ROOF_STYLES:
            for width, depth in ((6, 5), (5, 6), (5, 5)):
                config = HouseConfig(
                    width=width, depth=depth, variation=0, roof_style=style
                )
                plan = make_plan(config)
                for face in plan.roof_faces:
                    a, b, c = face[:3]
                    u = [b[i] - a[i] for i in range(3)]
                    v = [c[i] - a[i] for i in range(3)]
                    normal = (
                        u[1] * v[2] - u[2] * v[1],
                        u[2] * v[0] - u[0] * v[2],
                        u[0] * v[1] - u[1] * v[0],
                    )
                    self.assertGreater(normal[2], 0)
                    for point in face:
                        self.assertAlmostEqual(
                            sum(
                                normal[i] * (point[i] - a[i]) for i in range(3)
                            ),
                            0,
                        )
                points = [point for face in plan.roof_faces for point in face]
                self.assertAlmostEqual(
                    max(p[0] for p in points), width / 2 + config.overhang
                )
                self.assertAlmostEqual(
                    max(p[1] for p in points), depth / 2 + config.overhang
                )

    def test_shed_roof_meets_the_high_and_low_walls(self):
        plan = make_plan(HouseConfig(roof_style="SHED", variation=0))
        for wall in plan.walls:
            for u, z in wall.profile[2:]:
                x = wall.start[0] + wall.tangent[0] * u
                expected = plan.height + (plan.width / 2 - x) * math.tan(
                    math.radians(plan.pitch)
                )
                self.assertAlmostEqual(z, expected)
        self.assertGreater(
            max(p[2] for p in plan.roof_faces[0]),
            FOUNDATION_HEIGHT + plan.height,
        )

    def test_top_floor_window_frames_clear_roof_planes(self):
        for style in ROOF_STYLES:
            config = HouseConfig(
                floors=2,
                floor_height=2.4,
                roof_style=style,
                roof_pitch=50.0,
                window_height=1.4,
                bevel=0.035,
                variation=0.0,
            )
            plan = make_plan(config)
            planes = roof_planes(plan, 0.128 + config.bevel * 0.8)
            for wall in plan.walls:
                for opening in wall.openings:
                    if opening.kind != "WINDOW":
                        continue
                    z_top = FOUNDATION_HEIGHT + opening.z2 + 0.075
                    for u in (opening.x1 - 0.075, opening.x2 + 0.075):
                        px = (
                            wall.start[0]
                            + wall.tangent[0] * u
                            + wall.normal[0] * 0.155
                        )
                        py = (
                            wall.start[1]
                            + wall.tangent[1] * u
                            + wall.normal[1] * 0.155
                        )
                        for nx, ny, nz, d in planes:
                            self.assertLessEqual(
                                nx * px + ny * py + nz * z_top,
                                d + 1e-5,
                                (style, wall.name, opening),
                            )


if __name__ == "__main__":
    unittest.main()
