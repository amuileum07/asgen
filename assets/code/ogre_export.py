"""OGRE meshes, runtime buffers, materials and collisions."""

import hashlib
import json
import math
import re
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

from game_asset_format import (
    MeshSection,
    encode_mesh,
    write_collision,
    write_mesh_xml,
    write_scene,
)

AXIS = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, -1, 0, 0), (0, 0, 0, 1)))
EXCLUDE = {"castle_cutaway", "castle_label", "preview"}


def _name(text):
    return re.sub(r"[^A-Za-z0-9_./-]", "_", text)


def _material(material, registry):
    color = tuple(material.diffuse_color) if material else (0.7, 0.7, 0.7, 1)
    info = {
        "diffuse": color,
        "vertex_color": bool(material and material.get("uses_vertex_color")),
        "albedo": material.get("albedo_texture", "") if material else "",
        "normal": material.get("normal_texture", "") if material else "",
        "emissive": tuple(material.get("emissive_color", (0, 0, 0)))
        if material
        else (0, 0, 0),
    }
    if material and (foliage_bend_uv := material.get("foliage_bend_uv")):
        info["foliage_bend_uv"] = foliage_bend_uv
    if material and material.get("atlas_roof_surface"):
        info["atlas_roof_surface"] = True
    if info["albedo"]:
        info["diffuse"] = (1, 1, 1, 1)
    key = (
        "Proc/Roof/" if info.get("atlas_roof_surface") else "Proc/"
    ) + hashlib.sha256(json.dumps(info, sort_keys=True).encode()).hexdigest()[
        :14
    ]
    registry[key] = info
    return key


def _sections(obj, mesh, registry):
    mesh.calc_loop_triangles()
    uv = mesh.uv_layers.active
    color = mesh.color_attributes.active_color
    vertices, indices, lookups = (
        defaultdict(list),
        defaultdict(list),
        defaultdict(dict),
    )
    material_names = {}
    basis = AXIS.to_3x3()
    for tri in mesh.loop_triangles:
        slot = tri.material_index
        if slot not in material_names:
            material = (
                obj.material_slots[slot].material
                if slot < len(obj.material_slots)
                else None
            )
            material_names[slot] = _material(material, registry)
        name = material_names[slot]
        for li in tri.loops:
            loop = mesh.loops[li]
            p = basis @ mesh.vertices[loop.vertex_index].co
            n = basis @ mesh.corner_normals[li].vector
            tex = tuple(uv.data[li].uv) if uv else (0, 0)
            rgba = (
                tuple(
                    color.data[
                        loop.vertex_index if color.domain == "POINT" else li
                    ].color
                )
                if color
                else (1, 1, 1, 1)
            )
            row = tuple(p) + tuple(n) + tex + rgba
            key = tuple(round(v, 6) for v in row)
            if key not in lookups[name]:
                lookups[name][key] = len(vertices[name])
                vertices[name].append(row)
            indices[name].append(lookups[name][key])
    return tuple(
        MeshSection(name, tuple(vertices[name]), tuple(indices[name]))
        for name in sorted(vertices)
    )


def _chunks(sections, size=64):
    groups = defaultdict(list)
    for section in sections:
        for i in range(0, len(section.indices), 3):
            triangle = [
                section.vertices[j] for j in section.indices[i : i + 3]
            ]
            x = sum(v[0] for v in triangle) / 3
            z = sum(v[2] for v in triangle) / 3
            groups[math.floor(x / size), math.floor(z / size)].append(
                (section.material, triangle)
            )
    result = []
    for (x, z), triangles in sorted(groups.items()):
        origin = (x * size, 0, z * size)
        vertices, indices, lookup = (
            defaultdict(list),
            defaultdict(list),
            defaultdict(dict),
        )
        for material, triangle in triangles:
            for row in triangle:
                row = (
                    row[0] - origin[0],
                    row[1],
                    row[2] - origin[2],
                    *row[3:],
                )
                key = tuple(round(v, 6) for v in row)
                if key not in lookup[material]:
                    lookup[material][key] = len(vertices[material])
                    vertices[material].append(row)
                indices[material].append(lookup[material][key])
        result.append(
            (
                tuple(
                    MeshSection(m, tuple(vertices[m]), tuple(indices[m]))
                    for m in sorted(vertices)
                ),
                origin,
            )
        )
    return result


