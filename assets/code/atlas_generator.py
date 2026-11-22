"""Write the atlas index, streamable terrain and Blender tiles."""

import html
import json
import shutil
import struct
from hashlib import sha256
from itertools import pairwise
from pathlib import Path

from atlas_places import Landscape, atlas_paths, clip_segment, furnish_atlas
from atlas_rules import (
    ENVIRONMENTS,
    TILE,
    default_focus,
    plan_atlas,
    stable_seed,
)

CODE = Path(__file__).parent
TERRAIN_STEP = 16


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def atlas_svg(plan):
    width, height = plan["tile_shape"]
    extent = width * 14, height * 14
    sx, sy = plan["size_m"]

    def point(x, y):
        return (x / sx + 0.5) * extent[0], (0.5 - y / sy) * extent[1]

    title = html.escape(plan.get("title", "Procedural Atlas"))
    chunks = [
        '<svg xmlns="http://www.w3.org/2000/svg" role="img" '
        f'viewBox="0 0 {extent[0]} {extent[1]}" aria-label="{title}">'
    ]
    for tile in plan["tiles"]:
        i, j = tile["cell"]
        sky = tile["climate"]
        hue = "59909f" if sky["water"] else ENVIRONMENTS[sky["biome"]][3]
        chunks.append(
            f'<rect x="{i * 14}" y="{(height - 1 - j) * 14}" '
            f'width="14" height="14" fill="#{hue}"/>'
        )
    for r in plan["routes"]:
        points = " ".join(
            f"{a:.1f},{b:.1f}"
            for x, y, z in r["points"]
            for a, b in (point(x, y),)
        )
        chunks.append(
            f'<polyline points="{points}" fill="none" '
            'stroke="#f3dfb7" stroke-width="1.1" opacity=".72"/>'
        )
    for dungeon in plan["dungeons"]:
        x, y = point(*dungeon["entrance"][:2])
        name = html.escape(dungeon["id"])
        chunks.append(
            f'<path d="M{x:.1f},{y - 4:.1f}l4,4 -4,4 -4,-4z" '
            f'fill="#714c66"><title>{name}</title></path>'
        )
    for site in reversed(plan["sites"]):
        x, y = point(*site["centre"][:2])
        capital = site["rank"] == "CAPITAL"
        name = html.escape(site["name"])
        r = 4.0 if capital else 2.6 if site["rank"] == "CITY" else 1.65
        chunks.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="#34342b" '
            'stroke="#ffedd3" stroke-width=".8">'
            f"<title>{name}</title></circle>"
        )
        if capital:
            chunks.append(
                f'<text x="{x + 6:.1f}" y="{y + 4:.1f}" font-size="12" '
                'fill="#332b24" stroke="#f8e6c4" stroke-width="2" '
                f'paint-order="stroke" font-family="sans-serif">{name}</text>'
            )
    chunks.append("</svg>")
    return "\n".join(chunks)


def _road_rows(atlas, plan):
    rendered = set()
    for road in sorted(atlas_paths(plan), key=lambda r: -r["width"]):
        for a, b in pairwise(road["points"]):
            key = tuple(sorted(tuple(round(v, 3) for v in p) for p in (a, b)))
            if key in rendered:
                continue
            rendered.add(key)
            i, j = atlas.cell(min(a[0], b[0]), min(a[1], b[1]))
            m, n = atlas.cell(max(a[0], b[0]), max(a[1], b[1]))
            for col in range(i, m + 1):
                for row in range(j, n + 1):
                    x, y = atlas.corner(col, row)
                    if not (
                        p := clip_segment(a, b, (x, y, x + TILE, y + TILE))
                    ):
                        continue
                    u, v = p
                    wet = atlas.water_at(
                        *(0.5 * (u[k] + v[k]) for k in range(2))
                    )
                    yield (
                        "R",
                        col,
                        row,
                        road["width"],
                        int(wet is not None),
                        *(
                            round(q[k] * (-1 if k == 1 else 1), 4)
                            for q in p
                            for k in (0, 2, 1)
                        ),
                    )


