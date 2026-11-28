"""Terrain-aware medieval settlement planning without Blender."""

import heapq
import math
import random
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace

from art_style import validate_art_style
from castle_interior_rules import CastleInterior, make_castle_interior
from castle_rules import (
    CastleArchitecture,
    castle_point,
    make_castle_architecture,
)
from civic_rules import civic_navigation, make_civic_assets
from house_rules import HouseConfig, make_plan
from terrain_rules import (
    SpatialHash,
    TerrainSpec,
    boundary_distance,
    inside_polygon,
    natural_height,
    oriented_corners,
    polygons_overlap,
    segment_projection,
    terrain_height,
    terrain_outline,
    value_noise,
)
from transport_rules import conform_junctions, resample

ROAD_LIFT = 0.12
ROAD_WIDTHS = {"PRIMARY": 5.0, "SECONDARY": 3.6, "ALLEY": 2.2, "ACCESS": 1.2}
KINDS = ("PRIMARY", "SECONDARY", "ALLEY")
PROFILES = {
    "VILLAGE": {
        "radius": 42,
        "buildings": 28,
        "gates": 2,
        "rings": (),
        "alleys": 5,
        "markets": 1,
        "walls": False,
        "castle": False,
        "wall_height": 2.8,
    },
    "TOWN": {
        "radius": 78,
        "buildings": 100,
        "gates": 3,
        "rings": (0.57,),
        "alleys": 12,
        "markets": 1,
        "walls": True,
        "castle": False,
        "wall_height": 3.8,
    },
    "CITY": {
        "radius": 120,
        "buildings": 240,
        "gates": 4,
        "rings": (0.43, 0.73),
        "alleys": 25,
        "markets": 2,
        "walls": True,
        "castle": True,
        "wall_height": 5.2,
    },
    "CAPITAL": {
        "radius": 175,
        "buildings": 480,
        "gates": 5,
        "rings": (0.35, 0.59, 0.82),
        "alleys": 44,
        "markets": 3,
        "walls": True,
        "castle": True,
        "wall_height": 6.3,
    },
}

SITE_ASPECTS = {
    "INLAND": (1.0, 1.0),
    "HARBOR": (1.11, 0.81),
    "MOUNTAIN": (1.10, 0.86),
    "LAKESIDE": (1.05, 0.83),
    "RIVERSIDE": (1.19, 0.77),
}
SITE_BUSINESSES = {
    "HARBOR": ("FISHMONGER", "WAREHOUSE", "SHIP_CHANDLER"),
    "MOUNTAIN": ("MOUNTAIN_INN", "SMITH", "STONECUTTER"),
    "LAKESIDE": ("BOATHOUSE", "FISHMONGER", "TAVERN"),
    "RIVERSIDE": ("GRAIN_MERCHANT", "WEAVER", "MARKET_STORE"),
}


@dataclass(frozen=True)
class LocalSite:
    style: str
    bearing: float
    ground: Callable[[float, float], float]
    approach: tuple = ()


@dataclass(frozen=True)
class SettlementConfig:
    seed: int = 42
    terrain_seed: int = 84
    scale: str = "TOWN"
    radius: float = 0.0
    density: float = 0.90
    relief: float = 8.0
    irregularity: float = 0.20
    walls: str = "AUTO"
    castle: str = "AUTO"
    castle_site: str = "HILLTOP"
    castle_interior: bool = True
    castle_furnish: bool = True
    max_buildings: int = 0
    road_grid: float = 4.0
    max_road_grade: float = 0.20
    terrain_step: float = 2.5
    detail: str = "LOW"
    trees: bool = True
    grass: bool = True
    grass_density: float = 0.55
    civic: bool = True
    art_style: str = "CARTOON"

    def validate(self):
        validate_art_style(self.art_style)
        if self.scale not in PROFILES:
            raise ValueError(f"scale must be one of {tuple(PROFILES)}")
        for name in ("seed", "terrain_seed", "max_buildings"):
            value = getattr(self, name)
            maximum = 1200 if name == "max_buildings" else 2_000_000_000
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError(
                    f"{name} must be an integer in [0, {maximum}]"
                )
        limits = {
            "radius": (0, 350),
            "density": (0.15, 1),
            "relief": (0, 24),
            "irregularity": (0.04, 0.32),
            "road_grid": (2.5, 5),
            "max_road_grade": (0.08, 0.30),
            "terrain_step": (1.5, 5),
            "grass_density": (0, 1.5),
        }
        for name, (low, high) in limits.items():
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not low <= value <= high
            ):
                raise ValueError(f"{name} must be between {low} and {high}")
        if self.radius and self.radius < 35:
            raise ValueError("A custom settlement radius must be at least 35m")
        if self.walls not in ("AUTO", "ON", "OFF") or self.castle not in (
            "AUTO",
            "ON",
            "OFF",
        ):
            raise ValueError("walls/castle must be AUTO, ON or OFF")
        if self.detail not in ("LOW", "HIGH") or type(self.trees) is not bool:
            raise ValueError("Invalid detail level or trees switch")
        if any(type(v) is not bool for v in (self.grass, self.civic)):
            raise ValueError("grass/civic must be booleans")
        if self.castle_site not in ("HILLTOP", "WALLED"):
            raise ValueError("castle_site must be HILLTOP or WALLED")
        if (
            type(self.castle_interior) is not bool
            or type(self.castle_furnish) is not bool
        ):
            raise ValueError("castle_interior/castle_furnish must be booleans")
        return self

    @property
    def effective_radius(self):
        return self.radius or PROFILES[self.scale]["radius"]


