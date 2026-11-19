"""Build a Blender landscape with four settlement profiles."""

import json
import math
import random
import uuid
from dataclasses import asdict, replace
from functools import partial

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

import settlement_blender as towns
from civic_blender import add_conifer_crown, build_grass_meshes, ground_cast
from civic_rules import grass_cells, grass_samples, meadow_growth
from fortification_blender import cylinder
from house_generator import MeshBatch, _linear_color
from surface_blender import TerrainSkin, paint_land, set_edge_normals
from surface_quality import SurfaceGradeError
from terrain_rules import (
    ground_gradient,
    segment_projection,
    smoothstep,
    value_noise,
)
from world_landmarks import build_landmark
from world_rules import (
    LandmarkGradeError,
    choose_site,
    with_deck,
    world_navigation,
)

PALETTE = {
    label: _linear_color(colour)[:3]
    for label, colour in {
        "grass": "789d58",
        "meadow": "a2b76f",
        "wet_grass": "619366",
        "rock": "8b8584",
        "sand": "cbb38b",
        "silt": "90836d",
        "snow": "e1e9e8",
        "surf": "8ebdc0",
        "ocean": "437e93",
        "lake_edge": "78acad",
        "lake_deep": "4b8692",
        "river_edge": "8ab1ac",
        "river_deep": "548a96",
    }.items()
}
MEADOW_RADII = (32.0, 24.0)


def _mix(a, b, weight):
    return tuple(x + (y - x) * weight for x, y in zip(a, b, strict=True))


def _colour(terrain, x, y, height=None):
    config = terrain.config
    height = height or terrain.height
    level = height(x, y)
    slope = math.hypot(
        *ground_gradient(height, x, y, config.terrain_step * 0.42)
    )
    noise = value_noise(x / 46, y / 46, config.seed + 417)
    fleck = value_noise(x / 16, y / 16, config.seed + 214)
    growth = meadow_growth(x, y, config.seed)
    warmth = 0.72 * smoothstep(-0.42, 0.78, noise) + 0.28 * growth
    rgb = _mix(PALETTE["grass"], PALETTE["meadow"], warmth)
    rgb = tuple(c * (1 + fleck * 0.09) for c in rgb)
    rock = smoothstep(0.40, 0.94, slope)
    strata = value_noise(x / 29 + level / 14, y / 43, config.seed + 48)
    stone = tuple(c * (1 + 0.23 * strata) for c in PALETTE["rock"])
    rgb = _mix(rgb, stone, rock)
    snowy = smoothstep(
        config.snowline - 4, config.snowline + 28, level + fleck * 7
    )
    rgb = _mix(rgb, PALETTE["snow"], snowy * (1 - rock * 0.27))
    grassy = snowy < 0.32 and slope < 0.63
    waters = terrain.water_near(x, y)
    if waters:
        water = min(waters, key=lambda w: w.distance)
        if water.kind == "SEA":
            tint, bank = PALETTE["sand"], 10.5
        else:
            tint = _mix(PALETTE["silt"], PALETTE["wet_grass"], 0.40)
            bank = 4.4
        weight = 1 - smoothstep(bank * 0.35, bank * 1.75, water.distance)
        grassy &= water.distance > bank * 0.73
        rgb = _mix(rgb, tint, weight)
    return rgb, grassy


def _normal(terrain, x, y):
    sx, sy = ground_gradient(
        terrain.height, x, y, terrain.config.terrain_step * 0.45
    )
    return Vector((-sx, -sy, 1)).normalized()


def _skin(terrain, site):
    ox, oy = site.centre
    left, bottom = site.settlement.surface_boundary[0]
    right = max(p[0] for p in site.settlement.surface_boundary)
    top = max(p[1] for p in site.settlement.surface_boundary)
    local = site.settlement.terrain.ground
    allowed = _grass_mask(terrain, (site,))

    def ground(x, y):
        return local(x - ox, y - oy)

    def colour(x, y):
        if (
            min(abs(x - left), abs(x - right), abs(y - bottom), abs(y - top))
            < 0.001
        ):
            return _colour(terrain, x + ox, y + oy)
        return _colour(terrain, x + ox, y + oy, ground)

    return TerrainSkin(
        site.centre,
        colour,
        lambda x, y: terrain.height(x + ox, y + oy),
        lambda x, y: _normal(terrain, x + ox, y + oy),
        lambda x, y: allowed(x + ox, y + oy),
    )


