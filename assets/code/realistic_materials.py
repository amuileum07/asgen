"""Procedural PBR shaders, nature materials, and physical sky."""

import math

import bpy


def _link(tree, source, target):
    tree.links.new(source, target)


def _map_range(
    tree,
    value,
    from_min=0.0,
    from_max=1.0,
    to_min=0.0,
    to_max=1.0,
    *,
    interp="LINEAR",
    clamp=True,
    loc=(0, 0),
):
    node = tree.nodes.new("ShaderNodeMapRange")
    node.location = loc
    node.interpolation_type = interp
    node.clamp = clamp
    node.inputs["From Min"].default_value = from_min
    node.inputs["From Max"].default_value = from_max
    node.inputs["To Min"].default_value = to_min
    node.inputs["To Max"].default_value = to_max
    if value is not None:
        _link(tree, value, node.inputs["Value"])
    return node


def _noise(
    tree,
    vector,
    scale,
    detail=6.0,
    roughness=0.6,
    *,
    distortion=0.0,
    noise_type="FBM",
    loc=(0, 0),
):
    node = tree.nodes.new("ShaderNodeTexNoise")
    node.location = loc
    node.noise_type = noise_type
    node.inputs["Scale"].default_value = scale
    node.inputs["Detail"].default_value = detail
    node.inputs["Roughness"].default_value = roughness
    node.inputs["Distortion"].default_value = distortion
    if vector is not None:
        _link(tree, vector, node.inputs["Vector"])
    return node


def _voronoi(
    tree,
    vector,
    scale,
    *,
    feature="F1",
    randomness=0.85,
    loc=(0, 0),
):
    node = tree.nodes.new("ShaderNodeTexVoronoi")
    node.location = loc
    node.feature = feature
    node.inputs["Scale"].default_value = scale
    node.inputs["Randomness"].default_value = randomness
    if vector is not None:
        _link(tree, vector, node.inputs["Vector"])
    return node


def _mix_rgb(tree, blend, factor, a, b, *, clamp=False, loc=(0, 0)):
    node = tree.nodes.new("ShaderNodeMixRGB")
    node.location = loc
    node.blend_type = blend
    node.use_clamp = clamp
    if isinstance(factor, (int, float)):
        node.inputs[0].default_value = factor
    else:
        _link(tree, factor, node.inputs[0])
    if isinstance(a, tuple):
        node.inputs[1].default_value = a
    elif a is not None:
        _link(tree, a, node.inputs[1])
    if isinstance(b, tuple):
        node.inputs[2].default_value = b
    elif b is not None:
        _link(tree, b, node.inputs[2])
    return node


def _math(tree, op, a, b=None, *, clamp=False, loc=(0, 0)):
    node = tree.nodes.new("ShaderNodeMath")
    node.location = loc
    node.operation = op
    node.use_clamp = clamp
    if isinstance(a, (int, float)):
        node.inputs[0].default_value = a
    elif a is not None:
        _link(tree, a, node.inputs[0])
    if b is not None:
        if isinstance(b, (int, float)):
            node.inputs[1].default_value = b
        else:
            _link(tree, b, node.inputs[1])
    return node


def _vec_math(tree, op, a, b=None, *, loc=(0, 0)):
    node = tree.nodes.new("ShaderNodeVectorMath")
    node.location = loc
    node.operation = op
    if isinstance(a, tuple):
        node.inputs[0].default_value = a
    elif a is not None:
        _link(tree, a, node.inputs[0])
    if b is not None:
        if isinstance(b, tuple):
            node.inputs[1].default_value = b
        else:
            _link(tree, b, node.inputs[1])
    return node


def _bump(tree, height, strength, distance, *, normal=None, loc=(0, 0)):
    node = tree.nodes.new("ShaderNodeBump")
    node.location = loc
    node.inputs["Strength"].default_value = strength
    node.inputs["Distance"].default_value = distance
    if height is not None:
        _link(tree, height, node.inputs["Height"])
    if normal is not None:
        _link(tree, normal, node.inputs["Normal"])
    return node


def _ao_node(tree, distance=0.4, samples=8, *, only_local=False, loc=(0, 0)):
    node = tree.nodes.new("ShaderNodeAmbientOcclusion")
    node.location = loc
    node.samples = samples
    node.only_local = only_local
    node.inputs["Distance"].default_value = distance
    return node


def _new_surface_group(name):
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    for socket, direction, socket_type in (
        ("Tint", "INPUT", "NodeSocketColor"),
        ("Color", "OUTPUT", "NodeSocketColor"),
        ("Normal", "OUTPUT", "NodeSocketVector"),
        ("Roughness", "OUTPUT", "NodeSocketFloat"),
    ):
        group.interface.new_socket(
            name=socket, in_out=direction, socket_type=socket_type
        )
    inp = group.nodes.new("NodeGroupInput")
    inp.location = (-1200, 360)
    out = group.nodes.new("NodeGroupOutput")
    out.location = (960, 40)
    return group, inp, out


def _build_plaster(group, inp, out):
    coords = group.nodes.new("ShaderNodeTexCoord")
    coords.location = (-1200, 0)
    obj = coords.outputs["Object"]

    macro = _noise(
        group, obj, 1.15, detail=6.0, roughness=0.62, loc=(-920, 220)
    )
    medium = _noise(
        group, obj, 4.4, detail=5.0, roughness=0.58, loc=(-920, 20)
    )
    grit = _noise(
        group, obj, 68.0, detail=7.0, roughness=0.72, loc=(-920, -180)
    )

    # Vertical rain streaks under eaves and sills.
    streak_vec = _vec_math(
        group, "MULTIPLY", obj, (5.2, 5.2, 0.48), loc=(-920, -380)
    )
    streaks = _noise(
        group,
        streak_vec.outputs["Vector"],
        1.7,
        detail=5.0,
        roughness=0.65,
        loc=(-700, -380),
    )
    streak_fac = _map_range(
        group,
        streaks.outputs["Fac"],
        0.38,
        0.74,
        0.84,
        1.03,
        interp="SMOOTHSTEP",
        loc=(-480, -380),
    )

    # Occasional organic stucco hairline cracks in weathered areas.
    crack_warp = _mix_rgb(
        group, "MIX", 0.22, obj, medium.outputs["Color"], loc=(-700, -580)
    )
    cracks = _voronoi(
        group,
        crack_warp.outputs["Color"],
        1.7,
        feature="DISTANCE_TO_EDGE",
        loc=(-480, -580),
    )
    crack_raw = _map_range(
        group,
        cracks.outputs["Distance"],
        0.0,
        0.011,
        1.0,
        0.0,
        interp="SMOOTHSTEP",
        loc=(-260, -580),
    )
    crack_area = _map_range(
        group,
        macro.outputs["Fac"],
        0.64,
        0.78,
        0.0,
        0.55,
        interp="SMOOTHSTEP",
        loc=(-260, -760),
    )
    crack_amt = _math(
        group,
        "MULTIPLY",
        crack_raw.outputs["Result"],
        crack_area.outputs["Result"],
        clamp=True,
        loc=(-40, -640),
    )
    crack_mask = _math(
        group,
        "SUBTRACT",
        1.0,
        crack_amt.outputs["Value"],
        clamp=True,
        loc=(120, -640),
    )

    # Noise-broken rising damp and splash stain at wall base.
    gen_xyz = group.nodes.new("ShaderNodeSeparateXYZ")
    gen_xyz.location = (-920, -760)
    _link(group, coords.outputs["Generated"], gen_xyz.inputs["Vector"])
    damp_jitter = _map_range(
        group, macro.outputs["Fac"], 0.2, 0.8, -0.09, 0.09, loc=(-700, -760)
    )
    damp_z = _math(
        group,
        "ADD",
        gen_xyz.outputs["Z"],
        damp_jitter.outputs["Result"],
        loc=(-480, -760),
    )
    damp_mask = _map_range(
        group,
        damp_z.outputs["Value"],
        0.0,
        0.24,
        1.0,
        0.0,
        interp="SMOOTHSTEP",
        loc=(-260, -760),
    )

    # Ambient occlusion grime under beams, frames, and eaves.
    ao = _ao_node(group, distance=0.42, samples=8, loc=(-480, 420))
    ao_shade = _map_range(
        group,
        ao.outputs["AO"],
        0.22,
        0.96,
        0.46,
        1.0,
        interp="SMOOTHSTEP",
        loc=(-240, 420),
    )

    # Combine limewash mottling, warm shifts, streaks, cracks, AO.
    tone = _map_range(
        group,
        macro.outputs["Fac"],
        0.25,
        0.78,
        0.82,
        1.07,
        loc=(-480, 220),
    )
    tone_s = _math(
        group,
        "MULTIPLY",
        tone.outputs["Result"],
        streak_fac.outputs["Result"],
        loc=(-240, 220),
    )
    base = _mix_rgb(
        group,
        "MULTIPLY",
        1.0,
        inp.outputs["Tint"],
        tone_s.outputs["Value"],
        loc=(0, 260),
    )
    # Warm earthy ochre tint in aged mottling patches.
    warm_mask = _map_range(
        group,
        medium.outputs["Fac"],
        0.48,
        0.80,
        0.0,
        0.22,
        interp="SMOOTHSTEP",
        loc=(-240, 20),
    )
    warm_col = _mix_rgb(
        group,
        "MIX",
        warm_mask.outputs["Result"],
        base.outputs["Color"],
        (0.32, 0.26, 0.17, 1.0),
        loc=(200, 260),
    )
    # Darken hairline cracks subtly rather than sharp black lines.
    crack_blend = _map_range(
        group,
        crack_mask.outputs["Value"],
        0.0,
        1.0,
        0.66,
        1.0,
        loc=(200, -580),
    )
    crack_col = _mix_rgb(
        group,
        "MULTIPLY",
        1.0,
        warm_col.outputs["Color"],
        crack_blend.outputs["Result"],
        loc=(400, 260),
    )
    # Rising damp mossy/earthy stain near foundation.
    damp_fac = _math(
        group, "MULTIPLY", damp_mask.outputs["Result"], 0.48, loc=(200, -140)
    )
    damp_col = _mix_rgb(
        group,
        "MIX",
        damp_fac.outputs["Value"],
        crack_col.outputs["Color"],
        (0.12, 0.13, 0.08, 1.0),
        loc=(580, 260),
    )
    # Apply AO crevice darkening.
    final_col = _mix_rgb(
        group,
        "MULTIPLY",
        1.0,
        damp_col.outputs["Color"],
        ao_shade.outputs["Result"],
        loc=(760, 260),
    )
    _link(group, final_col.outputs["Color"], out.inputs["Color"])

    # Two-stage stucco bump (sand grit and trowel undulations).
    fine_h = _math(
        group,
        "MULTIPLY",
        grit.outputs["Fac"],
        crack_mask.outputs["Value"],
        loc=(180, -360),
    )
    bump_fine = _bump(
        group, fine_h.outputs["Value"], 0.45, 0.004, loc=(440, -340)
    )
    bump_coarse = _bump(
        group,
        medium.outputs["Fac"],
        0.52,
        0.011,
        normal=bump_fine.outputs["Normal"],
        loc=(680, -340),
    )
    _link(group, bump_coarse.outputs["Normal"], out.inputs["Normal"])

    # Chalky plaster roughness, rougher in AO crevices and damp areas.
    rough_base = _map_range(
        group, grit.outputs["Fac"], 0.25, 0.78, 0.77, 0.94, loc=(440, -560)
    )
    ao_inv = _map_range(
        group, ao.outputs["AO"], 0.25, 0.9, 0.08, 0.0, loc=(440, -740)
    )
    rough = _math(
        group,
        "ADD",
        rough_base.outputs["Result"],
        ao_inv.outputs["Result"],
        clamp=True,
        loc=(680, -560),
    )
    _link(group, rough.outputs["Value"], out.inputs["Roughness"])


