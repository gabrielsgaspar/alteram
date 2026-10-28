"""Price table, cost and budget: pure functions, no models."""

import pytest

from alteram.pricing import (
    DEFAULT_RUN_BUDGET_USD,
    PRICES_CHECKED,
    RUN_BUDGET_ENV,
    Budget,
    BudgetExceeded,
    UnknownModel,
    cost_usd,
    priced_model,
    run_budget_from_env,
    worst_case_usd,
)


def test_cost_on_hand_computed_example() -> None:
    # The judge call of runs/case-001/20261026T205844Z.json, at $4 in and $20 out:
    # 5305 * 4 = 21,220 and 1864 * 20 = 37,280; 58,500 / 1,000,000 = $0.0585.
    assert cost_usd("claude-opus-5-5", 5305, 1864) == pytest.approx(0.0585)
    # Its claimant: 2491 * 2 + 1255 * 10 = 17,532 -> $0.017532.
    assert cost_usd("claude-sonnet-5-5", 2491, 1255) == pytest.approx(0.017532)


def test_unknown_model_raises_instead_of_costing_nothing() -> None:
    with pytest.raises(UnknownModel, match="claude-opus-5-5-typo"):
        cost_usd("claude-opus-5-5-typo", 10, 10)
    with pytest.raises(UnknownModel):
        cost_usd("", 0, 0)  # a reply that reported no model


def test_priced_model_falls_back_to_configured_only_when_unpriced() -> None:
    assert priced_model("claude-opus-5-5", "claude-sonnet-5-5") == "claude-opus-5-5"
    dated = "claude-sonnet-5-5-20261001"
    assert priced_model(dated, "claude-sonnet-5-5") == "claude-sonnet-5-5"
    # Neither priced: the configured one comes back, and cost_usd raises on it.
    assert priced_model(dated, "claude-unpriced") == "claude-unpriced"


def test_price_table_is_dated() -> None:
    assert PRICES_CHECKED == "2026-10-27"


def test_worst_case_counts_full_max_tokens_and_generous_input() -> None:
    # 1000 characters -> 500 tokens in at $2; 32,000 out at $10.
    expected = (500 * 2 + 32000 * 10) / 1_000_000
    assert worst_case_usd("claude-sonnet-5-5", 1000, 32000) == pytest.approx(expected)


def test_budget_refuses_a_call_whose_worst_case_would_exceed() -> None:
    budget = Budget(1.0)
    budget.reserve(0.6)
    budget.settle(0.6, 0.25)
    budget.reserve(0.75)  # 0.25 + 0.75 = 1.0: exactly at the limit is allowed
    with pytest.raises(BudgetExceeded):
        budget.reserve(0.01)  # 0.75 still held for a call in flight
    budget.settle(0.75, 0.5)
    assert budget.spent_usd == pytest.approx(0.75)
    with pytest.raises(BudgetExceeded):
        budget.reserve(0.26)
    assert budget.spent_usd == pytest.approx(0.75)  # a refusal spends nothing


@pytest.mark.parametrize("raw", ["", "  "])
def test_budget_env_defaults_to_five_dollars(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv(RUN_BUDGET_ENV, raw)
    assert run_budget_from_env() == DEFAULT_RUN_BUDGET_USD == 5
    monkeypatch.delenv(RUN_BUDGET_ENV)
    assert run_budget_from_env() == 5


def test_budget_env_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(RUN_BUDGET_ENV, "0.5")
    assert run_budget_from_env() == 0.5


@pytest.mark.parametrize("raw", ["five", "0", "-1", "nan", "inf"])
def test_bad_budget_env_is_refused(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv(RUN_BUDGET_ENV, raw)
    with pytest.raises(ValueError, match=RUN_BUDGET_ENV):
        run_budget_from_env()
