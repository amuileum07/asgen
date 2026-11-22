"""Reusable civic props and terrain-conforming vegetation."""

import math
import random
from dataclasses import replace

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from castle_blender import _pointed_roof
from castle_roof_rules import RoofSpec
from civic_rules import grass_sites, meadow_growth
from fortification_blender import cylinder
from house_generator import MeshBatch, _linear_color
from terrain_rules import value_noise
from tree_blender import tree_stem


def _face(batch, points, material):
    start = len(batch.vertices)
    batch.vertices.extend(tuple(p) for p in points)
    batch.faces.append(tuple(range(start, len(batch.vertices))))
    batch.face_materials.append(batch.material_indices[material])


def _lathe(batch, profile, material, sides=16, *, origin=(0, 0, 0)):
    x, y, z = origin
    rings = []
    for radius, height in profile:
        if radius == 0:
            rings.append([(x, y, z + height)])
        else:
            rings.append(
                [
                    (
                        x + radius * math.cos(i * math.tau / sides),
                        y + radius * math.sin(i * math.tau / sides),
                        z + height,
                    )
                    for i in range(sides)
                ]
            )
    for a, b in zip(rings, rings[1:], strict=False):
        for i in range(sides):
            if len(a) == len(b) == 1:
                continue
            points = (
                [a[0], b[(i + 1) % sides], b[i]]
                if len(a) == 1
                else [a[i], a[(i + 1) % sides], b[0]]
                if len(b) == 1
                else [a[i], a[(i + 1) % sides], b[(i + 1) % sides], b[i]]
            )
            _face(batch, points, material)


def _tube(batch, points, radius, material, sides=8):
    rings = []
    points = [Vector(p) for p in points]
    for i, p in enumerate(points):
        direction = (
            points[min(i + 1, len(points) - 1)] - points[max(0, i - 1)]
        ).normalized()
        axis = (
            Vector((0, 0, 1)) if abs(direction.z) < 0.9 else Vector((1, 0, 0))
        )
        u = direction.cross(axis).normalized()
        v = direction.cross(u).normalized()
        rings.append(
            [
                p
                + radius
                * (
                    u * math.cos(j * math.tau / sides)
                    + v * math.sin(j * math.tau / sides)
                )
                for j in range(sides)
            ]
        )
    _face(batch, list(reversed(rings[0])), material)
    _face(batch, rings[-1], material)
    for a, b in zip(rings, rings[1:], strict=False):
        for i in range(sides):
            j = (i + 1) % sides
            _face(batch, [a[i], a[j], b[j], b[i]], material)


def _well(body, roof, water, params):
    sides = params["segments"]
    _lathe(
        body,
        [
            (0, -0.16),
            (1.14, -0.16),
            (1.18, 0.08),
            (1.08, 0.16),
            (1.08, 0.83),
            (1.18, 0.86),
            (1.18, 1.0),
            (0.87, 1.0),
            (0.87, 0.20),
            (0, 0.20),
        ],
        "stone_light",
        sides,
    )
    cylinder(water, (0, 0, 0.22), 0.85, 0.018, "well_water", sides)
    for x in (-1.32, 1.32):
        body.box((x, 0, 1.20), (0.16, 0.20, 2.4), "wood")
        body.box((x, 0, 0.06), (0.30, 0.33, 0.40), "stone")
    _tube(body, [(-1.4, 0, 1.92), (1.4, 0, 1.92)], 0.11, "wood")
    _tube(
        body,
        [(1.45, 0, 1.92), (1.45, 0, 1.62), (1.65, 0, 1.62)],
        0.045,
        "iron",
    )
    _tube(body, [(0, 0, 1.93), (0, 0, 0.65)], 0.016, "rope", 6)
    if params["roof"] == "PYRAMID_4":
        _pointed_roof(
            roof,
            RoofSpec("well", (0, 0), 2.40, 3.4, 2.9, 0.75, "PYRAMID_4", 4),
            "castle_slate",
        )
    else:
        for sign in (-1, 1):
            roof.prism(
                [
                    (0, -1.45, 3.15),
                    (sign * 1.7, -1.45, 2.40),
                    (sign * 1.7, 1.45, 2.40),
                    (0, 1.45, 3.15),
                ],
                (0, 0, -0.10),
                "castle_slate",
            )
    body.box((0, 0, 2.35), (2.9, 0.20, 0.18), "wood")


