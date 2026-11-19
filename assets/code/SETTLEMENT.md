# 중세 마을·도시·수도 생성기

지형부터 길, 가게와 주택, 성벽과 성을 생성하는 Blender 도구입니다.
집은 기존 `house_generator.py`로 만든 원형을 재사용합니다. 카툰풍 회벽,
목재 골조, 지붕과 성탑을 조합하며 외부 애셋이나 Python 패키지가 필요 없습니다.
산맥과 물길을 포함한 전체 지도에 여러 도시를 놓으려면
[게임 월드 생성기](WORLD.md)를 사용합니다.

## 파일

| 파일 | 역할 |
|---|---|
| `settlement_generator.py` | 실행 진입점, Blender 패널, JSON·SVG 출력 |
| `settlement_rules.py` | 규모·경계·도로·필지·상권·성 위치·이동 그래프 계산 |
| `terrain_rules.py` | 결정적 노이즈 지형과 도로·기초 평탄화 |
| `settlement_blender.py` | 지형 메시, 원형 집 재사용, 가게·장터·나무와 미리보기 |
| `fortification_blender.py` | 곡선 성벽·성문·원형 탑·성의 둘레 성벽 |
| `castle_rules.py` | 성 전용 본관·주탑·별관·돌출탑의 배치와 비례 |
| `castle_blender.py` | 석조 성, 지붕 접합부, 아치 문루 |
| `castle_roof_rules.py` | 사각뿔·팔각뿔·원뿔 지붕과 창문 간섭 검사 |
| `transport_rules.py` | 도로 교차점 높이와 연속적인 포장 영역 |
| `surface_blender.py` | 지면과 길이 정점을 공유하는 삼각분할 메시 |
| `surface_quality.py` | 실제 포장 면과 진행 방향의 경사 제한 |
| `game_materials.py` | 지면 정점 색과 포장 Albedo·Normal 맵 |
| `civic_rules.py` | 규모별 시설, Seed 변형, 통행 여유와 잔디 분포 |
| `civic_blender.py` | 우물·분수·가로등, 잔디와 모델 교체용 위치 |
| `ogre_export.py` | OGRE 메시·재질·배치·충돌 패키지 |
| `castle_geometry.py` | 겹친 평면·계단 구멍·지붕 면 잘라내기 |
| `castle_interior_rules.py` | 성의 방·계단·가구·이동 경로 |
| `castle_interior_blender.py` | 빈 벽체·실내 메시·층별 보기 |

기존 집·실내 모듈을 포함한 `assets/code` 폴더를 함께 보관하세요.

## 규모에 따른 도시 형태

| 규모 | 기준 크기 (m) | 건물 희망 상한 | 중심 장터 | 기본 성벽 | 기본 성 |
|---|---:|---:|---:|---|---|
| `VILLAGE` 작은 마을 | 42 | 28 | 1 | 없음 | 없음 |
| `TOWN` 성벽 마을 | 78 | 100 | 1 | 낮은 성벽 | 없음 |
| `CITY` 도시 | 120 | 240 | 2 | 성벽·성문·탑 | 고지대의 성 |
| `CAPITAL` 수도 | 175 | 480 | 3 | 높은 성벽·다수 성문 | 큰 성·본관 |

기준 크기는 불규칙한 경계를 만드는 기준 거리입니다. 실제 경계는 비대칭이고
방향마다 크기가 다릅니다. 건물 상한은 정확한 채 수 보장이 아닙니다.
밀도·도로 폭·빈터·경사·충돌 검사에 따라 실제 채 수가 줄어들며 결과에 기록됩니다.

마을은 소수의 큰길과 짧게 뻗는 골목을 만듭니다. 도시는 더 많은 성문과 큰길,
복수의 순환 연결로와 골목을 만듭니다. 수도는 여러 장터와 더 복잡한 길망을
사용하고 중심 상권에 높은 건물의 비중을 늘립니다. 실제 인구 수의 복제보다는
수백 채 단위의 게임용 축약 도시를 목표로 합니다.

## 알고리즘

1. Seed로 비대칭 축과 저주파 곡선을 조합해 경계선을 만듭니다. 원을 그대로
   쓰지 않으며 양의 방사 거리로 자기 교차를 방지합니다.
2. 여러 해상도의 결정적 노이즈로 언덕을 만들고 장터와 성의 고지대를 잡습니다.
3. 지형의 경사와 경로 비용으로 A* 도로를 만듭니다. 큰길, 연결로, 골목의
   위계를 구분합니다. 골목은 장터를 관통하는 지름길에 과도하게 몰리지 않으며
   기존 길 바로 옆의 불필요한 평행길도 억제합니다.