def _macro_mesh(plan, materials):
    grid, terrain = plan.grid, plan.terrain
    omitted, ring = set(), set()
    for site in plan.sites:
        left, bottom, right, top = site.bounding_cells
        omitted.update(
            (i, j) for i in range(left, right) for j in range(bottom, top)
        )
        ring.update(grid.ring(site.bounding_cells))
    n, m = grid.shape
    vertices, lookup, triangles = [], {}, []

    def vertex(i, j):
        key = i, j
        if key not in lookup:
            x, y = grid.xy(i, j)
            lookup[key] = len(vertices)
            vertices.append((x, y, terrain.height(x, y)))
        return lookup[key]

    for j in range(m):
        for i in range(n):
            if (i, j) in omitted:
                continue
            a, b = vertex(i, j), vertex(i + 1, j)
            c, d = vertex(i + 1, j + 1), vertex(i, j + 1)
            if (i + j) % 2:
                triangles.extend(((a, b, d), (b, c, d)))
            else:
                triangles.extend(((a, b, c), (a, c, d)))
    mesh = bpy.data.meshes.new("World_Landscape")
    mesh.from_pydata(vertices, [], triangles)
    mesh.update()
    paint_land(
        mesh, materials, [0] * len(triangles), partial(_colour, terrain)
    )
    if ring:
        seam = {i for i, (x, y, _) in enumerate(vertices) if (x, y) in ring}
        set_edge_normals(mesh, seam, partial(_normal, terrain))
    return mesh


def _link_mesh(mesh, collection, root, role, *, collision=True):
    obj = bpy.data.objects.new(mesh.name, mesh)
    collection.objects.link(obj)
    obj.parent = root
    for block in (mesh, obj):
        towns._owned(block, root[towns.GENERATION_KEY])
    obj["settlement_part"] = role
    obj["collision_enabled"] = collision
    return obj


def _clip_water(rows):
    result = []
    for a, b in zip(rows[-1:] + rows[:-1], rows, strict=True):
        if (a[3] > 0) != (b[3] > 0):
            t = a[3] / (a[3] - b[3])
            result.append(
                tuple(a[i] + (b[i] - a[i]) * t for i in range(3)) + (0,)
            )
        if b[3] > 0:
            result.append(b)
    return result


def _water_colour(kind, depth):
    rim, centre, limit = {
        "SEA": ("surf", "ocean", 8.5),
        "LAKE": ("lake_edge", "lake_deep", 4.6),
        "RIVER": ("river_edge", "river_deep", 2.2),
    }[kind]
    return (
        *_mix(PALETTE[rim], PALETTE[centre], smoothstep(0, limit, depth)),
        1,
    )


def _water_mesh(plan, sources, material):
    terrain = plan.terrain
    vertices, lookup, colours, triangles = [], {}, [], []
    reach = plan.grid.step * 1.6

    def vertex(row, kind):
        key = (kind, *(round(v, 5) for v in row[:3]))
        if key not in lookup:
            lookup[key] = len(vertices)
            vertices.append(row[:3])
            colours.append(_water_colour(kind, row[3]))
        return lookup[key]

    for mesh, (ox, oy) in sources:
        coords = [(v.co.x + ox, v.co.y + oy, v.co.z) for v in mesh.vertices]
        states = []
        for x, y, z in coords:
            bodies = terrain.water_near(x, y, reach)
            sea = next((w for w in bodies if w.kind == "SEA"), None)
            levels = {}
            for body in bodies:
                coverage = min(body.level - z - 0.001, -body.distance * 0.34)
                if sea and body.id in terrain.sea_outlets:
                    coverage = min(coverage, sea.distance * 0.34)
                levels[body.id] = (body.kind, body.level, coverage)
            states.append(levels)
        for polygon in mesh.polygons:
            ids = tuple(polygon.vertices)
            candidates = {
                key: (kind, level)
                for i in ids
                for key, (kind, level, sign) in states[i].items()
                if sign > 0
            }
            for key, (kind, default) in candidates.items():
                rows = []
                for i in ids:
                    x, y, _ = coords[i]
                    _, level, sign = states[i].get(
                        key, (kind, default, -reach * 0.34)
                    )
                    rows.append((x, y, level + 0.005, sign))
                clipped = _clip_water(rows)
                indices = [vertex(p, kind) for p in clipped]
                for j in range(1, len(indices) - 1):
                    tri = indices[0], indices[j], indices[j + 1]
                    if len(set(tri)) == 3:
                        triangles.append(tri)
    if not triangles:
        return None
    mesh = bpy.data.meshes.new("World_Water")
    mesh.from_pydata(vertices, [], triangles)
    mesh.materials.append(material)
    mesh.update()
    attribute = mesh.color_attributes.new(
        name="Color", type="FLOAT_COLOR", domain="POINT"
    )
    for item, value in zip(attribute.data, colours, strict=True):
        item.color = value
    return mesh