def _fountain(body, water, params):
    sides, tiers = params["segments"], params["tiers"]
    _lathe(
        body,
        [
            (0, -0.18),
            (1.67, -0.18),
            (1.72, 0.10),
            (1.62, 0.18),
            (1.62, 0.62),
            (1.72, 0.66),
            (1.72, 0.79),
            (1.43, 0.79),
            (1.34, 0.65),
            (1.34, 0.22),
            (0, 0.22),
        ],
        "stone_light",
        sides,
    )
    cylinder(water, (0, 0, 0.57), 1.335, 0.025, "water", sides)
    _lathe(
        body,
        [
            (0, 0.20),
            (0.45, 0.20),
            (0.45, 0.42),
            (0.26, 0.58),
            (0.20, 2.58),
            (0.32, 2.68),
            (0.24, 2.86),
            (0, 3.02),
        ],
        "stone_light",
        sides,
    )
    for i in range(tiers - 1):
        z = 1.50 + i * 0.74
        r = 0.83 - i * 0.24
        _lathe(
            body,
            [
                (0, z - 0.24),
                (r * 0.60, z - 0.24),
                (r, z - 0.08),
                (r, z + 0.10),
                (r - 0.10, z + 0.10),
                (r - 0.18, z - 0.06),
                (0, z - 0.06),
            ],
            "stone_light",
            sides,
        )
        cylinder(water, (0, 0, z + 0.035), r - 0.13, 0.02, "water", sides)
    for i in range(4):
        angle = i * math.tau / 4 + math.pi / 4
        stream = [
            (
                math.cos(angle) * (0.16 + 1.04 * t),
                math.sin(angle) * (0.16 + 1.04 * t),
                2.86 + 0.48 * t - 2.75 * t * t,
            )
            for t in (j / 10 for j in range(11))
        ]
        _tube(water, stream, 0.025, "water", 6)


def _lamp(body, glow, params):
    _lathe(
        body,
        [
            (0, -0.16),
            (0.26, -0.16),
            (0.29, 0.12),
            (0.20, 0.22),
            (0.17, 0.52),
            (0.10, 0.65),
            (0.075, 3.30),
            (0.13, 3.37),
            (0.08, 3.46),
            (0, 3.50),
        ],
        "iron",
        12,
    )
    lights = []
    for sign in (-1, 1) if params["arms"] == 2 else (-1,):
        curve = [
            (sign * x, 0, z)
            for x, z in (
                (0, 3.30),
                (0.20, 3.60),
                (0.48, 3.76),
                (0.77, 3.72),
                (0.96, 3.54),
                (0.96, 3.35),
            )
        ]
        _tube(body, curve, 0.045, "iron")
        x, base = sign * 0.96, 2.76
        # Solid glass panes are opaque emissive meshes, not collision.
        cylinder(
            glow,
            (x, 0, base + 0.10),
            0.19,
            0.48,
            "lantern_glow",
            params["lantern_sides"],
        )
        for z, radius, height in (
            (base, 0.25, 0.10),
            (base + 0.58, 0.27, 0.09),
        ):
            cylinder(
                body,
                (x, 0, z),
                radius,
                height,
                "iron",
                params["lantern_sides"],
            )
        for i in range(params["lantern_sides"]):
            angle = i * math.tau / params["lantern_sides"]
            body.beam(
                (x + 0.21 * math.cos(angle), 0.21 * math.sin(angle), base),
                (
                    x + 0.21 * math.cos(angle),
                    0.21 * math.sin(angle),
                    base + 0.65,
                ),
                0.035,
                "iron",
            )
        _pointed_roof(
            body,
            RoofSpec(
                "lantern",
                (x, 0),
                base + 0.67,
                0.62,
                0.62,
                0.23,
                "PYRAMID_4",
                4,
            ),
            "iron",
        )
        lights.append((x, 0, base + 0.34))
    return lights