def _table(path, atlas, plan):
    sx, sy = plan["size_m"]
    rows = [f"ATLAS\t2\t{plan['seed']}\t{sx}\t{sy}\t{TILE}"]
    weather = {t["id"]: t["weather"] for t in plan["themes"]}
    for tile in plan["tiles"]:
        i, j = tile["cell"]
        c = tile["climate"]
        row = (
            "T",
            i,
            j,
            tile["centre_z"],
            c["biome"],
            weather[tile["theme"][0]],
            tile["fog"],
            c["retention"],
            c["exposure"],
            c["water"] or "-",
            *c["monthly_c"],
            *c["monthly_mm"],
        )
        rows.append("\t".join(map(str, row)))
    for site in plan["sites"]:
        x, y, z = site["centre"]
        rows.append(f"N\t{site['id']}\t{x}\t{z}\t{-y}\t{site['rank']}")
    for route in plan["routes"]:
        rows.append(
            f"E\t{route['from']}\t{route['to']}\tALWAYS\t{route['length_m']}"
        )
    for d in plan["dungeons"]:
        x, y, z = d["entrance"]
        rows.append(f"D\t{d['id']}\t{d['kind']}\t{x}\t{z}\t{-y}\t{d['seal']}")
    for f in plan["features"]:
        if f["kind"] == "FOG_BASIN":
            continue
        row = (
            "W",
            f["id"],
            f["kind"],
            f.get("depth_m", 0),
            f.get("salinity", 0),
            int(f.get("seasonal", False)),
            f.get("outlet_id", "-"),
        )
        rows.append("\t".join(map(str, row)))
    for rule in plan.get("seasonal_links", ()):
        x, y, z = rule["gate"]
        row = (
            "E",
            rule["from"],
            rule["to"],
            rule["condition"],
            rule["length_m"],
            x,
            z,
            -y,
        )
        rows.append("\t".join(map(str, row)))
    rows.extend("\t".join(map(str, row)) for row in _road_rows(atlas, plan))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _terrain(path, atlas, plan):
    """Row-major xyz height and baseline water level for runtime LOD."""
    sx, sy = atlas.size
    w, h = sx // TERRAIN_STEP + 1, sy // TERRAIN_STEP + 1
    land = Landscape(atlas, plan)
    record = struct.Struct("<ffBBBB")
    part = path.with_suffix(".part")
    biome_ids = list(ENVIRONMENTS)
    with part.open("wb") as stream:
        stream.write(
            struct.pack(
                "<8sIIfff",
                b"PTIL\x02\x00\x00\x00",
                w,
                h,
                *atlas.origin,
                TERRAIN_STEP,
            )
        )
        for j in range(h):
            y = atlas.origin[1] + j * TERRAIN_STEP
            words = bytearray()
            for i in range(w):
                x = atlas.origin[0] + i * TERRAIN_STEP
                z = land.height(x, y)
                water = atlas.potential_water(x, y)
                biome = atlas.region_weights(x, y)[0][1]
                wet_type = 1 if water else 0
                if water and water[2] == "SEA":
                    wet_type = 2
                if water and water[2] == "CANYON":
                    wet_type = 3
                words.extend(
                    record.pack(
                        z,
                        water[0] if water else 0,
                        biome_ids.index(biome),
                        wet_type,
                        0,
                        0,
                    )
                )
            stream.write(words)
    part.replace(path)


def _write_index(out, atlas, plan, *, terrain=True):
    marker = out / ".procedural_atlas"
    if out.exists() and any(out.iterdir()) and not marker.is_file():
        raise ValueError(f"Use an empty atlas output folder: {out}")
    out.mkdir(parents=True, exist_ok=True)
    tiles = out / "tiles"
    tiles.mkdir(exist_ok=True)
    if tiles.resolve() != tiles:
        raise ValueError("Atlas tiles must be inside the output folder")
    old = marker.read_text() if marker.exists() else ""
    values = dict(atlas.blueprint)
    if atlas.art_style == "CARTOON":
        # Preserve the atlas identity for the original --toon alias.
        values.pop("art_style", None)
    blueprint = json.dumps(values, sort_keys=True, ensure_ascii=False)
    identity = (
        f"medieval_atlas_v2 {atlas.seed} {atlas.size[0]} {atlas.size[1]} "
        f"{stable_seed(blueprint):08x}"
    )
    if old and old.strip() != identity:
        raise ValueError("Use a separate output folder for a different atlas")
    marker.write_text(identity + "\n", encoding="utf-8")
    stamp = sha256(identity.encode())
    for name in ("atlas_rules.py", "atlas_places.py", "atlas_generator.py"):
        stamp.update((CODE / name).read_bytes())
    stamp_path = out / ".terrain_inputs"
    terrain_id = stamp.hexdigest()
    terrain_current = (
        (out / "terrain.ptil").is_file()
        and stamp_path.is_file()
        and stamp_path.read_text() == terrain_id
    )
    if terrain and not terrain_current:
        _terrain(out / "terrain.ptil", atlas, plan)
        stamp_path.write_text(terrain_id, encoding="ascii")
    _json(out / "atlas.json", plan)
    _table(out / "atlas.tsv", atlas, plan)
    ogre = out / "ogre"
    ogre.mkdir(exist_ok=True)
    for path in (CODE / "ogre").iterdir():
        if path.is_file() and path.suffix in (".hpp", ".glsl", ".cpp", ".txt"):
            shutil.copyfile(path, ogre / path.name)


