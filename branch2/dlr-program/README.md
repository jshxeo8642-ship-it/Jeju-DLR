# 제주 154 kV DLR — Branch 2 / Branch 3

**2026-10-28 V4 적용:** 현재 실행은 1시간씩 위험을 판단하는 24시간 순차 DLR입니다.
과거 SLR 운전 가정의 warm-up 초기화와 시간 선택 UI를 추가했습니다.
최신 계약 및 변경사항은 `docs/V4_IMPLEMENTATION.md`가 우선합니다.

`DLR_PROGRAM_ARCHITECTURE_V3.md`를 기준으로 구현한 위험 기반 DLR 엔진과 로컬 UI입니다.
전처리와 weather-model은 포함하지 않습니다. `data/example_scenarios.json`은
개발 점검용으로 고정해 둔 합성 trajectory이며 실제 예보나 학습모델 출력이 아닙니다.

## 실행

Windows에서 `start.bat`을 더블클릭하거나 다음을 실행합니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

브라우저에서 **http://127.0.0.1:8765**를 엽니다. ‘DLR 계산하기’를 누르면 예제를 계산합니다.
서버 종료는 터미널에서 Ctrl+C입니다. 실행기는 프로젝트 `.venv`, Codex 번들 Python,
일반 `python` 순으로 찾습니다. 일반 Python을 사용할 때에는 Python 3.10 이상과 NumPy가 필요합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python run.py ui
```

계산만 실행하려면:

```powershell
python run.py calculate --config config/example_ascc430.json --weather data/example_scenarios.json --output output/result.json
```

`python` 명령이 Windows Store 별칭을 가리키는 환경에서는 `start.ps1`을 사용하거나 실제 Python 실행파일 경로를 지정하세요.

## 역할과 파일

| 기능 | 위치 |
|---|---|
| IEEE 738 SI 열평형 항 | `risk-rating-engine/ieee738.py` |
| 모든 시나리오의 transient 온도·노출시간 적분 | `risk-rating-engine/thermal.py` |
| 교체 가능한 임시 열노화 모델 | `risk-rating-engine/degradation.py` |
| Tmax 경험확률·추가 열노화 ECDF | `risk-rating-engine/risk.py` |
| 고정 후보전류 UP/DOWN 탐색 | `risk-rating-engine/rating.py` |
| 공통 입출력 연결 | `risk-rating-engine/engine.py`, `contracts.py` |
| 로컬 대시보드·API | `ui/` |
| 도체·경간·위험기준·계수 | `config/example_ascc430.json` |

이 폴더는 작업 시작 시 Git 저장소가 아니었습니다. 브랜치 2/3의 기능 디렉터리를 구현했으며,
Git 초기화·커밋·원격 브랜치 생성은 하지 않았습니다.

## 사용

1. 기본 예제 실행 또는 weather-model이 제공한 시나리오 JSON을 불러옵니다.
2. 설정 JSON에서 도체·경간·SLR·초기온도·열화모델을 지정합니다. 실제 경간 ID와 시나리오 경간 순서가 같아야 합니다.
3. 빠른 설정에서 Tmax, 허용 초과확률, 열화 판정 분위수와 한계를 조절합니다.
4. 계산 결과에서 권고 DLR, SLR 대비 증감, Tmax 위험, 추가 열노화 risk curve를 확인합니다.
5. 원하는 분위수를 입력하거나 로그 확률축을 켭니다. 결과 JSON에 전체 경험분포와 표본을 저장할 수 있습니다.

결과에는 입력·설정 SHA-256, 사용 설정, 임시 가정, 모델 정보가 포함됩니다.
입력이나 설정을 바꾸면 이전 결과를 숨겨 새 조건의 결과와 혼동하지 않도록 했습니다.

## 임시 설정의 교체

- 숫자만 교체: `config/example_ascc430.json`의 `conductor`, `operation`, `risk_limits`, `degradation`.
- 식 교체: `degradation.py`의 `build_model()` 및 `rate_per_hour()` 구현. 상태를 갖는 손상 모델은 `thermal.py`의 누적 호출부도 바꾸어야 합니다.
- 지표가 바뀌면 `unit`, UI 표시, `risk_limits.max_additional_degradation`도 함께 변경합니다.
- 모델은 온도·전류 증가에 대해 손상이 감소하지 않아야 현재 이분 탐색의 가정이 성립합니다.

**현재 열화 출력은 기준온도 환산시간입니다. 강도손실률·단선확률 또는 도체 수명으로 해석하지 않습니다.**
ASCC/TW에 IEEE 1283 Annex C를 직접 대입하지 않았습니다. 도체 제원 중 AC 저항,
코어 비열 등 미확인 값은 명시적인 임시 추정값입니다. 사용자 요청에 따라 물리 기준사례 검증은 수행하지 않았습니다.

## 개발 확인

```powershell
python -m unittest discover -s validation -v
```

Node.js가 설치된 경우 `python run.py calculate` 이후 `node validation/test_ui.cjs`로 UI 로직도 검사할 수 있습니다.

이 검사는 입력 계약, 시나리오 재사용, SLR 비교, 위험 집계, 탐색 경계와 실행 연결을 확인합니다.
IEEE 기준사례 검증이나 실제 운전 안전성 검증을 대체하지 않습니다.

상세: `docs/INTERFACES.md`, `docs/MODEL_NOTES.md`, `docs/IMPLEMENTATION_STATUS.md`.