@dataclass(frozen=True)
class Market:
    id: str
    centre: tuple
    radius: float


@dataclass(frozen=True)
class Gate:
    id: str
    position: tuple
    outward: tuple
    width: float


@dataclass(frozen=True)
class Castle:
    centre: tuple
    radius: float
    outline: tuple
    gate: Gate
    keep_heading: float
    keep_entry: tuple
    keep_approach: tuple
    site: str
    architecture: CastleArchitecture
    interior: CastleInterior | None = None


@dataclass(frozen=True)
class Road:
    id: str
    kind: str
    width: float
    points: tuple


@dataclass(frozen=True)
class BuildingTemplate:
    id: str
    config: HouseConfig
    entrance: tuple


@dataclass(frozen=True)
class Building:
    id: str
    template_id: str
    position: tuple
    heading: float
    width: float
    depth: float
    corners: tuple
    entry: tuple
    street_id: str
    zone: str
    business: str
    commercial_score: float


@dataclass(frozen=True)
class SettlementPlan:
    config: SettlementConfig
    terrain: TerrainSpec
    boundary: tuple
    gates: tuple
    markets: tuple
    roads: tuple
    buildings: tuple
    templates: tuple
    castle: Castle | None
    has_walls: bool
    wall_height: float
    navigation: dict
    warnings: tuple
    civic_assets: tuple = ()
    site_style: str = "INLAND"
    surface_boundary: tuple = ()

    def as_dict(self):
        data = asdict(
            replace(self, terrain=replace(self.terrain, ground=None))
        )
        del data["terrain"]["ground"]
        return {
            "schema_version": 5,
            "units": "metres",
            "coordinate_space": "settlement_local",
            "terrain_boundary": terrain_outline(self),
            **data,
        }


def _enabled(value, automatic):
    return automatic if value == "AUTO" else value == "ON"


def _key(point):
    return tuple(round(float(value), 5) for value in point[:2])


def _edge(a, b):
    return tuple(sorted((_key(a), _key(b))))


def _boundary(config, rng, site):
    radius = config.effective_radius
    stretch = SITE_ASPECTS[site.style] if site else (1, 1)
    aspect = (
        rng.uniform(1.04, 1.20) * stretch[0],
        rng.uniform(0.82, 1.01) * stretch[1],
    )
    heading = site.bearing + math.pi / 2 if site else 0
    c, s = math.cos(heading), math.sin(heading)
    phase = [rng.uniform(0, math.tau) for _ in range(3)]
    points = []
    for index in range(128):
        angle = index * math.tau / 128
        variation = config.irregularity * (
            0.56 * math.sin(3 * angle + phase[0])
            + 0.30 * math.sin(5 * angle + phase[1])
            + 0.14 * math.cos(7 * angle + phase[2])
        )
        distance = radius * (1 + variation)
        x = distance * aspect[0] * math.cos(angle)
        y = distance * aspect[1] * math.sin(angle)
        points.append((x * c - y * s, x * s + y * c))
    return tuple(points), aspect


def _settlement_pot_rate(seed, style):
    """Choose whether a settlement omits, rarely uses, or mixes pots."""
    rng = random.Random(f"{seed}:{style}:chimney-tradition")
    roll = rng.random()
    if style in ("MOUNTAIN", "LAKESIDE"):
        if roll < 0.45:
            return 0.0
        if roll < 0.80:
            return 0.14
        return 0.72
    if roll < 0.35:
        return 0.0
    if roll < 0.70:
        return 0.16
    return 0.78


def _chimney_cap_for(seed, pot_rate):
    rng = random.Random(f"{seed}:chimney-cap")
    if rng.random() < pot_rate:
        return "POTS"
    return "STONE_CAP" if rng.random() < 0.58 else "OPEN"


