"""Software/contract tests only. These do not certify the physical model."""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "risk-rating-engine"))
from contracts import load_json, validate_config, parse_weather
from degradation import build_model
from thermal import simulate, ThermalResult
from risk import evaluate, risk_curve, empirical_quantile
from rating import search_rating
from engine import run_fixed_engine as run_engine


def fixture():
    config = copy.deepcopy(load_json(ROOT / "config/example_ascc430.json"))
    config["operation"]["max_search_current_a"] = 1000
    config["operation"]["current_tolerance_a"] = 5
    data = load_json(ROOT / "data/example_scenarios.json")
    data["scenario_ids"] = data["scenario_ids"][:4]
    start = datetime.fromisoformat(data["time_edges"][0])
    data["time_edges"] = [(start + timedelta(minutes=5*i)).isoformat() for i in range(4)]
    for field in ("air_temperature", "wind_speed", "wind_direction", "solar"):
        data[field] = [[span[:3] for span in scenario] for scenario in data[field][:4]]
    return config, data


class ContractsTest(unittest.TestCase):
    def setUp(self):
        self.config, self.data = fixture()

    def test_valid_and_readonly(self):
        w = parse_weather(self.data, validate_config(self.config))
        self.assertEqual(w.shape, (4,2,3))
        with self.assertRaises(ValueError): w.wind_speed[0,0,0] = 1

    def test_example_resistance_matches_documented_estimate(self):
        r = self.config["conductor"]["resistance"]
        for t in (25,75,200):
            self.assertAlmostEqual(r[f"r{t}_ohm_m"], .0668/1000*(1+.00403*(t-20))*1.02, places=12)

    def test_missing_negative_or_nonfinite_weather_rejected(self):
        for bad in (-1,float("nan"),float("inf")):
            self.data["wind_speed"][0][0][0] = bad
            with self.assertRaises(ValueError): parse_weather(self.data,self.config)

    def test_misaligned_shape_rejected(self):
        self.data["solar"][0][0].pop()
        with self.assertRaises(ValueError): parse_weather(self.data,self.config)

    def test_duplicate_scenario_rejected(self):
        self.data["scenario_ids"][1] = self.data["scenario_ids"][0]
        with self.assertRaises(ValueError): parse_weather(self.data,self.config)

    def test_span_order_rejected(self):
        self.data["span_ids"].reverse()
        with self.assertRaises(ValueError): parse_weather(self.data,self.config)

    def test_time_zone_and_time_order_required(self):
        original = self.data["time_edges"][:]
        self.data["time_edges"][0] = "2026-07-15T09:00:00"
        with self.assertRaises(ValueError): parse_weather(self.data,self.config)
        self.data["time_edges"] = original[::-1]
        with self.assertRaises(ValueError): parse_weather(self.data,self.config)

    def test_ghi_rejected(self):
        self.data["solar_definition"] = "GHI"
        with self.assertRaises(ValueError): parse_weather(self.data,self.config)

    def test_bad_risk_limits_and_step_rejected(self):
        self.config["risk_limits"]["degradation_quantile"] = 0
        with self.assertRaises(ValueError): validate_config(self.config)
        self.config["risk_limits"]["degradation_quantile"] = .95
        self.config["operation"]["integration_step_seconds"] = 60
        with self.assertRaises(ValueError): validate_config(self.config)


