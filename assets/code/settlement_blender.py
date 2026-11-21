"""Render settlements using the existing house generator."""

import json
import math
import random
import uuid
from dataclasses import replace

import bpy
from mathutils import Vector

import house_generator as houses
from castle_blender import _window, castle_batches
from castle_interior_blender import interior_batches, room_labels, show_level
from castle_rules import castle_point
from civic_blender import (
    add_tree,
    build_civic,
    build_grass,
    project_assets,
)
from civic_rules import civic_navigation
from fortification_blender import build_walls
from game_materials import configure_surface_materials, purge_unused_images
from settlement_rules import (
    SettlementConfig,
    make_settlement,
    navigation_graph,
    road_segments,
)
from surface_blender import surface_mesh
from terrain_rules import (
    TerrainSampler,
    inside_polygon,
    rectangle_distance,
    segment_projection,
    value_noise,
)

OWNER_KEY = "_settlement_owner"
OWNER = "medieval_settlement_v1"
GENERATION_KEY = "_settlement_generation"


def root_for(collection):
    if collection:
        return next(
            (
                obj
                for obj in collection.objects
                if obj.get(OWNER_KEY) == OWNER
                and obj.get("is_settlement_root")
            ),
            None,
        )
    return None


def _owned(obj, generation):
    obj[OWNER_KEY] = OWNER
    obj[GENERATION_KEY] = generation


def _materials(generation):
    colors = {
        "grass": "87a561",
        "grass_light": "9aa877",
        "grass_dark": "788d60",
        "soil": "89765b",
        "road": "c6b28a",
        "alley": "b9a77e",
        "terrain": "ffffff",
        "bare_terrain": "ffffff",
        "world_water": "ffffff",
        "path_surface": "b49d75",
        "road_surface": "bfb69e",
        "plaza_surface": "c7bca0",
        "stone": "94938a",
        "stone_light": "bbb7a5",
        "castle_roof": "637b87",
        "roof_edge": "354954",
        "castle_stone": "b7a783",
        "castle_slate": "394d59",
        "castle_cone": "394d59",
        "ashlar_light": "c1b190",
        "ashlar_dark": "a99b7f",
        "court_paving": "afa78c",
        "interior_floor": "9a7250",
        "interior_wall": "d7ceb4",
        "stair_wood": "72523a",
        "furniture_wood": "89603f",
        "fabric_red": "9c5249",
        "fabric_blue": "647e8a",
        "fabric_cream": "ded6b8",
        "metal": "575d5a",
        "fire": "edb85e",
        "label": "372d24",
        "castle_shade": "a39170",
        "castle_trim": "d5c5a0",
        "castle_plaster": "e3dac0",
        "glass": "293b3e",
        "timber": "594331",
        "flag": "ad514b",
        "rock": "73776b",
        "rock_light": "8b8e7d",
        "wood": "745238",
        "cloth_red": "b77461",
        "cloth_cream": "e8d7a6",
        "cloth_blue": "70999c",
        "leaves": "69865b",
        "leaves_light": "8e9e63",
        "grass_blade_0": "55783b",
        "grass_blade_1": "728f44",
        "grass_blade_2": "94a856",
        "grass_tuft": "7da356",
        "iron": "384244",
        "rope": "927650",
        "water": "69a6b2",
        "well_water": "34535a",
        "lantern_glow": "ffd291",
    }
    result = {}
    for key, color in colors.items():
        material = bpy.data.materials.new("Settlement_" + key)
        _owned(material, generation)
        material.diffuse_color = houses._linear_color(color)
        shader = houses._principled_shader(material)
        shader.inputs["Base Color"].default_value = material.diffuse_color
        shader.inputs["Roughness"].default_value = 0.85
        if key == "fire":
            shader.inputs[
                "Emission Color"
            ].default_value = material.diffuse_color
            shader.inputs["Emission Strength"].default_value = 1.5
        if key == "lantern_glow":
            shader.inputs[
                "Emission Color"
            ].default_value = material.diffuse_color
            shader.inputs["Emission Strength"].default_value = 2.0
            material["emissive_color"] = material.diffuse_color[:3]
        if key in ("water", "well_water", "world_water"):
            shader.inputs["Roughness"].default_value = 0.20
            shader.inputs["Metallic"].default_value = 0.20
        if key == "iron":
            shader.inputs["Metallic"].default_value = 0.65
            shader.inputs["Roughness"].default_value = 0.40
        result[key] = material
    configure_surface_materials(result, houses._principled_shader)
    return result