def _build_timber(group, inp, out):
    coords = group.nodes.new("ShaderNodeTexCoord")
    coords.location = (-1300, 0)

    # Grain-aligned UV stretched along beams and warped by 3D noise.
    stretch = _vec_math(
        group,
        "MULTIPLY",
        coords.outputs["UV"],
        (1.6, 22.0, 1.0),
        loc=(-1060, 140),
    )
    warp_noise = _noise(
        group, coords.outputs["Object"], 2.4, detail=4.0, loc=(-1060, -80)
    )
    warped = _mix_rgb(
        group,
        "MIX",
        0.045,
        stretch.outputs["Vector"],
        warp_noise.outputs["Color"],
        loc=(-840, 140),
    )

    # Cathedral growth rings + fine fibrous oak grain.
    rings = group.nodes.new("ShaderNodeTexWave")
    rings.location = (-620, 260)
    rings.wave_type = "BANDS"
    rings.bands_direction = "Y"
    rings.wave_profile = "SIN"
    rings.inputs["Scale"].default_value = 0.35
    rings.inputs["Distortion"].default_value = 7.5
    rings.inputs["Detail"].default_value = 6.0
    rings.inputs["Detail Scale"].default_value = 2.0
    _link(group, warped.outputs["Color"], rings.inputs["Vector"])

    fibers = _noise(
        group,
        warped.outputs["Color"],
        2.6,
        detail=8.0,
        roughness=0.68,
        loc=(-620, 20),
    )
    adzed = _noise(
        group, coords.outputs["Object"], 3.2, detail=3.0, loc=(-620, -220)
    )

    # Longitudinal seasoning cracks / wood checks.
    check_vec = _vec_math(
        group,
        "MULTIPLY",
        coords.outputs["UV"],
        (0.65, 11.0, 1.0),
        loc=(-840, -400),
    )
    checks = _voronoi(
        group,
        check_vec.outputs["Vector"],
        1.8,
        feature="DISTANCE_TO_EDGE",
        loc=(-620, -400),
    )
    check_mask = _map_range(
        group,
        checks.outputs["Distance"],
        0.0,
        0.022,
        0.0,
        1.0,
        interp="SMOOTHSTEP",
        loc=(-380, -400),
    )

    grain_mix = _math(
        group,
        "MULTIPLY",
        rings.outputs["Fac"],
        0.42,
        loc=(-380, 240),
    )
    grain_comb = _math(
        group,
        "ADD",
        grain_mix.outputs["Value"],
        _math(
            group, "MULTIPLY", fibers.outputs["Fac"], 0.58, loc=(-380, 60)
        ).outputs["Value"],
        clamp=True,
        loc=(-180, 160),
    )

    shade = _map_range(
        group,
        grain_comb.outputs["Value"],
        0.18,
        0.84,
        0.54,
        1.16,
        loc=(20, 220),
    )
    ao = _ao_node(group, distance=0.28, samples=8, loc=(-180, 420))
    ao_shade = _map_range(
        group,
        ao.outputs["AO"],
        0.20,
        0.95,
        0.42,
        1.0,
        interp="SMOOTHSTEP",
        loc=(20, 420),
    )

    # Subtle worn edge highlight via Geometry Pointiness.
    geom = group.nodes.new("ShaderNodeNewGeometry")
    geom.location = (-380, 600)
    edge = _map_range(
        group,
        geom.outputs["Pointiness"],
        0.51,
        0.58,
        0.0,
        0.16,
        interp="SMOOTHSTEP",
        loc=(-140, 600),
    )

    base = _mix_rgb(
        group,
        "MULTIPLY",
        1.0,
        inp.outputs["Tint"],
        shade.outputs["Result"],
        loc=(240, 260),
    )
    # Darken longitudinal checks.
    cracked = _mix_rgb(
        group,
        "MIX",
        check_mask.outputs["Result"],
        (0.035, 0.024, 0.016, 1.0),
        base.outputs["Color"],
        loc=(430, 260),
    )
    # Bleached weathered edge wear.
    worn = _mix_rgb(
        group,
        "MIX",
        edge.outputs["Result"],
        cracked.outputs["Color"],
        (0.32, 0.27, 0.21, 1.0),
        loc=(600, 260),
    )
    final_col = _mix_rgb(
        group,
        "MULTIPLY",
        1.0,
        worn.outputs["Color"],
        ao_shade.outputs["Result"],
        loc=(780, 260),
    )
    _link(group, final_col.outputs["Color"], out.inputs["Color"])

    # Two-stage wood bump: fine grain + checks, then hewn adze waves.
    fine_h = _math(
        group,
        "MULTIPLY",
        grain_comb.outputs["Value"],
        check_mask.outputs["Result"],
        loc=(240, -240),
    )
    bump_grain = _bump(
        group, fine_h.outputs["Value"], 0.65, 0.007, loc=(460, -240)
    )
    bump_adze = _bump(
        group,
        adzed.outputs["Fac"],
        0.35,
        0.012,
        normal=bump_grain.outputs["Normal"],
        loc=(680, -240),
    )
    _link(group, bump_adze.outputs["Normal"], out.inputs["Normal"])

    # Worn grain crests stay satin (~0.44); dark grooves matte (~0.88).
    rough_grain = _map_range(
        group,
        grain_comb.outputs["Value"],
        0.2,
        0.82,
        0.86,
        0.44,
        loc=(460, -480),
    )
    ao_rough = _map_range(
        group, ao.outputs["AO"], 0.25, 0.9, 0.14, 0.0, loc=(460, -660)
    )
    rough = _math(
        group,
        "ADD",
        rough_grain.outputs["Result"],
        ao_rough.outputs["Result"],
        clamp=True,
        loc=(680, -480),
    )
    _link(group, rough.outputs["Value"], out.inputs["Roughness"])


