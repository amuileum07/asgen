"""Natural crags, marsh reeds, cave grottos, mills, and belfries."""

import math

from mathutils import Vector
from mathutils.noise import noise

from castle_blender import _pointed_roof
from castle_roof_rules import RoofSpec
from fortification_blender import cylinder


def add_crag_boulder(
    batch, x, y, z, width, rng, *, realistic=False, material="rock_light"
):
    """Add a stratified natural boulder with ridged crag facets."""
    angle = rng.random() * math.tau
    rings = []
    first = len(batch.vertices)
    bias = rng.uniform(-39, 39)
    sides = 20 if realistic else 8
    profile = (
        (
            (-0.28, 0.76),
            (-0.04, 0.96),
            (0.11, 1.02),
            (0.22, 0.92),
            (0.32, 0.86),
            (0.42, 0.74),
            (0.51, 0.58),
            (0.58, 0.36),
            (0.62, 0.16),
        )
        if realistic
        else ((-0.15, 0.79), (0.14, 1.0), (0.55, 0.58))
    )
    for layer, (height, scale) in enumerate(profile):
        ring = []
        for k in range(sides):
            yaw = angle + k * math.tau / sides
            u, v = math.cos(yaw), math.sin(yaw)
            if realistic:
                p1 = Vector((u * 1.9 + bias, v * 1.9, layer * 0.72))
                p2 = Vector((u * 4.2 - bias, v * 4.2, layer * 1.65))
                ridge = 1.0 - abs(noise(p1))
                chip = noise(p2) * 0.08
                radial = (ridge - 0.52) * 0.34 + chip
                shelf = (1.0 - abs(noise(p1 * 1.3))) * 0.12
                ring.append(
                    (
                        x + (u * scale + u * radial) * width,
                        y + (v * scale * 0.78 + v * radial * 0.85) * width,
                        z + (height + shelf - 0.05) * width,
                    )
                )
            else:
                t = noise(Vector((u * 2 + bias, v * 2, layer * 0.91)))
                ring.append(
                    (
                        x + (u * scale + t * 0.16) * width,
                        y + (v * scale * 0.77 + t * 0.10) * width,
                        z + (height + t * 0.15) * width,
                    )
                )
        rings.append(ring)
        batch.vertices.extend(ring)
    last = sides * (len(rings) - 1)
    faces = [tuple(reversed(range(sides))), tuple(range(last, last + sides))]
    for ring_start in range(0, last, sides):
        faces.extend(
            (
                ring_start + i,
                ring_start + (i + 1) % sides,
                ring_start + (i + 1) % sides + sides,
                ring_start + i + sides,
            )
            for i in range(sides)
        )
    batch.faces.extend(tuple(first + i for i in face) for face in faces)
    batch.face_materials.extend(
        [batch.material_indices[material]] * len(faces)
    )


def add_reed_clump(batch, base, rng):
    """Add a wetland cluster of tall reeds and dark cattail heads."""
    origin = Vector(base)
    stalks = rng.randint(6, 10)
    for i in range(stalks):
        ang = i * math.tau / stalks + rng.uniform(-0.3, 0.3)
        dist = rng.uniform(0.04, 0.38)
        height = rng.uniform(0.85, 1.55)
        lean = Vector((math.cos(ang), math.sin(ang), 0)) * rng.uniform(
            0.10, 0.28
        )
        root = origin + Vector(
            (math.cos(ang) * dist, math.sin(ang) * dist, -0.08)
        )
        mid = root + Vector((0, 0, height * 0.55)) + lean * 0.45
        tip = root + Vector((0, 0, height)) + lean
        mat = "leaves_shadow" if i % 2 else "grass_dark"
        batch.beam(root, mid, 0.026, mat)
        batch.beam(mid, tip, 0.016, mat)
        if i < 3:
            # Dark-brown cattail head near the top of the stalk.
            head_start = mid.lerp(tip, 0.52)
            head_end = mid.lerp(tip, 0.82)
            batch.beam(head_start, head_end, 0.048, "timber")