def _instances(collection):
    members = set(collection.all_objects)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for item in depsgraph.object_instances:
        obj = item.object
        original = obj.original
        parent = item.parent.original if item.parent else None
        if original not in members and parent not in members:
            continue
        if obj.type != "MESH":
            continue
        role = obj.get("settlement_part", "")
        house_part = obj.get("house_part", "")
        if role in EXCLUDE or house_part in ("cutaway_walls", "label"):
            continue
        if parent and parent.hide_render:
            continue
        if (
            not item.is_instance
            and obj.hide_render
            and not (role.startswith("castle_") or house_part)
        ):
            continue
        yield obj, item.matrix_world.copy(), depsgraph


def _write_materials(out, registry):
    lines, images = [], set()
    for name, info in sorted(registry.items()):
        rgba = " ".join(format(v, ".7g") for v in info["diffuse"])
        tint = "vertexcolour" if info["vertex_color"] else rgba
        lines += [
            f"material {name}",
            "{",
            "  technique",
            "  {",
            "    pass",
            "    {",
            f"      ambient {tint}",
            f"      diffuse {tint}",
        ]
        if info.get("foliage_bend_uv"):
            lines += [
                "      cull_hardware none",
                "      cull_software none",
                "      specular 0.01 0.01 0.01 18",
            ]
        else:
            lines.append("      specular 0.025 0.025 0.025 16")
        if any(info["emissive"]):
            lines.append(
                "      emissive "
                + " ".join(format(v, ".7g") for v in info["emissive"])
            )
        if info["albedo"]:
            texture = _name(info["albedo"]) + ".png"
            lines += [
                "      texture_unit",
                "      {",
                f"        texture textures/{texture} gamma",
                "        filtering anisotropic",
                "        max_anisotropy 8",
                "      }",
            ]
            images.add(info["albedo"])
        if info["normal"]:
            images.add(info["normal"])
            texture = _name(info["normal"]) + ".png"
            lines += [
                "      rtshader_system",
                "      {",
                "        lighting_stage normal_map "
                f"textures/{texture} tangent_space 0",
                "      }",
            ]
        lines += ["    }", "  }", "}", ""]
    (out / "settlement.material").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    (out / "textures").mkdir(exist_ok=True)
    for name in sorted(images):
        image = bpy.data.images[name]
        original, format_ = image.filepath_raw, image.file_format
        try:
            image.filepath_raw = str(out / "textures" / (_name(name) + ".png"))
            image.file_format = "PNG"
            image.save()
        finally:
            image.filepath_raw, image.file_format = original, format_


@contextmanager
def _authored_visibility(collection):
    states = []
    for obj in collection.all_objects:
        role = obj.get("settlement_part", "")
        part = obj.get("house_part", "")
        if obj.type != "MESH" or role in EXCLUDE:
            continue
        if part in ("cutaway_walls", "label"):
            continue
        if role.startswith("castle_") or part:
            states.append((obj, obj.hide_get(), obj.hide_viewport))
    # Visibility changes can invalidate Blender's collection iterator.
    try:
        for obj, hidden, viewport in states:
            if viewport:
                obj.hide_viewport = False
            if hidden:
                obj.hide_set(False)
        bpy.context.view_layer.update()
        yield
    finally:
        for obj, hidden, viewport in states:
            if hidden:
                obj.hide_set(True)
            if viewport:
                obj.hide_viewport = True
        bpy.context.view_layer.update()


def export_settlement(collection, root, directory):
    """Export full floors, excluding labels and preview cutaways."""
    with _authored_visibility(collection):
        return _export_settlement(collection, root, directory)


