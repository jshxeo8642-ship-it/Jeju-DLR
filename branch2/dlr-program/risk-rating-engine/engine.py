"""Branch 2 public API: run_engine(constant_data, weather_scenarios_N)."""
from datetime import timedelta, timezone, datetime
import hashlib
import json
import time
import numpy as np

from contracts import validate_config, parse_weather
from degradation import build_model
from thermal import simulate
from risk import evaluate, empirical_quantile, risk_curve
from rating import search_rating


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode("utf-8")).hexdigest()


def bands(values):
    return {"p05": np.quantile(values, 0.05, axis=0).tolist(),
            "p50": np.quantile(values, 0.50, axis=0).tolist(),
            "p95": np.quantile(values, 0.95, axis=0).tolist(),
            "min": np.min(values, axis=0).tolist(), "max": np.max(values, axis=0).tolist()}


def run_fixed_engine(constant_data, weather_scenarios_N, initial_dlr=None, initial_slr=None):
    started = time.perf_counter()
    config = validate_config(constant_data)
    weather = parse_weather(weather_scenarios_N, config)
    model = build_model(config["degradation"])
    limits, op = config["risk_limits"], config["operation"]
    baseline = simulate(op["slr_current_a"], weather, config, model, initial_slr)
    cache, trace = {}, []

    def assess(current):
        if current not in cache:
            thermal = simulate(current, weather, config, model, initial_dlr)
            metrics = evaluate(thermal, baseline, limits)
            record = {"current_a": current, **{key: metrics[key] for key in
                      ("Tmax_risk", "additional_degradation_quantile", "safe", "tmax_safe", "degradation_safe")}}
            cache[current] = record
            trace.append(record)
        return cache[current]

    baseline_risk = assess(op["slr_current_a"])
    search = search_rating(assess, op["max_search_current_a"], op["current_tolerance_a"])
    current = search["current_a"]
    # Infeasible runs expose diagnostic curves at 0 A, never recommend 0 A as safe.
    evaluated_current = 0.0 if current is None else current
    selected = simulate(evaluated_current, weather, config, model, initial_dlr)
    metrics = evaluate(selected, baseline, limits)
    peak_scenario, peak_span = np.unravel_index(np.argmax(selected.maximum), selected.maximum.shape)
    peak_time = weather.times[0] + timedelta(seconds=float(selected.peak_seconds[peak_scenario, peak_span]))
    curve = risk_curve(metrics["delta"])
    warnings = ["열노화는 임시 Arrhenius 모델의 기준온도 환산시간입니다. 실제 강도손실률·단선확률이 아닙니다.",
                "경험확률은 입력 시나리오를 동일 가중치로 집계합니다. 0회 초과가 실제 위험 0을 뜻하지 않습니다.",
                "단면 내 온도를 동일하게 가정하며 물리 기준사례 검증은 수행하지 않았습니다."]
    if weather.source_kind == "synthetic_fixture":
        warnings.append("합성 예제 시나리오입니다. 실제 기상예보·관측 또는 학습된 날씨모델 결과가 아닙니다.")
    if (1 - limits["degradation_quantile"]) * weather.shape[0] < 1:
        warnings.append("선택 분위수의 꼬리 표본이 1개 미만입니다. 표시값은 표본 최댓값이며 극단 꼬리 추정이 아닙니다.")
    if np.any(weather.air_temperature < 15) or np.any(weather.wind_speed > 19):
        warnings.append("일부 기상이 IEEE 738 강제대류 실험 검증 범위 밖에 있습니다(기온 15°C 미만 또는 풍속 19 m/s 초과).")
    if not baseline_risk["safe"]:
        warnings.append("현재 SLR 전류도 이 시나리오·위험기준에서 안전조건을 만족하지 않습니다.")
    if search["status"] == "search_cap_reached":
        warnings.append("설정한 탐색상한까지 안전합니다. 전역 최대 허용전류를 찾았다는 뜻은 아닙니다.")
    if current is None:
        warnings.append("0 A에서도 위험조건을 만족하지 못해 권고 DLR을 산출하지 못했습니다. 그래프는 0 A 진단 결과입니다.")
    span_results = []
    for index, span in enumerate(config["spans"]):
        span_results.append({"id": span["id"], "name": span.get("name", span["id"]),
                             "Tmax_risk": float(metrics["tmax_by_span"][index]),
                             "maximum_temperature_c": float(selected.maximum[:, index].max()),
                             "additional_degradation_quantile": empirical_quantile(metrics["delta_by_span"][:, index], limits["degradation_quantile"]),
                             "dlr_temperature": bands(selected.temperatures[:, index]),
                             "slr_temperature": bands(baseline.temperatures[:, index]),
                             "sample_temperatures": selected.temperatures[:min(12, weather.shape[0]), index].tolist(),
                             "interval_tmax_risk": np.mean(selected.interval_maximum[:, index] > limits["tmax_c"], axis=0).tolist(),
                             "air_temperature": bands(weather.air_temperature[:, index]),
                             "wind_speed": bands(weather.wind_speed[:, index])})
    result = {
        "schema_version": "1.0", "SLR": op["slr_current_a"], "recommended_DLR": current,
        "increase_a": None if current is None else current - op["slr_current_a"],
        "increase_percent": None if current is None else 100 * (current / op["slr_current_a"] - 1),
        "Tmax_risk": metrics["Tmax_risk"], "degradation_risk_curve": curve,
        "additional_degradation_samples": metrics["delta"].tolist(),
        "scenario_ids": list(weather.scenario_ids),
        "additional_degradation_by_span": metrics["delta_by_span"].tolist(),
        "slr_degradation_by_span": baseline.degradation.tolist(),
        "dlr_degradation_by_span": selected.degradation.tolist(),
        "additional_degradation_quantile": metrics["additional_degradation_quantile"],
        "search": search, "search_trace": trace, "safe": metrics["safe"],
        "evaluated_current_a": evaluated_current, "slr_risk": baseline_risk,
        "risk_limits": limits, "degradation_model": config["degradation"],
        "conductor_name": config["conductor"]["name"],
        "scenario_count": weather.shape[0], "source_kind": weather.source_kind, "source_label": weather.label,
        "time_edges": [t.isoformat() for t in weather.times], "spans": span_results,
        "temperature_bottleneck_span": weather.span_ids[peak_span],
        "degradation_bottleneck_span": weather.span_ids[int(np.argmax([s["additional_degradation_quantile"] for s in span_results]))],
        "peak_temperature_c": float(selected.maximum[peak_scenario, peak_span]),
        "peak_scenario_id": weather.scenario_ids[peak_scenario], "peak_time": peak_time.isoformat(),
        "warnings": warnings, "configuration": config,
        "provenance": {"constant_data_sha256": fingerprint(constant_data),
                       "weather_scenarios_sha256": fingerprint(weather_scenarios_N),
                       "created_at": datetime.now(timezone.utc).isoformat(),
                       "physical_validation": "not_performed",
                       "span_aggregation": "scenario-wise max paired span degradation difference; Tmax any span/time",
                       "temperature_assumption": "isothermal conductor, Heun <=10s, interval-constant weather"},
        "elapsed_seconds": round(time.perf_counter() - started, 3)}
    result["initial_dlr_temperature"] = selected.temperatures[:, :, 0].tolist()
    result["initial_slr_temperature"] = baseline.temperatures[:, :, 0].tolist()
    result["end_dlr_temperature"] = selected.temperatures[:, :, -1].tolist()
    result["end_slr_temperature"] = baseline.temperatures[:, :, -1].tolist()
    return result


def run_engine(constant_data, weather_scenarios_N):
    from rolling import run_rolling
    return run_rolling(constant_data, weather_scenarios_N)