def _finish(batch, collection, root, role):
    obj = batch.finish(collection, root)
    if obj:
        _owned(obj, root[GENERATION_KEY])
        _owned(obj.data, root[GENERATION_KEY])
        obj["settlement_part"] = role
        if role == "castle_roofs":
            for polygon in obj.data.polygons:
                polygon.use_smooth = (
                    obj.data.materials[polygon.material_index]
                    == batch.materials["castle_cone"]
                )
            obj.data.set_sharp_from_angle(angle=math.radians(35))
        elif role in (
            "trees",
            "tree_trunks",
            "world_woodland",
            "world_tree_trunks",
            "world_tree_branches",
        ):
            for polygon in obj.data.polygons:
                polygon.use_smooth = len(polygon.vertices) <= 4
    return obj


def _local_box(batch, building, centre, dimensions, material):
    cosine, sine = math.cos(building.heading), math.sin(building.heading)
    x, y, z = centre
    batch.box(
        (
            building.position[0] + x * cosine - y * sine,
            building.position[1] + x * sine + y * cosine,
            building.position[2] + z,
        ),
        dimensions,
        material,
        ((cosine, sine, 0), (-sine, cosine, 0), (0, 0, 1)),
    )


def _shops_and_markets(plan, collection, root, materials):
    batch = houses.MeshBatch("Settlement_Commerce", materials)
    for building in plan.buildings:
        _local_box(
            batch,
            building,
            (0, 0, -0.25),
            (building.width + 0.28, building.depth + 0.28, 0.5),
            "stone",
        )
        if building.business == "RESIDENCE":
            continue
        width = building.width * 0.90
        for i in range(5):
            _local_box(
                batch,
                building,
                (
                    -width / 2 + (i + 0.5) * width / 5,
                    -building.depth / 2 - 0.7,
                    2.35,
                ),
                (width / 5, 1.25, 0.075),
                "cloth_red" if i % 2 else "cloth_cream",
            )
        for x in (-width / 2, width / 2):
            _local_box(
                batch,
                building,
                (x, -building.depth / 2 - 1.25, 1.16),
                (0.08, 0.08, 2.32),
                "wood",
            )
        _local_box(
            batch,
            building,
            (building.width * 0.35, -building.depth / 2 - 0.3, 1.8),
            (0.48, 0.13, 0.42),
            "wood",
        )
    for market in plan.markets:
        x, y, z = market.centre
        # Paving is part of the shared terrain/road surface.
        for i in range(4 if plan.config.scale == "VILLAGE" else 7):
            angle = (
                (i + 0.5)
                * math.tau
                / (4 if plan.config.scale == "VILLAGE" else 7)
            )
            sx = x + market.radius * 0.68 * math.cos(angle)
            sy = y + market.radius * 0.68 * math.sin(angle)
            if any(
                math.dist((sx, sy), a.position[:2]) < a.radius + 1.6
                for a in plan.civic_assets
            ):
                continue
            # Keep stalls away from routes through the square.
            if any(
                segment_projection((sx, sy), a, b)[0] < road.width / 2 + 1.5
                for road in plan.roads
                if road.kind != "ACCESS"
                for a, b in zip(road.points, road.points[1:], strict=False)
            ):
                continue
            batch.box((sx, sy, z + 0.62), (1.7, 1.0, 1.0), "wood")
            batch.box(
                (sx, sy, z + 2.05),
                (2.0, 1.4, 0.12),
                "cloth_blue" if i % 2 else "cloth_red",
            )
            for ox in (-0.8, 0.8):
                batch.box((sx + ox, sy, z + 1.05), (0.07, 0.07, 2.1), "wood")
    _finish(batch, collection, root, "commerce")


