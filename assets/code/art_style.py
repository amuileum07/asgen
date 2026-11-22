"""Shared appearance choices for procedural Blender assets."""

STYLE_ITEMS = (
    ("CARTOON", "카툰풍", "단계 명암과 밝은 유리 반사"),
    ("REALISTIC", "실사풍", "물리 기반 표면 질감과 투과 유리"),
)
ART_STYLES = tuple(item[0] for item in STYLE_ITEMS)


def validate_art_style(value):
    if value not in ART_STYLES:
        raise ValueError(f"art_style must be one of {ART_STYLES}")
    return value


def preview_engine(art_style):
    return "BLENDER_EEVEE" if art_style == "CARTOON" else "CYCLES"
