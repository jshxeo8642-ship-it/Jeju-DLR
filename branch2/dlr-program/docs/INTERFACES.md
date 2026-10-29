# Branch 2 / Branch 3 입출력 계약 v1.0

설계 기준: `DLR_PROGRAM_ARCHITECTURE_V3.md`. 아직 upstream이 완성되지 않아 정의한 초기 계약입니다.
실제 자료를 받으면 경계 어댑터로 연결할 수 있으며, 이 구현은 원시 자료 전처리·확률모델 학습을 수행하지 않습니다.

## preprocessing → engine: constant_data

JSON 구조의 완전한 예시는 `config/example_ascc430.json`입니다.

- `schema_version`: `"1.0"`
- `conductor`: 이번 선로에 공통으로 쓰는 교체 가능한 도체. 외경 m, 열용량 J/(m·K),
  방사율/흡수율 무차원, 저항 25/75/200°C의 60Hz AC Ω/m.
- `spans`: `{id, name, azimuth_deg, latitude_deg, longitude_deg, elevation_m, initial_temperature_c}`.
  방위는 북쪽 0°, 시계방향. 이번 버전은 수평 경간. 위도·경도는 도 단위.
- `operation`: `slr_current_a`, `max_search_current_a`, `current_tolerance_a`, `integration_step_seconds`.
  전류는 단일 도체에 흐르는 RMS A이며, 전체 회선/다도체 총전류를 그대로 입력하지 않습니다.
- `risk_limits`: `tmax_c`, `max_tmax_probability`(0~1), `degradation_quantile`(0 초과 1 이하),
  `max_additional_degradation`(현재 단위는 기준온도 환산 h).
- `degradation`: `model`, `reference_temperature_c`, `activation_energy_j_mol`, `unit`, 임시 여부.

SLR은 입력된 고정 기준전류입니다. 보수적 기상으로 SLR을 별도 계산하지 않습니다.
초기 도체온도는 모든 시나리오에 경간별 동일하게 사용하며 SLR/DLR 비교에서도 같습니다.
현재 각 경간은 같은 도체 사양을 공유합니다. 경간별 도체가 다른 선로는 계약 확장이 필요합니다.

## weather-model → engine: weather_scenarios_N

```json
{
  "schema_version": "1.0",
  "source_kind": "external",
  "label": "현재 예보 기반 조건부 시나리오",
  "solar_definition": "direct_normal_irradiance_w_m2",
  "scenario_ids": ["s001"],
  "span_ids": ["span-01"],
  "time_edges": ["2026-07-15T09:00:00+09:00", "2026-07-15T10:00:00+09:00"],
  "air_temperature": [[[30.0]]],
  "wind_speed": [[[1.5]]],
  "wind_direction": [[[90.0]]],
  "solar": [[[700.0]]]
}
```

각 기상 배열은 **[시나리오 N][경간 S][기상 구간 K]** 순서이며,
`time_edges` 길이는 K+1입니다. 마지막 경계를 명시하여 마지막 예보값에 임의의 노출시간을 붙이지 않습니다.
예시를 사용할 때 config의 spans도 span-01 하나로 맞춰야 합니다.

| 필드 | 단위·의미 |
|---|---|
| air_temperature | °C |
| wind_speed | m/s, 음수 금지 |
| wind_direction | 북쪽 기준 시계방향 기상학적 ‘불어오는’ 방향, ° |
| solar | 현장 직접법선일사량 DNI, W/m² |

풍향의 180° 반전은 수평 도체 대류각에 영향을 주지 않습니다.
**일사 GHI·누적 MJ/m²는 이 계약의 solar가 아닙니다.** upstream에서 DNI를 제공하거나,
추후 일사 입력 계약과 열해석 어댑터를 함께 확장해야 합니다. 엔진이 암묵적으로 GHI를 DNI로 간주하지 않습니다.
태양 위치와 경간 입사각은 열계산에서 산출합니다. 입력 DNI는 고도 보정 후 현장값으로 보고 추가 고도 보정하지 않습니다.

기상은 각 `[time_edges[k], time_edges[k+1])` 구간에서 일정합니다.
시간별 오차를 새로 뽑지 않으며 공간·시간 의존성은 weather-model이 제공한 전체 trajectory를 그대로 보존합니다.
시나리오 하나는 모든 경간의 공동 기상 실현 하나입니다. 모든 시나리오는 동일 가중치입니다.
비균등 가중치·기간별 다른 표본 구성은 현재 지원하지 않습니다.

결측, NaN, 음수 풍속, 중복 ID, 시간대 없는 시간, 경간 순서·배열 크기 불일치는 오류로 반환합니다.
전처리를 대신해 값 보정·정렬·결측 채우기를 수행하지 않습니다.

## engine → ui

핵심 필드는 설계문서의 `SLR`, `recommended_DLR`, `Tmax_risk`, `degradation_risk_curve`입니다.

- `recommended_DLR`: 안전한 탐색 하한 A, 해가 없으면 null.
- `Tmax_risk`: **시나리오에서 한 번이라도, 어느 경간에서든 Tmax를 초과**한 횟수 / N.
- `additional_degradation_samples[n]`: `max_s(D_I[n,s] - D_SLR[n,s])`.
  경간별 차이를 먼저 구한 후 최악 경간을 선택합니다. 경간 길이로 합산한 선로 총손상이 아닙니다.
- `degradation_risk_curve.threshold`: 중복을 합친 모든 관측 ΔD, 오름차순.
- `cdf`: P(ΔD ≤ threshold).
- `exceedance_probability`: P(ΔD > threshold). 마지막 지점은 경험확률 0이며 실제 확률 0의 증명이 아닙니다.
- 분위수: `sorted_samples[ceil(q*N)-1]`인 역 경험분포. tail 외삽을 하지 않습니다.
- `search.status`: `converged`, `search_cap_reached`, `infeasible`.
- `search.upper_bracket_a`: 수렴 시 불안전 상한. 안전 하한과 차이는 전류 허용오차 이하.
- `infeasible`에서는 DLR=null이며 곡선·온도는 `evaluated_current_a=0`의 진단값입니다.
- `spans`: 경간별 온도 분포, 최대 12개 표시용 trajectory, 풍속·기온 요약, 위험.
- `temperature_bottleneck_span`: 전체 표본·시간에서 최고온도가 발생한 경간.
- `degradation_bottleneck_span`: 선택 분위수의 경간별 추가 열노화가 가장 큰 경간.
- `configuration`, `provenance`, `warnings`: 재현 및 임시 가정 기록.

N개 경험분포의 해상도는 1/N입니다. q99.99 입력은 가능하지만 해당 tail 표본이 부족하면
표본 최댓값을 보여주며 정밀한 0.01% 위험 추정이라고 주장하지 않습니다.

## 로컬 HTTP API

- `GET /api/example`: `{constant_data, weather_scenarios_N}`
- `POST /api/calculate`: 같은 구조 입력, engine 결과 JSON 반환
- `GET /api/health`: 서버 연결 확인
- 잘못된 입력 400, 계산 중 중복 요청 409, 32 MB 초과 입력 413.
- 127.0.0.1에만 바인딩하며 UI는 외부 CDN·서비스를 사용하지 않습니다.

최대 N=10,000, 경간=30, 구간=288, 기간=48h. 배열 원소 수·상태 적분 횟수의 별도 한계를 검사합니다.
이는 로컬 프로토타입의 계산량 제한이며 확률모델의 통계적 요구조건을 의미하지 않습니다.
