"""Bake selected atlas tiles and their playable places in Blender."""

import json
import math
import random
import uuid
from functools import lru_cache
from itertools import chain, pairwise

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.noise import noise

import settlement_blender as towns
from atlas_places import (
    Landscape,
    atlas_paths,
    clip_segment,
    contains,
    routes_in_bounds,
)
from atlas_rules import ENVIRONMENTS, TILE, default_focus, stable_seed
from atlas_structures import (
    Buildings,
    castle,
    dungeon,
    house,
    institution,
    plaza,
)
from civic_blender import add_conifer_crown, build_grass_meshes
from civic_rules import grass_cells, grass_samples
from fortification_blender import cylinder
from house_generator import MeshBatch, _linear_color
from surface_blender import paint_land
from terrain_rules import ground_gradient, segment_projection, smoothstep
from world_blender import _clip_water, _preview_sky, _water_colour

EARTH = {
    key: _linear_color(value[3])[:3] for key, value in ENVIRONMENTS.items()
}


def _ground_colour(atlas, surface, x, y):
    layers = atlas.region_weights(x, y)[:3]
    total = sum(v[0] for v in layers)
    rgb = tuple(
        sum(EARTH[k][c] * w / total for w, k, _, _ in layers) for c in range(3)
    )
    slope = math.hypot(*ground_gradient(surface, x, y, 2.5))
    rock = smoothstep(0.38, 1.03, slope)
    wet = atlas.water_at(x, y)
    grass = layers[0][1] not in ("DESERT", "SNOW") and slope < 0.67 and not wet
    if wet:
        return _linear_color("817063")[:3], False
    detail = noise(Vector((x / 61, y / 61, atlas.seed % 2000))) * 0.15
    return tuple(
        (c + (d - c) * rock) * (1 + detail)
        for c, d in zip(rgb, _linear_color("92938d")[:3], strict=True)
    ), grass


def _seam_sample(probe, x, y, left, bottom):
    # All LOD vertex heights lie on the same 16m boundary polyline.
    if x in (left, left + TILE):
        base = math.floor(y / 16) * 16
        t = (y - base) / 16
        a, b = probe(x, base), probe(x, base + 16)
    elif y in (bottom, bottom + TILE):
        base = math.floor(x / 16) * 16
        t = (x - base) / 16
        a, b = probe(base, y), probe(base + 16, y)
    else:
        return probe(x, y)
    if t == 0:
        return a
    return a + (b - a) * t


def terrain_mesh(stage, atlas, land, cell, shafts, step):
    name = f"tile_{cell[0]}_{cell[1]}"
    left, bottom = atlas.corner(*cell)
    count = TILE // step + 1
    height = lru_cache(maxsize=60_000)(land.height)
    points, tris = [], []
    for j in range(count):
        for i in range(count):
            x, y = left + i * step, bottom + j * step
            points.append((x, y, _seam_sample(height, x, y, left, bottom)))
    for j in range(count - 1):
        for i in range(count - 1):
            x, y = left + (i + 0.5) * step, bottom + (j + 0.5) * step
            if any(contains(hole, x, y) for hole in shafts):
                continue
            a = j * count + i
            tris.extend(
                ((a, a + 1, a + count + 1), (a, a + count + 1, a + count))
            )
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(points, [], tris)
    mesh.update()
    paint_land(
        mesh,
        stage.materials,
        [0] * len(tris),
        lambda x, y: _ground_colour(atlas, height, x, y),
    )

    def normal(x, y):
        dx, dy = ground_gradient(height, x, y, 2.5)
        return Vector((-dx, -dy, 1)).normalized()

    mesh.normals_split_custom_set_from_vertices(
        [
            _seam_sample(normal, x, y, left, bottom).normalized()
            for x, y, _ in points
        ]
    )
    obj = bpy.data.objects.new(name, mesh)
    stage.collection.objects.link(obj)
    obj.parent = stage.root
    obj["settlement_part"] = "atlas_terrain"
    obj["atlas_tile"] = name
    return mesh, points, tris


