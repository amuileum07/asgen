"""Generate cartoon houses in Blender's Text Editor or command line.

CLI usage: blender -b -P this_file.py -- --help.
The layout module also runs with uv and ordinary Python.
Blender provides bpy and mathutils without a separate installation.
"""

import argparse
import importlib
import json
import math
import random
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if __name__ == "__main__":
    for module_name in (
        "solid_geometry",
        "house_rules",
        "interior_rules",
        "interior_blender",
        "game_materials",
    ):
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

from house_rules import (  # noqa: E402
    ARCHITECTURES,
    FOUNDATION_HEIGHT,
    PALETTES,
    ROOF_STYLES,
    WALL_STYLES,
    HouseConfig,
    Opening,
    clip_polygon,
    make_plan,
    polygon_area,
    rectangle,
    roof_planes,
    wall_tiles,
    without_openings,
)
from interior_rules import floor_z, load_catalog, make_interior_plan  # noqa: E402
from solid_geometry import clip_solid  # noqa: E402

try:
    import bpy
    from mathutils import Vector

    import interior_blender
    from game_materials import configure_architecture_surface
except ModuleNotFoundError:
    bpy = None
    Vector = None


OWNER = "cartoon_house_v1"
OWNER_KEY = "_cartoon_house_owner"
SETTINGS_KEY = "cartoon_house_settings"

COLORS = {
    "WARM": {
        "brick": "cc8971",
        "wood": "bc9468",
        "plaster": "f1ddba",
        "trim": "614b43",
        "roof": "588895",
        "frame": "f8e9cb",
        "door": "b47c49",
        "glass": "43768a",
        "foundation": "85928d",
    },
    "PASTEL": {
        "brick": "dcaaa1",
        "wood": "d3b894",
        "plaster": "f0decf",
        "trim": "80665f",
        "roof": "879bb9",
        "frame": "fff0da",
        "door": "9cabb0",
        "glass": "73a9b4",
        "foundation": "a0a6a1",
    },
    "COASTAL": {
        "brick": "deb895",
        "wood": "83aaa5",
        "plaster": "e9e2c9",
        "trim": "435f68",
        "roof": "cc856d",
        "frame": "f8efd7",
        "door": "c19b63",
        "glass": "487c9d",
        "foundation": "8c999a",
    },
}


def _require_blender():
    if bpy is None:
        raise RuntimeError(
            "Run this script inside Blender; use --dry-run with uv."
        )


def _linear_color(hex_color, brightness=1.0):
    values = [
        min(1.0, int(hex_color[i : i + 2], 16) / 255 * brightness)
        for i in (0, 2, 4)
    ]
    return tuple(
        v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
        for v in values
    ) + (1.0,)


def _principled_shader(material):
    """Find nodes by type so translated node names also work."""
    material.use_nodes = True
    nodes = material.node_tree.nodes
    shader = next(
        (node for node in nodes if node.type == "BSDF_PRINCIPLED"), None
    )
    if shader is None:
        shader = nodes.new("ShaderNodeBsdfPrincipled")
    output = next(
        (node for node in nodes if node.type == "OUTPUT_MATERIAL"), None
    )
    if output is None:
        output = nodes.new("ShaderNodeOutputMaterial")
    if not output.inputs["Surface"].is_linked:
        material.node_tree.links.new(
            shader.outputs["BSDF"], output.inputs["Surface"]
        )
    return shader


def _make_materials(config):
    colors = dict(COLORS[config.palette])
    if config.architecture == "MEDIEVAL":
        medieval = {
            "WARM": ("e2cd9d", "a25e48"),
            "PASTEL": ("e1c5b1", "758f92"),
            "COASTAL": ("ddd4b4", "607e77"),
        }
        plaster, roof = medieval[config.palette]
        colors.update(
            plaster=plaster,
            roof=roof,
            trim="49382f",
            frame="a88c62",
            door="977448",
            wood="ad895b",
            foundation="87867b",
            glass="47646b",
        )
    specifications = dict(colors)
    specifications["mortar"] = (
        "dfcfb5" if config.wall_style == "BRICK" else colors["trim"]
    )
    specifications["metal"] = "ddb66b"
    specifications["ground"] = "b2c3a4"
    specifications["stone"] = "939084"
    specifications["chimney_hole"] = "302c2b"
    specifications.update(
        {
            "floor": "cbbd9d",
            "partition": "ece4d2",
            "stairs": "9a8268",
            "bed": "819fc5",
            "lamp": "e7be62",
            "wardrobe": "bba378",
            "sofa": "82a795",
            "chair": "b78f80",
            "dining_table": "cfa779",
            "desk": "a58cb1",
            "label": "273640",
        }
    )
    base = colors["brick"] if config.wall_style == "BRICK" else colors["wood"]
    for i in range(7):
        specifications[f"cladding_{i}"] = base
        specifications[f"roof_{i}"] = colors["roof"]
    finishes = {
        "plaster": "plaster",
        "trim": "timber",
        "frame": "timber",
        "door": "timber",
        "wood": "timber",
        "roof": "clay",
        "stone": "stone",
        "foundation": "stone",
        "brick": "clay",
        "cladding": "clay" if config.wall_style == "BRICK" else "timber",
    }
    materials = {}
    for key, color in specifications.items():
        brightness = 0.90 + 0.033 * int(key[-1]) if key[-1].isdigit() else 1.0
        material = bpy.data.materials.new(f"CH_{config.palette}_{key}")
        material[OWNER_KEY] = OWNER
        material.diffuse_color = _linear_color(color, brightness)
        shader = _principled_shader(material)
        shader.inputs["Base Color"].default_value = material.diffuse_color
        shader.inputs["Roughness"].default_value = (
            0.28 if key == "glass" else 0.78
        )
        if key == "metal":
            shader.inputs["Metallic"].default_value = 0.65
            shader.inputs["Roughness"].default_value = 0.35
        if config.architecture == "MEDIEVAL":
            finish = finishes.get(key.rstrip("0123456789").rstrip("_"))
            if finish:
                configure_architecture_surface(material, shader, finish)
        materials[key] = material
    return materials


def _face_normal(points):
    normal = Vector((0, 0, 0))
    for a, b in zip(points, points[1:] + points[:1], strict=True):
        normal += a.cross(b)
    return normal.normalized()


