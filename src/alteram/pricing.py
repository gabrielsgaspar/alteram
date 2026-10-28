"""Model prices and the per-run budget."""

import math
import os
import threading
from typing import NamedTuple

PRICES_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
PRICES_CHECKED = "2026-10-27"

RUN_BUDGET_ENV = "ALTERAM_RUN_BUDGET_USD"
DEFAULT_RUN_BUDGET_USD = 5.0

# Characters per token used to bound a prompt's size before it is sent. Real
# prompts run nearer 4; 2 keeps the estimate on the high side.
CHARS_PER_TOKEN_LOW = 2


class Price(NamedTuple):
    input_per_mtok: float  # USD per million input tokens
    output_per_mtok: float  # USD per million output tokens, thinking included


# Base rates as of PRICES_CHECKED: global endpoint, no cache, no batch.
# Only models we use; a new model needs a row, checked against PRICES_URL.
PRICES: dict[str, Price] = {
    "claude-opus-5-5": Price(4.0, 20.0),
    "claude-sonnet-5-5": Price(2.0, 10.0),
}


class UnknownModel(KeyError):
    """A model with no row in PRICES; its cost is unknown, not zero."""


class BudgetExceeded(RuntimeError):
    """The next model call could take the run over its budget."""


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    try:
        price = PRICES[model]
    except KeyError:
        raise UnknownModel(
            f"no price for model {model!r}; add it to PRICES in pricing.py"
        ) from None
    return (
        input_tokens * price.input_per_mtok + output_tokens * price.output_per_mtok
    ) / 1_000_000


def priced_model(reported: str, configured: str) -> str:
    """The model to price a call at: the one that answered, if it has a row.

    APIs may report a dated ID with no row; the configured model stands in for it.
    If that has no row either, cost_usd raises."""
    return reported if reported in PRICES else configured


def worst_case_usd(model: str, prompt_chars: int, max_tokens: int) -> float:
    """An upper bound on one call: a generous input estimate, full max_tokens out."""
    input_tokens = math.ceil(prompt_chars / CHARS_PER_TOKEN_LOW)
    return cost_usd(model, input_tokens, max_tokens)


def run_budget_from_env() -> float:
    raw = os.environ.get(RUN_BUDGET_ENV, "").strip()
    if not raw:
        return DEFAULT_RUN_BUDGET_USD
    try:
        limit = float(raw)
    except ValueError:
        raise ValueError(f"{RUN_BUDGET_ENV} must be a number of dollars") from None
    if not math.isfinite(limit) or limit <= 0:
        raise ValueError(f"{RUN_BUDGET_ENV} must be more than 0")
    return limit


class Budget:
    """Money spent in one run. Lawyers run in parallel, so a lock guards it."""

    def __init__(self, limit_usd: float) -> None:
        self.limit_usd = limit_usd
        self.spent_usd = 0.0
        self._reserved_usd = 0.0
        self._lock = threading.Lock()

    def reserve(self, worst_usd: float) -> None:
        """Hold the worst case of the next call, or refuse it before it is made."""
        with self._lock:
            committed = self.spent_usd + self._reserved_usd
            if committed + worst_usd > self.limit_usd:
                raise BudgetExceeded(
                    f"budget ${self.limit_usd:.2f} could be exceeded: "
                    f"${committed:.4f} spent or held, next call up to ${worst_usd:.4f}"
                )
            self._reserved_usd += worst_usd

    def settle(self, reserved_usd: float, actual_usd: float) -> None:
        """Swap a reservation for what the call actually cost."""
        with self._lock:
            self._reserved_usd -= reserved_usd
            self.spent_usd += actual_usd