def _water(stage, atlas, cell, points, tris):
    tags = [atlas.potential_water(x, y) for x, y, z in points]
    features = {f["id"]: f for f in atlas.water_features}
    groups = {}
    for indices in tris:
        bodies = {tags[i][1] for i in indices if tags[i]}
        for name in bodies:
            feature = features[name]
            rows = []
            seasonal = feature["kind"] == "CANYON"
            edge = 0.26 if seasonal else 1
            for x, y, z in (points[i] for i in indices):
                r, h = atlas.water_shape(feature, x, y)
                h += 2.2 if seasonal else 0
                rows.append((x, y, h + 0.009, min(h - z, (edge - r) * 13)))
            clipped = _clip_water(rows)
            if len(clipped) < 3:
                continue
            xyz, faces, colours, lookup = groups.setdefault(
                name, ([], [], [], {})
            )
            kind = (
                "SEA"
                if feature["kind"] == "SEA"
                else "RIVER"
                if feature["kind"] == "RIVER"
                else "LAKE"
            )
            local = []
            for x, y, z, sign in clipped:
                key = (round(x, 5), round(y, 5), round(z, 5))
                if key not in lookup:
                    lookup[key] = len(xyz)
                    xyz.append((x, y, z))
                    colours.append(_water_colour(kind, sign))
                local.append(lookup[key])
            for i in range(1, len(local) - 1):
                faces.append((local[0], local[i], local[i + 1]))
    for name, (xyz, faces, colours, _) in groups.items():
        label = f"Water_{name}_{cell[0]}_{cell[1]}"
        mesh = bpy.data.meshes.new(label)
        mesh.from_pydata(xyz, [], faces)
        mesh.materials.append(stage.materials["world_water"])
        mesh.update()
        color = mesh.color_attributes.new(
            name="Color", type="FLOAT_COLOR", domain="POINT"
        )
        color.data.foreach_set("color", [c for rgba in colours for c in rgba])
        uv = mesh.uv_layers.new(name="UVMap")
        uv.data.foreach_set(
            "uv",
            [
                c
                for loop in mesh.loops
                for c in (
                    xyz[loop.vertex_index][0] / 4,
                    xyz[loop.vertex_index][1] / 4,
                )
            ],
        )
        ob = bpy.data.objects.new(label, mesh)
        stage.collection.objects.link(ob)
        ob.parent = stage.root
        ob["atlas_effect"], ob["water_id"] = "WATER", name
        ob["settlement_part"], ob["collision_enabled"] = "world_water", False


def _roads(stage, atlas, land, cell, paths, ground):
    a, b = atlas.corner(*cell)
    bounds = (a, b, a + TILE, b + TILE)
    batch = stage.batch(f"Roads_{cell[0]}_{cell[1]}")
    piers = stage.batch(f"RoadSupports_{cell[0]}_{cell[1]}")
    rendered = set()
    segments = routes_in_bounds(paths, bounds)
    for road, start, end in sorted(
        segments, key=lambda item: -item[0]["width"]
    ):
        key = tuple(
            sorted(tuple(round(v, 3) for v in p) for p in (start, end))
        )
        if key in rendered:
            continue
        rendered.add(key)
        segment = clip_segment(start, end, bounds)
        if not segment:
            continue
        p, q = map(Vector, segment)
        run = math.hypot(q.x - p.x, q.y - p.y)
        if run < 0.02:
            continue
        across = (
            Vector((-(q.y - p.y) / run, (q.x - p.x) / run, 0))
            * road["width"]
            * 0.5
        )
        n = max(1, math.ceil(run / 2.5))
        colour = "alley" if road["kind"] in ("TRAIL", "REGIONAL") else "road"
        for i in range(n):
            v, w = p.lerp(q, i / n), p.lerp(q, (i + 1) / n)
            mid = v.lerp(w, 0.5)
            water = atlas.water_at(mid.x, mid.y)
            roof = water is not None
            gap = mid.z - land.height(mid.x, mid.y)
            elevated = roof or gap > 0.8
            offset = 0.048 if elevated else 0.108
            corners = [v + across, w + across, w - across, v - across]
            for corner in corners:
                if not elevated:
                    hit, _, _, _ = ground.ray_cast(
                        (corner.x, corner.y, corner.z + 100), (0, 0, -1), 200
                    )
                    if hit is not None:
                        corner.z = max(corner.z, hit.z)
                corner.z += offset
            batch.prism(
                corners, (0, 0, -0.19), "stair_wood" if roof else colour
            )
            if elevated and i % 3 == 0:
                zs = atlas.terrain(mid.x, mid.y)
                if mid.z - zs > 0.16:
                    for off in (-0.71, 0.71):
                        x, y = mid.x + off * across.x, mid.y + off * across.y
                        piers.box(
                            (x, y, (mid.z + zs) / 2),
                            (0.52, 0.52, mid.z - zs),
                            "castle_trim",
                        )
    stage.finish(batch, "atlas_road")
    stage.finish(piers, "bridge_piers")


