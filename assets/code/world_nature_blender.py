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


def build_monument_statue(body, detail, *, scale=1.0, imperial=False):
    """Build a monumental stone-and-bronze guardian statue."""
    s = scale * (1.55 if imperial else 1.0)
    # Stepped octagonal marble and stone pedestal base.
    for z, r, h, mat in (
        (-0.20, 2.25, 0.52, "stone"),
        (0.32, 1.88, 0.42, "stone_light"),
        (0.74, 1.54, 0.36, "marble_white"),
    ):
        cylinder(body, (0, 0, z * s), r * s, h * s, mat, 8)
    # Fluted colonnaded pedestal drum.
    drum_z = 1.10 * s
    drum_h = 2.65 * s
    cylinder(body, (0, 0, drum_z), 1.05 * s, drum_h, "stone_light", 12)
    for i in range(8):
        a = i * math.tau / 8
        cylinder(
            detail,
            (math.cos(a) * 1.16 * s, math.sin(a) * 1.16 * s, drum_z),
            0.14 * s,
            drum_h,
            "marble_white",
            8,
        )
    cornice_z = drum_z + drum_h
    cylinder(body, (0, 0, cornice_z), 1.38 * s, 0.36 * s, "marble_white", 8)
    # Heroic cast-bronze armored guardian figure.
    fig_z = cornice_z + 0.36 * s
    # Boots and greaves.
    for sx in (-0.30, 0.30):
        cylinder(
            detail,
            (sx * s, 0, fig_z),
            0.22 * s,
            1.45 * s,
            "bronze_statue",
            8,
        )
    # Armored torso, pauldrons, and flowing bronze cape.
    detail.box(
        (0, 0, fig_z + 2.22 * s),
        (1.05 * s, 0.62 * s, 1.58 * s),
        "bronze_statue",
    )
    for sx in (-0.66, 0.66):
        cylinder(
            detail,
            (sx * s, 0, fig_z + 2.68 * s),
            0.28 * s,
            0.42 * s,
            "bronze_statue",
            8,
        )
    detail.prism(
        [
            (-0.58 * s, -0.32 * s, fig_z + 2.95 * s),
            (0.58 * s, -0.32 * s, fig_z + 2.95 * s),
            (0.92 * s, -0.78 * s, fig_z + 0.12 * s),
            (-0.92 * s, -0.78 * s, fig_z + 0.12 * s),
        ],
        (0, -0.14 * s, 0),
        "bronze_statue",
    )
    # Crested helm and heroic head.
    cylinder(
        detail,
        (0, 0, fig_z + 3.04 * s),
        0.31 * s,
        0.58 * s,
        "bronze_statue",
        10,
    )
    detail.box(
        (0, -0.04 * s, fig_z + 3.68 * s),
        (0.14 * s, 0.56 * s, 0.32 * s),
        "bronze_statue",
    )
    # Left kite shield on pedestal; right arm raising sword/spear.
    detail.box(
        (-0.84 * s, 0.38 * s, fig_z + 1.55 * s),
        (0.16 * s, 0.92 * s, 1.65 * s),
        "bronze_statue",
    )
    detail.beam(
        (0.68 * s, 0.05 * s, fig_z + 2.75 * s),
        (1.12 * s, 0.35 * s, fig_z + 3.55 * s),
        0.16 * s,
        "bronze_statue",
    )
    # Tall raised imperial sword/halberd towering above the square.
    detail.beam(
        (1.12 * s, 0.35 * s, fig_z + 2.20 * s),
        (1.12 * s, 0.35 * s, fig_z + 5.65 * s),
        0.09 * s,
        "bronze_statue",
    )
    detail.box(
        (1.12 * s, 0.35 * s, fig_z + 3.62 * s),
        (0.72 * s, 0.12 * s, 0.12 * s),
        "bronze_statue",
    )


