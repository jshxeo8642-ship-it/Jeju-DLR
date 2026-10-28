"""Empirical risk distributions; scenarios have equal weights, no tail extrapolation."""
import numpy as np


def empirical_quantile(samples, probability):
    values = np.sort(np.asarray(samples, dtype=float))
    if values.ndim != 1 or len(values) == 0 or not 0 < probability <= 1:
        raise ValueError("분위수에는 1차원 표본과 0 < q <= 1이 필요합니다.")
    return float(values[max(0, int(np.ceil(probability * len(values))) - 1)])


def risk_curve(samples):
    values, counts = np.unique(samples, return_counts=True)
    cumulative = np.cumsum(counts)
    n = len(samples)
    return {"threshold": values.tolist(), "cdf": (cumulative / n).tolist(),
            "exceedance_probability": ((n - cumulative) / n).tolist(),
            "definition": "P(additional_degradation > threshold)",
            "quantile_method": "inverse_ecdf_nearest_rank", "sample_count": n,
            "probability_resolution": 1 / n, "unit": "equivalent_hours"}


def evaluate(candidate, baseline, limits):
    # Take each scenario's worst paired span difference, not difference of two maxima.
    delta_by_span = candidate.degradation - baseline.degradation
    delta = np.max(delta_by_span, axis=1)
    exceeds = np.any(candidate.maximum > limits["tmax_c"], axis=1)
    probability = float(np.mean(exceeds))
    quantile = empirical_quantile(delta, limits["degradation_quantile"])
    return {"Tmax_risk": probability, "additional_degradation_quantile": quantile,
            "safe": bool(probability <= limits["max_tmax_probability"]
                         and quantile <= limits["max_additional_degradation"]),
            "tmax_safe": bool(probability <= limits["max_tmax_probability"]),
            "degradation_safe": bool(quantile <= limits["max_additional_degradation"]),
            "delta": delta, "delta_by_span": delta_by_span,
            "tmax_by_span": np.mean(candidate.maximum > limits["tmax_c"], axis=0)}