def _trees(plan, sampler, collection, root, materials, ground=None):
    if not plan.config.trees:
        return
    rng = random.Random(f"{plan.config.seed}:trees")
    crowns = random.Random(f"{plan.config.seed}:crowns")
    batch = houses.MeshBatch("Settlement_Trees", materials)
    trunks = houses.MeshBatch("Settlement_Trunks", materials)
    branches = houses.MeshBatch("Settlement_Branches", materials)
    segments, roads = road_segments(plan.roads)
    occupied = []
    radius = plan.config.effective_radius
    attempts = round(radius * 14)
    for _ in range(attempts):
        x, y = (
            rng.uniform(-radius * 1.35, radius * 1.35),
            rng.uniform(-radius * 1.25, radius * 1.25),
        )
        if not inside_polygon(
            (x, y), [(a * 1.4, b * 1.4) for a, b in plan.boundary]
        ):
            continue
        if inside_polygon((x, y), plan.boundary) and rng.random() > 0.08:
            continue
        if value_noise(x / 22, y / 22, plan.config.terrain_seed) < -0.1:
            continue
        if ground and not ground(x, y)[1]:
            continue
        if any(math.hypot(x - a, y - b) < 3.5 for a, b in occupied):
            continue
        if any(
            segment_projection((x, y), a, b)[0] < road.width / 2 + 3
            for index in roads.query((x, y), 8)
            for road, _, a, b in (segments[index],)
        ):
            continue
        if any(
            rectangle_distance(
                (x, y),
                building.position,
                building.width,
                building.depth,
                building.heading,
            )
            < 2.5
            for building in plan.buildings
        ):
            continue
        if (
            plan.castle
            and math.dist((x, y), plan.castle.centre[:2])
            < plan.castle.radius + 5
        ):
            continue
        if any(
            math.dist((x, y), m.centre[:2]) < m.radius + 3
            for m in plan.markets
        ):
            continue
        z, height = sampler.height(x, y), rng.uniform(3, 5.5)
        add_tree(
            batch,
            trunks,
            branches,
            (x, y, z),
            height,
            "leaves_light" if rng.random() < 0.4 else "leaves",
            crowns,
            broadleaf_chance=0.68,
        )
        occupied.append((x, y))
    obj = _finish(batch, collection, root, "trees")
    if obj:
        obj["collision_enabled"] = False
        obj["export_chunk_size"] = 32
    _finish(trunks, collection, root, "tree_trunks")
    if limbs := _finish(branches, collection, root, "world_tree_branches"):
        limbs["collision_enabled"] = False
        limbs["export_chunk_size"] = 32


def remove_settlement(collection):
    """Delete owned city data and preserve user additions."""
    root = root_for(collection)
    if root is None:
        return
    generation = root[GENERATION_KEY]
    # Delete instances before removing their house prototypes.
    owned = {
        obj
        for obj in collection.objects
        if obj.get(GENERATION_KEY) == generation
    }
    for obj in list(bpy.data.objects):
        if obj not in owned and obj.parent in owned:
            matrix = obj.matrix_world.copy()
            obj.parent = None
            obj.matrix_world = matrix
    data, materials = set(), set()
    for obj in list(owned):
        if obj.data:
            data.add((obj.type, obj.data))
            if hasattr(obj.data, "materials"):
                materials.update(m for m in obj.data.materials if m)
        bpy.data.objects.remove(obj, do_unlink=True)
    for child in list(bpy.data.collections):
        if child.get(GENERATION_KEY) == generation and child != collection:
            if any(
                obj.instance_collection == child for obj in bpy.data.objects
            ):
                continue
            houses._remove_owned_collection(child)
    storage = {
        "MESH": "meshes",
        "CAMERA": "cameras",
        "LIGHT": "lights",
        "FONT": "curves",
    }
    for kind, block in data:
        if block.users == 0 and kind in storage:
            getattr(bpy.data, storage[kind]).remove(block)
    for material in materials:
        if material.users == 0 and material.get(GENERATION_KEY) == generation:
            bpy.data.materials.remove(material)
    if not collection.objects and not collection.children:
        bpy.data.collections.remove(collection)
    purge_unused_images()


