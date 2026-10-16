"""Discrete-event simulator (SimPy) of a provisioned or serverless PostgreSQL service.

Capacity c is in vCPU-equivalents (configs/prices.yaml). A system with capacity c runs
k = max(1, round(c)) queries at once (FIFO queue); a query's service time is sampled
from the Docker calibration (results/calib_docker.json) at size c: the measured warm
samples at c in {1, 2, 4}, otherwise a per-query power law a_q * c^-b_q fitted to the
three warm medians, times a multiplicative noise draw from the measured samples. The
first execution of each query type after a (re)start uses the measured cold/warm ratio.

Serverless: 1-s controller; target capacity = clamp(queries in system, c_min, c_max);
scale up doubles c (at least +0.5) every d_up seconds while below target; scale down
halves c after `cooldown_s` with target below c. After tau seconds with nothing in
the system the service pauses (c = 0, nothing billed); the next arrival triggers a
resume of resume_s seconds (a cold start), billed at c_min, after which caches are
cold. Billing: integral of c over time while not paused (per second).
Provisioned: fixed c (or a known schedule), always billed.
"""
from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import simpy

CALIB_PATH = Path(__file__).resolve().parents[1] / "results" / "calib_docker.json"
SIZE_VCPU = {"s1": 1.0, "s2": 2.0, "s4": 4.0}


# --- calibration-driven service times -----------------------------------------------

class ServiceModel:
    def __init__(self, calib: dict):
        self.queries = sorted(calib["s1"]["queries"])
        self.sizes = sorted(SIZE_VCPU[s] for s in calib)
        self.warm, self.med, self.cold_ratio = {}, {}, {}
        for s, d in calib.items():
            c = SIZE_VCPU[s]
            for q, v in d["queries"].items():
                w = np.array(v["warm_s"], dtype=float)
                self.warm[(q, c)] = w
                self.med[(q, c)] = float(np.median(w))
                self.cold_ratio[(q, c)] = max(1.0, v["cold_first_query"]["median_s"] / float(np.median(w)))
        self.a, self.b = {}, {}
        x = np.log(self.sizes)
        for q in self.queries:
            y = np.log([self.med[(q, c)] for c in self.sizes])
            slope, icpt = np.polyfit(x, y, 1)
            self.b[q] = float(min(1.0, max(0.0, -slope)))
            self.a[q] = float(math.exp(icpt))
        # pooled noise: sample / median at the same size
        self.noise = np.concatenate([self.warm[k] / self.med[k] for k in self.warm])

    @classmethod
    def from_file(cls, path: Path = CALIB_PATH) -> "ServiceModel":
        return cls(json.loads(path.read_text(encoding="utf-8"))["data"])

    def nearest(self, c: float) -> float:
        return min(self.sizes, key=lambda s: abs(math.log(s) - math.log(max(c, 1e-6))))

    def median(self, q: str, c: float) -> float:
        if c in SIZE_VCPU.values() and (q, c) in self.med:
            return self.med[(q, c)]
        return self.a[q] * c ** (-self.b[q])

    def sample(self, q: str, c: float, rng: np.random.Generator, cold: bool = False) -> float:
        if (q, c) in self.warm:
            s = float(rng.choice(self.warm[(q, c)]))
        else:
            s = self.median(q, c) * float(rng.choice(self.noise))
        if cold:
            s *= self.cold_ratio[(q, self.nearest(c))]
        return s

    def mix_mean(self, c: float) -> float:
        return float(np.mean([self.median(q, c) for q in self.queries]))


# --- workload -------------------------------------------------------------------------

@dataclass(frozen=True)
class Workload:
    rate_qps: float          # Poisson rate during a burst
    burst_s: float = 300.0
    gap_s: float = 1200.0    # idle gap between bursts
    horizon_s: float = 10800.0
    first_burst_s: float = 60.0

    def bursts(self) -> list[tuple[float, float]]:
        out, t = [], self.first_burst_s
        while t < self.horizon_s:
            out.append((t, min(t + self.burst_s, self.horizon_s)))
            t += self.burst_s + self.gap_s
        return out

    def mean_rate(self) -> float:
        return self.rate_qps * self.burst_s / (self.burst_s + self.gap_s)


