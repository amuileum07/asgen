"""Shared appearance choices for procedural Blender assets."""

STYLE_ITEMS = (
    ("CARTOON", "카툰풍", "단계 명암과 밝은 유리 반사"),
    ("REALISTIC", "실사풍", "물리 기반 표면 질감과 투과 유리"),
)
ART_STYLES = tuple(item[0] for item in STYLE_ITEMS)
SEASON_ITEMS = (
    ("SPRING", "봄", "새잎과 벚꽃·개화 수목"),
    ("SUMMER", "여름", "짙은 녹음과 푸른 초원"),
    ("AUTUMN", "가을", "붉은·주황·황금 단풍과 낙엽수"),
    ("WINTER", "겨울", "잎이 진 활엽수와 서리 낀 침엽수"),
)
SEASONS = tuple(item[0] for item in SEASON_ITEMS)


def validate_art_style(value):
    if value not in ART_STYLES:
        raise ValueError(f"art_style must be one of {ART_STYLES}")
    return value


def validate_season(value):
    if value not in SEASONS:
        raise ValueError(f"season must be one of {SEASONS}")
    return value


def preview_engine(art_style):
    return "BLENDER_EEVEE" if art_style == "CARTOON" else "CYCLES"