def project_assets(plan, mesh):
    bvh = BVHTree.FromPolygons(
        [v.co for v in mesh.vertices], [p.vertices for p in mesh.polygons]
    )
    cast = ground_cast(mesh, bvh)
    result = []
    for asset in plan.civic_assets:
        samples = [asset.position[:2]]
        if asset.kind in ("WELL", "FOUNTAIN"):
            samples += [
                (
                    asset.position[0]
                    + asset.radius * math.cos(i * math.tau / 8),
                    asset.position[1]
                    + asset.radius * math.sin(i * math.tau / 8),
                )
                for i in range(8)
            ]
        heights = []
        for x, y in samples:
            hit, *_ = cast(x, y)
            if hit is not None:
                heights.append(hit.z)
        if heights:
            result.append(
                replace(asset, position=(*asset.position[:2], max(heights)))
            )
    return tuple(result), bvh


def build_civic(plan, collection, root, materials, finish, owned):
    cache = {}
    for asset in plan.civic_assets:
        marker = bpy.data.objects.new(asset.id + "_" + asset.kind, None)
        collection.objects.link(marker)
        owned(marker)
        marker.parent = root
        marker.location = asset.position
        marker.rotation_euler.z = asset.heading
        marker.scale = (asset.scale,) * 3
        marker["settlement_part"] = "civic_anchor"
        marker["civic_id"], marker["civic_kind"] = asset.id, asset.kind
        marker["reserved_size"] = asset.size
        marker["asset_origin"] = "BOTTOM_CENTER"
        marker["variant"] = asset.variant
        if asset.kind == "STATUE_ANCHOR":
            marker["engine_asset_anchor"] = True
            marker.empty_display_type = "PLAIN_AXES"
            volume = bpy.data.objects.new(asset.id + "_ReservedVolume", None)
            collection.objects.link(volume)
            owned(volume)
            volume.parent = marker
            volume.empty_display_type = "CUBE"
            volume.empty_display_size = 1
            volume.location.z = asset.size[2] / (2 * asset.scale)
            volume.scale = tuple(v / (2 * asset.scale) for v in asset.size)
            volume["settlement_part"] = "asset_reservation"
            continue
        key = (
            asset.kind,
            asset.variant,
            tuple(sorted(asset.parameters.items())),
        )
        if key not in cache:
            body = MeshBatch(asset.kind, materials)
            surface = MeshBatch(asset.kind + "_Surface", materials)
            canopy = MeshBatch(asset.kind + "_Canopy", materials)
            lights = []
            if asset.kind == "WELL":
                _well(body, canopy, surface, asset.parameters)
            elif asset.kind == "FOUNTAIN":
                _fountain(body, surface, asset.parameters)
            else:
                lights = _lamp(body, surface, asset.parameters)
            blocks = []
            for batch, role, collides in (
                (body, "civic_geometry", True),
                (canopy, "civic_canopy", True),
                (surface, "civic_effect", False),
            ):
                obj = finish(batch, collection, marker, role)
                if obj:
                    obj["collision_enabled"] = collides
                    obj["civic_id"] = asset.id
                    for p in obj.data.polygons:
                        p.use_smooth = True
                    obj.data.set_sharp_from_angle(angle=math.radians(35))
                    blocks.append((obj.data, role, collides))
            cache[key] = blocks, lights
        else:
            for data, role, collides in cache[key][0]:
                obj = bpy.data.objects.new(asset.id + "_" + role, data)
                collection.objects.link(obj)
                obj.parent = marker
                owned(obj)
                obj["settlement_part"] = role
                obj["collision_enabled"] = collides
                obj["civic_id"] = asset.id
        for i, point in enumerate(cache[key][1]):
            data = bpy.data.lights.new(asset.id + f"_Light_{i}", "POINT")
            data.energy, data.color, data.shadow_soft_size = (
                32,
                (1, 0.64, 0.29),
                0.20,
            )
            obj = bpy.data.objects.new(data.name, data)
            collection.objects.link(obj)
            obj.parent, obj.location = marker, point
            owned(obj)
            obj["settlement_part"] = "civic_light"
            obj["light_range"] = 9.0 * asset.scale
        if asset.kind == "FOUNTAIN":
            marker["effect_anchor"] = "FOUNTAIN_WATER"
            marker["effect_height"] = 2.86


def ground_cast(mesh, bvh):
    top = max(v.co.z for v in mesh.vertices) + 2
    depth = top - min(v.co.z for v in mesh.vertices) + 2

    def cast(x, y):
        return bvh.ray_cast(Vector((x, y, top)), Vector((0, 0, -1)), depth)

    return cast