def _template(
    identifier,
    width,
    depth,
    floors,
    config,
    palette,
    style,
    *,
    chimney_cap="AUTO",
):
    wall_style = {
        "MOUNTAIN": "BRICK",
        "HARBOR": "WOOD_VERTICAL" if palette == "COASTAL" else "PLASTER",
        "LAKESIDE": "WOOD_HORIZONTAL",
    }.get(style, "PLASTER")
    roof_pitch = {
        "MOUNTAIN": 49,
        "LAKESIDE": 35,
        "RIVERSIDE": 44,
    }.get(style, 40 + len(identifier) % 8)
    house = HouseConfig(
        art_style=config.art_style,
        seed=config.seed + len(identifier) * 19,
        detail_seed=(config.seed + len(identifier) * 7 + floors * 13) % 997,
        width=width,
        depth=depth,
        floors=floors,
        variation=0,
        interior=False,
        furnish=False,
        wall_style=wall_style,
        brick_width=0.92 if style == "MOUNTAIN" else 0.58,
        brick_height=0.40 if style == "MOUNTAIN" else 0.28,
        roof_pitch=roof_pitch,
        roof_tiles=config.detail == "HIGH",
        shutters=config.detail == "HIGH",
        palette=palette,
        bevel=0.012 if config.detail == "HIGH" else 0,
        chimney_cap=chimney_cap,
    )
    plan = make_plan(house)
    opening = next(o for o in plan.walls[0].openings if o.kind == "DOOR")
    entrance = (-width / 2 + (opening.x1 + opening.x2) / 2, -depth / 2)
    return BuildingTemplate(identifier, house, entrance)


def _templates(config, style):
    pot_rate = _settlement_pot_rate(config.seed, style)
    result = []
    for index, (width, depth) in enumerate(
        ((4.6, 5.0), (5.4, 6.0), (6.4, 7.0))
    ):
        for floors in range(1, 4):
            for palette in ("WARM", "COASTAL"):
                identifier = f"home_{index}_{floors}_{palette.lower()}"
                cap = _chimney_cap_for(f"{config.seed}:{identifier}", pot_rate)
                result.append(
                    _template(
                        identifier,
                        width,
                        depth,
                        floors,
                        config,
                        palette,
                        style,
                        chimney_cap=cap,
                    )
                )
    return tuple(result)


def _castle(config, boundary, terrain, market):
    radius = (
        34
        if config.scale == "CAPITAL"
        else 26
        if config.scale == "CITY"
        else 20
    )
    radius = min(radius, config.effective_radius * 0.26)
    candidates = []
    for index in range(17):
        angle = math.pi * (0.18 + index * 0.64 / 16)
        x, y = (
            config.effective_radius * 0.56 * math.cos(angle),
            config.effective_radius * 0.56 * math.sin(angle),
        )
        if (
            inside_polygon((x, y), boundary)
            and boundary_distance((x, y), boundary) > radius + 7
        ):
            candidates.append((natural_height(terrain, x, y), x, y))
    if not candidates:
        raise ValueError("Castle does not fit the boundary; increase radius")
    _, x, y = max(candidates)
    rise = config.effective_radius * 0.065 + config.relief * 0.20
    if config.castle_site == "WALLED":
        rise *= 0.12
    terrain = replace(
        terrain, hill=(x, y, config.effective_radius * 0.42, rise)
    )
    z = natural_height(terrain, x, y)
    angle = math.atan2(market[1] - y, market[0] - x)
    outward = (math.cos(angle), math.sin(angle))
    heading = angle + math.pi / 2
    architecture = make_castle_architecture(config.seed, radius)
    terrain = replace(
        terrain,
        castle_pad=(x, y, radius + 1, z),
        castle_blend=(
            *outward,
            radius * 1.7 + 14,
            5 if config.castle_site == "HILLTOP" else 20,
        ),
    )
    outline = tuple(
        castle_point((x, y, z), heading, point)[:2]
        for point in architecture.outline
    )
    gx, gy = (
        (outline[0][0] + outline[1][0]) / 2,
        (outline[0][1] + outline[1][1]) / 2,
    )
    distance = math.hypot(gx - x, gy - y)
    outward = ((gx - x) / distance, (gy - y) / distance)
    entry = castle_point((x, y, z), heading, architecture.entry)
    approach = (entry[0] + outward[0] * 2.0, entry[1] + outward[1] * 2.0)
    gate = Gate("castle_gate", (gx, gy, z), outward, architecture.gate_width)
    return Castle(
        (x, y, z),
        radius,
        outline,
        gate,
        heading,
        entry,
        approach,
        config.castle_site,
        architecture,
        make_castle_interior(
            architecture, config.seed, furnish=config.castle_furnish
        )
        if config.castle_interior
        else None,
    ), terrain