def _outside_settlements(plan, x, y):
    i = (x + plan.grid.size[0] / 2) / plan.grid.step
    j = (y + plan.grid.size[1] / 2) / plan.grid.step
    return all(
        not (left <= i <= right and bottom <= j <= top)
        for left, bottom, right, top in (s.bounding_cells for s in plan.sites)
    )


def _grass_mask(terrain, sites):
    deck_edges = [
        (a, b, site.landmark.width / 2 + 0.65)
        for site in sites
        if site.landmark
        for a, b in zip(site.deck_path, site.deck_path[1:], strict=False)
    ]

    def allowed(x, y):
        return not terrain.wet(x, y, margin=1.45) and not any(
            segment_projection((x, y), a, b)[0] < clearance
            for a, b, clearance in deck_edges
        )

    return allowed


def _meadow_fields(plan, cast, mesh, material, allowed):
    """Select continuous meadows near the major approaches."""
    half_x, half_y = (v / 2 for v in plan.grid.size)
    meadow = list(mesh.materials).index(material)
    grass_faces = [p.material_index == meadow for p in mesh.polygons]
    fields = []

    def eligible(x, y):
        point, normal, face, _ = cast(x, y)
        if (
            point is not None
            and normal.z >= 0.85
            and grass_faces[face]
            and allowed(x, y)
        ):
            return point
        return None

    def pick(candidates, target, site_id=None):
        ranked = []
        for x, y in candidates:
            if abs(x) > half_x - 12 or abs(y) > half_y - 12:
                continue
            if any(math.dist((x, y), p[:2]) < 72 for p, _, _ in fields):
                continue
            centre = eligible(x, y)
            if centre is None:
                continue
            support = sum(
                eligible(x + dx, y + dy) is not None
                for dx, dy in (
                    (-19, 0),
                    (19, 0),
                    (0, -15),
                    (0, 15),
                    (-15, -9),
                    (15, -9),
                    (-15, 9),
                    (15, 9),
                )
            )
            if support >= 6:
                score = support + meadow_growth(x, y, plan.config.seed)
                ranked.append((score, tuple(centre)))
        if ranked:
            _, centre = max(ranked)
            fields.append((centre, target, site_id))

    for site in plan.sites:
        left, bottom, right, top = site.bounding_cells
        x0, y0 = plan.grid.xy(left, bottom)
        x1, y1 = plan.grid.xy(right, top)
        cx, cy = site.centre
        picks = []
        for offset in (-25, 0, 25):
            picks.extend(
                (
                    (x0 - 28, cy + offset),
                    (x1 + 28, cy + offset),
                    (cx + offset, y0 - 22),
                    (cx + offset, y1 + 22),
                )
            )
        pick(picks, site.centre, site.id)
        if len(fields) == 4:
            break

    inland = [
        r.centre for r in plan.config.regions if r.kind in ("PLAIN", "VALLEY")
    ]
    if not inland and not fields:
        inland = [
            (half_x * u, half_y * v)
            for u in (-0.6, -0.3, 0, 0.3, 0.6)
            for v in (-0.6, -0.3, 0, 0.3, 0.6)
        ]
    if inland:
        pick(inland, None)
    return fields


