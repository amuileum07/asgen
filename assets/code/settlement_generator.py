"""Generate medieval villages, towns, cities and capitals in Blender."""

import argparse
import html
import importlib
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if __name__ == "__main__":
    for name in (
        "house_rules",
        "solid_geometry",
        "interior_rules",
        "interior_blender",
        "house_generator",
        "castle_roof_rules",
        "castle_rules",
        "terrain_rules",
        "castle_geometry",
        "transport_rules",
        "castle_interior_rules",
        "civic_rules",
        "settlement_rules",
        "fortification_blender",
        "castle_blender",
        "castle_interior_blender",
        "game_materials",
        "civic_blender",
        "surface_quality",
        "surface_blender",
        "game_asset_format",
        "ogre_export",
        "settlement_blender",
    ):
        if name in sys.modules:
            importlib.reload(sys.modules[name])

from settlement_rules import PROFILES, SettlementConfig, make_settlement  # noqa: E402

try:
    import bpy
except ModuleNotFoundError:
    bpy = None
if bpy is not None:
    import settlement_blender as builder

SETTINGS_KEY = "settlement_settings"


def layout_svg(plan):
    """Export a district map using the actual road geometry."""
    locations = list(plan.boundary) + [
        p[:2] for r in plan.roads for p in r.points
    ]
    x1, x2 = min(p[0] for p in locations) - 8, max(p[0] for p in locations) + 8
    y1, y2 = (
        -max(p[1] for p in locations) - 8,
        -min(p[1] for p in locations) + 8,
    )
    width, height = x2 - x1, y2 - y1
    pieces = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{x1} {y1} {width} {height}">',
        f'<rect x="{x1}" y="{y1}" width="{width}" height="{height}" '
        'fill="#edf0dd"/>',
        '<g transform="scale(1,-1)">',
    ]

    def points(values):
        return " ".join(f"{p[0]:.3f},{p[1]:.3f}" for p in values)

    pieces.append(
        f'<polygon points="{points(plan.boundary)}" fill="#d8dfc0" '
        'stroke="#626d59" stroke-width="1"/>'
    )
    for market in plan.markets:
        x, y, _ = market.centre
        pieces.append(
            f'<circle cx="{x}" cy="{y}" r="{market.radius}" fill="#dbca9e"/>'
        )
    for road in plan.roads:
        pieces.append(
            f'<polyline points="{points(road.points)}" fill="none" '
            f'stroke="#b49c75" stroke-width="{road.width}" '
            'stroke-linejoin="round"/>'
        )
    colors = {
        "COMMERCIAL": "#bf816c",
        "MIXED": "#ceb37b",
        "RESIDENTIAL": "#8da99e",
    }
    for building in plan.buildings:
        color = colors[building.zone]
        title = html.escape(building.id + ": " + building.business)
        pieces.append(
            f'<polygon points="{points(building.corners)}" fill="{color}" '
            'stroke="#665c4b" stroke-width="0.35">'
            f"<title>{title}</title></polygon>"
        )
    if plan.castle:
        pieces.append(
            f'<polygon points="{points(plan.castle.outline)}" fill="#acafb6" '
            'stroke="#626775" stroke-width="2"/>'
        )
    pieces.extend(
        (
            "</g>",
            '<text x="0" y="0" font-size="3" fill="#3a473d">MARKET</text>',
            "</svg>",
        )
    )
    return "\n".join(pieces)


def _config(settings):
    return SettlementConfig(
        **{
            name: getattr(settings, name)
            for name in SettlementConfig.__dataclass_fields__
        }
    )


