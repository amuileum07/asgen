# 카툰풍 집 생성기

산·계곡·해안·호수·강에 여러 정착지를 배치하는 전체 맵은
[게임 월드 생성기](WORLD.md)를 사용하세요.

마을·도시·수도와 지형·성벽·성을 한 번에 만들려면
[도시 생성기 사용법](SETTLEMENT.md)을 참고하세요. 실행 파일은
`settlement_generator.py`이며 기존 집·실내 생성기를 재사용합니다.
성은 전용 규칙으로 본관·주탑·별관·둘레 성벽을 만들며, 고지대 암반 성과
평지 요새를 선택할 수 있습니다. `presets/castle_hilltop.json`을 제공합니다.
성의 방·계단·가구와 층별 보기는 [성 실내 사용법](CASTLE_INTERIOR.md)에 있습니다.
공유 지형·도로와 OGRE C++ 에셋 출력은
[게임 에셋 사용법](GAME_ASSETS.md)을 참고하세요.
잔디·우물·분수·가로등과 조각상 위치는 [도시 시설 사용법](CIVIC.md)에 있습니다.

Blender Python으로 직사각형 1~3층 집의 **외관·실내 구조·가구 배치**를 생성합니다. 기본 외관은 중세풍 회벽과 목재 골조입니다. Blender **5.3.0**에서 실행·렌더링을 검증했습니다. 외부 Python 패키지, Adobe 프로그램, 텍스처 다운로드가 필요하지 않습니다.

## 파일 구성

```text
assets/
  code/
    house_generator.py       # Blender 모델 생성, 오른쪽 패널, 명령행 실행
    house_rules.py           # 크기·창문 배치, 지붕 계산, 벽 마감재 자르기
    interior_rules.py        # 방·계단·가구 배치와 동선 검사 (Blender 독립)
    interior_blender.py      # 실내 메시·가구 상자·층별 보기
    INTERIOR.md              # 실내와 가구 규칙, 크기 JSON, 모델 좌표 기준
    presets/                 # 수정해서 사용하는 JSON 설정 예제
    tests/                   # 일반 Python 검사와 Blender 통합 검사
  generated/                 # 예제 .blend와 렌더 이미지
```

위 Python 모듈 네 개는 같은 폴더에 두세요. 생성 결과는 `assets/generated` 등 별도 폴더에 저장하는 구성을 권장합니다.

## Blender에서 사용

1. Blender의 **Scripting** 작업 공간으로 이동합니다.
2. Text Editor에서 **Open**으로 `assets/code/house_generator.py`를 엽니다.
3. **Run Script** 또는 Text Editor 위에서 **Alt+P**를 누릅니다. 기본 집이 생성됩니다.
4. 3D Viewport에서 **N**을 누르고 오른쪽의 **Cartoon House** 탭을 엽니다.
5. 설정을 바꾸고 **집 생성 / 갱신**을 누릅니다. 설정 변경만으로는 재생성하지 않습니다.

버튼 동작:

- **집 생성 / 갱신**: `현재 집`에 지정된 생성 결과를 교체합니다.
- **새 구조 변형**: 구조 Seed를 1 증가시키고 현재 집을 갱신합니다.
- **별도 집 추가**: 기존 집을 보존하고 **3D Cursor 위치**에 새 집을 만듭니다. 이후 `현재 집`을 바꿔서 편집 대상을 선택할 수 있습니다.
- **미리보기 카메라 / 조명 만들기**: 생성된 집에 맞는 카메라·조명·바닥을 만들고 현재 장면의 카메라, World, 렌더 설정을 바꿉니다. **F12**로 렌더링합니다. 집 설정을 바꾼 뒤에는 이 버튼으로 카메라 구도를 다시 맞추세요.
- **선택한 층 실내 보기**: 지정한 층의 실내를 낮은 벽과 함께 보여 줍니다. **외관 다시 보기**로 전체 건물을 복구합니다. 자세한 규칙은 [INTERIOR.md](INTERIOR.md)에 있습니다.

모델과 설정은 `.blend`에 저장됩니다. Blender를 다시 열면 패널의 Python 정의를 불러오기 위해 스크립트를 다시 실행하세요. `CH_House` Empty를 이동·회전하면 집 전체가 함께 움직이며, 갱신할 때도 이 변환을 유지합니다.

## 지원 설정

