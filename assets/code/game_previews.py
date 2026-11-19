"""Render an existing game city from an overview and a street camera."""

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))

import settlement_blender as builder
from settlement_rules import SettlementConfig, make_settlement


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--prefix", default="game")
    parser.add_argument("--interiors", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    collection = next(c for c in bpy.data.collections if builder.root_for(c))
    root = builder.root_for(collection)
    config = SettlementConfig(**json.loads(root["config_json"]))
    plan = make_settlement(config)
    builder.preview_stage(plan, collection, root)
    scene = bpy.context.scene
    camera = scene.camera
    camera.data.ortho_scale *= 0.72
    scene.render.filepath = str(directory / (args.prefix + "_city.png"))
    bpy.ops.render.render(write_still=True)

    mesh = next(
        o.data for o in collection.objects if o.get("roads_integrated")
    )
    kind = mesh.attributes["surface_kind"]
    road_faces = [p for p in mesh.polygons if kind.data[p.index].value >= 2]
    grades = sorted(
        math.hypot(p.normal.x, p.normal.y) / max(1e-7, abs(p.normal.z))
        for p in road_faces
    )
    print("PAVING_GRADES", grades[len(grades) // 2], grades[-1], flush=True)
    road = max(
        (r for r in plan.roads if r.kind == "PRIMARY"),
        key=lambda r: sum(
            math.dist(a, b)
            for a, b in zip(r.points, r.points[1:], strict=False)
        ),
    )
    i = len(road.points) // 2
    point = Vector(road.points[i])
    tangent = Vector(road.points[min(i + 2, len(road.points) - 1)]) - point
    tangent.z = 0
    tangent.normalize()
    normal = Vector((-tangent.y, tangent.x, 0))
    camera.location = point - tangent * 13 + normal * 1.2 + Vector((0, 0, 2.4))
    target = point + tangent * 16 + Vector((0, 0, 2.6))
    camera.data.type = "PERSP"
    camera.data.lens = 32
    camera.rotation_euler = (
        (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    )
    scene.render.filepath = str(directory / (args.prefix + "_street.png"))
    bpy.ops.render.render(write_still=True)
    for kind, label, span in (("FOUNTAIN", "plaza", 11), ("WELL", "well", 8)):
        marker = next(
            (o for o in collection.objects if o.get("civic_kind") == kind),
            None,
        )
        if marker is None:
            continue
        camera = scene.camera
        target = marker.matrix_local @ Vector((0, 0, 1.25))
        camera.location = marker.matrix_local @ Vector((6, -8, 5.6))
        camera.data.type = "ORTHO"
        camera.data.ortho_scale = span * marker.scale.x
        camera.rotation_euler = (
            (target - camera.location).to_track_quat("-Z", "Y").to_euler()
        )
        scene.render.filepath = str(
            directory / (args.prefix + "_" + label + ".png")
        )
        bpy.ops.render.render(write_still=True)
    if args.interiors and plan.castle and plan.castle.interior:
        for level in (0, 2):
            builder.preview_castle_level(
                plan, collection, root, f"core_{level}"
            )
            scene.render.filepath = str(
                directory / (args.prefix + f"_interior_{level}.png")
            )
            bpy.ops.render.render(write_still=True)
        bpy.ops.wm.save_as_mainfile(
            filepath=str(directory / (args.prefix + "_interiors.blend"))
        )


if __name__ == "__main__":
    main()
