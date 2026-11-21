"""Room shells, town buildings, working stairs and dungeon entrances."""

import colorsys
import json
import math
import random
from itertools import pairwise
from types import SimpleNamespace

import bpy
from mathutils import Vector

import house_generator as houses
import settlement_blender as towns
from atlas_places import HOUSING, facility_rooms, rectangle, shop_sockets
from castle_blender import _window, castle_batches
from castle_interior_blender import interior_batches
from castle_interior_rules import make_castle_interior
from castle_rules import castle_point, make_castle_architecture
from civic_blender import _lathe
from fortification_blender import cylinder
from house_rules import HouseConfig

UP = Vector((0, 0, 1))


class Buildings:
    def __init__(self, collection, root, materials, *, game=False):
        self.collection, self.root, self.materials = (
            collection,
            root,
            materials,
        )
        self.game = game
        self.nodes, self.edges, self.markers = {}, [], []

    def batch(self, name, bevel=0.0):
        return houses.MeshBatch(name, self.materials, bevel)

    def finish(self, batch, role, *, effect=None):
        ob = towns._finish(batch, self.collection, self.root, role)
        if ob and effect:
            ob["atlas_effect"] = effect
            ob["collision_enabled"] = False
        return ob

    def node(self, uid, position, kind):
        self.nodes[uid] = {
            "id": uid,
            "position": tuple(position),
            "kind": kind,
        }
        return uid

    def edge(self, a, b, points=None, *, condition="ALWAYS"):
        path = points or (self.nodes[a]["position"], self.nodes[b]["position"])
        self.edges.append(
            {
                "from": a,
                "to": b,
                "path": tuple(path),
                "condition": condition,
                "kind": "WALK",
            }
        )

    def marker(self, uid, kind, position, size, **data):
        self.markers.append(
            {
                "id": uid,
                "kind": kind,
                "position": tuple(position),
                "size": tuple(size),
                **data,
            }
        )

    def navigation(self):
        return {
            "nodes": list(self.nodes.values()),
            "edges": self.edges,
            "points_of_interest": self.markers,
        }


def _tint_roof(collection, seed):
    rng = random.Random(f"{seed}:fired_terracotta")
    hue, value = rng.uniform(-3, 3) / 360, rng.uniform(0.95, 1.05)
    materials = {
        slot.material
        for obj in collection.objects
        if obj.type == "MESH"
        for slot in obj.material_slots
        if slot.material
        and slot.material.name.split("_")[-1].startswith("roof")
        or slot.material
        and "_roof_" in slot.material.name
    }
    for material in materials:
        colour = material.diffuse_color
        srgb = tuple(
            c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
            for c in colour[:3]
        )
        h, s, v = colorsys.rgb_to_hsv(*srgb)
        rgb = colorsys.hsv_to_rgb((h + hue) % 1, s, min(1, v * value))
        linear = tuple(
            c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
            for c in rgb
        )
        material.diffuse_color = (*linear, colour[3])
        if surface := material.node_tree.nodes.get("Architecture Surface"):
            surface.inputs["Tint"].default_value = material.diffuse_color
        else:
            houses._principled_shader(material).inputs[
                "Base Color"
            ].default_value = material.diffuse_color


def _stairs(batch, start, end, width, material):
    x, y, z = start
    dx, dy, dz = (b - a for a, b in zip(start, end, strict=True))
    length = max(0.01, math.hypot(dx, dy))
    aim = Vector((dx / length, dy / length, 0))
    tangent = Vector((-aim.y, aim.x, 0))
    count = max(1, math.ceil(abs(dz) / 0.18))
    tread = length / count
    path = [start]
    for i in range(count):
        level = z + (i + 1) * dz / count
        t = (i + 0.5) / count
        batch.box(
            (x + dx * t, y + dy * t, level - 0.14),
            (width, tread + 0.006, 0.28),
            material,
            (tangent, aim, UP),
        )
        path.append((x + dx * t, y + dy * t, level))
    path.append(end)
    return tuple(path)