def _world_grass(plan, fields, allowed):
    density = plan.config.grass_density
    seed = plan.config.seed
    half_x, half_y = (v / 2 for v in plan.grid.size)

    def valid(x, y):
        return (
            abs(x) < half_x
            and abs(y) < half_y
            and _outside_settlements(plan, x, y)
            and allowed(x, y)
        )

    rx, ry = MEADOW_RADII
    spacing = max(9.0, math.sqrt(math.prod(plan.grid.size) / 12_000))
    spacing /= math.sqrt(density)
    land = grass_cells((-half_x, -half_y, half_x, half_y), spacing)
    for x, y, growth, angle, chance in grass_samples(land, spacing, seed):
        if chance < 0.52 + growth * 0.3 and valid(x, y):
            yield x, y, 0.15 + growth * 0.15, angle

    area = len(fields) * rx * ry * 4
    detail = max(0.41, math.sqrt(area / 68_000)) / math.sqrt(density)
    outer_radius = 2.47
    shoulder = max(0.84, math.sqrt(area * outer_radius**2 / 148_000))
    shoulder /= math.sqrt(density)
    planted = set()
    for (cx, cy, _), _, _ in fields:
        xmin, xmax = cx - rx * outer_radius, cx + rx * outer_radius
        ymin, ymax = cy - ry * outer_radius, cy + ry * outer_radius
        outer = grass_cells((xmin, ymin, xmax, ymax), shoulder)
        for x, y, growth, angle, chance in grass_samples(
            outer, shoulder, seed
        ):
            radius = math.hypot((x - cx) / rx, (y - cy) / ry)
            radius += (0.5 - growth) * 0.29
            cover = smoothstep(0.61, 0.89, radius)
            cover *= 1 - smoothstep(1.24, outer_radius, radius)
            if chance < cover and (x, y) not in planted and valid(x, y):
                planted.add((x, y))
                yield x, y, 0.21 + growth * 0.11, angle

        inner = grass_cells(
            (cx - rx * 1.15, cy - ry * 1.15, cx + rx * 1.15, cy + ry * 1.15),
            detail,
        )
        for x, y, growth, angle, chance in grass_samples(inner, detail, seed):
            radius = math.hypot((x - cx) / rx, (y - cy) / ry)
            radius += (0.5 - growth) * 0.23
            cover = (0.81 + growth * 0.18) * (
                1 - smoothstep(0.63, 1.13, radius)
            )
            if chance < cover and valid(x, y):
                edge = 1 - smoothstep(0.54, 1.12, radius)
                yield x, y, 0.22 + edge * (0.32 + growth * 0.41), angle


def _trees(plan, project, collection, root, materials):
    """Place woodland between the shoreline and high ridges."""
    rng = random.Random(f"{plan.config.seed}:world-woods")
    crowns = random.Random(f"{plan.config.seed}:world-crowns")
    batch = MeshBatch("World_Woodland", materials)
    trunks = MeshBatch("World_Tree_Trunks", materials)
    grid, terrain = plan.grid, plan.terrain
    step = max(8.5, math.sqrt(math.prod(grid.size) / 24_000))
    nx, ny = (math.floor(size / step) for size in grid.size)
    for i in range(nx):
        for j in range(ny):
            x = (i + rng.uniform(0.19, 0.81)) * step - grid.size[0] / 2
            y = (j + rng.uniform(0.19, 0.81)) * step - grid.size[1] / 2
            noise = value_noise(x / 67, y / 67, plan.config.seed + 564)
            if noise < 0.02 or rng.random() > noise + 0.18:
                continue
            if not _outside_settlements(plan, x, y) or terrain.wet(x, y, 9):
                continue
            hit, normal, *_ = project(x, y)
            if (
                hit is None
                or normal.z < 0.81
                or hit.z > plan.config.snowline - 15
            ):
                continue
            height = rng.uniform(4.5, 8.3)
            cylinder(
                trunks,
                (x, y, hit.z - 0.18),
                height * 0.042,
                height * 0.65,
                "wood",
                8,
            )
            material = "leaves_light" if crowns.random() < 0.35 else "leaves"
            add_conifer_crown(batch, (x, y, hit.z), height, material, crowns)
    obj = towns._finish(batch, collection, root, "world_woodland")
    if obj:
        obj["collision_enabled"] = False
        obj["export_chunk_size"] = 128
    obj = towns._finish(trunks, collection, root, "world_tree_trunks")
    if obj:
        obj["export_chunk_size"] = 128