class MeshBatch:
    """Combine repeated pieces into one mesh per role."""

    def __init__(self, name, materials, bevel=0.0):
        self.name = name
        self.materials = materials
        self.material_indices = {
            key: index for index, key in enumerate(materials)
        }
        self.vertices = []
        self.faces = []
        self.face_materials = []
        self.bevel = bevel
        self.clip_planes = ()

    def prism(self, polygon, extrusion, material):
        points = [Vector(point) for point in polygon]
        direction = Vector(extrusion)
        normal = _face_normal(points)
        if len(points) < 3 or normal.length < 0.5 or direction.length < 1e-8:
            return
        if normal.dot(direction) < 0:
            points.reverse()
        if self.clip_planes:
            count = len(points)
            vertices = [tuple(p) for p in points]
            vertices += [tuple(p + direction) for p in points]
            faces = [
                tuple(reversed(range(count))),
                tuple(count + i for i in range(count)),
            ]
            faces += [
                (i, (i + 1) % count, count + (i + 1) % count, count + i)
                for i in range(count)
            ]
            vertices, faces = clip_solid(vertices, faces, self.clip_planes)
            first = len(self.vertices)
            self.vertices.extend(vertices)
            self.faces.extend(tuple(first + i for i in f) for f in faces)
            self.face_materials.extend(
                [self.material_indices[material]] * len(faces)
            )
            return
        first, count = len(self.vertices), len(points)
        self.vertices.extend(tuple(point) for point in points)
        self.vertices.extend(tuple(point + direction) for point in points)
        faces = [
            tuple(first + i for i in reversed(range(count))),
            tuple(first + count + i for i in range(count)),
        ]
        faces.extend(
            (
                first + i,
                first + (i + 1) % count,
                first + count + (i + 1) % count,
                first + count + i,
            )
            for i in range(count)
        )
        self.faces.extend(faces)
        self.face_materials.extend(
            [self.material_indices[material]] * len(faces)
        )

    def box(self, centre, dimensions, material, basis=None):
        axes = (
            [Vector(axis) for axis in basis]
            if basis
            else [Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))]
        )
        centre = Vector(centre)
        x, y, z = (
            axis * size / 2
            for axis, size in zip(axes, dimensions, strict=True)
        )
        self.prism(
            [
                centre - x - y - z,
                centre + x - y - z,
                centre + x + y - z,
                centre - x + y - z,
            ],
            z * 2,
            material,
        )

    def beam(self, start, end, width, material):
        start, end = Vector(start), Vector(end)
        axis = end - start
        if axis.length < 1e-6:
            return
        length = axis.length
        axis.normalize()
        reference = (
            Vector((0, 0, 1)) if abs(axis.z) < 0.95 else Vector((1, 0, 0))
        )
        x = axis.cross(reference).normalized()
        y = axis.cross(x).normalized()
        self.box(
            (start + end) / 2,
            (width, width, length + 0.025),
            material,
            (x, y, axis),
        )

    def finish(self, collection, parent):
        if not self.vertices:
            return None
        mesh = bpy.data.meshes.new(f"CH_{self.name}")
        mesh[OWNER_KEY] = OWNER
        mesh.from_pydata(self.vertices, [], self.faces)
        mesh.update()
        material_list = list(self.materials.values())
        used_indices = sorted(set(self.face_materials))
        remap = {old: new for new, old in enumerate(used_indices)}
        for index in used_indices:
            mesh.materials.append(material_list[index])
        for face, index in zip(
            mesh.polygons, self.face_materials, strict=True
        ):
            face.material_index = remap[index]
        # Face-local UVs use metres and overlap for tiling textures.
        # Lightmaps and unique painting atlases need separate packing.
        uv = mesh.uv_layers.new(name="UVMap")
        grain_slots = {
            index
            for index, material in enumerate(mesh.materials)
            if material is not None and material.get("grain_aligned_uv")
        }
        for face in mesh.polygons:
            a, b = face.vertices[:2]
            if face.material_index in grain_slots:
                outline = tuple(face.vertices)
                a, b = max(
                    zip(outline, outline[1:] + outline[:1], strict=True),
                    key=lambda edge: (
                        (
                            mesh.vertices[edge[1]].co
                            - mesh.vertices[edge[0]].co
                        ).length_squared
                    ),
                )
            origin = mesh.vertices[a].co
            u = (mesh.vertices[b].co - origin).normalized()
            v = face.normal.cross(u).normalized()
            for loop_index in face.loop_indices:
                co = (
                    mesh.vertices[mesh.loops[loop_index].vertex_index].co
                    - origin
                )
                uv.data[loop_index].uv = (co.dot(u), co.dot(v))
        obj = bpy.data.objects.new(f"CH_{self.name}", mesh)
        obj[OWNER_KEY] = OWNER
        collection.objects.link(obj)
        obj.parent = parent
        if self.bevel > 0:
            modifier = obj.modifiers.new("Soft cartoon edges", "BEVEL")
            modifier.width = self.bevel
            modifier.segments = 2
            modifier.limit_method = "ANGLE"
        return obj


def _wall_point(wall, u, z, offset=0.0):
    return (
        wall.start[0] + wall.tangent[0] * u + wall.normal[0] * offset,
        wall.start[1] + wall.tangent[1] * u + wall.normal[1] * offset,
        FOUNDATION_HEIGHT + z,
    )


def _wall_prism(batch, wall, polygon, offset, thickness, material):
    batch.prism(
        [_wall_point(wall, u, z, offset) for u, z in polygon],
        (wall.normal[0] * thickness, wall.normal[1] * thickness, 0),
        material,
    )


def _wall_box(batch, wall, x1, z1, x2, z2, offset, thickness, material):
    if x2 > x1 and z2 > z1:
        _wall_prism(
            batch, wall, rectangle(x1, z1, x2, z2), offset, thickness, material
        )


def _shutter_width(wall, opening, config):
    """Return shutter width clearing corners, neighbors and timber."""
    x1, _z1, x2, _z2 = opening.rectangle
    width = x2 - x1
    border = 0.075
    left_limit = 0.125
    right_limit = wall.length - 0.125
    for other in wall.openings:
        if (
            other == opening
            or other.z2 <= opening.z1
            or other.z1 >= opening.z2
        ):
            continue
        if other.x2 <= x1:
            gap = (x1 - border) - (other.x2 + border)
            if other.kind == "DOOR":
                left_limit = max(left_limit, other.x2 + border + 0.01)
            else:
                left_limit = max(
                    left_limit, other.x2 + border + gap / 2 + 0.01
                )
        elif other.x1 >= x2:
            gap = (other.x1 - border) - (x2 + border)
            if other.kind == "DOOR":
                right_limit = min(right_limit, other.x1 - border - 0.01)
            else:
                right_limit = min(
                    right_limit, other.x1 - border - gap / 2 - 0.01
                )
    if config.architecture == "MEDIEVAL":
        bays = max(2, int(wall.length / config.window_spacing))
        for index in range(1, bays):
            u = wall.length * index / bays
            if u + 0.055 <= x1 - border:
                left_limit = max(left_limit, u + 0.065)
            elif u - 0.055 >= x2 + border:
                right_limit = min(right_limit, u - 0.065)
    available = min((x1 - border) - left_limit, right_limit - (x2 + border))
    shutter_width = min(0.27, width * 0.22, available)
    return shutter_width if shutter_width >= 0.08 else 0.0