def house(stage, site, lot):
    uid = lot["id"]
    x, y, z = lot["centre"]
    width, depth = lot["size"]
    front = lot["front"]
    palette, wall, roof, pitch, overhang = HOUSING[site["biome"]]
    seed = lot["seed"] % 2_000_000_001
    config = HouseConfig(
        seed=seed,
        detail_seed=(seed + 143) % 2_000_000_001,
        interior_seed=(seed + 861) % 2_000_000_001,
        door_open=True,
        width=width,
        depth=depth,
        variation=0,
        floors=lot["floors"],
        floor_height=2.85,
        palette=palette,
        wall_style=wall,
        roof_style=roof,
        roof_pitch=pitch,
        overhang=overhang,
        bevel=0 if stage.game else 0.007,
        roof_tiles=site["rank"] == "CAPITAL" and not stage.game,
        interior=True,
        furnish=True,
    )
    raised = 0.80 if site["biome"] == "MARSH" else 0
    collection, root, plan = houses.build_house(
        config, location=(x, y, z + raised)
    )
    scene = bpy.context.scene
    stage.collection.children.link(collection)
    scene.collection.children.unlink(collection)
    collection.name = uid
    root.name = uid
    root.rotation_euler.z = 0 if front == 1 else math.pi
    root["atlas_building"] = uid
    _tint_roof(collection, seed)
    if stage.game:
        for ob in collection.objects:
            role = ob.get("house_geometry_role")
            if role in (
                "Cladding",
                "Timber",
                "WindowsAndDoor",
                "RoofTrim",
                "MedievalDetails",
            ):
                ob["collision_enabled"] = False
            if role == "Roof" and roof != "FLAT":
                for material in ob.data.materials:
                    material["atlas_roof_surface"] = True
    wall = plan.walls[0]
    opening = next(o for o in wall.openings if o.kind == "DOOR")
    along = (opening.x1 + opening.x2) * 0.5
    local_x = wall.start[0] + wall.tangent[0] * along
    local_y = wall.start[1] + wall.tangent[1] * along
    threshold = (x + front * local_x, y + front * local_y, z + raised + 0.30)
    landing = (threshold[0], threshold[1] - front * 0.32, threshold[2])
    foot = (threshold[0], threshold[1] - front * (1.1 + raised * 1.8), z)
    steps = stage.batch(uid + "_entry", 0.014)
    _stairs(steps, foot, landing, 1.25, "stair_wood")
    steps.box(
        (landing[0], landing[1] + front * 0.13, landing[2] - 0.07),
        (1.24, 0.44, 0.14),
        "stair_wood",
    )
    if raised:
        for a in (-0.38, 0.38):
            for b in (-0.39, 0.39):
                steps.box(
                    (x + a * width, y + b * depth, z + (raised - 0.17) * 0.5),
                    (0.38, 0.38, raised + 0.17),
                    "wood",
                )
    stage.finish(steps, "entry_stairs")
    entry = stage.node(uid + "_entry", foot, "BUILDING_ENTRY")
    portal = stage.node(uid + "_portal", threshold, "OPEN_DOOR")
    stage.edge(entry, portal, (foot, landing, threshold))
    plan_data = json.loads(root["interior_plan_json"])
    by_floor = {}
    entries = {}

    def position(xy, floor):
        return (
            x + front * xy[0],
            y + front * xy[1],
            z + raised + 0.315 + floor * 2.85,
        )

    for room in plan_data["rooms"]:
        floor = room["floor"]
        pos = position(room["entry"], floor)
        room_node = stage.node(
            uid + "_" + room["id"], pos, "HOUSE_" + room["kind"]
        )
        by_floor.setdefault(floor, []).append(room_node)
        entries[room_node] = room["entry"]
    for rooms in by_floor.values():
        for a, b in pairwise(rooms):
            stage.edge(a, b)
    ground = min(by_floor[0], key=lambda n: abs(entries[n][0] - local_x))
    ax, ay = entries[ground]
    front_y = -depth / 2 + 0.55
    stage.edge(
        portal,
        ground,
        (
            threshold,
            position((local_x, front_y), 0),
            position((ax, front_y), 0),
            position((ax, ay), 0),
        ),
    )
    for stair in plan_data["stairs"]:
        floor = stair["lower_floor"]
        box = stair["bounds"]
        flight = stair["flight_width"]
        left, right = box["x1"] + flight / 2, box["x2"] - flight / 2
        low = min(by_floor[floor], key=lambda n: abs(entries[n][0] - left))
        high = min(
            by_floor[floor + 1], key=lambda n: abs(entries[n][0] - right)
        )
        ya, yb = box["y1"], box["y2"] - stair["landing_depth"]
        count, rise, tread = (
            stair["steps_per_flight"],
            stair["rise"],
            stair["tread"],
        )
        axle = z + raised + 0.315 + floor * 2.85
        trace = [
            stage.nodes[low]["position"],
            position((left, ya - 0.37), floor),
        ]
        for i in range(count):
            px, py, _ = position((left, ya + (i + 0.5) * tread), floor)
            trace.append((px, py, axle + (i + 1) * rise))
        for px in (left, right):
            tx, ty, _ = position((px, yb + flight / 2), floor)
            trace.append((tx, ty, axle + count * rise))
        for i in range(count):
            px, py, _ = position((right, yb - (i + 0.5) * tread), floor)
            trace.append((px, py, axle + (count + i + 1) * rise))
        trace.extend(
            (
                position((right, ya - 0.37), floor + 1),
                stage.nodes[high]["position"],
            )
        )
        stage.edge(low, high, trace)
    for slot in shop_sockets(lot, palette):
        _shop_fixture(stage, slot, lot["business"])
    return entry


