"""Engine-neutral buffers, OGRE XML and dotScene output."""

import io
import math
import struct
import xml.etree.ElementTree as ET
from array import array
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"PGEO\x01\x00\x00\x00"
COLLISION_MAGIC = b"PCOL\x01\x00\x00\x00"
VERTEX_FLOATS = 12


@dataclass(frozen=True)
class MeshSection:
    material: str
    vertices: tuple
    indices: tuple


def encode_mesh(sections):
    data = io.BytesIO()
    data.write(MAGIC)
    data.write(struct.pack("<I", len(sections)))
    for section in sections:
        name = section.material.encode("utf-8")
        data.write(struct.pack("<H", len(name)))
        data.write(name)
        data.write(
            struct.pack("<II", len(section.vertices), len(section.indices))
        )
        for vertex in section.vertices:
            if len(vertex) != VERTEX_FLOATS or not all(
                math.isfinite(v) for v in vertex
            ):
                raise ValueError("Invalid game vertex")
            data.write(struct.pack("<12f", *vertex))
        if any(i < 0 or i >= len(section.vertices) for i in section.indices):
            raise ValueError("Index outside vertex buffer")
        data.write(struct.pack(f"<{len(section.indices)}I", *section.indices))
    return data.getvalue()


def decode_mesh(data):
    stream = io.BytesIO(data)
    if stream.read(8) != MAGIC:
        raise ValueError("Unsupported geometry version")
    (count,) = struct.unpack("<I", stream.read(4))
    result = []
    for _ in range(count):
        (length,) = struct.unpack("<H", stream.read(2))
        name = stream.read(length).decode("utf-8")
        nv, ni = struct.unpack("<II", stream.read(8))
        if nv > 20_000_000 or ni > 100_000_000 or ni % 3:
            raise ValueError("Invalid geometry counts")
        vertices = tuple(
            struct.unpack("<12f", stream.read(48)) for _ in range(nv)
        )
        indices = struct.unpack(f"<{ni}I", stream.read(ni * 4))
        if any(i >= nv for i in indices):
            raise ValueError("Invalid game index")
        result.append(MeshSection(name, vertices, indices))
    if stream.read(1):
        raise ValueError("Trailing geometry data")
    return tuple(result)


def write_mesh_xml(path, sections):
    root = ET.Element("mesh")
    submeshes = ET.SubElement(root, "submeshes")
    for section in sections:
        sub = ET.SubElement(
            submeshes,
            "submesh",
            material=section.material,
            usesharedvertices="false",
            use32bitindexes="true",
            operationtype="triangle_list",
        )
        faces = ET.SubElement(
            sub, "faces", count=str(len(section.indices) // 3)
        )
        for i in range(0, len(section.indices), 3):
            ET.SubElement(
                faces,
                "face",
                **{f"v{j + 1}": str(section.indices[i + j]) for j in range(3)},
            )
        geometry = ET.SubElement(
            sub, "geometry", vertexcount=str(len(section.vertices))
        )
        buffer = ET.SubElement(
            geometry,
            "vertexbuffer",
            positions="true",
            normals="true",
            colours_diffuse="true",
            texture_coords="1",
            texture_coord_dimensions_0="2",
        )
        for values in section.vertices:
            vertex = ET.SubElement(buffer, "vertex")
            for name, offset in (("position", 0), ("normal", 3)):
                ET.SubElement(
                    vertex,
                    name,
                    **{
                        axis: format(values[offset + j], ".9g")
                        for j, axis in enumerate("xyz")
                    },
                )
            ET.SubElement(
                vertex,
                "texcoord",
                u=format(values[6], ".9g"),
                v=format(values[7], ".9g"),
            )
            ET.SubElement(
                vertex,
                "colour_diffuse",
                value=" ".join(format(v, ".9g") for v in values[8:]),
            )
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def write_collision(path, vertices, triangles):
    with Path(path).open("wb") as stream:
        stream.write(COLLISION_MAGIC)
        stream.write(struct.pack("<II", len(vertices), len(triangles)))
        for p in vertices:
            stream.write(struct.pack("<3f", *p))
        for triangle in triangles:
            stream.write(struct.pack("<3I", *triangle))


def read_collision(path):
    with Path(path).open("rb") as stream:
        if stream.read(8) != COLLISION_MAGIC:
            raise ValueError("Unsupported collision version")
        nv, nt = struct.unpack("<II", stream.read(8))
        values = array("f")
        values.frombytes(stream.read(nv * 12))
        triangles = array("I")
        triangles.frombytes(stream.read(nt * 12))
        if len(values) != nv * 3 or len(triangles) != nt * 3 or stream.read(1):
            raise ValueError("Invalid collision payload")
        if any(i >= nv for i in triangles):
            raise ValueError("Invalid collision index")
        return values, triangles


def write_scene(path, nodes):
    root = ET.Element(
        "scene",
        formatVersion="1.0.0",
        minOgreVersion="1.12",
        author="Procedural medieval asset generator",
    )
    container = ET.SubElement(root, "nodes")
    for item in nodes:
        node = ET.SubElement(container, "node", name=item["name"])
        ET.SubElement(
            node,
            "position",
            **dict(zip("xyz", map(str, item["position"]), strict=True)),
        )
        ET.SubElement(
            node,
            "rotation",
            **dict(
                zip(
                    ("qw", "qx", "qy", "qz"),
                    map(str, item["rotation"]),
                    strict=True,
                )
            ),
        )
        ET.SubElement(
            node,
            "scale",
            **dict(zip("xyz", map(str, item["scale"]), strict=True)),
        )
        ET.SubElement(
            node,
            "entity",
            name=item["name"],
            meshFile=item["mesh"] + ".mesh",
            castShadows="true",
        )
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