def _build_opening(batch, wall, opening, config):
    x1, z1, x2, z2 = opening.rectangle
    width, height = x2 - x1, z2 - z1
    border = 0.075
    # Embed trim into the outer reveal so plaster walls have no air gap.
    _wall_box(
        batch,
        wall,
        x1 - border,
        z1 - 0.025,
        x1 + border / 2,
        z2 + border,
        -0.01,
        0.165,
        "frame",
    )
    _wall_box(
        batch,
        wall,
        x2 - border / 2,
        z1 - 0.025,
        x2 + border,
        z2 + border,
        -0.01,
        0.165,
        "frame",
    )
    _wall_box(
        batch,
        wall,
        x1 + border / 2,
        z2 - border / 2,
        x2 - border / 2,
        z2 + border,
        -0.01,
        0.165,
        "frame",
    )
    if opening.kind == "DOOR":
        if config.door_open:
            return
        _wall_box(
            batch,
            wall,
            x1 + 0.02,
            z1,
            x2 - 0.02,
            z2 - 0.02,
            -0.045,
            0.08,
            "door",
        )
        for bottom, top in ((0.22, 0.72), (0.87, height - 0.18)):
            _wall_box(
                batch,
                wall,
                x1 + 0.15,
                z1 + bottom,
                x2 - 0.15,
                z1 + top,
                0.036,
                0.018,
                "wood",
            )
        if config.architecture == "MEDIEVAL":
            for index in range(6):
                left = x1 + 0.04 + index * (width - 0.08) / 6
                _wall_box(
                    batch,
                    wall,
                    left,
                    z1 + 0.03,
                    left + (width - 0.08) / 6 - 0.018,
                    z2 - 0.04,
                    0.057,
                    0.025,
                    "door",
                )
            for fraction in (0.25, 0.72):
                _wall_box(
                    batch,
                    wall,
                    x1 + 0.07,
                    z1 + height * fraction,
                    x2 - 0.07,
                    z1 + height * fraction + 0.055,
                    0.084,
                    0.02,
                    "trim",
                )
        centre_u, centre_z = x2 - 0.17, z1 + height * 0.46
        circle = [
            _wall_point(
                wall,
                centre_u + math.cos(i * math.tau / 10) * 0.055,
                centre_z + math.sin(i * math.tau / 10) * 0.055,
                0.07,
            )
            for i in range(10)
        ]
        batch.prism(
            circle, (wall.normal[0] * 0.06, wall.normal[1] * 0.06, 0), "metal"
        )
        return
    _wall_box(
        batch,
        wall,
        x1 + 0.015,
        z1 + 0.015,
        x2 - 0.015,
        z2 - 0.015,
        -0.08,
        0.035,
        "glass",
    )
    _wall_box(
        batch,
        wall,
        x1 - 0.12,
        z1 - 0.085,
        x2 + 0.12,
        z1 + 0.025,
        -0.01,
        0.255,
        "frame",
    )
    mid_x, mid_z = (x1 + x2) / 2, (z1 + z2) / 2
    _wall_box(
        batch,
        wall,
        mid_x - 0.026,
        z1,
        mid_x + 0.026,
        z2,
        -0.045,
        0.12,
        "frame",
    )
    for left, right in ((x1, mid_x - 0.026), (mid_x + 0.026, x2)):
        _wall_box(
            batch,
            wall,
            left,
            mid_z - 0.026,
            right,
            mid_z + 0.026,
            -0.045,
            0.12,
            "frame",
        )
    if config.shutters:
        shutter_width = _shutter_width(wall, opening, config)
        if shutter_width > 0:
            for left in (x1 - border - shutter_width, x2 + border):
                for row in range(6):
                    bottom = z1 + row * height / 6 + 0.012
                    _wall_box(
                        batch,
                        wall,
                        left,
                        bottom,
                        left + shutter_width,
                        bottom + height / 6 - 0.024,
                        0.04,
                        0.085,
                        "door"
                        if config.wall_style.startswith("WOOD")
                        else "wood",
                    )


def _build_roof(batches, plan, config, rng):
    seen_edges = set()
    for face in plan.roof_faces:
        points = [Vector(p) for p in face]
        normal = _face_normal(points)
        batches["Roof"].prism(points, -normal * 0.12, "roof")
        for a, b in zip(points, points[1:] + points[:1], strict=True):
            key = tuple(sorted(tuple(round(c, 6) for c in p) for p in (a, b)))
            if key not in seen_edges:
                seen_edges.add(key)
                batches["RoofTrim"].beam(a, b, 0.14, "trim")
        if not config.roof_tiles or config.roof_style == "FLAT":
            continue
        origin = points[0]
        edges = [
            b - a for a, b in zip(points, points[1:] + points[:1], strict=True)
        ]
        horizontal = [
            edge for edge in edges if abs(edge.z) < 1e-6 and edge.length > 1e-6
        ]
        u = (
            max(horizontal, key=lambda edge: edge.length).normalized()
            if horizontal
            else edges[0].normalized()
        )
        v = normal.cross(u).normalized()
        boundary = [((p - origin).dot(u), (p - origin).dot(v)) for p in points]
        min_u, max_u = min(p[0] for p in boundary), max(p[0] for p in boundary)
        min_v, max_v = min(p[1] for p in boundary), max(p[1] for p in boundary)
        tile_w, tile_h, gap = 0.64, 0.40, 0.035
        for row in range(math.ceil((max_v - min_v) / tile_h)):
            offset = -tile_w / 2 if row % 2 else 0
            for column in range(math.ceil((max_u - min_u - offset) / tile_w)):
                left = min_u + offset + column * tile_w + gap / 2
                bottom = min_v + row * tile_h + gap / 2
                tile = clip_polygon(
                    rectangle(
                        left,
                        bottom,
                        left + tile_w - gap,
                        bottom + tile_h - gap,
                    ),
                    boundary,
                )
                if len(tile) >= 3 and polygon_area(tile) > 0.002:
                    world = [
                        origin + u * x + v * y + normal * 0.012
                        for x, y in tile
                    ]
                    batches["RoofTiles"].prism(
                        world, normal * 0.04, f"roof_{rng.randrange(7)}"
                    )