def _build_clay(group, inp, out):
    coords = group.nodes.new("ShaderNodeTexCoord")
    coords.location = (-1300, 0)
    obj = coords.outputs["Object"]
    geom = group.nodes.new("ShaderNodeNewGeometry")
    geom.location = (-1300, -480)

    # Kiln-fired mottled terracotta variation + fine mineral speckle.
    macro = _noise(
        group, obj, 2.4, detail=6.0, roughness=0.64, loc=(-1000, 260)
    )
    speck = _noise(
        group, obj, 44.0, detail=7.0, roughness=0.72, loc=(-1000, 40)
    )
    warp = _noise(
        group, obj, 6.2, detail=4.0, roughness=0.55, loc=(-1000, -180)
    )

    # Rainwater and chimney soot streaks down roof slopes.
    soot = _noise(
        group, obj, 0.85, detail=5.0, roughness=0.68, loc=(-1000, -400)
    )
    ao = _ao_node(group, distance=0.22, samples=8, loc=(-740, 480))
    ao_shade = _map_range(
        group,
        ao.outputs["AO"],
        0.22,
        0.95,
        0.62,
        1.0,
        interp="SMOOTHSTEP",
        loc=(-480, 480),
    )

    # Moss growth in shaded upward-facing tile troughs & valleys.
    n_xyz = group.nodes.new("ShaderNodeSeparateXYZ")
    n_xyz.location = (-1000, -620)
    _link(group, geom.outputs["Normal"], n_xyz.inputs["Vector"])
    up_mask = _map_range(
        group,
        n_xyz.outputs["Z"],
        0.38,
        0.78,
        0.0,
        1.0,
        interp="SMOOTHSTEP",
        loc=(-740, -620),
    )
    moss_noise = _noise(
        group, obj, 1.8, detail=7.0, roughness=0.72, loc=(-740, -820)
    )
    # Prefer moss in crevices (low AO) and organic clusters.
    crevice_boost = _map_range(
        group, ao.outputs["AO"], 0.35, 0.95, 0.24, 0.0, loc=(-500, -820)
    )
    moss_signal = _math(
        group,
        "ADD",
        moss_noise.outputs["Fac"],
        crevice_boost.outputs["Result"],
        loc=(-280, -760),
    )
    moss_patch = _map_range(
        group,
        moss_signal.outputs["Value"],
        0.58,
        0.76,
        0.0,
        0.82,
        interp="SMOOTHSTEP",
        loc=(-60, -760),
    )
    moss_mask = _math(
        group,
        "MULTIPLY",
        moss_patch.outputs["Result"],
        up_mask.outputs["Result"],
        clamp=True,
        loc=(160, -700),
    )

    # Sparse pale sage lichen flecks.
    lichen_noise = _voronoi(group, obj, 14.0, feature="F1", loc=(-500, -1020))
    lichen_spot = _map_range(
        group,
        lichen_noise.outputs["Distance"],
        0.0,
        0.13,
        0.42,
        0.0,
        interp="SMOOTHSTEP",
        loc=(-260, -1020),
    )
    lichen_gate = _map_range(
        group, soot.outputs["Fac"], 0.62, 0.78, 0.0, 1.0, loc=(-260, -1200)
    )
    lichen_mask = _math(
        group,
        "MULTIPLY",
        lichen_spot.outputs["Result"],
        _math(
            group,
            "MULTIPLY",
            lichen_gate.outputs["Result"],
            up_mask.outputs["Result"],
            loc=(-40, -1120),
        ).outputs["Value"],
        clamp=True,
        loc=(160, -1040),
    )

    # Kiln tone variation: warm terracotta, ochre, and subtle umber.
    kiln_shade = _map_range(
        group, macro.outputs["Fac"], 0.22, 0.80, 0.74, 1.20, loc=(-480, 260)
    )
    soot_shade = _map_range(
        group, soot.outputs["Fac"], 0.28, 0.78, 0.80, 1.08, loc=(-480, 40)
    )
    comb_shade = _math(
        group,
        "MULTIPLY",
        kiln_shade.outputs["Result"],
        soot_shade.outputs["Result"],
        loc=(-240, 200),
    )
    clay_base = _mix_rgb(
        group,
        "MULTIPLY",
        1.0,
        inp.outputs["Tint"],
        comb_shade.outputs["Value"],
        loc=(0, 240),
    )
    # Subtle kiln-fired umber scorch in darker areas.
    scorch_mask = _map_range(
        group,
        macro.outputs["Fac"],
        0.18,
        0.42,
        0.18,
        0.0,
        interp="SMOOTHSTEP",
        loc=(0, 40),
    )
    scorched = _mix_rgb(
        group,
        "MIX",
        scorch_mask.outputs["Result"],
        clay_base.outputs["Color"],
        (0.11, 0.055, 0.032, 1.0),
        loc=(220, 240),
    )
    # Blend moss & pale lichen on top.
    mossy = _mix_rgb(
        group,
        "MIX",
        moss_mask.outputs["Value"],
        scorched.outputs["Color"],
        (0.068, 0.112, 0.032, 1.0),
        loc=(420, 240),
    )
    lichened = _mix_rgb(
        group,
        "MIX",
        lichen_mask.outputs["Value"],
        mossy.outputs["Color"],
        (0.32, 0.35, 0.24, 1.0),
        loc=(600, 240),
    )
    final_col = _mix_rgb(
        group,
        "MULTIPLY",
        1.0,
        lichened.outputs["Color"],
        ao_shade.outputs["Result"],
        loc=(780, 240),
    )
    _link(group, final_col.outputs["Color"], out.inputs["Color"])

    # Two-stage fired clay + moss bump.
    bump_grit = _bump(
        group, speck.outputs["Fac"], 0.62, 0.006, loc=(440, -240)
    )
    bump_warp = _bump(
        group,
        warp.outputs["Fac"],
        0.48,
        0.013,
        normal=bump_grit.outputs["Normal"],
        loc=(680, -240),
    )
    _link(group, bump_warp.outputs["Normal"], out.inputs["Normal"])

    # Porous unglazed terracotta roughness (~0.76-0.96) prevents glare.
    clay_rough = _map_range(
        group, speck.outputs["Fac"], 0.22, 0.78, 0.76, 0.94, loc=(440, -480)
    )
    rough_moss = _math(
        group,
        "MAXIMUM",
        clay_rough.outputs["Result"],
        _map_range(
            group,
            moss_mask.outputs["Value"],
            0.0,
            1.0,
            0.76,
            0.98,
            loc=(440, -660),
        ).outputs["Result"],
        loc=(680, -480),
    )
    _link(group, rough_moss.outputs["Value"], out.inputs["Roughness"])


