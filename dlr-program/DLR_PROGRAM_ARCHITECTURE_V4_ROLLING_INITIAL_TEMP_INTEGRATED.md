# 제주 154 kV 가공송전선 DLR 프로그램 설계안

## 0. 최종 목적

기상예보를 그대로 IEEE 738에 넣는 단순 DLR 계산기가 아니라,

**기상예보 불확실성 → 미래 기상 시나리오 → 도체온도 → 추가 열화 → 리스크 → 허용 가능한 최대 전류**

까지 연결하는 확률·물리 기반 DLR 프로그램을 만든다.

최종적으로 사용자에게 다음을 제시한다.

- 기존 SLR 대비 추가 확보 가능한 송전전류
- 현재 0~1시간에 실제 적용할 권고 DLR
- 향후 24시간의 시간별 DLR trajectory
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
│ 시간별 후보전류 제시          │
│ → IEEE 738 transient          │
│ → 다음 시간 초기상태 갱신     │
│ → 추가 열화 / risk 평가       │
│ → 시간별 전류 UP / DOWN       │
│ → 24h DLR trajectory          │
└───────────────────────────────┘
        │
        ▼
┌───────────────────────────────┐
│ 3. feature/ui                 │
│ 현재 적용 DLR                 │
│ 24h 시간별 DLR trajectory     │
│ Tmax risk / 추가 열화 risk    │
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

미래 기상 시나리오 N개를 이용해 **1시간 단위의 허용전류를 순차적으로 결정하고, 향후 24시간의 DLR trajectory를 만든다.**

예보가 나온 현재 시점에서 0~1시간에 사용할 전류 \(I_1\)을 먼저 결정하고, 그 전류를 실제로 1시간 사용한다고 가정해 각 기상 시나리오의 도체온도를 계산한다.

그 결과를 1~2시간 구간의 초기상태로 이어서 \(I_2\)를 결정하고, 같은 방식으로 \(I_{24}\)까지 반복한다.

즉 최종 출력은 하나의 고정 DLR이 아니라,

```text
I1, I2, I3, ... , I24
```

형태의 **시간별 DLR trajectory**이다.

핵심 구조는 각 시간구간마다 수행하는 UP/DOWN 탐색이다.

```text
현재 도체온도 Ts0
        ↓
[0~1h]
후보전류 I1
        │
        ├─ scenario 1 → Ts1,1(t) → ΔD1,1
        ├─ scenario 2 → Ts1,2(t) → ΔD1,2
        ...
        └─ scenario N → Ts1,N(t) → ΔD1,N
        │
        ▼
Risk(I1)
        ↓
안전하면 UP / 위험하면 DOWN
        ↓
0~1h 허용전류 I1 확정
        ↓
각 scenario의 1시간 후 도체온도를
다음 시간의 초기상태로 사용
        ↓
[1~2h]
후보전류 I2
        ↓
같은 방식으로 반복
        ↓
...
        ↓
[23~24h]
I24 확정
        ↓
24시간 DLR trajectory
[I1, I2, ..., I24]
```

각 시간구간에서 제시하는 후보전류는 해당 구간의 N개 기상 시나리오에 동일하게 적용한다.

다만 도체온도는 시나리오마다 서로 다르게 진행되므로, 다음 시간구간에서는 각 시나리오별 이전 시간의 도체온도가 그대로 이어진다.

또한 실제 운영에서는 매시간 새로운 관측값과 예보를 받을 수 있으므로, 다음 시간이 되면 현재 상태를 다시 반영해 남은 24시간 DLR trajectory를 다시 계산하는 **rolling / receding-horizon 방식**으로 사용할 수 있다.

## 4.1 초기도체온도 결정

transient IEEE 738 계산에 필요한 현재 초기도체온도 \(T_{s,0}\)는 과거 기상·전류 이력을 이용해 결정한다.

```text
과거 warm-up 시작시점 설정
        ↓
높은 초기온도 T_high 설정
낮은 초기온도 T_low 설정
        ↓
동일한 과거 기상·전류 이력을 사용해
두 경우 모두 현재 시점까지 forward transient 계산
        ↓
현재 시점에서
|T_high - T_low| ≤ 1.0°C
인지 확인
        ↓
수렴하지 않으면 warm-up 구간을 더 과거로 확장
        ↓
수렴하면 초기조건의 영향이 충분히 사라진 것으로 판단
        ↓
두 결과 중 더 높은 현재 도체온도를
보수적인 T_s,0로 사용
```

- \(T_{high}\): 보수적으로 도체 최고허용온도 \(T_{max}\) 사용
- \(T_{low}\): 현실적인 낮은 초기 도체온도 사용
- 두 경우 모두 같은 과거 기상 및 전류 조건을 적용한다.
- 계산은 과거에서 현재 방향으로 진행하는 forward transient 계산이다.
- 수렴 기준 `1.0°C`는 현재 단계의 임시 engineering threshold이며, 추후 민감도 분석이나 검증 결과에 따라 조정할 수 있다.

