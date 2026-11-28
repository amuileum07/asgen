"""Cel lighting and painted or transmissive window glass."""

import bpy

from realistic_materials import configure_realistic_glass

SHADE = (0.32, 0.40, 0.57, 1)
HALFTONE = (0.70, 0.74, 0.80, 1)
SUN = (1.18, 1.07, 0.93, 1)


def _lighting(foliage):
    label = "Asgen Cel · Foliage" if foliage else "Asgen Cel · Architecture"
    if existing := bpy.data.node_groups.get(label):
        return existing
    tree = bpy.data.node_groups.new(label, "ShaderNodeTree")
    tree.interface.new_socket(
        name="Albedo", in_out="INPUT", socket_type="NodeSocketColor"
    )
    tree.interface.new_socket(
        name="Surface", in_out="OUTPUT", socket_type="NodeSocketShader"
    )
    inputs, outputs = (
        tree.nodes.new("NodeGroupInput"),
        tree.nodes.new("NodeGroupOutput"),
    )
    diffuse = tree.nodes.new("ShaderNodeBsdfDiffuse")
    diffuse.inputs["Color"].default_value = (1, 1, 1, 1)
    direct = tree.nodes.new("ShaderNodeShaderToRGB")
    luminance = tree.nodes.new("ShaderNodeRGBToBW")
    scale = tree.nodes.new("ShaderNodeMapRange")
    scale.inputs["From Max"].default_value = 0.88
    ramp = tree.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "EASE"
    stops = (
        ((0.35, SHADE), (0.48, HALFTONE))
        if foliage
        else (
            (0.51, SHADE),
            (0.60, HALFTONE),
            (0.67, HALFTONE),
            (0.73, SUN),
        )
    )
    ends = ramp.color_ramp.elements
    ends[0].position, ends[0].color = stops[0]
    ends[-1].position, ends[-1].color = stops[-1]
    for pos, colour in stops[1:-1]:
        ends.new(pos).color = colour
    colour = tree.nodes.new("ShaderNodeMixRGB")
    colour.blend_type = "MULTIPLY"
    colour.inputs[0].default_value = 1
    rim = tree.nodes.new("ShaderNodeFresnel")
    rim.inputs["IOR"].default_value = 1.18
    intensity = tree.nodes.new("ShaderNodeMath")
    intensity.operation = "MULTIPLY"
    intensity.inputs[1].default_value = 0.065 if not foliage else 0.025
    lightgate = tree.nodes.new("ShaderNodeMath")
    lightgate.operation = "MULTIPLY"
    out = tree.nodes.new("ShaderNodeMixRGB")
    out.blend_type = "ADD"
    out.inputs[2].default_value = (1.0, 0.87, 0.67, 1.0)
    emission = tree.nodes.new("ShaderNodeEmission")
    for node, position in (
        (diffuse, (-1060, 0)),
        (direct, (-870, 0)),
        (luminance, (-680, 0)),
        (scale, (-490, 0)),
        (ramp, (-270, 80)),
        (inputs, (-220, 270)),
        (colour, (40, 180)),
        (rim, (-490, -320)),
        (intensity, (-270, -320)),
        (lightgate, (40, -150)),
        (out, (250, 180)),
        (emission, (450, 180)),
        (outputs, (650, 180)),
    ):
        node.location = position
    for source, target in (
        (diffuse.outputs[0], direct.inputs[0]),
        (direct.outputs[0], luminance.inputs[0]),
        (luminance.outputs[0], scale.inputs["Value"]),
        (scale.outputs["Result"], ramp.inputs[0]),
        (inputs.outputs["Albedo"], colour.inputs[1]),
        (ramp.outputs[0], colour.inputs[2]),
        (rim.outputs[0], intensity.inputs[0]),
        (intensity.outputs[0], lightgate.inputs[0]),
        (scale.outputs["Result"], lightgate.inputs[1]),
        (lightgate.outputs[0], out.inputs[0]),
        (colour.outputs[0], out.inputs[1]),
        (out.outputs[0], emission.inputs[0]),
        (emission.outputs[0], outputs.inputs["Surface"]),
    ):
        tree.links.new(source, target)
    return tree