def _stone(batch, x, y, z, width, rng):
    angle = rng.random() * math.tau
    rings = []
    first = len(batch.vertices)
    bias = rng.uniform(-39, 39)
    for layer, (height, scale) in enumerate(
        ((-0.15, 0.79), (0.14, 1), (0.55, 0.58))
    ):
        ring = []
        for k in range(8):
            yaw = angle + k * math.tau / 8
            u, v = math.cos(yaw), math.sin(yaw)
            t = noise(Vector((u * 2 + bias, v * 2, layer * 0.91)))
            ring.append(
                (
                    x + (u * scale + t * 0.16) * width,
                    y + (v * scale * 0.77 + t * 0.10) * width,
                    z + (height + t * 0.15) * width,
                )
            )
        rings.append(ring)
        batch.vertices.extend(ring)
    faces = [tuple(reversed(range(8))), tuple(range(16, 24))]
    for ring_start in (0, 8):
        faces.extend(
            (
                ring_start + i,
                ring_start + (i + 1) % 8,
                ring_start + (i + 1) % 8 + 8,
                ring_start + i + 8,
            )
            for i in range(8)
        )
    batch.faces.extend(tuple(first + i for i in face) for face in faces)
    batch.face_materials.extend(
        [batch.material_indices["rock_light"]] * len(faces)
    )


def _nature(stage, atlas, land, cell, mesh, tree, shafts, meadow=None):
    seed = stable_seed(atlas.seed, cell, "nature")
    left, bottom = atlas.corner(*cell)
    bounds = (left, bottom, left + TILE, bottom + TILE)
    rng = random.Random(seed)
    crowns = stage.batch(f"Crown_{cell}")
    crown_weights = []
    trunks = stage.batch(f"Trunks_{cell}")
    stone = stage.batch(f"Rocks_{cell}", 0.035)

    def reserved(x, y):
        if any(contains(rect, x, y) for rect in shafts):
            return True
        district = land.district(x, y)
        if district and any(
            contains(p["bounds"], x, y) for p in district["places"]
        ):
            return True
        if district and contains(district["plaza"]["bounds"], x, y):
            return True
        return any(
            segment_projection((x, y), a, b)[0] < width / 2 + 1.3
            for i in land.path_index.query((x, y), 6)
            for width, a, b in (land.paths[i],)
        )

    for i in range(110):
        x, y = left + rng.random() * TILE, bottom + rng.random() * TILE
        if atlas.water_at(x, y) or reserved(x, y):
            continue
        z = land.height(x, y)
        climate = atlas.region_weights(x, y)[0][1]
        slope = math.hypot(*ground_gradient(land.height, x, y, 2.8))
        canopy = {
            "FOREST": 0.76,
            "PLAIN": 0.14,
            "MOUNTAIN": 0.18,
            "SNOW": 0.045,
            "DESERT": 0.009,
            "MARSH": 0.33,
            "COAST": 0.10,
            "MEDITERRANEAN": 0.19,
        }[climate]
        if rng.random() < canopy and slope < 0.72:
            height = rng.uniform(3.4, 8.2) * (
                1 - 0.35 * smoothstep(850, 1580, z)
            )
            if z > 1510:
                height *= 0.57
            cylinder(
                trunks,
                (x, y, z - 0.18),
                0.047 * height,
                height * 0.67,
                "wood",
                9,
            )
            begin = len(crowns.vertices)
            add_conifer_crown(crowns, (x, y, z), height, "leaves", rng)
            crown_weights.extend(
                min(1.0, max(0.0, (p[2] - z) / height)) ** 1.6
                for p in crowns.vertices[begin:]
            )
        elif i % 6 == 0 and slope < 1.4:
            _stone(stone, x, y, z, rng.uniform(0.28, 1.8), rng)
    if crown := stage.finish(crowns, "world_woodland", effect="CROWN"):
        uv = crown.data.uv_layers.active.data
        for loop, item in zip(crown.data.loops, uv, strict=True):
            item.uv.y = crown_weights[loop.vertex_index]
    stage.finish(trunks, "world_tree_trunks")
    stage.finish(stone, "natural_stone")

    spacing = 2.85
    grid = grass_cells(bounds, spacing)
    short = (
        (x, y, 0.16 + 0.15 * growth, angle)
        for x, y, growth, angle, chance in grass_samples(
            grid, spacing, atlas.seed
        )
        if left <= x < left + TILE
        and bottom <= y < bottom + TILE
        and chance < 0.44 + growth * 0.29
        and not reserved(x, y)
    )
    gx, gy = left + 97 + (seed % 53), bottom + 107 + (seed % 37)
    radius, spacing = 16, 0.57
    if meadow:
        gx, gy = meadow
        radius, spacing = 36, 0.49
    patch = grass_cells(
        (
            max(left, gx - radius),
            max(bottom, gy - radius),
            min(left + TILE, gx + radius),
            min(bottom + TILE, gy + radius),
        ),
        spacing,
    )
    long = (
        (x, y, 0.36 + 0.50 * growth, angle)
        for x, y, growth, angle, chance in grass_samples(
            patch, spacing, atlas.seed
        )
        if left <= x < left + TILE
        and bottom <= y < bottom + TILE
        and chance
        < (0.71 + growth * 0.24)
        * (1 - smoothstep(radius * 0.54, radius, math.dist((x, y), (gx, gy))))
        and not reserved(x, y)
    )

    def grass_finish(batch, collection, root, role):
        return stage.finish(batch, role, effect="GRASS")

    build_grass_meshes(
        chain(short, long),
        mesh,
        tree,
        atlas.seed,
        stage.collection,
        stage.root,
        stage.materials,
        grass_finish,
        chunk_size=32,
        simple=stage.game,
    )


