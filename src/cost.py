"""Cost model: list prices from configs/prices.yaml (URL + access date per number).

All capacities are in vCPU-equivalents (see prices.yaml header). Compute only.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

PRICES_PATH = Path(__file__).resolve().parents[1] / "configs" / "prices.yaml"


@lru_cache(maxsize=1)
def prices() -> dict:
    return yaml.safe_load(PRICES_PATH.read_text(encoding="utf-8"))


def usd_per_vcpu_hour(model: str) -> float:
    p = prices()
    if model == "aurora_serverless_v2":
        a = p[model]
        return a["usd_per_acu_hour"] * a["acu_per_vcpu_eq"]
    if model in ("neon_launch", "neon_scale"):
        n = p[model]
        return n["usd_per_cu_hour"] * n["cu_per_vcpu_eq"]
    if model == "rds_postgresql":
        return p[model]["usd_per_vcpu_hour"]
    raise KeyError(model)


def cost_usd(vcpu_seconds: float, model: str, scale: float = 1.0) -> float:
    """Cost of vcpu_seconds of billed capacity under a price model (scale for sensitivity)."""
    if vcpu_seconds < 0:
        raise ValueError("negative vcpu_seconds")
    return vcpu_seconds / 3600.0 * usd_per_vcpu_hour(model) * scale


def per_1k_queries(cost: float, n_queries: int) -> float:
    return float("nan") if n_queries == 0 else cost / n_queries * 1000.0
