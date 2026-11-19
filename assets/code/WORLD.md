# 게임 월드 생성

`world_generator.py`는 한 장의 지형 위에 산과 계곡, 바다·호수·강,
여러 정착지를 배치합니다. 단위는 m이고 Blender에서는 XY가 지면, Z가
고도입니다. 같은 설정과 Seed를 쓰면 같은 지형과 배치를 재현합니다.

## 실행

Blender Text Editor에서 `world_generator.py`를 열고 **Alt+P**를
누릅니다. 3D Viewport의 **N → World Map** 탭에서 설정 JSON을 선택하고
**새 월드 생성**을 누릅니다. 미리 볼 정착지 ID 칸을 비우면 전체,
`west_port`처럼 ID를 입력하면 해당 정착지 카메라를 설정합니다.
같은 월드의 입지나 지형을 수정하려면 JSON을 수정한 뒤 새로 생성합니다.

백그라운드에서 예제 전체를 생성하는 PowerShell 명령입니다.

```powershell
$blender = 'C:\Program Files\Blender Foundation\Blender 5.3\blender.exe'
& $blender --background --factory-startup --python-exit-code 1 `
  --python-expr 'import bpy; bpy.ops.wm.read_factory_settings(use_empty=True)' `
  --python assets/code/world_generator.py -- `
  --config assets/code/presets/world_example.json `
  --output assets/generated/my_world.blend `
  --layout-output assets/generated/my_world.json `
  --map assets/generated/my_world.svg `
  --render assets/generated/my_world.png `
  --ogre-output assets/generated/my_world_ogre
```

`--focus river_crossing`을 붙이면 강변 도시를 확대합니다.
`--focus high_ridge --meadow-view`는 능선 마을로 향하는 초지의 1.7m
눈높이에서 봅니다. 패널의 **초지 눈높이 카메라**도 같은 기능을 합니다.
정착지 ID를 비우면 생성된 초지 중 첫 번째를 보여 줍니다.

`--seed 57`은 월드 지형의 Seed를 바꿉니다. 각 도시의 건축 Seed는
`settlements[].settlement.seed`에서 따로 바꿀 수 있습니다.
`--force`로 이전 파일의 덮어쓰기를 허용합니다. 렌더와 OGRE 폴더는
필요한 경우에만 지정하면 됩니다.

Blender 없이 입지와 평면부터 확인하려면 다음 명령을 실행합니다.

```powershell
uv run --no-project --python 3.13 python assets/code/world_generator.py `
  --config assets/code/presets/world_example.json `
  --layout-output assets/generated/my_plan.json `
  --map assets/generated/my_plan.svg
