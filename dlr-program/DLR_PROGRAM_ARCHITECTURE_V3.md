# 제주 154 kV 가공송전선 DLR 프로그램 설계안

## 0. 최종 목적

기상예보를 그대로 IEEE 738에 넣는 단순 DLR 계산기가 아니라,

**기상예보 불확실성 → 미래 기상 시나리오 → 도체온도 → 추가 열화 → 리스크 → 허용 가능한 최대 전류**

까지 연결하는 확률·물리 기반 DLR 프로그램을 만든다.

최종적으로 사용자에게 다음을 제시한다.

- 기존 SLR 대비 추가 확보 가능한 송전전류
- 최종 권고 DLR
- 도체 최고허용온도 \(T_{\max}\) 초과확률
- SLR 운전 대비 추가 열화량의 확률분포
- 추가 열화의 q99 / q99.9 / q99.99 등 위험 분위수
- 병목 경간 및 위험 시간대

---

# 1. 전체 프로그램 구조

```text
사용자 / 운영 입력
- 대상 선로
- 현재 시각
- 현재 도체온도 또는 초기상태 추정값
- 현재/기준 전류
        │
        ▼
┌───────────────────────────────┐
│ 0. feature/preprocessing      │
│ 원시 예보·관측 데이터         │
│ → 전처리 완료 데이터          │
└───────────────────────────────┘
        │
        ▼
┌───────────────────────────────┐
│ 1. feature/weather-model      │
│ 예보 + 과거 오차              │
│ → 미래 기상 trajectory N개    │
└───────────────────────────────┘
        │
        ▼
┌───────────────────────────────┐
│ 2. feature/risk-rating-engine │
│ 후보전류 제시                 │
│ → IEEE 738 transient          │
│ → 도체온도 trajectory         │
│ → 추가 열화                   │
│ → risk 평가                   │
│ → 전류 UP / DOWN              │
│ → 최종 허용 DLR               │
└───────────────────────────────┘
        │
        ▼
┌───────────────────────────────┐
│ 3. feature/ui                 │
│ DLR / SLR 비교                │
│ Tmax risk                     │
│ 추가 열화 risk                │
│ 결과 시각화                   │
└───────────────────────────────┘
```

---

# 2. Branch 0 — `feature/preprocessing`

## 역할

원시 예보·관측 데이터를 정리해 **weather-model이 바로 사용할 수 있는 전처리 완료 데이터**를 만든다.

- 시간 정렬
- 결측·이상값 처리
- 단위·컬럼 통일
- 예보와 관측 대응
- 도체정보·선로정보·SLR 조건 등 고정 데이터 정리

---

# 3. Branch 1 — `feature/weather-model`

## 역할

**현재 기상예보 조건에서 실제 미래 날씨가 어떻게 달라질 수 있는지 확률적으로 표현하고, 시간적으로 연결된 미래 기상 시나리오 N개를 생성한다.**

최종 출력은 분포함수 자체보다 다음 브랜치가 바로 사용할 수 있는 미래 기상 trajectory가 적합하다.

```text
scenario_id
time
air_temperature
wind_speed
wind_direction
solar
...
```

## 데이터

- 약 5년치 시간자료
- 단기예보 / 초단기예보
- 실제 관측값
- 기온
- 풍속
- 풍향
- 일사 등

예보오차 기본 정의:

```text
error = actual - forecast
```

## 분석 목적

요소별 분포를 따로 만들어 합치는 것이 목적이 아니다.

요소별 분석은 **어떤 조건이 최종 오차분포를 실제로 변화시키는지 찾는 탐색 단계**이다.

후보 요소:

- forecast horizon
- forecast wind speed
- forecast temperature
- season / month
- hour / day-night
- 최근 풍속·기온 변화
- 이전 오차
- 예보 revision
- 풍향
- 강수 / 일사 / 구름 관련 변수
- 관측소 / 공간 조건

확인할 특성:

- 중심 / bias
- 퍼짐 / variance
- skewness
- tail
- multimodality
- 위험오차의 지속시간
- 동일 부호 오차의 연속성

특히 transient DLR에서는 **한 시점의 극단오차만이 아니라, 위험한 오차가 몇 시간 지속되는가**가 중요하다.

## 최종 목표

```text
P(error | current forecast condition)
```

또는 그에 준하는 조건부 확률모델을 만들고, 이를 이용해 미래 기상 trajectory를 생성한다.

가능한 모델 후보:

- Conditional Gaussian
- Distributional regression
- Quantile regression
- 필요 시 skew-t 계열
- KDE: 전체 분포 형태 탐색 / benchmark
- EVT: 극단 tail 보강

KDE나 EVT 중 하나를 무조건 최종 모델로 고정하지 않는다.

전체 분포를 보되, DLR에 중요한 위험 tail과 위험오차 지속성은 별도로 분석한다.

## 시간적 의존성

시간별 오차를 독립적으로 뽑으면 안 된다.

최종 scenario 생성에서는 최소한 다음을 고려한다.

- 시간 autocorrelation
- 위험오차 persistence
- 풍속-기온 dependence
- 필요 시 풍향 / 일사 dependence

---

# 4. Branch 2 — `feature/risk-rating-engine`

## 역할

미래 기상 시나리오 N개에 동일한 후보전류를 적용해,

**온도 → 열화 → 리스크를 계산하고, 안전조건을 만족하는 최대 허용전류를 찾는다.**

핵심 구조는 사실상 UP/DOWN 탐색이다.