def _shop_fixture(stage, slot, trade):
    uid = slot["id"]
    x, y, z = slot["position"]
    support = stage.batch(uid, 0.012)
    detail = stage.batch(uid + "_stock", 0.006)
    tall = trade in (
        "ARMOURER",
        "BUTCHER",
        "CLOTHIER",
        "SAILMAKER",
        "HERBALIST",
    )
    top = z + (0.97 if tall else 0.24)
    for off in (-0.39, 0.39):
        support.box(
            (x + off, y, (top + z - 0.88) / 2),
            (0.085, 0.11, top - z + 0.88),
            "timber",
        )
    support.box((x, y, top), (0.88, 0.34, 0.07), "furniture_wood")
    match trade:
        case "ARMOURER":
            cylinder(detail, (x, y - 0.02, top - 0.55), 0.24, 0.09, "metal", 8)
            for dx in (-0.29, 0.23):
                detail.beam(
                    (x + dx, y, top - 0.71),
                    (x + dx + 0.16, y, top + 0.19),
                    0.066,
                    "iron",
                )
        case "BUTCHER":
            for idx, dx in enumerate((-0.25, 0, 0.24)):
                detail.beam(
                    (x + dx, y, top), (x + dx, y, top - 0.30), 0.018, "iron"
                )
                detail.box(
                    (x + dx, y, top - 0.40),
                    (0.12, 0.11, 0.27 - 0.045 * idx),
                    "cloth_red",
                )
        case "CLOTHIER" | "SAILMAKER":
            for dx, colour in ((-0.25, "cloth_blue"), (0.24, "fabric_cream")):
                detail.box(
                    (x + dx, y, top - 0.35), (0.32, 0.034, 0.68), colour
                )
        case "HERBALIST":
            for dx in (-0.27, 0, 0.27):
                detail.beam(
                    (x + dx, y, top),
                    (x + dx + 0.05, y, top - 0.42),
                    0.058,
                    "leaves",
                )
                detail.box(
                    (x + dx, y, top - 0.38), (0.14, 0.12, 0.19), "leaves_light"
                )
        case "POTTER":
            for dx in (-0.26, 0, 0.26):
                cylinder(
                    detail,
                    (x + dx, y, top + 0.045),
                    0.084,
                    0.23,
                    "cloth_red",
                    12,
                )
        case "CARTOGRAPHER":
            support.box((x, y, top + 0.16), (0.72, 0.39, 0.08), "timber")
            detail.box((x, y, top + 0.21), (0.58, 0.31, 0.023), "fabric_cream")
        case "SNOWGEAR":
            for dx in (-0.22, 0.22):
                detail.box(
                    (x + dx, y, top + 0.17), (0.23, 0.37, 0.055), "timber"
                )
        case _:
            support.box((x, y, top + 0.13), (0.86, 0.49, 0.25), "timber")
            for dx in (-0.27, 0, 0.27):
                detail.box(
                    (x + dx, y, top + 0.27),
                    (0.15, 0.26, 0.12),
                    "world_water" if trade == "FISHMONGER" else "fabric_cream",
                )
    stage.finish(support, "shop_fixture")
    stage.finish(detail, "shop_stock")
    position = slot["position"]
    extra = {
        k: v
        for k, v in slot.items()
        if k not in ("id", "kind", "position", "bounds_m")
    }
    stage.marker(uid, slot["kind"], position, slot["bounds_m"], **extra)


def _offset(point, vector, length):
    return tuple(a + b * length for a, b in zip(point, vector, strict=True))


def _wall(
    batch, a, b, z, height, span, *, thick=0.31, material="castle_stone"
):
    length = math.dist(a, b)
    vx, vy = (v / length for v in (b[0] - a[0], b[1] - a[1]))
    tangent, normal = Vector((vx, vy, 0)), Vector((-vy, vx, 0))

    def panel(left, right, bottom, top):
        if right - left < 0.001 or top - bottom < 0.001:
            return
        t = (left + right) / 2
        batch.box(
            (a[0] + vx * t, a[1] + vy * t, z + (bottom + top) / 2),
            (right - left, thick, top - bottom),
            material,
            (tangent, normal, UP),
        )

    if span:
        width, sill, head = span
        left, right = (length - width) / 2, (length + width) / 2
        panel(-thick * 0.48, left, 0, height)
        panel(right, length + thick * 0.48, 0, height)
        panel(left, right, 0, sill)
        panel(left, right, head, height)
    else:
        panel(-thick * 0.48, length + thick * 0.48, 0, height)


def _dungeon_masonry(batch, a, b, z, height, opening, style):
    length = math.dist(a, b)
    tangent = Vector(((b[0] - a[0]) / length, (b[1] - a[1]) / length, 0))
    normal = Vector((-tangent.y, tangent.x, 0))
    base = Vector((*a, z))
    rng = random.Random(f"{a}:{b}:{style}")
    courses = 7 if style == "CATACOMB" else 5
    height_step = height / courses
    for i in range(courses):
        bottom = i * height_step
        strips = [(0, length)]
        if opening and bottom < opening[2]:
            half = opening[0] / 2
            strips = [(0, length / 2 - half), (length / 2 + half, length)]
        for start, end in strips:
            u = start
            while end - u > 0.10:
                v = min(end, u + rng.uniform(0.69, 1.57))
                material = rng.choice(
                    ("ashlar_light", "ashlar_dark", "castle_stone")
                )
                mid = (
                    base
                    + tangent * ((u + v) / 2)
                    + UP * (bottom + height_step / 2)
                )
                for side in (-1, 1):
                    batch.box(
                        mid + normal * side * rng.uniform(0.174, 0.185),
                        (v - u - 0.021, 0.054, height_step - 0.026),
                        material,
                        (tangent, normal, UP),
                    )
                u = v
    if opening:
        middle = base + tangent * (length / 2)
        inner, spring = opening[0] / 2, 1.34
        outer = inner + 0.23
        for side in (-1, 1):
            face = middle + normal * side * 0.204
            for leg in (-1, 1):
                batch.box(
                    face
                    + tangent * leg * ((inner + outer) / 2)
                    + UP * (spring / 2),
                    (outer - inner, 0.10, spring),
                    "castle_shade",
                    (tangent, normal, UP),
                )
            face += UP * spring
            for i in range(11):
                theta = i * math.pi / 11 + 0.014
                phi = (i + 1) * math.pi / 11 - 0.014
                points = tuple(
                    face
                    + tangent * (r * math.cos(angle))
                    + UP * (r * math.sin(angle))
                    for r, angle in (
                        (inner, theta),
                        (outer, theta),
                        (outer, phi),
                        (inner, phi),
                    )
                )
                batch.prism(
                    points,
                    -side * normal * 0.10,
                    "castle_trim" if i == 5 else "castle_shade",
                )


