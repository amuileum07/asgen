# OGRE C++용 게임 에셋

지붕·성·도시를 Blender에서 생성하고 렌더용 메시, 재질, 텍스처, 배치와
정적 충돌 삼각형을 함께 내보냅니다. Adobe 도구나 외부 Python 패키지는
필요하지 않습니다. `presets/game_city.json`이 게임 출력 예제입니다.

전체 월드는 [월드 생성기](WORLD.md)에서 같은 런타임 파일 형식으로
출력합니다. 월드 패키지에는 입지별 시설 경로와 정착지 위치를 담은
`world.json`이 추가됩니다.

## 형상과 표면

- 성의 큰 본관은 사각뿔, 작은 돌출탑과 성벽 탑은 팔각뿔, 주탑과 문루는
  원뿔을 사용합니다. 각 지붕은 한 꼭짓점으로 끝납니다. 원뿔은 40개 측면을
  부드러운 법선으로 표현하고 피라미드 지붕은 평면의 모서리를 유지합니다.
- 낮은 지붕보다 탑 처마가 높아지도록 층 단위로 높이를 보정합니다. 건물에
  파묻히는 지붕 면은 잘라내고 만나는 모서리를 얇게 마감합니다. 지붕이 닿는
  벽에는 창문 전체와 창틀 크기를 검사해 배치하지 않습니다.
- 도로 외곽, 둥근 모서리, 교차로, 광장, 집 기초를 포함한 제약 삼각분할로
  하나의 지면 메시를 만듭니다. 도로와 잔디가 정점과 높이를 공유하며 별도의
  겹친 도로 판을 두지 않습니다. 성터 내부는 안뜰·바닥 메시가 담당합니다.
- 가까운 도로 사이의 높이도 함께 조정합니다. 최종 삼각형의 경사를 다시
  제한하며 도로 중심 경로는 `max_road_grade`, 포장 면 전체는 여기에 0.15를
  더한 기울기를 상한으로 사용합니다. 기본값은 각각 20%, 35%(약 19°)입니다.
  문 앞·광장·성터의 기준 높이는 유지합니다. Blender 생성 후에는 도로와 이동
  그래프도 최종 지면의 높이에 맞추고 `surface_conformed`를 기록합니다.
  Blender 없이 출력한 계획은 메시 생성 전 단계의 높이입니다.
- 지면에는 경사와 저주파 노이즈를 이용한 연속 정점 색을 적용합니다. 포장에는
  반복 가능한 256×256 Albedo·Normal PNG를 생성합니다. UV는 월드 크기 기준이며
  지면의 한 타일은 2m입니다. 법선과 UV, 정점 RGBA를 게임 출력에 보존합니다.

## 생성과 출력

Blender 패널 **N → Settlement → OGRE 출력 폴더 → OGRE 에셋 출력**을
사용하거나 프로젝트 루트에서 아래 명령을 실행합니다.

```powershell
$blenderExe = 'C:\Program Files\Blender Foundation\Blender 5.3\blender.exe'
& $blenderExe --background --factory-startup --python-exit-code 1 `
  --python-expr 'import bpy; bpy.ops.wm.read_factory_settings(use_empty=True)' `
  --python assets/code/settlement_generator.py -- `
  --config assets/code/presets/game_city.json `
  --output assets/generated/my_game_city.blend `
  --layout-output assets/generated/my_game_city.json `
  --ogre-output assets/generated/my_ogre_city
```

`.blend` 등 기존 파일을 갱신할 때는 `--force`를 추가합니다. 에셋 출력 폴더는
빈 폴더 또는 이 생성기의 `.procedural_asset_package` 표식이 있는 폴더만
사용합니다. 다른 설정으로 바꾸어 내보낼 때는 새 폴더를 권장합니다. 로더는
현재 manifest/TSV에 기록된 파일만 읽으며 이전에 생성한 메시 파일을 사용하지
않습니다. 파일 경로와 출력 폴더는 게임 프로젝트의 에셋 폴더로 지정하면 됩니다.