```text
후보전류 I
        │
        ├─ scenario 1 → Ts1(t) → ΔD1
        ├─ scenario 2 → Ts2(t) → ΔD2
        ├─ scenario 3 → Ts3(t) → ΔD3
        ...
        └─ scenario N → TsN(t) → ΔDN
        │
        ▼
Risk(I)
- P(max Ts > Tmax)
- 추가 열화 분포
- q99 / q99.9 / q99.99
        │
        ▼
안전조건 만족?
YES → I 증가
NO  → I 감소
        │
        ▼
반복
        │
        ▼
최종 허용 DLR
```

## 3.1 온도 계산

IEEE 738 transient 열평형:

```text
mCp dTs/dt
=
I²R(Ts)
+ q_s
- q_c
- q_r
```

입력:

- candidate current
- initial conductor temperature
- air temperature
- wind speed
- wind direction
- solar
- conductor data
- span direction

출력:

- Ts(t)
- max Ts
- Tmax exceedance 여부

## 3.2 추가 열화 계산

같은 미래 기상 scenario에 대해 SLR과 후보 DLR을 각각 계산한다.

```text
SLR 운전
→ Ts_SLR(t)
→ D_SLR

후보 DLR 운전
→ Ts_DLR(t)
→ D_DLR
```

추가 열화:

```text
ΔD = D_DLR - D_SLR
```

N개 scenario에서:

```text
ΔD1, ΔD2, ..., ΔDN
```

의 확률분포를 얻는다.

최종 표현 예:

```text
99.99%의 시나리오에서
SLR 운전 대비 추가 열화가 X 이하
```

실제 열화 정의와 계산식은 IEEE 1283 및 대상 도체 재료 특성을 기준으로 검증한다.

## 3.3 안전조건

최종 DLR은 최소 두 조건을 동시에 만족해야 한다.

```text
P(max Ts > Tmax) ≤ 허용 위험수준
```

그리고

```text
Qp(ΔD) ≤ 허용 추가열화
```

예:

```text
Q99.99(ΔD) ≤ degradation_limit
```

## 3.4 추천 파일 구조

```text
risk-rating-engine/
│
├─ thermal.py
│   └─ IEEE 738 transient
│
├─ degradation.py
│   └─ Ts(t) → 열화량
│
├─ risk.py
│   └─ Tmax risk / 추가열화 분포
│
├─ rating.py
│   └─ 후보전류 UP/DOWN 탐색
│
└─ engine.py
    └─ 전체 연결
```

필요하면 IEEE 738 수식만 별도로:

```text
ieee738.py
```

---

# 5. Branch 3 — `feature/ui`

## 역할

최종 계산결과를 사용자가 바로 이해할 수 있도록 표시한다.

추천 출력:

```text
현재 SLR
최종 권고 DLR
SLR 대비 추가전류
SLR 대비 증가율

Tmax 초과확률

추가 열화 risk curve
- 원하는 q에서 추가 열화 확인
- 필요 시 확률축을 로그 형태로 표시

병목 경간
위험 시간대
```

추천 그래프:

- 시간별 기상예보 및 불확실성
- 시간별 도체온도 trajectory
- 추가 열화 분포
- SLR vs DLR 비교
- 병목 경간 표시

---

# 6. 추가적으로 필요한 작업

## 6.1 공통 입출력 규격

### preprocessing → weather-model

```text
preprocessed_weather_data
```

### preprocessing → risk-rating-engine

```text
constant_data
```

### weather-model → risk-rating-engine

```text
weather_scenarios_N
```

### risk-rating-engine → ui

```text
SLR
recommended_DLR
Tmax_risk
degradation_risk_curve
```

---

# 7. Git 구조

```text
main
│
├─ feature/preprocessing
│
├─ feature/weather-model
│
├─ feature/risk-rating-engine
│
└─ feature/ui
```

별도 공통 폴더:

```text
validation/
config/
data/
docs/
```

브랜치는 큰 기능 단위로 나누고, 세부 기능은 각 브랜치 안에서 파일로 분리한다.

---

# 8. 프로젝트 핵심 흐름

```text
[Branch 0 — preprocessing]
원시 예보·관측 데이터
→ 전처리 완료 데이터

[Branch 1 — weather-model]
기상예보
→ 예보오차 확률모델
→ 미래 기상 trajectory N개

[Branch 2 — risk-rating-engine]
→ 후보전류 I
→ IEEE 738 transient
→ 도체온도 trajectory N개
→ IEEE 1283 기반 추가 열화 N개
→ Tmax 초과확률 + 추가 열화 분포
→ 안전하면 전류 UP / 위험하면 DOWN
→ 최종 DLR

[Branch 3 — ui]
→ UI 표시
```

한 문장으로:

> **예보의 불확실성과 도체의 열적 열화를 함께 고려하여, 허용 리스크 내에서 기존 SLR보다 얼마나 더 많은 전류를 안전하게 허용할 수 있는지를 제시하는 확률·물리 기반 DLR 프로그램**

---

# 9. 현재 핵심 연구 포인트

1. 어떤 조건이 예보오차분포를 실제로 변화시키는가?
2. 조건부 오차분포를 어떤 구조로 표현할 것인가?
3. 극단오차뿐 아니라 위험오차의 지속성을 어떻게 trajectory에 반영할 것인가?
4. q99.9 / q99.99 수준의 위험 tail을 어디에서 모델링할 것인가?
5. IEEE 1283 기반 추가 열화를 어떤 물리량으로 정의할 것인가?
6. Tmax risk와 추가열화 risk의 허용기준을 어떻게 정할 것인가?
7. 5년 historical backtest에서 확률예측이 실제로 calibration되는가?