def _district(stage, land, site, cells, atlas):
    uid = site["id"]
    junction = stage.node(uid, site["centre"], "SETTLEMENT")
    if (port := site.get("waterfront")) and atlas.cell(
        *port["head"][:2]
    ) in cells:
        _waterfront(stage, port, junction)
    if tuple(site["tile"]) in cells:
        plaza(stage, site)
        stage.edge(junction, site["plaza"]["id"])
        surface = stage.batch(uid + "_plaza_surface")
        x, y, z = site["plaza"]["centre"]
        w, d = site["plaza"]["size"]
        surface.box((x, y, z - 0.02), (w, d, 0.28), "court_paving")
        stage.finish(surface, "plaza")
    for place in site["places"]:
        if atlas.cell(*place["centre"][:2]) not in cells:
            continue
        role = place["kind"]
        if role == "HOUSE":
            entry = house(stage, site, place)
        elif role == "CASTLE":
            entry = castle(stage, place, land)
        else:
            entry = institution(stage, place)
        foot = stage.nodes[entry]["position"]
        segments = (
            (r, a, b)
            for r in site["streets"]
            for a, b in pairwise(r["points"])
        )
        _, _, waypoint = min(
            (distance, r["id"], p)
            for r, a, b in segments
            for distance, _, p in (segment_projection(foot, a, b),)
        )
        px, py = waypoint[:2]
        door = stage.node(
            place["id"] + "_lane", (px, py, land.height(px, py)), "ACCESS_LANE"
        )
        stage.edge(door, entry)
        # Split the approach at the axial street.
        x, y, z = site["centre"]
        stage.edge(
            junction,
            door,
            ((x, y, z), (x, py, z), (px, py, land.height(px, py))),
        )


def _waterfront(stage, port, junction):
    uid = port["id"]
    head, tip = map(Vector, (port["head"], port["tip"]))
    aim = (tip - head).normalized()
    across = Vector((-aim.y, aim.x, 0)) * port["width"] / 2
    batch = stage.batch(uid, 0.014)
    batch.prism(
        (head + across, head - across, tip - across, tip + across),
        (0, 0, -0.25),
        "stair_wood",
    )
    for t in (0.18, 0.48, 0.74, 0.96):
        for side in (-0.84, 0.84):
            p = head.lerp(tip, t) + across * side
            batch.box((p.x, p.y, p.z - 2.45), (0.38, 0.38, 5.2), "timber")
    stage.finish(batch, "waterfront")
    kind = "DOCK" if port["kind"] != "SPRING" else "SPRING"
    landing = stage.node(uid, tip, kind)
    stage.edge(junction, landing, (*port["access"]["points"], tuple(tip)))
    stage.marker(
        uid + "_anchor",
        "BOAT_STOP" if kind == "DOCK" else "OASIS_SPRING",
        tip,
        (2, 4, 1),
        water_id=port["water_id"],
    )


