"""One conforming terrain/road mesh with shared junction vertices."""

import math
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace

import bpy
from mathutils import Vector
from mathutils.geometry import delaunay_2d_cdt

from castle_geometry import circle
from surface_quality import limit_road_slopes
from terrain_rules import (
    SpatialHash,
    boundary_distance,
    ground_gradient,
    inside_polygon,
    segment_projection,
    smoothstep,
    terrain_outline,
    value_noise,
)
from transport_rules import resample, road_footprints

SURFACE_CODES = {
    "land": 0,
    "ALLEY": 1,
    "ACCESS": 1,
    "SECONDARY": 2,
    "PRIMARY": 3,
    "plaza": 4,
}
GROUND_KEYS = (
    "terrain",
    "path_surface",
    "road_surface",
    "plaza_surface",
    "bare_terrain",
)


@dataclass(frozen=True)
class TerrainSkin:
    origin: tuple
    colour: Callable
    edge_height: Callable
    edge_normal: Callable
    grass_allowed: Callable | None = None


def surface_mesh(plan, sampler, materials, *, skin=None):
    outer = terrain_outline(plan)
    vertices, faces, tags, constraints, lookup = [], [], [], [], {}

    def vertex(point):
        key = tuple(round(v, 5) for v in point[:2])
        if key not in lookup:
            lookup[key] = len(vertices)
            vertices.append(Vector(key))
        return lookup[key]

    def polygon(points, tag):
        indices = [vertex(p) for p in points]
        faces.append(indices)
        tags.append(tag)

    polygon(outer, "land")
    for road in plan.roads:
        for p in road_footprints(road):
            polygon(p, road.kind)
        path = resample(road.points)
        constraints += [
            (vertex(a), vertex(b))
            for a, b in zip(path, path[1:], strict=False)
        ]
    for market in plan.markets:
        polygon(circle(market.centre[:2], market.radius, 48), "plaza")
    if plan.castle:
        polygon(plan.castle.outline, "castle")
        x, y, rad, _ = plan.terrain.castle_pad
        for scale in (1.02, 1.20, 1.42):
            points = circle((x, y), rad * scale, 64)
            constraints += [
                (vertex(a), vertex(b))
                for a, b in zip(points, points[1:] + points[:1], strict=True)
            ]
    for building in plan.buildings:
        polygon(building.corners, "land")
    step = plan.config.terrain_step
    left, right = min(p[0] for p in outer), max(p[0] for p in outer)
    bottom, top = min(p[1] for p in outer), max(p[1] for p in outer)

    def on_edge(x, y):
        return (
            min(abs(x - left), abs(x - right), abs(y - bottom), abs(y - top))
            < 0.001
        )

    for j in range(math.ceil((top - bottom) / step) + 1):
        for i in range(math.ceil((right - left) / step) + 1):
            x, y = left + i * step, bottom + j * step
            x += (
                value_noise(i * 0.7, j * 0.7, plan.config.terrain_seed + 9)
                * step
                * 0.10
            )
            y += (
                value_noise(i * 0.7, j * 0.7, plan.config.terrain_seed + 19)
                * step
                * 0.10
            )
            if inside_polygon((x, y), outer) and (
                skin is None or not on_edge(x, y)
            ):
                vertex((x, y))
    points, _, triangles, _, _, _ = delaunay_2d_cdt(
        vertices, constraints, faces, 1, 0.0005, False
    )
    seam = {i for i, p in enumerate(points) if skin and on_edge(p.x, p.y)}
    xyz = [
        (
            p.x,
            p.y,
            skin.edge_height(p.x, p.y)
            if i in seam
            else sampler.height(p.x, p.y),
        )
        for i, p in enumerate(points)
    ]
    kept, codes = [], []
    for triangle in triangles:
        centre = tuple(sum(points[i][j] for i in triangle) / 3 for j in (0, 1))
        if plan.castle and inside_polygon(centre, plan.castle.outline):
            continue
        a, b, c = (Vector(xyz[i]) for i in triangle)
        if (b - a).cross(c - a).length < 1e-8:
            continue
        if (b - a).cross(c - a).z < 0:
            triangle = list(reversed(triangle))
        kept.append(triangle)
        code = 0
        for index in sampler.roads.query(centre, 8):
            a, b, width, kind = sampler.segments[index]
            if segment_projection(centre, a, b)[0] <= width / 2 + 0.001:
                code = max(code, SURFACE_CODES[kind])
        if any(
            math.dist(centre, m.centre[:2]) < m.radius for m in plan.markets
        ):
            code = 4
        codes.append(code)
    tracks, centre_edges = _centre_tracks(points, sampler)
    fixed = set(_fixed_levels(xyz, plan)) | seam
    grade = plan.config.max_road_grade + 0.15
    correction = limit_road_slopes(
        xyz,
        kept,
        codes,
        grade,
        fixed=fixed,
        centre_edges=centre_edges,
        longitudinal=plan.config.max_road_grade * 0.999,
    )
    mesh = bpy.data.meshes.new("Game_Terrain_Roads")
    mesh.from_pydata(xyz, [], kept)
    mesh.update()
    if skin:
        colour_at, origin = skin.colour, skin.origin
    else:
        origin = (0, 0)

        def colour_at(x, y):
            return meadow_colour(
                x, y, sampler.height, plan.config.terrain_seed, materials, step
            )

    paint_land(mesh, materials, codes, colour_at, origin)
    if seam:
        set_edge_normals(mesh, seam, skin.edge_normal)
    mesh["surface_vertices_shared"] = True
    mesh["road_triangles"] = sum(code > 0 for code in codes)
    mesh["max_road_grade"] = plan.config.max_road_grade
    mesh["max_surface_road_grade"] = grade
    mesh["surface_height_correction"] = correction
    mesh["boundary_open"] = True
    return mesh, _surface_roads(plan.roads, tracks, xyz)


