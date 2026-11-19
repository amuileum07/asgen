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


def configure_surface_materials(materials, shader_for):
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