def _realize_site(plan, initial, occupied, collection, root, scene, materials):
    site, rejected = initial, set()
    request = next(r for r in plan.config.settlements if r.id == site.id)
    for attempt in range(5):
        child = None
        try:
            child, city, realized = towns.build_settlement(
                site.settlement.config,
                scene=scene,
                plan=site.settlement,
                parent_collection=collection,
                location=(*site.centre, 0),
                skin=_skin(plan.terrain, site),
            )
            mesh = next(
                o.data for o in child.objects if o.get("roads_integrated")
            )
            site = replace(site, settlement=realized)
            if site.landmark:
                bvh = BVHTree.FromPolygons(
                    [v.co for v in mesh.vertices],
                    [p.vertices for p in mesh.polygons],
                    all_triangles=True,
                )
                ox, oy = site.centre
                cast = ground_cast(mesh, bvh)

                def height(x, y, project=cast, origin=(ox, oy)):
                    point, *_ = project(x - origin[0], y - origin[1])
                    if point is not None:
                        return point.z
                    return plan.terrain.height(x, y)

                site = with_deck(site, height)
                build_landmark(
                    site,
                    plan.terrain,
                    height,
                    collection,
                    root,
                    materials=materials,
                )
        except (SurfaceGradeError, LandmarkGradeError) as error:
            if child:
                towns.remove_settlement(child)
            if attempt == 4 or not request.search_radius:
                raise ValueError(f"{site.id}: {error}") from error
            print(f"{site.id}: checking the next site ({error})", flush=True)
            rejected.add(site.centre)
            site = choose_site(
                plan.terrain, plan.grid, request, occupied, rejected=rejected
            )
        except Exception:
            if child:
                towns.remove_settlement(child)
            raise
        else:
            child.name = site.id
            city.name, city.parent = site.id + "_Root", root
            city["world_site_id"] = site.id
            city["world_site_profile"] = site.profile
            return site, child, mesh


def build_world(plan, *, scene=None):
    scene = scene or bpy.context.scene
    collection = bpy.data.collections.new("ProceduralWorld")
    scene.collection.children.link(collection)
    root = bpy.data.objects.new("WorldMap", None)
    collection.objects.link(root)
    generation = uuid.uuid4().hex
    for block in (collection, root):
        towns._owned(block, generation)
    root["is_world_root"] = True
    created = []
    materials = {}
    try:
        materials = towns._materials(generation)
        sources, sites = [], []
        for i, initial in enumerate(plan.sites):
            occupied = (*sites, *plan.sites[i + 1 :])
            site, child, mesh = _realize_site(
                plan, initial, occupied, collection, root, scene, materials
            )
            created.append(child)
            sources.append((mesh, site.centre))
            sites.append(site)
        plan = replace(plan, sites=tuple(sites))
        macro = _macro_mesh(plan, materials)
        obj = _link_mesh(macro, collection, root, "world_terrain")
        obj["export_chunk_size"] = 128
        tree = BVHTree.FromPolygons(
            [v.co for v in macro.vertices],
            [p.vertices for p in macro.polygons],
            all_triangles=True,
        )
        sources.insert(0, (macro, (0, 0)))
        if (plan.config.coast or plan.config.lakes or plan.config.rivers) and (
            mesh := _water_mesh(plan, sources, materials["world_water"])
        ):
            obj = _link_mesh(
                mesh, collection, root, "world_water", collision=False
            )
            obj["export_chunk_size"] = 128
        project = ground_cast(macro, tree)
        if plan.config.grass_density > 0:
            allowed = _grass_mask(plan.terrain, plan.sites)
            fields = _meadow_fields(
                plan, project, macro, materials["terrain"], allowed
            )
            root["grass_tufts"] = build_grass_meshes(
                _world_grass(plan, fields, allowed),
                macro,
                tree,
                plan.config.seed,
                collection,
                root,
                materials,
                towns._finish,
            )
            root["meadow_views_json"] = json.dumps(fields)
        _trees(plan, project, collection, root, materials)
        summary = [
            {
                "id": s.id,
                "profile": s.profile,
                "centre": (*s.centre, plan.terrain.height(*s.centre)),
                "radius": s.settlement.config.effective_radius,
                "landmark": asdict(s.landmark) if s.landmark else None,
                "deck_path": s.deck_path,
                "building_count": len(s.settlement.buildings),
            }
            for s in sites
        ]
        root["config_json"] = json.dumps(asdict(plan.config))
        root["plan_json"] = json.dumps({"navigation": world_navigation(sites)})
        root["world_sites_json"] = json.dumps(summary)
        bpy.context.view_layer.update()
    except Exception:
        for child in created:
            towns.remove_settlement(child)
        for obj in list(collection.objects):
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data and data.users == 0:
                bpy.data.meshes.remove(data)
        bpy.data.collections.remove(collection)
        raise
    finally:
        for material in materials.values():
            if material.users == 0:
                bpy.data.materials.remove(material)
        towns.purge_unused_images()
    return collection, root, plan


