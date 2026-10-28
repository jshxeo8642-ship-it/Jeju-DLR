"""Strict, unit-explicit boundary between preprocessing/weather-model and Branch 2."""
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path

import numpy as np


def load_json(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        return json.load(stream)


def number(value, name, lower=None, upper=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
        raise ValueError(f"{name}: 유한한 숫자가 필요합니다.")
    if lower is not None and value < lower or upper is not None and value > upper:
        raise ValueError(f"{name}: 허용 범위 {lower} ~ {upper}를 벗어났습니다.")
    return float(value)


def validate_config(config):
    if config.get("schema_version") != "1.0":
        raise ValueError("constant_data.schema_version은 1.0이어야 합니다.")
    c = config["conductor"]
    if not isinstance(c["name"], str) or not c["name"]:
        raise ValueError("도체 이름이 필요합니다.")
    number(c["diameter_m"], "diameter_m", 0.001, 0.15)
    number(c["heat_capacity_j_m_k"], "heat_capacity_j_m_k", 1, 100000)
    for name in ("emissivity", "absorptivity"):
        number(c[name], name, 0, 1)
    r = c["resistance"]
    if r["frequency_hz"] != 60:
        raise ValueError("현재 도체 설정은 60 Hz AC 저항을 사용합니다.")
    vals = [number(r[k], k, 1e-9, 0.1) for k in ("r25_ohm_m", "r75_ohm_m", "r200_ohm_m")]
    if not vals[0] <= vals[1] <= vals[2]:
        raise ValueError("저항은 온도에 대해 단조 증가해야 합니다.")
    spans = config["spans"]
    if not isinstance(spans, list) or not 1 <= len(spans) <= 30:
        raise ValueError("경간 수는 1~30개여야 합니다.")
    ids = [s["id"] for s in spans]
    if any(not isinstance(x, str) or not x for x in ids) or len(set(ids)) != len(ids):
        raise ValueError("span id는 중복 없는 문자열이어야 합니다.")
    for s in spans:
        for k, lo, hi in (("azimuth_deg", 0, 360), ("latitude_deg", -90, 90),
                          ("longitude_deg", -180, 180), ("elevation_m", -500, 5000),
                          ("initial_temperature_c", -60, 300)):
            number(s[k], f"{s['id']}.{k}", lo, hi)
    op = config["operation"]
    number(op["slr_current_a"], "slr_current_a", 0.001, 10000)
    number(op["max_search_current_a"], "max_search_current_a", 0.001, 10000)
    number(op["current_tolerance_a"], "current_tolerance_a", 0.01, 100)
    number(op["integration_step_seconds"], "integration_step_seconds", 0.1, 10)
    limits = config["risk_limits"]
    number(limits["tmax_c"], "tmax_c", -50, 300)
    number(limits["max_tmax_probability"], "max_tmax_probability", 0, 1)
    number(limits["degradation_quantile"], "degradation_quantile", 0.000001, 1)
    number(limits["max_additional_degradation"], "max_additional_degradation", 0, 1e9)
    d = config["degradation"]
    if d["model"] != "arrhenius_equivalent_hours":
        raise ValueError("지원하지 않는 열화모델입니다. degradation.py의 모델 등록을 확인하세요.")
    number(d["reference_temperature_c"], "reference_temperature_c", -50, 300)
    number(d["activation_energy_j_mol"], "activation_energy_j_mol", 1, 300000)
    if d.get("unit") != "equivalent_hours":
        raise ValueError("현재 모델의 단위는 equivalent_hours입니다.")
    return config


@dataclass(frozen=True)
class WeatherScenarios:
    scenario_ids: tuple
    span_ids: tuple
    times: tuple
    durations: np.ndarray
    air_temperature: np.ndarray
    wind_speed: np.ndarray
    wind_direction: np.ndarray
    solar: np.ndarray
    source_kind: str
    label: str

    @property
    def shape(self):
        return self.air_temperature.shape


def parse_weather(payload, config):
    if payload.get("schema_version") != "1.0":
        raise ValueError("weather_scenarios_N.schema_version은 1.0이어야 합니다.")
    if payload.get("solar_definition") != "direct_normal_irradiance_w_m2":
        raise ValueError("solar는 직접법선일사량(DNI, W/m²)이어야 합니다. GHI를 그대로 넣지 마세요.")
    ids = payload["scenario_ids"]
    spans = payload["span_ids"]
    if not isinstance(ids, list) or not 1 <= len(ids) <= 10000:
        raise ValueError("시나리오는 1~10000개여야 합니다.")
    if any(not isinstance(x, str) or not x for x in ids) or len(set(ids)) != len(ids):
        raise ValueError("scenario_ids는 중복 없는 문자열이어야 합니다.")
    if spans != [s["id"] for s in config["spans"]]:
        raise ValueError("span_ids와 constant_data의 경간 순서가 일치해야 합니다.")
    times = tuple(datetime.fromisoformat(t.replace("Z", "+00:00")) for t in payload["time_edges"])
    if not 2 <= len(times) <= 289 or any(t.tzinfo is None or t.utcoffset() is None for t in times):
        raise ValueError("time_edges는 시간대가 있는 ISO 시각 2~289개여야 합니다.")
    durations = np.array([(b.timestamp() - a.timestamp()) for a, b in zip(times, times[1:])])
    if np.any(durations <= 0) or durations.sum() > 48 * 3600:
        raise ValueError("시각은 증가해야 하며 예측구간은 최대 48시간입니다.")
    shape = (len(ids), len(spans), len(durations))
    if np.prod(shape) > 2000000:
        raise ValueError("입력 크기가 너무 큽니다(N × 경간 × 시간 <= 2,000,000).")
    # Prevent accidentally launching an unbounded local calculation.
    steps = sum(np.ceil(durations / config["operation"]["integration_step_seconds"]))
    if steps * len(ids) * len(spans) > 50000000:
        raise ValueError("계산량이 큽니다. 시나리오 수·경간 수·기간을 줄이세요(후보당 최대 5천만 상태).")
    arrays = {}
    for key, lo, hi in (("air_temperature", -60, 60), ("wind_speed", 0, 60),
                         ("wind_direction", 0, 360), ("solar", 0, 1600)):
        a = np.asarray(payload[key], dtype=float)
        if a.shape != shape or not np.isfinite(a).all():
            raise ValueError(f"{key}: shape={shape}인 유한한 숫자 배열이 필요합니다.")
        if np.any(a < lo) or np.any(a > hi):
            raise ValueError(f"{key}: 값의 허용 범위는 {lo}~{hi}입니다.")
        a.setflags(write=False)
        arrays[key] = a
    durations.setflags(write=False)
    source = payload.get("source_kind", "external")
    if source not in ("synthetic_fixture", "external"):
        raise ValueError("source_kind는 synthetic_fixture 또는 external입니다.")
    return WeatherScenarios(tuple(ids), tuple(spans), times, durations, **arrays,
                            source_kind=source, label=str(payload.get("label", "외부 시나리오")))