| 출력 | 내용 |
|---|---|
| `manifest.json` | 좌표 기준, 재질, 메시·배치 정보, 경계 상자와 삼각형 수 |
| `meshes/*.ogregeom` | 제공한 C++ 로더가 직접 읽는 정점·인덱스 버퍼 |
| `meshes/*.mesh.xml` | OGRE 공식 도구로 변환할 수 있는 XML 메시 |
| `settlement.tsv` | C++ 로더용 배치, 위치·쿼터니언·스케일 |
| `settlement.scene` | `.mesh`로 변환한 경우 사용할 dotScene 배치 |
| `settlement.material` | 기본 색·정점 색·텍스처와 RTSS 노멀맵 설정 |
| `textures/*.png` | Albedo(sRGB), Normal(linear) 맵 |
| `static.collision.bin` | 월드 공간 정적 삼각형 충돌 데이터 |
| `navigation.json` | OGRE 월드 좌표의 도로·방·계단 경로와 POI |
| `ProceduralAssets.hpp` | OGRE Classic용 C++17 로더 |
| `markers.json`, `asset_markers.tsv` | 시설 및 조각상 모델을 붙일 위치 |
| `street_lights.tsv` | 가로등의 점광원 위치·색·범위 |

동일한 집은 메시를 공유하고 노드로 반복 배치합니다. 지면은 64m 단위의 메시로
나누며 경계 법선·정점 색·UV를 원본에서 복사합니다. 자동 거리별 LOD나 스트리밍
코드는 포함하지 않습니다. 삼각형 수는 각 패키지의 `manifest.json`에서 확인할
수 있고 `detail`, 건물 수, `terrain_step`으로 조절합니다.

## C++에서 불러오기

현재 대상은 **OGRE Classic 1.12/14, C++17**입니다. OGRE-Next 2.x/3.x는
장면·재질 API가 다르므로 별도 어댑터가 필요합니다. OGRE Root, 렌더 시스템,
SceneManager와 카메라를 초기화한 게임 코드에서 다음과 같이 사용합니다.

```cpp
#include "ProceduralAssets.hpp"

const std::filesystem::path directory = "assets/ogre_city";
auto* town = sceneManager->getRootSceneNode()->createChildSceneNode("Town");
ProceduralAssets::loadScene(directory, *sceneManager, *town);
auto collision = ProceduralAssets::loadCollision(
    directory / "static.collision.bin");
// collision.positions: float xyz, stride 12 bytes.
// collision.indices: uint32 triangle list, three per triangle.
```

OGRE 라이브러리와 링크합니다. `loadScene`이 리소스 그룹을 만들고 재질을
읽으며 ManualObject로 메시를 생성하고 공유 Entity를 배치합니다. 따라서
이 경로는 XMLConverter 실행이나 `.mesh` 변환을 요구하지 않습니다. 서로
다른 도시를 동시에 불러오면 별도의 `prefix`, `group` 인자를 지정하세요.

우물·분수·가로등과 잔디는 [도시 시설 사용법](CIVIC.md)을 참고하세요.
방·복도·가구의 새 배치는 [성 실내 사용법](CASTLE_INTERIOR.md)에 있습니다.
`loadAssetMarkers`로 조각상 위치를 읽고 필요하면 `loadStreetLights`로 야간
조명을 생성할 수 있습니다. 잔디와 물, 발광면은 렌더 메시로만 내보내며 정적
충돌에는 넣지 않습니다. 모델을 추가한 조각상의 충돌은 게임에서 연결하세요.

GL3+/D3D11 등에서 사용할 셰이더는 게임의 RTSS 설정을 사용합니다. 앱에서
`Ogre::RTShader::ShaderGenerator`를 초기화하고 SceneManager를 등록하며,
OGRE 배포본의 RTShaderLib 경로, 재질 scheme listener와 viewport scheme을
설정해야 합니다. 표준 OGRE ApplicationContext를 쓰면 해당 설정을 재사용할 수
있습니다. 로더는 UV와 접선(tangent)을 준비하고 포장 재질에 tangent-space
normal mapping 설정을 제공합니다. 환경광·직접광·그림자·후처리는 게임에서
설정합니다. Blender 렌더 조명은 에셋 패키지에 포함하지 않습니다.

