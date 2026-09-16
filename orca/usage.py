"""Live token & cost tracking with an optional hard session cap.

Pricing model (approximate, per 1M tokens):
  * normal input  : full price
  * cache read    : 10% of input price (prompt caching discount)
  * cache write   : 125% of input price (Anthropic cache creation premium)
  * output        : full output price
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .config import model_info


class CostLimitExceeded(Exception):
    pass


class TokenBudgetExceeded(Exception):
    pass


class UsageTracker:
    def __init__(self, max_cost_usd: Optional[float] = None):
        self.max_cost_usd = max_cost_usd
        self.rows: Dict[str, Dict[str, int]] = {}   # "provider/model" -> counters
        self.total_in = 0
        self.total_out = 0
        self.total_cache_read = 0
        self.total_cache_write = 0
        self.total_cost = 0.0

    def record(self, provider: str, model: str, usage: Dict[str, int]) -> None:
        key = f"{provider}/{model}"
        row = self.rows.setdefault(
            key, {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0, "calls": 0})
        row["in"] += usage.get("input", 0)
        row["out"] += usage.get("output", 0)
        row["cache_read"] += usage.get("cache_read", 0) or 0
        row["cache_write"] += usage.get("cache_write", 0) or 0
        row["calls"] += 1
        self.total_in += usage.get("input", 0)
        self.total_out += usage.get("output", 0)
        self.total_cache_read += usage.get("cache_read", 0) or 0
        self.total_cache_write += usage.get("cache_write", 0) or 0
        self.total_cost = self._compute_cost()

    def _compute_cost(self) -> float:
        total = 0.0
        for key, row in self.rows.items():
            model = key.split("/", 1)[1]
            info = model_info(model)
            pin, pout = info.get("in"), info.get("out")
            if pin is None or pout is None:
                continue
            uncached = max(0, row["in"] - row["cache_read"] - row["cache_write"])
            total += uncached * pin / 1_000_000
            total += row["cache_read"] * (pin * 0.10) / 1_000_000
            total += row["cache_write"] * (pin * 1.25) / 1_000_000
            total += row["out"] * pout / 1_000_000
        return max(0.0, total)

    @property
    def total_tokens(self) -> int:
        """Everything the providers processed this session (cached included)."""
        return self.total_in + self.total_out + self.total_cache_read + self.total_cache_write

    @property
    def has_pricing(self) -> bool:
        return bool(self.rows) and all(
            model_info(key.split("/", 1)[1]).get("in") is not None for key in self.rows
        )

    @property
    def cache_hit_rate(self) -> Optional[float]:
        """Share of input tokens served from cache (None when no traffic)."""
        if self.total_in <= 0:
            return None
        return min(1.0, self.total_cache_read / self.total_in)

    def guard(self) -> None:
        if self.max_cost_usd is None:
            return
        if self.total_cost >= float(self.max_cost_usd):
            raise CostLimitExceeded(
                f"Session cost cap reached: ${self.total_cost:.4f} ≥ ${self.max_cost_usd:.2f}. "
                f"Raise it with --max-cost or ORCA_MAX_COST."
            )

    def cost_text(self) -> str:
        base = f"{self.total_in:,} in · {self.total_out:,} out"
        if self.total_cache_read or self.total_cache_write:
            rate = self.cache_hit_rate
            base += (f" · cache {self.total_cache_read:,} read"
                     f" ({int(rate * 100)}% hit)" if rate is not None else "")
        if self.has_pricing and self.total_cost > 0:
            return f"{base} · ${self.total_cost:.4f}"
        return f"{base} · cost n/a for this model (pricing not in catalog)"

    def summary_rows(self) -> List[Tuple[str, int, int, int, str]]:
        rows: List[Tuple[str, int, int, int, str]] = []
        for key, row in sorted(self.rows.items()):
            info = model_info(key.split("/", 1)[1])
            if info.get("in") is not None:
                uncached = row["in"] - row["cache_read"] - row["cache_write"]
                cost = (uncached * info["in"]
                        + row["cache_read"] * info["in"] * 0.10
                        + row["cache_write"] * info["in"] * 1.25
                        + row["out"] * info["out"]) / 1e6
                label = f"${cost:.4f}"
            else:
                label = "~"
            rows.append((key, row["in"], row["out"], row["cache_read"], label))
        return rows