class RoadPlanner:
    def __init__(self, config, terrain, boundary, castle):
        self.config, self.terrain = config, terrain
        self.boundary, self.castle = boundary, castle
        self.edges = {}
        self.road_cells = set()
        self.heights, self.valid = {}, {}

    def cell(self, point):
        return tuple(
            round(value / self.config.road_grid) for value in point[:2]
        )

    def point(self, cell):
        return tuple(value * self.config.road_grid for value in cell)

    def allowed(self, cell):
        if cell not in self.valid:
            point = self.point(cell)
            valid = inside_polygon(point, self.boundary)
            if valid and self.castle:
                valid = (
                    math.dist(point, self.castle.centre[:2])
                    > self.castle.radius + 10
                )
            self.valid[cell] = valid
        return self.valid[cell]

    def height(self, cell):
        if cell not in self.heights:
            self.heights[cell] = terrain_height(
                self.terrain, *self.point(cell)
            )
        return self.heights[cell]

    def nearest_allowed(self, point):
        start = self.cell(point)
        for radius in range(9):
            choices = [
                (
                    math.dist(self.point((start[0] + x, start[1] + y)), point),
                    (start[0] + x, start[1] + y),
                )
                for x in range(-radius, radius + 1)
                for y in range(-radius, radius + 1)
                if self.allowed((start[0] + x, start[1] + y))
            ]
            if choices:
                return min(choices)[1]
        raise ValueError("No traversable road cell near the requested point")

    def add_path(self, points, kind):
        for a, b in zip(points, points[1:], strict=False):
            if math.dist(a, b) > 1e-5:
                edge = _edge(a, b)
                self.edges[edge] = min(kind, self.edges.get(edge, kind))
                self.road_cells.update((self.cell(a), self.cell(b)))

    def route(self, start, end, kind, optional=False):
        first, last = self.nearest_allowed(start), self.nearest_allowed(end)
        queue = [(math.dist(first, last), 0.0, first)]
        costs, parents = {first: 0.0}, {}
        visited = 0
        while queue:
            _, cost, cell = heapq.heappop(queue)
            if cost > costs[cell] + 1e-8:
                continue
            if cell == last:
                path = [cell]
                while path[-1] != first:
                    path.append(parents[path[-1]])
                points = [self.point(item) for item in reversed(path)]
                self.add_path(points, kind)
                return points
            visited += 1
            if visited > 100000:
                break
            for dx, dy in (
                (1, 0),
                (0, 1),
                (-1, 0),
                (0, -1),
                (1, 1),
                (-1, 1),
                (-1, -1),
                (1, -1),
            ):
                other = (cell[0] + dx, cell[1] + dy)
                if not self.allowed(other):
                    continue
                if kind == 2 and any(
                    math.dist(self.point(other), (x, y)) < radius + 5
                    for x, y, radius, _ in self.terrain.plazas
                ):
                    continue
                length = math.hypot(dx, dy) * self.config.road_grid
                grade = abs(self.height(other) - self.height(cell)) / length
                if grade > self.config.max_road_grade:
                    continue
                point = self.point(other)
                noise = value_noise(
                    point[0] / 24, point[1] / 24, self.config.seed + 37
                )
                known = _edge(self.point(cell), point) in self.edges
                step_cost = length * (
                    1 + grade * grade * 30 + (noise + 1) * 0.12
                )
                step_cost *= 0.91 if known else 1.0
                if other not in self.road_cells and any(
                    (other[0] + x, other[1] + y) in self.road_cells
                    for x, y in ((1, 0), (-1, 0), (0, 1), (0, -1))
                ):
                    step_cost *= 1.45
                candidate = cost + step_cost
                if candidate + 1e-8 < costs.get(other, math.inf):
                    costs[other], parents[other] = candidate, cell
                    heuristic = (
                        math.dist(other, last) * self.config.road_grid * 0.90
                    )
                    heapq.heappush(
                        queue, (candidate + heuristic, candidate, other)
                    )
        if optional:
            return []
        raise ValueError(
            "Terrain blocks a required road; reduce relief or grade limits"
        )


def _smooth(points):
    if len(points) < 3:
        return points
    result = [points[0]]
    for a, b in zip(points, points[1:], strict=False):
        result.extend(
            (
                tuple(a[i] * 0.8 + b[i] * 0.2 for i in range(2)),
                tuple(a[i] * 0.2 + b[i] * 0.8 for i in range(2)),
            )
        )
    result.append(points[-1])
    return result


def _road_chains(planner):
    edges = dict(planner.edges)
    # Split crossing diagonals at a shared junction.
    diagonals = defaultdict(list)
    step = planner.config.road_grid
    for (a, b), kind in edges.items():
        if (
            abs(abs(a[0] - b[0]) - step) < 1e-5
            and abs(abs(a[1] - b[1]) - step) < 1e-5
        ):
            diagonals[_key(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))].append(
                (a, b, kind)
            )
    for midpoint, crossing in diagonals.items():
        if len(crossing) == 2:
            for a, b, kind in crossing:
                edges.pop(_edge(a, b))
                for edge in (_edge(a, midpoint), _edge(midpoint, b)):
                    edges[edge] = min(kind, edges.get(edge, kind))
    adjacent = defaultdict(set)
    for a, b in edges:
        adjacent[a].add(b)
        adjacent[b].add(a)
    remaining = set(edges)
    roads = []
    while remaining:
        a, b = min(remaining)
        kind = edges[(a, b)]
        if len(adjacent[a]) == 2 and len(adjacent[b]) != 2:
            a, b = b, a
        points = [a, b]
        remaining.remove(_edge(a, b))
        while len(adjacent[points[-1]]) == 2:
            current = points[-1]
            other = next(
                point
                for point in sorted(adjacent[current])
                if point != points[-2]
            )
            edge = _edge(current, other)
            if edge not in remaining or edges[edge] != kind:
                break
            points.append(other)
            remaining.remove(edge)
        smoothed = _smooth(_smooth(points))
        positions = [
            (x, y, terrain_height(planner.terrain, x, y) + ROAD_LIFT)
            for x, y in smoothed
        ]
        if any(
            abs(a[2] - b[2]) / math.dist(a[:2], b[:2])
            > planner.config.max_road_grade + 1e-6
            for a, b in zip(positions, positions[1:], strict=False)
        ):
            positions = [
                (x, y, terrain_height(planner.terrain, x, y) + ROAD_LIFT)
                for x, y in points
            ]
        roads.append(
            Road(
                f"street_{len(roads)}",
                KINDS[kind],
                ROAD_WIDTHS[KINDS[kind]],
                tuple(positions),
            )
        )
    return roads