def _prototype(template, generation, scene):
    collection, root, _ = houses.build_house(template.config, scene=scene)
    collection.name = "Prototype_" + template.id
    collection[GENERATION_KEY] = generation
    collection["template_id"] = template.id
    scene.collection.children.unlink(collection)
    return collection


def _instance(collection, root, prototype, identifier, position, heading):
    obj = bpy.data.objects.new(identifier, None)
    collection.objects.link(obj)
    _owned(obj, root[GENERATION_KEY])
    obj.parent = root
    obj.location = position
    obj.rotation_euler.z = heading
    obj.instance_type, obj.instance_collection = "COLLECTION", prototype
    obj["template_id"] = prototype["template_id"]
    obj["building_id"] = identifier
    return obj


def build_settlement(
    config,
    *,
    scene=None,
    replace_collection=None,
    location=(0, 0, 0),
    plan=None,
    parent_collection=None,
    skin=None,
):
    """Build a city before replacing its previous result."""
    if plan is None:
        plan = make_settlement(config)
    scene = scene or bpy.context.scene
    previous_root = root_for(replace_collection)
    if replace_collection is not None and previous_root is None:
        raise ValueError(
            "Select a collection created by the settlement generator"
        )
    if previous_root is not None:
        bpy.context.view_layer.update()
    previous_matrix = (
        previous_root.matrix_world.copy() if previous_root else None
    )
    name = (
        replace_collection.name if replace_collection else "MedievalSettlement"
    )
    collection = bpy.data.collections.new("Settlement_building")
    (parent_collection or scene.collection).children.link(collection)
    root = bpy.data.objects.new("Settlement", None)
    collection.objects.link(root)
    generation = uuid.uuid4().hex
    for block in (collection, root):
        _owned(block, generation)
    root["is_settlement_root"] = True
    root["config_json"] = json.dumps(as_config(config), sort_keys=True)
    root["plan_json"] = json.dumps(plan.as_dict(), sort_keys=True)
    if previous_matrix:
        root.matrix_world = previous_matrix
    else:
        root.location = location
    materials = {}
    try:
        materials = _materials(generation)
        sampler = TerrainSampler(plan)
        mesh, roads = surface_mesh(plan, sampler, materials, skin=skin)
        civic, ground_bvh = project_assets(plan, mesh)
        plan = replace(
            plan,
            roads=roads,
            civic_assets=civic,
            navigation=civic_navigation(
                navigation_graph(
                    roads,
                    plan.buildings,
                    plan.gates,
                    plan.markets,
                    plan.castle,
                ),
                civic,
            ),
        )
        plan.navigation["surface_conformed"] = True
        root["plan_json"] = json.dumps(plan.as_dict(), sort_keys=True)
        obj = bpy.data.objects.new("Terrain_Roads", mesh)
        collection.objects.link(obj)
        for block in (obj, mesh):
            _owned(block, generation)
        obj.parent = root
        obj["settlement_part"] = "terrain"
        obj["roads_integrated"] = True
        wall_batch = houses.MeshBatch("Settlement_Walls", materials)
        if plan.has_walls:
            build_walls(
                wall_batch,
                plan.boundary,
                plan.gates,
                plan.wall_height,
                sampler,
                22 if config.scale == "CAPITAL" else 28,
            )
        _finish(wall_batch, collection, root, "fortifications")
        if plan.castle:
            for role, batch in castle_batches(
                plan.castle, sampler, materials
            ).items():
                obj = _finish(batch, collection, root, "castle_" + role)
                if obj and role == "masonry":
                    obj["building_id"], obj["business"] = "keep", "CASTLE"
            if plan.castle.interior:
                for batch, role, metadata, placement in interior_batches(
                    plan.castle, materials, _window
                ):
                    obj = _finish(batch, collection, root, role)
                    if obj is None:
                        continue
                    for key, value in metadata.items():
                        obj[key] = value
                    if placement:
                        obj.location = placement[0]
                        obj.rotation_euler.z = placement[1]
                room_labels(
                    plan.castle,
                    collection,
                    root,
                    materials["label"],
                    lambda block: _owned(block, generation),
                )
                show_level(collection, root)
                root["castle_view"] = "EXTERIOR"
        needed = {building.template_id for building in plan.buildings}
        prototypes = {
            template.id: _prototype(template, generation, scene)
            for template in plan.templates
            if template.id in needed
        }
        for building in plan.buildings:
            obj = _instance(
                collection,
                root,
                prototypes[building.template_id],
                building.id,
                building.position,
                building.heading,
            )
            obj["business"], obj["zone"] = building.business, building.zone
        _shops_and_markets(plan, collection, root, materials)
        _trees(
            plan,
            sampler,
            collection,
            root,
            materials,
            skin.colour if skin else None,
        )
        build_civic(
            plan,
            collection,
            root,
            materials,
            _finish,
            lambda block: _owned(block, generation),
        )
        build_grass(
            plan,
            mesh,
            ground_bvh,
            collection,
            root,
            materials,
            _finish,
            allowed=skin.grass_allowed if skin else None,
        )
        for poi in plan.navigation["points_of_interest"]:
            if poi["kind"] == "BUILDING_ENTRY":
                continue
            marker = bpy.data.objects.new("POI_" + poi["id"], None)
            collection.objects.link(marker)
            _owned(marker, generation)
            marker.parent = root
            marker.location = poi["position"]
            marker.empty_display_type = "CIRCLE"
            marker["poi_kind"] = poi["kind"]
        for material in list(materials.values()):
            if material.users == 0:
                bpy.data.materials.remove(material)
    except Exception:
        material_names = [material.name for material in materials.values()]
        remove_settlement(collection)
        for material_name in material_names:
            material = bpy.data.materials.get(material_name)
            if material and material.users == 0:
                bpy.data.materials.remove(material)
        purge_unused_images()
        raise
    if replace_collection:
        remove_settlement(replace_collection)
    collection.name = name
    return collection, root, plan