4. 대각선이 교차하면 실제 공유 교차점으로 나눕니다. 교차점 끝을 유지하면서
   도로를 부드럽게 하고 설정한 최대 경사를 다시 검사합니다.
5. 길 양쪽에서 집 후보를 만들고 회전된 사각형 필지로 검사합니다. 마을 경계,
   장터, 성, 다른 집, 도로와 출입구 경로를 침범하는 후보는 제외합니다.
6. 장터 접근성과 큰길 여부를 바탕으로 연속적인 상업 점수를 계산합니다.
   중심지에서는 가게가 모이고, 바깥쪽은 주거가 많으며, 주거 골목에도 작은
   가게가 생길 수 있습니다. 드문 골목 상점의 최소 사례도 보존합니다.
7. 도로 높이에 맞춰 지형을 깎고 집 기초를 평탄화합니다. 포장 외곽·교차점·광장·
   집 기초를 제약선으로 삼각분할합니다. 지형과 길이 같은 정점을 사용하므로
   교차로 포장끼리 겹치거나 도로 아래가 허공으로 뜨지 않습니다.
8. 큰 도시에는 경계 곡선을 따르는 성벽을 만듭니다. 큰길이 통과하는 성문은
   실제로 비어 있고 양쪽 문루와 위쪽 보를 생성합니다.
9. 성은 전용 규칙으로 높은 주탑, 대회관, 전면 별관, 예배당을 서로 붙여
   배치합니다. 높이가 다른 원형 탑과 상층 돌출탑, 사각뿔·팔각뿔·원뿔 지붕,
   굴뚝, 좁은 아치창과 목조 상층부로 중세 성의 실루엣을 만듭니다.
   불규칙한 둘레 성벽과 탑, 통과 가능한 아치 문루가 안뜰을 둘러쌉니다.
   본관은 성 전용 메시로 생성합니다. 인접한 낮은 지붕을 기준으로 탑 높이를
   보정하고 벽에 닿는 지붕 면을 잘라 접합부를 마감합니다. 지붕과 겹치는
   창문·창틀은 배치하지 않습니다.

가게 종류는 빵집·재단사·식료품점·선술집·대장간입니다. 가게에는 차양과 간판을
추가하고 각 건물에 `business`와 `zone` 속성을 저장합니다. 구역은 엄격한 동심원
경계 대신 중심지와 길을 따른 점수로 분포합니다.

## Blender에서 사용

1. Scripting의 Text Editor에서 `settlement_generator.py`를 열고 **Alt+P**.
2. 3D Viewport에서 **N → Settlement** 탭을 엽니다.
3. 규모·Seed·기복·밀도·성벽·성을 설정하고 **도시 생성 / 갱신**을 누릅니다.
4. **도시 미리보기 카메라 / 조명**을 누르고 **F12**로 렌더링합니다.

`새 도시 변형`은 도시 Seed를 증가시킵니다. 생성 결과는 별도 컬렉션과
`Settlement` Empty 아래에 놓이며 전체 이동·회전을 유지한 채 갱신할 수 있습니다.
현재 도시 컬렉션을 비우고 다시 생성하면 별도 도시를 만들 수 있습니다.
사용자가 추가한 오브젝트는 생성 결과 교체 시 보존합니다.

LOW는 외관 원형을 공유하고 입체 지붕 타일·덧문을 생략합니다. HIGH는 이 세부
표현을 추가합니다. 품질 선택이며 실시간 거리 기반 LOD 시스템은 아닙니다.

### 사진 같은 고지대 성과 평지 요새

`성 입지`에서 다음 두 유형을 선택할 수 있습니다. 두 유형 모두 성 전용
둘레 성벽을 가지며, 도시 전체를 둘러싸는 `성벽` 옵션과는 별개입니다.

- `HILLTOP` 고지대 암반 성: 도시의 높은 곳을 골라 언덕과 성터를 만듭니다.
  뒤쪽과 측면은 짧고 가파른 전이로 암반이 드러나고, 성문 방향은 긴 전이로
  진입 도로가 오를 수 있게 합니다. 노출된 암반은 메시와 재질로 표현합니다.
- `WALLED` 평지 요새: 언덕 상승량을 줄이고 완만한 지형 위에 성벽과 문루,
  밀집된 석조 건물을 만듭니다.

