"""Curtain walls, open gates and towers for towns and castles."""

import math


def cylinder(batch, centre, radius, height, material, vertices=12):
    x, y, z = centre
    polygon = [
        (
            x + radius * math.cos(i * math.tau / vertices),
            y + radius * math.sin(i * math.tau / vertices),
            z,
        )
        for i in range(vertices)
    ]
    batch.prism(polygon, (0, 0, height), material)


def cone(batch, centre, radius, height, material, vertices=12):
    x, y, z = centre
    # A tiny upper ring keeps the apex faces nondegenerate.
    lower = [
        (
            x + radius * math.cos(i * math.tau / vertices),
            y + radius * math.sin(i * math.tau / vertices),
            z,
        )
        for i in range(vertices)
    ]
    upper = [
        (
            x + 0.015 * math.cos(i * math.tau / vertices),
            y + 0.015 * math.sin(i * math.tau / vertices),
            z + height,
        )
        for i in range(vertices)
    ]
    start = len(batch.vertices)
    batch.vertices.extend(lower + upper)
    faces = [
        tuple(start + i for i in reversed(range(vertices))),
        tuple(start + vertices + i for i in range(vertices)),
    ]
    faces.extend(
        (
            start + i,
            start + (i + 1) % vertices,
            start + vertices + (i + 1) % vertices,
            start + vertices + i,
        )
        for i in range(vertices)
    )
    batch.faces.extend(faces)
    batch.face_materials.extend(
        [batch.material_indices[material]] * len(faces)
    )


def _tower(batch, x, y, z, radius, height):
    cylinder(batch, (x, y, z - 0.25), radius, height + 0.25, "stone")
    cylinder(
        batch, (x, y, z + height - 0.4), radius * 1.13, 0.45, "stone_light"
    )
    cone(
        batch,
        (x, y, z + height + 0.05),
        radius * 1.33,
        radius * 1.6,
        "castle_roof",
    )


def build_walls(
    batch,
    outline,
    gates,
    height,
    sampler,
    tower_spacing=25,
    *,
    decorate_towers=True,
    decorate_gates=True,
    thickness=None,
    crenellations=True,
):
    """Follow the boundary and leave gate passages open."""
    thickness = thickness or (1.3 if height < 5 else 1.8)
    accumulated, next_tower = 0.0, 0.0
    for a, b in zip(outline, outline[1:] + outline[:1], strict=True):
        length = math.dist(a, b)
        if length < 1e-6:
            continue
        tx, ty = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        nx, ny = ty, -tx
        count = max(1, math.ceil(length / 1.6))
        for index in range(count):
            t1, t2 = index / count, (index + 1) / count
            p = (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)
            q = (a[0] + (b[0] - a[0]) * t2, a[1] + (b[1] - a[1]) * t2)
            centre = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            if any(
                math.dist(centre, gate.position[:2]) < gate.width / 2 + 0.8
                for gate in gates
            ):
                continue
            z1, z2 = sampler.height(*p), sampler.height(*q)
            # Overlap the wall ends slightly to close seams.
            top = [
                (
                    p[0] + nx * thickness / 2 - tx * 0.05,
                    p[1] + ny * thickness / 2 - ty * 0.05,
                    z1 + height,
                ),
                (
                    q[0] + nx * thickness / 2 + tx * 0.05,
                    q[1] + ny * thickness / 2 + ty * 0.05,
                    z2 + height,
                ),
                (
                    q[0] - nx * thickness / 2 + tx * 0.05,
                    q[1] - ny * thickness / 2 + ty * 0.05,
                    z2 + height,
                ),
                (
                    p[0] - nx * thickness / 2 - tx * 0.05,
                    p[1] - ny * thickness / 2 - ty * 0.05,
                    z1 + height,
                ),
            ]
            batch.prism(top, (0, 0, -height - 0.45), "stone")
            if crenellations and index % 2 == 0:
                for side in (-1, 1):
                    batch.box(
                        (
                            centre[0] + nx * thickness * 0.33 * side,
                            centre[1] + ny * thickness * 0.33 * side,
                            (z1 + z2) / 2 + height + 0.35,
                        ),
                        (length / count * 0.6, 0.42, 0.7),
                        "stone_light",
                        ((tx, ty, 0), (-ty, tx, 0), (0, 0, 1)),
                    )
        if decorate_towers and accumulated + length >= next_tower:
            centre = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            if not any(
                math.dist(centre, gate.position[:2]) < gate.width / 2 + 4.5
                for gate in gates
            ):
                _tower(
                    batch,
                    *centre,
                    sampler.height(*centre),
                    thickness * 1.35,
                    height + 1.5,
                )
                next_tower = accumulated + tower_spacing
        accumulated += length
    for gate in gates if decorate_gates else ():
        x, y, _ = gate.position
        nx, ny = gate.outward
        tx, ty = -ny, nx
        z = sampler.height(x, y)
        tower_radius = thickness * 1.3
        for side in (-1, 1):
            distance = gate.width / 2 + tower_radius
            _tower(
                batch,
                x + tx * distance * side,
                y + ty * distance * side,
                z,
                tower_radius,
                height + 2.0,
            )
        clearance = max(3.6, height - 0.8)
        batch.box(
            (x, y, z + clearance + 0.45),
            (gate.width + tower_radius * 2, thickness * 1.7, 0.9),
            "stone_light",
            ((tx, ty, 0), (-ty, tx, 0), (0, 0, 1)),
        )