| 설정 | 설명 |
|---|---|
| 건축 양식 | `MEDIEVAL`(중세 목조, 기본값), `SIMPLE`(기본 카툰) |
| 구조 Seed | 같은 설정·코드에서 같은 집을 재현하는 정수 |
| 마감 Seed | 형상을 유지하고 벽돌·판자·지붕 타일의 색상 배치 변경 |
| 구조 변화량 | 가로·세로의 변화 범위. `0.08`은 ±8%. `0`이면 입력 크기 고정 |
| 층수 | 1~3층. 선택한 층수 자체는 랜덤으로 바뀌지 않음 |
| 벽 마감 | `BRICK`, `WOOD_HORIZONTAL`, `WOOD_VERTICAL`, `PLASTER` |
| 지붕 형태 | `GABLE`(박공), `HIP`(우진각), `SHED`(외쪽 경사), `FLAT`(평지붕) |
| 팔레트 | `WARM`, `PASTEL`, `COASTAL` |
| 부품 크기 | 벽돌 크기, 판자 폭, 창문 크기·간격, 처마 길이 등 |
| 실내 / 가구 배치 | 층별 바닥·칸막이·계단과 가구 상자를 선택적으로 생성 |
| 가구 배치 Seed | 외관과 평면을 유지하면서 가구 후보 배치 변경 |
| 통로 폭 | 문 앞 공용 공간과 가구 접근 경로에 확보할 폭 |
| 가구 크기 JSON | 가구 모델 없이 종류별 크기·접근 여유를 지정 |

단위는 **1 Blender unit = 1m**입니다. 창문 너비는 설정을 상한으로 사용하며, 벽 길이와 덧문 여유에 맞춰 줄어들 수 있습니다. `window_spacing`은 창문을 배치할 칸 수의 기준이며 실제 간격은 벽 길이에 맞춰 균등하게 조정합니다.

벽돌·판자·지붕 타일은 실제 입체 형상입니다. 문·창문 영역은 벽과 마감재에서 함께 제외하고, 박공과 경사 지붕 경계에 닿은 부품은 잘라 맞춥니다. 많은 부품을 역할별 메시에 병합해 오브젝트 수를 줄였습니다. 첫 버전은 Python으로 직접 메시를 생성하며 Geometry Nodes는 사용하지 않습니다.

모든 메시에 **UVMap**을 생성합니다. 면마다 실제 크기에 맞춘 반복 텍스처용 UV이므로 서로 겹칩니다. Painter에서 집 전체를 고유하게 칠하거나 라이트맵을 베이크하려면 별도의 UV 패킹이 필요합니다.

중세 양식은 회벽과 짙은 목재 골조, 사선 버팀목, 석재 기단·굴뚝과 판자 문을 추가합니다. 골조는 문·창문 영역을 비워 두고 지붕 높이에 맞춥니다. `presets/medieval_house.json`에 가파른 지붕과 긴 처마를 조합한 예제가 있습니다.

실내는 단순한 거실·침실·계단실 구성과 가구 크기 상자를 지원합니다. ㄱ자 평면·주방·욕실·게임 충돌체·실제 가구 모델 연결은 후속 확장 대상입니다. 카툰 표현은 형태·색상·둥근 모서리 중심이며 외곽선이나 셀 명암 셰이더는 포함하지 않습니다.

## 건물 알고리즘 상태 (개구부·구조 정합성)

- **주택 외관 및 골조 (`house_rules.py`, `house_generator.py`)**:
  - 상층 처마 창문은 지붕 경사·두께(`roof_planes`)를 고려해 창틀 상단이 잘리지 않도록 높이를 제한합니다.
  - 덧문 폭은 모서리 기둥, 인접 창문·출입문, 중세 수직 골조와의 간격을 확인해 자동으로 줄이거나 생략하며, 대각 브레이스도 덧문 영역을 비워 둡니다.
  - 창틀·문틀·유리창은 벽 외면에 매입되도록 배치해 회벽(`PLASTER`)에서도 틈새가 생기지 않으며, 중세 굴뚝은 경사 지붕의 내리막 모서리까지 지붕 안으로 내려 뜹을 방지합니다.
- **주택 실내 및 계단 (`interior_rules.py`, `interior_blender.py`)**:
  - `interior=True`일 때 칸막이 벽(`split`)은 정면 출입문과 앞·뒤 창문을 피하도록 배치하고, 계단실(`stair_bounds`) 뒤쪽 및 계단 쪽 옆벽과 겹치는 창문은 제외해 창문이 벽·계단에 가려지거나 잘리지 않게 합니다.
  - 칸막이 문은 계단 시작부 앞의 통로 여유를 확보하며, 평지붕(`FLAT`) 최상층 칸막이는 지붕 슬래브 하단 높이 이내로 맞춥니다.
  - `variation`으로 인해 실제 평면이 계단과 방을 함께 둘 수 없을 만큼 작아지면 `make_interior_plan`이 `ValueError`를 보고해 무리한 겹침을 방지합니다.
