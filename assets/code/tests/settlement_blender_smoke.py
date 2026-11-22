"""Check city meshes, ownership and editable interiors."""

import sys
from dataclasses import replace
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import settlement_blender as builder
import settlement_generator as ui
from settlement_rules import SettlementConfig
from terrain_rules import TerrainSampler


def counts():
    return tuple(
        len(data)
        for data in (
            bpy.data.objects,
            bpy.data.meshes,
            bpy.data.materials,
            bpy.data.collections,
            bpy.data.curves,
            bpy.data.cameras,
            bpy.data.lights,
            bpy.data.images,
        )
    )


def validate(collection):
    for obj in collection.objects:
        if obj.type != "MESH":
            continue
        assert not obj.data.validate(), obj.name
        assert obj.data.uv_layers.get("UVMap"), obj.name
        assert all(face.area > 1e-9 for face in obj.data.polygons), obj.name


sentinel = bpy.data.objects.new("UserObject", None)
bpy.context.scene.collection.objects.link(sentinel)
ui.register()
ui.register()
config = SettlementConfig(
    scale="VILLAGE",
    max_buildings=8,
    terrain_step=5,
    trees=False,
    walls="ON",
    art_style="REALISTIC",
)
collection, root, plan = builder.build_settlement(config)
validate(collection)
assert len(
    [obj for obj in collection.objects if obj.get("building_id")]
) == len(plan.buildings)
initial = counts()
for _ in range(2):
    collection, root, plan = builder.build_settlement(
        config, replace_collection=collection
    )
assert counts() == initial, "City regeneration leaked data"
assert sentinel.name in bpy.data.objects

root.location = (12, -7, 2)
collection, root, plan = builder.build_settlement(
    config, replace_collection=collection
)
assert tuple(root.location) == (12, -7, 2)
builder.preview_stage(plan, collection, root)
initial = counts()
builder.preview_stage(plan, collection, root)
assert counts() == initial, "Overview recreation leaked data"

instance = next(obj for obj in collection.objects if obj.get("building_id"))
position = instance.location.copy()
interior, house_root = builder.materialize_building(instance, root, collection)
assert instance.hide_render
assert house_root.parent == root
assert (house_root.location - position).length < 1e-5
assert house_root.get("interior_plan_json")
assert (
    len([obj for obj in interior.objects if obj.get("house_part") == "floor"])
    >= 1
)
assert '"door_open": true' in house_root["config_json"]
assert '"art_style": "REALISTIC"' in house_root["config_json"]
initial = counts()
again, _ = builder.materialize_building(instance, root, collection)
assert again == interior and counts() == initial
validate(interior)

config = SettlementConfig(
    scale="CITY", radius=85, max_buildings=10, terrain_step=5, trees=True
)
collection, root, plan = builder.build_settlement(
    config, replace_collection=collection
)
assert plan.castle is not None and plan.has_walls
validate(collection)
assert any(obj.get("building_id") == "keep" for obj in collection.objects)
castle_objects = [
    obj
    for obj in collection.objects
    if obj.get("settlement_part", "").startswith("castle_")
    and obj.type == "MESH"
]
assert any(
    obj.get("settlement_part") == "castle_floor" for obj in castle_objects
)
assert any(
    obj.get("settlement_part") == "castle_stairs" for obj in castle_objects
)
castle = plan.castle
sampler = TerrainSampler(plan)
# Test the actual aperture at several offsets, not just the road graph.
for offset in (-0.8, 0, 0.8):
    nx, ny = castle.gate.outward
    x, y, _ = castle.gate.position
    x, y = x - ny * offset, y + nx * offset
    start = Vector((x + nx * 5, y + ny * 5, sampler.height(x, y) + 1.0))
    direction = Vector((-nx, -ny, 0))
    for obj in castle_objects:
        hit, *_ = obj.ray_cast(start, direction, distance=10)
        assert not hit, ("Blocked castle gate", offset, obj.name)
initial = counts()
collection, root, plan = builder.build_settlement(
    config, replace_collection=collection
)
validate(collection)
assert counts() == initial, "Castle regeneration leaked data"
initial = counts()
old = builder._shops_and_markets


def fail(*args):
    old(*args)
    raise RuntimeError("Intentional city failure")


builder._shops_and_markets = fail
try:
    builder.build_settlement(config, replace_collection=collection)
except RuntimeError:
    pass
else:
    raise AssertionError("Failure injection did not run")
finally:
    builder._shops_and_markets = old
assert root.name in bpy.data.objects
assert counts() == initial, "Failed city build leaked data"
settings = getattr(bpy.context.scene, ui.SETTINGS_KEY)
settings.target = collection
assert bpy.ops.settlement.preview() == {"FINISHED"}

config = replace(config, castle_site="WALLED")
collection, root, plan = builder.build_settlement(
    config, replace_collection=collection
)
validate(collection)
assert not any(
    obj.get("settlement_part") == "castle_rock" for obj in collection.objects
)
settings.target = collection
assert bpy.ops.settlement.preview(castle_focus=True) == {"FINISHED"}
initial = counts()
assert bpy.ops.settlement.preview(castle_focus=True) == {"FINISHED"}
assert counts() == initial, "Castle overview recreation leaked data"

decoration = bpy.data.objects.new("UserDecoration", None)
collection.objects.link(decoration)
decoration.parent = root
decoration.location = (1, 2, 0)
bpy.context.view_layer.update()
position = decoration.matrix_world.copy()
builder.remove_settlement(collection)
assert decoration.name in bpy.data.objects
assert (
    decoration.matrix_world.translation - position.translation
).length < 1e-5
assert sentinel.name in bpy.data.objects
ui.unregister()
print(
    "PASS settlement terrain, walls, castle, instances, "
    "interiors and ownership"
)
