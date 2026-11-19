"""Hollow castle shells, accessible stairs and replaceable furniture."""

import math

import bpy

from castle_geometry import planar_regions
from castle_interior_rules import SLAB, stair_path
from castle_rules import castle_point
from fortification_blender import cylinder
from house_generator import MeshBatch
from house_rules import rectangle


def _wall(batch, wall, height=None):
    height = wall.height if height is None else min(height, wall.height)
    length = math.dist(wall.a, wall.b)
    tx, ty = (wall.b[0] - wall.a[0]) / length, (wall.b[1] - wall.a[1]) / length
    nx, ny = -ty, tx
    holes = []
    for opening in wall.openings:
        if all(wall.sides):
            holes.append(
                rectangle(
                    opening.start, opening.bottom, opening.end, opening.top
                )
            )
            continue
        radius = (opening.end - opening.start) / 2
        centre = (opening.start + opening.end) / 2
        spring = opening.top - radius
        holes.append(
            tuple(
                [
                    (opening.start, opening.bottom),
                    (opening.end, opening.bottom),
                ]
                + [
                    (
                        centre + radius * math.cos(i * math.pi / 10),
                        spring + radius * math.sin(i * math.pi / 10),
                    )
                    for i in range(11)
                ]
            )
        )
    panels = [
        polygon
        for _, polygon in planar_regions(
            (("wall", rectangle(0, 0, length, height)),), tuple(holes)
        )
    ]
    material = "interior_wall" if all(wall.sides) else "castle_stone"
    for polygon in panels:
        batch.prism(
            [
                (
                    wall.a[0] + tx * u - nx * wall.thickness / 2,
                    wall.a[1] + ty * u - ny * wall.thickness / 2,
                    wall.z + z,
                )
                for u, z in polygon
            ],
            (nx * wall.thickness, ny * wall.thickness, 0),
            material,
        )


def _low_walls(batch, level):
    strips = []
    for wall in level.walls:
        length = math.dist(wall.a, wall.b)
        tx, ty = (
            (wall.b[0] - wall.a[0]) / length,
            (wall.b[1] - wall.a[1]) / length,
        )
        spans = [(0, length)]
        for opening in wall.openings:
            if opening.bottom > 0:
                continue
            spans = [
                (a, b)
                for start, end in spans
                for a, b in (
                    (start, min(end, opening.start)),
                    (max(start, opening.end), end),
                )
                if b - a > 1e-5
            ]
        for start, end in spans:
            polygon = tuple(
                (wall.a[0] + tx * u - ty * v, wall.a[1] + ty * u + tx * v)
                for u, v in (
                    (start, -wall.thickness / 2),
                    (end, -wall.thickness / 2),
                    (end, wall.thickness / 2),
                    (start, wall.thickness / 2),
                )
            )
            strips.append(("wall", polygon))
    for _, polygon in planar_regions(tuple(strips)):
        batch.prism(
            [(*p, level.z) for p in polygon], (0, 0, 0.65), "interior_wall"
        )


