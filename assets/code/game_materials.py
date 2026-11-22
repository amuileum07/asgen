"""Portable baked paving maps and vertex-painted ground materials."""

import math
import random

import bpy

SHARED_IMAGE = "procedural_game_surface"


def meadow_images(size=256):
    names = ("Meadow_Albedo", "Bare_Ground_Albedo")
    existing = tuple(bpy.data.images.get(name) for name in names)
    if all(existing):
        return existing
    rng = random.Random(1733)
    cells = 13
    pattern = [rng.uniform(-0.041, 0.041) for _ in range(cells * cells)]

    def grain(x, y):
        x, y = x * cells / size, y * cells / size
        i, j = math.floor(x), math.floor(y)
        u, v = x - i, y - j
        u, v = u * u * (3 - 2 * u), v * v * (3 - 2 * v)
        left, right = i, (i + 1) % cells
        lower, upper = j * cells, ((j + 1) % cells) * cells
        return (
            pattern[lower + left] * (1 - u) + pattern[lower + right] * u
        ) * (1 - v) + (
            pattern[upper + left] * (1 - u) + pattern[upper + right] * u
        ) * v

    values = [
        0.945 + grain(x, y) + rng.uniform(-0.021, 0.021)
        for y in range(size)
        for x in range(size)
    ]
    for _ in range(size * 13):
        x, y = rng.randrange(size), rng.randrange(size)
        height, bend = rng.randint(3, 10), rng.uniform(-0.55, 0.55)
        light = rng.uniform(-0.23, 0.12)
        for i in range(height):
            column = (x + round(i * bend)) % size
            row = (y + i) % size
            index = row * size + column
            values[index] += light * (1 - i / height)

    def tone(value):
        return value * 0.985, value, value * 0.967, 1

    values = [min(1.0, max(0.54, value)) for value in values]
    meadow = [channel for value in values for channel in tone(value)]
    bare = list(tone(math.fsum(values) / len(values))) * 16
    result = []
    for name, image, edge, pixels in zip(
        names, existing, (size, 4), (meadow, bare), strict=True
    ):
        if image is None:
            image = bpy.data.images.new(
                name, width=edge, height=edge, alpha=False
            )
            image[SHARED_IMAGE] = True
            image.colorspace_settings.name = "sRGB"
            image.pixels.foreach_set(pixels)
            image.file_format = "PNG"
            image.pack()
        result.append(image)
    return tuple(result)


def paving_images(size=256):
    names = ("Paving_Albedo", "Paving_Normal")
    existing = [bpy.data.images.get(name) for name in names]
    if all(existing):
        return tuple(existing)
    heights, albedo = [], []
    for j in range(size):
        for i in range(size):
            u, v = i / size * 4, j / size * 4
            row = math.floor(v)
            u += (row % 2) * 0.5
            column = math.floor(u)
            x, y = u - column, v - row
            edge = min(x, 1 - x, y, 1 - y)
            t = min(1, max(0, (edge - 0.035) / 0.11))
            t = t * t * (3 - 2 * t)
            tone = ((column % 4) * 17 + (row % 4) * 31) % 13 / 13
            grain = math.sin(i * 0.83 + j * 1.31) * 0.007
            stone = 0.27 + tone * 0.09 + grain
            shade = 0.13 * (1 - t) + stone * t
            albedo.extend((shade * 1.08, shade, shade * 0.84, 1))
            heights.append(t * 0.028)
    normal = []
    for j in range(size):
        for i in range(size):
            dx = (
                (
                    heights[j * size + (i + 1) % size]
                    - heights[j * size + (i - 1) % size]
                )
                * size
                / 4
            )
            dy = (
                (
                    heights[((j + 1) % size) * size + i]
                    - heights[((j - 1) % size) * size + i]
                )
                * size
                / 4
            )
            length = math.sqrt(dx * dx + dy * dy + 1)
            normal.extend(
                (
                    -dx / length * 0.5 + 0.5,
                    -dy / length * 0.5 + 0.5,
                    0.5 / length + 0.5,
                    1,
                )
            )
    images = []
    for name, pixels, space in zip(
        names, (albedo, normal), ("sRGB", "Non-Color"), strict=True
    ):
        old = bpy.data.images.get(name)
        if old and old.users == 0:
            bpy.data.images.remove(old)
        image = bpy.data.images.new(name, width=size, height=size, alpha=False)
        image[SHARED_IMAGE] = True
        image.colorspace_settings.name = space
        image.pixels.foreach_set(pixels)
        image.file_format = "PNG"
        image.pack()
        images.append(image)
    return tuple(images)


