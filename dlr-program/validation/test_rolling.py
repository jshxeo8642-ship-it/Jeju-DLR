import copy
from datetime import timedelta
import unittest
from unittest.mock import patch
import numpy as np
from test_engine import fixture
from contracts import load_json
from rolling import initialize, window, instant, run_rolling
from pathlib import Path


class RollingTests(unittest.TestCase):
    def test_split_preserves_scenario_identity(self):
        c,d=fixture(); start=instant(d['time_edges'][0])
        w=window(d,start+timedelta(seconds=150),start+timedelta(seconds=450))
        self.assertEqual(w['scenario_ids'],d['scenario_ids'])
        self.assertEqual(len(w['time_edges']),3)
        self.assertEqual(w['wind_speed'][0][0],d['wind_speed'][0][0][:2])

    def test_missing_history_fallback(self):
        c,d=fixture(); d.pop('historical_weather',None); t,info=initialize(c,d)
        self.assertEqual(info['status'],'fallback_missing_history')
        self.assertEqual(t,[c['risk_limits']['tmax_c']]*2)

    def test_warmup_converges_using_slr(self):
        root=Path(__file__).resolve().parents[1]
        c=load_json(root/'config/example_ascc430.json');d=load_json(root/'data/example_scenarios.json')
        t,info=initialize(c,d)
        self.assertEqual(info['status'],'converged')
        self.assertEqual(info['past_current_a'],c['operation']['slr_current_a'])
        self.assertTrue(all(np.isfinite(t)))

    def test_rolls_independent_paths_and_zero_fallback(self):
        root=Path(__file__).resolve().parents[1]
        c=load_json(root/'config/example_ascc430.json');d=load_json(root/'data/example_scenarios.json')
        c['initialization']['mode']='manual'
        calls=[]
        def fake(config,weather,dlr,slr):
            calls.append((copy.deepcopy(dlr),copy.deepcopy(slr)))
            h=len(calls)-1
            return {'evaluated_current_a':0 if h==2 else 700,'search':{'status':'infeasible' if h==2 else 'converged'},
                    'SLR':600,'end_dlr_temperature':[[50+h,60+h]],'end_slr_temperature':[[30+h,40+h]],
                    'provenance':{},'warnings':[]}
        with patch('engine.run_fixed_engine',side_effect=fake): r=run_rolling(c,d)
        self.assertEqual(len(calls),24)
        self.assertEqual(calls[1],([[50,60]],[[30,40]]))
        self.assertEqual(r['hourly_DLR_trajectory_24h'][2],0)
        self.assertEqual(r['hourly_results'][2]['search']['status'],'infeasible')
        self.assertEqual(r['risk_scope'],'individual_hour')

    def test_hour_damage_is_local_not_accumulated(self):
        from engine import run_fixed_engine
        c,d=fixture()
        a=run_fixed_engine(c,d)
        b=run_fixed_engine(c,d,a['end_dlr_temperature'],a['end_slr_temperature'])
        self.assertEqual(b['initial_dlr_temperature'],a['end_dlr_temperature'])
        self.assertEqual(b['initial_slr_temperature'],a['end_slr_temperature'])
        delta=np.array(b['dlr_degradation_by_span'])-np.array(b['slr_degradation_by_span'])
        np.testing.assert_allclose(delta,b['additional_degradation_by_span'])