def _leaf_cluster(batch, centre, radius, depth, turn, material, rng, rounded):
    first = len(batch.vertices)
    sides = 6
    profile = (
        ((0.60, -0.39), (1.0, -0.02), (0.65, 0.33))
        if rounded
        else ((0.64, -0.42), (1.0, -0.20), (0.49, 0.26))
    )
    rings = len(profile)
    for side in range(sides):
        angle = turn + side * math.tau / sides
        reach = radius * rng.uniform(0.80, 1.16)
        dz = depth * rng.uniform(-0.14, 0.14)
        for ring, (scale, level) in enumerate(profile):
            yaw = angle + (ring - 1) * 0.12
            batch.vertices.append(
                (
                    centre.x + math.cos(yaw) * reach * scale,
                    centre.y + math.sin(yaw) * reach * scale,
                    centre.z + depth * level + dz,
                )
            )
    bottom = len(batch.vertices)
    batch.vertices.append((centre.x, centre.y, centre.z - depth * 0.54))
    batch.vertices.append(
        (
            centre.x + radius * 0.18 * math.cos(turn),
            centre.y + radius * 0.18 * math.sin(turn),
            centre.z + depth * (0.52 if rounded else 0.68),
        )
    )
    slot = batch.material_indices[material]
    for side in range(sides):
        a = first + side * rings
        b = first + (side + 1) % sides * rings
        batch.faces.append((bottom, b, a))
        batch.faces.extend(
            (a + j, b + j, b + j + 1, a + j + 1) for j in range(rings - 1)
        )
        batch.faces.append((a + rings - 1, b + rings - 1, bottom + 1))
        batch.face_materials.extend([slot] * (rings + 1))


def add_tree(
    crowns,
    trunks,
    branches,
    base,
    height,
    material,
    rng,
    *,
    broadleaf_chance,
    library=None,
):
    """Add a tapered trunk, branching limbs and an irregular crown."""
    turn = rng.uniform(0, math.tau)
    spread = rng.uniform(0.84, 1.13)
    lean = Vector((rng.uniform(-0.09, 0.09), rng.uniform(-0.09, 0.09), 0))
    detail = random.Random(rng.uniform(-80, 80))
    tier_jitter = [rng.uniform(-0.025, 0.025) for _ in range(3)]
    broadleaf = detail.random() < broadleaf_chance
    if library is not None:
        library.plant(base, height, turn, spread, broadleaf, detail, material)
        return
    origin = Vector(base)
    up = Vector((0, 0, 1))
    bend = Vector((-lean.y, lean.x, 0)) * 0.46

    def stem(level):
        return origin + height * (
            up * level + lean * level**2 + bend * math.sin(level * math.pi)
        )

    width = height * (0.050 if broadleaf else 0.038)
    tree_stem(
        trunks,
        [stem(level) for level in (-0.04, 0.09, 0.39, 0.79)],
        [width * scale for scale in (1.12, 0.79, 0.62, 0.24)],
        turn,
        6,
    )
    if broadleaf:
        limbs = (
            (0.35, 0.61, 0.22, 0.17, 0.23),
            (0.44, 0.67, 0.27, 0.18, 0.26),
            (0.48, 0.64, 0.23, 0.16, 0.23),
            (0.55, 0.76, 0.22, 0.19, 0.25),
            (0.62, 0.82, 0.17, 0.16, 0.23),
        )
        tip_radius, tip_depth = 0.18, 0.23
    else:
        limbs = (
            (0.33, 0.40, 0.23, 0.17, 0.23),
            (0.37, 0.43, 0.21, 0.16, 0.22),
            (0.47, 0.55, 0.18, 0.15, 0.25),
            (0.52, 0.59, 0.16, 0.14, 0.23),
            (0.62, 0.70, 0.13, 0.13, 0.27),
            (0.67, 0.74, 0.10, 0.12, 0.26),
        )
        tip_radius, tip_depth = 0.12, 0.29
    for i, (start, end, reach, radius, depth) in enumerate(limbs):
        angle = turn + i * 2.39996 + detail.uniform(-0.24, 0.24)
        direction = Vector((math.cos(angle), math.sin(angle), 0))
        end += tier_jitter[i % 3]
        base_point = stem(start)
        tip = stem(end) + direction * (height * reach * spread)
        if i < (4 if broadleaf else 3):
            elbow = base_point.lerp(tip, 0.53) - up * (height * 0.032)
            tree_stem(
                branches,
                [base_point, elbow, tip],
                [width * 0.43, width * 0.27, width * 0.085],
                angle + math.pi / 2,
                4,
            )
        _leaf_cluster(
            crowns,
            tip,
            height * radius * spread,
            height * depth,
            angle,
            material,
            detail,
            broadleaf,
        )
    _leaf_cluster(
        crowns,
        stem(0.86),
        height * tip_radius * spread,
        height * tip_depth,
        turn,
        material,
        detail,
        broadleaf,
    )