def _room_floor(batch, bounds, z, hole, material):
    x0, y0, x1, y1 = bounds
    if hole:
        a, b, c, d = hole
        boxes = (
            (x0, y0, a, y1),
            (c, y0, x1, y1),
            (a, y0, c, b),
            (a, d, c, y1),
        )
    else:
        boxes = (bounds,)
    for a, b, c, d in boxes:
        batch.box(
            ((a + c) / 2, (b + d) / 2, z - 0.13),
            (c - a, d - b, 0.26),
            material,
        )


def _room_props(stage, batch, room):
    x, y, z = room["centre"]
    w, d = room["size"]
    name = room["kind"]
    p = (x - w * 0.29, y + d * 0.25)
    if name in ("BURIAL", "FUNERARY_GALLERY", "OSSUARY"):
        for k in range(2):
            py = y + (k - 0.5) * 1.7
            batch.box(
                (x - w * 0.32, py, z + 0.38), (1.22, 1.36, 0.76), "ashlar_dark"
            )
            batch.box(
                (x - w * 0.32, py, z + 0.79), (1.36, 1.45, 0.12), "castle_trim"
            )
    elif name == "LATE_NEST":
        for k in range(7):
            angle = k * math.tau / 7
            a = (
                *_offset(p, (math.cos(angle), math.sin(angle)), 0.64),
                z + 0.10,
            )
            b = (
                *_offset(
                    p, (math.cos(angle + 0.6), math.sin(angle + 0.6)), 0.71
                ),
                z + 0.20,
            )
            batch.beam(a, b, 0.10, "timber")
        stage.marker(
            room["id"] + "_tracks", "LATE_OCCUPATION", (*p, z), (0.9, 1.1, 0.2)
        )
    elif name in ("PRAYER", "CHOIR", "NAVE", "SANCTUARY"):
        mat = "fabric_blue" if name == "PRAYER" else "fabric_cream"
        for k in range(3):
            py = y + (k - 1) * d * 0.18
            batch.box((x - w * 0.29, py, z + 0.018), (1.65, 0.58, 0.036), mat)
        if name in ("CHOIR", "SANCTUARY"):
            batch.box(
                (x, y + d * 0.30, z + 0.5), (1.68, 0.68, 1), "castle_trim"
            )
    elif name == "ABLUTION":
        cylinder(batch, (*p, z), 0.78, 0.32, "castle_trim")
        stage.marker(
            room["id"] + "_water", "ABLUTION", (*p, z + 0.34), (1.3, 1.3, 0.2)
        )
    elif name in (
        "LIBRARY",
        "LABORATORY",
        "ARCHIVE",
        "RECORDS",
        "WORKROOM",
        "KITCHEN",
        "OBSERVATORY",
        "ARMOURY",
        "DELIVERY",
        "GREAT_HALL",
        "MESS",
        "TIMBER_STORE",
        "WORKSHOP",
        "AUDIENCE",
    ):
        batch.box((*p, z + 0.42), (1.8, 0.56, 0.84), "furniture_wood")
        batch.box((*p, z + 0.88), (1.94, 0.67, 0.10), "interior_floor")
        batch.box(
            (p[0], p[1] + 0.66, z + 0.22), (0.61, 0.54, 0.44), "stair_wood"
        )
        stage.marker(
            room["id"] + "_use",
            "WORK_SURFACE",
            (*p, z + 0.95),
            (1.7, 0.59, 0.6),
        )