def _medieval_details(batches, house, config):
    timber = batches["Timber"]
    stone = batches["MedievalDetails"]

    def strip(wall, polygon, extra_openings=()):
        clipped = clip_polygon(polygon, wall.profile)
        if len(clipped) >= 3 and polygon_area(clipped) > 1e-6:
            for piece in without_openings(
                clipped, tuple(wall.openings) + tuple(extra_openings)
            ):
                _wall_prism(timber, wall, piece, 0.065, 0.065, "trim")

    for wall in house.walls:
        shutter_masks = []
        if config.shutters:
            for opening in wall.openings:
                if opening.kind != "WINDOW":
                    continue
                sw = _shutter_width(wall, opening, config)
                if sw > 0:
                    shutter_masks.append(
                        Opening(
                            "SHUTTER",
                            opening.x1 - 0.075 - sw,
                            opening.z1,
                            opening.x2 + 0.075 + sw,
                            opening.z2,
                        )
                    )
        bays = max(2, int(wall.length / config.window_spacing))
        top = max(z for _, z in wall.profile)
        for index in range(1, bays):
            u = wall.length * index / bays
            strip(wall, rectangle(u - 0.055, 0, u + 0.055, top))
        for floor in range(config.floors):
            bottom = floor * house.floor_height
            strip(
                wall, rectangle(0, bottom + 0.08, wall.length, bottom + 0.21)
            )
            for bay in (0, bays - 1):
                a = (wall.length * bay / bays + 0.12, bottom + 0.25)
                b = (
                    wall.length * (bay + 1) / bays - 0.12,
                    bottom + house.floor_height - 0.18,
                )
                if bay % 2:
                    a, b = (a[0], b[1]), (b[0], a[1])
                length = math.dist(a, b)
                dx, dz = (b[0] - a[0]) / length, (b[1] - a[1]) / length
                thickness = 0.045
                strip(
                    wall,
                    [
                        (a[0] - dz * thickness, a[1] + dx * thickness),
                        (a[0] + dz * thickness, a[1] - dx * thickness),
                        (b[0] + dz * thickness, b[1] - dx * thickness),
                        (b[0] - dz * thickness, b[1] + dx * thickness),
                    ],
                    shutter_masks,
                )
        count = math.ceil(wall.length / 0.70)
        for index in range(count):
            left = index * wall.length / count + 0.012
            right = (index + 1) * wall.length / count - 0.012
            _wall_box(
                stone, wall, left, -0.27, right, -0.03, 0.045, 0.13, "stone"
            )
    stone = batches["Chimney"]
    x, y = -house.width * 0.28, house.depth * 0.20
    roof_z = None
    min_roof_z = None
    for face in house.roof_faces:
        projected = [(p[0], p[1]) for p in face]
        if not all(
            (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0]) >= -1e-7
            for a, b in zip(
                projected, projected[1:] + projected[:1], strict=True
            )
        ):
            continue
        points = [Vector(point) for point in face]
        normal = _face_normal(points)
        p = points[0]
        roof_z = p.z - (normal.x * (x - p.x) + normal.y * (y - p.y)) / normal.z
        min_roof_z = min(
            p.z - (normal.x * (cx - p.x) + normal.y * (cy - p.y)) / normal.z
            for cx in (x - 0.30, x + 0.30)
            for cy in (y - 0.325, y + 0.325)
        )
        break
    if roof_z is not None:
        top = max(
            roof_z + 0.95,
            max(p[2] for face in house.roof_faces for p in face) + 0.16,
        )
        bottom = min_roof_z - 0.12
        stone.box(
            (x, y, (bottom + top) / 2), (0.60, 0.65, top - bottom), "stone"
        )
        for offset in (-0.35, 0.35):
            stone.box((x, y + offset, top + 0.06), (0.82, 0.12, 0.12), "stone")
        for offset in (-0.35, 0.35):
            stone.box((x + offset, y, top + 0.06), (0.12, 0.58, 0.12), "stone")
        stone.box((x, y, top + 0.012), (0.54, 0.54, 0.012), "chimney_hole")


def _root_for(collection):
    if collection:
        return next(
            (
                obj
                for obj in collection.objects
                if obj.get(OWNER_KEY) == OWNER and obj.get("is_house_root")
            ),
            None,
        )
    return None


def _remove_owned_collection(collection):
    """Remove generated data and preserve user additions."""
    if not collection or collection.get(OWNER_KEY) != OWNER:
        return
    meshes, materials = set(), set()
    owned = {obj for obj in collection.objects if obj.get(OWNER_KEY) == OWNER}
    # User objects can have been parented to the house after generation.
    for obj in list(bpy.data.objects):
        if obj not in owned and obj.parent in owned:
            transform = obj.matrix_world.copy()
            obj.parent = None
            obj.matrix_world = transform
    for obj in list(collection.objects):
        if obj.get(OWNER_KEY) != OWNER:
            continue
        if obj.type == "MESH":
            meshes.add(obj.data)
            materials.update(m for m in obj.data.materials if m)
        elif obj.type in ("CAMERA", "LIGHT", "FONT"):
            data = obj.data
            kind = obj.type
            if kind == "FONT":
                materials.update(
                    material for material in data.materials if material
                )
            bpy.data.objects.remove(obj, do_unlink=True)
            if data.users == 0:
                storage = {
                    "CAMERA": "cameras",
                    "LIGHT": "lights",
                    "FONT": "curves",
                }
                getattr(bpy.data, storage[kind]).remove(data)
            continue
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in meshes:
        if mesh.users == 0 and mesh.get(OWNER_KEY) == OWNER:
            bpy.data.meshes.remove(mesh)
    for material in materials:
        if material.users == 0 and material.get(OWNER_KEY) == OWNER:
            bpy.data.materials.remove(material)
    if not collection.objects and not collection.children:
        bpy.data.collections.remove(collection)