```

## 지형 설정

전체 예제는 [world_example.json](presets/world_example.json)에 있습니다.

| 항목 | 예제와 의미 |
|---|---|
| `size`, `terrain_step` | `[1600, 1224]`, `8`. 중심이 `[0, 0]`인 전체 범위와 지면 정점 간격. 정착지는 별도 `terrain_step`으로 더 촘촘하게 만듭니다. |
| `base_elevation`, `relief` | 기본 지면 높이와 Seed에 따른 요철. |
| `regions[]` | `MOUNTAIN`, `HILLS`, `VALLEY`, `PLAIN`. `centre: [x,y]`, `radii: [가로 반경, 세로 반경]`, `heading`(도), `elevation`(목표 고도), `max_elevation`(지형 상한). |
| `coast` | `side: "WEST"`, `position: -563`. 지정한 쪽에 바다를 만들며 `waviness`로 만곡, `level`로 수위를 지정합니다. |
| `lakes[]` | `id`, `centre`, `radii`, `level`, `depth`. 호수마다 수위와 수심을 따로 지정합니다. |
| `rivers[]` | `id`, `width`, `depth`, `points: [[x,y,수위], ...]`. 상류부터 입력하고 수위를 유지하거나 낮춥니다. 점 사이의 물길을 곡선으로 만듭니다. |
| `snowline`, `grass_density` | 눈이 시작되는 고도와 월드 풀잎 밀도. 각 도시의 풀잎 밀도도 따로 지정할 수 있습니다. |

예를 들어 `{"kind":"MOUNTAIN","centre":[262,370],"radii":[395,305],"heading":16,"max_elevation":224}`
는 북동쪽에 224m까지 오르는 타원형 산지를 만듭니다. `max_elevation`은
타원 안에서 샘플링한 자연 지형에 적용되고 경계 밖에서 부드럽게 완화됩니다.
`elevation`으로 산의 목표 높이를 별도로 지정할 수도 있습니다. 마을의
도로·광장·터와 성의 인공 언덕은 해당 위치의 지형을 추가로 다듬습니다.
실제 메시의 산 정상은 격자 간격에 따라 목표보다 조금 낮을 수 있습니다.

강과 호수는 설정한 위치에 수면과 바닥을 같이 만듭니다. 강 폭은
`terrain_step`의 2.5배 이상으로 두세요. 하구는 강 끝점을 바다까지
이어 놓고 마지막 수위를 해수면에 맞춥니다.

## 정착지 배치

`settlements[]`에 `id`, `near: [x,y]`, `search_radius`, `profile`과
선택적으로 `settlement`를 지정합니다. `settlement`는 기존 도시 생성기의
크기·건물 수·성벽·성·가구·지면·잔디 설정을 받습니다. 탐색 거리를 0으로
하면 지정한 위치만 검사합니다. `settlements: []`은 지형만 생성합니다.

후보 입지는 해안이나 물길과의 거리, 물에 잠기지 않는 바닥 면적,
지면 경사, 다른 정착지와의 간격으로 평가합니다. 선택한 지형에서만
완만한 건축 구역을 만들고, 기존 건물·도로 생성기에 연결합니다.
지형 격자에 배치 면의 가장자리 정점과 법선을 맞춥니다.
Blender는 실제 도로 삼각형도 검사하고 경사를 충족하지 못하면
탐색 범위 안의 다음 후보를 시도합니다. 계획 전용 출력에는 첫 번째
계획 입지가, Blender 출력에는 검사 후 확정한 입지가 기록됩니다.

| 입지 | 배치와 특징 |
|---|---|
| `HARBOR` | 해안과 평행한 장터 구역, 석조 안벽, 목재 부두, 계류한 배, 생선 가게와 창고. |
| `MOUNTAIN` | 산허리의 높이가 다른 건축 구역, 높은 지붕의 석조 주택, 여관과 석공, 계곡을 향한 전망대. |
| `LAKESIDE` | 목재 주택, 보트 가게, 호수로 연결되는 작은 선착장과 보트. |
| `RIVERSIDE` | 강을 따라 길어진 구역, 곡물 상점과 직조점, 양안에 닿는 목조 다리. |
| `INLAND` / `AUTO` | 일반 내륙 지형. AUTO는 가까운 물가나 산기슭의 조건을 먼저 평가합니다. |

좁은 해안이나 절벽에서 입지가 맞지 않으면 오류에 정착지 ID가 표시됩니다.
`near`나 `search_radius`를 조정하거나 정착지의 `radius`를 줄이면
탐색 범위와 필요한 평지 크기를 조절할 수 있습니다.

## 잔디와 게임 출력

완만하고 건조한 지면이 넓게 이어지는 곳을 찾아, 정착지 주변과 열린
평지에 키 큰 초지를 만듭니다. 안쪽은 잎이 서로 겹치고 가장자리에는
짧은 풀이 드문드문 섞입니다. 초지 바깥의 먼 지면에는 바닥색과 잔디
텍스처가 이어집니다. 급경사·눈밭·모래·물·도로·부두는 배치에서
제외합니다. `grass_density`를 높이면 뿌리 사이의 간격이 좁아집니다.

OGRE Classic C++17 출력은 도시와 동일한 `ProceduralAssets.hpp` 로더를
사용합니다. [게임 에셋 사용법](GAME_ASSETS.md)을 참고하세요.
`world.json`은 정착지 유형·위치와 시설 접근 경로를, `navigation.json`은
도로와 부두·선착장·다리·전망대로 이어지는 노드를 OGRE의 Y-up 좌표로
저장합니다. 충돌 파일에 지형과 시설 구조물이 포함됩니다. 수면과 잔디,
계류한 장식 보트는 렌더용입니다. 풀은 32m 단위로 묶이며 OGRE에서
얇은 잎의 양쪽 면을 표시합니다. 잎의 UV V는 뿌리 0, 끝 1입니다.
게임에서 바람이나 밟힘을 구현할 때 이 값을 굽힘 가중치로 쓸 수
있습니다. 정착지별 시작 노드를 제공하며 장거리
정착지 간 도로와 월드 전역의 내비메시는 게임에서 별도로 구성합니다.
수면과 잔디는 기본 자세로 생성합니다.

공유 지형의 경계, 시설 바닥, 교량 경사와 잔디 재질을 검증하려면
Blender에서 `assets/code/tests/world_blender_smoke.py`를 실행합니다.
위 명령의 `--python` 경로를 이 검사 파일로 바꾸고 뒤의 인자를
생략하면 내장 예제를 검사합니다.