def _stairs(batch, rails, stair):
    rise = (stair.top - stair.bottom) / stair.steps
    if stair.kind == "SPIRAL":
        x, y = stair.centre
        cylinder(
            batch,
            (x, y, stair.bottom),
            stair.inner,
            stair.top - stair.bottom,
            "stair_wood",
            12,
        )
        for i in range(stair.steps):
            angles = [
                stair.angle + math.radians(30 + n * 300 / stair.steps)
                for n in (i, i + 1)
            ]
            polygon = [
                (
                    x + r * math.cos(a),
                    y + r * math.sin(a),
                    stair.bottom + (i + 1) * rise,
                )
                for r, a in (
                    (stair.inner, angles[0]),
                    (stair.outer, angles[0]),
                    (stair.outer, angles[1]),
                    (stair.inner, angles[1]),
                )
            ]
            batch.prism(polygon, (0, 0, -min(0.14, rise * 0.8)), "stair_wood")
    else:
        n = stair.steps // 2
        x1, y1 = stair.polygon[0]
        x2, y2 = stair.polygon[2]
        for i in range(n):
            for x, y, step in (
                (x1 + stair.width / 2, y1 + (i + 0.5) * stair.tread, i + 1),
                (
                    x2 - stair.width / 2,
                    y2 - stair.landing - (i + 0.5) * stair.tread,
                    n + i + 1,
                ),
            ):
                height = step * rise
                batch.box(
                    (x, y, stair.bottom + height - 0.07),
                    (stair.width, stair.tread, 0.14),
                    "stair_wood",
                )
        height = n * rise
        batch.box(
            (
                (x1 + x2) / 2,
                y2 - stair.landing / 2,
                stair.bottom + height - 0.09,
            ),
            (x2 - x1, stair.landing, 0.18),
            "stair_wood",
        )
        for x in (x1 + 0.08, x1 + stair.width - 0.08):
            batch.beam(
                (x, y1 + stair.tread / 2, stair.bottom + rise - 0.12),
                (x, y2 - stair.landing, stair.bottom + height - 0.12),
                0.10,
                "stair_wood",
            )
        for x in (x2 - stair.width + 0.08, x2 - 0.08):
            batch.beam(
                (x, y2 - stair.landing, stair.bottom + height - 0.12),
                (x, y1 + stair.tread / 2, stair.top - 0.12),
                0.10,
                "stair_wood",
            )
        # Protect the slab opening and leave its landing front open.
        for x in (x1, x2):
            rails.beam(
                (x, y1, stair.top + 0.95),
                (x, y2, stair.top + 0.95),
                0.075,
                "timber",
            )
            for y in (y1, y2):
                rails.beam(
                    (x, y, stair.top), (x, y, stair.top + 0.95), 0.07, "timber"
                )
        rails.beam(
            (x1, y2, stair.top + 0.95),
            (x2, y2, stair.top + 0.95),
            0.075,
            "timber",
        )
    if stair.kind == "SPIRAL":
        path = stair_path(stair)[1:-1]
        for a, b in zip(path, path[1:], strict=False):
            vx, vy = a[0] - stair.centre[0], a[1] - stair.centre[1]
            length = math.hypot(vx, vy)
            px, py = (
                stair.centre[0] + vx / length * stair.outer,
                stair.centre[1] + vy / length * stair.outer,
            )
            wx, wy = b[0] - stair.centre[0], b[1] - stair.centre[1]
            length = math.hypot(wx, wy)
            qx, qy = (
                stair.centre[0] + wx / length * stair.outer,
                stair.centre[1] + wy / length * stair.outer,
            )
            rails.beam(
                (px, py, a[2] + 0.90), (qx, qy, b[2] + 0.90), 0.045, "timber"
            )


