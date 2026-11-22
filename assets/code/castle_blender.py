"""Stone castle exteriors with attached wings and steep slate roofs."""

import math
import random
from types import SimpleNamespace

from mathutils import Vector

from castle_geometry import circle, edges, subtract_convex, subtract_prism
from castle_interior_rules import BASE, SLAB, block_polygon, defensive_towers
from castle_roof_rules import (
    RoofSpec,
    block_roofs,
    roof_geometry,
    tower_roof,
    window_under_roof,
)
from castle_rules import castle_point
from fortification_blender import build_walls, cylinder
from house_generator import MeshBatch
from solid_geometry import convex_planes
from terrain_rules import segment_projection


def _face(batch, points, material):
    first = len(batch.vertices)
    batch.vertices.extend(points)
    batch.faces.append(tuple(range(first, first + len(points))))
    batch.face_materials.append(batch.material_indices[material])


def _frustum(batch, centre, lower, upper, height, material, count=16):
    x, y, z = centre
    rings = [
        [
            (
                x + radius * math.cos(i * math.tau / count),
                y + radius * math.sin(i * math.tau / count),
                z + offset,
            )
            for i in range(count)
        ]
        for radius, offset in ((lower, 0), (upper, height))
    ]
    _face(batch, list(reversed(rings[0])), material)
    _face(batch, rings[1], material)
    for index in range(count):
        next_ = (index + 1) % count
        _face(
            batch,
            [
                rings[0][index],
                rings[0][next_],
                rings[1][next_],
                rings[1][index],
            ],
            material,
        )


def _roof(batch, centre, size, height, material, hip=False):
    spec = RoofSpec(
        "pavilion", centre[:2], centre[2], *size, height, "PYRAMID_4", 4
    )
    _pointed_roof(batch, spec, material)


def _pointed_roof(batch, spec, material="castle_slate"):
    first = len(batch.faces)
    vertices, faces = roof_geometry(spec)
    for i, face in enumerate(faces):
        _face(
            batch,
            [vertices[v] for v in face],
            "roof_edge" if i == 0 else material,
        )
    if not hasattr(batch, "roof_spans"):
        batch.roof_spans = []
    batch.roof_spans.append((first, len(batch.faces), spec))


def _arch_points(width, height):
    radius = width / 2
    return [(-radius, 0), (radius, 0)] + [
        (
            radius * math.cos(i * math.pi / 10),
            height - radius + radius * math.sin(i * math.pi / 10),
        )
        for i in range(11)
    ]


def _window(
    batch,
    position,
    tangent,
    normal,
    width,
    height,
    *,
    slit=False,
    glazed=True,
    mullion=True,
    border_width=None,
    arched=True,
    sill=True,
    frame_depth=0.18,
    frame_offset=0.07,
):
    """Add a dark arched reveal and a raised stone surround."""

    def point(u, z, offset=0):
        return (
            position[0] + tangent[0] * u + normal[0] * offset,
            position[1] + tangent[1] * u + normal[1] * offset,
            position[2] + z,
        )

    inside = (
        _arch_points(width, height)
        if arched
        else [
            (-width / 2, 0),
            (width / 2, 0),
            (width / 2, height),
            (-width / 2, height),
        ]
    )
    if glazed:
        batch.prism(
            [point(u, z, 0.035) for u, z in inside],
            (normal[0] * 0.045, normal[1] * 0.045, 0),
            "glass",
        )
    border = width * (0.24 if slit else 0.15)
    if border_width is not None:
        border = min(border, border_width)
    radius = width / 2
    spring = height - radius if arched else height
    for sign in (-1, 1):
        batch.box(
            point(sign * (radius + border / 2), spring / 2, frame_offset),
            (border, frame_depth, spring),
            "castle_trim",
            (
                (tangent[0], tangent[1], 0),
                (normal[0], normal[1], 0),
                (0, 0, 1),
            ),
        )
    for index in range(10 if arched else 0):
        angles = (index * math.pi / 10, (index + 1) * math.pi / 10)
        polygon = [
            point(r * math.cos(angle), spring + r * math.sin(angle), -0.02)
            for r, angle in (
                (radius, angles[0]),
                (radius + border, angles[0]),
                (radius + border, angles[1]),
                (radius, angles[1]),
            )
        ]
        batch.prism(
            polygon, (normal[0] * 0.21, normal[1] * 0.21, 0), "castle_trim"
        )
    if not arched:
        batch.box(
            point(0, height + border / 2, frame_offset),
            (width + border * 2, frame_depth, border),
            "castle_trim",
            ((*tangent, 0), (*normal, 0), (0, 0, 1)),
        )
    if sill:
        batch.box(
            point(0, -border / 2, 0.10),
            (width + border * 2, 0.26, border),
            "castle_trim",
            (
                (tangent[0], tangent[1], 0),
                (normal[0], normal[1], 0),
                (0, 0, 1),
            ),
        )
    if not slit and mullion:
        batch.beam(
            point(0, 0.08, 0.09),
            point(0, height - 0.1, 0.09),
            border * 0.5,
            "timber",
        )