def _commercial_score(point, markets, radius):
    return max(
        math.exp(
            -(math.dist(point, market.centre[:2]) ** 2)
            / (radius * (0.42 if index == 0 else 0.26)) ** 2
        )
        for index, market in enumerate(markets)
    )


def road_segments(roads):
    segments, index = [], SpatialHash()
    for road in roads:
        if road.kind == "ACCESS":
            continue
        for i, (a, b) in enumerate(
            zip(road.points, road.points[1:], strict=False)
        ):
            identifier = len(segments)
            segments.append((road, i, a, b))
            index.insert(
                identifier,
                (
                    min(a[0], b[0]),
                    min(a[1], b[1]),
                    max(a[0], b[0]),
                    max(a[1], b[1]),
                ),
            )
    return segments, index


def _point_at(road, distance):
    for index, (a, b) in enumerate(
        zip(road.points, road.points[1:], strict=False)
    ):
        length = math.dist(a[:2], b[:2])
        if distance <= length and length > 1e-8:
            t = distance / length
            return (
                index,
                tuple(a[i] + (b[i] - a[i]) * t for i in range(3)),
                ((b[0] - a[0]) / length, (b[1] - a[1]) / length),
            )
        distance -= length
    return None


def _street_rectangle(a, b, width):
    return oriented_corners(
        ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2),
        math.dist(a[:2], b[:2]),
        width,
        math.atan2(b[1] - a[1], b[0] - a[0]),
    )


