"""Draw interior plans as replaceable, labelled furniture proxies."""

import math

import bpy

from house_rules import rectangle, subtract_rectangle
from interior_rules import (
    FLOOR_OFFSET,
    PARTITION_THICKNESS,
    SLAB_THICKNESS,
    WALL_THICKNESS,
    floor_z,
)

OWNER_KEY = "_cartoon_house_owner"


def _tag(obj, part, floor):
    if obj is not None:
        obj["house_part"] = part
        obj["floor_index"] = floor
    return obj


def _partition(batch, partition, z, height):
    start = partition.door_y - partition.door_width / 2
    end = partition.door_y + partition.door_width / 2
    for a, b in ((partition.y1, start), (end, partition.y2)):
        batch.box(
            (partition.x, (a + b) / 2, z + height / 2),
            (PARTITION_THICKNESS, b - a, height),
            "partition",
        )
    if height > partition.door_height:
        lintel = height - partition.door_height
        batch.box(
            (
                partition.x,
                partition.door_y,
                z + partition.door_height + lintel / 2,
            ),
            (PARTITION_THICKNESS, partition.door_width, lintel),
            "partition",
        )


def _label(item, proxy, collection, material, owner):
    text = bpy.data.curves.new(f"CH_Label_{item.id}", "FONT")
    text.body = item.kind.replace("_", " ").upper()
    text.align_x, text.align_y = "CENTER", "CENTER"
    text.size = min(0.20, item.size[0] / (len(text.body) * 0.68))
    text.materials.append(material)
    obj = bpy.data.objects.new(f"CH_Label_{item.id}", text)
    collection.objects.link(obj)
    obj[OWNER_KEY] = owner
    _tag(obj, "label", item.floor)
    obj.parent = proxy
    obj.location = (0, 0, item.size[2] + 0.012)