def build_house(config, *, scene=None, replace=None, location=(0, 0, 0)):
    """Replace a generated house after building its replacement."""
    _require_blender()
    plan = make_plan(config)
    path = (
        bpy.path.abspath(config.furniture_catalog)
        if config.interior and config.furnish and config.furniture_catalog
        else ""
    )
    catalog = load_catalog(path)
    interior = make_interior_plan(config, plan, catalog)
    scene = scene or bpy.context.scene
    if replace is not None and (
        replace.get(OWNER_KEY) != OWNER or _root_for(replace) is None
    ):
        raise ValueError(
            "The target collection was not created by this generator"
        )
    old_root = _root_for(replace)
    visible_floor = (
        old_root.get("visible_interior_floor", -1) if old_root else -1
    )
    transform = old_root.matrix_world.copy() if old_root else None
    old_name = replace.name if replace else "CartoonHouse"
    collection = bpy.data.collections.new("CartoonHouse_building")
    collection[OWNER_KEY] = OWNER
    scene.collection.children.link(collection)
    materials = {}
    try:
        root = bpy.data.objects.new("CH_House", None)
        root[OWNER_KEY] = OWNER
        root["is_house_root"] = True
        root["config_json"] = json.dumps(config.as_dict(), sort_keys=True)
        root["actual_width"] = plan.width
        root["actual_depth"] = plan.depth
        root["interior_plan_json"] = json.dumps(
            interior.as_dict(), sort_keys=True
        )
        root["furniture_catalog_json"] = json.dumps(
            {
                kind: {"size": spec.size, "clearance": spec.clearance}
                for kind, spec in catalog.items()
            },
            sort_keys=True,
        )
        root["unplaced_count"] = len(interior.unplaced)
        collection.objects.link(root)
        root.empty_display_type = "PLAIN_AXES"
        root.empty_display_size = 0.6
        if transform is not None:
            root.matrix_world = transform
        else:
            root.location = location
        materials = _make_materials(config)
        batches = {
            name: MeshBatch(name, materials, config.bevel * factor)
            for name, factor in (
                ("Foundation", 1.5),
                ("Walls", 0),
                ("Cladding", 1),
                ("Timber", 1.2),
                ("RoofTrim", 1.2),
                ("WindowsAndDoor", 0.8),
                ("Roof", 1),
                ("RoofTiles", 0.7),
                ("MedievalDetails", 0.8),
                ("Chimney", 0.8),
            )
        }
        for name in (
            "Walls",
            "Cladding",
            "Timber",
            "WindowsAndDoor",
            "MedievalDetails",
        ):
            batches[name].clip_planes = roof_planes(
                plan, 0.128 + batches[name].bevel
            )
        batches["Foundation"].box(
            (0, 0, FOUNDATION_HEIGHT / 2),
            (plan.width + 0.34, plan.depth + 0.34, FOUNDATION_HEIGHT),
            "foundation",
        )
        for wall in plan.walls:
            for part in without_openings(wall.profile, wall.openings):
                _wall_prism(
                    batches["Walls"],
                    wall,
                    part,
                    0,
                    -0.16,
                    "plaster" if config.wall_style == "PLASTER" else "mortar",
                )
            rng = random.Random(f"{config.detail_seed}:{wall.name}:cladding")
            for tile in wall_tiles(wall, config):
                thickness = 0.07 if config.wall_style == "BRICK" else 0.045
                _wall_prism(
                    batches["Cladding"],
                    wall,
                    tile,
                    0.004,
                    thickness,
                    f"cladding_{rng.randrange(7)}",
                )
            for opening in wall.openings:
                _build_opening(
                    batches["WindowsAndDoor"], wall, opening, config
                )
                if opening.kind == "DOOR":
                    centre = _wall_point(
                        wall, (opening.x1 + opening.x2) / 2, -0.20, 0.42
                    )
                    batches["Foundation"].box(
                        centre,
                        (opening.x2 - opening.x1 + 0.55, 0.85, 0.20),
                        "foundation",
                    )
            for floor in range(1, config.floors):
                z = floor * plan.floor_height
                _wall_box(
                    batches["Timber"],
                    wall,
                    0,
                    z - 0.09,
                    wall.length,
                    z + 0.04,
                    0.04,
                    0.10,
                    "trim",
                )
        slope = math.tan(math.radians(plan.pitch))
        for x in (-plan.width / 2, plan.width / 2):
            height = plan.height
            if config.roof_style == "SHED":
                height += (plan.width / 2 - x) * slope
            for y in (-plan.depth / 2, plan.depth / 2):
                batches["Timber"].box(
                    (x, y, FOUNDATION_HEIGHT + height / 2),
                    (0.23, 0.23, height),
                    "trim",
                )
        _build_roof(batches, plan, config, random.Random(config.detail_seed))
        if config.architecture == "MEDIEVAL":
            _medieval_details(batches, plan, config)
        for batch in batches.values():
            obj = batch.finish(collection, root)
            if obj:
                obj["house_part"] = "exterior"
                obj["house_geometry_role"] = batch.name
        if config.interior:
            interior_blender.build_geometry(
                interior, plan, config, collection, root, materials, MeshBatch
            )
            if visible_floor >= 0:
                interior_blender.show_floor(
                    collection, root, min(visible_floor, config.floors - 1)
                )
        # Keep only palette entries referenced by the generated meshes.
        for material in materials.values():
            if material.users == 0:
                bpy.data.materials.remove(material)
    except Exception:
        material_names = [material.name for material in materials.values()]
        _remove_owned_collection(collection)
        for name in material_names:
            material = bpy.data.materials.get(name)
            if material is not None and material.users == 0:
                bpy.data.materials.remove(material)
        raise
    if replace is not None:
        _remove_owned_collection(replace)
    collection.name = old_name
    return collection, root, plan


