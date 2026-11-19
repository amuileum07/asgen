# 커스텀 아틀라스 월드 생성기

`world_generator.py`에 `blueprint_version: 2` JSON을 넘기면 256m 타일 기반의 대규모 오픈월드를 절차적으로 생성합니다. 지형(해안·능선·봉우리·고원·분지·사구), 8종 바이옴 기후와 월별 강수·배수, 수계(바다·강·협곡·빙식호·산정호·우각호·종착호·샘), 왕국·여행 권역, 정착지(수도·도시·마을과 공공시설·성), 던전(카타콤·보고), 도로망을 모두 JSON으로 선언합니다.

예제 파일은 [presets/atlas_example.json](presets/atlas_example.json)입니다.

## 블루프린트 구조

`centre_uv`, `near_uv`, `axis_uv`, `spine_uv`의 좌표는 `0–1` 정규화 범위이며 `(0, 0)`이 남서쪽, `(1, 1)`이 북동쪽입니다. `size_m`은 2,048–32,768m 사이의 256m 배수입니다.

| 최상위 키 | 필수 여부 | 설명 |
|---|---|---|
| `blueprint_version` | 필수 | `2` |
| `title` | 선택 | 월드 이름 (SVG 라벨·Blender 컬렉션 이름) |
| `seed` | 선택 | 결정론적 생성 정수 (`0–2,000,000,000`) |
| `size_m` | 선택 | `[폭, 높이]` (m, 256의 배수) |
| `extends` | 선택 | 상속할 기준 블루프린트 JSON 파일 경로 |
| `terrain` | 선택 | `base_elevation_m`, `north_slope_m`, `east_slope_m`, `grain_m`, `ledge_m`, `coast`(없으면 내륙), `ridges`, `peaks`, `plateaus`, `basins`, `dunes` |
| `climate` | 선택 | `temp_offset_c`, `lapse_base_m`, `lapse_rate`, `rain_shadow`, `windward` |
| `regions` | 필수 | 환경 구역 목록 (`COAST`, `FOREST`, `PLAIN`, `MOUNTAIN`, `SNOW`, `DESERT`, `MARSH`, `MEDITERRANEAN`) |
| `features` | 선택 | 수계(`SEA`, `RIVER`, `CANYON`, `GLACIAL_TROUGH`, `TARN`, `OXBOW`, `TERMINAL`, `SPRING`) 및 안개 분지(`FOG_BASIN`) |
| `themes` | 선택 | 여행 권역(날씨·지역 특화 상점·경로 뼈대). 생략 시 기본 중립 권역 사용 |
| `realms` | 필수 | 왕국/영토 목록 (`id`, `biome`, `centre_uv`, `target_land_fraction`, `theme`) |
| `sites` | 선택 | 정착지 목록 (`CAPITAL`, `CITY`, `VILLAGE`, `grand_capital`, `concepts`, `castle_role`, `placement`) |
| `dungeons` | 선택 | 던전 목록 (`CATACOMB`, `VAULT`, `near_uv` 또는 `fog_basin_id` + `offset_fraction`) |
| `seasonal_links` | 선택 | 계절별 조건부 연결 (`FERRY`, `ICE`, `LOW_WATER`) |

### 기존 블루프린트 상속과 덮어쓰기

`"extends"`에 다른 JSON 파일 경로를 지정하면 기본 지도를 불러온 뒤 `region_overrides`, `feature_overrides`, `realm_overrides`, `theme_overrides`, `site_overrides`, `dungeon_overrides`로 원하는 ID만 수정하거나 `"remove": true`로 제외할 수 있습니다.

```json
{
  "blueprint_version": 2,
  "extends": "atlas_example.json",
  "seed": 202,
  "region_overrides": [{"id": "east_highlands", "max_elevation_m": 240}],
  "site_overrides": [{"id": "central_capital", "near_uv": [0.50, 0.44], "search_radius_m": 300}]
}
```

`GUIDED`(기본값)는 검색 반경 안에서 건조하고 완만한 후보를 찾고, `FIXED`는 지정 좌표를 고정하며 충돌 시 문제 ID를 오류로 보고합니다.

## 생성 명령

Blender 없이 계획 JSON과 SVG 지도만 생성할 수 있습니다.

```powershell
uv run --no-project --python 3.13 python assets/code/world_generator.py `
  --config assets/code/presets/atlas_example.json `
  --layout-output assets/generated/my_atlas.json `
  --map assets/generated/my_atlas.svg
```

Blender에서 도시·던전 메시를 생성하거나 OGRE 타일 패키지를 내보낼 수 있습니다.

```powershell
$blender = 'C:\Program Files\Blender Foundation\Blender 5.3\blender.exe'
$preset = 'assets/code/presets/atlas_example.json'

& $blender --background --python-exit-code 1 --python assets/code/world_generator.py -- `
  --config $preset --focus central_capital --toon `
  --output assets/generated/my_capital.blend --render assets/generated/my_capital.png

& $blender --background --python-exit-code 1 --python assets/code/world_generator.py -- `
  --config $preset --all-sites --ogre-output assets/generated/my_atlas_ogre
```

`--focus <정착지 또는 던전 ID>`, `--tile X,Y`(반복 지정 가능), `--meadow-view`, `--atlas-index-only`, `--all-sites`, `--force` 옵션을 지원합니다.

## C++/OGRE Classic 연결

| 파일 | 읽는 데이터 |
|---|---|
| `atlas.json`, `atlas.tsv` | 월드 계획, 정착지, 던전, 조건부 길망, 타일별 기후와 도로 구간 |
| `terrain.ptil` | 전역 16m 간격의 높이·수위·환경 ID |
| `tiles/X_Y/settlement.tsv`, `meshes/*.ogregeom`, `static.collision.bin` | 고정 구조물·지면·실내 모델과 충돌 (Blender Z-up → OGRE Y-up) |
| `tiles/X_Y/effects.tsv`, `interactions.tsv`, `navigation.json` | 식생·수면·천 효과, 우물·분수·등불 소켓, 방·길·봉인과 보상 위치 |
| `ogre/AtlasRuntime.hpp`, `AtlasRenderer.hpp`, `AtlasProbe.cpp`, `AtlasWalk.cpp` | 월드 상태, 스트리밍, 셰이더 연결, 이동·상호작용 C++17 예제 |