def _covered(architecture, x, y, z, own_id):
    s = architecture.scale
    for block in architecture.blocks:
        if block.id == own_id or z >= block.height:
            continue
        if (
            abs(x - block.centre[0]) < block.size[0] / 2 + 0.05
            and abs(y - block.centre[1]) < block.size[1] / 2 + 0.05
        ):
            return True
    for tower in architecture.towers:
        if tower.id == own_id:
            continue
        if (
            tower.base < z < tower.base + tower.height
            and math.dist((x, y), tower.centre) < tower.radius + 0.05 * s
        ):
            return True
        if (
            tower.base > 0
            and tower.base - 1.8 * s < z <= tower.base
            and math.dist((x, y), tower.centre) < tower.radius + 0.05 * s
        ):
            return True
    return False


def _window_covered(
    architecture, position, tangent, normal, width, height, scale, own_id
):
    border = width * 0.15
    half_w = width / 2 + border + 0.04 * scale
    for u in (-half_w, 0.0, half_w):
        px = position[0] + tangent[0] * u + normal[0] * 0.15 * scale
        py = position[1] + tangent[1] * u + normal[1] * 0.15 * scale
        for dz in (0.0, height * 0.5, height):
            if _covered(architecture, px, py, position[2] + dz, own_id):
                return True
    return False