def _build_stone(group, inp, out, *, crag=False):
    coords = group.nodes.new("ShaderNodeTexCoord")
    coords.location = (-1350, 0)
    obj = coords.outputs["Object"]
    geom = group.nodes.new("ShaderNodeNewGeometry")
    geom.location = (-1350, -520)

    # Stratified rock or chiseled ashlar stone blocks.
    strata_scale = (1.0, 1.0, 2.5) if crag else (1.0, 1.0, 1.45)
    strata_vec = _vec_math(
        group, "MULTIPLY", obj, strata_scale, loc=(-1100, 180)
    )
    ridged = _noise(
        group,
        strata_vec.outputs["Vector"],
        2.6 if crag else 3.2,
        detail=8.0,
        roughness=0.68,
        noise_type="RIDGED_MULTIFRACTAL",
        loc=(-860, 240),
    )
    grit = _noise(
        group,
        obj,
        34.0 if crag else 46.0,
        detail=8.0,
        roughness=0.72,
        loc=(-860, 0),
    )

    # Voronoi stone facets + fractured edge grooves.
    vor_warp = _mix_rgb(
        group, "MIX", 0.06, obj, ridged.outputs["Color"], loc=(-860, -240)
    )
    vor_scale = 2.8 if crag else 2.2
    cells = _voronoi(
        group,
        vor_warp.outputs["Color"],
        vor_scale,
        feature="F1",
        loc=(-620, -140),
    )
    edges = _voronoi(
        group,
        vor_warp.outputs["Color"],
        vor_scale,
        feature="DISTANCE_TO_EDGE",
        loc=(-620, -360),
    )
    crack_w = 0.045 if crag else 0.032
    crack = _map_range(
        group,
        edges.outputs["Distance"],
        0.0,
        crack_w,
        0.0,
        1.0,
        interp="SMOOTHSTEP",
        loc=(-380, -360),
    )

    ao = _ao_node(
        group, distance=0.55 if crag else 0.42, samples=8, loc=(-620, 480)
    )
    ao_shade = _map_range(
        group,
        ao.outputs["AO"],
        0.18,
        0.95,
        0.36 if crag else 0.40,
        1.0,
        interp="SMOOTHSTEP",
        loc=(-360, 480),
    )

    # Moss growth on upward-facing stone ledges & boulder crowns.
    n_xyz = group.nodes.new("ShaderNodeSeparateXYZ")
    n_xyz.location = (-1080, -640)
    _link(group, geom.outputs["Normal"], n_xyz.inputs["Vector"])
    moss_noise = _noise(
        group, obj, 2.2, detail=6.0, roughness=0.72, loc=(-840, -760)
    )
    n_perturb = _map_range(
        group,
        moss_noise.outputs["Fac"],
        0.2,
        0.8,
        -0.18,
        0.18,
        loc=(-600, -760),
    )
    up_signal = _math(
        group,
        "ADD",
        n_xyz.outputs["Z"],
        n_perturb.outputs["Result"],
        loc=(-360, -680),
    )
    moss_mask = _map_range(
        group,
        up_signal.outputs["Value"],
        0.54 if crag else 0.68,
        0.82 if crag else 0.90,
        0.0,
        0.82 if crag else 0.42,
        interp="SMOOTHSTEP",
        loc=(-120, -680),
    )

    # Combine per-block cell tone + mineral veins + dark cracks.
    cell_bw = group.nodes.new("ShaderNodeRGBToBW")
    cell_bw.location = (-380, -140)
    _link(group, cells.outputs["Color"], cell_bw.inputs["Color"])
    cell_tone = _map_range(
        group, cell_bw.outputs["Val"], 0.0, 1.0, 0.78, 1.15, loc=(-160, -140)
    )
    vein_tone = _map_range(
        group, ridged.outputs["Fac"], 0.15, 0.85, 0.72, 1.16, loc=(-160, 160)
    )
    stone_shade = _math(
        group,
        "MULTIPLY",
        cell_tone.outputs["Result"],
        vein_tone.outputs["Result"],
        loc=(60, 180),
    )
    base = _mix_rgb(
        group,
        "MULTIPLY",
        1.0,
        inp.outputs["Tint"],
        stone_shade.outputs["Value"],
        loc=(260, 220),
    )
    fractured = _mix_rgb(
        group,
        "MIX",
        crack.outputs["Result"],
        (0.06, 0.058, 0.052, 1.0),
        base.outputs["Color"],
        loc=(450, 220),
    )
    mossy = _mix_rgb(
        group,
        "MIX",
        moss_mask.outputs["Result"],
        fractured.outputs["Color"],
        (0.048, 0.092, 0.026, 1.0),
        loc=(620, 220),
    )
    final_col = _mix_rgb(
        group,
        "MULTIPLY",
        1.0,
        mossy.outputs["Color"],
        ao_shade.outputs["Result"],
        loc=(790, 220),
    )
    _link(group, final_col.outputs["Color"], out.inputs["Color"])

    # Two-stage stone bump: crystalline grit and fractured strata.
    bump_grit = _bump(
        group,
        grit.outputs["Fac"],
        0.55,
        0.008 if crag else 0.006,
        loc=(420, -280),
    )
    coarse_h = _math(
        group,
        "MULTIPLY",
        ridged.outputs["Fac"],
        crack.outputs["Result"],
        loc=(180, -340),
    )
    bump_crag = _bump(
        group,
        coarse_h.outputs["Value"],
        0.82 if crag else 0.72,
        0.032 if crag else 0.020,
        normal=bump_grit.outputs["Normal"],
        loc=(680, -280),
    )
    _link(group, bump_crag.outputs["Normal"], out.inputs["Normal"])

    # Mineral micro-glint vs rough fractures and mossy caps.
    stone_rough = _map_range(
        group, grit.outputs["Fac"], 0.25, 0.80, 0.54, 0.94, loc=(420, -520)
    )
    moss_rough = _map_range(
        group,
        moss_mask.outputs["Result"],
        0.0,
        1.0,
        0.54,
        0.96,
        loc=(420, -700),
    )
    rough = _math(
        group,
        "MAXIMUM",
        stone_rough.outputs["Result"],
        moss_rough.outputs["Result"],
        loc=(680, -520),
    )
    _link(group, rough.outputs["Value"], out.inputs["Roughness"])


def _build_slate(group, inp, out):
    coords = group.nodes.new("ShaderNodeTexCoord")
    coords.location = (-1200, 0)
    obj = coords.outputs["Object"]

    cleave_vec = _vec_math(
        group, "MULTIPLY", obj, (1.0, 1.0, 3.8), loc=(-960, 180)
    )
    cleave = _noise(
        group,
        cleave_vec.outputs["Vector"],
        4.5,
        detail=7.0,
        roughness=0.65,
        noise_type="RIDGED_MULTIFRACTAL",
        loc=(-720, 180),
    )
    shingles = _voronoi(group, obj, 5.2, feature="F1", loc=(-720, -60))
    edges = _voronoi(
        group, obj, 5.2, feature="DISTANCE_TO_EDGE", loc=(-720, -280)
    )
    grit = _noise(group, obj, 48.0, detail=6.0, loc=(-720, -480))
    ao = _ao_node(group, distance=0.35, samples=8, loc=(-460, 420))
    ao_shade = _map_range(
        group, ao.outputs["AO"], 0.2, 0.95, 0.45, 1.0, loc=(-200, 420)
    )

    cell_bw = group.nodes.new("ShaderNodeRGBToBW")
    cell_bw.location = (-460, -60)
    _link(group, shingles.outputs["Color"], cell_bw.inputs["Color"])
    tone = _map_range(
        group, cell_bw.outputs["Val"], 0.0, 1.0, 0.74, 1.18, loc=(-200, 40)
    )
    base = _mix_rgb(
        group,
        "MULTIPLY",
        1.0,
        inp.outputs["Tint"],
        tone.outputs["Result"],
        loc=(180, 220),
    )
    final_col = _mix_rgb(
        group,
        "MULTIPLY",
        1.0,
        base.outputs["Color"],
        ao_shade.outputs["Result"],
        loc=(560, 220),
    )
    _link(group, final_col.outputs["Color"], out.inputs["Color"])

    edge_cut = _map_range(
        group, edges.outputs["Distance"], 0.0, 0.04, 0.0, 1.0, loc=(-360, -280)
    )
    h = _math(
        group,
        "MULTIPLY",
        cleave.outputs["Fac"],
        edge_cut.outputs["Result"],
        loc=(100, -240),
    )
    b1 = _bump(group, grit.outputs["Fac"], 0.38, 0.004, loc=(360, -240))
    b2 = _bump(
        group,
        h.outputs["Value"],
        0.62,
        0.014,
        normal=b1.outputs["Normal"],
        loc=(620, -240),
    )
    _link(group, b2.outputs["Normal"], out.inputs["Normal"])

    rough = _map_range(
        group, cleave.outputs["Fac"], 0.2, 0.85, 0.34, 0.72, loc=(620, -480)
    )
    _link(group, rough.outputs["Result"], out.inputs["Roughness"])


def _build_metal(group, inp, out):
    coords = group.nodes.new("ShaderNodeTexCoord")
    coords.location = (-1100, 0)
    obj = coords.outputs["Object"]

    hammered = _voronoi(group, obj, 34.0, feature="SMOOTH_F1", loc=(-820, 120))
    grit = _noise(
        group, obj, 85.0, detail=6.0, roughness=0.7, loc=(-820, -120)
    )
    patina_n = _noise(group, obj, 6.5, detail=5.0, loc=(-820, -340))
    ao = _ao_node(group, distance=0.18, samples=8, loc=(-560, 360))
    ao_inv = _map_range(
        group, ao.outputs["AO"], 0.25, 0.92, 0.65, 0.0, loc=(-300, 360)
    )
    rust_mask = _math(
        group,
        "MULTIPLY",
        ao_inv.outputs["Result"],
        _map_range(
            group,
            patina_n.outputs["Fac"],
            0.35,
            0.75,
            0.3,
            1.0,
            loc=(-300, -340),
        ).outputs["Result"],
        clamp=True,
        loc=(-40, 200),
    )

    shade = _map_range(
        group, patina_n.outputs["Fac"], 0.25, 0.8, 0.72, 1.12, loc=(-300, 120)
    )
    base = _mix_rgb(
        group,
        "MULTIPLY",
        1.0,
        inp.outputs["Tint"],
        shade.outputs["Result"],
        loc=(180, 220),
    )
    weathered = _mix_rgb(
        group,
        "MIX",
        rust_mask.outputs["Value"],
        base.outputs["Color"],
        (0.11, 0.052, 0.024, 1.0),
        loc=(520, 220),
    )
    _link(group, weathered.outputs["Color"], out.inputs["Color"])

    b1 = _bump(group, grit.outputs["Fac"], 0.28, 0.002, loc=(320, -180))
    b2 = _bump(
        group,
        hammered.outputs["Distance"],
        0.35,
        0.004,
        normal=b1.outputs["Normal"],
        loc=(600, -180),
    )
    _link(group, b2.outputs["Normal"], out.inputs["Normal"])

    rough_base = _map_range(
        group, grit.outputs["Fac"], 0.2, 0.8, 0.26, 0.50, loc=(320, -420)
    )
    rough = _math(
        group,
        "ADD",
        rough_base.outputs["Result"],
        _math(
            group,
            "MULTIPLY",
            rust_mask.outputs["Value"],
            0.34,
            loc=(320, -600),
        ).outputs["Value"],
        clamp=True,
        loc=(600, -420),
    )
    _link(group, rough.outputs["Value"], out.inputs["Roughness"])


