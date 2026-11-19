"""EEVEE material outputs for the atlas and legacy world previews."""

import bpy

from house_generator import _linear_color

SHADE = (0.50, 0.60, 0.76, 1)
HALFTONE = (0.78, 0.82, 0.84, 1)
SUN = (1.0, 0.97, 0.86, 1)


def _lighting(foliage):
    label = (
        "World Toon · Foliage" if foliage else "World Toon · Stone and Wood"
    )
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
            (0.27, SHADE),
            (0.33, HALFTONE),
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
    out.inputs[2].default_value = _linear_color("fff0d5")
    emission = tree.nodes.new("ShaderNodeEmission")
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
        output = tree.nodes.new("ShaderNodeOutputMaterial")
        output.name = "Toon Output"
        output.target = "EEVEE"
        layer = tree.nodes.new("ShaderNodeGroup")
        layer.node_tree = _lighting(
            bool(
                material.get("foliage_bend_uv")
                or "leaves" in material.name.lower()
            )
        )
        base = shader.inputs["Base Color"]
        layer.inputs["Albedo"].default_value = base.default_value
        if base.is_linked:
            tree.links.new(base.links[0].from_socket, layer.inputs["Albedo"])
        tree.links.new(layer.outputs[0], output.inputs["Surface"])