def _block(masonry, roofs, details, block, architecture):
    s = architecture.scale
    x, y = block.centre
    width, depth = block.size
    height = block.height
    timber_height = 3.2 * s if block.timber else 0
    masonry.box(
        (x, y, (height - timber_height) / 2 - 0.15),
        (width, depth, height - timber_height + 0.3),
        "castle_stone",
    )
    masonry.box(
        (x, y, 0.35 * s),
        (width + 0.5 * s, depth + 0.5 * s, 0.7 * s),
        "castle_shade",
    )
    if block.timber:
        masonry.box(
            (x, y, height - timber_height / 2),
            (width + 0.18 * s, depth + 0.18 * s, timber_height),
            "castle_plaster",
        )
        for z in (height - timber_height, height - 0.12 * s):
            details.box(
                (x, y, z),
                (width + 0.28 * s, depth + 0.28 * s, 0.2 * s),
                "timber",
            )
    else:
        for z in (height * 0.38, height * 0.72, height - 0.3 * s):
            masonry.box(
                (x, y, z),
                (width + 0.2 * s, depth + 0.2 * s, 0.18 * s),
                "castle_trim",
            )
    _roof(
        roofs,
        (x, y, height + 0.08 * s),
        (width + 0.56 * s, depth + 0.56 * s),
        block.roof_height,
        "castle_slate",
        block.roof == "HIP",
    )
    if block.roof == "GABLE":
        for side in (-1, 1):
            face_y = y + side * depth / 2
            masonry.prism(
                [
                    (x - width / 2, face_y, height),
                    (x + width / 2, face_y, height),
                    (x, face_y, height + block.roof_height * 0.90),
                ],
                (0, side * 0.08 * s, 0),
                "castle_plaster",
            )
            _window(
                details,
                (x, face_y + side * 0.1 * s, height + 0.7 * s),
                (1, 0),
                (0, side),
                0.65 * s,
                1.25 * s,
            )
    for axis, length in ((0, width), (1, depth)):
        count = max(1, round(length / (2.7 * s)))
        for side in (-1, 1):
            normal = (0, side) if axis == 0 else (side, 0)
            tangent = (1, 0) if axis == 0 else (0, 1)
            for index in range(count):
                offset = -length / 2 + (index + 0.5) * length / count
                px, py = (
                    (x + offset, y + side * depth / 2)
                    if axis == 0
                    else (x + side * width / 2, y + offset)
                )
                for floor in range(block.storeys):
                    z = (floor + 0.32) * height / block.storeys
                    win_w = (0.65 if floor < 2 else 0.90) * s
                    win_h = 1.55 * s
                    reveal = (
                        0.10 * s
                        if block.timber and z > height - timber_height
                        else 0
                    )
                    pos = (
                        px + normal[0] * reveal,
                        py + normal[1] * reveal,
                        z,
                    )
                    if _window_covered(
                        architecture,
                        pos,
                        tangent,
                        normal,
                        win_w,
                        win_h,
                        s,
                        block.id,
                    ):
                        continue
                    half = 0.55 * s
                    if window_under_roof(
                        architecture,
                        (px - tangent[0] * half, py - tangent[1] * half),
                        (px + tangent[0] * half, py + tangent[1] * half),
                        z,
                        z + win_h,
                    ):
                        continue
                    if (
                        block.id == "palas"
                        and axis == 0
                        and side == -1
                        and floor == 0
                        and abs(px - architecture.entry[0]) < 2 * s
                    ):
                        continue
                    _window(
                        details,
                        pos,
                        tangent,
                        normal,
                        win_w,
                        win_h,
                    )
                if block.timber:
                    for sign in (-1, 1):
                        u = offset + sign * length / count * 0.43
                        a = (x + u, py) if axis == 0 else (px, y + u)
                        details.box(
                            (*a, height - timber_height / 2),
                            (0.15 * s, 0.19 * s, timber_height),
                            "timber",
                            ((*tangent, 0), (*normal, 0), (0, 0, 1)),
                        )
    _masonry_details(details, block, architecture)
    # Tall chimney stacks break the roofline without external assets.
    if block.id in ("palas", "forewing"):
        z = height + block.roof_height * 0.5
        details.box(
            (x - width * 0.28, y + depth * 0.22, z),
            (0.95 * s, 1.1 * s, block.roof_height + 1.8 * s),
            "castle_shade",
        )
        details.box(
            (
                x - width * 0.28,
                y + depth * 0.22,
                z + block.roof_height / 2 + 0.9 * s,
            ),
            (1.2 * s, 1.35 * s, 0.25 * s),
            "castle_trim",
        )