def _preview_sky(scene):
    if not scene.world or not scene.world.get("procedural_world_lighting"):
        scene.world = bpy.data.worlds.new("World_Sky")
        scene.world["procedural_world_lighting"] = True
        scene.world.use_nodes = True
    tree = scene.world.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputWorld")
    light = tree.nodes.new("ShaderNodeBackground")
    light.inputs["Color"].default_value = (0.56, 0.72, 1.0, 1)
    light.inputs["Strength"].default_value = 0.58
    coordinate = tree.nodes.new("ShaderNodeTexCoord").outputs["Normal"]
    xyz = tree.nodes.new("ShaderNodeSeparateXYZ")
    tree.links.new(coordinate, xyz.inputs["Vector"])
    sky = tree.nodes.new("ShaderNodeValToRGB")
    sky.color_ramp.interpolation = "EASE"
    horizon, zenith = sky.color_ramp.elements
    horizon.position, horizon.color = 0.0, _linear_color("D6EBEC")
    zenith.position, zenith.color = 0.48, _linear_color("76B9E7")
    tree.links.new(xyz.outputs["Z"], sky.inputs["Fac"])

    clouds = tree.nodes.new("ShaderNodeTexNoise")
    clouds.inputs["Scale"].default_value = 5.8
    clouds.inputs["Detail"].default_value = 2.65
    tree.links.new(coordinate, clouds.inputs["Vector"])
    cover = tree.nodes.new("ShaderNodeMapRange")
    cover.interpolation_type = "SMOOTHERSTEP"
    cover.inputs["From Min"].default_value = 0.54
    cover.inputs["From Max"].default_value = 0.70
    cover.inputs["To Max"].default_value = 0.77
    tree.links.new(clouds.outputs["Fac"], cover.inputs["Value"])
    cloud_mix = tree.nodes.new("ShaderNodeMixRGB")
    cloud_mix.inputs[2].default_value = _linear_color("FFF4E6")
    tree.links.new(cover.outputs["Result"], cloud_mix.inputs[0])
    tree.links.new(sky.outputs["Color"], cloud_mix.inputs[1])
    backdrop = tree.nodes.new("ShaderNodeBackground")
    backdrop.inputs["Strength"].default_value = 1.25
    path = tree.nodes.new("ShaderNodeLightPath")
    mix = tree.nodes.new("ShaderNodeMixShader")
    tree.links.new(cloud_mix.outputs["Color"], backdrop.inputs["Color"])
    tree.links.new(light.outputs["Background"], mix.inputs[1])
    tree.links.new(backdrop.outputs["Background"], mix.inputs[2])
    tree.links.new(path.outputs["Is Camera Ray"], mix.inputs[0])
    tree.links.new(mix.outputs["Shader"], output.inputs["Surface"])


def _meadow_haze(scene, enabled):
    if not hasattr(scene, "compositing_node_group"):
        return
    tree = scene.compositing_node_group
    if tree and not tree.get("procedural_meadow_haze"):
        return
    if tree or enabled:
        scene.render.use_compositing = enabled
    if not enabled:
        return
    scene.world.mist_settings.start = 40
    scene.world.mist_settings.depth = 520
    scene.world.mist_settings.falloff = "LINEAR"
    layer = bpy.context.view_layer
    layer.use_pass_mist = True
    if tree is None:
        tree = bpy.data.node_groups.new("Meadow Haze", "CompositorNodeTree")
        tree["procedural_meadow_haze"] = True
        tree.interface.new_socket(
            name="Image", in_out="OUTPUT", socket_type="NodeSocketColor"
        )
        scene.compositing_node_group = tree
    tree.nodes.clear()
    source = tree.nodes.new("CompositorNodeRLayers")
    source.layer = layer.name
    depth = tree.nodes.new("ShaderNodeMath")
    depth.operation = "MULTIPLY"
    depth.inputs[1].default_value = 0.57
    tint = tree.nodes.new("ShaderNodeMixRGB")
    tint.inputs[2].default_value = _linear_color("BCDCE4")
    output = tree.nodes.new("NodeGroupOutput")
    tree.links.new(source.outputs["Mist"], depth.inputs[0])
    tree.links.new(depth.outputs[0], tint.inputs[0])
    tree.links.new(source.outputs["Image"], tint.inputs[1])
    tree.links.new(tint.outputs[0], output.inputs["Image"])