def _architecture_surface(kind, realistic):
    prefix = "Asgen PBR" if realistic else "Asgen Painted"
    name = f"{prefix} {kind.title()} Surface"
    if group := bpy.data.node_groups.get(name):
        return group
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    for socket, direction, socket_type in (
        ("Tint", "INPUT", "NodeSocketColor"),
        ("Color", "OUTPUT", "NodeSocketColor"),
        ("Normal", "OUTPUT", "NodeSocketVector"),
    ):
        group.interface.new_socket(
            name=socket, in_out=direction, socket_type=socket_type
        )

    nodes, links = group.nodes, group.links
    tint = nodes.new("NodeGroupInput")
    tint.location = (20, 240)
    output = nodes.new("NodeGroupOutput")
    output.location = (620, 40)
    coords = nodes.new("ShaderNodeTexCoord")
    coords.location = (-850, 30)
    vector = coords.outputs["Object"]
    if kind == "timber":
        grain = nodes.new("ShaderNodeVectorMath")
        grain.operation = "MULTIPLY"
        grain.inputs[1].default_value = (3.0, 42.0, 1.0)
        grain.location = (-640, 40)
        links.new(coords.outputs["UV"], grain.inputs[0])
        vector = grain.outputs["Vector"]

    scale, minimum, maximum, grain_scale, depth = {
        "plaster": (1.8, 0.81, 1.08, 58.0, 0.003),
        "timber": (1.0, 0.67, 1.16, 1.0, 0.004),
        "clay": (3.5, 0.68, 1.14, 37.0, 0.004),
        "stone": (2.2, 0.73, 1.12, 26.0, 0.006),
    }[kind]
    pattern = nodes.new("ShaderNodeTexNoise")
    pattern.location = (-440, 40)
    pattern.inputs["Scale"].default_value = scale
    pattern.inputs["Detail"].default_value = 3.0
    links.new(vector, pattern.inputs["Vector"])
    variation = nodes.new("ShaderNodeMapRange")
    variation.location = (-225, 40)
    for socket, value in (
        ("From Min", 0.25),
        ("From Max", 0.75),
        ("To Min", minimum),
        ("To Max", maximum),
    ):
        variation.inputs[socket].default_value = value
    links.new(pattern.outputs["Fac"], variation.inputs["Value"])
    shade = variation.outputs["Result"]

    if kind == "plaster":
        height = nodes.new("ShaderNodeSeparateXYZ")
        height.location = (-640, -330)
        links.new(coords.outputs["Generated"], height.inputs["Vector"])
        foot = nodes.new("ShaderNodeMapRange")
        foot.location = (-440, -330)
        foot.interpolation_type = "SMOOTHSTEP"
        foot.inputs["From Max"].default_value = 0.23
        foot.inputs["To Min"].default_value = 0.64
        links.new(height.outputs["Z"], foot.inputs["Value"])
        weathering = nodes.new("ShaderNodeMath")
        weathering.operation = "MULTIPLY"
        weathering.location = (20, 40)
        links.new(shade, weathering.inputs[0])
        links.new(foot.outputs["Result"], weathering.inputs[1])
        shade = weathering.outputs[0]

    color = nodes.new("ShaderNodeMixRGB")
    color.blend_type = "MULTIPLY"
    color.inputs[0].default_value = 1.0 if realistic else 0.28
    color.location = (390, 180)
    links.new(tint.outputs["Tint"], color.inputs[1])
    links.new(shade, color.inputs[2])
    links.new(color.outputs[0], output.inputs["Color"])

    detail = pattern
    if kind != "timber":
        detail = nodes.new("ShaderNodeTexNoise")
        detail.location = (-210, -295 if kind != "plaster" else -630)
        detail.inputs["Scale"].default_value = grain_scale
        detail.inputs["Detail"].default_value = 2.0
        links.new(vector, detail.inputs["Vector"])
    bump = nodes.new("ShaderNodeBump")
    bump.location = (390, -80)
    bump.inputs["Distance"].default_value = depth
    links.new(detail.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], output.inputs["Normal"])
    if realistic:
        group.interface.new_socket(
            name="Roughness", in_out="OUTPUT", socket_type="NodeSocketFloat"
        )
        roughness = nodes.new("ShaderNodeMapRange")
        roughness.location = (390, -310)
        low, high = {
            "timber": (0.36, 0.78),
            "clay": (0.50, 0.87),
            "plaster": (0.74, 0.97),
            "stone": (0.59, 0.94),
        }[kind]
        roughness.inputs["To Min"].default_value = low
        roughness.inputs["To Max"].default_value = high
        links.new(detail.outputs["Fac"], roughness.inputs["Value"])
        links.new(roughness.outputs["Result"], output.inputs["Roughness"])
    return group