성의 크기는 도시 규모에 맞추고 Seed가 탑·본관 높이, 지붕 비례와 성벽의
외곽 형태를 바꿉니다. 성문과 본관 앞뜰은 기존 도로·이동 그래프에 연결합니다.
성 뒤의 급경사 구간은 일반 도로 후보에서 제외합니다. 문루의 아치 아래에는
실제로 통과 공간을 남기고 쇠창살은 위로 올린 상태로 생성합니다.

`성 확대 미리보기`를 누르면 성과 주변 언덕을 향한 카메라를 설정합니다.
`castle_hilltop.json`, `castle_walled.json` 프리셋을 제공합니다.

### 개별 건물의 실내

도시 전체에 가구까지 중복 생성하지 않습니다. 집 인스턴스를 선택하고
**선택 건물을 실내가 있는 집으로 전환**을 누르면 기존 실내 생성기를 사용해
해당 집만 편집 가능한 메시·층·계단·가구로 전환합니다. 출입문은 열린 상태로
만들며 위치·회전·크기를 유지합니다. 기존 외관 인스턴스는 숨깁니다.

전환한 집은 **Cartoon House** 탭에서 층별로 살펴볼 수 있습니다.
성은 **성 실내 생성** 옵션으로 방·층·문·계단·가구를 함께 만듭니다.
**성 내부 층 보기**, **성벽 통로 / 문루 보기**, **성 외관 복원** 버튼을
제공합니다. 자세한 구성과 데이터는 [성 실내 사용법](CASTLE_INTERIOR.md)에
있습니다. 도시를 갱신하면 전환된 집과 성도 다시 생성 대상이므로 직접 편집한
모델은 별도 복제본을 두세요.

## 명령행 예제

프로젝트 루트에서 PowerShell로 실행합니다. 빈 장면은 새 백그라운드 Blender에만
적용되며 이미 열려 있는 창에는 영향을 주지 않습니다.

```powershell
$blenderExe = 'C:\Program Files\Blender Foundation\Blender 5.3\blender.exe'
$emptyScene = 'import bpy; bpy.ops.wm.read_factory_settings(use_empty=True)'

& $blenderExe --background --factory-startup --python-exit-code 1 `
  --python-expr $emptyScene --python assets/code/settlement_generator.py -- `
  --config assets/code/presets/settlement_city.json `
  --output assets/generated/my_city.blend `
  --layout-output assets/generated/my_city.json `
  --map assets/generated/my_city.svg `
  --render assets/generated/my_city.png
```

기존 파일을 교체할 때만 `--force`를 추가합니다. 렌더는 생략할 수 있습니다.
`settlement_village.json`, `settlement_town.json`, `settlement_city.json`,
`settlement_capital.json`의 예제를 제공합니다. 도시 예제는 빠르게 살펴보기 위해
기준 크기와 건물 상한을 기본 도시 프로필보다 줄였습니다.

고지대 성을 확대해서 저장·렌더링하려면 위 명령에서 다음 값을 사용합니다.

```powershell
--config assets/code/presets/castle_hilltop.json --castle-preview `
--output assets/generated/my_castle.blend `
--render assets/generated/my_castle.png
```

명령행에서 `--castle-site HILLTOP` 또는 `--castle-site WALLED`로 입지를
덮어쓸 수도 있습니다. 새 지붕·지면과 OGRE 출력을 포함한 예제는
`assets/generated/game_city.blend`, `game_castle.png`, `game_street.png`입니다.
`presets/game_city.json`으로 다시 만들 수 있습니다. OGRE 출력과 C++ 사용법은
[게임 에셋 사용법](GAME_ASSETS.md)에 있습니다.

Blender 없이 계획·지도만 생성할 수도 있습니다.

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.uv-cache'
uv run --no-project --python 3.13 python assets/code/settlement_generator.py `
  --scale CAPITAL --layout-output assets/generated/capital_plan.json `
  --map assets/generated/capital_map.svg