def arrivals(wl: Workload, queries: list[str], rng: np.random.Generator) -> list[tuple[float, str]]:
    out = []
    for a, b in wl.bursts():
        n = rng.poisson(wl.rate_qps * (b - a))
        ts = np.sort(rng.uniform(a, b, n))
        qs = rng.choice(queries, n)
        out.extend(zip(ts.tolist(), qs.tolist()))
    return out


# --- policies -------------------------------------------------------------------------

@dataclass(frozen=True)
class Policy:
    name: str
    kind: str                       # "provisioned" | "serverless"
    size: float = 4.0               # provisioned capacity (vCPU)
    scheduled: bool = False         # provisioned: size in bursts, idle_size between
    idle_size: float = 1.0
    tau_s: float = 300.0            # serverless idle timeout (inf = never pause)
    c_min: float = 0.25             # serverless minimum while active (0.5 ACU)
    c_max: float = 4.0
    resume_s: float = 15.0          # Aurora docs: ~15 s typical resume
    d_up_s: float = 5.0
    cooldown_s: float = 60.0
    prewarm: bool = False
    prewarm_margin_s: float = 5.0
    price_model: str = "rds_postgresql"


def provisioned_mean_size(wl: Workload, sm: ServiceModel, rho_max: float = 0.7) -> float:
    """Smallest calibrated size whose utilisation at the mean arrival rate is <= rho_max."""
    for c in sm.sizes:
        if wl.mean_rate() * sm.mix_mean(c) / max(1, round(c)) <= rho_max:
            return c
    return sm.sizes[-1]


def standard_policies(wl: Workload, sm: ServiceModel, tau_tuned_s: float | None = None) -> list[Policy]:
    srv = dict(kind="serverless", price_model="aurora_serverless_v2")
    pols = [
        Policy("P-peak", "provisioned", size=4.0),
        Policy("P-mean", "provisioned", size=provisioned_mean_size(wl, sm)),
        Policy("P-sched", "provisioned", size=4.0, scheduled=True, idle_size=1.0),
        Policy("S-default", tau_s=300.0, **srv),
        Policy("S-floor", tau_s=math.inf, **srv),
        Policy("S-prewarm", tau_s=300.0, prewarm=True, **srv),
    ]
    if tau_tuned_s is not None:
        pols.append(Policy("S-tuned", tau_s=tau_tuned_s, **srv))
    return pols


# --- simulation -------------------------------------------------------------------------

@dataclass
class _State:
    c: float
    status: str = "active"           # active | paused | resuming
    busy: int = 0
    queue: deque = field(default_factory=deque)
    billed: float = 0.0              # vCPU-seconds
    busy_s: float = 0.0              # server-seconds actually serving
    last_t: float = 0.0
    idle_since: float | None = 0.0
    resume_ev: object = None
    warm_types: set = field(default_factory=set)
    cold_starts: int = 0
    prewarms: int = 0
    last_up: float = -1e9
    below_since: float | None = None