def build_geometry(
    layout, house, config, collection, root, materials, batch_type
):
    """Build slabs, partitions, U-stairs and furniture proxies."""
    for floor in range(config.floors):
        z = floor_z(house, floor)
        slab = batch_type(f"Floor_{floor + 1}", materials, 0)
        boundary = layout.bounds
        pieces = [
            rectangle(boundary.x1, boundary.y1, boundary.x2, boundary.y2)
        ]
        for stair in layout.stairs:
            if stair.upper_floor == floor:
                hole = stair.bounds
                pieces = [
                    piece
                    for polygon in pieces
                    for piece in subtract_rectangle(
                        polygon, (hole.x1, hole.y1, hole.x2, hole.y2)
                    )
                ]
        for polygon in pieces:
            slab.prism(
                [(x, y, z) for x, y in polygon],
                (0, 0, -SLAB_THICKNESS),
                "floor",
            )
        _tag(slab.finish(collection, root), "floor", floor)
        full = batch_type(f"Partitions_{floor + 1}", materials, 0.008)
        low = batch_type(f"CutawayWalls_{floor + 1}", materials, 0.008)
        part_height = house.floor_height - SLAB_THICKNESS
        if config.roof_style == "FLAT" and floor == config.floors - 1:
            part_height -= FLOOR_OFFSET
        for partition in layout.partitions:
            if partition.floor == floor:
                _partition(full, partition, z, part_height)
                _partition(low, partition, z, 0.42)
        for wall in house.walls:
            spans = [(0, wall.length)]
            if floor == 0:
                for opening in wall.openings:
                    if opening.kind == "DOOR":
                        spans = [(0, opening.x1), (opening.x2, wall.length)]
            for start, end in spans:
                if not wall.tangent[0]:
                    start = max(start, WALL_THICKNESS)
                    end = min(end, wall.length - WALL_THICKNESS)
                centre = (
                    (
                        wall.start[0]
                        + wall.tangent[0] * (start + end) / 2
                        - wall.normal[0] * WALL_THICKNESS / 2
                    ),
                    (
                        wall.start[1]
                        + wall.tangent[1] * (start + end) / 2
                        - wall.normal[1] * WALL_THICKNESS / 2
                    ),
                    z + 0.21,
                )
                dimensions = (
                    (end - start, WALL_THICKNESS, 0.42)
                    if wall.tangent[0]
                    else (WALL_THICKNESS, end - start, 0.42)
                )
                low.box(centre, dimensions, "partition")
        _tag(full.finish(collection, root), "partition", floor)
        low_obj = _tag(low.finish(collection, root), "cutaway_walls", floor)
        if low_obj:
            low_obj.hide_render = True
            low_obj.hide_set(True)
    for stair in layout.stairs:
        batch = batch_type(stair.id, materials, 0.006)
        bounds = stair.bounds
        base = floor_z(house, stair.lower_floor)
        count = stair.steps_per_flight
        for i in range(count):
            height = (i + 1) * stair.rise
            batch.box(
                (
                    bounds.x1 + stair.flight_width / 2,
                    bounds.y1 + (i + 0.5) * stair.tread,
                    base + height / 2,
                ),
                (stair.flight_width, stair.tread, height),
                "stairs",
            )
            height = (count + i + 1) * stair.rise
            batch.box(
                (
                    bounds.x2 - stair.flight_width / 2,
                    bounds.y2 - stair.landing_depth - (i + 0.5) * stair.tread,
                    base + height / 2,
                ),
                (stair.flight_width, stair.tread, height),
                "stairs",
            )
        height = count * stair.rise
        batch.box(
            (
                (bounds.x1 + bounds.x2) / 2,
                bounds.y2 - stair.landing_depth / 2,
                base + height / 2,
            ),
            (bounds.width, stair.landing_depth, height),
            "stairs",
        )
        obj = _tag(batch.finish(collection, root), "stairs", stair.lower_floor)
        obj["connects_to_floor"] = stair.upper_floor
        obj["stairs_id"] = stair.id
        # Keep the upper landing's front open for arrival and departure.
        rail = batch_type(stair.id + "_rails", materials, 0.006)
        top = floor_z(house, stair.upper_floor)
        for x in (bounds.x1, bounds.x2):
            rail.box(
                (x, bounds.centre[1], top + 0.85),
                (0.055, bounds.depth, 0.07),
                "trim",
            )
            for y in (bounds.y1 + 0.08, bounds.y2 - 0.08):
                rail.box((x, y, top + 0.43), (0.055, 0.055, 0.86), "trim")
        rail.box(
            (bounds.centre[0], bounds.y2, top + 0.85),
            (bounds.width, 0.055, 0.07),
            "trim",
        )
        _tag(rail.finish(collection, root), "railing", stair.upper_floor)
    for item in layout.furniture:
        batch = batch_type(item.id, materials, min(config.bevel, 0.012))
        batch.box((0, 0, item.size[2] / 2), item.size, item.kind)
        proxy = _tag(batch.finish(collection, root), "furniture", item.floor)
        proxy.location = item.position
        proxy.rotation_euler.z = math.radians(item.rotation_z)
        proxy["furniture_id"] = item.id
        proxy["furniture_kind"] = item.kind
        proxy["room_id"] = item.room_id
        proxy["asset_placeholder"] = True
        proxy["size"] = item.size
        proxy["anchor_id"] = item.anchor_id
        proxy["asset_origin"] = "BOTTOM_CENTER"
        proxy["asset_front"] = "-Y"
        _label(item, proxy, collection, materials["label"], root[OWNER_KEY])


def show_floor(collection, root, floor=None):
    """Toggle a floor cutaway without modifying the generation plan."""
    for obj in collection.objects:
        if obj.get(OWNER_KEY) != root.get(OWNER_KEY):
            continue
        part = obj.get("house_part", "")
        if not part:
            continue
        if floor is None:
            visible = part != "cutaway_walls"
        elif part == "exterior" or part == "partition":
            visible = False
        else:
            visible = (
                obj.get("floor_index") == floor
                or part == "stairs"
                and obj.get("connects_to_floor") == floor
            )
        obj.hide_set(not visible)
        obj.hide_render = not visible
    root["visible_interior_floor"] = -1 if floor is None else floor
