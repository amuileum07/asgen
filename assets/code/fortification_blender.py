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


def _tower(batch, x, y, z, radius, height, realistic=False):
    sides = 28 if realistic else 12
    cylinder(batch, (x, y, z - 0.25), radius, height + 0.25, "stone", sides)
    cylinder(
        batch,
        (x, y, z + height - 0.4),
        radius * 1.13,
        0.45,
        "stone_light",
        sides,
    )
    if realistic:
        for level, reach, depth in (
            (0.12, 1.10, 0.42),
            (0.77, 1.04, 0.12),
            (0.88, 1.075, 0.17),
        ):
            cylinder(
                batch,
                (x, y, z + height * level),
                radius * reach,
                depth,
                "stone",
                sides,
            )
        # Machicolation corbels supporting the overhanging parapet.
        corbels = 14
        for k in range(corbels):
            ang = k * math.tau / corbels
            cx, cy = math.cos(ang), math.sin(ang)
            batch.box(
                (
                    x + cx * radius * 1.04,
                    y + cy * radius * 1.04,
                    z + height - 0.54,
                ),
                (0.24, 0.28, 0.34),
                "stone_light",
                ((-cy, cx, 0), (cx, cy, 0), (0, 0, 1)),
            )
        # Battered defensive talus base flares into the hillside.
        cylinder(batch, (x, y, z - 0.55), radius * 1.18, 1.35, "stone", sides)
    cone(
        batch,
        (x, y, z + height + 0.05),
        radius * 1.33,
        radius * (2.05 if realistic else 1.6),
        "castle_roof",
        sides,
    )
    if realistic:
        # Wrought-iron spire finial crowning each bastion tower.
        apex_z = z + height + 0.05 + radius * 2.05
        batch.beam((x, y, apex_z - 0.15), (x, y, apex_z + 1.15), 0.055, "iron")


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
    realistic=False,
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
            if realistic:
                basis = ((tx, ty, 0), (-ty, tx, 0), (0, 0, 1))
                mid_z = (z1 + z2) / 2
                seg_len = length / count
                # Battered outer talus plinth and stone wall buttress.
                if height >= 4.2:
                    batch.box(
                        (
                            centre[0] + nx * (thickness * 0.5 + 0.22),
                            centre[1] + ny * (thickness * 0.5 + 0.22),
                            mid_z + 0.55,
                        ),
                        (seg_len + 0.08, 0.58, 1.75),
                        "stone",
                        basis,
                    )
                    if index % 3 == 1:
                        batch.box(
                            (
                                centre[0] + nx * (thickness * 0.5 + 0.36),
                                centre[1] + ny * (thickness * 0.5 + 0.36),
                                mid_z + height * 0.44,
                            ),
                            (0.68, 0.72, height * 0.88),
                            "stone",
                            basis,
                        )
                    # Projecting machicolation cornice under parapet.
                    batch.box(
                        (
                            centre[0] + nx * (thickness * 0.5 + 0.14),
                            centre[1] + ny * (thickness * 0.5 + 0.14),
                            mid_z + height - 0.34,
                        ),
                        (seg_len + 0.06, 0.34, 0.24),
                        "stone_light",
                        basis,
                    )
                # Individual coping stones follow the grade of the wall.
                for first, last in ((0.01, 0.49), (0.51, 0.99)):
                    cap = []
                    for t, side in (
                        (first, 1),
                        (last, 1),
                        (last, -1),
                        (first, -1),
                    ):
                        off = side * (thickness / 2 + 0.075)
                        cap.append(
                            (
                                p[0] + t * (q[0] - p[0]) + nx * off,
                                p[1] + t * (q[1] - p[1]) + ny * off,
                                z1 + (z2 - z1) * t + height + 0.09,
                            )
                        )
                    batch.prism(cap, (0, 0, -0.16), "stone_light")
            if crenellations and index % 2 == 0:
                for side in (-1, 1):
                    merlon_xy = (
                        centre[0] + nx * thickness * 0.33 * side,
                        centre[1] + ny * thickness * 0.33 * side,
                    )
                    merlon_z = (z1 + z2) / 2 + height + 0.35
                    basis = ((tx, ty, 0), (-ty, tx, 0), (0, 0, 1))
                    batch.box(
                        (*merlon_xy, merlon_z),
                        (length / count * 0.6, 0.42, 0.7),
                        "stone_light",
                        basis,
                    )
                    if realistic:
                        # Projecting weathered capstone on each merlon.
                        batch.box(
                            (*merlon_xy, merlon_z + 0.39),
                            (length / count * 0.66, 0.50, 0.10),
                            "stone",
                            basis,
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
                    realistic,
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
                realistic,
            )
        clearance = max(3.6, height - 0.8)
        basis = ((tx, ty, 0), (-ty, tx, 0), (0, 0, 1))
        batch.box(
            (x, y, z + clearance + 0.45),
            (gate.width + tower_radius * 2, thickness * 1.7, 0.9),
            "stone_light",
            basis,
        )
        if realistic:
            # Grand barbican gatehouse gallery and raised portcullis.
            gallery_h = max(1.8, height * 0.28)
            batch.box(
                (x, y, z + clearance + 0.9 + gallery_h / 2),
                (gate.width + tower_radius * 1.4, thickness * 1.9, gallery_h),
                "stone",
                basis,
            )
            batch.box(
                (x, y, z + clearance + 0.9 + gallery_h + 0.16),
                (gate.width + tower_radius * 1.5, thickness * 2.05, 0.32),
                "stone_light",
                basis,
            )
            # Raised iron portcullis teeth strictly above clearance.
            teeth = 7
            for k in range(teeth):
                u = -gate.width * 0.44 + k * (gate.width * 0.88) / (teeth - 1)
                batch.beam(
                    (x + tx * u, y + ty * u, z + clearance + 0.06),
                    (x + tx * u, y + ty * u, z + clearance + 0.82),
                    0.075,
                    "iron",
                )
            # Heraldic banners flanking the grand gatehouse.
            for side in (-1, 1):
                bx = x + tx * (gate.width * 0.5 + tower_radius * 0.85) * side
                by = y + ty * (gate.width * 0.5 + tower_radius * 0.85) * side
                bz = z + height + 1.15
                batch.box(
                    (bx + nx * 0.95, by + ny * 0.95, bz),
                    (0.75, 0.05, 2.25),
                    "flag" if side > 0 else "cloth_blue",
                    basis,
                )