def simulate(policy: Policy, wl: Workload, sm: ServiceModel, seed: int,
             rtt_s: float = 0.0, keep_latencies: bool = False,
             trace: list[tuple[float, str]] | None = None) -> dict:
    """trace: fixed (time, query) arrivals (validation replay); default draws from wl."""
    rng = np.random.default_rng(seed)
    arr = trace if trace is not None else arrivals(wl, sm.queries, np.random.default_rng(seed + 10_000))
    env = simpy.Environment()
    serverless = policy.kind == "serverless"
    bursts = wl.bursts()

    def prov_size(t: float) -> float:
        if not policy.scheduled:
            return policy.size
        return policy.size if any(a <= t < b for a, b in bursts) else policy.idle_size

    st = _State(c=policy.c_min if serverless else prov_size(0.0))
    st.warm_types = set(sm.queries)  # start warm
    lat: list[float] = []

    def accrue():
        if st.status != "paused":
            st.billed += st.c * (env.now - st.last_t)
        st.last_t = env.now

    def k() -> int:
        return max(1, round(st.c))

    def dispatch():
        while st.queue and st.status == "active" and st.busy < k():
            job = st.queue.popleft()
            st.busy += 1
            st.idle_since = None
            env.process(serve(job))

    def serve(job):
        q, done = job
        cold = q not in st.warm_types
        st.warm_types.add(q)
        s = sm.sample(q, st.c, rng, cold=cold)
        st.busy_s += s
        yield env.timeout(s)
        st.busy -= 1
        if st.busy == 0 and not st.queue:
            st.idle_since = env.now
        done.succeed()
        dispatch()

    def resume(prewarm: bool):
        accrue()
        st.status, st.c = "resuming", policy.c_min
        st.resume_ev = env.event()
        if prewarm:
            st.prewarms += 1
        else:
            st.cold_starts += 1
        yield env.timeout(policy.resume_s)
        accrue()
        st.status = "active"
        st.warm_types = set()            # caches are cold after a resume
        st.idle_since = env.now if (st.busy == 0 and not st.queue) else None
        ev, st.resume_ev = st.resume_ev, None
        ev.succeed()
        dispatch()

    def query(t: float, q: str):
        yield env.timeout(t - env.now)
        t0 = env.now
        st.idle_since = None
        if st.status == "paused":
            env.process(resume(prewarm=False))
        if st.status == "resuming":
            yield st.resume_ev
        done = env.event()
        st.queue.append((q, done))
        dispatch()
        yield done
        lat.append(env.now - t0 + rtt_s)

    def controller():
        while True:
            yield env.timeout(1.0)
            if not serverless:
                c = prov_size(env.now)
                if c != st.c:
                    accrue()
                    st.c = c
                    dispatch()
                continue
            if st.status != "active":
                continue
            n = st.busy + len(st.queue)
            if n == 0 and st.idle_since is not None and env.now - st.idle_since >= policy.tau_s:
                accrue()
                st.status, st.c = "paused", 0.0
                continue
            target = min(policy.c_max, max(policy.c_min, float(n)))
            if target > st.c and env.now - st.last_up >= policy.d_up_s:
                accrue()
                st.c = min(target, max(2 * st.c, st.c + 0.5))
                st.last_up = env.now
                st.below_since = None
                dispatch()
            elif target < st.c:
                if st.below_since is None:
                    st.below_since = env.now
                elif env.now - st.below_since >= policy.cooldown_s:
                    accrue()
                    st.c = max(target, st.c / 2)
                    st.below_since = env.now
            else:
                st.below_since = None

    def wake_at(t: float):
        if t > env.now:
            yield env.timeout(t - env.now)
        if st.status == "paused":
            yield from resume(prewarm=True)

    for t, q in arr:
        env.process(query(t, q))
    env.process(controller())
    if serverless and policy.prewarm:
        # Schedule wake-ups lazily: each burst start seen (by arrival time) schedules the next.
        def prewarm_driver():
            starts: list[float] = []
            last = -1e9
            for t, _ in arr:
                if t - last >= 30.0:
                    if t > env.now:
                        yield env.timeout(t - env.now)
                    starts.append(t)
                    if len(starts) >= 2:
                        nxt = starts[-1] + float(np.mean(np.diff(starts[-4:])))
                        env.process(wake_at(nxt - policy.resume_s - policy.prewarm_margin_s))
                last = t
        env.process(prewarm_driver())
    env.run(until=wl.horizon_s)
    accrue()
    billed = st.billed
    env.run(until=wl.horizon_s + 3600.0)  # drain the backlog; billing stops at the horizon

    lat_a = np.array(lat) if lat else np.array([np.nan])
    out = {
        "n_queries": len(lat), "n_arrivals": len(arr), "n_unfinished": len(arr) - len(lat),
        "p50_s": float(np.percentile(lat_a, 50)), "p95_s": float(np.percentile(lat_a, 95)),
        "p99_s": float(np.percentile(lat_a, 99)), "mean_s": float(np.mean(lat_a)),
        "compute_vcpu_s": billed, "busy_server_s": st.busy_s,
        "cold_starts": st.cold_starts, "prewarms": st.prewarms,
    }
    if keep_latencies:
        out["latencies"] = lat
    return out


def with_tau(p: Policy, tau_s: float, name: str | None = None) -> Policy:
    return replace(p, tau_s=tau_s, name=name or p.name)
