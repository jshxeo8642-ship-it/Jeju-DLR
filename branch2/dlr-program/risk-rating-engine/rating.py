"""Bracketed UP/DOWN search on a fixed scenario set."""


def search_rating(evaluate_current, upper_a, tolerance_a):
    """Return largest feasible lower bracket, or explicit infeasible/capped state.

    Assumes risk constraints are nondecreasing in current for a fixed initial state,
    common scenarios, increasing R(T), and monotonic degradation model.
    """
    low = 0.0
    if not evaluate_current(low)["safe"]:
        return {"status": "infeasible", "current_a": None, "upper_bracket_a": 0.0,
                "iterations": 1}
    if evaluate_current(upper_a)["safe"]:
        return {"status": "search_cap_reached", "current_a": upper_a,
                "upper_bracket_a": None, "iterations": 2}
    high = upper_a
    count = 2
    while high - low > tolerance_a:
        mid = (low + high) / 2
        if evaluate_current(mid)["safe"]:
            low = mid
        else:
            high = mid
        count += 1
    return {"status": "converged", "current_a": low, "upper_bracket_a": high,
            "iterations": count}