def _rooms(stage, uid, rooms, *, dungeon_kind=None, tower=False):
    """Share door openings across collision, rendering and paths."""
    underground = dungeon_kind is not None
    walls = stage.batch(uid + "_walls", 0.025)
    floors = stage.batch(uid + "_floors")
    furnishings = stage.batch(uid + "_furniture", 0.015)
    trim = stage.batch(uid + "_stonework", 0.018)
    ashlars = (
        stage.batch(uid + "_ashlar", 0 if stage.game else 0.006)
        if underground
        else None
    )
    lights = stage.batch(uid + "_lamps")
    ladder = stage.batch(uid + "_stairs", 0.007)
    index = {(r["level"], *r["cell"]): r for r in rooms}
    minimum_y = min(r["centre"][1] for r in rooms)
    entry_room = (
        max(rooms, key=lambda r: r["centre"][1])
        if underground
        else min(
            (r for r in rooms if r["level"] == 0),
            key=lambda r: (r["centre"][1] - minimum_y, abs(r["cell"][0] - 1)),
        )
    )
    for r in rooms:
        x, y, z = r["centre"]
        shift = 2.65 if tower else 0
        stage.node(r["id"], (x + shift, y, z), r["kind"])
    entrance = None
    for r in rooms:
        x, y, z = r["centre"]
        w, d = r["size"]
        h = r["height"]
        level = r["level"]
        column, row = r["cell"]
        x0, y0, x1, y1 = rectangle((x, y), (w, d))
        stair_hole = (x - 1.07, y - 4.8, x + 1.07, y + 1.7)
        _room_floor(
            floors,
            (x0, y0, x1, y1),
            z,
            stair_hole if tower and level else None,
            "court_paving" if underground else "interior_floor",
        )
        if underground:
            _room_floor(
                walls, (x0, y0, x1, y1), z + h + 0.26, None, "castle_stone"
            )
        for dx, dy, a, b in (
            (0, -1, (x0, y0), (x1, y0)),
            (1, 0, (x1, y0), (x1, y1)),
            (0, 1, (x1, y1), (x0, y1)),
            (-1, 0, (x0, y1), (x0, y0)),
        ):
            peer = index.get((level, column + dx, row + dy))
            if peer and peer["id"] < r["id"]:
                continue
            is_entry = r is entry_room and dy == (1 if underground else -1)
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, z)
            door_width = 2 if underground else 2.5
            opening = None
            if peer or is_entry:
                opening = (door_width, 0, 2.45 if underground else 2.8)
                portal = stage.node(
                    r["id"] + f"_portal_{dx}_{dy}", mid, "OPEN_DOOR"
                )
                stage.edge(r["id"], portal)
                if peer:
                    stage.edge(portal, peer["id"])
                if is_entry:
                    entrance = stage.node(
                        uid + "_entry",
                        (mid[0] + dx * 0.65, mid[1] + dy * 0.65, z),
                        "ENTRY",
                    )
                    stage.edge(entrance, portal)
                if underground:
                    stage.marker(
                        portal + "_light",
                        "DUNGEON_LAMP",
                        (mid[0] - dx * 0.31, mid[1] - dy * 0.31, z + 2.30),
                        (0.16, 0.16, 0.24),
                    )
            elif not underground and r["kind"] != "COURTYARD":
                sill, head = (1.24, min(h - 0.25, 7.6 if h > 6 else 2.84))
                opening = (1.25, sill, head)
                _window(
                    trim,
                    (mid[0] + dx * 0.20, mid[1] + dy * 0.20, z + sill),
                    (dy, -dx),
                    (dx, dy),
                    1.25,
                    head - sill,
                    glazed=False,
                )
            if r["kind"] == "COURTYARD" and not peer:
                _wall(
                    walls,
                    a,
                    b,
                    z,
                    0.88,
                    (door_width, 0, 0.88) if opening else None,
                )
            else:
                _wall(walls, a, b, z, h, opening)
                if ashlars is not None:
                    _dungeon_masonry(
                        ashlars, a, b, z, h, opening, dungeon_kind
                    )
        _room_props(stage, furnishings, r)
        if tower and level < len(rooms) - 1:
            upper = rooms[level + 1]
            low, high = (x, y - 4.55, z), (x, y + 1.7, upper["centre"][2])
            trace = _stairs(ladder, low, high, 1.55, "stair_wood")
            approach = (
                stage.nodes[r["id"]]["position"],
                (x + 2.6, low[1], z),
                *trace,
                (x + 2.6, high[1], high[2]),
                stage.nodes[upper["id"]]["position"],
            )
            stage.edge(r["id"], upper["id"], approach)
        if underground:
            lx, ly = x + w * 0.43, y + d * 0.30
            lights.box((lx, ly, z + 1.83), (0.16, 0.21, 0.22), "lantern_glow")
            stage.marker(
                r["id"] + "_lantern",
                "DUNGEON_LAMP",
                (lx, ly, z + 1.9),
                (0.18, 0.24, 0.26),
            )
            bulb = bpy.data.lights.new(r["id"] + "_preview", "POINT")
            bulb.color = (1, 0.72, 0.41) if column % 2 else (0.46, 0.69, 0.91)
            bulb.energy, bulb.shadow_soft_size = 162, 0.22
            light = bpy.data.objects.new(bulb.name, bulb)
            stage.collection.objects.link(light)
            light.location = (lx - 0.20, ly, z + 2.05)
            light["settlement_part"] = "preview"
    stage.finish(walls, "masonry")
    stage.finish(floors, "walkable_floor")
    stage.finish(furnishings, "furniture")
    stage.finish(trim, "opening_frames")
    if ashlars is not None and (
        masonry := stage.finish(ashlars, "masonry_facing")
    ):
        masonry["collision_enabled"] = False
    stage.finish(lights, "lamp_glass", effect="LAMP")
    stage.finish(ladder, "stairs")
    return entrance


def _gable(batch, bounds, z, rise, material):
    x0, y0, x1, y1 = bounds
    mid = (x0 + x1) / 2
    for x in (x0 - 0.25, x1 + 0.25):
        batch.prism(
            (
                (x, y0 - 0.26, z),
                (mid, y0 - 0.26, z + rise),
                (mid, y1 + 0.26, z + rise),
                (x, y1 + 0.26, z),
            ),
            (0, 0, -0.17),
            material,
        )
    for y in (y0, y1):
        batch.prism(
            ((x0, y, z), (x1, y, z), (mid, y, z + rise)),
            (0, -0.17 if y == y1 else 0.17, 0),
            "castle_stone",
        )