def create_preview_stage(plan, root, *, scene=None):
    """Create preview lighting, camera, world and render settings."""
    _require_blender()
    scene = scene or bpy.context.scene
    for old in list(scene.collection.children):
        if old.get(OWNER_KEY) == OWNER and old.get("is_preview_stage"):
            _remove_owned_collection(old)
    stage = bpy.data.collections.new("CartoonHouse_Preview")
    stage[OWNER_KEY] = OWNER
    stage["is_preview_stage"] = True
    scene.collection.children.link(stage)
    material = bpy.data.materials.new("CH_PreviewGround")
    material[OWNER_KEY] = OWNER
    color = _linear_color("b8c9ac")
    material.diffuse_color = color
    shader = _principled_shader(material)
    shader.inputs["Base Color"].default_value = color
    shader.inputs["Roughness"].default_value = 0.9
    ground = MeshBatch("PreviewGround", {"ground": material})
    ground.box((0, 0, -0.12), (200, 200, 0.16), "ground")
    ground_obj = ground.finish(stage, None)
    ground_obj.location = root.matrix_world.translation
    top = max(point[2] for face in plan.roof_faces for point in face)
    span = max(plan.width, plan.depth, top)
    target_point = (0, 0, top * 0.44)
    camera_point = (span * 1.2, -span * 1.65, top + span * 0.65)
    ortho_scale = span * 1.85
    visible_floor = root.get("visible_interior_floor", -1)
    if visible_floor >= 0:
        floor_height = floor_z(plan, visible_floor)
        view_span = max(plan.width, plan.depth)
        target_point = (0, 0, floor_height + 0.25)
        camera_point = (
            view_span * 0.65,
            -view_span * 0.85,
            floor_height + view_span * 1.65,
        )
        ortho_scale = view_span * 1.55
    target = root.matrix_world @ Vector(target_point)
    camera_data = bpy.data.cameras.new("CH_PreviewCamera")
    camera = bpy.data.objects.new("CH_PreviewCamera", camera_data)
    camera[OWNER_KEY] = OWNER
    stage.objects.link(camera)
    camera.location = root.matrix_world @ Vector(camera_point)
    camera.rotation_euler = (
        (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    )
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = ortho_scale
    scene.camera = camera
    for name, position, energy, size in (
        ("Key", (-span * 0.7, -span, top + span), 2100, span * 0.85),
        ("Fill", (span, -span * 0.25, top + span * 0.6), 1100, span),
        ("Rim", (0, span, top + span * 0.8), 1800, span * 0.7),
    ):
        data = bpy.data.lights.new(f"CH_{name}", "AREA")
        data.energy, data.shape, data.size = (
            energy * (span / 6.5) ** 2,
            "DISK",
            size,
        )
        obj = bpy.data.objects.new(f"CH_{name}", data)
        obj[OWNER_KEY] = OWNER
        stage.objects.link(obj)
        obj.location = root.matrix_world @ Vector(position)
        obj.rotation_euler = (
            (target - obj.location).to_track_quat("-Z", "Y").to_euler()
        )
    if scene.world is None or scene.world.get(OWNER_KEY) != OWNER:
        scene.world = bpy.data.worlds.new("CH_PreviewWorld")
        scene.world[OWNER_KEY] = OWNER
    scene.world.use_nodes = True
    nodes = scene.world.node_tree.nodes
    background = next(
        (node for node in nodes if node.type == "BACKGROUND"), None
    )
    if background is None:
        background = nodes.new("ShaderNodeBackground")
        output = next(
            (node for node in nodes if node.type == "OUTPUT_WORLD"), None
        )
        if output is None:
            output = nodes.new("ShaderNodeOutputWorld")
        scene.world.node_tree.links.new(
            background.outputs["Background"], output.inputs["Surface"]
        )
    background.inputs["Color"].default_value = (0.70, 0.80, 1.0, 1.0)
    background.inputs["Strength"].default_value = 0.45
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 32
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 960
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    return stage


def _config_from_settings(settings):
    return HouseConfig(
        **{
            name: getattr(settings, name)
            for name in HouseConfig.__dataclass_fields__
        }
    )


def _select_root(root):
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    root.select_set(True)
    bpy.context.view_layer.objects.active = root
    for area in bpy.context.screen.areas if bpy.context.screen else ():
        if area.type == "VIEW_3D":
            area.spaces.active.shading.color_type = "MATERIAL"


def _generate_from_settings(context, new_house=False):
    settings = getattr(context.scene, SETTINGS_KEY)
    collection, root, _ = build_house(
        _config_from_settings(settings),
        scene=context.scene,
        replace=None if new_house else settings.target,
        location=context.scene.cursor.location,
    )
    settings.target = collection
    _select_root(root)
    return collection


UI_CLASSES = ()
if bpy is not None:

    class CH_Settings(bpy.types.PropertyGroup):
        target: bpy.props.PointerProperty(
            name="현재 집",
            type=bpy.types.Collection,
            poll=lambda self, value: _root_for(value) is not None,
        )
        seed: bpy.props.IntProperty(
            name="구조 Seed", default=42, min=0, max=2_000_000_000
        )
        detail_seed: bpy.props.IntProperty(
            name="마감 Seed", default=7, min=0, max=2_000_000_000
        )
        width: bpy.props.FloatProperty(
            name="가로 (m)", default=6.4, min=4, max=16
        )
        depth: bpy.props.FloatProperty(
            name="세로 (m)", default=5.4, min=4, max=16
        )
        floors: bpy.props.IntProperty(name="층수", default=2, min=1, max=3)
        floor_height: bpy.props.FloatProperty(
            name="층 높이 (m)", default=2.55, min=2.4, max=3.5
        )
        variation: bpy.props.FloatProperty(
            name="구조 변화량", default=0.08, min=0, max=0.2, subtype="FACTOR"
        )
        wall_style: bpy.props.EnumProperty(
            name="벽 마감",
            default="PLASTER",
            items=[
                ("BRICK", "벽돌", "입체 벽돌과 줄눈"),
                (
                    "WOOD_HORIZONTAL",
                    "가로 나무 판자",
                    "가로로 배치한 입체 판자",
                ),
                ("WOOD_VERTICAL", "세로 나무 판자", "세로로 배치한 입체 판자"),
                ("PLASTER", "회벽", "단색 회벽과 나무 테두리"),
            ],
        )
        roof_style: bpy.props.EnumProperty(
            name="지붕 형태",
            default="GABLE",
            items=[
                ("GABLE", "박공", "양쪽으로 경사진 지붕"),
                ("HIP", "우진각", "사방으로 경사진 지붕"),
                ("SHED", "외쪽 경사", "한쪽으로 경사진 지붕"),
                ("FLAT", "평지붕", "평평한 지붕"),
            ],
        )
        roof_pitch: bpy.props.FloatProperty(
            name="지붕 경사 (도)", default=40, min=10, max=50
        )
        overhang: bpy.props.FloatProperty(
            name="처마 길이 (m)", default=0.55, min=0.2, max=0.8
        )
        window_width: bpy.props.FloatProperty(
            name="창문 가로 (m)", default=1.05, min=0.65, max=1.5
        )
        window_height: bpy.props.FloatProperty(
            name="창문 높이 (m)", default=1.1, min=0.65, max=1.4
        )
        window_spacing: bpy.props.FloatProperty(
            name="창문 간격 (m)", default=2, min=1.7, max=3.2
        )
        brick_width: bpy.props.FloatProperty(
            name="벽돌 가로 (m)", default=0.58, min=0.35, max=1.2
        )
        brick_height: bpy.props.FloatProperty(
            name="벽돌 높이 (m)", default=0.28, min=0.18, max=0.5
        )
        plank_width: bpy.props.FloatProperty(
            name="판자 폭 (m)", default=0.26, min=0.18, max=0.5
        )
        bevel: bpy.props.FloatProperty(
            name="모서리 둥글기 (m)", default=0.018, min=0, max=0.035
        )
        palette: bpy.props.EnumProperty(
            name="색상 팔레트",
            default="WARM",
            items=[
                ("WARM", "따뜻한 색", "살구색 벽과 청록 지붕"),
                ("PASTEL", "파스텔", "연한 분홍과 푸른 지붕"),
                ("COASTAL", "해안 마을", "청록 나무와 주황 지붕"),
            ],
        )
        roof_tiles: bpy.props.BoolProperty(name="입체 지붕 타일", default=True)
        shutters: bpy.props.BoolProperty(name="창문 덧문", default=True)
        door_open: bpy.props.BoolProperty(name="출입문 열기", default=False)
        architecture: bpy.props.EnumProperty(
            name="건축 양식",
            default="MEDIEVAL",
            items=[
                ("SIMPLE", "기본 카툰", "간단한 외관"),
                ("MEDIEVAL", "중세 목조", "목재 골조와 석재 기단, 굴뚝"),
            ],
        )
        interior: bpy.props.BoolProperty(name="실내 구조 생성", default=True)
        furnish: bpy.props.BoolProperty(name="가구 배치", default=True)
        interior_seed: bpy.props.IntProperty(
            name="가구 배치 Seed", default=17, min=0, max=2_000_000_000
        )
        walkway_width: bpy.props.FloatProperty(
            name="통로 폭 (m)", default=0.8, min=0.6, max=1.0
        )
        furniture_catalog: bpy.props.StringProperty(
            name="가구 크기 JSON", subtype="FILE_PATH", default=""
        )
        inspect_floor: bpy.props.IntProperty(
            name="살펴볼 층", default=1, min=1, max=3
        )

    class CH_OT_generate(bpy.types.Operator):
        bl_idname = "cartoon_house.generate"
        bl_label = "집 생성 / 갱신"
        bl_options = {"REGISTER", "UNDO"}
        new_house: bpy.props.BoolProperty(default=False, options={"SKIP_SAVE"})

        def execute(self, context):
            try:
                collection = _generate_from_settings(context, self.new_house)
            except Exception as error:
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}
            self.report({"INFO"}, f"집 생성 완료: {collection.name}")
            return {"FINISHED"}

    class CH_OT_variant(bpy.types.Operator):
        bl_idname = "cartoon_house.new_variant"
        bl_label = "새 구조 변형"
        bl_options = {"REGISTER", "UNDO"}

        def execute(self, context):
            settings = getattr(context.scene, SETTINGS_KEY)
            previous = settings.seed
            settings.seed = (previous + 1) % 2_000_000_001
            try:
                _generate_from_settings(context)
            except Exception as error:
                settings.seed = previous
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}
            return {"FINISHED"}

    class CH_OT_preview(bpy.types.Operator):
        bl_idname = "cartoon_house.preview_stage"
        bl_label = "미리보기 카메라 / 조명 만들기"
        bl_options = {"REGISTER", "UNDO"}

        def execute(self, context):
            settings = getattr(context.scene, SETTINGS_KEY)
            root = _root_for(settings.target)
            if root is None:
                self.report({"ERROR"}, "먼저 집을 생성하세요")
                return {"CANCELLED"}
            config = HouseConfig(**json.loads(root["config_json"]))
            create_preview_stage(make_plan(config), root, scene=context.scene)
            self.report({"INFO"}, "미리보기 준비 완료. F12로 렌더링하세요")
            return {"FINISHED"}

    class CH_OT_interior_view(bpy.types.Operator):
        bl_idname = "cartoon_house.interior_view"
        bl_label = "선택한 층 실내 보기"
        bl_options = {"REGISTER", "UNDO"}
        exterior: bpy.props.BoolProperty(default=False)

        def execute(self, context):
            settings = getattr(context.scene, SETTINGS_KEY)
            root = _root_for(settings.target)
            if root is None:
                self.report({"ERROR"}, "먼저 집을 생성하세요")
                return {"CANCELLED"}
            config = HouseConfig(**json.loads(root["config_json"]))
            if not self.exterior and (
                not config.interior or settings.inspect_floor > config.floors
            ):
                self.report({"ERROR"}, "실내가 생성된 집의 층을 선택하세요")
                return {"CANCELLED"}
            interior_blender.show_floor(
                settings.target,
                root,
                None if self.exterior else settings.inspect_floor - 1,
            )
            return {"FINISHED"}

    class CH_PT_panel(bpy.types.Panel):
        bl_idname = "CH_PT_house_generator"
        bl_label = "Cartoon House"
        bl_space_type = "VIEW_3D"
        bl_region_type = "UI"
        bl_category = "Cartoon House"

        def draw(self, context):
            layout = self.layout
            settings = getattr(context.scene, SETTINGS_KEY)
            layout.use_property_split = True
            layout.prop(settings, "target")
            for names in (
                ("seed", "detail_seed", "variation"),
                ("width", "depth", "floors", "floor_height"),
                ("architecture", "wall_style", "palette", "bevel"),
                ("roof_style", "roof_pitch", "overhang", "roof_tiles"),
                (
                    "window_width",
                    "window_height",
                    "window_spacing",
                    "shutters",
                    "door_open",
                ),
            ):
                box = layout.box()
                for name in names:
                    row = box.row()
                    row.enabled = not (
                        name == "roof_pitch" and settings.roof_style == "FLAT"
                    )
                    row.prop(settings, name)
            box = layout.box()
            if settings.wall_style == "BRICK":
                box.prop(settings, "brick_width")
                box.prop(settings, "brick_height")
            elif settings.wall_style.startswith("WOOD"):
                box.prop(settings, "plank_width")
            box = layout.box()
            box.prop(settings, "interior")
            inner = box.column()
            inner.enabled = settings.interior
            for name in (
                "furnish",
                "interior_seed",
                "walkway_width",
                "furniture_catalog",
            ):
                inner.prop(settings, name)
            inner.prop(settings, "inspect_floor")
            inner.operator("cartoon_house.interior_view")
            button = box.operator(
                "cartoon_house.interior_view", text="외관 다시 보기"
            )
            button.exterior = True
            root = _root_for(settings.target)
            if root and root.get("unplaced_count", 0):
                box.label(
                    text=f"미배치 가구: {root['unplaced_count']}개",
                    icon="INFO",
                )
            layout.operator("cartoon_house.generate", icon="HOME")
            layout.operator("cartoon_house.new_variant", icon="FILE_REFRESH")
            button = layout.operator(
                "cartoon_house.generate", text="별도 집 추가", icon="ADD"
            )
            button.new_house = True
            layout.operator("cartoon_house.preview_stage", icon="CAMERA_DATA")

    UI_CLASSES = (
        CH_Settings,
        CH_OT_generate,
        CH_OT_variant,
        CH_OT_preview,
        CH_OT_interior_view,
        CH_PT_panel,
    )