```

## 게임 엔진에 연결할 데이터

JSON은 마을 Empty 기준 로컬 좌표이며 1 unit = 1m, +Z가 위쪽입니다.
현재 스키마 버전은 5입니다. 성의 주택 원형이 성 전용 구조로 바뀌었으므로
이전 버전의 `templates`에 있던 `keep` 대신 `castle.architecture`를 사용합니다.

- `buildings`: 건물 위치·회전(rad)·원형 집 설정·출입구·업종·구역·상업 점수.
- `roads`: 폭과 실제 3D 경로. `ACCESS`는 도로에서 건물 문까지의 연결입니다.
- `navigation`: 이동 노드·연결·길이·폭과 모든 출입구·장터·성문의 POI.
- `spawn_node`: 첫 성문 바깥의 플레이어 시작 지점. 장터 시작 지점도 별도 제공.
- `terrain`, `terrain_boundary`: 재현 가능한 지형 파라미터와 생성 영역.
- `boundary`, `gates`, `castle`: 마을 경계, 통과 구멍, 성과 본관 위치.
- `castle.architecture`: 성 내부 로컬 좌표의 건물·탑·지붕·외곽·문 위치.
  `castle.centre`, `keep_heading`으로 마을 좌표로 변환합니다.
- `castle.interior`: 방·계단·벽과 구멍·가구·층별 경로. 최상위 이동 그래프도
  성 내부까지 연결되며 `CASTLE_ROOM` POI를 포함합니다.
- `civic_assets`: 우물·분수·가로등·조각상 위치, 회전·치수·도시별 형태 파라미터.
- `navigation.obstacles`: 시설물의 공간과 향후 조각상을 위해 비워 둔 영역.

기준 이동체는 반지름 0.35m, 높이 1.7m입니다. 수치상 최대 도로 경사를 검사하고
모든 출입구까지 그래프가 연결되는지 검증합니다. 실제 메시의 도로 높이와
틈도 검사합니다. [OGRE 출력](GAME_ASSETS.md)은 +Y 위쪽 좌표로 변환하며
정적 삼각형 충돌 데이터를 제공합니다. 물리 엔진 연결과 NavMesh 생성은 게임
프로젝트에서 처리합니다.

시설과 잔디를 포함한 예제는 `presets/civic_city.json`입니다. 설정과 OGRE의
조명·교체용 모델 연결은 [도시 시설 사용법](CIVIC.md)을 참고하세요.

Blender에서 메시 생성 후 도로·이동 그래프를 최종 지면 높이에 맞추며
`navigation.surface_conformed`를 기록합니다. Blender 없이 생성한 계획은
메시 생성 전 단계의 높이입니다.

현재 구현은 도시·장면·이동 데이터 생성기입니다. 플레이어 컨트롤러, 거리별
스트리밍, NPC 일과·대화·상점 거래는 게임 엔진 쪽 연결 대상입니다. 하천·교량,
침식 시뮬레이션과 문 애니메이션은 포함하지 않습니다.

## 연구 참고와 구현 범위

논문의 아이디어를 참고해 현재 프로젝트용 코드를 작성했습니다. 논문 시스템
전체를 재현하거나 원저자의 구현 코드를 가져온 것은 아닙니다.

- [Galin 등, Procedural Generation of Roads (2010)](https://diglib.eg.org/items/0aba12a9-bdbc-43a2-982c-5d1a9a43a2ba): 경사 등 지형 비용에 따른 경로 탐색과 도로 주변 지형 조정. 여기서는 8방향 격자 A*와 경사 검사를 사용합니다.
- [Chen 등, Interactive Procedural Street Modeling (2008)](https://www2.cs.uh.edu/~chengu/Publications/streetModeling/street_modeling.html): 지형·위계·그래프를 이용한 도로 설계의 배경 참고. 논문의 텐서 필드 편집기는 구현하지 않았습니다.
- [Vanegas 등, Procedural Generation of Parcels in Urban Modeling (2012)](https://www.cs.purdue.edu/cgvlab/www/publications/vanegas2012procedural/): 도로 접근성을 갖는 필지 생성의 배경 참고. 여기서는 도로 접면 후보와 회전 사각형 충돌 검사를 사용하며 논문의 블록 전체 분할을 재현하지 않습니다.

## 검증

```powershell
uv run --no-project --python 3.13 python -m unittest discover `
  -s assets/code/tests -p 'test_*.py' -v

& $blenderExe --background --factory-startup --python-exit-code 1 `
  --python assets/code/tests/settlement_blender_smoke.py
```

Seed, 규모 차이, 비원형 경계, 필지 간섭, 도로 경사, 전체 이동망 연결,
중심 상권·골목 상점, 기초 높이, 성, JSON·SVG 출력과 Blender 원형 재사용,
실내 전환, 실패 복구·사용자 오브젝트 보존을 검사합니다. Ruff 기준은
루트 `codingstyle.md`를 따릅니다.

성 검사는 주탑과 별관의 높이 차이, 성벽 내부 수용, 본관 진입 통로,
입지에 따른 고도 차이와 좌표 변환을 확인합니다. Blender에서는 문루 아래의
실제 통과 공간을 ray cast로 검사하고 고지대·평지 요새의 메시와 재생성,
확대 카메라 재설정 시 데이터 누적 여부도 확인합니다.