def _masonry_details(batch, block, architecture):
    """Add sparse ashlar patches and alternating corner stones."""
    s = architecture.scale
    x, y = block.centre
    width, depth = block.size
    top = block.height - (3.2 * s if block.timber else 0)
    rng = random.Random(f"{block.id}:{block.height}:ashlar")
    for level in range(max(1, int(top / (0.70 * s)))):
        z = (level + 0.5) * 0.70 * s
        for nx, ny in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            length = width if nx == 0 else depth
            count = max(1, int(length / (1.5 * s)))
            for index in range(count):
                if rng.random() > 0.20:
                    continue
                u = -length / 2 + (index + 0.5) * length / count
                px = x + (u if nx == 0 else nx * (width / 2 + 0.015 * s))
                py = y + (ny * (depth / 2 + 0.015 * s) if nx == 0 else u)
                if _covered(
                    architecture,
                    px + nx * 0.1 * s,
                    py + ny * 0.1 * s,
                    z,
                    block.id,
                ):
                    continue
                batch.box(
                    (px, py, z),
                    (rng.uniform(0.65, 1.05) * s, 0.025 * s, 0.38 * s),
                    "ashlar_light" if index % 2 else "ashlar_dark",
                    ((-ny, nx, 0), (nx, ny, 0), (0, 0, 1)),
                )
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            batch.box(
                (
                    x + sx * (width / 2 - 0.16 * s),
                    y + sy * (depth / 2 - 0.16 * s),
                    z,
                ),
                (
                    (0.62 if level % 2 else 0.82) * s,
                    (0.82 if level % 2 else 0.62) * s,
                    0.48 * s,
                ),
                "castle_trim",
            )


def _tower(
    masonry, roofs, details, tower, scale, *, slit=False, architecture=None
):
    x, y = tower.centre
    z, radius, height = tower.base, tower.radius, tower.height
    if z > 0:
        _frustum(
            masonry,
            (x, y, z - 1.8 * scale),
            radius * 0.24,
            radius,
            1.8 * scale,
            "castle_shade",
        )
    cylinder(
        masonry, (x, y, z - 0.15), radius, height + 0.15, "castle_stone", 16
    )
    for level in (0.18, 0.72, 0.97):
        cylinder(
            masonry,
            (x, y, z + height * level),
            radius * 1.05,
            0.22 * scale,
            "castle_trim",
            16,
        )
    cylinder(
        masonry,
        (x, y, z + height - 0.5 * scale),
        radius * 1.12,
        0.65 * scale,
        "castle_trim",
        16,
    )
    spec = tower_roof(tower, scale, base=0.15 * scale)
    _pointed_roof(
        roofs,
        spec,
        "castle_cone" if spec.kind == "CONE" else "castle_slate",
    )
    top = z + height + tower.roof_height + 0.15 * scale
    details.beam(
        (x, y, top), (x, y, top + 0.85 * scale), 0.07 * scale, "timber"
    )
    levels = max(1, round(height / (4.0 * scale)))
    for floor in range(levels):
        for index in range(8):
            angle = (index + 0.5) * math.tau / 8
            nx, ny = math.cos(angle), math.sin(angle)
            px, py = x + radius * nx, y + radius * ny
            wz = z + (floor + 0.3) * height / levels
            win_w = (0.27 if slit else 0.56) * scale
            win_h = (1.0 if slit else 1.30) * scale
            if architecture and _window_covered(
                architecture,
                (px, py, wz),
                (-ny, nx),
                (nx, ny),
                win_w,
                win_h,
                scale,
                getattr(tower, "id", None),
            ):
                continue
            half = 0.42 * scale
            if architecture and window_under_roof(
                architecture,
                (px + ny * half, py - nx * half),
                (px - ny * half, py + nx * half),
                wz,
                wz + win_h,
            ):
                continue
            _window(
                details,
                (px, py, wz),
                (-ny, nx),
                (nx, ny),
                win_w,
                win_h,
                slit=slit,
            )