def as_config(config):
    return {
        name: getattr(config, name)
        for name in SettlementConfig.__dataclass_fields__
    }


def materialize_building(instance, city_root, city_collection):
    """Replace an exterior instance with an editable interior house."""
    if instance.get("business") == "CASTLE":
        raise ValueError(
            "성은 전용 외관입니다. 일반 주택 인스턴스를 선택하세요."
        )
    if (
        instance.get(GENERATION_KEY) != city_root[GENERATION_KEY]
        or not instance.instance_collection
    ):
        raise ValueError(
            "Select a building instance belonging to this settlement"
        )
    for child in city_collection.children:
        if child.get("materialized_building") == instance["building_id"]:
            return child, houses._root_for(child)
    prototype = instance.instance_collection
    proto_root = houses._root_for(prototype)
    config = houses.HouseConfig(**json.loads(proto_root["config_json"]))
    config = replace(config, interior=True, furnish=True, door_open=True)
    collection, root, _ = houses.build_house(config)
    collection[GENERATION_KEY] = city_root[GENERATION_KEY]
    collection["materialized_building"] = instance["building_id"]
    bpy.context.scene.collection.children.unlink(collection)
    city_collection.children.link(collection)
    root.parent = city_root
    root.location = instance.location
    root.rotation_euler = instance.rotation_euler
    root.scale = instance.scale
    instance.hide_set(True)
    instance.hide_render = True
    return collection, root


