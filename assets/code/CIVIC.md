# 잔디와 도시 시설

도시 Seed가 시설의 형태와 배치를 재현합니다. 우물의 석조 단면·덮개, 분수의
받침과 단 수, 가로등의 팔 수와 랜턴 단면을 도시마다 조금씩 바꿉니다. 같은
도시 안에서는 같은 양식을 공유하고 크기는 작은 범위에서 달라집니다.

| 규모 | 기본 시설 |
|---|---|
| VILLAGE / TOWN | 덮개가 있는 우물 |
| CITY | 우물, 분수, 고전적인 가로등, 조각상 위치 |
| CAPITAL | 여러 우물·분수, 더 촘촘한 가로등, 조각상 위치 |

길 전체 폭, 문으로 이어지는 접근로, 집과 성벽, 다른 시설의 공간을 검사합니다.
광장 안에 충분한 여유가 없으면 주변의 열린 공간을 찾으며, 안전한 후보가 없는
시설은 생략합니다. 상점 가판대도 시설 및 조각상의 예약 영역을 피합니다.

## 설정과 예제

Blender **N → Settlement**에서 다음 항목을 설정합니다.

- **잔디 덤불 생성** (`grass`): 지면에 붙은 작은 잎의 묶음을 만듭니다.
- **잔디 밀도** (`grass_density`): 0~1.5. 기본 0.55, 예제는 1.0입니다.
- **우물·분수·가로등** (`civic`): 도시 시설 생성을 켜거나 끕니다.
- **Seed**: 도시 배치와 시설 양식을 함께 바꿉니다.

```powershell
$blenderExe = 'C:\Program Files\Blender Foundation\Blender 5.3\blender.exe'
& $blenderExe --background --factory-startup --python-exit-code 1 `
  --python-expr 'import bpy; bpy.ops.wm.read_factory_settings(use_empty=True)' `
  --python assets/code/settlement_generator.py -- `
  --config assets/code/presets/civic_city.json `
  --output assets/generated/my_civic_city.blend `
  --layout-output assets/generated/my_civic_city.json `
  --ogre-output assets/generated/my_civic_assets
```

명령행에서 `--grass-density 1.0`, `--no-grass`, `--no-civic`로 덮어쓸 수
있습니다. 완성된 예제는 `civic_city.blend`와 `civic_interiors.blend`입니다.

## 잔디와 물

초지 재질에는 반복 가능한 풀잎 패턴을 넣고, 그 위에 높이가 다른 입체 잎을
만듭니다. 길 바로 옆은 낮고, 보행 구간에서 조금 벗어나면 더 길고 촘촘하게
자랍니다. 급경사, 도로와 출입구, 광장, 건물 기초와 시설은 비워 둡니다.
입체 잎과 작은 야생화는 32m 단위로 묶고, 출력되는 풀잎 수는 도시 면적과
도로 길이에 맞춰 배분합니다. 풀이 없는 설정에서도 바닥 텍스처는 적용됩니다.

분수의 수면과 물줄기도 정적인 메시입니다. 동적 물줄기를 붙일 수 있도록 분수의
효과 위치를 `markers.json`에 저장합니다. 잔디·물·랜턴 발광면에는 충돌을 만들지
않고 우물·분수·가로등 몸체는 정적 충돌에 포함합니다.

## 조각상과 조명

조각상은 만들지 않고 `STATUE_ANCHOR` Empty와 바닥 중심 위치, 회전, 예약 치수를
저장합니다. 나중에 실제 모델을 배치할 공간을 비워 둡니다. 기본 예약 크기는
1.8×1.8×3.2m이며 도시 Empty의 변환은 OGRE 출력 시 반영합니다.

OGRE 패키지에는 다음 파일이 추가됩니다.

- `markers.json`: 모든 시설의 위치·종류·양식, 조각상 예약 공간, 분수 효과 위치.
- `asset_markers.tsv`: C++에서 읽을 조각상 위치·회전·치수·양식.
- `street_lights.tsv`: 실제 점광원의 위치·색·범위.

```cpp
const auto markers = ProceduralAssets::loadAssetMarkers(directory);
// marker.position / orientation / size에 맞춰 완성된 조각상 모델을 배치합니다.

// 야간에 필요한 경우 호출합니다. 낮에는 생략해도 랜턴 모델은 표시됩니다.
ProceduralAssets::loadStreetLights(directory, *sceneManager, *town);
```

발광 재질만으로 주변 물체를 비추지는 않으므로 별도의 점광원 데이터를
제공합니다. [OGRE 재질 문서](https://ogrecave.github.io/ogre/api/14/_material-_scripts.html#emissive)
기준으로 `emissive`를 출력합니다. 넓은 도시에서는 게임의 가시 구역에 맞춰
광원을 활성화하세요. C++ 헬퍼의 SDK 구문 검사를 수행하며 OGRE 런타임의
셰이더·조명·물리 검증은 게임 프로젝트에서 진행해야 합니다.

## 지붕 접합부

주택의 벽·마감·골조·창틀은 두께까지 포함해 지붕의 밑면 안으로 자릅니다.
잘린 부재의 윗면을 닫으며 지붕 테두리와 굴뚝은 별도로 생성합니다. 성은 작은
돌출탑의 벽 끝과 지붕 시작을 같은 높이에 맞추고, 서로 겹치는 지붕 안쪽 면을
제거합니다. 출입문의 벽 구멍도 아치 창틀의 곡선에 맞춥니다.