def _build_fabric(group, inp, out):
    coords = group.nodes.new("ShaderNodeTexCoord")
    coords.location = (-1100, 0)
    uv = coords.outputs["UV"]
    obj = coords.outputs["Object"]

    warp = group.nodes.new("ShaderNodeTexWave")
    warp.location = (-820, 120)
    warp.wave_type = "BANDS"
    warp.bands_direction = "X"
    warp.inputs["Scale"].default_value = 55.0
    _link(group, uv, warp.inputs["Vector"])

    weft = group.nodes.new("ShaderNodeTexWave")
    weft.location = (-820, -140)
    weft.wave_type = "BANDS"
    weft.bands_direction = "Y"
    weft.inputs["Scale"].default_value = 55.0
    _link(group, uv, weft.inputs["Vector"])

    weave = _math(
        group,
        "ADD",
        _math(
            group, "MULTIPLY", warp.outputs["Fac"], 0.5, loc=(-560, 120)
        ).outputs["Value"],
        _math(
            group, "MULTIPLY", weft.outputs["Fac"], 0.5, loc=(-560, -140)
        ).outputs["Value"],
        loc=(-320, 0),
    )
    fade = _noise(group, obj, 1.8, detail=5.0, loc=(-560, 340))
    ao = _ao_node(group, distance=0.30, samples=8, loc=(-560, 560))
    ao_shade = _map_range(
        group, ao.outputs["AO"], 0.25, 0.95, 0.52, 1.0, loc=(-240, 560)
    )

    fade_tone = _map_range(
        group, fade.outputs["Fac"], 0.25, 0.78, 0.80, 1.10, loc=(-240, 340)
    )
    base = _mix_rgb(
        group,
        "MULTIPLY",
        1.0,
        inp.outputs["Tint"],
        fade_tone.outputs["Result"],
        loc=(160, 260),
    )
    final_col = _mix_rgb(
        group,
        "MULTIPLY",
        1.0,
        base.outputs["Color"],
        ao_shade.outputs["Result"],
        loc=(520, 260),
    )
    _link(group, final_col.outputs["Color"], out.inputs["Color"])

    bump = _bump(group, weave.outputs["Value"], 0.45, 0.0025, loc=(520, -140))
    _link(group, bump.outputs["Normal"], out.inputs["Normal"])

    rough = _map_range(
        group, weave.outputs["Value"], 0.0, 1.0, 0.80, 0.95, loc=(520, -360)
    )
    _link(group, rough.outputs["Result"], out.inputs["Roughness"])


def build_pbr_surface_group(kind):
    """Build or reuse a rich AAA procedural PBR shader node group."""
    name = f"Asgen PBR {kind.title()} Surface"
    if group := bpy.data.node_groups.get(name):
        return group
    group, inp, out = _new_surface_group(name)
    builders = {
        "plaster": _build_plaster,
        "timber": _build_timber,
        "clay": _build_clay,
        "stone": lambda g, i, o: _build_stone(g, i, o, crag=False),
        "rock": lambda g, i, o: _build_stone(g, i, o, crag=True),
        "slate": _build_slate,
        "metal": _build_metal,
        "fabric": _build_fabric,
    }
    builders[kind](group, inp, out)
    return group


def configure_pbr_shader_extras(shader, kind):
    """Set calibrated Principled BSDF properties per surface kind."""
    if "Diffuse Roughness" in shader.inputs:
        shader.inputs["Diffuse Roughness"].default_value = {
            "plaster": 0.65,
            "timber": 0.30,
            "clay": 0.55,
            "stone": 0.70,
            "rock": 0.75,
            "slate": 0.35,
            "metal": 0.10,
            "fabric": 0.70,
        }.get(kind, 0.35)
    if "Specular IOR Level" in shader.inputs:
        shader.inputs["Specular IOR Level"].default_value = {
            "plaster": 0.28,
            "timber": 0.42,
            "clay": 0.22,
            "stone": 0.38,
            "rock": 0.38,
            "slate": 0.50,
            "metal": 0.55,
            "fabric": 0.20,
        }.get(kind, 0.5)
    if kind == "metal":
        shader.inputs["Metallic"].default_value = 0.86
    elif kind == "fabric":
        if "Sheen Weight" in shader.inputs:
            shader.inputs["Sheen Weight"].default_value = 0.48
        if "Sheen Roughness" in shader.inputs:
            shader.inputs["Sheen Roughness"].default_value = 0.65


def configure_realistic_glass(material, shader):
    """Hand-blown wavy medieval crown glass with sky reflections."""
    tree = material.node_tree
    shader.inputs["Base Color"].default_value = (0.76, 0.86, 0.84, 1.0)
    shader.inputs["Transmission Weight"].default_value = 0.92
    shader.inputs["IOR"].default_value = 1.52
    if "Coat Weight" in shader.inputs:
        shader.inputs["Coat Weight"].default_value = 0.65
        shader.inputs["Coat Roughness"].default_value = 0.03
    if "Specular IOR Level" in shader.inputs:
        shader.inputs["Specular IOR Level"].default_value = 0.62

    coords = tree.nodes.new("ShaderNodeTexCoord")
    coords.location = (shader.location.x - 760, shader.location.y - 160)
    wave = _noise(
        tree,
        coords.outputs["Object"],
        3.2,
        detail=2.0,
        roughness=0.45,
        loc=(shader.location.x - 520, shader.location.y - 220),
    )
    bump = _bump(
        tree,
        wave.outputs["Fac"],
        0.09,
        0.003,
        loc=(shader.location.x - 240, shader.location.y - 220),
    )
    _link(tree, bump.outputs["Normal"], shader.inputs["Normal"])

    # Subtle grime/dust raising roughness right near the frame muntins.
    ao = _ao_node(
        tree,
        distance=0.14,
        samples=6,
        loc=(shader.location.x - 520, shader.location.y - 40),
    )
    rough = _map_range(
        tree,
        ao.outputs["AO"],
        0.30,
        0.95,
        0.24,
        0.04,
        interp="SMOOTHSTEP",
        loc=(shader.location.x - 240, shader.location.y - 40),
    )
    _link(tree, rough.outputs["Result"], shader.inputs["Roughness"])


