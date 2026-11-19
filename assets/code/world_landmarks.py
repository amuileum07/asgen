"""Walkable waterfront structures and elevated viewpoints."""

import math
from itertools import pairwise

from mathutils import Vector

from civic_blender import _face
from fortification_blender import cylinder
from house_generator import MeshBatch
from settlement_blender import _finish
from transport_rules import resample


def _deck_strip(batch, a, b, side, width, thickness, material):
    edge = side * (width / 2)
    batch.prism(
        [a - edge, b - edge, b + edge, a + edge],
        (0, 0, -thickness),
        material,
    )


def _railing(batch, path, side, width, spacing=2.6, material="wood"):
    edge = side * (width / 2 - 0.12)
    top = Vector((0, 0, 0.91))
    for a, b in pairwise(path):
        batch.beam(a + edge + top, b + edge + top, 0.13, material)
    for p in resample(path, spacing):
        p = Vector(p) + edge
        batch.beam(p, p + top, 0.15, material)


def _supports(batch, points, side, width, height, material):
    for p in points:
        for sign in (-1, 1):
            x, y, z = Vector(p) + side * (sign * (width / 2 - 0.32))
            bottom = min(z - 0.3, height(x, y) - 0.28)
            cylinder(batch, (x, y, bottom), 0.19, z - bottom, material, 8)


def _boat(batch, centre, axis, scale):
    """Build an open hull with a sheer line, keel and seats."""
    along = Vector(axis)
    side = Vector((-along.y, along.x, 0))
    stations = (
        (-2.05, 0.10, 0.38),
        (-1.45, 0.57, 0.22),
        (-0.65, 0.74, 0.16),
        (0.45, 0.77, 0.18),
        (1.36, 0.54, 0.29),
        (2.17, 0.045, 0.52),
    )
    outer, lip, inner, keel = [], [], [], []
    for length, width, rise in stations:
        base = centre + along * length * scale
        top = base + Vector((0, 0, rise * scale))
        outer.append(
            tuple(top + sign * side * (width * scale) for sign in (-1, 1))
        )
        lip.append(
            tuple(
                top + sign * side * (width * 0.82 * scale) for sign in (-1, 1)
            )
        )
        inner.append(
            tuple(
                base
                + sign * side * (width * 0.47 * scale)
                + Vector((0, 0, -0.05 * scale))
                for sign in (-1, 1)
            )
        )
        keel.append(
            tuple(
                base
                + sign * side * (width * 0.42 * scale)
                + Vector((0, 0, -0.26 * scale))
                for sign in (-1, 1)
            )
        )
    for i in range(len(stations) - 1):
        for j in (0, 1):
            for upper, lower, material in (
                (outer, keel, "cloth_blue"),
                (lip, inner, "wood"),
                (outer, lip, "timber"),
            ):
                panel = [
                    upper[i][j],
                    upper[i + 1][j],
                    lower[i + 1][j],
                    lower[i][j],
                ]
                if (j == 0) == (upper is outer and lower is keel):
                    panel.reverse()
                _face(batch, panel, material)
        for layer, material in ((inner, "wood"), (keel, "timber")):
            panel = [
                layer[i][0],
                layer[i + 1][0],
                layer[i + 1][1],
                layer[i][1],
            ]
            _face(batch, panel if layer is inner else panel[::-1], material)
    for i in (0, len(stations) - 1):
        panel = [outer[i][0], outer[i][1], keel[i][1], keel[i][0]]
        _face(batch, panel if i == 0 else panel[::-1], "cloth_blue")
    for pos in (-0.84, 0.38):
        base = centre + along * pos * scale + Vector((0, 0, 0.1 * scale))
        batch.box(
            base,
            (0.25 * scale, 1.25 * scale, 0.08),
            "wood",
            (along, side, (0, 0, 1)),
        )