def build_training_ground(body, detail, surface, *, radius=6.4):
    """Build an enclosed imperial military sparring and archery yard."""
    # Raked sand sparring floor with low dressed stone curb.
    cylinder(surface, (0, 0, 0.02), radius - 0.35, 0.10, "arena_sand", 16)
    ring_n = 16
    for i in range(ring_n):
        a0 = i * math.tau / ring_n
        a1 = (i + 1) * math.tau / ring_n
        # Leave an open front entrance gateway along -Y.
        if -1.95 < math.atan2(math.sin(a0), math.cos(a0)) < -1.15:
            continue
        p0 = (math.cos(a0) * radius, math.sin(a0) * radius, 0.0)
        p1 = (math.cos(a1) * radius, math.sin(a1) * radius, 0.0)
        body.box((p0[0], p0[1], 0.62), (0.20, 0.20, 1.38), "timber")
        for rail_z in (0.48, 0.96):
            body.beam(
                (p0[0], p0[1], rail_z),
                (p1[0], p1[1], rail_z),
                0.09,
                "wood",
            )
        if i % 4 == 0:
            # Tall crimson-and-blue imperial training banners.
            detail.beam(
                (p0[0], p0[1], 0.0), (p0[0], p0[1], 4.6), 0.09, "timber"
            )
            in_x, in_y = -math.cos(a0), -math.sin(a0)
            detail.prism(
                [
                    (p0[0], p0[1], 4.45),
                    (p0[0] + in_x * 1.15, p0[1] + in_y * 1.15, 4.10),
                    (p0[0], p0[1], 3.35),
                ],
                (0, 0, 0.05),
                "flag" if (i // 4) % 2 == 0 else "fabric_blue",
            )
    # Three archery targets on wooden tripod stands along the far side.
    for tx in (-2.4, 0.0, 2.4):
        ty = radius * 0.56
        body.beam((tx - 0.35, ty + 0.2, 0), (tx, ty, 1.55), 0.07, "wood")
        body.beam((tx + 0.35, ty + 0.2, 0), (tx, ty, 1.55), 0.07, "wood")
        body.beam((tx, ty - 0.4, 0), (tx, ty, 1.55), 0.07, "wood")
        detail.box((tx, ty - 0.06, 1.18), (0.92, 0.22, 0.92), "hay_gold")
        detail.box((tx, ty - 0.18, 1.18), (0.52, 0.04, 0.52), "cloth_red")
        detail.box((tx, ty - 0.21, 1.18), (0.20, 0.04, 0.20), "cloth_cream")
    # Two wooden knight sparring dummies (pell posts) in the arena.
    for dx, dy in ((-2.2, -1.2), (2.2, -1.2)):
        body.box((dx, dy, 0.95), (0.22, 0.22, 1.95), "timber")
        body.box((dx, dy, 1.38), (1.28, 0.16, 0.18), "wood")
        detail.box((dx, dy, 1.35), (0.44, 0.34, 0.58), "hay_gold")
        detail.box((dx, dy, 1.82), (0.28, 0.28, 0.30), "iron")
    # Weapon rack along the west palisade.
    rx = -radius * 0.62
    for ry in (-0.9, 0.9):
        body.box((rx, ry, 0.72), (0.14, 0.14, 1.45), "timber")
    for rz in (0.45, 1.15):
        body.beam((rx, -0.95, rz), (rx, 0.95, rz), 0.07, "wood")
    for k in range(5):
        wy = -0.68 + k * 0.34
        detail.beam((rx + 0.10, wy, 0.15), (rx + 0.10, wy, 2.05), 0.04, "iron")


def _face(batch, points, material):
    first = len(batch.vertices)
    batch.vertices.extend(tuple(p) for p in points)
    batch.faces.append(tuple(range(first, len(batch.vertices))))
    batch.face_materials.append(batch.material_indices[material])


def _add_wheat_sheaf(batch, base, rng, material, height):
    """Build a slender cluster of golden wheat stalks and ears."""
    stalks = 6
    for i in range(stalks):
        ang = i * math.tau / stalks + rng.uniform(-0.35, 0.35)
        ox, oy = math.cos(ang), math.sin(ang)
        r = rng.uniform(0.03, 0.22)
        p0 = base + Vector((ox * r, oy * r, 0.0))
        h = height * rng.uniform(0.78, 1.18)
        lean = h * rng.uniform(0.14, 0.34)
        fwd = Vector((ox, oy, 0.0))
        side = Vector((-oy, ox, 0.0))
        p1 = p0 + fwd * (lean * 0.42) + Vector((0, 0, h * 0.56))
        p2 = p0 + fwd * lean + Vector((0, 0, h))
        w0, w1, w2 = 0.022, 0.018, 0.008
        _face(
            batch,
            [p0 - side * w0, p0 + side * w0, p1 + side * w1, p1 - side * w1],
            material,
        )
        _face(
            batch,
            [p1 - side * w1, p1 + side * w1, p2 + side * w2, p2 - side * w2],
            material,
        )
        # Plump drooping golden grain ear at the stalk tip.
        ear = p2 + fwd * 0.04 - Vector((0, 0, 0.05))
        batch.box(ear, (0.048, 0.036, 0.14), material)


def _add_cabbage_rosette(batch, base, rng, material):
    """Build a layered leafy vegetable rosette mound."""
    r = rng.uniform(0.22, 0.32)
    h = rng.uniform(0.18, 0.28)
    for k in range(5):
        ang = k * math.tau / 5 + rng.uniform(-0.25, 0.25)
        fwd = Vector((math.cos(ang), math.sin(ang), 0.0))
        side = Vector((-fwd.y, fwd.x, 0.0))
        tip = base + fwd * r + Vector((0, 0, h * 0.55))
        _face(
            batch,
            [
                base + Vector((0, 0, 0.04)),
                base
                + fwd * (r * 0.48)
                - side * (r * 0.44)
                + Vector((0, 0, h)),
                tip,
                base
                + fwd * (r * 0.48)
                + side * (r * 0.44)
                + Vector((0, 0, h)),
            ],
            material,
        )
    cylinder(batch, base, r * 0.46, h * 0.85, material, 6)


def build_farmland_patch(
    soil_batch,
    crop_batch,
    centre,
    size,
    heading,
    height_fn,
    rng,
    *,
    season="SUMMER",
):
    """Build plowed furrows, crops, timber fence, and hay bales."""
    cx, cy = centre
    w, d = size
    c, s = math.cos(heading), math.sin(heading)
    basis = ((c, s, 0), (-s, c, 0), (0, 0, 1))
    crop_kind = rng.choice(("WHEAT", "WHEAT", "VEGETABLE"))

    def world_pt(u, v, z_off=0.0):
        wx = cx + u * c - v * s
        wy = cy + u * s + v * c
        return Vector((wx, wy, height_fn(wx, wy) + z_off))

    # Plowed soil furrow ridges across the field width.
    rows = max(5, int(d / 1.35))
    row_step = d / rows
    segs = max(5, int(w / 3.2))
    seg_len = w / segs
    for r in range(rows):
        v = -d / 2 + (r + 0.5) * row_step
        for k in range(segs):
            u = -w / 2 + (k + 0.5) * seg_len
            p = world_pt(u, v, 0.05)
            soil_batch.box(
                p,
                (seg_len * 0.99, row_step * 0.68, 0.24),
                "soil_furrow",
                basis,
            )
            if season == "WINTER":
                continue
            if crop_kind == "WHEAT":
                mat = "wheat_gold" if season != "SPRING" else "crop_green"
                h = 0.86 if season != "SPRING" else 0.44
                sheaves = 4
                for m in range(sheaves):
                    su = u + (m - (sheaves - 1) / 2) * (seg_len / sheaves)
                    sp = world_pt(
                        su + rng.uniform(-0.14, 0.14),
                        v + rng.uniform(-0.12, 0.12),
                        0.15,
                    )
                    _add_wheat_sheaf(crop_batch, sp, rng, mat, h)
            else:
                heads = 3
                for m in range(heads):
                    su = u + (m - (heads - 1) / 2) * (seg_len / heads)
                    sp = world_pt(
                        su + rng.uniform(-0.10, 0.10),
                        v + rng.uniform(-0.08, 0.08),
                        0.16,
                    )
                    _add_cabbage_rosette(crop_batch, sp, rng, "crop_green")

    # Split-rail timber fence posts and rails around the field.
    hw, hd = w / 2 + 0.65, d / 2 + 0.65
    corners = ((-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd))
    for a, b in zip(corners, corners[1:] + corners[:1], strict=True):
        dist = math.hypot(b[0] - a[0], b[1] - a[1])
        posts = max(2, round(dist / 3.4))
        prev = None
        for i in range(posts + 1):
            t = i / posts
            pu = a[0] + (b[0] - a[0]) * t
            pv = a[1] + (b[1] - a[1]) * t
            p = world_pt(pu, pv, 0.0)
            soil_batch.box(
                p + Vector((0, 0, 0.46)), (0.14, 0.14, 1.12), "timber", basis
            )
            if prev is not None and not (i == posts // 2 and a == corners[0]):
                for rz in (0.36, 0.76):
                    soil_batch.beam(
                        prev + Vector((0, 0, rz)),
                        p + Vector((0, 0, rz)),
                        0.065,
                        "wood",
                    )
            prev = p

    # Stacked golden hay bales near one field corner.
    for bu, bv, bz in (
        (-hw + 1.8, -hd + 1.6, 0.44),
        (-hw + 3.1, -hd + 1.6, 0.44),
        (-hw + 2.45, -hd + 1.6, 1.24),
    ):
        soil_batch.box(
            world_pt(bu, bv, bz), (1.18, 0.86, 0.80), "hay_gold", basis
        )