def build_grass(
    plan, mesh, bvh, collection, root, materials, finish, *, allowed=None
):
    sites = grass_sites(plan)
    if allowed is not None:
        sites = (site for site in sites if allowed(*site[:2]))
    root["grass_tufts"] = build_grass_meshes(
        sites,
        mesh,
        bvh,
        plan.config.seed,
        collection,
        root,
        materials,
        finish,
    )


class _GrassBatch:
    """Chunked stylized grass mesh with vertex colors and normals."""

    def __init__(self, name, material):
        self.name = name
        self.material = material
        self.materials = {"grass": material}
        self.vertices = []
        self.faces = []
        self.uvs = []
        self.colors = []
        self.normals = []

    def finish(self, collection, parent):
        if not self.vertices:
            return None
        mesh = bpy.data.meshes.new(self.name)
        mesh.from_pydata(self.vertices, [], self.faces)
        mesh.materials.append(self.material)
        color_attr = mesh.color_attributes.new(
            name="Color", type="FLOAT_COLOR", domain="POINT"
        )
        color_attr.data.foreach_set(
            "color", [c for rgba in self.colors for c in rgba]
        )
        uv = mesh.uv_layers.new(name="UVMap")
        uv.data.foreach_set(
            "uv",
            [c for poly in self.faces for vi in poly for c in self.uvs[vi]],
        )
        mesh.polygons.foreach_set("use_smooth", [True] * len(self.faces))
        mesh.update()
        mesh.normals_split_custom_set_from_vertices(self.normals)
        obj = bpy.data.objects.new(self.name, mesh)
        collection.objects.link(obj)
        obj.parent = parent
        return obj


def _clamp_rgb(color):
    return tuple(min(1.0, max(0.0, c)) for c in color)


BLADE_PROFILES = {
    1: ((0.0, 0.91),),
    2: ((0.0, 0.86), (0.46, 0.67)),
    3: ((0.0, 0.82), (0.37, 1.0), (0.72, 0.48)),
}


def _add_blade(
    batch,
    base,
    forward,
    side,
    width,
    height,
    lean,
    curl,
    tones,
    up_normal,
    *,
    segments=3,
):
    """Build one tapered ribbon with its root-to-tip weight in UV V."""
    verts, faces, colors, normals, uvs = (
        batch.vertices,
        batch.faces,
        batch.colors,
        batch.normals,
        batch.uvs,
    )
    up_tuple = tuple(up_normal)
    first = len(verts)
    for (t, scale), rgb in zip(
        BLADE_PROFILES[segments], tones[:segments], strict=True
    ):
        bend = lean * t + curl * t**2.5
        centre = base + Vector((0, 0, height * t)) + forward * bend
        offset = side * (width * scale)
        verts.extend((tuple(centre - offset), tuple(centre + offset)))
        colors.extend(((*rgb, 1.0),) * 2)
        normals.extend((up_tuple,) * 2)
        uvs.extend(((0.0, t), (1.0, t)))
    tip_idx = len(verts)
    verts.append(
        tuple(base + Vector((0, 0, height)) + forward * (lean + curl))
    )
    colors.append((*tones[-1], 1.0))
    normals.append(up_tuple)
    uvs.append((0.5, 1.0))
    for a in range(first, tip_idx - 2, 2):
        faces.append((a, a + 1, a + 3, a + 2))
    faces.append((tip_idx - 2, tip_idx - 1, tip_idx))


def _ground_tint(point, indices, mesh, colours, fallback):
    if colours is None or len(indices) != 3:
        return fallback
    a, b, c = (mesh.vertices[i].co for i in indices)
    dx, dy = point.x - a.x, point.y - a.y
    ux, uy = b.x - a.x, b.y - a.y
    vx, vy = c.x - a.x, c.y - a.y
    determinant = ux * vy - uy * vx
    if abs(determinant) < 1e-8:
        return fallback
    u = (dx * vy - dy * vx) / determinant
    v = (ux * dy - uy * dx) / determinant
    low, right, left = (colours[i] for i in indices)
    return low + u * (right - low) + v * (left - low)