class RiskTest(unittest.TestCase):
    def test_ecdf_ties_strict_exceedance(self):
        curve = risk_curve(np.array([0,0,1,3]))
        self.assertEqual(curve["threshold"], [0,1,3])
        self.assertEqual(curve["exceedance_probability"], [.5,.25,0])
        self.assertEqual(empirical_quantile([0,0,1,3],.5),0)
        self.assertEqual(empirical_quantile([0,0,1,3],.9999),3)

    def test_pair_spans_before_aggregation(self):
        # max(DLR-SLR)=3; max(DLR)-max(SLR)=2 would be the wrong pairing.
        base = ThermalResult(None,np.array([[80.,80.]]),None,np.array([[10.,1.]]),None)
        candidate = ThermalResult(None,np.array([[85.,85.]]),None,np.array([[12.,4.]]),None)
        m = evaluate(candidate,base,{"tmax_c":85,"max_tmax_probability":0,"degradation_quantile":1,"max_additional_degradation":3})
        self.assertEqual(m["delta"].tolist(),[3])
        self.assertEqual(m["Tmax_risk"],0)  # strictly > Tmax, not >=
        self.assertTrue(m["safe"])

    def test_any_span_exceedance_is_per_scenario(self):
        base=ThermalResult(None,np.zeros((2,2)),None,np.zeros((2,2)),None)
        candidate=ThermalResult(None,np.array([[101,101],[90,90]]),None,np.zeros((2,2)),None)
        m=evaluate(candidate,base,{"tmax_c":100,"max_tmax_probability":.5,"degradation_quantile":1,"max_additional_degradation":0})
        self.assertEqual(m["Tmax_risk"],.5)

    def test_search_boundary_cap_and_infeasible(self):
        r=search_rating(lambda i:{"safe":i<=712.3},1000,.1)
        self.assertLessEqual(r["current_a"],712.3)
        self.assertLessEqual(712.3-r["current_a"],.1)
        self.assertEqual(search_rating(lambda i:{"safe":True},1000,1)["status"],"search_cap_reached")
        r=search_rating(lambda i:{"safe":False},1000,1)
        self.assertIsNone(r["current_a"])


class EngineIntegrationTest(unittest.TestCase):
    def test_same_current_has_zero_additional_degradation(self):
        c,d=fixture(); w=parse_weather(d,c); model=build_model(c["degradation"])
        a=simulate(c["operation"]["slr_current_a"],w,c,model)
        b=simulate(c["operation"]["slr_current_a"],w,c,model)
        self.assertTrue(np.array_equal(a.temperatures,b.temperatures))
        self.assertTrue(np.array_equal(a.degradation,b.degradation))
        self.assertTrue(np.all(evaluate(a,b,c["risk_limits"])["delta"]==0))

    def test_fixed_scenarios_repeatable_and_no_mutation(self):
        c,d=fixture(); before=json.dumps([c,d],sort_keys=True)
        a=run_engine(c,d); b=run_engine(c,d)
        for key in ("recommended_DLR","additional_degradation_samples","search_trace"):
            self.assertEqual(a[key],b[key])
        self.assertEqual(before,json.dumps([c,d],sort_keys=True))
        json.dumps(a,allow_nan=False)

    def test_current_increase_orders_temperature_and_dose(self):
        c,d=fixture(); w=parse_weather(d,c); model=build_model(c["degradation"])
        low=simulate(500,w,c,model); high=simulate(800,w,c,model)
        self.assertTrue(np.all(high.temperatures >= low.temperatures-1e-9))
        self.assertTrue(np.all(high.degradation >= low.degradation))

    def test_initial_temperature_is_in_risk(self):
        c,d=fixture(); c["spans"][0]["initial_temperature_c"]=130
        r=run_engine(c,d)
        self.assertEqual(r["search"]["status"],"infeasible")
        self.assertIsNone(r["recommended_DLR"])
        self.assertEqual(r["Tmax_risk"],1)

    def test_two_independent_constraints(self):
        c,d=fixture(); c["risk_limits"]["tmax_c"]=300
        c["risk_limits"]["max_additional_degradation"]=0
        r=run_engine(c,d)
        self.assertLessEqual(r["recommended_DLR"],c["operation"]["slr_current_a"])
        self.assertTrue(any(not t["degradation_safe"] for t in r["search_trace"]))
        c["risk_limits"]["max_additional_degradation"]=1e9
        c["risk_limits"]["tmax_c"]=55
        c["risk_limits"]["max_tmax_probability"]=0
        r=run_engine(c,d)
        self.assertTrue(any(not t["tmax_safe"] for t in r["search_trace"]))

    def test_negative_delta_is_retained_below_slr(self):
        c,d=fixture(); c["operation"]["max_search_current_a"]=100
        r=run_engine(c,d)
        self.assertEqual(r["search"]["status"],"search_cap_reached")
        self.assertTrue(all(v<0 for v in r["additional_degradation_samples"]))

    def test_interval_maxima_include_interior_peak(self):
        c,d=fixture(); w=parse_weather(d,c); model=build_model(c["degradation"])
        result=simulate(600,w,c,model)
        self.assertTrue(np.all(result.maximum >= np.max(result.temperatures,axis=2)))
        self.assertTrue(np.all(result.interval_maximum >= result.temperatures[:,:,1:]))
        self.assertTrue(np.all(result.peak_seconds <= sum(w.durations)+1e-6))


if __name__ == "__main__":
    unittest.main()