def preview_stage(plan, collection, root):
    """Create a city overview camera and soft studio-style lighting."""
    generation = root[GENERATION_KEY]
    if plan.castle and plan.castle.interior:
        show_level(collection, root)
        root["castle_view"] = "EXTERIOR"
    span = max(
        max(x for x, _ in plan.boundary) - min(x for x, _ in plan.boundary),
        max(y for _, y in plan.boundary) - min(y for _, y in plan.boundary),
    )
    target = Vector((0, 0, 2))
    for obj in list(collection.objects):
        if obj.get("settlement_part") != "preview":
            continue
        data, kind = obj.data, obj.type
        bpy.data.objects.remove(obj, do_unlink=True)
        if data.users == 0:
            getattr(
                bpy.data, "cameras" if kind == "CAMERA" else "lights"
            ).remove(data)
    data = bpy.data.cameras.new("Settlement_Camera")
    camera = bpy.data.objects.new("Settlement_Camera", data)
    collection.objects.link(camera)
    _owned(camera, generation)
    camera["settlement_part"] = "preview"
    camera.parent = root
    camera.location = (span * 0.80, -span * 1.05, span * 0.90)
    bpy.context.view_layer.update()
    camera.rotation_euler = (
        (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    )
    data.type, data.ortho_scale, data.clip_end = (
        "ORTHO",
        span * 1.85,
        span * 20,
    )
    bpy.context.scene.camera = camera
    for name, position, energy in (
        ("Key", (-span * 0.5, -span * 0.5, span), 1900),
        ("Fill", (span * 0.7, 0, span * 0.7), 1000),
    ):
        data = bpy.data.lights.new("Settlement_" + name, "AREA")
        data.energy, data.shape, data.size = (
            energy * (span / 8) ** 2,
            "DISK",
            span * 0.8,
        )
        obj = bpy.data.objects.new("Settlement_" + name, data)
        collection.objects.link(obj)
        _owned(obj, generation)
        obj["settlement_part"] = "preview"
        obj.parent = root
        obj.location = position
        bpy.context.view_layer.update()
        obj.rotation_euler = (
            (target - obj.location).to_track_quat("-Z", "Y").to_euler()
        )
    scene = bpy.context.scene
    if scene.world is None or scene.world.get(OWNER_KEY) != OWNER:
        scene.world = bpy.data.worlds.new("Settlement_World")
        scene.world[OWNER_KEY] = OWNER
    scene.world.use_nodes = True
    background = next(
        (
            node
            for node in scene.world.node_tree.nodes
            if node.type == "BACKGROUND"
        ),
        None,
    )
    if background:
        background.inputs["Color"].default_value = (0.72, 0.82, 0.91, 1)
        background.inputs["Strength"].default_value = 0.6
    scene.render.engine = "CYCLES"
    scene.cycles.samples, scene.cycles.use_denoising = 24, True
    scene.cycles.device = "CPU"
    scene.render.resolution_x, scene.render.resolution_y = 1400, 1100
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"


def preview_castle(plan, collection, root):
    """Frame the castle, its hillside and the gate approach."""
    if plan.castle is None:
        raise ValueError("먼저 성이 있는 도시를 생성하세요")
    preview_stage(plan, collection, root)
    castle = plan.castle
    radius = castle.radius
    height = castle.architecture.height
    camera = bpy.context.scene.camera
    target = Vector(
        castle_point(castle.centre, castle.keep_heading, (0, 0, height * 0.37))
    )
    camera.location = castle_point(
        castle.centre,
        castle.keep_heading,
        (radius * 2.7, -radius * 3.8, height * 1.35),
    )
    camera.rotation_euler = (
        (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    )
    camera.data.ortho_scale = max(radius * 3.25, height * 1.8)
    bpy.context.view_layer.update()


def preview_castle_level(plan, collection, root, level):
    if not plan.castle or not plan.castle.interior:
        raise ValueError("성 실내 생성을 켜고 도시를 갱신하세요")
    chosen = next(
        (f for f in plan.castle.interior.levels if f.id == level), None
    )
    if chosen is None:
        raise ValueError("해당 성 층이 없습니다")
    preview_castle(plan, collection, root)
    show_level(collection, root, level)
    root["castle_view"] = level
    castle = plan.castle
    radius = castle.radius
    target = Vector(
        castle_point(
            castle.centre,
            castle.keep_heading,
            (0, 2 * castle.architecture.scale, chosen.z),
        )
    )
    camera = bpy.context.scene.camera
    camera.location = castle_point(
        castle.centre,
        castle.keep_heading,
        (radius * 0.8, -radius * 1.0, chosen.z + radius * 2.2),
    )
    camera.rotation_euler = (
        (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    )
    camera.data.ortho_scale = radius * (2.55 if level == "rampart" else 1.90)
    bpy.context.view_layer.update()