def _add_wildflower(
    batch, base, wind_dir, height, petal_rgb, stem_rgb, center_rgb, up_normal
):
    """Add a tiny five-petal wildflower nestled in the grass clump."""
    verts, faces, colors, normals, uvs = (
        batch.vertices,
        batch.faces,
        batch.colors,
        batch.normals,
        batch.uvs,
    )
    stem_top = base + Vector((0, 0, height)) + wind_dir * (height * 0.25)
    r = 0.006
    b_idx = len(verts)
    for k in range(3):
        a = k * math.tau / 3
        verts.append(
            tuple(base + Vector((r * math.cos(a), r * math.sin(a), 0)))
        )
        colors.append((*stem_rgb, 1.0))
        normals.append(tuple(up_normal))
        uvs.append((0.5, 0.0))
    t_idx = len(verts)
    for k in range(3):
        a = k * math.tau / 3
        verts.append(
            tuple(
                stem_top
                + Vector((r * 0.7 * math.cos(a), r * 0.7 * math.sin(a), 0))
            )
        )
        colors.append((*stem_rgb, 1.0))
        normals.append(tuple(up_normal))
        uvs.append((0.5, 1.0))
    for k in range(3):
        kn = (k + 1) % 3
        faces.append((b_idx + k, b_idx + kn, t_idx + kn, t_idx + k))

    tilt = (up_normal + wind_dir * 0.28).normalized()
    u = tilt.cross(Vector((1, 0, 0)))
    if u.length < 0.1:
        u = tilt.cross(Vector((0, 1, 0)))
    u.normalize()
    v = tilt.cross(u).normalized()

    c_top = len(verts)
    verts.append(tuple(stem_top + tilt * 0.004))
    colors.append((*center_rgb, 1.0))
    normals.append(tuple(tilt))
    uvs.append((0.5, 1.0))

    c_bot = len(verts)
    verts.append(tuple(stem_top - tilt * 0.004))
    colors.append((*stem_rgb, 1.0))
    normals.append(tuple(-tilt))
    uvs.append((0.5, 1.0))

    pr = 0.052
    for k in range(5):
        a0 = k * math.tau / 5 + 0.2
        dir_c = u * math.cos(a0) + v * math.sin(a0)
        dir_l = u * math.cos(a0 - 0.38) + v * math.sin(a0 - 0.38)
        dir_r = u * math.cos(a0 + 0.38) + v * math.sin(a0 + 0.38)
        idx = len(verts)
        verts.extend(
            (
                tuple(stem_top + dir_l * (pr * 0.62) + tilt * 0.012),
                tuple(stem_top + dir_c * pr + tilt * 0.022),
                tuple(stem_top + dir_r * (pr * 0.62) + tilt * 0.012),
            )
        )
        colors.extend(((*petal_rgb, 1.0),) * 3)
        normals.extend((tuple(tilt),) * 3)
        uvs.extend(((0.0, 1.0), (0.5, 1.0), (1.0, 1.0)))
        faces.append((c_top, idx, idx + 1, idx + 2))
        faces.append((c_bot, idx + 2, idx + 1, idx))


