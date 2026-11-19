# 프로젝트 작업 지침

- Python 코드를 수정할 때는 `codingstyle.md`와 `pyproject.toml`의 Ruff
  설정을 따릅니다. 의존성은 uv로 관리합니다.
- Python 변경 후에는 Ruff 린트와 포맷 검사를 모두 통과시킵니다.
- 생성 규칙이나 Blender 통합 코드를 수정한 경우 기존 규칙 검사와
  `assets/code/tests/blender_smoke.py`도 실행합니다. 명령은
  `codingstyle.md`에 있습니다.
- 도시·지형·성곽 코드를 수정하면
  `assets/code/tests/settlement_blender_smoke.py`도 실행합니다.
- 성 실내나 성 외관을 수정하면
  `assets/code/tests/castle_blender_smoke.py`도 실행합니다.
- 지면·도로·게임 출력 코드를 수정하면
  `assets/code/tests/game_assets_blender_smoke.py`도 실행합니다.
- Blender 진입 파일의 `bpy.props` 주석은 런타임 평가가 필요하므로
  `from __future__ import annotations`를 추가하지 않습니다.
