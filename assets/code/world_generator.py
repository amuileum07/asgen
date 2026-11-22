"""Build a game world in Blender or export the site plan."""

import argparse
import html
import json
import sys
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

SCRIPT = Path(__file__).resolve()
if str(SCRIPT.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT.parent))

from art_style import ART_STYLES, STYLE_ITEMS  # noqa: E402
from world_rules import WorldConfig, make_world  # noqa: E402

try:
    import bpy
except ModuleNotFoundError:
    bpy = None

PRESET = SCRIPT.with_name("presets") / "world_example.json"
SETTINGS = "procedural_world_settings"
PROFILE_COLOURS = {
    "HARBOR": "#346b8b",
    "MOUNTAIN": "#83504c",
    "LAKESIDE": "#396c5d",
    "RIVERSIDE": "#775988",
    "INLAND": "#8c653f",
}


def layout_svg(plan):
    width, height = plan.config.size
    left, bottom = -width / 2, -height / 2
    n, m = plan.grid.shape
    colours = (
        "#c5d3a7",
        "#b3c695",
        "#9fb485",
        "#9dad87",
        "#a5ae97",
        "#b7bcad",
        "#cdd2c9",
        "#e9eee9",
    )
    paths = defaultdict(list)
    for j in range(m):
        for i in range(n):
            x, y = plan.grid.xy(i, j)
            xx, yy = plan.grid.xy(i + 1, j + 1)
            mx, my = (x + xx) / 2, (y + yy) / 2
            water = plan.terrain.wet(mx, my)
            level = plan.terrain.height(mx, my)
            band = min(len(colours) - 1, max(0, int(level / 28)))
            colour = "#78afbf" if water else colours[band]
            paths[colour].append(
                f"M{x:g},{-yy:g}h{xx - x:g}v{yy - y:g}h{x - xx:g}z"
            )
    pieces = [
        '<svg xmlns="http://www.w3.org/2000/svg" role="img" '
        f'viewBox="{left:g} {bottom:g} {width:g} {height:g}">',
        "<title>Procedural world and settlement sites</title>",
    ]
    for colour, path in sorted(paths.items()):
        pieces.append(f'<path fill="{colour}" d="{"".join(path)}"/>')
    text_size = max(width, height) / 67
    for site in plan.sites:
        x, y = site.centre
        colour = PROFILE_COLOURS[site.profile]
        boundary = " ".join(
            f"{x + a:.3f},{-y - b:.3f}" for a, b in site.settlement.boundary
        )
        pieces.append(
            f'<polygon points="{boundary}" fill="{colour}" fill-opacity="0.3" '
            f'stroke="{colour}" stroke-width="1.7"/>'
        )
        for road in site.settlement.roads:
            if road.kind not in ("PRIMARY", "SECONDARY"):
                continue
            points = " ".join(
                f"{a + x:.3f},{-b - y:.3f}" for a, b, _ in road.points
            )
            pieces.append(
                f'<polyline points="{points}" fill="none" stroke="#fffcf0" '
                f'stroke-width="{road.width * 0.63:.1f}"/>'
            )
        if site.deck_path:
            points = " ".join(
                f"{a:.3f},{-b:.3f}" for a, b, _ in site.deck_path
            )
            pieces.append(
                f'<polyline points="{points}" fill="none" stroke="{colour}" '
                'stroke-width="4.2"/>'
            )
        name = html.escape(site.id.replace("_", " ").title())
        pieces.append(
            f'<text x="{x:.3f}" y="{-y - text_size * 0.65:.3f}" '
            f'font-family="sans-serif" font-size="{text_size:.1f}" '
            'font-weight="bold" '
            f'text-anchor="middle" paint-order="stroke" stroke="#fcfaec" '
            f'stroke-width="{text_size * 0.15:.2f}" fill="{colour}">'
            f"{name}<title>{site.profile}</title></text>"
        )
    pieces.append("</svg>")
    return "\n".join(pieces)


def _read_config(path):
    values = json.loads(path.read_text(encoding="utf-8-sig"))
    return WorldConfig.from_dict(values)