def _tile_revision(out, bpy):
    contents = sha256((out / ".terrain_inputs").read_bytes())
    contents.update(bpy.app.version_string.encode())
    for code in sorted(CODE.glob("*.py")):
        contents.update(code.read_bytes())
    return contents.hexdigest()


def _export_tile(collection, root, directory, revision, export):
    package_marker = ".procedural_asset_package"
    if directory.exists() and (
        directory.resolve() != directory
        or not (directory / package_marker).is_file()
    ):
        raise ValueError(
            f"Use an empty or generated tile directory: {directory}"
        )
    ready = directory / ".atlas_bake"
    ready.unlink(missing_ok=True)
    manifest = export(collection, root, directory)
    used = {f"{name}.ogregeom" for name in manifest["meshes"]}
    meshes = directory / "meshes"
    if meshes.resolve() == meshes:
        for old in meshes.glob("mesh_*.ogregeom"):
            if old.relative_to(directory).as_posix() not in used:
                old.unlink()
    ready.write_text(revision, encoding="ascii")


def run_blueprint(args, blueprint, bpy, base_dir=None):
    atlas, plan = plan_atlas(blueprint, args.seed, base_dir=base_dir)
    furnish_atlas(atlas, plan)
    if args.layout_output:
        _json(args.layout_output, plan)
    if args.map:
        args.map.parent.mkdir(parents=True, exist_ok=True)
        args.map.write_text(atlas_svg(plan), encoding="utf-8")
    if args.ogre_output:
        out = args.ogre_output.resolve()
        _write_index(out, atlas, plan)
    print("ATLAS_PLAN", json.dumps(plan["report"]), flush=True)
    if not (
        args.render
        or args.output
        or (args.ogre_output and not args.atlas_index_only)
    ):
        return
    if bpy is None:
        raise ValueError("Blender is required to bake atlas tiles")
    from atlas_blender import build_atlas, choose_tiles, meadow_view, preview
    from ogre_export import export_settlement

    focus = args.focus or (None if args.tile else default_focus(plan))
    cells = choose_tiles(atlas, plan, args.tile, focus)
    if args.ogre_output and not args.atlas_index_only:
        revision = _tile_revision(out, bpy)
        game_cells = cells
        if args.all_sites:
            game_cells = {
                cell
                for place in (*plan["sites"], *plan["dungeons"])
                for cell in choose_tiles(atlas, plan, (), place["id"])
            }
        for cell in sorted(game_cells):
            directory = out / "tiles" / f"{cell[0]}_{cell[1]}"
            marker = directory / ".atlas_bake"
            if marker.is_file() and marker.read_text() == revision:
                continue
            print(f"ATLAS_TILE {cell[0]},{cell[1]}", flush=True)
            collection, root = build_atlas(atlas, plan, {cell}, game=True)
            try:
                _export_tile(
                    collection, root, directory, revision, export_settlement
                )
            finally:
                objects = list(collection.all_objects)
                children = list(collection.children_recursive)
                meshes = {obj.data for obj in objects if obj.type == "MESH"}
                materials = {m for mesh in meshes for m in mesh.materials if m}
                for obj in objects:
                    bpy.data.objects.remove(obj, do_unlink=True)
                for child in reversed(children):
                    bpy.data.collections.remove(child)
                bpy.data.collections.remove(collection)
                for mesh in meshes:
                    if not mesh.users:
                        bpy.data.meshes.remove(mesh)
                for material in materials:
                    if not material.users:
                        bpy.data.materials.remove(material)
    if args.render or args.output:
        meadow = meadow_view(atlas, plan, focus) if args.meadow_view else None
        if meadow:
            i, j = atlas.cell(meadow[0] - 42, meadow[1] - 42)
            u, v = atlas.cell(meadow[0] + 42, meadow[1] + 42)
            cells.update(
                (x, y) for x in range(i, u + 1) for y in range(j, v + 1)
            )
        backdrop = (
            {
                (i + dx, j + dy)
                for i, j in cells
                for dx, dy in ((-1, 0), (1, 0), (0, 1), (0, -1))
                if 0 <= i + dx < atlas.shape[0]
                and 0 <= j + dy < atlas.shape[1]
            }
            if any(s["id"] == focus for s in plan["sites"])
            else set()
        )
        collection, root = build_atlas(
            atlas, plan, cells, meadow=meadow, backdrop=backdrop
        )
        preview(collection, root, atlas, plan, cells, focus, meadow=meadow)
        if args.render:
            args.render.resolve().parent.mkdir(parents=True, exist_ok=True)
            bpy.context.scene.render.filepath = str(args.render.resolve())
        if args.output:
            args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
            bpy.ops.wm.save_as_mainfile(
                filepath=str(args.output.resolve()), compress=True
            )
        if args.render:
            bpy.ops.render.render(write_still=True)
