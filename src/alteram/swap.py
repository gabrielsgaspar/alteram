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
)

ORDERS: tuple[JudgeOrder, ...] = get_args(JudgeOrder)


def _share(differs: list[bool]) -> float | None:
    return sum(differs) / len(differs) if differs else None


def summarize(judges: list[JudgeResult]) -> SwapSummary:
    winners = {
        order: [j.verdict.winner for j in judges if j.judge_order == order]
        for order in ORDERS
    }
    within = [a != b for ws in winners.values() for a, b in combinations(ws, 2)]
    across = [a != b for a, b in product(*winners.values())]
    return SwapSummary(
        winners=winners,
        mean_confidence={
            order: mean(j.verdict.confidence for j in judges if j.judge_order == order)
            for order in ORDERS
        },
        within_order_disagreement=_share(within),
        across_order_disagreement=_share(across),
    )


def run_swap(
    case: Case, repeats: int, chat_model: ChatModelFactory = anthropic_chat_model
) -> SwapRun:
    """Lawyers once, then the judge `repeats` times in each order."""
    started_at = datetime.now(UTC)
    arguments: dict[str, Argument] = {}
    calls: dict[str, AgentCall] = {}
    judges: list[JudgeResult] = []
    try:
        for side in ("claimant", "respondent"):
            arguments[side], calls[side] = run_lawyer(case, side, chat_model)
        # Orders interleaved, so drift over time doesn't look like an order effect.
        for _ in range(repeats):
            for order in ORDERS:
                verdict, call = run_judge(
                    case,
                    arguments["claimant"],
                    arguments["respondent"],
                    order,
                    chat_model,
                )
                judges.append(
                    JudgeResult(judge_order=order, verdict=verdict, call=call)
                )
    except Exception as e:
        if isinstance(e, AgentError):
            calls[e.role] = e.call
        raise RunFailed(
            FailedRun(
                command="swap",
                case_id=case.id,
                case_sha256=case.sha256,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                error=f"{type(e).__name__}: {e}",
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