def _world_root(collection):
    if collection:
        return next(
            (o for o in collection.objects if o.get("is_world_root")), None
        )
    return None


UI_CLASSES = ()
if bpy is not None:
    import world_blender as builder
    from ogre_export import export_settlement

    class WORLDMAP_Settings(bpy.types.PropertyGroup):
        art_style: bpy.props.EnumProperty(
            name="표현 스타일",
            items=(("CONFIG", "JSON 설정", "기본값은 카툰풍"), *STYLE_ITEMS),
            default="CONFIG",
        )
        config: bpy.props.StringProperty(
            name="월드 설정 JSON", subtype="FILE_PATH", default=str(PRESET)
        )
        target: bpy.props.PointerProperty(
            name="월드",
            type=bpy.types.Collection,
            poll=lambda self, value: _world_root(value) is not None,
        )
        focus: bpy.props.StringProperty(name="미리 볼 정착지 ID", default="")
        meadow: bpy.props.BoolProperty(
            name="초지 눈높이 카메라", default=False
        )
        output: bpy.props.StringProperty(name="OGRE 폴더", subtype="DIR_PATH")

    class WORLDMAP_OT_generate(bpy.types.Operator):
        bl_idname = "worldmap.generate"
        bl_label = "새 월드 생성"
        bl_options = {"REGISTER", "UNDO"}

        def execute(self, context):
            settings = getattr(context.scene, SETTINGS)
            try:
                config = _read_config(Path(bpy.path.abspath(settings.config)))
                if settings.art_style != "CONFIG":
                    config = replace(config, art_style=settings.art_style)
                collection, root, plan = builder.build_world(
                    make_world(config)
                )
                settings.target = collection
                builder.preview_world(collection, root)
            except (OSError, ValueError, TypeError) as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            self.report({"INFO"}, f"정착지 {len(plan.sites)}곳 생성")
            return {"FINISHED"}

    class WORLDMAP_OT_preview(bpy.types.Operator):
        bl_idname = "worldmap.preview"
        bl_label = "지도 / 정착지 미리보기"

        def execute(self, context):
            settings = getattr(context.scene, SETTINGS)
            root = _world_root(settings.target)
            if root is None:
                self.report({"ERROR"}, "월드 컬렉션을 선택하세요.")
                return {"CANCELLED"}
            try:
                builder.preview_world(
                    settings.target,
                    root,
                    settings.focus or None,
                    meadow=settings.meadow,
                )
            except ValueError as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            return {"FINISHED"}

    class WORLDMAP_OT_export(bpy.types.Operator):
        bl_idname = "worldmap.export"
        bl_label = "OGRE 월드 출력"

        def execute(self, context):
            settings = getattr(context.scene, SETTINGS)
            root = _world_root(settings.target)
            if root is None or not settings.output:
                self.report({"ERROR"}, "월드와 출력 폴더를 선택하세요.")
                return {"CANCELLED"}
            try:
                export_settlement(
                    settings.target, root, bpy.path.abspath(settings.output)
                )
            except (OSError, ValueError) as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            return {"FINISHED"}

    class WORLDMAP_PT_panel(bpy.types.Panel):
        bl_label = "게임 월드"
        bl_idname = "WORLDMAP_PT_panel"
        bl_space_type = "VIEW_3D"
        bl_region_type = "UI"
        bl_category = "World Map"

        def draw(self, context):
            settings = getattr(context.scene, SETTINGS)
            layout = self.layout
            layout.prop(settings, "config")
            layout.prop(settings, "art_style")
            layout.operator("worldmap.generate")
            layout.prop(settings, "target")
            layout.prop(settings, "focus")
            layout.prop(settings, "meadow")
            layout.operator("worldmap.preview")
            layout.prop(settings, "output")
            layout.operator("worldmap.export")

    UI_CLASSES = (
        WORLDMAP_Settings,
        WORLDMAP_OT_generate,
        WORLDMAP_OT_preview,
        WORLDMAP_OT_export,
        WORLDMAP_PT_panel,
    )