UI_CLASSES = ()
if bpy is not None:

    class SETTLEMENT_Settings(bpy.types.PropertyGroup):
        target: bpy.props.PointerProperty(
            name="현재 도시",
            type=bpy.types.Collection,
            poll=lambda self, value: builder.root_for(value) is not None,
        )
        scale: bpy.props.EnumProperty(
            name="규모",
            default="TOWN",
            items=[
                ("VILLAGE", "작은 마을", "시골 길과 작은 장터"),
                ("TOWN", "성벽 마을", "장터와 주거 골목"),
                ("CITY", "도시", "복수 상권과 성"),
                ("CAPITAL", "수도", "다중 중심지와 큰 성곽"),
            ],
        )
        seed: bpy.props.IntProperty(
            name="도시 Seed", default=42, min=0, max=2_000_000_000
        )
        terrain_seed: bpy.props.IntProperty(
            name="지형 Seed", default=84, min=0, max=2_000_000_000
        )
        radius: bpy.props.FloatProperty(
            name="기준 크기 (0=자동)", default=0, min=0, max=350
        )
        density: bpy.props.FloatProperty(
            name="건물 밀도", default=0.9, min=0.15, max=1
        )
        relief: bpy.props.FloatProperty(
            name="지형 기복 (m)", default=8, min=0, max=24
        )
        irregularity: bpy.props.FloatProperty(
            name="경계 굴곡", default=0.20, min=0.04, max=0.32
        )
        walls: bpy.props.EnumProperty(
            name="성벽",
            default="AUTO",
            items=[
                ("AUTO", "규모별 자동", "마을 규모에 따라 결정"),
                ("ON", "생성", "성벽을 생성"),
                ("OFF", "생략", "성벽을 생략"),
            ],
        )
        castle: bpy.props.EnumProperty(
            name="성",
            default="AUTO",
            items=[
                ("AUTO", "규모별 자동", "도시와 수도에 생성"),
                ("ON", "생성", "성을 생성"),
                ("OFF", "생략", "성을 생략"),
            ],
        )
        castle_site: bpy.props.EnumProperty(
            name="성 입지",
            default="HILLTOP",
            items=[
                ("HILLTOP", "고지대 암반 성", "높은 언덕과 암반 위의 성"),
                ("WALLED", "평지 요새", "낮은 지형에 둘레 성벽을 갖춘 성"),
            ],
        )
        castle_interior: bpy.props.BoolProperty(
            name="성 실내 생성", default=True
        )
        castle_furnish: bpy.props.BoolProperty(
            name="성 가구 배치", default=True
        )
        castle_floor: bpy.props.IntProperty(
            name="성 층 (0=지상)", default=0, min=0, max=12
        )
        ogre_directory: bpy.props.StringProperty(
            name="OGRE 출력 폴더", subtype="DIR_PATH", default="//ogre_assets"
        )
        max_buildings: bpy.props.IntProperty(
            name="건물 상한 (0=자동)", default=0, min=0, max=1200
        )
        road_grid: bpy.props.FloatProperty(
            name="도로 탐색 간격", default=4, min=2.5, max=5
        )
        max_road_grade: bpy.props.FloatProperty(
            name="최대 도로 경사", default=0.20, min=0.08, max=0.30
        )
        terrain_step: bpy.props.FloatProperty(
            name="지형 메시 간격", default=2.5, min=1.5, max=5
        )
        detail: bpy.props.EnumProperty(
            name="집 세부 표현",
            default="LOW",
            items=[
                ("LOW", "가벼운 외관", "공유 원형과 단순 지붕"),
                ("HIGH", "상세 외관", "입체 타일과 덧문"),
            ],
        )
        trees: bpy.props.BoolProperty(name="나무 생성", default=True)
        grass: bpy.props.BoolProperty(name="잔디 덤불 생성", default=True)
        grass_density: bpy.props.FloatProperty(
            name="잔디 밀도", default=0.55, min=0, max=1.5
        )
        civic: bpy.props.BoolProperty(name="우물·분수·가로등", default=True)

    class SETTLEMENT_OT_generate(bpy.types.Operator):
        bl_idname = "settlement.generate"
        bl_label = "도시 생성 / 갱신"
        bl_options = {"REGISTER", "UNDO"}
        new_seed: bpy.props.BoolProperty(default=False)

        def execute(self, context):
            settings = getattr(context.scene, SETTINGS_KEY)
            previous_seed = settings.seed
            if self.new_seed:
                settings.seed = (settings.seed + 1) % 2_000_000_001
            try:
                collection, root, plan = builder.build_settlement(
                    _config(settings),
                    replace_collection=settings.target,
                    location=context.scene.cursor.location,
                )
            except Exception as error:
                settings.seed = previous_seed
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}
            settings.target = collection
            builder.houses._select_root(root)
            self.report({"INFO"}, f"생성 완료: 건물 {len(plan.buildings)}채")
            return {"FINISHED"}

    class SETTLEMENT_OT_preview(bpy.types.Operator):
        bl_idname = "settlement.preview"
        bl_label = "도시 미리보기 카메라 / 조명"
        bl_options = {"REGISTER", "UNDO"}
        castle_focus: bpy.props.BoolProperty(default=False)

        def execute(self, context):
            settings = getattr(context.scene, SETTINGS_KEY)
            root = builder.root_for(settings.target)
            if root is None:
                self.report({"ERROR"}, "먼저 도시를 생성하세요")
                return {"CANCELLED"}
            config = SettlementConfig(**json.loads(root["config_json"]))
            preview = (
                builder.preview_castle
                if self.castle_focus
                else builder.preview_stage
            )
            try:
                preview(make_settlement(config), settings.target, root)
            except ValueError as error:
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}
            return {"FINISHED"}

    class SETTLEMENT_OT_materialize(bpy.types.Operator):
        bl_idname = "settlement.materialize"
        bl_label = "선택 건물을 실내가 있는 집으로 전환"
        bl_options = {"REGISTER", "UNDO"}

        def execute(self, context):
            settings = getattr(context.scene, SETTINGS_KEY)
            root = builder.root_for(settings.target)
            if root is None or context.active_object is None:
                self.report({"ERROR"}, "도시의 집 오브젝트를 선택하세요")
                return {"CANCELLED"}
            try:
                collection, house_root = builder.materialize_building(
                    context.active_object, root, settings.target
                )
                houses = builder.houses
                houses.register()
                house_settings = getattr(context.scene, houses.SETTINGS_KEY)
                config = houses.HouseConfig(
                    **json.loads(house_root["config_json"])
                )
                for name, value in config.as_dict().items():
                    setattr(house_settings, name, value)
                house_settings.target = collection
                houses._select_root(house_root)
            except Exception as error:
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}
            return {"FINISHED"}

    class SETTLEMENT_OT_castle_floor(bpy.types.Operator):
        bl_idname = "settlement.castle_floor"
        bl_label = "성 내부 층 보기"
        bl_options = {"REGISTER", "UNDO"}
        rampart: bpy.props.BoolProperty(default=False)
        exterior: bpy.props.BoolProperty(default=False)

        def execute(self, context):
            settings = getattr(context.scene, SETTINGS_KEY)
            root = builder.root_for(settings.target)
            if root is None:
                self.report({"ERROR"}, "먼저 성이 있는 도시를 생성하세요")
                return {"CANCELLED"}
            try:
                plan = make_settlement(
                    SettlementConfig(**json.loads(root["config_json"]))
                )
                if self.exterior:
                    builder.preview_castle(plan, settings.target, root)
                else:
                    level = (
                        "rampart"
                        if self.rampart
                        else f"core_{settings.castle_floor}"
                    )
                    builder.preview_castle_level(
                        plan, settings.target, root, level
                    )
            except ValueError as error:
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}
            return {"FINISHED"}

    class SETTLEMENT_OT_ogre(bpy.types.Operator):
        bl_idname = "settlement.export_ogre"
        bl_label = "OGRE 게임 에셋 내보내기"

        def execute(self, context):
            settings = getattr(context.scene, SETTINGS_KEY)
            root = builder.root_for(settings.target)
            if root is None:
                self.report({"ERROR"}, "먼저 도시를 생성하세요")
                return {"CANCELLED"}
            from ogre_export import export_settlement

            try:
                result = export_settlement(
                    settings.target,
                    root,
                    bpy.path.abspath(settings.ogre_directory),
                )
            except Exception as error:
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}
            count = result["statistics"]["unique_meshes"]
            self.report({"INFO"}, f"OGRE 에셋 저장: {count}개 메시")
            return {"FINISHED"}

    class SETTLEMENT_PT_panel(bpy.types.Panel):
        bl_idname = "SETTLEMENT_PT_generator"
        bl_label = "Medieval Settlement"
        bl_space_type, bl_region_type, bl_category = (
            "VIEW_3D",
            "UI",
            "Settlement",
        )

        def draw(self, context):
            layout = self.layout
            settings = getattr(context.scene, SETTINGS_KEY)
            for name in (
                "target",
                "scale",
                "seed",
                "terrain_seed",
                "radius",
                "density",
                "relief",
                "irregularity",
                "walls",
                "castle",
                "castle_site",
                "castle_interior",
                "castle_furnish",
                "max_buildings",
                "detail",
                "trees",
                "grass",
                "grass_density",
                "civic",
                "terrain_step",
                "road_grid",
                "max_road_grade",
            ):
                layout.prop(settings, name)
            layout.operator("settlement.generate")
            layout.operator(
                "settlement.generate", text="새 도시 변형"
            ).new_seed = True
            layout.operator("settlement.preview")
            layout.operator(
                "settlement.preview", text="성 확대 미리보기"
            ).castle_focus = True
            layout.operator("settlement.materialize")
            layout.prop(settings, "castle_floor")
            layout.operator("settlement.castle_floor")
            layout.operator(
                "settlement.castle_floor", text="성벽 통로 / 문루 보기"
            ).rampart = True
            layout.operator(
                "settlement.castle_floor", text="성 외관 복원"
            ).exterior = True
            layout.prop(settings, "ogre_directory")
            layout.operator("settlement.export_ogre")

    UI_CLASSES = (
        SETTLEMENT_Settings,
        SETTLEMENT_OT_generate,
        SETTLEMENT_OT_preview,
        SETTLEMENT_OT_materialize,
        SETTLEMENT_OT_castle_floor,
        SETTLEMENT_OT_ogre,
        SETTLEMENT_PT_panel,
    )