def _gatehouse(masonry, roofs, details, architecture, *, hollow=False):
    s = architecture.scale
    x, y = 0, architecture.outline[0][1]
    width = architecture.gate_width
    radius = width / 2
    spring = max(2.4, 3.2 * s)
    height = max(8.5 * s, spring + radius + 1.2 * s)
    if hollow:
        height = BASE + architecture.wall_height - SLAB
    depth, post = 3.6 * s, 1.8 * s
    for side in (-1, 1):
        masonry.box(
            (side * (radius + post / 2), y, height / 2 - 0.15),
            (post, depth, height + 0.3),
            "castle_stone",
        )
    for index in range(16):
        angles = (index * math.pi / 16, (index + 1) * math.pi / 16)
        (u1, z1), (u2, z2) = [
            (radius * math.cos(a), spring + radius * math.sin(a))
            for a in angles
        ]
        masonry.prism(
            [
                (u1, y - depth / 2, z1),
                (u2, y - depth / 2, z2),
                (u2, y - depth / 2, height),
                (u1, y - depth / 2, height),
            ],
            (0, depth, 0),
            "castle_stone",
        )
    roof_z = (
        BASE + architecture.wall_height + max(2.8, 3.2 * s)
        if hollow
        else height
    )
    _roof(
        roofs,
        (x, y, roof_z),
        (width + 2 * post + 0.6 * s, depth + 0.8 * s),
        4.5 * s,
        "castle_slate",
        True,
    )
    for side in (-1, 1):
        if hollow:
            continue
        tower = SimpleNamespace(
            centre=(side * (radius + post), y),
            base=0,
            radius=1.65 * s,
            height=height + 1.2 * s,
            roof_height=5.5 * s,
        )
        _tower(masonry, roofs, details, tower, s, slit=True)
    # Raised portcullis stays wholly above the traversable arch.
    for index in range(0 if hollow else 7):
        u = -radius + (index + 0.5) * width / 7
        details.beam(
            (u, y, spring + radius + 0.12),
            (u, y, height - 0.2 * s),
            0.10 * s,
            "timber",
        )


def _hollow_roofs(architecture, masonry, roofs, details):
    s = architecture.scale
    for block, spec in zip(
        architecture.blocks, block_roofs(architecture), strict=True
    ):
        x, y = block.centre
        w, d = block.size
        _pointed_roof(roofs, spec)
        if block.id in ("palas", "forewing"):
            z = BASE + block.height + block.roof_height * 0.60
            details.box(
                (x - w * 0.28, y + d * 0.22, z),
                (0.95 * s, 1.1 * s, block.roof_height),
                "castle_shade",
            )
    for tower in architecture.towers:
        x, y = tower.centre
        if tower.base:
            cylinder(
                masonry,
                (x, y, BASE + tower.base + tower.height - 0.16 * s),
                tower.radius + 0.20 * s,
                0.17 * s,
                "castle_trim",
                8,
            )
        _pointed_roof(
            roofs,
            tower_roof(tower, s),
            "castle_cone" if tower.roof == "CONE" else "castle_slate",
        )
        if tower.base:
            _frustum(
                masonry,
                (x, y, BASE + tower.base - 1.25 * s),
                tower.radius * 0.30,
                tower.radius,
                1.25 * s,
                "castle_trim",
                8,
            )
    for name, centre, radius in defensive_towers(architecture):
        x, y = centre
        cylinder(
            masonry,
            (x, y, -0.15),
            radius,
            BASE + architecture.wall_height - SLAB + 0.15,
            "castle_stone",
            8,
        )
        top = BASE + architecture.wall_height + max(2.8, 3.2 * s)
        kind = "CONE" if name.startswith("gate") else "PYRAMID_8"
        spec = RoofSpec(
            name,
            centre,
            top,
            (radius + 0.25 * s) * 2,
            (radius + 0.25 * s) * 2,
            (4.3 if kind == "CONE" else 3.6) * s,
            kind,
            40 if kind == "CONE" else 8,
        )
        _pointed_roof(
            roofs, spec, "castle_cone" if kind == "CONE" else "castle_slate"
        )


