"""Check the actual shared ground, roads and OGRE asset package."""

import json
import math
import sys
import tempfile
from collections import Counter
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import settlement_blender as builder
from game_asset_format import decode_mesh, read_collision
from ogre_export import export_settlement
from settlement_rules import SettlementConfig
from terrain_rules import boundary_distance, terrain_outline

collection, root, plan = builder.build_settlement(
    SettlementConfig(
        scale="CITY", radius=85, max_buildings=8, trees=False, terrain_step=3
    )
)
surface = next(o for o in collection.objects if o.get("roads_integrated"))
assert root.get("grass_tufts", 0) > 0
assert {"WELL", "FOUNTAIN", "STREET_LAMP", "STATUE_ANCHOR"} <= {
    a.kind for a in plan.civic_assets
}
assert all(
    not o.get("collision_enabled", True)
    for o in collection.objects
    if o.get("settlement_part") in ("grass", "civic_effect")
)
mesh = surface.data
assert not mesh.validate()
assert mesh.color_attributes.get("Color") and mesh.uv_layers.get("UVMap")
areas = Counter()
for p in mesh.polygons:
    assert p.area > 1e-9
    if mesh.attributes["surface_kind"].data[p.index].value:
        grade = math.hypot(p.normal.x, p.normal.y) / p.normal.z
        assert grade < mesh["max_surface_road_grade"] + 0.002, grade
    areas[mesh.attributes["surface_kind"].data[p.index].value] += p.area * abs(
        p.normal.z
    )
assert areas[0] / sum(areas.values()) > 0.5, areas
assert sum(v for k, v in areas.items() if k) / sum(areas.values()) > 0.01
edge_counts = Counter()
for p in mesh.polygons:
    ids = tuple(p.vertices)
    for a, b in zip(ids, ids[1:] + ids[:1], strict=True):
        edge_counts[tuple(sorted((a, b)))] += 1
outer = terrain_outline(plan)
for (a, b), count in edge_counts.items():
    assert count in (1, 2)
    if count == 1:
        point = (mesh.vertices[a].co + mesh.vertices[b].co) / 2
        distance = min(
            boundary_distance(point[:2], outer),
            boundary_distance(point[:2], plan.castle.outline),
        )
        assert distance < 0.002, (
            "Unexpected surface crack",
            distance,
            tuple(point),
        )
vertices, faces = [], []
for obj in collection.objects:
    if obj.type != "MESH" or obj.get("settlement_part") not in (
        "terrain",
        "castle_floor",
    ):
        continue
    first = len(vertices)
    vertices.extend(tuple(v.co) for v in obj.data.vertices)
    faces.extend(
        tuple(first + i for i in p.vertices) for p in obj.data.polygons
    )
bvh = BVHTree.FromPolygons(vertices, faces, all_triangles=False)
worst = 0
for road in plan.roads:
    for a, b in zip(road.points, road.points[1:], strict=False):
        for t in (0, 0.5):
            p = Vector(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))
            hit, _, _, _ = bvh.ray_cast(
                p + Vector((0, 0, 0.3)), Vector((0, 0, -1)), 1.0
            )
            assert hit is not None, ("Road lacks ground", road.id, tuple(p))
            worst = max(worst, abs(hit.z - p.z))
assert worst < 0.035, ("Road/ground height mismatch", worst)
instance = next(o for o in collection.objects if o.instance_collection)
interior, _ = builder.materialize_building(instance, root, collection)
floor = next(o for o in interior.objects if o.get("house_part") == "floor")
upper = next(
    o
    for o in collection.objects
    if o.get("settlement_part") == "castle_floor"
    and o.get("castle_level") == "core_2"
)
builder.show_level(collection, root, "core_0")
assert upper.hide_get()
visibility = {o: (o.hide_get(), o.hide_render) for o in collection.all_objects}
root.location = (6, -4, 1.5)
root.rotation_euler.z = 0.4
bpy.context.view_layer.update()
before = (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials))
with tempfile.TemporaryDirectory() as directory:
    result = export_settlement(collection, root, directory)
    assert any(
        m["placeholder"] and m["kind"] == "STATUE_ANCHOR"
        for m in result["markers"]
    )
    assert result["lights"]
    assert (
        result["collision"]["triangles"]
        < result["statistics"]["scene_triangles"]
    )
    assert any(any(info["emissive"]) for info in result["materials"].values())
    grass_materials = {
        name
        for name, info in result["materials"].items()
        if info.get("foliage_bend_uv") == "V"
    }
    assert grass_materials
    scripts = (Path(directory) / "settlement.material").read_text()
    assert scripts.count("cull_hardware none") == len(grass_materials)
    assert (Path(directory) / "asset_markers.tsv").exists()
    assert (Path(directory) / "street_lights.tsv").exists()
    assert any(n["source"] == floor.name for n in result["nodes"])
    assert any(n["source"] == upper.name for n in result["nodes"])
    assert visibility == {
        o: (o.hide_get(), o.hide_render) for o in collection.all_objects
    }
    navigation = json.loads((Path(directory) / "navigation.json").read_text())
    point = root.matrix_world @ Vector(plan.navigation["nodes"][0]["position"])
    expected = (point.x, point.z, -point.y)
    assert math.dist(expected, navigation["nodes"][0]["position"]) < 0.0001
    assert (
        result["statistics"]["instances"]
        > result["statistics"]["unique_meshes"]
    )
    grass_weights = set()
    for name in result["meshes"]:
        sections = decode_mesh(
            (Path(directory) / (name + ".ogregeom")).read_bytes()
        )
        assert all(s.material in result["materials"] for s in sections)
        for section in sections:
            for v in section.vertices:
                assert abs(math.sqrt(sum(n * n for n in v[3:6])) - 1) < 0.002
                if section.material in grass_materials:
                    assert 0 <= v[7] <= 1
                    grass_weights.add(v[7])
    assert {0, 1} <= grass_weights
    assert len(grass_weights) > 2
    positions, indices = read_collision(
        Path(directory) / "static.collision.bin"
    )
    assert len(indices) // 3 == result["collision"]["triangles"]
    assert all(math.isfinite(p) for p in positions)
    assert (Path(directory) / "ProceduralAssets.hpp").exists()
    assert list((Path(directory) / "textures").glob("*.png"))
    again = export_settlement(collection, root, directory)
    assert again["statistics"] == result["statistics"]
assert before == (
    len(bpy.data.objects),
    len(bpy.data.meshes),
    len(bpy.data.materials),
)
print(
    "PASS shared road/ground vertices, no cracks, "
    "road heights and OGRE buffers"
)
