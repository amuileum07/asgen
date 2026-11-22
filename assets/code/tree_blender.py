"""Branch skeletons and shared foliage meshes for realistic trees."""

import math
import random

from mathutils import Vector

from house_generator import MeshBatch

UP = Vector((0, 0, 1))


def tree_stem(batch, points, radii, turn, sides, material="wood"):
    axis = (points[-1] - points[0]).normalized()
    horizontal = Vector((math.cos(turn), math.sin(turn), 0))
    u = axis.cross(horizontal).normalized()
    v = axis.cross(u)
    first = len(batch.vertices)
    for point, radius in zip(points, radii, strict=True):
        for side in range(sides):
            angle = side * math.tau / sides
            offset = u * math.cos(angle) + v * math.sin(angle)
            batch.vertices.append(tuple(point + radius * offset))
    last = first + (len(points) - 1) * sides
    faces = [
        tuple(range(first + sides - 1, first - 1, -1)),
        tuple(range(last, last + sides)),
    ]
    for a in range(first, last, sides):
        for side in range(sides):
            i = a + side
            j = a + (side + 1) % sides
            faces.append((i, j, j + sides, i + sides))
    batch.faces.extend(faces)
    batch.face_materials.extend(
        [batch.material_indices[material]] * len(faces)
    )


def _direction(angle):
    return Vector((math.cos(angle), math.sin(angle), 0))


def _leaf(batch, start, direction, length, width, slot):
    """Four triangles meet at the raised midrib of a pointed blade."""
    forward = direction.normalized()
    side = UP.cross(forward).normalized()
    normal = forward.cross(side)
    middle = start + forward * (length * 0.44)
    first = len(batch.vertices)
    batch.vertices.extend(
        tuple(p)
        for p in (
            start,
            middle - side * width,
            start + forward * length,
            middle + side * width,
            middle + normal * (width * 0.33),
        )
    )
    batch.faces.extend(
        (first + i, first + (i + 1) % 4, first + 4) for i in range(4)
    )
    batch.face_materials.extend([slot] * 4)


def _spray(leaves, twigs, start, end, angle, rng, pine, slots, compact):
    along = end - start
    direction = along.normalized()
    side = UP.cross(direction).normalized()
    radius = 0.011 if pine else 0.014
    tree_stem(twigs, (start, end), (radius, 0.003), angle, 4, "bark")
    pairs = 3 if compact else (8 if pine else 6)
    for i in range(pairs):
        t = (i + 0.35) / pairs
        node = start + along * t
        for sign in (-1, 1):
            aim = direction * (0.32 + 0.5 * t) + side * sign
            aim.z += rng.uniform(-0.48, 0.38)
            # A conifer spray narrows towards its growing tip.
            length = (0.24 - 0.15 * t) if pine else rng.uniform(0.17, 0.31)
            if compact:
                length *= 1.35
            width = length * (0.12 if pine else rng.uniform(0.25, 0.37))
            _leaf(leaves, node, aim, length, width, rng.choice(slots))


def _broadleaf(leaves, trunk, limbs, rng, slots, compact):
    lean = _direction(rng.random() * math.tau) * rng.uniform(0.12, 0.36)

    def stem(z):
        return UP * z + lean * (z / 4) ** 1.6

    tree_stem(
        trunk,
        [stem(z) for z in (0, 0.22, 1.2, 2.2, 3.1, 3.9)],
        (0.225, 0.155, 0.122, 0.095, 0.057, 0.019),
        0.7,
        11,
        "bark",
    )
    for i in range(5):
        yaw = i * math.tau / 5 + rng.uniform(-0.24, 0.24)
        out = _direction(yaw)
        tree_stem(
            trunk,
            (UP * 0.28, out * 0.22 + UP * 0.06, out * 0.43 - UP * 0.09),
            (0.12, 0.075, 0.026),
            yaw + 1.5,
            7,
            "bark",
        )
    for i in range(16):
        t = i / 15
        angle = i * 2.39996 + rng.uniform(-0.27, 0.27)
        radial = _direction(angle)
        base = stem(1.45 + t * 2.4)
        reach = (1.55 - 0.82 * t) * rng.uniform(0.82, 1.19)
        elbow = base + radial * reach * 0.47 + UP * 0.33
        tip = base + radial * reach + UP * rng.uniform(0.73, 1.15)
        tree_stem(
            limbs,
            (base, elbow, tip),
            (0.082 - 0.04 * t, 0.044, 0.015),
            angle + 1.2,
            7,
            "bark",
        )
        forks = 3 if compact else 5
        for j in range(forks):
            fork = elbow.lerp(tip, j / forks)
            yaw = angle + (-1 if j % 2 else 1) * rng.uniform(0.54, 1.3)
            direction = _direction(yaw)
            end = (
                fork
                + direction * rng.uniform(0.38, 0.74)
                + UP * rng.uniform(0.25, 0.58)
            )
            tree_stem(limbs, (fork, end), (0.027, 0.009), yaw + 1, 5, "bark")
            for k in range(4):
                start = fork.lerp(end, 0.32 + 0.20 * k)
                fan = _direction(yaw + (k - 1.5) * 0.78)
                stop = (
                    start
                    + fan * rng.uniform(0.32, 0.55)
                    + UP * rng.uniform(-0.08, 0.28)
                )
                _spray(
                    leaves, limbs, start, stop, yaw, rng, False, slots, compact
                )