def furniture_batch(item, materials):
    """Simple silhouettes stay inside the exported asset dimensions."""
    batch = MeshBatch(item.id, materials)
    w, d, h = item.size
    kind = item.kind
    wood = "furniture_wood"
    if kind in (
        "banquet_table",
        "dining_table",
        "desk",
        "altar",
        "bench",
        "pew",
        "chair",
    ):
        seat = h * 0.50 if kind in ("chair", "pew") else h
        batch.box((0, 0, seat - 0.06), (w, d, 0.12), wood)
        for x in (-w * 0.39, w * 0.39):
            for y in (-d * 0.34, d * 0.34):
                batch.box(
                    (x, y, (seat - 0.12) / 2), (0.08, 0.08, seat - 0.12), wood
                )
        if kind in ("chair", "pew"):
            batch.box(
                (0, d * 0.42, seat + (h - seat) / 2), (w, 0.09, h - seat), wood
            )
    elif kind == "bed":
        batch.box((0, 0, h * 0.28), (w, d, h * 0.56), wood)
        batch.box(
            (0, 0, h * 0.68), (w * 0.94, d * 0.94, h * 0.32), "fabric_blue"
        )
        batch.box(
            (0, d * 0.32, h * 0.92),
            (w * 0.72, d * 0.25, h * 0.16),
            "fabric_cream",
        )
    elif kind == "sofa":
        batch.box((0, 0, h * 0.3), (w, d, h * 0.6), "fabric_red")
        batch.box((0, d * 0.40, h * 0.8), (w, d * 0.2, h * 0.4), "fabric_red")
    elif kind in ("shelf", "weapon_rack"):
        for x in (-w * 0.45, w * 0.45):
            batch.box((x, 0, h / 2), (w * 0.1, d, h), wood)
        for z in (0.08, h * 0.5, h - 0.05):
            batch.box((0, 0, z), (w, d, 0.08), wood)
        if kind == "weapon_rack":
            for x in (-w * 0.25, 0, w * 0.25):
                batch.beam((x, 0, h * 0.15), (x, 0, h * 0.95), 0.06, "metal")
    elif kind == "lamp":
        cylinder(batch, (0, 0, 0), w * 0.48, h * 0.15, "metal", 8)
        cylinder(batch, (0, 0, 0), w * 0.12, h * 0.75, "metal", 8)
        batch.box((0, 0, h * 0.83), (w * 0.65, d * 0.65, h * 0.34), "fire")
    elif kind == "barrel":
        cylinder(batch, (0, 0, 0), min(w, d) * 0.47, h, wood, 12)
        for z in (h * 0.2, h * 0.75):
            cylinder(batch, (0, 0, z), min(w, d) / 2, h * 0.06, "metal", 12)
    elif kind == "hearth":
        for x in (-w * 0.38, w * 0.38):
            batch.box(
                (x, 0, h * 0.38), (w * 0.24, d, h * 0.76), "castle_shade"
            )
        batch.box((0, 0, h * 0.88), (w, d, h * 0.24), "castle_trim")
        batch.box((0, 0, h * 0.12), (w * 0.48, d * 0.6, h * 0.20), "fire")
    else:
        batch.box((0, 0, h / 2), item.size, wood)
        if kind == "wardrobe":
            batch.box(
                (0, -d * 0.49, h / 2), (w * 0.04, d * 0.015, h * 0.9), "metal"
            )
    return batch