def unregister():
    _require_blender()
    if hasattr(bpy.types.Scene, SETTINGS_KEY):
        delattr(bpy.types.Scene, SETTINGS_KEY)
    old_classes = bpy.app.driver_namespace.pop("_cartoon_house_classes", ())
    for cls in reversed(old_classes or UI_CLASSES):
        registered = (
            cls
            if "bl_rna" in cls.__dict__
            else cls.__bases__[0].bl_rna_get_subclass_py(cls.__name__, None)
        )
        if registered is not None:
            bpy.utils.unregister_class(registered)


def register():
    _require_blender()
    unregister()
    for cls in UI_CLASSES:
        bpy.utils.register_class(cls)
    setattr(
        bpy.types.Scene,
        SETTINGS_KEY,
        bpy.props.PointerProperty(type=CH_Settings),
    )
    bpy.app.driver_namespace["_cartoon_house_classes"] = UI_CLASSES


def _arguments(argv):
    parser = argparse.ArgumentParser(
        description="Procedural cartoon houses for Blender"
    )
    parser.add_argument(
        "--config", type=Path, help="Optional JSON configuration"
    )
    for name in ("seed", "detail_seed", "interior_seed", "floors"):
        parser.add_argument("--" + name.replace("_", "-"), type=int)
    for name in ("width", "depth", "variation", "walkway_width"):
        parser.add_argument("--" + name.replace("_", "-"), type=float)
    for name in ("interior", "furnish"):
        parser.add_argument(
            "--" + name, action=argparse.BooleanOptionalAction, default=None
        )
    parser.add_argument("--furniture-catalog", type=str)
    parser.add_argument(
        "--layout-output", type=Path, help="Export interior layout JSON"
    )
    parser.add_argument(
        "--view-floor",
        type=int,
        help="Render/show one cutaway floor (1-based)",
    )
    parser.add_argument("--wall-style", choices=WALL_STYLES)
    parser.add_argument("--roof-style", choices=ROOF_STYLES)
    parser.add_argument("--palette", choices=PALETTES)
    parser.add_argument("--architecture", choices=ARCHITECTURES)
    parser.add_argument("--output", type=Path, help="Save a .blend file")
    parser.add_argument(
        "--render", type=Path, help="Render a PNG, creating a preview stage"
    )
    parser.add_argument(
        "--stage", action="store_true", help="Create preview camera and lights"
    )
    parser.add_argument(
        "--force", action="store_true", help="Allow overwriting output files"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the layout JSON without Blender",
    )
    return parser.parse_args(argv)