def choose_tiles(atlas, plan, selector, district=None):
    if selector:
        cells = {tuple(map(int, t.split(","))) for t in selector}
    elif district:
        matches = [s for s in plan["sites"] if s["id"] == district]
        if matches:
            bounds = matches[0]["graded_bounds"]
            a, b = atlas.cell(bounds[0] - 10, bounds[1] - 23)
            c, d = atlas.cell(bounds[2] + 10, bounds[3] + 18)
            cells = {(i, j) for i in range(a, c + 1) for j in range(b, d + 1)}
            if port := matches[0].get("waterfront"):
                cells.update(
                    atlas.cell(*p[:2]) for p in port["access"]["points"]
                )
                cells.add(atlas.cell(*port["tip"][:2]))
        else:
            dungeon = next(
                (d for d in plan["dungeons"] if d["id"] == district), None
            )
            if dungeon is None:
                raise ValueError(f"Unknown atlas district/dungeon: {district}")
            cells = {tuple(dungeon["tile"])}
    else:
        target = default_focus(plan)
        if target is None:
            return {(atlas.shape[0] // 2, atlas.shape[1] // 2)}
        return choose_tiles(atlas, plan, (), target)
    if any(
        len(t) != 2
        or not all(0 <= x < n for x, n in zip(t, atlas.shape, strict=True))
        for t in cells
    ):
        raise ValueError("Atlas tile outside the map")
    return cells


def build_atlas(
    atlas, plan, cells, *, lod=0, meadow=None, backdrop=(), game=False
):
    collection = bpy.data.collections.new(
        plan.get("title", "Procedural Atlas")
    )
    bpy.context.scene.collection.children.link(collection)
    root = bpy.data.objects.new("Atlas_Tiles", None)
    collection.objects.link(root)
    towns._owned(root, uuid.uuid4().hex)
    materials = towns._materials(root[towns.GENERATION_KEY])
    stage = Buildings(collection, root, materials, game=game)
    land = Landscape(atlas, plan)
    paths = atlas_paths(plan)
    for cell in sorted(cells.union(backdrop)):
        shafts = [d["shaft"] for d in plan["dungeons"] if d["tile"] == cell]
        detailed = cell in cells and not lod
        step = 4 if detailed or shafts else 8
        mesh, points, tris = terrain_mesh(
            stage, atlas, land, cell, shafts, step
        )
        ground = BVHTree.FromPolygons(points, tris, all_triangles=True)
        _water(stage, atlas, cell, points, tris)
        _roads(stage, atlas, land, cell, paths, ground)
        if detailed:
            _nature(stage, atlas, land, cell, mesh, ground, shafts, meadow)
    for site in plan["sites"]:
        port = site.get("waterfront")
        if (
            tuple(site["tile"]) in cells
            or (port and atlas.cell(*port["head"][:2]) in cells)
            or any(
                atlas.cell(*p["centre"][:2]) in cells for p in site["places"]
            )
        ):
            _district(stage, land, site, cells, atlas)
    for route in plan["routes"]:
        a, b = route["from"], route["to"]
        if a in stage.nodes and b in stage.nodes:
            stage.edge(a, b, route["points"])
    for spec in plan["dungeons"]:
        if spec["tile"] in cells:
            entry = dungeon(stage, spec)
            trail = spec["trail"]
            approach = stage.node(spec["id"] + "_trail", trail[0], "TRAILHEAD")
            stage.edge(approach, entry, trail)
    root["plan_json"] = json.dumps(
        {"navigation": stage.navigation()}, ensure_ascii=False
    )
    root["atlas_tile_ids"] = json.dumps(sorted(cells))
    bpy.context.view_layer.update()
    return collection, root


def meadow_view(atlas, plan, district):
    site = next((s for s in plan["sites"] if s["id"] == district), None)
    if site is None:
        raise ValueError("The meadow camera needs a settlement ID")
    land = Landscape(atlas, plan)
    cx, cy, z = site["centre"]
    best = None
    for d in (210, 250, 300, 365, 425):
        for i in range(32):
            a = math.tau * i / 32
            x, y = cx + d * math.cos(a), cy + d * math.sin(a)
            if any(
                abs(v) + 60 > n / 2
                for v, n in zip((x, y), atlas.size, strict=True)
            ):
                continue
            points = (
                (x + u, y + v) for u in (-28, 0, 28) for v in (-28, 0, 28)
            )
            candidates = tuple(points)
            if any(
                atlas.water_at(*p) or land.district(*p) for p in candidates
            ):
                continue
            heights = [land.height(*p) for p in candidates]
            relief = max(heights) - min(heights)
            row = (4 * relief + d * 0.025 + abs(heights[4] - z) * 0.3, x, y)
            if best is None or row < best:
                best = row
    if best is None:
        raise ValueError(f"{district}: no dry meadow beside this settlement")
    return best[1:]


def preview(
    collection, root, atlas, plan, cells, district=None, *, meadow=None
):
    scene = bpy.context.scene
    site = next((s for s in plan["sites"] if s["id"] == district), None)
    cave = next((s for s in plan["dungeons"] if s["id"] == district), None)
    land = Landscape(atlas, plan)
    water = next(
        (
            m
            for m in bpy.data.materials
            if m.get(towns.GENERATION_KEY) == root[towns.GENERATION_KEY]
            and m.name.split(".", 1)[0] == "Settlement_water"
        ),
        None,
    )
    if water:
        basin = MeshBatch("Civic water preview", {"water": water})
        for point in json.loads(root["plan_json"])["navigation"][
            "points_of_interest"
        ]:
            if point["kind"] in ("WELL_WATER", "FOUNTAIN_WATER"):
                cylinder(
                    basin,
                    point["position"],
                    point["size"][0] / 2,
                    0.015,
                    "water",
                    24,
                )
        towns._finish(basin, collection, root, "preview")
    if meadow:
        x, y = meadow
        dx, dy = site["centre"][0] - x, site["centre"][1] - y
        aim = Vector((dx, dy, 0)).normalized()
        camera_xy = x - aim.x * 11, y - aim.y * 11
        z = land.height(*camera_xy)
        target = Vector((x + aim.x * 28, y + aim.y * 28, z + 2.0))
        framing = 42
    elif site:
        x, y, z = site["centre"]
        framing = (
            315
            if site.get("grand_capital") or site["extent_m"][0] >= 800
            else 135
        )
        target = Vector((x, y + framing * 0.165, z + 2))
    elif cave:
        x, y, z = cave["rooms"][0]["centre"]
        framing = 34
        target = Vector((x, y - 8, z + 1.45))
    else:
        x, y = atlas.centre(*min(cells))
        target = Vector((x, y, land.height(x, y)))
        framing = 300
    camera_data = bpy.data.cameras.new("Atlas Camera")
    camera = bpy.data.objects.new(camera_data.name, camera_data)
    collection.objects.link(camera)
    camera.parent = root
    camera["settlement_part"] = "preview"
    if meadow:
        camera.location = (*camera_xy, z + 1.69)
    elif cave:
        camera.location = (x + 0.65, y + 2.7, z + 1.65)
    else:
        camera.location = target + Vector((0.48, -0.94, 0.65)) * framing
    camera.rotation_euler = (
        (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    )
    camera_data.type = "PERSP" if cave or meadow else "ORTHO"
    if cave or meadow:
        camera_data.lens = 28
    camera_data.ortho_scale = framing
    camera_data.clip_end = 1600
    scene.camera = camera
    sun_data = bpy.data.lights.new("Atlas Sun", "SUN")
    sun = bpy.data.objects.new(sun_data.name, sun_data)
    collection.objects.link(sun)
    sun["settlement_part"] = "preview"
    sun.rotation_euler = (
        Vector((0.57, 0.68, -0.84)).to_track_quat("-Z", "Y").to_euler()
    )
    sun_data.energy, sun_data.color, sun_data.angle = (
        2.7,
        (1, 0.91, 0.76),
        math.radians(6),
    )
    _preview_sky(scene)
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 16
    scene.render.resolution_x, scene.render.resolution_y = 1280, 840
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "AgX"