def add_cave_mouth(
    batch,
    centre,
    heading,
    width,
    height,
    depth,
    ground_at,
    rng,
    *,
    rock_mat="rock",
    dark_mat="iron",
):
    """Build a natural stratified rock cave arch with dark tunnel."""
    cx, cy = centre
    z0 = ground_at(cx, cy)
    ang = math.radians(heading)
    fwd = Vector((math.cos(ang), math.sin(ang), 0.0))
    side = Vector((-fwd.y, fwd.x, 0.0))
    up = Vector((0.0, 0.0, 1.0))
    origin = Vector((cx, cy, z0))

    # Recessed dark cavern chamber shell extending into the hillside.
    arch_steps = 8
    half_w = width * 0.50
    profile = [(-half_w, -0.35), (-half_w, height * 0.42)]
    for i in range(arch_steps + 1):
        a = math.pi * (1.0 - i / arch_steps)
        profile.append(
            (
                half_w * math.cos(a),
                height * 0.42 + (height * 0.58) * math.sin(a),
            )
        )
    profile.append((half_w, -0.35))

    # Dark back wall closing the recessed cave depth.
    back_center = origin - fwd * depth
    back_poly = [tuple(back_center + side * u + up * v) for u, v in profile]
    batch.prism(back_poly, tuple(-fwd * 0.8), dark_mat)

    # Rough tunnel ribs stepping back into shadow.
    rib_count = 4
    for step in range(rib_count):
        t = step / rib_count
        pos = origin - fwd * (t * depth)
        shrink = 1.0 - t * 0.16
        for idx in range(len(profile) - 1):
            u0, v0 = profile[idx]
            u1, v1 = profile[idx + 1]
            p0 = pos + side * (u0 * shrink) + up * (v0 * shrink)
            p1 = pos + side * (u1 * shrink) + up * (v1 * shrink)
            mid = (p0 + p1) * 0.5
            seg_len = max(0.3, (p1 - p0).length)
            tang = (p1 - p0).normalized()
            out_n = tang.cross(fwd).normalized()
            batch.box(
                mid + out_n * 0.45,
                (seg_len + 0.25, depth / rib_count + 0.4, 0.9),
                dark_mat if step >= 2 else rock_mat,
                (tang, -fwd, out_n),
            )

    # Organic stacked crags framing the cave piers and brow arch.
    for sign in (-1, 1):
        for tier in range(3):
            b_pos = (
                origin
                + side * (sign * (half_w + 0.75 + tier * 0.22))
                - fwd * (tier * 0.35)
            )
            add_crag_boulder(
                batch,
                b_pos.x,
                b_pos.y,
                z0 + tier * height * 0.34,
                width * rng.uniform(0.30, 0.44),
                rng,
                realistic=True,
                material=rock_mat if tier % 2 else "rock_light",
            )
    for k in range(5):
        frac = (k / 4.0) * 2.0 - 1.0
        arch_z = height * (0.86 + 0.24 * (1.0 - frac * frac))
        b_pos = origin + side * (frac * half_w * 1.05) + fwd * 0.35
        add_crag_boulder(
            batch,
            b_pos.x,
            b_pos.y,
            z0 + arch_z,
            width * rng.uniform(0.30, 0.42),
            rng,
            realistic=True,
            material="rock_light" if k % 2 else rock_mat,
        )
    # Hanging stalactites along the upper cavern brow.
    for _ in range(4):
        u = rng.uniform(-half_w * 0.65, half_w * 0.65)
        st_len = rng.uniform(0.45, 0.95)
        top_z = z0 + height * (0.94 - 0.16 * (u / half_w) ** 2)
        pt = origin + side * u - fwd * rng.uniform(0.2, 1.4)
        batch.beam(
            (pt.x, pt.y, top_z),
            (pt.x, pt.y, top_z - st_len),
            0.14,
            "rock_light",
        )


