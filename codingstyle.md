# Python 코딩 스타일

이 프로젝트는 PEP 8을 기준으로 작성하고 Ruff로 린트와 포맷을 검사합니다.
실행 가능한 규칙의 기준은 루트 `pyproject.toml`입니다.

## 기본 규칙

- Python 3.11 이상에서 지원하는 문법을 사용합니다.
- 들여쓰기는 공백 4칸, 코드 줄 길이는 79자입니다.
- 주석과 문서 문자열은 72자 이내로 작성합니다.
- 파일은 UTF-8, 줄바꿈은 LF, 문자열은 큰따옴표를 사용합니다.
- 함수·변수·모듈 이름은 `snake_case`, 클래스는 `PascalCase`, 상수는
  `UPPER_SNAKE_CASE`를 사용합니다.
- import는 표준 라이브러리, 외부 라이브러리, 프로젝트 모듈 순서로
  묶고 Ruff가 정렬하도록 합니다.

## Pythonic한 코드

- 단순한 컬렉션은 리터럴을 사용하고 불필요한 중간 리스트는 피합니다.
- 이해하기 쉬운 comprehension과 generator expression을 사용합니다.
  조건과 변환이 복잡해지면 이름 있는 함수나 명시적인 반복문으로 풉니다.
- 길이가 같아야 하는 데이터를 함께 순회할 때는 `zip(..., strict=True)`로
  조건을 명시합니다.
- 반복문의 변수를 내부 함수가 암묵적으로 참조하지 않도록 합니다.
- 입력 검증과 오류 메시지는 경계에서 명확하게 작성합니다.
  `bool`이 `int`의 하위 타입이라는 점처럼 검증에 영향을 주는 차이는
  단순화 과정에서도 유지합니다.
- 생성 규칙은 `house_rules.py`와 `interior_rules.py`에 두고 Blender API와
  분리합니다. 실내 메시 생성은 `interior_blender.py`에서 담당합니다.
- 도시·지형 계산은 `settlement_rules.py`, `terrain_rules.py`에 두고,
  Blender 렌더링은 `settlement_blender.py`, `fortification_blender.py`에
  분리합니다. UI 진입점의 RNA 클래스 명명 예외를 유지합니다.
- 성 전용 배치·비례는 `castle_rules.py`, 메시 생성은 `castle_blender.py`에
  둡니다. 일반 주택 원형과 성 본관의 역할을 구분합니다.
- 성 실내 계산과 Blender 메시 생성은 `castle_interior_rules.py`와
  `castle_interior_blender.py`로 분리합니다. 평면 합집합·구멍·지붕 잘라내기는
  `castle_geometry.py`에서 공통 처리하고, 문·계단의 실제 통과 공간을 검사합니다.
- 지붕 형태·간섭 규칙은 `castle_roof_rules.py`, 도로 접합 규칙은
  `transport_rules.py`에 둡니다. 실제 포장 면의 경사 제한은
  `surface_quality.py`에 둡니다. `surface_blender.py`는 도로와 지형을
  공유 메시로 만들고 `game_materials.py`는 내보낼 표면 맵을 만듭니다.
- 게임 버퍼 규격은 `game_asset_format.py`에서 Blender와 분리합니다.
  `ogre_export.py`는 Blender 데이터에서 OGRE 패키지를 만들며 C++ 사용법은
  `assets/code/GAME_ASSETS.md`를 따릅니다.
- Seed 재현성, 문·창문 영역, 사용자 오브젝트 보존 등의 기존 동작을
  스타일 정리 과정에서도 유지합니다.
- 시설 배치·도시별 양식은 `civic_rules.py`, 메시와 실제 지면 투영은
  `civic_blender.py`에 둡니다. `solid_geometry.py`는 두께가 있는 부재를 자를 때
  닫힌 절단면을 만들며, 주택 골조가 지붕을 관통하지 않는지 검사합니다.

Ruff는 PEP 8, import 정렬, 명명, 최신 문법, 흔한 오류와 불필요한 표현을
검사합니다. 규칙 묶음은 `pyproject.toml`의 `tool.ruff.lint.select`에
명시되어 있습니다.

## Blender에서 필요한 예외

- `CH_OT_generate`, `CH_PT_panel` 등은 Blender의 RNA 클래스 명명
  관례를 따릅니다. 해당 진입 파일에만 `N801` 예외를 적용합니다.
- Blender Text Editor에서 형제 모듈을 불러오려면 `sys.path` 설정과
  모듈 재로딩이 먼저 필요합니다. 해당 import의 `E402` 예외를 유지합니다.
- `house_generator.py`의 `bpy.props` 프로퍼티 주석은 런타임에 평가되어야
  합니다. 이 파일에 `from __future__ import annotations`를 추가하지
  않습니다.
- `bpy`, `mathutils`는 Blender가 제공하므로 uv 의존성에 추가하지 않습니다.

새 예외가 필요하면 적용 범위를 좁히고 이유를 주석으로 남깁니다.

## uv로 검사와 포맷 실행

Ruff는 개발 의존성이며 버전은 `pyproject.toml`과 `uv.lock`에 고정합니다.
현재 버전은 **0.17.5**입니다. 버전을 올릴 때 설정의 `required-version`과
아래 명령도 함께 갱신합니다.

프로젝트 가상환경을 사용하는 일반적인 작업 흐름:

```powershell
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
```

프로젝트 가상환경 없이 실행하려면 다음 명령을 사용합니다. 캐시와 도구
잠금 파일을 프로젝트 안에 두는 이 방식으로도 검증했습니다.

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.uv-cache'
$env:UV_TOOL_DIR = Join-Path (Get-Location) '.uv-tools'

uv tool run --from ruff==0.17.5 ruff check .
uv tool run --from ruff==0.17.5 ruff format --check .
```

자동으로 고칠 때는 `ruff check . --fix`와 `ruff format .`를 실행합니다.
수정 결과를 검토하고 위 검사 두 개를 다시 통과시킵니다.

생성 규칙과 Blender 통합에 영향을 주는 변경은 기존 검사도 실행합니다.

```powershell
uv run --no-project --python 3.13 python -m unittest discover `
  -s assets/code/tests -p 'test_*.py' -v

$blenderExe = 'C:\Program Files\Blender Foundation\Blender 5.3\blender.exe'
& $blenderExe --background --factory-startup --python-exit-code 1 `
  --python assets/code/tests/blender_smoke.py

& $blenderExe --background --factory-startup --python-exit-code 1 `
  --python assets/code/tests/settlement_blender_smoke.py

& $blenderExe --background --factory-startup --python-exit-code 1 `
  --python assets/code/tests/castle_blender_smoke.py

& $blenderExe --background --factory-startup --python-exit-code 1 `
  --python assets/code/tests/game_assets_blender_smoke.py
```

추가 Python 패키지는 uv로 관리하며, 개발 도구는 `dependency-groups.dev`에
등록합니다. Blender에서 집을 생성하는 데에는 외부 패키지가 필요 없습니다.