def unregister():
    if hasattr(bpy.types.Scene, SETTINGS_KEY):
        delattr(bpy.types.Scene, SETTINGS_KEY)
    classes = bpy.app.driver_namespace.pop("_settlement_classes", ())
    for cls in reversed(classes or UI_CLASSES):
        registered = (
            cls
            if "bl_rna" in cls.__dict__
            else cls.__bases__[0].bl_rna_get_subclass_py(cls.__name__, None)
        )
        if registered:
            bpy.utils.unregister_class(registered)


def register():
    unregister()
    for cls in UI_CLASSES:
        bpy.utils.register_class(cls)
    setattr(
        bpy.types.Scene,
        SETTINGS_KEY,
        bpy.props.PointerProperty(type=SETTLEMENT_Settings),
    )
    bpy.app.driver_namespace["_settlement_classes"] = UI_CLASSES


def _arguments(argv):
    parser = argparse.ArgumentParser(
        description="Procedural medieval settlements"
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--scale", choices=tuple(PROFILES))
    for name in ("seed", "terrain_seed", "max_buildings"):
        parser.add_argument("--" + name.replace("_", "-"), type=int)
    for name in (
        "radius",
        "density",
        "relief",
        "irregularity",
        "terrain_step",
        "max_road_grade",
        "grass_density",
    ):
        parser.add_argument("--" + name.replace("_", "-"), type=float)
    parser.add_argument("--walls", choices=("AUTO", "ON", "OFF"))
    parser.add_argument("--castle", choices=("AUTO", "ON", "OFF"))
    parser.add_argument("--castle-site", choices=("HILLTOP", "WALLED"))
    for name in ("castle_interior", "castle_furnish"):
        parser.add_argument(
            "--" + name.replace("_", "-"),
            action=argparse.BooleanOptionalAction,
            default=None,
        )
    parser.add_argument("--detail", choices=("LOW", "HIGH"))
    parser.add_argument(
        "--trees", action=argparse.BooleanOptionalAction, default=None
    )
    for flag in ("grass", "civic"):
        parser.add_argument(
            "--" + flag, action=argparse.BooleanOptionalAction, default=None
        )
    for name in ("output", "render", "layout_output", "map"):
        parser.add_argument("--" + name.replace("_", "-"), type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--castle-preview", action="store_true")
    parser.add_argument("--castle-floor", type=int)
    parser.add_argument("--ogre-output", type=Path)
    return parser.parse_args(argv)


def main(argv=None):
    if argv is None:
        argv = (
            sys.argv[sys.argv.index("--") + 1 :]
            if "--" in sys.argv
            else []
            if bpy is not None
            else sys.argv[1:]
        )
    args = _arguments(argv)
    values = (
        json.loads(args.config.read_text(encoding="utf-8-sig"))
        if args.config
        else {}
    )
    for name in SettlementConfig.__dataclass_fields__:
        value = getattr(args, name, None)
        if value is not None:
            values[name] = value
    config = SettlementConfig(**values).validate()
    if bpy is not None:
        register()
        settings = getattr(bpy.context.scene, SETTINGS_KEY)
        if not argv and not bpy.app.background:
            config = _config(settings)
        else:
            for name in SettlementConfig.__dataclass_fields__:
                setattr(settings, name, getattr(config, name))
    if args.dry_run:
        print(json.dumps(make_settlement(config).as_dict(), indent=2))
        return
    for path, extension in (
        (args.output, ".blend"),
        (args.render, ".png"),
        (args.layout_output, ".json"),
        (args.map, ".svg"),
    ):
        if path and (
            path.suffix.lower() != extension
            or path.exists()
            and not args.force
        ):
            raise ValueError(f"Use a new {extension} path, or --force: {path}")
    if bpy is None:
        if args.output or args.render or args.ogre_output:
            raise RuntimeError("Blender is required to build 3D geometry")
        plan = make_settlement(config)
    else:
        collection, root, plan = builder.build_settlement(
            config, replace_collection=settings.target
        )
        settings.target = collection
        builder.houses._select_root(root)
        if args.output or args.render:
            preview = (
                builder.preview_castle
                if args.castle_preview
                else builder.preview_stage
            )
            preview(plan, collection, root)
            if args.castle_floor is not None:
                settings.castle_floor = args.castle_floor
                builder.preview_castle_level(
                    plan, collection, root, f"core_{args.castle_floor}"
                )
    for path, content in (
        (args.layout_output, json.dumps(plan.as_dict(), indent=2)),
        (args.map, layout_svg(plan)),
    ):
        if path:
            path.resolve().parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    if args.ogre_output:
        if bpy is None:
            raise RuntimeError("Blender is required for OGRE geometry export")
        from ogre_export import export_settlement

        export_settlement(collection, root, args.ogre_output)
    if args.render:
        args.render.resolve().parent.mkdir(parents=True, exist_ok=True)
        bpy.context.scene.render.filepath = str(args.render.resolve())
    if args.output:
        args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()))
    if args.render:
        bpy.ops.render.render(write_still=True)
    shops = sum(item.business != "RESIDENCE" for item in plan.buildings)
    print(
        f"{config.scale}: {len(plan.buildings)} buildings, {shops} shops, "
        f"{len(plan.navigation['nodes'])} navigation nodes"
    )
    for warning in plan.warnings:
        print("NOTE:", warning)


if __name__ == "__main__":
    main()