def configure_realistic_bark(material, shader):
    """Deeply furrowed tree bark with mossy base and crevice AO."""
    tree = material.node_tree
    coords = tree.nodes.new("ShaderNodeTexCoord")
    coords.location = (-1200, 0)
    obj = coords.outputs["Object"]

    stretched = _vec_math(
        tree, "MULTIPLY", obj, (14.0, 14.0, 2.2), loc=(-960, 140)
    )
    furrows = _noise(
        tree,
        stretched.outputs["Vector"],
        1.45,
        detail=8.0,
        roughness=0.72,
        noise_type="RIDGED_MULTIFRACTAL",
        loc=(-720, 200),
    )
    cracks = _voronoi(
        tree,
        stretched.outputs["Vector"],
        1.8,
        feature="DISTANCE_TO_EDGE",
        loc=(-720, -40),
    )
    flakes = _noise(
        tree, obj, 42.0, detail=7.0, roughness=0.75, loc=(-720, -260)
    )

    ao = _ao_node(tree, distance=0.45, samples=8, loc=(-460, 420))
    ao_shade = _map_range(
        tree, ao.outputs["AO"], 0.2, 0.95, 0.36, 1.0, loc=(-200, 420)
    )

    # Moss growth near trunk base.
    gen_xyz = tree.nodes.new("ShaderNodeSeparateXYZ")
    gen_xyz.location = (-960, -460)
    _link(tree, coords.outputs["Generated"], gen_xyz.inputs["Vector"])
    moss_n = _noise(tree, obj, 3.0, detail=6.0, loc=(-720, -560))
    moss_h = _math(
        tree,
        "ADD",
        gen_xyz.outputs["Z"],
        _map_range(
            tree,
            moss_n.outputs["Fac"],
            0.2,
            0.8,
            -0.14,
            0.14,
            loc=(-480, -560),
        ).outputs["Result"],
        loc=(-260, -480),
    )
    moss_mask = _map_range(
        tree,
        moss_h.outputs["Value"],
        0.0,
        0.24,
        0.68,
        0.0,
        interp="SMOOTHSTEP",
        loc=(-20, -480),
    )

    fissure = _map_range(
        tree, cracks.outputs["Distance"], 0.0, 0.18, 0.0, 1.0, loc=(-460, -40)
    )
    ridge_h = _math(
        tree,
        "MULTIPLY",
        furrows.outputs["Fac"],
        fissure.outputs["Result"],
        loc=(-220, 40),
    )

    ramp = tree.nodes.new("ShaderNodeValToRGB")
    ramp.location = (20, 200)
    ramp.color_ramp.elements[0].position = 0.12
    ramp.color_ramp.elements[0].color = (0.028, 0.020, 0.014, 1.0)
    mid = ramp.color_ramp.elements.new(0.52)
    mid.color = (0.095, 0.072, 0.052, 1.0)
    ramp.color_ramp.elements[-1].position = 0.90
    ramp.color_ramp.elements[-1].color = (0.20, 0.17, 0.135, 1.0)
    _link(tree, ridge_h.outputs["Value"], ramp.inputs["Fac"])

    mossy = _mix_rgb(
        tree,
        "MIX",
        moss_mask.outputs["Result"],
        ramp.outputs["Color"],
        (0.048, 0.092, 0.028, 1.0),
        loc=(320, 200),
    )
    final_col = _mix_rgb(
        tree,
        "MULTIPLY",
        1.0,
        mossy.outputs["Color"],
        ao_shade.outputs["Result"],
        loc=(540, 200),
    )
    _link(tree, final_col.outputs["Color"], shader.inputs["Base Color"])

    b_fine = _bump(tree, flakes.outputs["Fac"], 0.50, 0.006, loc=(240, -180))
    b_deep = _bump(
        tree,
        ridge_h.outputs["Value"],
        0.88,
        0.028,
        normal=b_fine.outputs["Normal"],
        loc=(480, -180),
    )
    _link(tree, b_deep.outputs["Normal"], shader.inputs["Normal"])

    rough = _map_range(
        tree, ridge_h.outputs["Value"], 0.1, 0.9, 0.96, 0.72, loc=(480, -400)
    )
    _link(tree, rough.outputs["Result"], shader.inputs["Roughness"])
    if "Diffuse Roughness" in shader.inputs:
        shader.inputs["Diffuse Roughness"].default_value = 0.75


def configure_realistic_foliage(material, shader):
    """Backlit translucent canopy leaves with AO and waxy sheen."""
    tree = material.node_tree
    geom = tree.nodes.new("ShaderNodeNewGeometry")
    geom.location = (-1040, 120)
    coords = tree.nodes.new("ShaderNodeTexCoord")
    coords.location = (-1040, -140)

    # World-space sunlit warmth variation across branches and crowns.
    variation = _noise(
        tree,
        geom.outputs["Position"],
        0.85,
        detail=5.0,
        roughness=0.65,
        loc=(-780, 160),
    )
    veins = _noise(
        tree,
        geom.outputs["Position"],
        26.0,
        detail=5.0,
        roughness=0.6,
        loc=(-780, -120),
    )

    ao = _ao_node(tree, distance=0.85, samples=6, loc=(-780, 380))
    ao_shade = _map_range(
        tree,
        ao.outputs["AO"],
        0.18,
        0.92,
        0.38,
        1.08,
        interp="SMOOTHSTEP",
        loc=(-500, 380),
    )

    # Sun-warmed yellow-green outer tips vs deep cool interior shadows.
    base_rgb = tuple(material.diffuse_color)
    warm_leaf = (
        min(1.0, base_rgb[0] * 1.48),
        min(1.0, base_rgb[1] * 1.28),
        base_rgb[2] * 0.65,
        1.0,
    )
    cool_leaf = (
        base_rgb[0] * 0.68,
        base_rgb[1] * 0.82,
        base_rgb[2] * 0.78,
        1.0,
    )
    var_fac = _map_range(
        tree, variation.outputs["Fac"], 0.25, 0.78, 0.0, 1.0, loc=(-500, 160)
    )
    tinted = _mix_rgb(
        tree,
        "MIX",
        var_fac.outputs["Result"],
        cool_leaf,
        warm_leaf,
        loc=(-240, 200),
    )
    shaded = _mix_rgb(
        tree,
        "MULTIPLY",
        1.0,
        tinted.outputs["Color"],
        ao_shade.outputs["Result"],
        loc=(0, 240),
    )
    _link(tree, shaded.outputs["Color"], shader.inputs["Base Color"])

    # Waxy leaf cuticle specular + subtle micro-vein bump.
    rough = _map_range(
        tree, veins.outputs["Fac"], 0.2, 0.8, 0.34, 0.56, loc=(0, -60)
    )
    _link(tree, rough.outputs["Result"], shader.inputs["Roughness"])
    if "Specular IOR Level" in shader.inputs:
        shader.inputs["Specular IOR Level"].default_value = 0.52
    if "Coat Weight" in shader.inputs:
        shader.inputs["Coat Weight"].default_value = 0.14
        shader.inputs["Coat Roughness"].default_value = 0.28
    if "Subsurface Weight" in shader.inputs:
        shader.inputs["Subsurface Weight"].default_value = 0.0

    bump = _bump(tree, veins.outputs["Fac"], 0.24, 0.004, loc=(0, -260))
    _link(tree, bump.outputs["Normal"], shader.inputs["Normal"])

    # Physical backlit sunlight translucency through thin leaves.
    trans_tint = _mix_rgb(
        tree,
        "MULTIPLY",
        1.0,
        tinted.outputs["Color"],
        (1.22, 1.32, 0.62, 1.0),
        loc=(260, -140),
    )
    trans = tree.nodes.new("ShaderNodeBsdfTranslucent")
    trans.location = (480, -140)
    _link(tree, trans_tint.outputs["Color"], trans.inputs["Color"])
    _link(tree, bump.outputs["Normal"], trans.inputs["Normal"])

    mix_shader = tree.nodes.new("ShaderNodeMixShader")
    mix_shader.location = (720, 80)
    mix_shader.inputs["Fac"].default_value = 0.26
    _link(tree, shader.outputs["BSDF"], mix_shader.inputs[1])
    _link(tree, trans.outputs["BSDF"], mix_shader.inputs[2])

    output = next(n for n in tree.nodes if n.type == "OUTPUT_MATERIAL")
    output.location = (940, 80)
    _link(tree, mix_shader.outputs["Shader"], output.inputs["Surface"])