def main(argv=None):
    if argv is None:
        argv = (
            sys.argv[sys.argv.index("--") + 1 :]
            if "--" in sys.argv
            else ([] if bpy is not None else sys.argv[1:])
        )
    args = _arguments(argv)
    values = (
        json.loads(args.config.read_text(encoding="utf-8"))
        if args.config
        else {}
    )
    if not isinstance(values, dict):
        raise ValueError("The JSON configuration must be an object")
    for name in HouseConfig.__dataclass_fields__:
        value = getattr(args, name, None)
        if value is not None:
            values[name] = value
    config = HouseConfig(**values).validate()
    plan = make_plan(config)
    if args.dry_run:
        catalog = load_catalog(
            config.furniture_catalog
            if config.interior and config.furnish
            else ""
        )
        interior = make_interior_plan(config, plan, catalog)
        print(
            json.dumps(
                {
                    "config": config.as_dict(),
                    "plan": plan.as_dict(),
                    "interior": interior.as_dict(),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return
    _require_blender()
    if args.view_floor is not None and (
        not config.interior or not 1 <= args.view_floor <= config.floors
    ):
        raise ValueError("--view-floor requires an existing interior floor")
    for path, extension in (
        (args.output, ".blend"),
        (args.render, ".png"),
        (args.layout_output, ".json"),
    ):
        if path:
            if path.suffix.lower() != extension:
                raise ValueError(
                    f"Output must have a {extension} extension: {path}"
                )
            if path.exists() and not args.force:
                raise FileExistsError(
                    f"File already exists; pass --force to overwrite: {path}"
                )
    register()
    settings = getattr(bpy.context.scene, SETTINGS_KEY)
    # Preserve saved panel values when rerunning from the Text Editor.
    if not argv and not bpy.app.background:
        config = _config_from_settings(settings)
    else:
        for name, value in config.as_dict().items():
            setattr(settings, name, value)
    collection, root, plan = build_house(config, replace=settings.target)
    settings.target = collection
    _select_root(root)
    if args.view_floor is not None:
        settings.inspect_floor = args.view_floor
        interior_blender.show_floor(collection, root, args.view_floor - 1)
    if args.layout_output:
        args.layout_output.resolve().parent.mkdir(parents=True, exist_ok=True)
        args.layout_output.write_text(
            json.dumps(
                json.loads(root["interior_plan_json"]),
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    if args.stage or args.render:
        create_preview_stage(plan, root)
    if args.render:
        args.render.resolve().parent.mkdir(parents=True, exist_ok=True)
        bpy.context.scene.render.filepath = str(args.render.resolve())
    if args.output:
        args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()))
    if args.render:
        bpy.ops.render.render(write_still=True)
    print(
        f"CartoonHouse: {config.wall_style}/{config.roof_style}, "
        f"seed={config.seed}, "
        f"{plan.width:.2f} x {plan.depth:.2f} m, {config.floors} floors"
    )


if __name__ == "__main__":
    main()
