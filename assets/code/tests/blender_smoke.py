"""Check Blender integration using a fresh background session.

Run: blender -b --factory-startup --python-exit-code 1 -P this_file.py
"""

import json
import math
import sys
from dataclasses import replace
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import house_generator as generator
from house_rules import (
    ROOF_STYLES,
    WALL_STYLES,
    HouseConfig,
    clip_polygon,
    polygon_area,
    roof_planes,
)
from interior_rules import floor_z


def mesh_signature(collection):
    return [
        (
            obj.name.split(".")[0],
            [tuple(round(c, 6) for c in v.co) for v in obj.data.vertices],
            [tuple(face.vertices) for face in obj.data.polygons],
            [face.material_index for face in obj.data.polygons],
        )
        for obj in collection.objects
        if obj.type == "MESH"
    ]


def check_meshes(collection):
    house = generator._root_for(collection)
    planes = roof_planes(
        generator.make_plan(HouseConfig(**json.loads(house["config_json"]))),
        0.12,
    )
    for obj in collection.objects:
        if obj.type != "MESH":
            continue
        assert obj.data.uv_layers.get("UVMap"), obj.name
        assert not obj.data.validate(), f"Invalid geometry: {obj.name}"
        assert all(
            math.isfinite(v) for vertex in obj.data.vertices for v in vertex.co
        )
        assert all(face.area > 1e-10 for face in obj.data.polygons), obj.name
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        if obj.get("house_geometry_role") in (
            "Walls",
            "Cladding",
            "Timber",
            "WindowsAndDoor",
            "MedievalDetails",
        ):
            assert all(
                nx * v.co.x + ny * v.co.y + nz * v.co.z <= d + 0.0001
                for v in mesh.vertices
                for nx, ny, nz, d in planes
            ), obj.name
        assert len(mesh.polygons) >= len(obj.data.polygons)
        evaluated.to_mesh_clear()


sentinel = bpy.data.objects.new("UserObjectMustSurvive", None)
bpy.context.scene.collection.objects.link(sentinel)
generator.register()
generator.register()  # Text Editor Run Script must be repeatable.
bpy.app.driver_namespace.pop("_cartoon_house_classes")
# Loading a file can clear the driver namespace.
generator.register()
assert hasattr(bpy.types.Scene, generator.SETTINGS_KEY)
material = bpy.data.materials.new("RenamedNodeTest")
material.use_nodes = True
for node in material.node_tree.nodes:
    node.name = "Translated_" + node.name
assert generator._principled_shader(material).type == "BSDF_PRINCIPLED"
bpy.data.materials.remove(material)
config = HouseConfig(width=4.5, depth=4.2, floors=1)
collection, root, plan = generator.build_house(config)
finishes = set()
for material in {
    material
    for obj in collection.objects
    if obj.type == "MESH"
    for material in obj.data.materials
}:
    if surface := material.node_tree.nodes.get("Architecture Surface"):
        shader = generator._principled_shader(material)
        assert tuple(surface.inputs["Tint"].default_value) == tuple(
            material.diffuse_color
        )
        assert shader.inputs["Base Color"].links[0].from_node == surface
        assert shader.inputs["Normal"].links[0].from_node == surface
        finishes.add(surface.node_tree.name)
assert finishes == {
    "Asgen Plaster Surface",
    "Asgen Timber Surface",
    "Asgen Clay Surface",
    "Asgen Stone Surface",
}
timber = next(
    obj
    for obj in collection.objects
    if obj.get("house_geometry_role") == "Timber"
)
grain_uv = timber.data.uv_layers.active.data
for face in timber.data.polygons:
    verts = [timber.data.vertices[index].co for index in face.vertices]
    u = [grain_uv[index].uv.x for index in face.loop_indices]
    longest = max(
        (b - a).length
        for a, b in zip(verts, verts[1:] + verts[:1], strict=True)
    )
    assert max(u) - min(u) >= longest - 1e-5
first = mesh_signature(collection)
collection, root, plan = generator.build_house(config, replace=collection)
assert mesh_signature(collection) == first, "Same seed changed the mesh"
check_meshes(collection)

# Visible window-frame faces must not overlap in the same plane.
window_batch = generator.MeshBatch(
    "WindowCheck", {"frame": None, "glass": None}
)
wall = plan.walls[0]
window = next(opening for opening in wall.openings if opening.kind == "WINDOW")
generator._build_opening(
    window_batch,
    wall,
    window,
    replace(config, shutters=False, architecture="SIMPLE"),
)
fronts = []
for face, material_index in zip(
    window_batch.faces, window_batch.face_materials, strict=True
):
    points = [Vector(window_batch.vertices[index]) for index in face]
    if material_index == 0 and generator._face_normal(points).y < -0.99:
        fronts.append((points[0].y, [(point.x, point.z) for point in points]))
for index, (plane, polygon) in enumerate(fronts):
    for other_plane, other in fronts[index + 1 :]:
        if abs(plane - other_plane) < 1e-6:
            assert polygon_area(clip_polygon(polygon, other)) < 1e-7

# A user object in the generated collection must survive a regeneration.
user_child = bpy.data.objects.new("UserDecoration", None)
collection.objects.link(user_child)
user_child.parent = root
user_child.location = (2, 1, 0)
root.location = (5, -3, 1)
bpy.context.view_layer.update()
expected_position = user_child.matrix_world.translation.copy()
collection, root, plan = generator.build_house(config, replace=collection)
assert tuple(root.location) == (5, -3, 1), "Regeneration reset house placement"
assert user_child.name in bpy.data.objects, (
    "Regeneration deleted a user object"
)
assert (user_child.matrix_world.translation - expected_position).length < 1e-6
assert sentinel.name in bpy.data.objects