def build_grass_meshes(
    sites,
    mesh,
    bvh,
    seed,
    collection,
    root,
    materials,
    finish,
    *,
    chunk_size=32,
    simple=False,
):
    rng = random.Random(f"{seed}:grass-mesh")
    batches, count = {}, 0
    cast = ground_cast(mesh, bvh)
    meadow = list(mesh.materials).index(materials["terrain"])
    material_indices = [p.material_index for p in mesh.polygons]
    poly_verts = [tuple(p.vertices) for p in mesh.polygons]
    color_attr = mesh.color_attributes.get("Color")
    point_colors = (
        [Vector(c.color[:3]) for c in color_attr.data]
        if color_attr and color_attr.domain == "POINT"
        else None
    )
    fallback_rgb = Vector(
        materials["grass"].diffuse_color[:3]
        if "grass" in materials
        else _linear_color("789d57")[:3]
    )
    grass_mat = materials.get("grass_tuft") or materials["grass_blade_0"]

    mid_cool = Vector(_linear_color("70994f")[:3])
    mid_warm = Vector(_linear_color("a1b75b")[:3])
    tip_cool = Vector(_linear_color("9dbc71")[:3])
    tip_warm = Vector(_linear_color("d1d58b")[:3])
    flower_colors = (
        _linear_color("4ba7ff")[:3],
        _linear_color("f8f4e2")[:3],
        _linear_color("f6cd44")[:3],
        _linear_color("c79cff")[:3],
    )
    stem_rgb = _linear_color("355e1c")[:3]
    center_rgb = _linear_color("f5d24a")[:3]

    world_offset = root.location.copy()
    for x, y, height, angle in sites:
        point, normal, face, _ = cast(x, y)
        if (
            point is None
            or normal.z < 0.85
            or material_indices[face] != meadow
        ):
            continue
        key = math.floor(x / chunk_size), math.floor(y / chunk_size)
        if key not in batches:
            batches[key] = _GrassBatch(f"Grass_{key[0]}_{key[1]}", grass_mat)
        batch = batches[key]
        ground_vec = _ground_tint(
            point, poly_verts[face], mesh, point_colors, fallback_rgb
        )
        wx, wy = x + world_offset.x, y + world_offset.y
        growth = meadow_growth(wx, wy, seed)
        root_vec = ground_vec.lerp(mid_cool, 0.18) * 0.94
        mid_base = ground_vec.lerp(mid_cool.lerp(mid_warm, growth), 0.70)
        tip_base = mid_base.lerp(tip_cool.lerp(tip_warm, growth), 0.72)
        wind_angle = 0.63 + 0.48 * value_noise(wx / 17, wy / 17, seed + 77)
        wind_dir = Vector((math.cos(wind_angle), math.sin(wind_angle), 0))
        low = height < 0.33
        count_blades = (3 if low else 5) if simple else (4 if low else 8)
        for j in range(count_blades):
            theta = (
                angle + j * math.tau / count_blades + rng.uniform(-0.32, 0.32)
            )
            out = Vector((math.cos(theta), math.sin(theta), 0))
            radius = rng.uniform(0.025, 0.22)
            dx, dy = out.x * radius, out.y * radius
            dz = -(dx * normal.x + dy * normal.y) / normal.z - 0.018
            base = Vector((point.x + dx, point.y + dy, point.z + dz))
            is_short = j >= 4
            if low:
                h = height * rng.uniform(0.63, 1.14)
                w = rng.uniform(0.019, 0.033)
                segments = 1
            elif is_short:
                h = height * rng.uniform(0.47, 0.84)
                w = rng.uniform(0.012, 0.025)
                segments = 2
            else:
                h = height * rng.uniform(0.84, 1.18)
                w = rng.uniform(0.012, 0.025)
                segments = 3
            mix_w = 0.36 if is_short else 0.65
            fwd = (wind_dir * mix_w + out * (1.0 - mix_w)).normalized()
            side = Vector((-fwd.y, fwd.x, 0))
            lean = h * rng.uniform(0.07, 0.22)
            curl = h * rng.uniform(0.14, 0.30)
            shade = rng.uniform(0.84, 1.14)
            tones = (
                _clamp_rgb(root_vec * shade),
                _clamp_rgb(mid_base * shade),
                _clamp_rgb(tip_base * shade),
            )
            _add_blade(
                batch,
                base,
                fwd,
                side,
                w,
                h,
                lean,
                curl,
                tones,
                (normal - fwd * 0.27).normalized(),
                segments=segments,
            )
        if growth > 0.55 and 0.29 < height < 0.70 and rng.random() < 0.04:
            fdx, fdy = rng.uniform(-0.14, 0.14), rng.uniform(-0.14, 0.14)
            fdz = -(fdx * normal.x + fdy * normal.y) / normal.z - 0.015
            _add_wildflower(
                batch,
                Vector((point.x + fdx, point.y + fdy, point.z + fdz)),
                wind_dir,
                height * rng.uniform(0.68, 0.90),
                flower_colors[rng.randrange(len(flower_colors))],
                stem_rgb,
                center_rgb,
                normal,
            )
        count += 1
    for batch in batches.values():
        obj = finish(batch, collection, root, "grass")
        if obj:
            obj["collision_enabled"] = False
            obj["cosmetic_only"] = True
            obj["export_chunk_size"] = chunk_size
    return count