def _buildings(
    config, boundary, terrain, roads, markets, castle, templates, site=None
):
    rng = random.Random(f"{config.seed}:frontage")
    radius = config.effective_radius
    segments, streets = road_segments(roads)
    candidates = []
    for road in roads:
        length = sum(
            math.dist(a[:2], b[:2])
            for a, b in zip(road.points, road.points[1:], strict=False)
        )
        distance = rng.uniform(2, 6)
        while distance < length - 2:
            result = _point_at(road, distance)
            if result:
                segment, point, tangent = result
                for side in (-1, 1):
                    score = _commercial_score(point[:2], markets, radius)
                    population = 0.35 + 0.65 * math.exp(
                        -(math.hypot(*point[:2]) ** 2) / (radius * 0.8) ** 2
                    )
                    priority = -math.log(max(1e-9, rng.random())) / population
                    candidates.append(
                        (priority, road, segment, point, tangent, side, score)
                    )
            distance += rng.uniform(3.5, 5.5)
    candidates.sort(key=lambda item: item[0])
    occupied, accesses = SpatialHash(), SpatialHash()
    buildings, connectors, attachments = [], [], defaultdict(list)
    target = config.max_buildings or round(
        PROFILES[config.scale]["buildings"] * config.density
    )
    homes = [template for template in templates if template.id != "keep"]
    for _, road, segment, point, tangent, side, score in candidates:
        if len(buildings) >= target:
            break
        if rng.random() > config.density:
            continue
        zone = (
            "COMMERCIAL"
            if score > 0.52
            else (
                "MIXED"
                if score > 0.18 or road.kind == "PRIMARY"
                else "RESIDENTIAL"
            )
        )
        probability = min(
            0.95,
            0.045 + score * 0.77 + (0.13 if road.kind == "PRIMARY" else 0.02),
        )
        shop = rng.random() < probability
        floors = (
            rng.choice((2, 3))
            if zone == "COMMERCIAL" and config.scale in ("CITY", "CAPITAL")
            else rng.choice((1, 2))
        )
        possible = [
            template for template in homes if template.config.floors == floors
        ]
        template = rng.choice(possible)
        width, depth = template.config.width, template.config.depth
        normal = (-tangent[1] * side, tangent[0] * side)
        heading = math.atan2(-normal[0], normal[1])
        setback = 1.8 if shop else rng.uniform(2.0, 3.0)
        distance = road.width / 2 + setback + depth / 2
        centre = (
            point[0] + normal[0] * distance,
            point[1] + normal[1] * distance,
        )
        corners = oriented_corners(centre, width, depth, heading, 0.8)
        diagonal = math.hypot(width, depth) / 2 + 2
        if not all(
            inside_polygon(corner, boundary)
            and boundary_distance(corner, boundary) > 2.0
            for corner in corners
        ):
            continue
        if any(
            math.dist(centre, market.centre[:2]) < market.radius + diagonal
            for market in markets
        ):
            continue
        if (
            castle
            and math.dist(centre, castle.centre[:2])
            < castle.radius + diagonal + 3
        ):
            continue
        if any(
            polygons_overlap(corners, buildings[index].corners)
            for index in occupied.query(centre, diagonal + 10)
        ):
            continue
        if any(
            polygons_overlap(
                corners, _street_rectangle(a, b, other.width + 0.7)
            )
            for index in streets.query(centre, diagonal + 5)
            for other, _, a, b in (segments[index],)
        ):
            continue
        if any(
            polygons_overlap(
                corners, _street_rectangle(*connectors[index].points, 1.4)
            )
            for index in accesses.query(centre, diagonal + 5)
        ):
            continue
        local_x, local_y = template.entrance
        entry = (
            centre[0]
            + local_x * math.cos(heading)
            - local_y * math.sin(heading),
            centre[1]
            + local_x * math.sin(heading)
            + local_y * math.cos(heading),
            point[2] - ROAD_LIFT + 0.30,
        )
        a, b = road.points[segment : segment + 2]
        _, t, street_xy = segment_projection(entry, a, b)
        street_z = a[2] + (b[2] - a[2]) * t
        street_point = (*street_xy, street_z)
        if (
            abs(entry[2] - street_z) / math.dist(entry[:2], street_xy)
            > config.max_road_grade
        ):
            continue
        path_polygon = _street_rectangle(street_point, entry, 1.25)
        if any(
            polygons_overlap(path_polygon, buildings[index].corners)
            for index in occupied.query(centre, diagonal + 10)
        ):
            continue
        level = point[2] - ROAD_LIFT
        if (
            max(
                abs(terrain_height(terrain, *corner) - level)
                for corner in corners
            )
            > 1.8
        ):
            continue
        business = "RESIDENCE"
        if shop:
            business = rng.choice(
                ("BAKERY", "TAILOR", "GROCER", "TAVERN", "SMITH")
            )
        identifier = f"building_{len(buildings):04d}"
        building = Building(
            identifier,
            template.id,
            (*centre, level),
            heading,
            width,
            depth,
            corners,
            entry,
            road.id,
            zone,
            business,
            score,
        )
        occupied.insert(
            len(buildings),
            (
                min(p[0] for p in corners),
                min(p[1] for p in corners),
                max(p[0] for p in corners),
                max(p[1] for p in corners),
            ),
        )
        buildings.append(building)
        access = Road(
            identifier + "_access",
            "ACCESS",
            ROAD_WIDTHS["ACCESS"],
            (street_point, entry),
        )
        accesses.insert(
            len(connectors),
            (
                min(street_point[0], entry[0]),
                min(street_point[1], entry[1]),
                max(street_point[0], entry[0]),
                max(street_point[1], entry[1]),
            ),
        )
        connectors.append(access)
        attachments[(road.id, segment)].append((t, street_point))
    # Preserve a small commercial pocket along residential alleys.
    if buildings and not any(
        item.business != "RESIDENCE" for item in buildings
    ):
        index = max(
            range(len(buildings)), key=lambda i: buildings[i].commercial_score
        )
        buildings[index] = replace(buildings[index], business="GROCER")
    alley_ids = {road.id for road in roads if road.kind == "ALLEY"}
    alley_buildings = [
        i for i, item in enumerate(buildings) if item.street_id in alley_ids
    ]
    if len(alley_buildings) >= 5 and not any(
        buildings[i].business != "RESIDENCE" for i in alley_buildings
    ):
        index = max(
            alley_buildings, key=lambda i: buildings[i].commercial_score
        )
        buildings[index] = replace(buildings[index], business="BAKERY")
    if site and site.style in SITE_BUSINESSES:
        # Put local trades on the streets closest to their feature.
        order = sorted(
            range(len(buildings)),
            key=lambda i: (
                buildings[i].business == "RESIDENCE",
                math.dist(buildings[i].position[:2], site.approach),
            ),
        )
        for index, business in zip(
            order, SITE_BUSINESSES[site.style], strict=False
        ):
            buildings[index] = replace(buildings[index], business=business)
    connected = []
    for road in roads:
        points = [road.points[0]]
        for i, end in enumerate(road.points[1:]):
            for _, anchor in sorted(attachments[(road.id, i)]):
                if math.dist(points[-1], anchor) > 1e-6:
                    points.append(anchor)
            if math.dist(points[-1], end) > 1e-6:
                points.append(end)
        connected.append(replace(road, points=tuple(points)))
    return tuple(buildings), connected + connectors, target