def preview_world(collection, root, focus=None, *, meadow=False):
    """Frame the map, a settlement or a walk through its meadow."""
    config = json.loads(root["config_json"])
    sites = json.loads(root["world_sites_json"])
    span = max(config["size"])
    if meadow:
        fields = json.loads(root.get("meadow_views_json", "[]"))
        field = next((f for f in fields if not focus or f[2] == focus), None)
        if field is None:
            raise ValueError("No walkable meadow was found for this view")
        ground, near, _ = field
        forward = (
            Vector((near[0] - ground[0], near[1] - ground[1], 0))
            if near
            else Vector((0.4, 1.0, 0))
        ).normalized()
        location = Vector(ground) + Vector((0, 0, 1.70))
        target = location + forward * 32 + Vector((0, 0, -3.6))
        framing = 33
        sideways = Vector((-forward.y, forward.x, 0))
        direction = -forward * 0.57 + sideways * 0.83 + Vector((0, 0, -0.82))
    else:
        direction = Vector((0.5, 0.72, -0.82))
    for obj in list(collection.objects):
        if obj.get("settlement_part") == "preview":
            source = (
                bpy.data.cameras if obj.type == "CAMERA" else bpy.data.lights
            )
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data.users == 0:
                source.remove(data)
    if not meadow and focus:
        site = next((s for s in sites if s["id"] == focus), None)
        if not site:
            raise ValueError(f"Unknown focus site: {focus}")
        centre = Vector(site["centre"])
        target = centre.copy()
        if site["deck_path"]:
            target = target.lerp(Vector(site["deck_path"][-1]), 0.40)
        offset = Vector((target.x - centre.x, target.y - centre.y, 0))
        if offset.length < 1e-6:
            offset = Vector((0, -1, 0))
        offset.normalize()
        side = Vector((-offset.y, offset.x, 0))
        framing = site["radius"] * 2.92
        location = target + framing * (
            offset * 0.77 + side * 0.55 + Vector((0, 0, 0.52))
        )
    elif not meadow:
        framing = span * 1.18
        target = Vector((0, 0, config["base_elevation"] + span * 0.012))
        location = target + Vector((-0.18, -0.99, 1.16)) * span
    generation = root[towns.GENERATION_KEY]
    camera_data = bpy.data.cameras.new("World_Camera")
    camera = bpy.data.objects.new("World_Camera", camera_data)
    collection.objects.link(camera)
    towns._owned(camera, generation)
    camera["settlement_part"] = "preview"
    camera.parent = root
    camera.location = location
    camera.rotation_euler = (
        (target - location).to_track_quat("-Z", "Y").to_euler()
    )
    camera_data.type = "PERSP" if meadow else "ORTHO"
    camera_data.lens = 32
    camera_data.ortho_scale, camera_data.clip_end = framing, span * 8
    camera_data.clip_start = 0.08 if meadow else 0.1
    sun_data = bpy.data.lights.new("World_Sun", "SUN")
    sun_data.energy = 3.4 if meadow else 2.8
    sun_data.angle = math.radians(7 if meadow else 9)
    sun_data.color = (1.0, 0.86, 0.69) if meadow else (1.0, 0.94, 0.81)
    sun = bpy.data.objects.new("World_Sun", sun_data)
    collection.objects.link(sun)
    towns._owned(sun, generation)
    sun["settlement_part"] = "preview"
    sun.parent = root
    sun.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    scene = bpy.context.scene
    scene.camera = camera
    _preview_sky(scene)
    scene.render.engine = "CYCLES"
    scene.cycles.samples, scene.cycles.use_denoising = 16, True
    scene.render.resolution_x, scene.render.resolution_y = 1600, 1150
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = 0.20 if meadow else 0
    _meadow_haze(scene, meadow)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                space.clip_end = span * 8
                space.region_3d.view_location = target
                space.region_3d.view_rotation = (
                    camera.rotation_euler.to_quaternion()
                )
                space.region_3d.view_distance = framing * 0.87
                space.region_3d.view_perspective = (
                    "CAMERA" if meadow else "ORTHO"
                )