def configure_architecture_surface(material, shader, kind, *, realistic=False):
    tree = material.node_tree
    surface = tree.nodes.new("ShaderNodeGroup")
    surface.name = "Architecture Surface"
    surface.label = f"{kind.title()} · Colour and Relief"
    surface.location = (shader.location.x - 240, shader.location.y)
    surface.node_tree = _architecture_surface(kind, realistic)
    surface.inputs["Tint"].default_value = material.diffuse_color
    if kind == "timber":
        material["grain_aligned_uv"] = True
    shader.inputs["Roughness"].default_value = {
        "plaster": 0.89,
        "timber": 0.68,
        "clay": 0.81,
        "stone": 0.86,
    }[kind]
    tree.links.new(surface.outputs["Color"], shader.inputs["Base Color"])
    tree.links.new(surface.outputs["Normal"], shader.inputs["Normal"])
    if realistic:
        tree.links.new(
            surface.outputs["Roughness"], shader.inputs["Roughness"]
        )


def configure_surface_materials(materials, shader_for):
    if bark := materials.get("bark"):
        shader = shader_for(bark)
        tree = bark.node_tree
        coords = tree.nodes.new("ShaderNodeTexCoord")
        scale = tree.nodes.new("ShaderNodeVectorMath")
        scale.operation = "MULTIPLY"
        scale.inputs[1].default_value = (29.0, 29.0, 3.2)
        furrows = tree.nodes.new("ShaderNodeTexNoise")
        furrows.inputs["Scale"].default_value = 1.0
        furrows.inputs["Detail"].default_value = 2.8
        tint = tree.nodes.new("ShaderNodeValToRGB")
        tint.color_ramp.elements[0].color = (0.042, 0.028, 0.018, 1)
        tint.color_ramp.elements[1].color = (0.25, 0.19, 0.13, 1)
        bump = tree.nodes.new("ShaderNodeBump")
        bump.inputs["Distance"].default_value = 0.014
        for source, target in (
            (coords.outputs["Object"], scale.inputs[0]),
            (scale.outputs[0], furrows.inputs["Vector"]),
            (furrows.outputs["Fac"], tint.inputs[0]),
            (tint.outputs[0], shader.inputs["Base Color"]),
            (furrows.outputs["Fac"], bump.inputs["Height"]),
            (bump.outputs[0], shader.inputs["Normal"]),
        ):
            tree.links.new(source, target)
    meadow, bare = meadow_images()
    for key in ("terrain", "bare_terrain", "world_water"):
        material = materials[key]
        shader = shader_for(material)
        tree = material.node_tree
        color = tree.nodes.new("ShaderNodeVertexColor")
        color.layer_name = "Color"
        output = color.outputs["Color"]
        if key != "world_water":
            tex = tree.nodes.new("ShaderNodeTexImage")
            tex.image = meadow if key == "terrain" else bare
            mix = tree.nodes.new("ShaderNodeMixRGB")
            mix.blend_type, mix.inputs[0].default_value = "MULTIPLY", 1
            tree.links.new(output, mix.inputs[1])
            tree.links.new(tex.outputs["Color"], mix.inputs[2])
            output = mix.outputs["Color"]
            material["albedo_texture"] = tex.image.name
        tree.links.new(output, shader.inputs["Base Color"])
        material["uses_vertex_color"] = True
    albedo, normal = paving_images()
    for key in ("road_surface", "plaza_surface"):
        material = materials[key]
        tree = material.node_tree
        shader = shader_for(material)
        texture = tree.nodes.new("ShaderNodeTexImage")
        texture.image = albedo
        tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
        ntex = tree.nodes.new("ShaderNodeTexImage")
        ntex.image = normal
        mapping = tree.nodes.new("ShaderNodeNormalMap")
        mapping.inputs["Strength"].default_value = 0.45
        tree.links.new(ntex.outputs["Color"], mapping.inputs["Color"])
        tree.links.new(mapping.outputs["Normal"], shader.inputs["Normal"])
        material["albedo_texture"] = albedo.name
        material["normal_texture"] = normal.name
    if "grass_tuft" in materials:
        grass = materials["grass_tuft"]
        tree = grass.node_tree
        shader = shader_for(grass)
        color = tree.nodes.new("ShaderNodeVertexColor")
        color.layer_name = "Color"
        tree.links.new(color.outputs["Color"], shader.inputs["Base Color"])
        shader.inputs["Roughness"].default_value = 0.72
        uv = tree.nodes.new("ShaderNodeTexCoord")
        height = tree.nodes.new("ShaderNodeSeparateXYZ")
        transmission = tree.nodes.new("ShaderNodeMapRange")
        transmission.inputs["To Min"].default_value = 0.12
        transmission.inputs["To Max"].default_value = 0.47
        tree.links.new(uv.outputs["UV"], height.inputs["Vector"])
        tree.links.new(height.outputs["Y"], transmission.inputs["Value"])
        tree.links.new(color.outputs["Color"], shader.inputs["Emission Color"])
        tree.links.new(
            transmission.outputs["Result"], shader.inputs["Emission Strength"]
        )
        if "Specular IOR Level" in shader.inputs:
            shader.inputs["Specular IOR Level"].default_value = 0.14
        if "Subsurface Weight" in shader.inputs:
            shader.inputs["Subsurface Weight"].default_value = 0.0

        # Add downward-normal translucency so blade backs catch sky
        # light in Cycles without dark shadow-terminator artifacts.
        down_vec = tree.nodes.new("ShaderNodeCombineXYZ")
        down_vec.inputs["X"].default_value = 0.0
        down_vec.inputs["Y"].default_value = 0.0
        down_vec.inputs["Z"].default_value = -1.0

        trans = tree.nodes.new("ShaderNodeBsdfTranslucent")
        tree.links.new(color.outputs["Color"], trans.inputs["Color"])
        tree.links.new(down_vec.outputs["Vector"], trans.inputs["Normal"])

        foliage = tree.nodes.new("ShaderNodeMixShader")
        foliage.inputs["Fac"].default_value = 0.44
        tree.links.new(shader.outputs["BSDF"], foliage.inputs[1])
        tree.links.new(trans.outputs["BSDF"], foliage.inputs[2])

        light_path = tree.nodes.new("ShaderNodeLightPath")
        shadow_tr = tree.nodes.new("ShaderNodeBsdfTransparent")
        shadow_tr.inputs["Color"].default_value = (0.94, 0.97, 0.91, 1.0)
        final_mix = tree.nodes.new("ShaderNodeMixShader")
        tree.links.new(
            light_path.outputs["Is Shadow Ray"], final_mix.inputs["Fac"]
        )
        tree.links.new(foliage.outputs["Shader"], final_mix.inputs[1])
        tree.links.new(shadow_tr.outputs["BSDF"], final_mix.inputs[2])

        output = next(n for n in tree.nodes if n.type == "OUTPUT_MATERIAL")
        tree.links.new(final_mix.outputs["Shader"], output.inputs["Surface"])
        grass["uses_vertex_color"] = True
        grass["foliage_bend_uv"] = "V"
        grass.use_backface_culling = False


def purge_unused_images():
    for image in list(bpy.data.images):
        if image.get(SHARED_IMAGE) and image.users == 0:
            bpy.data.images.remove(image)
