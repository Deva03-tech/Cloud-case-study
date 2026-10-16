import math

import numpy as np
import pytest

from src import cost
from src.sim import Policy, ServiceModel, Workload, simulate, standard_policies

CALIB = {s: {"queries": {q: {"warm_s": [m * f for f in (0.9, 1.0, 1.1)],
                             "cold_first_query": {"median_s": 2 * m}}
                         for q, m in (("q01", 0.4 / c), ("q06", 0.05 / c))}}
         for s, c in (("s1", 1), ("s2", 2), ("s4", 4))}


@pytest.fixture(scope="module")
def sm():
    return ServiceModel(CALIB)


def test_power_law_fit_exact_on_ideal_scaling(sm):
    assert sm.b["q01"] == pytest.approx(1.0)
    assert sm.median("q01", 0.5) == pytest.approx(0.8)
    assert sm.median("q06", 2.0) == pytest.approx(0.025)


def test_cold_sample_uses_ratio(sm):
    rng = np.random.default_rng(0)
    assert sm.sample("q06", 1.0, rng, cold=True) / 0.05 == pytest.approx(2.0, rel=0.11)


def test_workload_bursts_and_mean_rate():
    wl = Workload(rate_qps=2, burst_s=100, gap_s=300, horizon_s=1000, first_burst_s=0)
    assert wl.bursts() == [(0, 100), (400, 500), (800, 900)]
    assert wl.mean_rate() == pytest.approx(0.5)


def test_provisioned_bills_whole_horizon(sm):
    wl = Workload(rate_qps=1, burst_s=60, gap_s=600, horizon_s=1800)
    r = simulate(Policy("P", "provisioned", size=2.0), wl, sm, seed=1)
    assert r["compute_vcpu_s"] == pytest.approx(2.0 * 1800)
    assert r["cold_starts"] == 0 and r["n_unfinished"] == 0


def test_serverless_pauses_and_cold_starts(sm):
    wl = Workload(rate_qps=1, burst_s=60, gap_s=900, horizon_s=3000)
    r = simulate(Policy("S", "serverless", tau_s=120, resume_s=15), wl, sm, seed=1)
    assert r["cold_starts"] == len(wl.bursts()) - 1      # first burst finds it warm
    assert r["compute_vcpu_s"] < 4.0 * 3000
    assert r["p99_s"] >= 10                             # resume wait shows in the tail


def test_never_pause_has_no_cold_starts(sm):
    wl = Workload(rate_qps=1, burst_s=60, gap_s=900, horizon_s=3000)
    r = simulate(Policy("S", "serverless", tau_s=math.inf), wl, sm, seed=1)
    assert r["cold_starts"] == 0
    assert r["compute_vcpu_s"] >= 0.25 * 3000 - 1


def test_prewarm_removes_some_cold_starts(sm):
    wl = Workload(rate_qps=1, burst_s=60, gap_s=900, horizon_s=6000)
    base = simulate(Policy("S", "serverless", tau_s=120), wl, sm, seed=2)
    pw = simulate(Policy("S", "serverless", tau_s=120, prewarm=True), wl, sm, seed=2)
    assert pw["cold_starts"] < base["cold_starts"] and pw["prewarms"] > 0


def test_seed_determinism(sm):
    wl = Workload(rate_qps=2, burst_s=60, gap_s=300, horizon_s=1200)
    p = standard_policies(wl, sm)[3]
    assert simulate(p, wl, sm, 7) == simulate(p, wl, sm, 7)


def test_cost_model():
    assert cost.usd_per_vcpu_hour("aurora_serverless_v2") == pytest.approx(0.24)
    assert cost.usd_per_vcpu_hour("rds_postgresql") == pytest.approx(0.084)
    assert cost.cost_usd(3600, "neon_launch") == pytest.approx(0.106)
    assert cost.per_1k_queries(1.0, 500) == pytest.approx(2.0)
    with pytest.raises(ValueError):
        cost.cost_usd(-1, "rds_postgresql")
    for m in ("aurora_serverless_v2", "neon_launch", "rds_postgresql"):
        assert all(s["url"].startswith("https://") and s["accessed"] for s in cost.prices()[m]["sources"])