def interior_batches(castle, materials, window_frame):
    """Yield batches with roles, floor tags and object transforms."""
    layout = castle.interior
    for level in layout.levels:
        floor = MeshBatch("Castle_Floor_" + level.id, materials)
        for owner, polygon in level.regions:
            if owner == "stairwell":
                continue
            material = (
                "interior_floor"
                if level.id.startswith("core_")
                else "court_paving"
            )
            floor.prism(
                [(*p, level.z) for p in polygon], (0, 0, -SLAB), material
            )
        full = MeshBatch("Castle_Walls_" + level.id, materials)
        low = MeshBatch("Castle_Cutaway_" + level.id, materials)
        frames = MeshBatch("Castle_Frames_" + level.id, materials)
        for wall in level.walls if level.id != "courtyard" else ():
            _wall(full, wall)
            length = math.dist(wall.a, wall.b)
            tx, ty = (
                (wall.b[0] - wall.a[0]) / length,
                (wall.b[1] - wall.a[1]) / length,
            )
            nx, ny = (ty, -tx) if wall.sides[0] else (-ty, tx)
            if level.id == "rampart" and wall.height <= 1.0:
                count = max(1, round(length / 1.25))
                for i in range(count):
                    u = (i + 0.5) * length / count
                    full.box(
                        (
                            wall.a[0] + tx * u,
                            wall.a[1] + ty * u,
                            wall.z + 1.25,
                        ),
                        (length / count * 0.52, wall.thickness, 0.5),
                        "castle_trim",
                        ((tx, ty, 0), (-ty, tx, 0), (0, 0, 1)),
                    )
            for opening in wall.openings:
                u = (opening.start + opening.end) / 2
                interior_door = all(wall.sides)
                normal_offset = 0.0 if interior_door else wall.thickness / 2
                position = (
                    wall.a[0] + tx * u + nx * normal_offset,
                    wall.a[1] + ty * u + ny * normal_offset,
                    wall.z + opening.bottom,
                )
                window_frame(
                    frames,
                    position,
                    (tx, ty),
                    (nx, ny),
                    opening.end - opening.start,
                    opening.top - opening.bottom,
                    glazed=False,
                    mullion=opening.kind == "WINDOW",
                    border_width=max(
                        0.02, min(0.12, opening.start, length - opening.end)
                    ),
                    arched=not interior_door,
                    sill=not interior_door,
                    frame_depth=wall.thickness + 0.05
                    if interior_door
                    else 0.18,
                    frame_offset=0.0 if interior_door else 0.07,
                )
        if level.id != "courtyard":
            _low_walls(low, level)
        metadata = {
            "castle_level": level.id,
            "floor_index": level.index,
            "castle_z": level.z,
        }
        for role, batch in (
            ("floor", floor),
            ("wall", full),
            ("cutaway", low),
            ("frame", frames),
        ):
            batch.vertices = [
                castle_point(castle.centre, castle.keep_heading, p)
                for p in batch.vertices
            ]
            yield batch, "castle_" + role, metadata, None
    for stair in layout.stairs:
        batch = MeshBatch("Castle_" + stair.id, materials)
        rails = MeshBatch("Castle_Rails_" + stair.id, materials)
        _stairs(batch, rails, stair)
        metadata = {
            "castle_level": stair.lower,
            "upper_level": stair.upper,
            "stair_id": stair.id,
            "stair_kind": stair.kind,
            "castle_z": stair.bottom,
        }
        for role, mesh in (("stairs", batch), ("railing", rails)):
            mesh.vertices = [
                castle_point(castle.centre, castle.keep_heading, p)
                for p in mesh.vertices
            ]
            yield mesh, "castle_" + role, metadata, None
    for item in layout.furniture:
        metadata = {
            "castle_level": item.level,
            "room_id": item.room_id,
            "furniture_id": item.id,
            "furniture_kind": item.kind,
            "anchor_id": item.anchor_id,
            "asset_placeholder": True,
            "asset_origin": "BOTTOM_CENTER",
            "asset_front": "-Y",
            "size": item.size,
            "castle_z": item.position[2],
        }
        placement = (
            castle_point(castle.centre, castle.keep_heading, item.position),
            castle.keep_heading + item.heading,
        )
        if item.approach:
            metadata["approach_position"] = item.approach
        yield (
            furniture_batch(item, materials),
            "castle_furniture",
            metadata,
            placement,
        )


def room_labels(castle, collection, root, material, mark_owned):
    for room in castle.interior.rooms:
        curve = bpy.data.curves.new("Castle_Label_" + room.id, "FONT")
        curve.body = (
            "TOWER"
            if room.kind == "TOWER_LANDING"
            else room.kind.replace("_", "\n")
        )
        curve.align_x, curve.align_y = "CENTER", "CENTER"
        curve.size = 0.32
        curve.materials.append(material)
        obj = bpy.data.objects.new("Castle_Label_" + room.id, curve)
        collection.objects.link(obj)
        mark_owned(obj)
        mark_owned(curve)
        obj.parent = root
        obj.location = castle_point(
            castle.centre,
            castle.keep_heading,
            (*room.position[:2], room.position[2] + 0.025),
        )
        obj.rotation_euler.z = castle.keep_heading
        obj["settlement_part"] = "castle_label"
        obj["castle_level"] = room.level
        obj["room_id"] = room.id
        obj["castle_z"] = room.position[2]
        obj.hide_render = True
        obj.hide_set(True)


def show_level(collection, root, level=None):
    """Show an owned castle floor without changing its geometry."""
    generation = root["_settlement_generation"]
    for obj in collection.objects:
        if obj.get("_settlement_generation") != generation:
            continue
        part = obj.get("settlement_part", "")
        if not part.startswith("castle_"):
            continue
        if level is None:
            visible = part not in ("castle_cutaway", "castle_label")
        elif obj.get("castle_level") == level:
            visible = part not in ("castle_wall", "castle_frame")
        elif obj.get("upper_level") == level and part in (
            "castle_stairs",
            "castle_railing",
        ):
            visible = True
        else:
            visible = False
        obj.hide_render = not visible
        obj.hide_set(not visible)