def build_landmark(site, terrain, height, collection, root, materials):
    feature = site.landmark
    path = tuple(Vector(p) for p in site.deck_path)
    along = path[-1] - path[0]
    along.z = 0
    along.normalize()
    side = Vector((-along.y, along.x, 0))
    width = feature.width
    batch = MeshBatch(site.id + "_" + feature.kind, materials)
    path_ends = (Vector(path[0]), Vector(path[-1]))
    if feature.kind == "LOOKOUT":
        a, b = path_ends
        cap = Vector((0, 0, 0.19))
        _deck_strip(batch, a, b, side, width, cap.z, "stone_light")
        _deck_strip(batch, a - cap, b - cap, side, width - 0.26, 0.37, "stone")
        for t in (0.20, 0.78):
            p = a.lerp(b, t)
            top = p.z - 0.55
            bottom = min(
                top - 0.30,
                *(
                    height(*(p + side * offset)[:2]) - 0.28
                    for offset in (-1.9, 1.9)
                ),
            )
            count = math.ceil((top - bottom) / 0.69)
            dz = (top - bottom) / count
            for i in range(count):
                centre = Vector((p.x, p.y, bottom + (i + 0.5) * dz))
                flare = 1 - i / count
                batch.box(
                    centre,
                    (1.91 + 0.55 * flare, 3.9 + 0.54 * flare, dz),
                    "castle_stone" if i % 3 else "ashlar_dark",
                    (along, side, (0, 0, 1)),
                )
        for normal in (side, -side):
            _railing(batch, path, normal, width, material="timber")
        lip = path[-1] + Vector((0, 0, 0.91))
        batch.beam(
            lip - side * (width / 2 - 0.14),
            lip + side * (width / 2 - 0.14),
            0.13,
            "timber",
        )
    else:
        timber = path
        if feature.kind == "QUAY":
            a = path[0]
            b = a.lerp(path[-1], 7.9 / math.dist(a[:2], path[-1][:2]))
            timber = (b, path[-1])
            trim = Vector((0, 0, 0.17))
            _deck_strip(
                batch,
                a - trim,
                b - trim,
                side,
                19,
                a.z - feature.water_level + 1.2,
                "stone",
            )
            _deck_strip(batch, a, b, side, 19, 0.17, "stone_light")
            for sign in (-1, 1):
                for i in range(3):
                    p = a.lerp(b, (2.8 + 1.05 * i) / 7.9)
                    p += side * ((5.0 + 1.16 * i) * sign)
                    size = 0.76 + (i % 2) * 0.19
                    batch.box(
                        p + Vector((0, 0, size / 2)),
                        (size, size, size),
                        "wood",
                        (along, side, (0, 0, 1)),
                    )
        points = tuple(Vector(p) for p in resample(timber, 0.48))
        for i, (a, b) in enumerate(pairwise(points)):
            _deck_strip(
                batch,
                a,
                b,
                side,
                width,
                0.18,
                "wood" if i % 5 else "stair_wood",
            )
        posts = resample(timber, 5.0 if feature.kind == "QUAY" else 6.0)
        _supports(batch, posts, side, width, height, "timber")
        for a, b in pairwise(timber):
            for offset in (-0.35, 0.35):
                beam = side * (width * offset) - Vector((0, 0, 0.27))
                batch.beam(a + beam, b + beam, 0.30, "timber")
        if feature.kind == "BRIDGE":
            for normal in (side, -side):
                _railing(batch, path, normal, width, material="timber")
            for p, sign in ((path[0], 1), (path[-1], -1)):
                p = p + along * sign * 2.1
                batch.box(
                    p - Vector((0, 0, 0.67)),
                    (3.7, width + 0.5, 1.05),
                    "stone",
                    (along, side, (0, 0, 1)),
                )
        elif feature.kind == "LANDING":
            _railing(batch, path, -side, width, spacing=3.25)
        if feature.kind != "BRIDGE":
            for sign in (-1, 1):
                for fraction in (0.51, 0.92):
                    p = path[0].lerp(path[-1], fraction) + side * (
                        sign * (width / 2 - 0.25)
                    )
                    cylinder(batch, p, 0.115, 0.39, "timber", 8)
            a = path[-1] - along * 3.2 + side * (width / 2 + 1.35)
            distance, level = terrain.water_distance(
                feature.water_id, a.x, a.y
            )
            if distance < -3:
                a.z = level
                boat = MeshBatch(site.id + "_Boat", materials)
                _boat(boat, a, along, 1.2 if feature.kind == "QUAY" else 0.87)
                obj = _finish(boat, collection, root, "moored_boat")
                obj["collision_enabled"] = False
    obj = _finish(batch, collection, root, "world_landmark")
    obj["landmark_kind"] = feature.kind
    obj["site_id"] = site.id
    return obj