def navigation_graph(roads, buildings, gates, markets, castle):
    nodes, by_point, edges = [], {}, []

    def node(point):
        key = tuple(round(value, 4) for value in point)
        if key not in by_point:
            by_point[key] = len(nodes)
            nodes.append({"id": len(nodes), "position": tuple(point)})
        return by_point[key]

    for road in roads:
        for a, b in zip(road.points, road.points[1:], strict=False):
            edges.append(
                {
                    "a": node(a),
                    "b": node(b),
                    "width": road.width,
                    "length": math.dist(a, b),
                    "kind": road.kind,
                }
            )

    def nearest(point):
        return min(
            nodes,
            key=lambda value: math.dist(value["position"][:2], point[:2]),
        )["id"]

    pois = [
        {
            "id": item.id,
            "kind": "BUILDING_ENTRY",
            "node": nearest(item.entry),
            "business": item.business,
            "position": item.entry,
        }
        for item in buildings
    ]
    pois.extend(
        {
            "id": gate.id,
            "kind": "GATE",
            "node": nearest(gate.position),
            "position": gate.position,
        }
        for gate in gates
    )
    pois.extend(
        {
            "id": market.id,
            "kind": "MARKET",
            "node": nearest(market.centre),
            "position": market.centre,
        }
        for market in markets
    )
    if castle:
        pois.append(
            {
                "id": "keep_entry",
                "kind": "CASTLE_ENTRY",
                "node": nearest(castle.keep_entry),
                "position": castle.keep_entry,
            }
        )
        pois.append(
            {
                "id": "castle_gate",
                "kind": "CASTLE_GATE",
                "node": nearest(castle.gate.position),
                "position": castle.gate.position,
            }
        )
    if castle and castle.interior:
        inside = castle.interior.navigation
        offset = len(nodes)
        exterior_entry, exterior_gate = (
            nearest(castle.keep_entry),
            nearest(castle.gate.position),
        )
        for item in inside["nodes"]:
            nodes.append(
                {
                    **item,
                    "id": offset + item["id"],
                    "position": castle_point(
                        castle.centre, castle.keep_heading, item["position"]
                    ),
                }
            )
        for edge in inside["edges"]:
            edges.append(
                {
                    **edge,
                    "a": offset + edge["a"],
                    "b": offset + edge["b"],
                    "path": tuple(
                        castle_point(castle.centre, castle.keep_heading, p)
                        for p in edge["path"]
                    ),
                }
            )
        for outside, inside_id in (
            (exterior_entry, inside["entry_node"]),
            (exterior_gate, inside["gate_node"]),
        ):
            target = offset + inside_id
            edges.append(
                {
                    "a": outside,
                    "b": target,
                    "kind": "CASTLE_ACCESS",
                    "width": 1.2,
                    "length": math.dist(
                        nodes[outside]["position"], nodes[target]["position"]
                    ),
                    "path": (
                        nodes[outside]["position"],
                        nodes[target]["position"],
                    ),
                }
            )
        by_name = {n["name"]: n["id"] for n in inside["nodes"]}
        for room in castle.interior.rooms:
            pois.append(
                {
                    "id": room.id,
                    "kind": "CASTLE_ROOM",
                    "room_kind": room.kind,
                    "node": offset + by_name[room.id],
                    "position": castle_point(
                        castle.centre, castle.keep_heading, room.position
                    ),
                }
            )
    entrance = gates[0]
    outside = (
        entrance.position[0] + entrance.outward[0] * 16,
        entrance.position[1] + entrance.outward[1] * 16,
    )
    return {
        "nodes": nodes,
        "edges": edges,
        "points_of_interest": pois,
        "spawn_node": nearest(outside),
        "suggested_spawns": {
            "market": nearest(markets[0].centre),
            "main_gate": nearest(outside),
        },
        "agent_radius": 0.35,
        "agent_height": 1.7,
    }


