"""Verify shared landscape seams, deck collision and world export."""

import argparse
import json
import math
import sys
from collections import defaultdict
from itertools import pairwise
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE))

from game_asset_format import decode_mesh, read_collision  # noqa: E402
from ogre_export import export_settlement  # noqa: E402
from world_blender import build_world  # noqa: E402
from world_generator import PRESET, _read_config, _world_root, register  # noqa: E402
from world_rules import make_world  # noqa: E402
from world_terrain import Grid  # noqa: E402


def _edge_values(mesh, ring, origin):
    index = {
        v.index: (round(v.co.x + origin[0], 3), round(v.co.y + origin[1], 3))
        for v in mesh.vertices
    }
    count = defaultdict(int)
    for poly in mesh.polygons:
        for a, b in poly.edge_keys:
            count[a, b] += 1
    stitched = {
        tuple(sorted((index[a], index[b])))
        for (a, b), count in count.items()
        if count == 1 and index[a] in ring and index[b] in ring
    }
    height = {
        index[v.index]: v.co.z for v in mesh.vertices if index[v.index] in ring
    }
    return stitched, height


def _project(mesh):
    bvh = BVHTree.FromPolygons(
        [v.co for v in mesh.vertices], [p.vertices for p in mesh.polygons]
    )
    top = max(v.co.z for v in mesh.vertices) + 5

    def sample(x, y):
        point, *_ = bvh.ray_cast(Vector((x, y, top)), Vector((0, 0, -1)))
        return point.z if point is not None else None

    return sample


def verify_scene(collection, root, data):
    macro = next(
        o
        for o in collection.objects
        if o.get("settlement_part") == "world_terrain"
    )
    water = next(
        o
        for o in collection.objects
        if o.get("settlement_part") == "world_water"
    )
    assert water.data.polygons and not water["collision_enabled"]
    assert len(water.data.color_attributes["Color"].data) > 100
    assert macro.data.materials[0]["albedo_texture"] == "Meadow_Albedo"
    assert bpy.data.images["Meadow_Albedo"].packed_file is not None
    grid = Grid(tuple(data["config"]["size"]), data["config"]["terrain_step"])
    for site in data["sites"]:
        origin = site["centre"]
        child = next(
            c
            for c in collection.children
            if any(o.get("world_site_id") == site["id"] for o in c.objects)
        )
        town = next(o for o in child.objects if o.get("roads_integrated"))
        ring = {
            tuple(round(v, 3) for v in p)
            for p in grid.ring(site["bounding_cells"])
        }
        outside, base = _edge_values(macro.data, ring, (0, 0))
        inside, city = _edge_values(town.data, ring, origin)
        assert len(outside) == len(ring)
        assert inside == outside, site["id"]
        assert set(base) == set(city) == ring
        assert max(abs(base[p] - city[p]) for p in ring) < 0.0005
        deck = next(
            o
            for o in collection.objects
            if o.get("settlement_part") == "world_landmark"
            and o.get("site_id") == site["id"]
        )
        assert deck.get("collision_enabled", True)
        project = _project(deck.data)
        ground = _project(town.data)
        for a, b in pairwise(site["deck_path"]):
            for t in (0.17, 0.5, 0.83):
                x, y, z = (x + (y - x) * t for x, y in zip(a, b, strict=True))
                hit = project(x, y)
                assert hit is not None and abs(hit - z) < 0.018, (
                    site["id"],
                    z,
                    hit,
                )
                base = ground(x - origin[0], y - origin[1])
                assert base is None or base <= z + 0.13, (site["id"], z, base)
            assert abs(a[2] - b[2]) / math.dist(a[:2], b[:2]) <= 0.21
    assert root.get("grass_tufts", 0) > 1000
    grass = [
        o
        for o in collection.all_objects
        if o.get("settlement_part") == "grass"
    ]
    assert grass and all(not o["collision_enabled"] for o in grass)
    navigation = json.loads(root["plan_json"])["navigation"]
    assert navigation["surface_conformed"]
    assert len(navigation["suggested_spawns"]) == len(data["sites"])
    print(
        "WORLD_GEOMETRY_OK",
        len(data["sites"]),
        len(macro.data.polygons),
        len(water.data.polygons),
        len(grass),
        root["grass_tufts"],
        flush=True,
    )


def verify_export(collection, root, out):
    manifest = export_settlement(collection, root, out)
    metadata = json.loads((out / manifest["world"]).read_text())
    assert metadata["coordinate_space"] == "ogre_world_y_up"
    assert len(metadata["sites"]) == 4
    layout = json.loads(root["world_sites_json"])
    for source, target in zip(layout, metadata["sites"], strict=True):
        x, y, z = source["deck_path"][0]
        assert math.dist((x, z, -y), target["deck_path"][0]) < 0.001
    for stem, entry in manifest["meshes"].items():
        sections = decode_mesh((out / (stem + ".ogregeom")).read_bytes())
        assert sum(len(s.indices) // 3 for s in sections) == entry["triangles"]
    vertices, indices = read_collision(out / "static.collision.bin")
    assert len(indices) // 3 == manifest["collision"]["triangles"]
    assert len(vertices) // 3 == manifest["collision"]["vertices"]
    assert len(indices) // 3 < manifest["statistics"]["scene_triangles"]
    print("WORLD_OGRE_OK", manifest["statistics"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layout", type=Path)
    parser.add_argument("--ogre-output", type=Path)
    args = parser.parse_args(
        sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    )
    register()
    if args.layout is not None:
        collection = next(c for c in bpy.data.collections if _world_root(c))
        root = _world_root(collection)
        data = json.loads(args.layout.read_text(encoding="utf-8"))
    else:
        collection, root, plan = build_world(make_world(_read_config(PRESET)))
        data = plan.as_dict()
    verify_scene(collection, root, data)
    if args.ogre_output is not None:
        verify_export(collection, root, args.ogre_output.resolve())