def _dome(batch, centre, radius):
    """Open below, with a rounded shell over one continuous room."""
    x, y, z = centre
    for i in range(24):
        a, b = i * math.tau / 24, (i + 1) * math.tau / 24
        for t, s in pairwise((0, 0.27, 0.52, 0.77, 1.02, 1.27, 1.556)):

            def point(u, v):
                return (
                    x + radius * math.cos(u) * math.cos(v),
                    y + radius * math.sin(u) * math.cos(v),
                    z + radius * math.sin(v),
                )

            batch.prism(
                (point(a, t), point(b, t), point(b, s), point(a, s)),
                (0, 0, -0.095),
                "castle_roof",
            )
    cylinder(batch, (x, y, z + radius - 0.08), 0.21, 0.60, "metal", 10)


def institution(stage, place):
    uid = place["id"]
    kind = place["kind"]
    rooms = facility_rooms(place)
    tower = kind == "MAGE_TOWER"
    entry = _rooms(stage, uid, rooms, tower=tower)
    x, y, z = place["centre"]
    w, d = place["size"]
    roofs = stage.batch(uid + "_roof", 0.013)
    if kind in ("FRIDAY_MOSQUE", "CARAVANSERAI", "TRAINING_YARD"):
        for room in rooms:
            if room["kind"] in ("COURTYARD", "CATCHMENT"):
                continue
            top = room["centre"][2] + room["height"]
            if kind == "FRIDAY_MOSQUE" and room["cell"] == (1, 1):
                _dome(roofs, (*room["centre"][:2], top), 3.95)
            else:
                _gable(
                    roofs,
                    rectangle(room["centre"], room["size"]),
                    top,
                    1.0,
                    "castle_roof",
                )
        if kind == "FRIDAY_MOSQUE":
            stage.marker(
                uid + "_qibla",
                "PRAYER_DIRECTION",
                (x, y + d / 2 - 0.30, z),
                (2.5, 0.6, 2.8),
                front=(0, 1, 0),
            )
        if kind == "TRAINING_YARD":
            for i in range(3):
                px, py = x + (i - 1) * 9, y - d * 0.19
                roofs.box((px, py, z + 0.56), (0.14, 0.16, 1.1), "wood")
                roofs.prism(
                    (
                        (px - 0.39, py, z + 0.85),
                        (px + 0.39, py, z + 0.85),
                        (px + 0.39, py, z + 1.52),
                        (px - 0.39, py, z + 1.52),
                    ),
                    (0, 0.12, 0),
                    "fabric_cream",
                )
                roofs.box(
                    (px, py - 0.03, z + 1.19),
                    (0.28, 0.065, 0.26),
                    "fabric_red",
                )
                stage.marker(
                    uid + f"_target_{i}",
                    "PRACTICE_TARGET",
                    (px, py, z + 1.19),
                    (0.77, 0.12, 0.67),
                )
    elif kind == "CATHEDRAL":
        left, bottom, right, top = place["bounds"]
        eave = z + rooms[0]["height"]
        nave = w / 6
        for side in (-1, 1):
            wx = x + side * nave
            _wall(
                roofs,
                (wx, bottom),
                (wx, top),
                eave - 0.06,
                2.05,
                (1.25, 0.46, 1.59),
                thick=0.18,
            )
            edge = left if side < 0 else right
            _gable(
                roofs,
                (min(edge, wx), bottom, max(edge, wx), top),
                eave,
                1.29,
                "castle_roof",
            )
            for i in range(3):
                py = bottom + 3.1 + i * d / 3
                roofs.box(
                    (edge + side * 0.30, py, z + 2.22),
                    (0.92, 0.78, 4.48),
                    "castle_shade",
                )
                roofs.beam(
                    (edge + side * 0.48, py, z + 4.35),
                    (edge, py, eave - 0.36),
                    0.38,
                    "castle_shade",
                )
        for ey in (bottom, top):
            _wall(
                roofs,
                (x - nave, ey),
                (x + nave, ey),
                eave - 0.02,
                2.0,
                (1.45, 0.34, 1.76),
                thick=0.22,
            )
            _window(
                roofs,
                (x, ey, eave + 0.32),
                (1, 0),
                (0, -1 if ey == bottom else 1),
                1.44,
                1.44,
                glazed=True,
            )
        _gable(
            roofs,
            (x - nave, bottom, x + nave, top),
            eave + 1.99,
            3.05,
            "castle_slate",
        )
    else:
        top = max(r["centre"][2] + r["height"] for r in rooms)
        _gable(
            roofs,
            place["bounds"],
            top,
            3.1 if tower or kind == "CATHEDRAL" else 1.6,
            "castle_slate" if tower or kind == "CATHEDRAL" else "castle_roof",
        )
    stage.finish(roofs, "institution_roof")
    if kind in ("TRAINING_YARD", "ROYAL_HALL", "SAWMILL", "CISTERN"):
        stage.marker(
            uid + "_service", kind, (x, y - d / 2 - 2.5, z), (w, 3, 0.3)
        )
    return entry