def configure_realistic_terrain(material, shader, base_socket, *, bare=False):
    """Layer multi-scale turf, soil, and slope-driven cliff detail."""
    tree = material.node_tree
    geom = tree.nodes.new("ShaderNodeNewGeometry")
    geom.location = (-1250, -160)
    pos = geom.outputs["Position"]

    # Macro meadow patches, medium turf clumps, and fine soil grit.
    macro = _noise(
        tree, pos, 0.085, detail=6.0, roughness=0.62, loc=(-960, 220)
    )
    clump = _noise(tree, pos, 0.55, detail=7.0, roughness=0.68, loc=(-960, 0))
    grit = _noise(tree, pos, 7.5, detail=8.0, roughness=0.74, loc=(-960, -220))
    strata_vec = _vec_math(
        tree, "MULTIPLY", pos, (0.32, 0.32, 0.95), loc=(-960, -440)
    )
    rock_n = _noise(
        tree,
        strata_vec.outputs["Vector"],
        1.3,
        detail=8.0,
        roughness=0.72,
        noise_type="RIDGED_MULTIFRACTAL",
        loc=(-720, -440),
    )

    n_xyz = tree.nodes.new("ShaderNodeSeparateXYZ")
    n_xyz.location = (-960, -680)
    _link(tree, geom.outputs["Normal"], n_xyz.inputs["Vector"])

    # Slope transition: grass to loamy soil to fractured bedrock.
    slope_jit = _map_range(
        tree, clump.outputs["Fac"], 0.2, 0.8, -0.07, 0.07, loc=(-720, -680)
    )
    nz = _math(
        tree,
        "ADD",
        n_xyz.outputs["Z"],
        slope_jit.outputs["Result"],
        loc=(-500, -680),
    )
    dirt_slope = _map_range(
        tree,
        nz.outputs["Value"],
        0.74,
        0.90,
        0.65,
        0.0,
        interp="SMOOTHSTEP",
        loc=(-260, -580),
    )
    cliff_slope = _map_range(
        tree,
        nz.outputs["Value"],
        0.52,
        0.78,
        0.92,
        0.0,
        interp="SMOOTHSTEP",
        loc=(-260, -780),
    )

    # Macro dry-grass, clover, and loam variation over vertex color.
    tone = _map_range(
        tree, macro.outputs["Fac"], 0.24, 0.78, 0.52, 1.06, loc=(-640, 220)
    )
    clump_tone = _map_range(
        tree, clump.outputs["Fac"], 0.22, 0.80, 0.70, 1.15, loc=(-640, 0)
    )
    shade = _math(
        tree,
        "MULTIPLY",
        tone.outputs["Result"],
        clump_tone.outputs["Result"],
        loc=(-400, 140),
    )
    ground = _mix_rgb(
        tree,
        "MULTIPLY",
        1.0,
        base_socket,
        shade.outputs["Value"],
        loc=(-160, 200),
    )
    if not bare:
        # Organic dried-straw and moss patches break up uniform green.
        dry_mask = _map_range(
            tree,
            macro.outputs["Fac"],
            0.58,
            0.82,
            0.0,
            0.46,
            interp="SMOOTHSTEP",
            loc=(-160, 0),
        )
        ground = _mix_rgb(
            tree,
            "MIX",
            dry_mask.outputs["Result"],
            ground.outputs["Color"],
            (0.19, 0.165, 0.072, 1.0),
            loc=(60, 200),
        )
    # Blend loamy earth patches in hollows/slopes.
    loam_n = _map_range(
        tree,
        clump.outputs["Fac"],
        0.18,
        0.38,
        0.48 if not bare else 0.62,
        0.0,
        interp="SMOOTHSTEP",
        loc=(60, -40),
    )
    loam_fac = _math(
        tree,
        "MAXIMUM",
        dirt_slope.outputs["Result"],
        loam_n.outputs["Result"],
        clamp=True,
        loc=(260, -80),
    )
    with_soil = _mix_rgb(
        tree,
        "MIX",
        loam_fac.outputs["Value"],
        ground.outputs["Color"],
        (0.095, 0.072, 0.044, 1.0),
        loc=(440, 200),
    )
    # Stratified cliff bedrock on steep slopes.
    rock_tone = _map_range(
        tree, rock_n.outputs["Fac"], 0.15, 0.85, 0.09, 0.24, loc=(260, -420)
    )
    rock_col = _mix_rgb(
        tree,
        "MULTIPLY",
        1.0,
        (0.86, 0.83, 0.77, 1.0),
        rock_tone.outputs["Result"],
        loc=(440, -420),
    )
    final_col = _mix_rgb(
        tree,
        "MIX",
        cliff_slope.outputs["Result"],
        with_soil.outputs["Color"],
        rock_col.outputs["Color"],
        loc=(640, 200),
    )
    _link(tree, final_col.outputs["Color"], shader.inputs["Base Color"])

    # Two-stage ground relief: turf/soil grit and clod/cliff strata.
    macro_h = _mix_rgb(
        tree,
        "MIX",
        cliff_slope.outputs["Result"],
        clump.outputs["Fac"],
        rock_n.outputs["Fac"],
        loc=(240, -240),
    )
    b_fine = _bump(tree, grit.outputs["Fac"], 0.78, 0.022, loc=(440, -200))
    b_macro = _bump(
        tree,
        macro_h.outputs["Color"],
        0.82,
        0.055,
        normal=b_fine.outputs["Normal"],
        loc=(660, -200),
    )
    _link(tree, b_macro.outputs["Normal"], shader.inputs["Normal"])

    rough = _map_range(
        tree, grit.outputs["Fac"], 0.2, 0.82, 0.78, 0.96, loc=(660, -420)
    )
    _link(tree, rough.outputs["Result"], shader.inputs["Roughness"])
    if "Diffuse Roughness" in shader.inputs:
        shader.inputs["Diffuse Roughness"].default_value = 0.78
    if "Specular IOR Level" in shader.inputs:
        shader.inputs["Specular IOR Level"].default_value = 0.28


def configure_realistic_paving(material, shader, albedo_socket, normal_socket):
    """Weathered cobble roads with dusty joints, moss, and worn tops."""
    tree = material.node_tree
    geom = tree.nodes.new("ShaderNodeNewGeometry")
    geom.location = (-960, -260)
    pos = geom.outputs["Position"]

    macro = _noise(
        tree, pos, 0.45, detail=6.0, roughness=0.65, loc=(-720, -180)
    )
    grit = _noise(
        tree, pos, 18.0, detail=7.0, roughness=0.72, loc=(-720, -400)
    )

    # Height cue from Paving_Albedo brightness (dark = mortar joint).
    luma = tree.nodes.new("ShaderNodeRGBToBW")
    luma.location = (-480, 120)
    _link(tree, albedo_socket, luma.inputs["Color"])
    joint_mask = _map_range(
        tree, luma.outputs["Val"], 0.04, 0.14, 1.0, 0.0, loc=(-240, 120)
    )

    # Moss in damp mortar joints.
    moss_fac = _math(
        tree,
        "MULTIPLY",
        joint_mask.outputs["Result"],
        _map_range(
            tree, macro.outputs["Fac"], 0.52, 0.76, 0.0, 0.72, loc=(-240, -180)
        ).outputs["Result"],
        clamp=True,
        loc=(0, -60),
    )
    tone = _map_range(
        tree, macro.outputs["Fac"], 0.25, 0.78, 0.74, 1.14, loc=(-240, 320)
    )
    varied = _mix_rgb(
        tree,
        "MULTIPLY",
        1.0,
        albedo_socket,
        tone.outputs["Result"],
        loc=(20, 260),
    )
    mossy = _mix_rgb(
        tree,
        "MIX",
        moss_fac.outputs["Value"],
        varied.outputs["Color"],
        (0.055, 0.092, 0.032, 1.0),
        loc=(260, 260),
    )
    _link(tree, mossy.outputs["Color"], shader.inputs["Base Color"])

    # Combine tangent-space Paving_Normal with micro-stone grit bump.
    b_grit = _bump(
        tree,
        grit.outputs["Fac"],
        0.48,
        0.008,
        normal=normal_socket,
        loc=(260, -240),
    )
    _link(tree, b_grit.outputs["Normal"], shader.inputs["Normal"])

    # Worn cobble tops catch specular (~0.46), joints dusty (~0.94).
    stone_r = _map_range(
        tree, luma.outputs["Val"], 0.04, 0.22, 0.94, 0.46, loc=(260, -460)
    )
    _link(tree, stone_r.outputs["Result"], shader.inputs["Roughness"])
    if "Diffuse Roughness" in shader.inputs:
        shader.inputs["Diffuse Roughness"].default_value = 0.62


def configure_realistic_water(material, shader):
    """Physically reflective water with dual-octave wind ripples."""
    tree = material.node_tree
    shader.inputs["Metallic"].default_value = 0.0
    shader.inputs["Roughness"].default_value = 0.035
    shader.inputs["IOR"].default_value = 1.333
    if "Specular IOR Level" in shader.inputs:
        shader.inputs["Specular IOR Level"].default_value = 0.62
    if "Coat Weight" in shader.inputs:
        shader.inputs["Coat Weight"].default_value = 0.55
        shader.inputs["Coat Roughness"].default_value = 0.02

    geom = tree.nodes.new("ShaderNodeNewGeometry")
    geom.location = (-960, -220)
    pos = geom.outputs["Position"]

    swell = _noise(
        tree,
        _vec_math(
            tree, "MULTIPLY", pos, (1.4, 0.75, 1.0), loc=(-720, -120)
        ).outputs["Vector"],
        2.4,
        detail=5.0,
        roughness=0.55,
        loc=(-480, -120),
    )
    ripple = _noise(
        tree, pos, 11.5, detail=6.0, roughness=0.62, loc=(-480, -340)
    )
    b1 = _bump(tree, ripple.outputs["Fac"], 0.14, 0.006, loc=(-220, -260))
    b2 = _bump(
        tree,
        swell.outputs["Fac"],
        0.24,
        0.018,
        normal=b1.outputs["Normal"],
        loc=(20, -260),
    )
    _link(tree, b2.outputs["Normal"], shader.inputs["Normal"])