def meadow_colour(x, y, height, seed, materials, step):
    slope = math.hypot(*ground_gradient(height, x, y, max(0.45, step * 0.4)))
    blend = smoothstep(0.42, 0.98, slope)
    noise = value_noise(x / 18, y / 18, seed + 31)
    grass = materials["grass"].diffuse_color
    rock = materials["rock_light"].diffuse_color
    colour = tuple(
        (grass[i] * (1 - blend) + rock[i] * blend) * (1 + noise * 0.18)
        for i in range(3)
    )
    return colour, slope < 0.63


def paint_land(mesh, materials, codes, colour_at, origin=(0, 0)):
    for key in GROUND_KEYS:
        mesh.materials.append(materials[key])
    code_attribute = mesh.attributes.new("surface_kind", "INT", "FACE")
    colour = mesh.color_attributes.new(
        name="Color", type="FLOAT_COLOR", domain="POINT"
    )
    grassy = []
    for v in mesh.vertices:
        rgb, grass = colour_at(v.co.x, v.co.y)
        grassy.append(grass)
        colour.data[v.index].color = (*rgb, 1)
    for poly, code in zip(mesh.polygons, codes, strict=True):
        if code == 0:
            meadow = sum(grassy[i] for i in poly.vertices) >= 2
            poly.material_index = 0 if meadow else 4
        else:
            poly.material_index = 3 if code == 4 else 2 if code >= 2 else 1
        poly.use_smooth = True
        code_attribute.data[poly.index].value = code
    uv = mesh.uv_layers.new(name="UVMap")
    for loop in mesh.loops:
        point = mesh.vertices[loop.vertex_index].co
        uv.data[loop.index].uv = (
            (point.x + origin[0]) / 2.0,
            (point.y + origin[1]) / 2.0,
        )


def set_edge_normals(mesh, seam, normal_at):
    normals = [
        normal_at(v.co.x, v.co.y) if v.index in seam else (0, 0, 0)
        for v in mesh.vertices
    ]
    mesh.normals_split_custom_set_from_vertices(normals)


def _centre_tracks(points, sampler):
    candidates = defaultdict(list)
    for i, p in enumerate(points):
        for index in sampler.roads.query(p, 0.001):
            a, b, _, _ = sampler.segments[index]
            distance, t, _ = segment_projection(p, a, b)
            if distance < 0.00075:
                candidates[index].append((t, i, distance))
    tracks, links = {}, set()
    for index, rows in candidates.items():
        length = math.dist(*[p[:2] for p in sampler.segments[index][:2]])
        clean = []
        for row in sorted(rows):
            if clean and (row[0] - clean[-1][0]) * length < 0.001:
                if row[2] < clean[-1][2]:
                    clean[-1] = row
            else:
                clean.append(row)
        tracks[index] = [(t, i) for t, i, _ in clean]
        links.update(
            (a[1], b[1]) for a, b in zip(clean, clean[1:], strict=False)
        )
    return tracks, sorted(links)


def _fixed_levels(xyz, plan):
    anchors = [b.entry for b in plan.buildings]
    sites = SpatialHash(2)
    for i, p in enumerate(anchors):
        sites.insert(i, (p[0], p[1], p[0], p[1]))
    fixed = set()
    for i, p in enumerate(xyz):
        height = None
        for m in plan.markets:
            if math.dist(p[:2], m.centre[:2]) <= m.radius:
                height = m.centre[2] + 0.12
        castle = plan.castle
        if (
            castle
            and math.dist(p[:2], castle.centre[:2]) < castle.radius * 1.1
            and (
                inside_polygon(p[:2], castle.outline)
                or boundary_distance(p[:2], castle.outline) < 0.001
            )
        ):
            height = castle.centre[2] + 0.12
        for j in sites.query(p, 0.001):
            if math.dist(p[:2], anchors[j][:2]) < 0.001:
                height = anchors[j][2]
        if height is not None:
            xyz[i] = (*p[:2], height)
            fixed.add(i)
    return fixed


def _surface_roads(roads, tracks, xyz):
    result, index = [], 0
    for road in roads:
        points = []
        for a, b in zip(road.points, road.points[1:], strict=False):
            length = math.dist(a[:2], b[:2])
            for t, i in tracks.get(index, ()):
                t = 0 if t * length < 0.001 else t
                t = 1 if (1 - t) * length < 0.001 else t
                p = tuple(a[j] + (b[j] - a[j]) * t for j in (0, 1))
                p += (xyz[i][2],)
                if not points or math.dist(p[:2], points[-1][:2]) > 0.001:
                    points.append(p)
            index += 1
        result.append(replace(road, points=tuple(points)))
    return tuple(result)