def castle(stage, place, landscape):
    uid = place["id"]
    home = place["centre"]
    role = place["role"]
    architecture = make_castle_architecture(place["seed"], place["radius"])
    interior = make_castle_interior(architecture, place["seed"])
    hand = SimpleNamespace(
        architecture=architecture,
        interior=interior,
        centre=home,
        keep_heading=0,
    )
    for name, batch in castle_batches(
        hand, landscape, stage.materials
    ).items():
        stage.finish(batch, "castle_" + name)
    for batch, name, meta, location in interior_batches(
        hand, stage.materials, _window
    ):
        obj = stage.finish(batch, name)
        if obj:
            for key, value in meta.items():
                obj[key] = value
            if location:
                obj.location = location[0]
                obj.rotation_euler.z = location[1]
    nav = interior.navigation
    for node in nav["nodes"]:
        stage.node(
            f"{uid}_{node['id']}",
            castle_point(home, 0, node["position"]),
            node["name"],
        )
    for edge in nav["edges"]:
        a, b = f"{uid}_{edge['a']}", f"{uid}_{edge['b']}"
        if a in stage.nodes and b in stage.nodes:
            points = tuple(
                castle_point(home, 0, p) for p in edge.get("path", ())
            )
            stage.edge(a, b, points)
    gate = castle_point(home, 0, (0, architecture.outline[0][1] - 1.7, 0))
    entry = stage.node(uid + "_outside", gate, role)
    arrival = next(
        n for n in nav["nodes"] if n["name"] == "castle_gate_inside"
    )
    stage.edge(entry, f"{uid}_{arrival['id']}")
    stage.marker(uid, role, home, (*place["size"], architecture.height))
    return entry


def dungeon(stage, spec):
    uid = spec["id"]
    rooms = spec["rooms"]
    entry = _rooms(stage, uid, rooms, dungeon_kind=spec["kind"])
    x, y, z = spec["entrance"]
    floor = spec["cellar_z"]
    shaft = stage.batch(uid + "_shaft", 0.018)
    path = _stairs(shaft, (x, y - 16, floor), (x, y, z), 7.6, "castle_stone")
    for off in (-3.94, 3.94):
        shaft.box(
            (x + off, y - 8, (z + floor) / 2),
            (0.24, 16, z - floor + 0.50),
            "castle_stone",
        )
    stage.finish(shaft, "dungeon_stair")
    head = stage.node(uid + "_surface", (x, y + 0.35, z), "DUNGEON_ENTRANCE")
    stage.edge(entry, head, (*path, (x, y + 0.35, z)))
    stage.marker(
        uid,
        spec["kind"],
        (x, y + 0.35, z),
        (5, 6, 3),
        lore=spec["lore"],
        seal=spec["seal"],
    )
    clue = next(r for r in rooms if r["kind"] == "CLUE")
    reward = next(r for r in rooms if r["kind"] in ("OSSUARY", "REPOSITORY"))
    stones = stage.batch(uid + "_inscribed_stone", 0.015)
    glyphs = stage.batch(uid + "_inscriptions")
    targets = []
    for room, is_clue in ((clue, True), (reward, False)):
        rx, ry, rz = room["centre"]
        px = rx + (1.9 if is_clue else 2.2)
        py = ry + 2.0
        cylinder(stones, (px, py, rz), 0.54, 0.86, "castle_shade", 8)
        cylinder(stones, (px, py, rz + 0.86), 0.46, 0.09, "castle_trim", 8)
        glyph_z = rz + 0.952
        stroke = ((-0.28, 0), (0, -0.28), (0.28, 0), (0, 0.28), (-0.28, 0))
        for a, b in pairwise(stroke):
            glyphs.beam(
                (px + a[0], py + a[1], glyph_z),
                (px + b[0], py + b[1], glyph_z),
                0.032,
                "lantern_glow",
            )
        targets.append((px, py, glyph_z))
    stage.marker(
        uid + "_clue",
        "SEAL_CLUE",
        targets[0],
        (0.8, 0.8, 1),
        dungeon=uid,
        seal=spec["seal"],
    )
    stage.marker(
        uid + "_reward",
        "SEALED_RELIC",
        targets[1],
        (0.7, 0.7, 0.8),
        dungeon=uid,
        seal=spec["seal"],
    )
    recorded = set()
    for edge in stage.edges:
        if reward["id"] in (edge["from"], edge["to"]):
            edge["condition"] = spec["seal"]
            other = (
                edge["to"] if edge["from"] == reward["id"] else edge["from"]
            )
            if other not in recorded:
                recorded.add(other)
                sx, sy, sz = stage.nodes[other]["position"]
                cylinder(
                    glyphs, (sx, sy, sz + 0.009), 0.49, 0.017, "fabric_blue", 8
                )
                stage.marker(
                    other + "_seal",
                    "SEAL_TRIGGER",
                    stage.nodes[other]["position"],
                    (1.8, 0.9, 2.3),
                    seal=spec["seal"],
                )
    stage.finish(stones, "inscribed_stone")
    stage.finish(glyphs, "runes", effect="LAMP")
    stone = stage.batch(uid + "_waystone", 0.06)
    stone.box(
        (x + 2.9, y + 0.94, z + 0.63), (0.64, 0.42, 1.26), "castle_stone"
    )
    stage.finish(stone, "trail_marker")
    return head