def register():
    if hasattr(bpy.types.Scene, SETTINGS):
        delattr(bpy.types.Scene, SETTINGS)
        for cls in reversed(UI_CLASSES):
            existing = getattr(bpy.types, cls.__name__, None)
            if existing is not None:
                bpy.utils.unregister_class(existing)
    for cls in UI_CLASSES:
        bpy.utils.register_class(cls)
    setattr(
        bpy.types.Scene,
        SETTINGS,
        bpy.props.PointerProperty(type=UI_CLASSES[0]),
    )


def main(argv=None):
    if argv is None:
        if bpy is None:
            argv = sys.argv[1:]
        else:
            argv = (
                sys.argv[sys.argv.index("--") + 1 :]
                if "--" in sys.argv
                else []
            )
            if not argv and not bpy.app.background:
                register()
                return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PRESET)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--focus", help="Frame a settlement by its ID")
    parser.add_argument("--tile", action="append", default=[], metavar="X,Y")
    parser.add_argument("--atlas-index-only", action="store_true")
    parser.add_argument("--all-sites", action="store_true")
    style = parser.add_mutually_exclusive_group()
    style.add_argument("--art-style", type=str.upper, choices=ART_STYLES)
    style.add_argument(
        "--toon", dest="art_style", action="store_const", const="CARTOON"
    )
    parser.add_argument(
        "--meadow-view",
        action="store_true",
        help="Frame the meadow at eye level",
    )
    for name in ("output", "render", "layout-output", "map", "ogre-output"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    files = (
        (args.output, ".blend"),
        (args.render, ".png"),
        (args.layout_output, ".json"),
        (args.map, ".svg"),
    )
    for path, suffix in files:
        if path and (
            path.suffix.lower() != suffix or path.exists() and not args.force
        ):
            parser.error(f"Use a new {suffix} path, or --force: {path}")
    blueprint = json.loads(args.config.read_text(encoding="utf-8-sig"))
    if args.art_style:
        blueprint["art_style"] = args.art_style
    if "blueprint_version" in blueprint:
        from atlas_generator import run_blueprint

        return run_blueprint(
            args, blueprint, bpy, base_dir=args.config.resolve().parent
        )
    if args.tile or args.atlas_index_only or args.all_sites:
        parser.error("Atlas options require a version 2 blueprint")
    model = bool(args.output or args.render or args.ogre_output)
    if model and bpy is None:
        parser.error("Blender is required for model, render and OGRE output")
    config = WorldConfig.from_dict(blueprint)
    if args.seed is not None:
        config = replace(config, seed=args.seed)
    if args.focus and args.focus not in {s.id for s in config.settlements}:
        parser.error(f"Unknown focus site: {args.focus}")
    print("Planning world terrain and sites", flush=True)
    plan = make_world(config)
    if model:
        print("Building terrain, settlements and vegetation", flush=True)
        collection, root, plan = builder.build_world(plan)
        if args.output or args.render:
            builder.preview_world(
                collection, root, args.focus, meadow=args.meadow_view
            )
        if args.ogre_output:
            print("Exporting OGRE terrain and collision", flush=True)
            export_settlement(collection, root, args.ogre_output)
    if args.layout_output:
        args.layout_output.resolve().parent.mkdir(parents=True, exist_ok=True)
        args.layout_output.write_text(
            json.dumps(plan.as_dict(), indent=2), encoding="utf-8"
        )
    if args.map:
        args.map.resolve().parent.mkdir(parents=True, exist_ok=True)
        args.map.write_text(layout_svg(plan), encoding="utf-8")
    if args.render:
        args.render.resolve().parent.mkdir(parents=True, exist_ok=True)
        bpy.context.scene.render.filepath = str(args.render.resolve())
    if args.output:
        args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()))
    if args.render:
        bpy.ops.render.render(write_still=True)
    for site in plan.sites:
        count = len(site.settlement.buildings)
        print(
            f"{site.id}: {site.profile}, {count} buildings",
            flush=True,
        )


if __name__ == "__main__":
    main()
