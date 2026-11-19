"""Check castle apertures and exported paths against the meshes."""

import sys
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import settlement_blender as builder
from castle_rules import castle_point
from settlement_rules import SettlementConfig


def check_castle(config, previous=None):
    collection, root, plan = builder.build_settlement(
        config, replace_collection=previous
    )
    castle = plan.castle
    bpy.context.view_layer.update()
    vertices, faces, face_owners = [], [], []
    for obj in collection.objects:
        if obj.type != "MESH" or obj.hide_render:
            continue
        if not obj.get("settlement_part", "").startswith("castle_"):
            continue
        assert not obj.data.validate(), obj.name
        assert obj.data.uv_layers.get("UVMap"), obj.name
        assert all(p.area > 1e-9 for p in obj.data.polygons), obj.name
        start = len(vertices)
        vertices.extend(obj.matrix_local @ v.co for v in obj.data.vertices)
        faces.extend(
            tuple(start + i for i in p.vertices) for p in obj.data.polygons
        )
        face_owners.extend(obj.name for _ in obj.data.polygons)
    bvh = BVHTree.FromPolygons(vertices, faces, all_triangles=False)

    def world(point, head=0):
        x, y, z = point
        return Vector(
            castle_point(castle.centre, castle.keep_heading, (x, y, z + head))
        )

    # Check paths against walls, roofs, furniture and stair rails.
    for edge in castle.interior.navigation["edges"]:
        for local_a, local_b in zip(
            edge["path"], edge["path"][1:], strict=False
        ):
            for height in (0.5, 1.0, 1.7):
                a, b = world(local_a, height), world(local_b, height)
                direction = b - a
                if direction.length < 1e-6:
                    continue
                hit, normal, index, distance = bvh.ray_cast(
                    a, direction.normalized(), direction.length
                )
                assert hit is None, (
                    config.scale,
                    edge["kind"],
                    edge.get("stairs_id"),
                    face_owners[index],
                    height,
                    local_a,
                    local_b,
                )
    for room in castle.interior.rooms:
        hit, normal, index, distance = bvh.ray_cast(
            world(room.position, 0.9), Vector((0, 0, 1)), 0.8
        )
        assert hit is None, ("Room headroom", room.id, face_owners[index])
    for name in ("core_0", "core_2", "rampart"):
        builder.preview_castle_level(plan, collection, root, name)
        assert root["castle_view"] == name
        assert any(
            not o.hide_render
            and o.get("castle_level") == name
            and o.get("settlement_part") == "castle_floor"
            for o in collection.objects
        )
        assert all(
            o.hide_render
            for o in collection.objects
            if o.get("settlement_part") == "castle_roofs"
        )
    builder.preview_castle(plan, collection, root)
    assert root["castle_view"] == "EXTERIOR"
    assert all(
        o.hide_render
        for o in collection.objects
        if o.get("settlement_part") == "castle_cutaway"
    )
    return collection


previous = None
for config in (
    SettlementConfig(
        scale="CITY", radius=100, max_buildings=4, trees=False, terrain_step=5
    ),
    SettlementConfig(
        scale="TOWN",
        seed=7,
        castle="ON",
        castle_site="WALLED",
        max_buildings=4,
        trees=False,
        terrain_step=5,
    ),
):
    previous = check_castle(config, previous)
print("PASS castle interiors, holes, physical routes, headroom and cutaways")