def build_bell_tower(body, canopy, accent, *, grand=False):
    """Build a medieval stone bell tower with open belfry and bell."""
    w = 3.5 if grand else 2.55
    shaft_h = 12.8 if grand else 8.2
    belfry_h = 3.4 if grand else 2.55
    spire_h = 6.2 if grand else 4.1

    # Battered stone plinth and corner buttresses.
    body.box((0, 0, 0.45), (w + 0.85, w + 0.85, 1.25), "stone")
    body.box((0, 0, 1.18), (w + 0.55, w + 0.55, 0.24), "stone_light")
    body.box((0, 0, shaft_h / 2 + 0.4), (w, w, shaft_h), "castle_stone")
    for sx in (-1, 1):
        for sy in (-1, 1):
            body.box(
                (sx * (w * 0.50), sy * (w * 0.50), shaft_h * 0.34),
                (
                    0.55 if grand else 0.42,
                    0.55 if grand else 0.42,
                    shaft_h * 0.68,
                ),
                "stone",
            )
            # Alternating corner quoins rising up the upper shaft.
            for q in range(4):
                qz = shaft_h * 0.68 + q * 0.68
                if qz < shaft_h - 0.3:
                    body.box(
                        (sx * (w * 0.48), sy * (w * 0.48), qz),
                        (
                            0.44 if q % 2 else 0.32,
                            0.32 if q % 2 else 0.44,
                            0.34,
                        ),
                        "stone_light",
                    )

    # Arched timber entry portal on front face (-Y).
    door_w = 1.15 if grand else 0.92
    door_h = 2.35 if grand else 2.05
    body.box(
        (0, -w / 2 - 0.04, door_h / 2 + 0.1),
        (door_w + 0.32, 0.24, door_h + 0.25),
        "stone_light",
    )
    body.box(
        (0, -w / 2 - 0.02, door_h / 2 + 0.05), (door_w, 0.16, door_h), "wood"
    )

    # Projecting corbeled stone cornice beneath the open belfry.
    base_z = shaft_h + 0.4
    body.box((0, 0, base_z - 0.14), (w + 0.42, w + 0.42, 0.28), "stone_light")
    body.box((0, 0, base_z + 0.10), (w + 0.62, w + 0.62, 0.22), "stone")
    body.box((0, 0, base_z + 0.45), (w + 0.28, w + 0.28, 0.55), "castle_stone")

    # Open four-corner belfry piers showing the hanging bronze bell.
    pier_w = 0.48 if grand else 0.36
    pier_off = w * 0.46
    for sx in (-1, 1):
        for sy in (-1, 1):
            body.box(
                (sx * pier_off, sy * pier_off, base_z + 0.4 + belfry_h / 2),
                (pier_w, pier_w, belfry_h),
                "stone_light",
            )
    top_z = base_z + 0.4 + belfry_h
    body.box((0, 0, top_z + 0.14), (w + 0.54, w + 0.54, 0.32), "stone_light")

    # Oak bell yoke beam and flared cast-bronze bell inside the belfry.
    bell_z = base_z + 0.55 + belfry_h * 0.54
    body.beam(
        (-pier_off, 0, bell_z + 0.55),
        (pier_off, 0, bell_z + 0.55),
        0.18,
        "timber",
    )
    bell_r = 0.62 if grand else 0.46
    bell_h = 0.92 if grand else 0.72
    cylinder(
        accent,
        (0, 0, bell_z + 0.15),
        bell_r * 0.42,
        bell_h * 0.45,
        "metal",
        14,
    )
    cylinder(
        accent,
        (0, 0, bell_z - 0.10),
        bell_r * 0.68,
        bell_h * 0.35,
        "metal",
        14,
    )
    cylinder(accent, (0, 0, bell_z - 0.28), bell_r, bell_h * 0.22, "metal", 16)
    body.beam((0, 0, bell_z + 0.55), (0, 0, bell_z - 0.36), 0.08, "iron")

    # Steep slate spire and wrought-iron cross finial.
    spec = RoofSpec(
        "belfry_spire",
        (0, 0),
        top_z + 0.26,
        w + 0.95,
        w + 0.95,
        spire_h,
        "PYRAMID_8" if grand else "PYRAMID_4",
        8 if grand else 4,
    )
    _pointed_roof(canopy, spec, "castle_slate")
    finial_base = top_z + 0.26 + spire_h
    body.beam(
        (0, 0, finial_base - 0.15), (0, 0, finial_base + 1.45), 0.06, "iron"
    )
    body.beam(
        (-0.42, 0, finial_base + 0.95),
        (0.42, 0, finial_base + 0.95),
        0.045,
        "iron",
    )