def _glass(material, shader, art_style):
    if art_style == "REALISTIC":
        configure_realistic_glass(material, shader)
        return
    tree = material.node_tree
    coords = tree.nodes.new("ShaderNodeTexCoord")
    diagonal = tree.nodes.new("ShaderNodeVectorMath")
    diagonal.operation = "DOT_PRODUCT"
    diagonal.inputs[1].default_value = (0.84, -0.52, 0.0)
    repeat = tree.nodes.new("ShaderNodeMath")
    repeat.operation = "FRACT"
    paint = tree.nodes.new("ShaderNodeValToRGB")
    paint.label = "Sky reflection"
    for node, offset in (
        (coords, -860),
        (diagonal, -660),
        (repeat, -460),
        (paint, -280),
    ):
        node.location = (shader.location.x + offset, shader.location.y)
    ramp = paint.color_ramp
    ramp.interpolation = "CONSTANT"
    base = tuple(material.diffuse_color)
    ramp.elements[0].color = base
    ramp.elements[1].color = base
    sky = (0.28, 0.56, 0.63, 1.0)
    for position, colour in (
        (0.38, sky),
        (0.50, base),
        (0.53, sky),
        (0.56, base),
    ):
        ramp.elements.new(position).color = colour
    for source, target in (
        (coords.outputs["UV"], diagonal.inputs[0]),
        (diagonal.outputs["Value"], repeat.inputs[0]),
        (repeat.outputs[0], paint.inputs[0]),
        (paint.outputs[0], shader.inputs["Base Color"]),
    ):
        tree.links.new(source, target)


def style_material(material, shader, key, art_style):
    if key == "glass":
        _glass(material, shader, art_style)
    elif art_style == "CARTOON" and key not in (
        "water",
        "well_water",
        "world_water",
        "fire",
        "lantern_glow",
        "metal",
        "iron",
        "label",
    ):
        foliage = key.startswith(("leaves", "grass_"))
        _cel_outputs(material, shader, foliage)


def _cel_outputs(material, shader, foliage):
    tree = material.node_tree
    if tree.nodes.get("Toon Output"):
        return
    layer = tree.nodes.new("ShaderNodeGroup")
    layer.node_tree = _lighting(foliage)
    layer.location = (shader.location.x, shader.location.y - 370)
    cycles = tree.nodes.new("ShaderNodeBsdfToon")
    cycles.location = (layer.location.x, layer.location.y - 160)
    cycles.inputs["Size"].default_value = 0.68
    cycles.inputs["Smooth"].default_value = 0.12
    base = shader.inputs["Base Color"]
    for socket in (layer.inputs["Albedo"], cycles.inputs["Color"]):
        socket.default_value = base.default_value
        if base.is_linked:
            tree.links.new(base.links[0].from_socket, socket)
    for engine, node, name in (
        ("EEVEE", layer, "Toon Output"),
        ("CYCLES", cycles, "Cycles Toon Output"),
    ):
        output = tree.nodes.new("ShaderNodeOutputMaterial")
        output.name = name
        output.target = engine
        output.is_active_output = True
        output.location = (node.location.x + 230, node.location.y)
        tree.links.new(node.outputs[0], output.inputs["Surface"])


def install_toon(collection):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.view_settings.view_transform = "AgX"
    materials = {
        slot.material
        for obj in collection.all_objects
        if obj.type == "MESH"
        for slot in obj.material_slots
        if slot.material
    }
    for material in materials:
        if not material.use_nodes or any(
            x in material.name.lower()
            for x in ("water", "glass", "glow", "fire")
        ):
            continue
        tree = material.node_tree
        if tree.nodes.get("Toon Output"):
            continue
        shader = next(
            (node for node in tree.nodes if node.type == "BSDF_PRINCIPLED"),
            None,
        )
        if shader is None:
            continue
        _cel_outputs(
            material,
            shader,
            bool(
                material.get("foliage_bend_uv")
                or "leaves" in material.name.lower()
            ),
        )
