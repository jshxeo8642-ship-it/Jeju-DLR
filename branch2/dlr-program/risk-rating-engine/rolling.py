"""Hourly greedy decisions; each hour has a separate risk budget."""
import copy
from datetime import datetime, timedelta
import time
import numpy as np
from contracts import parse_weather, validate_config, number
from thermal import simulate
from degradation import build_model


def instant(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def window(payload, start, end):
    """Split interval-constant input at exact boundaries without resampling scenarios."""
    edges = [instant(t) for t in payload["time_edges"]]
    if start < edges[0] or end > edges[-1] or start >= end:
        raise ValueError("요청한 시간구간을 입력 기상이 완전히 포함해야 합니다.")
    indices, boundaries = [], [start]
    for j in range(len(edges)-1):
        left, right = max(start, edges[j]), min(end, edges[j+1])
        if right > left:
            indices.append(j)
            boundaries.append(right)
    result = {k:v for k,v in payload.items() if k != "historical_weather"}
    result["time_edges"] = [t.isoformat() for t in boundaries]
    for key in ("air_temperature", "wind_speed", "wind_direction", "solar"):
        result[key] = np.asarray(payload[key])[:, :, indices].tolist()
    return result


def initialize(config, payload):
    settings = config.get("initialization", {})
    mode = settings.get("mode", "warmup")
    tmax = config["risk_limits"]["tmax_c"]
    fallback = [tmax] * len(config["spans"])
    if mode == "manual":
        return [s["initial_temperature_c"] for s in config["spans"]], {"status":"manual"}
    if mode != "warmup":
        raise ValueError("initialization.mode는 warmup 또는 manual입니다.")
    low = number(settings.get("low_temperature_c", 0), "low_temperature_c", -60, tmax)
    tolerance = number(settings.get("tolerance_c", 1), "tolerance_c", .001, 10)
    initial = number(settings.get("start_hours", 1), "start_hours", .01, 48)
    extension = number(settings.get("extension_hours", 1), "extension_hours", .01, 48)
    maximum = number(settings.get("max_hours", 12), "max_hours", initial, 48)
    history = payload.get("historical_weather")
    if history is None:
        return fallback, {"status":"fallback_missing_history", "note":"과거 기상 부재: Tmax 사용"}
    parsed = parse_weather(history, config)
    if parsed.shape[0] != 1 or parsed.times[-1] != instant(payload["time_edges"][0]):
        raise ValueError("historical_weather는 시나리오 1개이며 현재 예측 시작시각에 끝나야 합니다.")
    available = min(maximum, float(parsed.durations.sum()/3600))
    if available < initial:
        return fallback, {"status":"fallback_insufficient_history"}
    attempts = []
    hours = initial
    while True:
        w = parse_weather(window(history, parsed.times[-1]-timedelta(hours=hours), parsed.times[-1]), config)
        model = build_model(config["degradation"])
        high_result = simulate(config["operation"]["slr_current_a"], w, config, model, fallback)
        low_result = simulate(config["operation"]["slr_current_a"], w, config, model, [low]*len(fallback))
        high_end, low_end = high_result.temperatures[0,:,-1], low_result.temperatures[0,:,-1]
        gap = np.abs(high_end-low_end)
        attempts.append({"hours":hours,"gap_c":gap.tolist()})
        if np.all(gap <= tolerance):
            return np.maximum(high_end,low_end).tolist(), {"status":"converged", "attempts":attempts,
                     "past_current_a":config["operation"]["slr_current_a"]}
        if hours >= available:
            return np.maximum(tmax,np.maximum(high_end,low_end)).tolist(), {"status":"fallback_not_converged","attempts":attempts}
        hours = min(hours+extension,available)


def run_rolling(config, payload):
    from engine import run_fixed_engine, fingerprint
    began = time.perf_counter()
    validate_config(config)
    parsed = parse_weather(payload, config)
    if abs(parsed.durations.sum()-86400) > .001:
        raise ValueError("V4는 정확히 24시간 기상 coverage가 필요합니다.")
    first = parsed.times[0]
    initial, initialization = initialize(config,payload)
    dlr_state = slr_state = initial
    hours = []
    for h in range(24):
        part = window(payload,first+timedelta(hours=h),first+timedelta(hours=h+1))
        r = run_fixed_engine(config,part,dlr_state,slr_state)
        r["hour_index"] = h
        r["current_recommended_DLR"] = r["evaluated_current_a"]
        # Zero is an explicit fallback, not a declaration of feasibility.
        r["recommended_DLR"] = r["evaluated_current_a"]
        r["increase_a"] = r["recommended_DLR"]-r["SLR"]
        r["increase_percent"] = 100*r["increase_a"]/r["SLR"]
        dlr_state, slr_state = r["end_dlr_temperature"], r["end_slr_temperature"]
        hours.append(r)
    result = copy.deepcopy(hours[0])
    result["schema_version"] = "2.0"
    result["hourly_results"] = hours
    result["hourly_DLR_trajectory_24h"] = [r["recommended_DLR"] for r in hours]
    result["hourly_time_edges"] = [(first+timedelta(hours=h)).isoformat() for h in range(25)]
    result["initialization"] = {**initialization,"temperature_c":initial}
    result["risk_scope"] = "individual_hour"
    result["provenance"]["weather_scenarios_sha256"] = fingerprint(payload)
    result["warnings"].append("24시간 경로는 매시간 DLR 전부 사용 가정의 전망입니다. 위험 한계는 각 1시간에 적용합니다.")
    if initialization["status"].startswith("fallback"):
        result["warnings"].append("warm-up 미수렴/자료 부족으로 보수적 초기온도 대체값을 사용했습니다.")
    result["elapsed_seconds"] = round(time.perf_counter()-began,3)
    return result