def build_watermill(batch, centre, along, side, water_level):
    """Build a riverside stone-and-timber watermill and wheel."""
    up = Vector((0, 0, 1))
    origin = Vector((centre[0], centre[1], water_level))
    basis = (along, side, up)

    def pt(x, y, z):
        return origin + along * x + side * y + up * z

    # Dressed stone wheelhouse basement rooted into riverbed.
    mw, md, stone_h = 5.4, 4.4, 2.35
    batch.box(
        pt(0, 0, stone_h * 0.35 - 0.45),
        (mw, md, stone_h + 1.2),
        "castle_stone",
        basis,
    )
    batch.box(
        pt(0, 0, stone_h + 0.06),
        (mw + 0.26, md + 0.26, 0.16),
        "stone_light",
        basis,
    )

    # Half-timbered upper millhouse.
    upper_h = 2.65
    upper_z = stone_h + 0.14
    batch.box(
        pt(0, 0, upper_z + upper_h / 2),
        (mw - 0.08, md - 0.08, upper_h),
        "castle_plaster",
        basis,
    )
    for sx in (-mw / 2 + 0.04, 0.0, mw / 2 - 0.04):
        for sy in (-md / 2 + 0.04, md / 2 - 0.04):
            batch.box(
                pt(sx, sy, upper_z + upper_h / 2),
                (0.18, 0.18, upper_h + 0.08),
                "timber",
                basis,
            )
    for z_rail in (upper_z + 0.08, upper_z + upper_h - 0.08):
        batch.box(
            pt(0, 0, z_rail), (mw + 0.10, md + 0.10, 0.16), "timber", basis
        )

    # Steep pitched terracotta gable roof and loft hoist beam.
    eave_z = upper_z + upper_h
    ridge_z = eave_z + 2.35
    over = 0.55
    for sign in (-1, 1):
        p0 = pt(-mw / 2 - over, sign * (md / 2 + over), eave_z - 0.22)
        p1 = pt(mw / 2 + over, sign * (md / 2 + over), eave_z - 0.22)
        p2 = pt(mw / 2 + over, 0.0, ridge_z)
        p3 = pt(-mw / 2 - over, 0.0, ridge_z)
        batch.prism([p0, p1, p2, p3], (0, 0, -0.16), "castle_roof")
    for end_x in (-mw / 2, mw / 2):
        batch.prism(
            [
                pt(end_x, -md / 2, eave_z),
                pt(end_x, md / 2, eave_z),
                pt(end_x, 0.0, ridge_z - 0.08),
            ],
            tuple(along * (-0.16 if end_x > 0 else 0.16)),
            "castle_plaster",
        )
    batch.beam(
        pt(-mw / 2 - over, 0, ridge_z + 0.06),
        pt(mw / 2 + over, 0, ridge_z + 0.06),
        0.18,
        "castle_roof",
    )
    # Projecting timber hoist beam for lifting flour sacks.
    batch.beam(
        pt(mw / 2 - 0.4, 0, eave_z + 1.05),
        pt(mw / 2 + 1.15, 0, eave_z + 1.05),
        0.14,
        "timber",
    )

    # Spoked oak undershot waterwheel on the river-facing (-side) wall.
    wheel_y = -md / 2 - 0.62
    wheel_r = 1.78
    hub_z = 1.48
    # Heavy axle piercing the stone wall + outer timber bearing pier.
    batch.beam(
        pt(0, -md / 2 + 0.35, hub_z),
        pt(0, wheel_y - 0.65, hub_z),
        0.26,
        "timber",
    )
    batch.box(
        pt(0, wheel_y - 0.65, hub_z * 0.5 - 0.3),
        (0.48, 0.48, hub_z + 0.95),
        "stone",
        basis,
    )
    spokes = 12
    for i in range(spokes):
        a0 = i * math.tau / spokes
        a1 = (i + 1) * math.tau / spokes
        ca0, sa0 = math.cos(a0), math.sin(a0)
        ca1, sa1 = math.cos(a1), math.sin(a1)
        # Dual wheel rims and radial spokes.
        for rim_off in (-0.34, 0.34):
            batch.beam(
                pt(0, wheel_y + rim_off, hub_z),
                pt(ca0 * wheel_r, wheel_y + rim_off, hub_z + sa0 * wheel_r),
                0.09,
                "timber",
            )
            batch.beam(
                pt(ca0 * wheel_r, wheel_y + rim_off, hub_z + sa0 * wheel_r),
                pt(ca1 * wheel_r, wheel_y + rim_off, hub_z + sa1 * wheel_r),
                0.11,
                "wood",
            )
        # Wide oak paddle blade mounted across the two rims.
        p_mid = pt(
            ca0 * (wheel_r + 0.06), wheel_y, hub_z + sa0 * (wheel_r + 0.06)
        )
        rad_v = (along * ca0 + up * sa0).normalized()
        tang_v = (-along * sa0 + up * ca0).normalized()
        batch.box(p_mid, (0.36, 0.78, 0.06), "wood", (rad_v, side, tang_v))

    # Timber millrace sluice channel feeding the wheel.
    batch.box(
        pt(-mw * 0.72, wheel_y, 0.42),
        (mw * 0.68, 1.05, 0.14),
        "timber",
        basis,
    )
    for s_off in (-0.52, 0.52):
        batch.box(
            pt(-mw * 0.72, wheel_y + s_off, 0.72),
            (mw * 0.68, 0.10, 0.52),
            "timber",
            basis,
        )
    # Stacked grain crates on the mill landing.
    for cx, cy, sz in (
        (mw * 0.5 + 0.55, 0.55, 0.68),
        (mw * 0.5 + 0.65, -0.25, 0.56),
    ):
        batch.box(
            pt(cx, cy, stone_h * 0.25 + sz / 2), (sz, sz, sz), "wood", basis
        )