def castle_batches(castle, sampler, materials, *, realistic=False):
    """Return world-space batches; let the caller manage ownership."""
    architecture = castle.architecture
    s = architecture.scale
    batches = {
        role: MeshBatch("Castle_" + role, materials)
        for role in ("masonry", "roofs", "details", "curtain", "rock")
    }
    masonry, roofs, details = (
        batches[r] for r in ("masonry", "roofs", "details")
    )
    if castle.interior:
        _hollow_roofs(architecture, masonry, roofs, details)
    else:
        masonry.prism(
            [(*p, 0.015) for p in architecture.outline],
            (0, 0, -0.25),
            "court_paving",
        )
        for block in architecture.blocks:
            _block(masonry, roofs, details, block, architecture)
        for tower in architecture.towers:
            _tower(
                masonry, roofs, details, tower, s, architecture=architecture
            )
    for index in (
        () if castle.interior else range(2, len(architecture.outline), 2)
    ):
        tower = SimpleNamespace(
            centre=architecture.outline[index],
            base=0,
            radius=1.7 * s,
            height=architecture.wall_height + 2 * s,
            roof_height=4.5 * s,
        )
        _tower(masonry, roofs, details, tower, s, slit=True)
    gate = SimpleNamespace(
        position=(0, architecture.outline[0][1], 0),
        outward=(0, -1),
        width=architecture.gate_width,
    )

    def local_height(x, y):
        world = castle_point(castle.centre, castle.keep_heading, (x, y))
        return sampler.height(*world[:2]) - castle.centre[2]

    curtain = batches["curtain"]
    # Keep the reusable city-wall primitive and apply castle sandstone.
    curtain.material_indices["stone"] = curtain.material_indices[
        "castle_stone"
    ]
    curtain.material_indices["stone_light"] = curtain.material_indices[
        "castle_trim"
    ]
    build_walls(
        curtain,
        architecture.outline,
        (gate,),
        architecture.wall_height,
        SimpleNamespace(height=local_height),
        decorate_towers=False,
        decorate_gates=False,
        thickness=max(2.2, 2.0 * s) if castle.interior else None,
        crenellations=not bool(castle.interior),
        realistic=realistic,
    )
    _gatehouse(
        masonry, roofs, details, architecture, hollow=bool(castle.interior)
    )
    entry = architecture.entry
    if not castle.interior:
        _window(details, entry, (1, 0), (0, -1), 2.0 * s, 3.5 * s)
    # A pennant gives the main donjon a readable distant silhouette.
    donjon = next(b for b in architecture.blocks if b.id == "donjon")
    x, y = donjon.centre
    top = donjon.height + donjon.roof_height
    details.beam((x, y, top), (x, y, top + 2.8 * s), 0.09 * s, "timber")
    details.prism(
        [
            (x, y, top + 2.7 * s),
            (x + 2.3 * s, y, top + 2.25 * s),
            (x, y, top + 1.75 * s),
        ],
        (0, 0.05 * s, 0),
        "flag",
    )
    # The terrain owns the cliff skin; a second rock sheet causes seams.
    _clip_roofs(roofs, architecture, details)
    for batch in batches.values():
        batch.vertices = [
            castle_point(castle.centre, castle.keep_heading, point)
            for point in batch.vertices
        ]
    return batches