def plaza(stage, site):
    spec = site["plaza"]
    x, y, z = spec["centre"]
    w, d = spec["size"]
    uid = spec["id"]
    rng = random.Random(f"{site['seed']}:civic")
    stage.node(uid, (x, y, z), "PLAZA")
    props = stage.batch(uid + "_street_objects", 0.014)
    flags = stage.batch(uid + "_flags")
    bulbs = stage.batch(uid + "_lantern_glass")
    if site["rank"] == "VILLAGE":
        wx = x + w * 0.29
        radius = rng.uniform(0.80, 1.06)
        _lathe(
            props,
            [
                (0, 0.02),
                (radius, 0.02),
                (radius, 0.76),
                (radius + 0.065, 0.82),
                (radius + 0.065, 0.94),
                (radius - 0.20, 0.94),
                (radius - 0.20, 0.20),
                (0, 0.20),
            ],
            "castle_stone",
            rng.choice((12, 16, 20)),
            origin=(wx, y, z),
        )
        for side in (-1, 1):
            props.box(
                (wx + side * (radius + 0.19), y, z + 1.29),
                (0.13, 0.17, 2.55),
                "wood",
            )
        props.beam(
            (wx - radius - 0.31, y, z + 1.91),
            (wx + radius + 0.31, y, z + 1.91),
            0.16,
            "wood",
        )
        props.beam((wx, y, z + 1.91), (wx, y, z + 0.61), 0.026, "rope")
        _gable(
            props,
            rectangle((wx, y), (2 * radius + 0.64, 1.25)),
            z + 2.52,
            0.55,
            "castle_roof",
        )
        stage.marker(
            uid + "_well",
            "WELL_WATER",
            (wx, y, z + 0.36),
            (2 * (radius - 0.22), 2 * (radius - 0.22), 0.7),
        )
    else:
        fx, fy = x + w * 0.25, y + d * 0.14
        radius = (3 if site["rank"] == "CAPITAL" else 1.68) * rng.uniform(
            0.92, 1.08
        )
        pool = radius - 0.28
        _lathe(
            props,
            [
                (0, 0.02),
                (radius, 0.02),
                (radius, 0.53),
                (radius + 0.055, 0.58),
                (radius + 0.055, 0.71),
                (pool, 0.71),
                (pool, 0.20),
                (0, 0.20),
            ],
            "castle_stone",
            rng.choice((20, 24, 28)),
            origin=(fx, fy, z),
        )
        _lathe(
            props,
            [
                (0, 0.18),
                (0.42, 0.18),
                (0.42, 0.37),
                (0.22, 0.58),
                (0.16, 1.28),
                (0.27, 1.34),
                (0, 1.52),
            ],
            "castle_trim",
            16,
            origin=(fx, fy, z),
        )
        stage.marker(
            uid + "_fountain",
            "FOUNTAIN_WATER",
            (fx, fy, z + 0.46),
            (pool * 1.98, pool * 1.98, 1.52),
        )
        sx, sy = x - w * 0.25, y + d * 0.14
        props.box((sx, sy, z + 0.28), (1.9, 1.75, 0.56), "castle_stone")
        stage.marker(
            uid + "_statue",
            "STATUE_ANCHOR",
            (sx, sy, z + 0.56),
            (1.5, 1.5, 2.7),
        )
        for i, side in enumerate((-1, 1)):
            lx, ly = x + side * (w / 2 - 3.5), y - d * 0.31
            length = (5.9 if site["rank"] == "CAPITAL" else 3.8) * rng.uniform(
                0.97, 1.03
            )
            _lathe(
                props,
                [
                    (0, 0),
                    (0.29, 0),
                    (0.26, 0.29),
                    (0.19, 0.48),
                    (0.11, 0.61),
                    (0.082, length - 0.1),
                    (0.13, length),
                    (0, length + 0.11),
                ],
                "iron",
                12,
                origin=(lx, ly, z),
            )
            for hand in (-1, 1):
                arm = 1.43 if length > 5 else 0.56
                props.beam(
                    (lx, ly, z + length - 0.26),
                    (lx + hand * arm, ly, z + length - 0.26),
                    0.070,
                    "iron",
                )
                if length > 5:
                    a, b = lx + hand * 0.22, lx + hand * arm
                    flags.prism(
                        (
                            (a, ly, z + length - 0.30),
                            (b, ly, z + length - 0.30),
                            (b, ly, z + length - 0.85),
                            (a, ly, z + length - 0.85),
                        ),
                        (0, 0.012, 0),
                        "cloth_red" if i else "cloth_blue",
                    )
                mx, low = lx + hand * arm, z + length - 0.75
                cylinder(
                    bulbs,
                    (mx, ly, low + 0.043),
                    0.136,
                    0.31,
                    "lantern_glow",
                    8,
                )
                _lathe(
                    props,
                    [(0, 0), (0.175, 0), (0.17, 0.058), (0, 0.058)],
                    "iron",
                    8,
                    origin=(mx, ly, low),
                )
                _lathe(
                    props,
                    [(0, 0), (0.182, 0), (0.153, 0.075), (0, 0.15)],
                    "iron",
                    8,
                    origin=(mx, ly, low + 0.34),
                )
                stage.marker(
                    uid + f"_light_{i}_{hand}",
                    "STREET_LIGHT",
                    (mx, ly, low + 0.20),
                    (0.22, 0.24, 0.37),
                )
    stage.finish(props, "civic_structure")
    stage.finish(bulbs, "lamp_glass", effect="LAMP")
    if fabric := stage.finish(flags, "banner_preview", effect="FLAG"):
        highest = max(v.co.z for v in fabric.data.vertices)
        uv = fabric.data.uv_layers.active.data
        for loop, item in zip(fabric.data.loops, uv, strict=True):
            height = fabric.data.vertices[loop.vertex_index].co.z
            item.uv.y = min(1.0, max(0.0, (highest - height) / 0.55))