def configure_realistic_grass(material, shader, color_socket):
    """Grounded, backlit realistic meadow grass without cartoon glow."""
    tree = material.node_tree
    uv = tree.nodes.new("ShaderNodeTexCoord")
    uv.location = (-860, 120)
    uv_xyz = tree.nodes.new("ShaderNodeSeparateXYZ")
    uv_xyz.location = (-640, 120)
    _link(tree, uv.outputs["UV"], uv_xyz.inputs["Vector"])

    # Darken roots so blades sit grounded in turf without floating.
    root_ao = _map_range(
        tree,
        uv_xyz.outputs["Y"],
        0.0,
        0.42,
        0.44,
        1.06,
        interp="SMOOTHSTEP",
        loc=(-400, 140),
    )
    grounded = _mix_rgb(
        tree,
        "MULTIPLY",
        1.0,
        color_socket,
        root_ao.outputs["Result"],
        loc=(-140, 200),
    )
    _link(tree, grounded.outputs["Color"], shader.inputs["Base Color"])

    shader.inputs["Roughness"].default_value = 0.44
    shader.inputs["Emission Strength"].default_value = 0.0
    if "Specular IOR Level" in shader.inputs:
        shader.inputs["Specular IOR Level"].default_value = 0.44
    if "Subsurface Weight" in shader.inputs:
        shader.inputs["Subsurface Weight"].default_value = 0.0

    # Natural backlit translucency for sunlit meadow shimmer.
    trans_col = _mix_rgb(
        tree,
        "MULTIPLY",
        1.0,
        grounded.outputs["Color"],
        (1.18, 1.28, 0.64, 1.0),
        loc=(100, -100),
    )
    trans = tree.nodes.new("ShaderNodeBsdfTranslucent")
    trans.location = (320, -100)
    _link(tree, trans_col.outputs["Color"], trans.inputs["Color"])

    foliage = tree.nodes.new("ShaderNodeMixShader")
    foliage.location = (540, 80)
    foliage.inputs["Fac"].default_value = 0.30
    _link(tree, shader.outputs["BSDF"], foliage.inputs[1])
    _link(tree, trans.outputs["BSDF"], foliage.inputs[2])

    # Partial shadow transmission casts soft dappled grass shadows.
    light_path = tree.nodes.new("ShaderNodeLightPath")
    light_path.location = (320, 320)
    shadow_weight = _math(
        tree,
        "MULTIPLY",
        light_path.outputs["Is Shadow Ray"],
        0.72,
        loc=(540, 300),
    )
    shadow_tr = tree.nodes.new("ShaderNodeBsdfTransparent")
    shadow_tr.location = (540, -100)
    shadow_tr.inputs["Color"].default_value = (0.86, 0.92, 0.80, 1.0)
    final_mix = tree.nodes.new("ShaderNodeMixShader")
    final_mix.location = (760, 120)
    _link(tree, shadow_weight.outputs["Value"], final_mix.inputs["Fac"])
    _link(tree, foliage.outputs["Shader"], final_mix.inputs[1])
    _link(tree, shadow_tr.outputs["BSDF"], final_mix.inputs[2])

    output = next(n for n in tree.nodes if n.type == "OUTPUT_MATERIAL")
    output.location = (980, 120)
    _link(tree, final_mix.outputs["Shader"], output.inputs["Surface"])


def configure_realistic_preview_ground(material, shader):
    """Weathered earth, mossy turf, and gravel ground for previews."""
    tree = material.node_tree
    geom = tree.nodes.new("ShaderNodeNewGeometry")
    geom.location = (-1100, 0)
    pos = geom.outputs["Position"]

    macro = _noise(
        tree, pos, 0.28, detail=6.0, roughness=0.62, loc=(-820, 220)
    )
    medium = _noise(tree, pos, 1.6, detail=7.0, roughness=0.68, loc=(-820, 0))
    gravel = _voronoi(tree, pos, 26.0, feature="F1", loc=(-820, -240))
    grit = _noise(
        tree, pos, 32.0, detail=7.0, roughness=0.72, loc=(-820, -440)
    )

    # Radial worn-earth apron around house fading into mossy turf.
    dist = _vec_math(tree, "LENGTH", pos, loc=(-820, 440))
    apron = _map_range(
        tree,
        _math(
            tree,
            "ADD",
            dist.outputs["Value"],
            _map_range(
                tree,
                macro.outputs["Fac"],
                0.2,
                0.8,
                -1.8,
                1.8,
                loc=(-580, 300),
            ).outputs["Result"],
            loc=(-360, 400),
        ).outputs["Value"],
        4.2,
        7.8,
        0.0,
        1.0,
        interp="SMOOTHSTEP",
        loc=(-140, 400),
    )

    earth_tone = _map_range(
        tree, medium.outputs["Fac"], 0.22, 0.80, 0.0, 1.0, loc=(-500, 80)
    )
    earth = _mix_rgb(
        tree,
        "MIX",
        earth_tone.outputs["Result"],
        (0.105, 0.092, 0.072, 1.0),
        (0.185, 0.162, 0.128, 1.0),
        loc=(-220, 120),
    )
    turf = _mix_rgb(
        tree,
        "MIX",
        earth_tone.outputs["Result"],
        (0.088, 0.122, 0.056, 1.0),
        (0.155, 0.185, 0.088, 1.0),
        loc=(-220, -80),
    )
    ground_col = _mix_rgb(
        tree,
        "MIX",
        apron.outputs["Result"],
        earth.outputs["Color"],
        turf.outputs["Color"],
        loc=(80, 180),
    )

    ao = _ao_node(tree, distance=0.85, samples=8, loc=(-140, -300))
    ao_shade = _map_range(
        tree, ao.outputs["AO"], 0.2, 0.95, 0.42, 1.0, loc=(100, -300)
    )
    final_col = _mix_rgb(
        tree,
        "MULTIPLY",
        1.0,
        ground_col.outputs["Color"],
        ao_shade.outputs["Result"],
        loc=(340, 180),
    )
    _link(tree, final_col.outputs["Color"], shader.inputs["Base Color"])

    b_pebble = _bump(
        tree, gravel.outputs["Distance"], 0.45, 0.010, loc=(120, -520)
    )
    b_macro = _bump(
        tree,
        medium.outputs["Fac"],
        0.55,
        0.025,
        normal=b_pebble.outputs["Normal"],
        loc=(360, -520),
    )
    _link(tree, b_macro.outputs["Normal"], shader.inputs["Normal"])

    rough = _map_range(
        tree, grit.outputs["Fac"], 0.2, 0.8, 0.80, 0.96, loc=(360, -720)
    )
    _link(tree, rough.outputs["Result"], shader.inputs["Roughness"])
    if "Diffuse Roughness" in shader.inputs:
        shader.inputs["Diffuse Roughness"].default_value = 0.75


def configure_realistic_sky(
    world,
    *,
    sun_elevation=22.0,
    sun_rotation=232.0,
    sun_disc=True,
    sun_intensity=1.0,
    strength=None,
    air_density=1.30,
    aerosol_density=1.45,
    ozone_density=1.55,
):
    """Configure a physical multiple-scattering sky for Cycles."""
    world.use_nodes = True
    tree = world.node_tree
    tree.nodes.clear()
    sky = tree.nodes.new("ShaderNodeTexSky")
    sky.location = (-360, 120)
    sky.sky_type = "MULTIPLE_SCATTERING"
    sky.sun_disc = sun_disc
    sky.sun_size = math.radians(0.68)
    sky.sun_intensity = sun_intensity
    sky.sun_elevation = math.radians(sun_elevation)
    sky.sun_rotation = math.radians(sun_rotation)
    sky.air_density = air_density
    sky.aerosol_density = aerosol_density
    sky.ozone_density = ozone_density
    sky.ground_albedo = 0.24

    bg = tree.nodes.new("ShaderNodeBackground")
    bg.location = (-80, 120)
    if strength is None:
        strength = 0.085 if sun_disc else 0.14
    bg.inputs["Strength"].default_value = strength
    output = tree.nodes.new("ShaderNodeOutputWorld")
    output.location = (180, 120)
    _link(tree, sky.outputs["Color"], bg.inputs["Color"])
    _link(tree, bg.outputs["Background"], output.inputs["Surface"])
    return sky, bg


def configure_realistic_cycles(scene, *, samples=64, exposure=0.0):
    """Set Cycles bounces, adaptive sampling, and AgX look."""
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = 0.015
    scene.cycles.use_denoising = True
    if hasattr(scene.cycles, "denoising_input_passes"):
        scene.cycles.denoising_input_passes = "RGB_ALBEDO_NORMAL"
    scene.cycles.max_bounces = 8
    scene.cycles.diffuse_bounces = 4
    scene.cycles.glossy_bounces = 4
    scene.cycles.transmission_bounces = 6
    scene.cycles.transparent_max_bounces = 8
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = exposure
    scene.view_settings.gamma = 1.0
