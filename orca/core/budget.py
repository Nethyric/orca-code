"""Usage accounting and hard budget stops.

Cache-read tokens are counted once, in their own column — never folded into
input tokens (double counting is how effective context silently halves).
"""
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    requests: int = 0
    cost_usd: float = 0.0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read += other.cache_read
        self.requests += other.requests
        self.cost_usd += other.cost_usd

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


# rough USD per 1M tokens (input, output) for popular families; unknown = 0
PRICING: Dict[str, Tuple[float, float]] = {
    "gpt-5.1": (1.25, 10.0),
    "gpt-5.1-mini": (0.25, 2.0),
    "claude-sonnet": (3.0, 15.0),
    "claude-opus": (15.0, 75.0),
    "claude-haiku": (0.8, 4.0),
    "deepseek": (0.27, 1.1),
    "kimi": (0.6, 2.5),
    "glm": (0.3, 1.2),
    "minimax": (0.3, 1.2),
    "grok": (3.0, 15.0),
    "gemini-3-pro": (2.0, 12.0),
    "llama": (0.2, 0.6),
    "qwen": (0.3, 1.0),
}


def price_of(model: str, usage: Usage) -> float:
    model = (model or "").lower()
    for family, (pin, pout) in PRICING.items():
        if family in model:
            return (usage.input_tokens * pin + usage.output_tokens * pout) / 1_000_000
    return 0.0


@dataclass
class Budget:
    max_cost_usd: Optional[float] = None
    max_tokens: Optional[int] = None
    usage: Usage = field(default_factory=Usage)

    def record(self, usage: Usage, model: str = "") -> None:
        if not usage.cost_usd:
            usage.cost_usd = price_of(model, usage)
        self.usage.add(usage)

    def exceeded(self) -> Optional[str]:
        u = self.usage
        if self.max_cost_usd is not None and u.cost_usd >= self.max_cost_usd:
            return (f"cost ceiling reached: ${u.cost_usd:.4f} of "
                    f"${self.max_cost_usd:.2f}")
        if self.max_tokens is not None and u.total_tokens >= self.max_tokens:
            return (f"token budget reached: {u.total_tokens:,} of "
                    f"{self.max_tokens:,}")
        return None
