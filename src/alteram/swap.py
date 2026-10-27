"""The order-swap check: one pair of arguments, the judge run in both orders."""

from datetime import UTC, datetime
from itertools import combinations, product
from statistics import mean
from typing import get_args

from alteram.graph import (
    AgentError,
    ChatModelFactory,
    RunFailed,
    anthropic_chat_model,
    run_judge,
    run_lawyer,
)
from alteram.models import (
    AgentCall,
    Argument,
    Case,
    FailedRun,
    JudgeOrder,
    JudgeResult,
    SwapRun,
    SwapSummary,
    Winner,
)
from alteram.pricing import DEFAULT_RUN_BUDGET_USD, Budget

ORDERS: tuple[JudgeOrder, ...] = get_args(JudgeOrder)


def _share(differs: list[bool]) -> float | None:
    return sum(differs) / len(differs) if differs else None


def disagreement(
    winners: dict[JudgeOrder, list[Winner]],
) -> tuple[float | None, float | None]:
    """Share of winner pairs that differ: within the same order, then across."""
    within = [a != b for ws in winners.values() for a, b in combinations(ws, 2)]
    across = [a != b for a, b in product(*winners.values())]
    return _share(within), _share(across)


def summarize(judges: list[JudgeResult]) -> SwapSummary:
    winners = {
        order: [j.verdict.winner for j in judges if j.judge_order == order]
        for order in ORDERS
    }
    within, across = disagreement(winners)
    return SwapSummary(
        winners=winners,
        mean_confidence={
            order: mean(j.verdict.confidence for j in judges if j.judge_order == order)
            for order in ORDERS
        },
        within_order_disagreement=within,
        across_order_disagreement=across,
    )


def run_swap(
    case: Case,
    repeats: int,
    chat_model: ChatModelFactory = anthropic_chat_model,
    budget: Budget | None = None,
) -> SwapRun:
    """Lawyers once, then the judge `repeats` times in each order."""
    budget = budget or Budget(DEFAULT_RUN_BUDGET_USD)
    started_at = datetime.now(UTC)
    arguments: dict[str, Argument] = {}
    calls: dict[str, AgentCall] = {}
    judges: list[JudgeResult] = []
    try:
        for side in ("claimant", "respondent"):
            arguments[side], calls[side] = run_lawyer(case, side, chat_model, budget)
        # Orders interleaved, so drift over time doesn't look like an order effect.
        for _ in range(repeats):
            for order in ORDERS:
                verdict, call = run_judge(
                    case,
                    arguments["claimant"],
                    arguments["respondent"],
                    order,
                    chat_model,
                    budget,
                )
                judges.append(
                    JudgeResult(judge_order=order, verdict=verdict, call=call)
                )
    except Exception as e:
        if isinstance(e, AgentError) and e.call:
            calls[e.role] = e.call
        raise RunFailed(
            FailedRun(
                command="swap",
                case_id=case.id,
                case_sha256=case.sha256,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                error=f"{type(e).__name__}: {e}",
                cost_usd=budget.spent_usd,
                claimant=arguments.get("claimant"),
                respondent=arguments.get("respondent"),
                calls=calls,
                judges=judges,
            )
        ) from e
    return SwapRun(
        case_id=case.id,
        case_sha256=case.sha256,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        claimant=arguments["claimant"],
        respondent=arguments["respondent"],
        calls=calls,
        judges=judges,
        summary=summarize(judges),
    )