def data_counts():
    return tuple(
        len(data)
        for data in (
            bpy.data.meshes,
            bpy.data.materials,
            bpy.data.objects,
            bpy.data.curves,
            bpy.data.collections,
        )
    )


baseline_counts = data_counts()
for _ in range(3):
    collection, root, plan = generator.build_house(config, replace=collection)
assert baseline_counts == data_counts(), "Regeneration leaked Blender data"

# A failed build must preserve the old house and datablock counts.
old_finish = generator.MeshBatch.finish


def failing_finish(*args):
    old_finish(*args)
    raise RuntimeError("Intentional test failure")


generator.MeshBatch.finish = failing_finish
try:
    generator.build_house(config, replace=collection)
except RuntimeError:
    pass
else:
    raise AssertionError("Failure injection did not run")
finally:
    generator.MeshBatch.finish = old_finish
assert root.name in bpy.data.objects
assert baseline_counts == data_counts()

for roof in ROOF_STYLES:
    for wall in WALL_STYLES:
        candidate = replace(config, wall_style=wall, roof_style=roof)
        collection, root, plan = generator.build_house(
            candidate, replace=collection
        )
        check_meshes(collection)
        print(f"PASS {wall}/{roof}")

try:
    generator.build_house(config, replace=bpy.context.scene.collection)
except ValueError:
    pass
else:
    raise AssertionError("Accepted a user collection as a replacement target")

settings = getattr(bpy.context.scene, generator.SETTINGS_KEY)
settings.target = collection
for name, value in config.as_dict().items():
    setattr(settings, name, value)
assert bpy.ops.cartoon_house.generate() == {"FINISHED"}
assert bpy.ops.cartoon_house.new_variant() == {"FINISHED"}
assert settings.seed == config.seed + 1
assert (
    json.loads(generator._root_for(settings.target)["config_json"])["seed"]
    == settings.seed
)
root = generator._root_for(settings.target)
collection = settings.target
plan = generator.make_plan(HouseConfig(**json.loads(root["config_json"])))
generator.create_preview_stage(plan, root)
stage_counts = (
    len(bpy.data.meshes),
    len(bpy.data.materials),
    len(bpy.data.lights),
    len(bpy.data.cameras),
    len(bpy.data.objects),
    len(bpy.data.worlds),
)
generator.create_preview_stage(plan, root)
assert stage_counts == (
    len(bpy.data.meshes),
    len(bpy.data.materials),
    len(bpy.data.lights),
    len(bpy.data.cameras),
    len(bpy.data.objects),
    len(bpy.data.worlds),
)
assert sentinel.name in bpy.data.objects
for floors in (1, 2, 3):
    candidate = HouseConfig(
        width=8.2,
        depth=6.2,
        floors=floors,
        wall_style="PLASTER",
        roof_tiles=False,
    )
    collection, root, plan = generator.build_house(
        candidate, replace=collection
    )
    layout = generator.make_interior_plan(candidate, plan)
    check_meshes(collection)
    stored = json.loads(root["interior_plan_json"])
    proxies = {
        obj["furniture_id"]: obj
        for obj in collection.objects
        if obj.get("asset_placeholder")
    }
    assert len(stored["furniture"]) == len(proxies)
    for item in layout.furniture:
        proxy = proxies[item.id]
        assert proxy["asset_origin"] == "BOTTOM_CENTER"
        assert proxy["asset_front"] == "-Y"
        assert tuple(proxy["size"]) == item.size
        assert (proxy.location - Vector(item.position)).length < 1e-5
    for stair in layout.stairs:
        slab = next(
            obj
            for obj in collection.objects
            if obj.get("house_part") == "floor"
            and obj["floor_index"] == stair.upper_floor
        )
        z = floor_z(plan, stair.upper_floor)
        origin = Vector((*stair.bounds.centre, z + 0.2))
        assert not slab.ray_cast(origin, Vector((0, 0, -1)))[0], (
            "Blocked stair hole"
        )
        stair_obj = next(
            obj
            for obj in collection.objects
            if obj.get("stairs_id") == stair.id
        )
        assert (
            abs(max(vertex.co.z for vertex in stair_obj.data.vertices) - z)
            < 1e-5
        )
    print(f"PASS interior, furniture and stair holes: {floors} floor(s)")

settings.target = collection
settings.inspect_floor = 2
assert bpy.ops.cartoon_house.interior_view() == {"FINISHED"}
assert root["visible_interior_floor"] == 1
assert all(
    obj.hide_render
    for obj in collection.objects
    if obj.get("house_part") == "exterior"
)
assert all(
    not obj.hide_render
    for obj in collection.objects
    if obj.get("house_part") == "furniture" and obj["floor_index"] == 1
)
collection, root, plan = generator.build_house(candidate, replace=collection)
settings.target = collection
assert root["visible_interior_floor"] == 1, "Regeneration lost cutaway view"
assert bpy.ops.cartoon_house.interior_view(exterior=True) == {"FINISHED"}
assert root["visible_interior_floor"] == -1

baseline_counts = data_counts()
old_label = generator.interior_blender._label


def failing_label(*args):
    old_label(*args)
    raise RuntimeError("Intentional furniture failure")


generator.interior_blender._label = failing_label
try:
    generator.build_house(candidate, replace=collection)
except RuntimeError:
    pass
else:
    raise AssertionError("Furniture failure injection did not run")
finally:
    generator.interior_blender._label = old_label
assert root.name in bpy.data.objects
assert data_counts() == baseline_counts, "Failed furniture build leaked data"

generator.unregister()
print(
    "PASS: Blender mesh, UI, regeneration, ownership, UV "
    "and preview-stage checks"
)