def _conifer(leaves, trunk, limbs, rng, slots, compact):
    lean = _direction(rng.random() * math.tau) * 0.12

    def stem(z):
        return UP * z + lean * (z / 5) ** 2

    levels = (-0.12, 0.22, 1.4, 2.8, 4.1, 5.0)
    tree_stem(
        trunk,
        [stem(z) for z in levels],
        (0.18, 0.126, 0.102, 0.078, 0.041, 0.007),
        0,
        10,
        "bark",
    )
    tiers = 8 if compact else 11
    for row in range(tiers):
        t = row / (tiers - 1)
        level = 0.95 + 3.91 * t
        radius = 1.4 * (1 - t) ** 0.82 + 0.07
        count = 7 - round(3 * t)
        turn = rng.random() * math.tau
        for i in range(count):
            yaw = turn + i * math.tau / count + rng.uniform(-0.18, 0.18)
            radial = _direction(yaw)
            base = stem(level + rng.uniform(-0.055, 0.055))
            reach = radius * rng.uniform(0.84, 1.14)
            elbow = base + (radial * 0.60 - UP * 0.18) * reach
            tip = base + (radial - UP * 0.09) * reach
            tree_stem(
                limbs,
                (base, elbow, tip),
                (0.008 + reach * 0.026, 0.009 + reach * 0.012, 0.004),
                yaw + 1,
                5,
                "bark",
            )
            sprays = 3 if compact else 5
            for j in range(sprays):
                f = 0.18 + (j / (sprays - 1)) * 0.64
                start = (
                    base.lerp(elbow, f / 0.6)
                    if f <= 0.6
                    else elbow.lerp(tip, (f - 0.6) / 0.4)
                )
                for sign in (-1, 1):
                    fan = _direction(yaw + sign * (0.85 - f * 0.3))
                    end = start + (fan - UP * 0.32) * (
                        reach * (0.41 - f * 0.22) + 0.06
                    )
                    _spray(
                        leaves,
                        limbs,
                        start,
                        end,
                        yaw,
                        rng,
                        True,
                        slots,
                        compact,
                    )


class TreeLibrary:
    """Reuse tree meshes within a generated collection."""

    def __init__(
        self, collection, root, materials, finish, *, town=False, compact=False
    ):
        self.collection, self.root = collection, root
        self.materials, self.finish = materials, finish
        self.compact = compact
        self.roles = (
            "trees" if town else "world_woodland",
            "tree_trunks" if town else "world_tree_trunks",
            "world_tree_branches",
        )
        self.variants = {}

    def plant(self, base, height, turn, spread, broadleaf, rng, material):
        variant = rng.randrange(3)
        key = broadleaf, variant, material
        if key in self.variants:
            objects = [obj.copy() for obj in self.variants[key]]
            for obj in objects:
                self.collection.objects.link(obj)
        else:
            species = "Broadleaf" if broadleaf else "Conifer"
            batches = [
                MeshBatch(f"{species}_{part}_{variant}", self.materials)
                for part in ("Foliage", "Trunk", "Branches")
            ]
            leaves = batches[0].material_indices
            slots = [leaves[material]] * 5 + [
                leaves["leaves_light"],
                leaves["leaves_shadow"],
            ]
            grow = _broadleaf if broadleaf else _conifer
            grow(
                *batches,
                random.Random(f"{species}:{variant}"),
                slots,
                self.compact,
            )
            objects = [
                self.finish(batch, self.collection, self.root, role)
                for batch, role in zip(batches, self.roles, strict=True)
            ]
            crown, _, branches = objects
            crown["collision_enabled"] = branches["collision_enabled"] = False
            crown["atlas_effect"] = "CROWN"
            mesh = crown.data
            uv = mesh.uv_layers.active.data
            for loop in mesh.loops:
                z = mesh.vertices[loop.vertex_index].co.z
                uv[loop.index].uv.y = min(1.0, max(0.0, z / 5)) ** 1.6
            self.variants[key] = objects
        scale = height / 5
        for obj in objects:
            obj.location = base
            obj.rotation_euler.z = turn
            obj.scale = (spread * scale, spread * scale, scale)