def make_settlement(config, *, site=None):
    config.validate()
    rng = random.Random(config.seed)
    profile = PROFILES[config.scale]
    radius = config.effective_radius
    style = site.style if site else "INLAND"
    boundary, aspect = _boundary(config, rng, site)
    terrain = TerrainSpec(
        config.terrain_seed,
        radius,
        config.relief,
        aspect,
        ground=site.ground if site else None,
    )
    grid = config.road_grid
    market_xy = [
        (
            round(-radius * 0.06 / grid) * grid,
            round(-radius * 0.06 / grid) * grid,
        )
    ]
    for i in range(1, profile["markets"]):
        angle = -math.pi / 3 + (i - 1) * math.pi
        market_xy.append(
            (
                round(radius * 0.46 * math.cos(angle) / grid) * grid,
                round(radius * 0.46 * math.sin(angle) / grid) * grid,
            )
        )
    castle = None
    if _enabled(config.castle, profile["castle"]):
        castle, terrain = _castle(config, boundary, terrain, market_xy[0])
    markets = tuple(
        Market(
            f"market_{i}",
            (x, y, terrain_height(terrain, x, y)),
            (
                5
                if config.scale == "VILLAGE"
                else 8
                if config.scale == "TOWN"
                else 11
                if config.scale == "CITY"
                else 14
            )
            * (1 if i == 0 else 0.65),
        )
        for i, (x, y) in enumerate(market_xy)
    )
    terrain = replace(
        terrain,
        plazas=tuple((*m.centre[:2], m.radius, m.centre[2]) for m in markets),
    )
    gates = []
    phase = rng.uniform(0, 0.5)
    if site and site.approach:
        phase = -math.pi / 2
    for i in range(profile["gates"]):
        index = round(
            (i / profile["gates"] + phase / math.tau) * len(boundary)
        ) % len(boundary)
        x, y = boundary[index]
        a, b = (
            boundary[(index - 1) % len(boundary)],
            boundary[(index + 1) % len(boundary)],
        )
        tangent = (b[0] - a[0], b[1] - a[1])
        length = math.hypot(*tangent)
        outward = (tangent[1] / length, -tangent[0] / length)
        gates.append(
            Gate(
                f"gate_{i}",
                (x, y, terrain_height(terrain, x, y)),
                outward,
                7.5,
            )
        )
    planner = RoadPlanner(config, terrain, boundary, castle)
    core = markets[0].centre[:2]
    for i, gate in enumerate(gates):
        inner = (
            gate.position[0] - gate.outward[0] * 12,
            gate.position[1] - gate.outward[1] * 12,
        )
        path = planner.route(core, inner, 0)
        outside = (
            gate.position[0] + gate.outward[0] * 16,
            gate.position[1] + gate.outward[1] * 16,
        )
        if i == 0 and site and site.approach:
            planner.add_path((path[-1], gate.position[:2]), 0)
            planner.add_path(
                resample((gate.position[:2], site.approach), 3.0), 1
            )
        else:
            planner.add_path((path[-1], gate.position[:2], outside), 0)
    for market in markets[1:]:
        planner.route(core, market.centre[:2], 0)
    for fraction in profile["rings"]:
        anchors = []
        for i in range(profile["gates"] * 2):
            angle = i * math.tau / (profile["gates"] * 2) + phase
            index = round(angle / math.tau * len(boundary)) % len(boundary)
            point = tuple(value * fraction for value in boundary[index])
            anchors.append(planner.point(planner.nearest_allowed(point)))
        known = sorted({point for edge in planner.edges for point in edge})
        nearest = min(known, key=lambda point: math.dist(point, anchors[0]))
        planner.route(nearest, anchors[0], 1)
        for a, b in zip(anchors, anchors[1:] + anchors[:1], strict=True):
            planner.route(a, b, 1)
    for _ in range(profile["alleys"]):
        known = sorted(
            {
                point
                for edge in planner.edges
                for point in edge
                if inside_polygon(point, boundary)
                and math.hypot(*point) < radius * 0.9
            }
        )
        first = rng.choice(known)
        choices = [
            point
            for point in known
            if 14 < math.dist(point, first) < radius * 0.55
        ]
        if choices:
            planner.route(first, rng.choice(choices), 2, optional=True)
    # Grow short streets away from existing loops to add frontage.
    for index in range(
        3 if config.scale == "VILLAGE" else profile["alleys"] // 3
    ):
        angle = phase + index * 2.399963 + rng.uniform(-0.25, 0.25)
        target = (
            radius * rng.uniform(0.45, 0.78) * math.cos(angle),
            radius * rng.uniform(0.45, 0.78) * math.sin(angle),
        )
        target = planner.point(planner.nearest_allowed(target))
        known = sorted(
            {
                point
                for edge in planner.edges
                for point in edge
                if inside_polygon(point, boundary)
            }
        )
        first = min(known, key=lambda point: math.dist(point, target))
        planner.route(first, target, 2, optional=True)
    if castle:
        gate = castle.gate
        approach = (
            gate.position[0] + gate.outward[0] * 7,
            gate.position[1] + gate.outward[1] * 7,
        )
        path = planner.route(core, approach, 0)
        planner.add_path(
            (path[-1], gate.position[:2], castle.keep_approach), 1
        )
    roads = _road_chains(planner)
    if castle:
        start = (
            *castle.keep_approach,
            terrain_height(terrain, *castle.keep_approach) + ROAD_LIFT,
        )
        roads.append(
            Road("keep_access", "ACCESS", 2.0, (start, castle.keep_entry))
        )
    roads = conform_junctions(roads, terrain, config.max_road_grade)
    templates = _templates(config, style)
    buildings, roads, target = _buildings(
        config, boundary, terrain, roads, markets, castle, templates, site
    )
    warnings = []
    if len(buildings) < target:
        warnings.append(
            f"Placed {len(buildings)} of {target} requested buildings; "
            "remaining land reserved"
        )
    navigation = navigation_graph(roads, buildings, gates, markets, castle)
    wall_height = profile["wall_height"]
    if config.art_style == "REALISTIC":
        wall_height *= {
            "VILLAGE": 1.15,
            "TOWN": 1.25,
            "CITY": 1.40,
            "CAPITAL": 1.52,
        }[config.scale]
    plan = SettlementPlan(
        config,
        terrain,
        boundary,
        tuple(gates),
        markets,
        tuple(roads),
        buildings,
        templates,
        castle,
        _enabled(config.walls, profile["walls"]),
        wall_height,
        navigation,
        tuple(warnings),
        site_style=style,
    )
    civic = make_civic_assets(plan)
    return replace(
        plan,
        civic_assets=civic,
        navigation=civic_navigation(plan.navigation, civic),
    )