def _civic_metadata(collection, out):
    markers, lights = [], []
    for obj in sorted(collection.all_objects, key=lambda o: o.name):
        role = obj.get("settlement_part")
        if role == "civic_anchor":
            matrix = AXIS @ obj.matrix_world @ AXIS.inverted()
            position, rotation, _ = matrix.decompose()
            base = obj.get("reserved_size", (1, 1, 1))
            parent_scale = obj.parent.matrix_world.to_scale()
            size = (
                base[0] * abs(parent_scale.x),
                base[2] * abs(parent_scale.z),
                base[1] * abs(parent_scale.y),
            )
            prefix = obj.parent.get("world_site_id")
            identifier = obj["civic_id"]
            if prefix:
                identifier = f"{prefix}/{identifier}"
            markers.append(
                {
                    "id": identifier,
                    "kind": obj["civic_kind"],
                    "position": tuple(position),
                    "rotation": tuple(rotation),
                    "size": size,
                    "variant": obj["variant"],
                    "placeholder": bool(obj.get("engine_asset_anchor")),
                }
            )
        elif role == "civic_light":
            lights.append(
                {
                    "id": obj.name,
                    "position": tuple(AXIS @ obj.matrix_world.translation),
                    "color": tuple(obj.data.color),
                    "range": 9 * max(obj.matrix_world.to_scale()),
                }
            )
        if role == "civic_anchor" and obj.get("effect_anchor"):
            markers[-1]["effect"] = {
                "kind": obj["effect_anchor"],
                "position": tuple(
                    AXIS
                    @ (obj.matrix_world @ Vector((0, 0, obj["effect_height"])))
                ),
            }
    (out / "markers.json").write_text(
        json.dumps(
            {
                "coordinate_space": "ogre_world_y_up",
                "assets": markers,
                "lights": lights,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    rows = ["# id kind position_xyz quaternion_wxyz size_xyz variant"]
    for m in markers:
        if m["placeholder"]:
            rows.append(
                "\t".join(
                    map(
                        str,
                        (
                            m["id"],
                            m["kind"],
                            *m["position"],
                            *m["rotation"],
                            *m["size"],
                            m["variant"],
                        ),
                    )
                )
            )
    (out / "asset_markers.tsv").write_text(
        "\n".join(rows) + "\n", encoding="utf-8"
    )
    rows = ["# id position_xyz rgb range"]
    for light in lights:
        rows.append(
            "\t".join(
                map(
                    str,
                    (
                        light["id"],
                        *light["position"],
                        *light["color"],
                        light["range"],
                    ),
                )
            )
        )
    (out / "street_lights.tsv").write_text(
        "\n".join(rows) + "\n", encoding="utf-8"
    )
    return markers, lights


def _world_metadata(root, out):
    sites = json.loads(root["world_sites_json"])

    def position(point):
        return tuple(AXIS @ (root.matrix_world @ Vector(point)))

    for site in sites:
        site["centre"] = position(site["centre"])
        site["deck_path"] = [position(point) for point in site["deck_path"]]
        feature = site["landmark"]
        if feature:
            deck = site["deck_path"]
            feature["start"], feature["end"] = deck[0], deck[-1]
            feature["water_level"] = position((0, 0, feature["water_level"]))[
                1
            ]
    path = out / "world.json"
    path.write_text(
        json.dumps(
            {"coordinate_space": "ogre_world_y_up", "sites": sites},
            indent=2,
        ),
        encoding="utf-8",
    )
    return path.name


def _export_settlement(collection, root, directory):
    out = Path(directory).resolve()
    marker = out / ".procedural_asset_package"
    if out.exists() and any(out.iterdir()) and not marker.exists():
        raise ValueError(
            "비어 있는 폴더나 이전 OGRE 에셋 출력 폴더를 선택하세요"
        )
    out.mkdir(parents=True, exist_ok=True)
    marker.write_text("medieval_game_assets_v1\n", encoding="utf-8")
    (out / "meshes").mkdir(exist_ok=True)
    registry, assets, nodes, mesh_cache = {}, {}, [], {}
    atlas_tile = "atlas_tile_ids" in root
    collision_vertices, collision_triangles, collision_lookup = [], [], {}

    def collision(point):
        key = tuple(round(v, 5) for v in point)
        if key not in collision_lookup:
            collision_lookup[key] = len(collision_vertices)
            collision_vertices.append(tuple(point))
        return collision_lookup[key]

    for obj, world, depsgraph in _instances(collection):
        mesh_key = (
            obj.data.as_pointer(),
            obj.original.as_pointer() if obj.modifiers else 0,
            tuple(
                s.material.as_pointer() if s.material else 0
                for s in obj.material_slots
            ),
        )
        mesh = obj.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
        try:
            if mesh_key not in mesh_cache:
                sections = _sections(obj, mesh, registry)
                chunk_size = obj.get("export_chunk_size")
                mesh_cache[mesh_key] = (
                    _chunks(sections, chunk_size or 64)
                    if chunk_size
                    or obj.get("roads_integrated")
                    or obj.get("settlement_part") == "grass"
                    else [(sections, (0, 0, 0))]
                )
            matrix = AXIS @ world @ AXIS.inverted()
            for sections, origin in mesh_cache[mesh_key]:
                payload = encode_mesh(sections)
                digest = hashlib.sha256(payload).hexdigest()[:20]
                stem = "meshes/mesh_" + digest
                if stem not in assets:
                    (out / (stem + ".ogregeom")).write_bytes(payload)
                    if not atlas_tile:
                        write_mesh_xml(out / (stem + ".mesh.xml"), sections)
                    points = [v[:3] for s in sections for v in s.vertices]
                    assets[stem] = {
                        "vertices": sum(len(s.vertices) for s in sections),
                        "triangles": sum(
                            len(s.indices) // 3 for s in sections
                        ),
                        "bounds_min": [
                            min(p[i] for p in points) for i in range(3)
                        ],
                        "bounds_max": [
                            max(p[i] for p in points) for i in range(3)
                        ],
                    }
                transform = matrix @ Matrix.Translation(origin)
                position, rotation, scale = transform.decompose()
                nodes.append(
                    {
                        "name": f"asset_{len(nodes):05d}",
                        "source": obj.name,
                        "mesh": stem,
                        "position": tuple(position),
                        "rotation": tuple(rotation),
                        "scale": tuple(scale),
                    }
                )
                if atlas_tile and (effect := obj.get("atlas_effect")):
                    nodes[-1]["effect"] = effect
                    nodes[-1]["water_id"] = obj.get("water_id", "-")
            if not obj.get("collision_enabled", True):
                continue
            collision_mesh = obj.original.data if atlas_tile else mesh
            collision_mesh.calc_loop_triangles()
            for tri in collision_mesh.loop_triangles:
                points = [
                    AXIS @ (world @ collision_mesh.vertices[i].co)
                    for i in tri.vertices
                ]
                if (points[1] - points[0]).cross(
                    points[2] - points[0]
                ).length < 1e-8:
                    continue
                collision_triangles.append(tuple(collision(p) for p in points))
        finally:
            obj.to_mesh_clear()
    _write_materials(out, registry)
    write_scene(
        out / "settlement.scene", [n for n in nodes if "effect" not in n]
    )
    rows = ["# PGEO scene v1; metres; +Y up; right-handed; quaternion wxyz"]
    effects = [
        "# PGEO effects v1; ordinary node fields followed by type and water ID"
    ]
    for node in nodes:
        fields = [
            node["name"],
            node["mesh"],
            *node["position"],
            *node["rotation"],
            *node["scale"],
        ]
        if "effect" in node:
            fields.extend((node["effect"], node["water_id"]))
            effects.append("\t".join(str(v) for v in fields))
        else:
            rows.append("\t".join(str(v) for v in fields))
    (out / "settlement.tsv").write_text(
        "\n".join(rows) + "\n", encoding="utf-8"
    )
    if atlas_tile:
        (out / "effects.tsv").write_text(
            "\n".join(effects) + "\n", encoding="utf-8"
        )
    write_collision(
        out / "static.collision.bin", collision_vertices, collision_triangles
    )
    navigation = json.loads(root["plan_json"])["navigation"]
    for node in navigation["nodes"]:
        node["position"] = tuple(
            AXIS @ (root.matrix_world @ Vector(node["position"]))
        )
    for poi in navigation["points_of_interest"]:
        poi["position"] = tuple(
            AXIS @ (root.matrix_world @ Vector(poi["position"]))
        )
        if "front" in poi:
            poi["front"] = tuple(
                AXIS.to_3x3()
                @ root.matrix_world.to_3x3()
                @ Vector(poi["front"])
            )
        if "access_point" in poi:
            poi["access_point"] = tuple(
                AXIS @ (root.matrix_world @ Vector(poi["access_point"]))
            )
        if atlas_tile and "size" in poi:
            width, depth, height = poi["size"]
            poi["size"] = (width, height, depth)
    for edge in navigation["edges"]:
        if "path" in edge:
            edge["path"] = [
                tuple(AXIS @ (root.matrix_world @ Vector(p)))
                for p in edge["path"]
            ]
    for obstacle in navigation.get("obstacles", ()):
        obstacle["position"] = tuple(
            AXIS @ (root.matrix_world @ Vector(obstacle["position"]))
        )
        scale = root.matrix_world.to_scale()
        obstacle["radius"] *= max(abs(scale.x), abs(scale.y))
        obstacle["height"] *= abs(scale.z)
    navigation["coordinate_space"] = "ogre_world_y_up"
    (out / "navigation.json").write_text(
        json.dumps(navigation, indent=2), encoding="utf-8"
    )
    markers, lights = _civic_metadata(collection, out)
    if atlas_tile:
        records = ["# ATLAS interactions v1"]
        for poi in navigation["points_of_interest"]:
            fields = (
                poi["id"],
                poi["kind"],
                *poi["position"],
                *poi.get("size", (0, 0, 0)),
                poi.get("seal", "-"),
            )
            records.append("\t".join(map(str, fields)))
        (out / "interactions.tsv").write_text(
            "\n".join(records) + "\n", encoding="utf-8"
        )
    manifest = {
        "schema_version": 2,
        "generator": "medieval_game_assets",
        "units": "metres",
        "axis": "+Y up, right-handed",
        "blender_to_ogre": "(x,y,z) -> (x,z,-y)",
        "meshes": assets,
        "nodes": nodes,
        "materials": registry,
        "markers": markers,
        "lights": lights,
        "collision": {
            "file": "static.collision.bin",
            "vertices": len(collision_vertices),
            "triangles": len(collision_triangles),
            "static_only": True,
        },
        "statistics": {
            "unique_meshes": len(assets),
            "instances": len(nodes),
            "unique_triangles": sum(a["triangles"] for a in assets.values()),
            "scene_triangles": sum(
                assets[n["mesh"]]["triangles"] for n in nodes
            ),
        },
    }
    if root.get("is_world_root"):
        manifest["world"] = _world_metadata(root, out)
    if atlas_tile:
        manifest["environment"] = {
            "scene": "effects.tsv",
            "interactions": "interactions.tsv",
        }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    (out / "resources.cfg").write_text(
        "[ProceduralTown]\nFileSystem=.\n", encoding="utf-8"
    )
    source = Path(__file__).parent / "ogre" / "ProceduralAssets.hpp"
    (out / "ProceduralAssets.hpp").write_text(
        source.read_text(encoding="utf-8"), encoding="utf-8"
    )
    guide = Path(__file__).parent / "GAME_ASSETS.md"
    (out / "README.md").write_text(
        guide.read_text(encoding="utf-8"), encoding="utf-8"
    )
    guides = ["CIVIC.md", "CASTLE_INTERIOR.md"]
    if root.get("is_world_root"):
        guides.append("WORLD.md")
    for name in guides:
        source = Path(__file__).parent / name
        (out / name).write_text(
            source.read_text(encoding="utf-8"), encoding="utf-8"
        )
    return manifest