def _clip_roofs(batch, architecture, details=None):
    roof_volumes = []
    for start, end, spec in getattr(batch, "roof_spans", ()):
        points, spec_faces = roof_geometry(spec)
        planes = []
        for nx, ny, nz, d in convex_planes(points, spec_faces):
            planes.append((-nx, -ny, -nz, d))
        roof_volumes.append((start, end, planes))
    volumes = [
        (
            tuple(
                (
                    x + (0.19 if x > b.centre[0] else -0.19),
                    y + (0.19 if y > b.centre[1] else -0.19),
                )
                for x, y in block_polygon(b)
            ),
            BASE,
            BASE + b.height - 0.015,
        )
        for b in architecture.blocks
    ]
    volumes += [
        (
            circle(t.centre, t.radius + 0.205, 8),
            BASE + t.base,
            BASE + t.base + t.height - 0.015,
        )
        for t in architecture.towers
    ]
    corbels = []
    for tower in architecture.towers:
        if not tower.base:
            continue
        top = BASE + tower.base
        bottom = top - 1.25 * architecture.scale
        low = tower.radius * 0.30
        slope = (tower.radius - low) / (top - bottom)
        cosine = math.cos(math.pi / 8)
        planes = [(0, 0, 1, -bottom), (0, 0, -1, top)]
        for i in range(8):
            angle = (i + 0.5) * math.tau / 8
            nx, ny = math.cos(angle), math.sin(angle)
            planes.append(
                (
                    -nx,
                    -ny,
                    slope * cosine,
                    nx * tower.centre[0]
                    + ny * tower.centre[1]
                    + (low - slope * bottom) * cosine,
                )
            )
        corbels.append(planes)
    faces, vertices, materials, welded, seams = [], [], [], {}, set()
    for fi, (indices, material) in enumerate(
        zip(batch.faces, batch.face_materials, strict=True)
    ):
        pieces = [tuple(batch.vertices[i] for i in indices)]
        a, b, c = (Vector(p) for p in pieces[0][:3])
        face_normal = (b - a).cross(c - a).normalized()
        for start, end, planes in roof_volumes:
            if start <= fi < end:
                continue
            # Equal coplanar surfaces belong to the earlier roof.
            if fi < start and any(
                face_normal.dot(Vector((-nx, -ny, -nz))) > 1 - 1e-7
                and abs(face_normal.dot(a) - d) < 1e-6
                for nx, ny, nz, d in planes
            ):
                continue
            pieces = [
                part
                for piece in pieces
                for part in subtract_convex(piece, planes)
            ]
        for polygon, bottom, top in volumes:
            pieces = [
                part
                for piece in pieces
                for part in subtract_prism(piece, polygon, bottom, top)
            ]
        for planes in corbels:
            pieces = [
                part
                for piece in pieces
                for part in subtract_convex(piece, planes)
            ]
        for piece in pieces:
            clean = []
            for p in piece:
                if not clean or math.dist(clean[-1], p) > 1e-4:
                    clean.append(p)
            if len(clean) > 1 and math.dist(clean[0], clean[-1]) < 1e-4:
                clean.pop()
            changed = True
            while changed and len(clean) > 3:
                changed = False
                for i in range(len(clean)):
                    a, b, c = (
                        Vector(clean[j % len(clean)])
                        for j in (i - 1, i, i + 1)
                    )
                    if (b - a).cross(c - b).length < 1e-7:
                        clean.pop(i)
                        changed = True
                        break
            piece = tuple(clean)
            if len(piece) < 3:
                continue
            # Collinear fragments can occur at shared roof/body edges.
            normal = Vector((0, 0, 0))
            for i in range(1, len(piece) - 1):
                normal += (Vector(piece[i]) - Vector(piece[0])).cross(
                    Vector(piece[i + 1]) - Vector(piece[0])
                )
            if normal.length < 1e-8:
                continue
            mapped = []
            for point in piece:
                key = tuple(round(v, 5) for v in point)
                if key not in welded:
                    welded[key] = len(vertices)
                    vertices.append(point)
                mapped.append(welded[key])
            mapped = list(dict.fromkeys(mapped))
            if len(mapped) < 3:
                continue
            faces.append(tuple(mapped))
            materials.append(material)
            if details:
                for p, q in zip(piece, piece[1:] + piece[:1], strict=True):
                    if math.dist(p, q) < 0.2:
                        continue
                    key = tuple(
                        sorted(tuple(round(v, 5) for v in r) for r in (p, q))
                    )
                    if key in seams:
                        continue
                    for polygon, bottom, top in volumes:
                        if not bottom - 1e-5 < min(p[2], q[2]) < top + 1e-5:
                            continue
                        if any(
                            segment_projection(p[:2], a, b)[0] < 1e-5
                            and segment_projection(q[:2], a, b)[0] < 1e-5
                            for a, b in edges(polygon)
                        ):
                            details.beam(
                                p, q, 0.08 * architecture.scale, "roof_edge"
                            )
                            seams.add(key)
                            break
    batch.vertices, batch.faces, batch.face_materials = (
        vertices,
        faces,
        materials,
    )