- **성 외관 및 실내 (`castle_rules.py`, `castle_blender.py`, `castle_interior_rules.py`, `castle_interior_blender.py`)**:
  - 외관 전용 모드(`castle_interior=False`)에서도 블록과 탑의 창문 테두리 전체가 인접 블록·탑·돌출탑(`oriel`) 코벨에 가려지는지 검사해 벽에 끼이는 창문을 제거하며, 블록 지붕 처마 규격을 `castle_roof_rules.py`와 일치시켰습니다.
  - 실내 모드(`castle_interior=True`)에서는 창문 폭 전체 기준으로 출입구(`ENTRY`/`DOOR`)와 겹치지 않게 제외하고, 외벽 창틀 돌출부와 `oriel` 코벨 간섭을 함께 검사합니다. 내부 문틀은 창턱 없이 벽 양면을 감싸며, 문서 기준 최소 반경(`19.2m`)을 부동소수점 오차 없이 허용합니다.
- **도시 시설 (`civic_rules.py`, `civic_blender.py`)**:
  - 우물·분수·가로등·조각상 예약 공간은 도로·건물·성곽과의 간격을 검사한 뒤 지면에 맞춰 배치됩니다. (맵·지형·도로 규칙은 별도 문서인 [SETTLEMENT.md](SETTLEMENT.md) 및 [WORLD.md](WORLD.md) 범위를 따릅니다.)

## 명령행 생성

프로젝트 루트에서 PowerShell로 실행합니다. Blender 경로는 설치 위치에 맞춰 바꿔 주세요.

```powershell
$blenderExe = 'C:\Program Files\Blender Foundation\Blender 5.3\blender.exe'

& $blenderExe --background --factory-startup --python-exit-code 1 `
  --python assets/code/house_generator.py -- `
  --config assets/code/presets/brick_gable.json `
  --output assets/generated/my_house.blend `
  --render assets/generated/my_house.png
```

기존 출력 파일을 교체하려면 `--force`를 추가합니다. 렌더가 필요 없으면 `--render`를 생략하세요. `--stage`를 추가하면 렌더 없이 카메라와 조명을 포함한 `.blend`를 저장할 수 있습니다.

`--seed 123`, `--detail-seed 8`, `--wall-style WOOD_VERTICAL`, `--roof-style SHED`, `--floors 1`, `--width 7`, `--depth 5`, `--variation 0.05`, `--palette PASTEL`처럼 JSON 설정을 덮어쓸 수 있습니다. 나머지 값은 JSON에 `HouseConfig` 필드 이름으로 지정합니다.

## uv로 검사

코딩 기준과 Ruff 린트·포맷 명령은 [codingstyle.md](../../codingstyle.md)에 있습니다. Ruff는 uv로 관리하는 개발 도구이며, 생성기 실행에는 외부 패키지가 필요하지 않습니다.

`bpy`와 `mathutils`는 Blender가 제공합니다. 별도로 설치하지 않습니다. 일반 Python은 Blender와 독립적인 생성 규칙 검사와 `--dry-run`에 사용합니다. 생성 규칙 검사는 `uv run --no-project`로 가상환경 생성 없이 실행할 수 있습니다.

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.uv-cache'

uv run --no-project --python 3.13 python -m unittest discover -s assets/code/tests -p 'test_*.py' -v

uv run --no-project --python 3.13 python assets/code/house_generator.py --dry-run --seed 123

& $blenderExe --background --factory-startup --python-exit-code 1 `
  --python assets/code/tests/blender_smoke.py
```

일반 검사는 외관과 실내의 Seed 재현성·개구부·가구 간섭·접근 경로·계단 연결을 확인합니다. Blender 검사는 벽 4종 × 지붕 4종, 1~3층 실내와 실제 계단 구멍, UV, 패널, 층별 보기, 실패 복구 및 데이터 누적 여부를 확인합니다.

## 편집할 때

- 형태 생성 규칙: `house_rules.py`의 `HouseConfig`, `make_plan`, `_roof_faces`
- 벽돌·판자 배치: `house_rules.py`의 `wall_tiles`
- 색상: `house_generator.py`의 `COLORS` (sRGB HEX)
- 창틀·문·덧문: `house_generator.py`의 `_build_opening`
- Blender 패널: `house_generator.py`의 `CH_Settings`, `CH_PT_panel`
- 중세 목재 골조·기단·굴뚝: `house_generator.py`의 `_medieval_details`
- 방·계단·가구 배치: `interior_rules.py`, 크기 예제 `presets/furniture_sizes.json`
- 실내 메시와 층별 보기: `interior_blender.py`

모듈을 편집한 후 Blender에서 실행 스크립트를 다시 실행하면 됩니다. 나머지 모듈도 다시 불러오므로 Blender를 재시작할 필요가 없습니다.

갱신은 생성기가 표시한 오브젝트만 교체합니다. 생성된 메시를 직접 편집한 내용은 갱신하면 다시 만들어지므로, 직접 수정할 집은 컬렉션을 복제해 별도로 보관하세요. 사용자 추가 오브젝트와 다른 컬렉션은 유지합니다.