## 4.2 온도 계산

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

- hourly candidate current
- initial conductor temperature
- air temperature
- wind speed
- wind direction
- solar
- conductor data
- span direction

출력:

- scenario별 Ts(t)
- 각 시간구간 종료 시 Ts
- max Ts
- Tmax exceedance 여부

시간구간이 끝나면 각 scenario의 종료 도체온도를 다음 시간구간의 초기 도체온도로 전달한다.

## 4.3 추가 열화 계산

같은 미래 기상 scenario에 대해 SLR 운전과 시간별 DLR trajectory 운전을 각각 계산한다.

```text
SLR 운전
→ Ts_SLR(t)
→ D_SLR

시간별 DLR 운전
I1 → I2 → ... → I24
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

## 4.4 안전조건

시간별 DLR trajectory는 기존과 동일하게 최소 두 조건을 만족해야 한다.

```text
P(max Ts > Tmax) ≤ 허용 위험수준
```

그리고

```text
Qp(ΔD) ≤ 허용 추가열화
```

각 시간구간의 후보전류를 조정할 때 위 위험조건을 확인하고, 허용 범위 안에서 전류를 UP/DOWN한다.

## 4.5 추천 파일 구조

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
│   └─ 시간별 후보전류 UP/DOWN 탐색
│
└─ engine.py
    └─ I1 → I2 → ... → I24 순차 계산 및 rolling update
```

필요하면 IEEE 738 수식만 별도로:

```text
ieee738.py
```

---

# 5. Branch 3 — `feature/ui`

## 역할

현재 시점에 실제 적용할 DLR과, 현재 예보를 기준으로 계산한 향후 24시간의 시간별 DLR trajectory를 사용자가 바로 이해할 수 있도록 표시한다.

추천 출력:

```text
현재 SLR
현재 0~1h 적용 권고 DLR
향후 24시간 시간별 DLR trajectory
SLR 대비 시간별 추가전류 / 증가율

Tmax 초과확률

추가 열화 risk curve
- 원하는 q에서 추가 열화 확인
- 필요 시 확률축을 로그 형태로 표시

병목 경간
위험 시간대
```

향후 시간의 DLR은 현재 예보와 현재 도체상태를 기준으로 계산된 값이며, 실제 운영에서는 매시간 새로운 관측값과 예보를 반영해 다시 계산될 수 있음을 구분해 표시한다.

추천 그래프:

- 향후 24시간 시간별 DLR trajectory
- 시간별 SLR vs DLR 비교
- 시간별 기상예보 및 불확실성
- 시간별 도체온도 trajectory
- 추가 열화 분포
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
current_recommended_DLR
hourly_DLR_trajectory_24h
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
→ 0~1h 후보전류 I1 제시
→ N개 scenario에 대해 IEEE 738 transient
→ 도체온도 및 열화 risk 평가
→ 안전하면 UP / 위험하면 DOWN
→ I1 확정
→ 각 scenario의 종료 도체온도를 다음 시간 초기상태로 전달
→ 1~2h 후보전류 I2 결정
→ 같은 방식으로 I24까지 순차 반복
→ 24시간 DLR trajectory [I1, I2, ..., I24]
→ 실제 운영 시 매시간 현재상태와 새 예보로 trajectory 재계산

[Branch 3 — ui]
→ 현재 적용 DLR + 24시간 시간별 DLR trajectory 표시
→ Tmax risk + 추가 열화 risk 표시
```

한 문장으로:

> **예보의 불확실성과 도체의 열적 상태·열화를 함께 고려하여, 매시간 현재 상태를 갱신하면서 향후 시간별로 안전하게 허용할 수 있는 전류를 제시하는 확률·물리 기반 rolling DLR 프로그램**

---

# 9. 현재 핵심 연구 포인트

1. 어떤 조건이 예보오차분포를 실제로 변화시키는가?
2. 조건부 오차분포를 어떤 구조로 표현할 것인가?
3. 극단오차뿐 아니라 위험오차의 지속성을 어떻게 trajectory에 반영할 것인가?
4. q99.9 / q99.99 수준의 위험 tail을 어디에서 모델링할 것인가?
5. 시간별 DLR trajectory에서 이전 시간의 도체온도와 열화를 다음 시간 판단에 어떻게 연결할 것인가?
6. IEEE 1283 기반 추가 열화를 어떤 물리량으로 정의할 것인가?
7. Tmax risk와 추가열화 risk의 허용기준을 어떻게 정할 것인가?
8. 5년 historical backtest에서 확률예측이 실제로 calibration되는가?