이미 `.mesh` 파이프라인이 있으면 OGRE 공식 XMLConverter/AssimpConverter로
각 `*.mesh.xml`을 `*.mesh`로 변환한 후 `settlement.scene`을 사용할 수도
있습니다. 제공 예제에는 아직 변환하지 않은 XML이 포함됩니다.

## 좌표·충돌·이동

- 1 unit = 1m, +Y가 위쪽인 오른손 좌표계입니다.
  Blender `(x, y, z)`를 OGRE `(x, z, -y)`로 변환합니다.
- 버퍼의 법선·정점은 메시 로컬 공간, TSV의 위치·회전·크기는 배치 공간입니다.
  쿼터니언은 `w x y z` 순서입니다. 출력 당시 도시 Empty의 변환도 반영합니다.
- 충돌 데이터는 출력 시점의 모든 배치를 반영한 월드 삼각형입니다. Bullet/Jolt
  등의 **정적 오목 지형 충돌체**로 연결하세요. 닫힌 볼륨이나 동적 convex
  물체용 메시가 아닙니다. 도시를 로드한 뒤 parent를 이동하면 물리와 이동
  데이터에도 같은 변환을 적용해야 합니다.
- OGRE는 렌더링을 담당하며 이 로더가 물리 월드나 캐릭터를 생성하지 않습니다.
  `navigation.json`은 경로 그래프입니다. Recast 등에서 사용할 NavMesh는
  게임의 캐릭터 반경·높이·최대 경사에 맞춰 충돌 삼각형으로 빌드하세요.
- 성 실내와 계단은 포함됩니다. 일반 주택은 기본적으로 외관 인스턴스이며
  Blender에서 **실내가 있는 집으로 전환**한 건물만 실내도 내보냅니다.
  가구는 종류·크기·접근 공간을 정한 대체 형상입니다. 최종 가구 모델로
  바꾸는 작업과 열린 주택 출입문 설정은 기존 실내 도구에서 처리합니다.

## 버퍼 규격

수치는 little-endian입니다. 문자열은 UTF-8입니다.

`PGEO`: 8바이트 `PGEO 01 00 00 00`, u32 section 수. 각 section은 u16
재질 이름 바이트 수, 이름, u32 정점 수·인덱스 수, 정점 배열, u32 인덱스
배열 순서입니다. 정점 하나는 float32 12개(48바이트)로 position xyz,
normal xyz, uv, rgba 순서입니다. 인덱스는 section 정점 배열을 참조합니다.

`PCOL`: 8바이트 `PCOL 01 00 00 00`, u32 정점 수·삼각형 수,
float32 xyz 배열, u32 삼각형 인덱스 배열 순서입니다.

## 검증 범위

Ruff 린트·포맷, 일반 Python 단위 검사, 집·도시·성 Blender 통합 검사를
실행합니다. `tests/game_assets_blender_smoke.py`는 실제 지면 메시의 틈,
도로 높이, 잔디/포장 면적, 유효한 UV·정점 색·법선, 출력 버퍼 재읽기와 반복
출력을 검사합니다. 성 검사는 지붕을 포함한 실제 메시의 통행 공간을 ray cast로
확인합니다.

C++ 헤더는 OGRE **14.6.2**의 실제 SDK 헤더와 g++ C++17 구문 검사를
통과했습니다. 이 PC에서는 OGRE 공식 변환 실행 파일이 Windows 실행 정책에
막혀 OGRE 런타임 렌더·물리 주행까지 확인하지는 못했습니다. 게임 프로젝트에
연결한 뒤 사용하는 렌더 시스템과 물리 설정으로 확인해야 합니다.

참고 API: [Blender 제약 삼각분할](https://docs.blender.org/api/main/mathutils.geometry.html),
[OGRE 메시 도구](https://ogrecave.github.io/ogre/api/latest/_mesh-_tools.html),
[재질 스크립트](https://ogrecave.github.io/ogre/api/latest/_material-_scripts.html),
[RTSS](https://ogrecave.github.io/ogre/api/14/rtss.html).
