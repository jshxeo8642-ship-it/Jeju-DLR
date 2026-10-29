"""Vectorized N-scenario, multi-span non-steady heat integration."""
from dataclasses import dataclass
from datetime import timedelta
import math
import numpy as np
from ieee738 import solar_projection, wind_angle_factor, temperature_rate


@dataclass
class ThermalResult:
    temperatures: np.ndarray  # N, span, interval edges
    maximum: np.ndarray      # N, span; includes initial state and every substep
    peak_seconds: np.ndarray
    degradation: np.ndarray  # N, span
    interval_maximum: np.ndarray


def simulate(current_a, weather, config, model, initial_temperature=None):
    if not np.isfinite(current_a) or current_a < 0:
        raise ValueError("후보전류는 0 이상의 유한한 숫자여야 합니다.")
    n, s, k = weather.shape
    spans, conductor = config["spans"], config["conductor"]
    initial = [v["initial_temperature_c"] for v in spans] if initial_temperature is None else initial_temperature
    temperature = np.broadcast_to(initial, (n, s)).astype(float).copy()
    if not np.isfinite(temperature).all():
        raise ValueError("초기온도는 유한해야 합니다.")
    history = np.empty((n, s, k + 1))
    history[:, :, 0] = temperature
    interval_max = np.empty((n, s, k))
    maximum, peak = temperature.copy(), np.zeros((n, s))
    dose = np.zeros((n, s))
    elevation = np.array([v["elevation_m"] for v in spans])
    azimuth = np.array([v["azimuth_deg"] for v in spans])
    elapsed = 0.0
    for j, duration in enumerate(weather.durations):
        steps = math.ceil(duration / config["operation"]["integration_step_seconds"])
        dt = duration / steps
        ambient = weather.air_temperature[:, :, j]
        wind = weather.wind_speed[:, :, j]
        angle = wind_angle_factor(weather.wind_direction[:, :, j], azimuth)
        interval_peak = temperature.copy()
        for index in range(steps):
            instant = weather.times[j] + timedelta(seconds=(index + 0.5) * dt)
            solar_gain = (conductor["absorptivity"] * conductor["diameter_m"]
                          * weather.solar[:, :, j] * solar_projection(instant, spans))
            args = (current_a, ambient, wind, angle, solar_gain, conductor, elevation)
            # Explicit Heun (2nd order); weather is held constant within its interval.
            a = temperature_rate(temperature, *args)
            predictor = temperature + dt * a
            if not np.isfinite(predictor).all() or np.any(predictor < -100) or np.any(predictor > 1000):
                raise ValueError("수치 적분 범위 초과: 탐색상한을 낮추거나 적분 간격을 줄이세요.")
            new_temperature = temperature + 0.5 * dt * (a + temperature_rate(predictor, *args))
            if not np.isfinite(new_temperature).all() or np.any(new_temperature < -100) or np.any(new_temperature > 1000):
                raise ValueError("온도 적분이 안정 범위를 벗어났습니다. 설정을 확인하세요.")
            dose += 0.5 * (model.rate_per_hour(temperature) + model.rate_per_hour(new_temperature)) * dt / 3600
            temperature = new_temperature
            elapsed += dt
            changed = temperature > maximum
            peak = np.where(changed, elapsed, peak)
            maximum = np.maximum(maximum, temperature)
            interval_peak = np.maximum(interval_peak, temperature)
        history[:, :, j + 1] = temperature
        interval_max[:, :, j] = interval_peak
    if not np.isfinite(dose).all():
        raise ValueError("열노화 지표 계산이 유한하지 않습니다.")
    return ThermalResult(history, maximum, peak, dose, interval_max)
