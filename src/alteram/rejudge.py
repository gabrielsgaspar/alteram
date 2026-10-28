"""Paired re-judging: the current judge prompt on the arguments of an earlier file."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

from pydantic import BaseModel, ValidationError

from alteram.events import EventLog, state_change
from alteram.graph import AgentError, ChatModelFactory, RunFailed, run_judge
from alteram.loader import load_prompt
from alteram.models import (
    AgentCall,
    Argument,
    Case,
    FailedRun,
    JudgeResult,
    PromptRef,
    RejudgeRun,
    RejudgeStats,
    RejudgeSummary,
    Run,
    SwapRun,
)
from alteram.pricing import DEFAULT_RUN_BUDGET_USD, Budget
from alteram.swap import ORDERS, disagreement


class SourceError(ValueError):
    """The source file cannot be re-judged."""


class CaseChanged(RuntimeError):
    """The case file is not the one the source file was made from."""


class Source(BaseModel):
    path: str
    sha256: str  # hash of the file's bytes
    case_id: str
    case_sha256: str
    claimant: Argument
    respondent: Argument
    judges: list[JudgeResult]


def load_source(path: Path) -> Source:
    """Read a run or swap file; failed-run files have no complete result to pair."""
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise SourceError(f"{path}: not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise SourceError(f"{path}: not a run or swap file")
    try:
        if "command" in data:
            raise SourceError(f"{path}: a failed run cannot be re-judged")
        if "judges" in data:
            swap = SwapRun.model_validate(data)
            judges = swap.judges
            claimant, respondent = swap.claimant, swap.respondent
            case_id, case_sha256 = swap.case_id, swap.case_sha256
        elif "verdict" in data:
            run = Run.model_validate(data)
            call = run.calls["judge"]
            judges = [
                JudgeResult(judge_order=run.judge_order, verdict=run.verdict, call=call)
            ]
            claimant, respondent = run.claimant, run.respondent
            case_id, case_sha256 = run.case_id, run.case_sha256
        else:
            raise SourceError(f"{path}: neither a run file nor a swap file")
    except (ValidationError, KeyError) as e:
        raise SourceError(f"{path}: cannot read it as a run or swap file: {e}") from e
    if not judges:
        raise SourceError(f"{path}: it holds no judge verdicts to compare with")
    return Source(
        path=str(path),
        sha256=hashlib.sha256(raw).hexdigest(),
        case_id=case_id,
        case_sha256=case_sha256,
        claimant=claimant,
        respondent=respondent,
        judges=judges,
    )


def check_case(case: Case, source: Source) -> None:
    if case.sha256 != source.case_sha256:
        raise CaseChanged(
            f"cases/{case.id}.md has changed since {source.path} was made "
            f"(saved sha256 {source.case_sha256}, current {case.sha256}). "
            "The saved arguments cite paragraphs of the old text. "
            "Pass --allow-changed-case to re-judge anyway."
        )


def stats(judges: list[JudgeResult]) -> RejudgeStats:
    winners = {
        order: [j.verdict.winner for j in judges if j.judge_order == order]
        for order in ORDERS
    }
    confidence = {
        order: [j.verdict.confidence for j in judges if j.judge_order == order]
        for order in ORDERS
    }
    within, across = disagreement(winners)
    return RejudgeStats(
        winners=winners,
        mean_confidence={o: mean(c) for o, c in confidence.items() if c},
        within_order_disagreement=within,
        across_order_disagreement=across,
        retry_rate=sum(j.call.attempts > 1 for j in judges) / len(judges),
    )


def run_rejudge(
    case: Case,
    source: Source,
    repeats: int,
    chat_model: ChatModelFactory,
    budget: Budget | None = None,
    events: EventLog | None = None,
) -> RejudgeRun:
    """The judge alone, `repeats` times in each order; the lawyers are never called."""
    budget = budget or Budget(DEFAULT_RUN_BUDGET_USD)
    events = events or EventLog(case.id)
    sink = events.add
    started_at = datetime.now(UTC)
    prompt = load_prompt("judge")
    judges: list[JudgeResult] = []
    calls: dict[str, AgentCall] = {}
    try:
        state_change(sink, None, "deciding")
        # Orders interleaved, as in the swap check.
        for _ in range(repeats):
            for order in ORDERS:
                verdict, call = run_judge(
                    case,
                    source.claimant,
                    source.respondent,
                    order,
                    chat_model,
                    budget,
                    sink,
                )
                judges.append(
                    JudgeResult(judge_order=order, verdict=verdict, call=call)
                )
        state_change(sink, "deciding", "decided")
    except Exception as e:
        if isinstance(e, AgentError) and e.call:
            calls[e.role] = e.call
        raise RunFailed(
            FailedRun(
                command="rejudge",
                case_id=case.id,
                case_sha256=case.sha256,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                error=f"{type(e).__name__}: {e}",
                cost_usd=budget.spent_usd,
                claimant=source.claimant,
                respondent=source.respondent,
                calls=calls,
                judges=judges,
            )
        ) from e
    seen = {(j.call.prompt_version, j.call.prompt_sha256) for j in source.judges}
    return RejudgeRun(
        case_id=case.id,
        case_sha256=case.sha256,
        source_path=source.path,
        source_sha256=source.sha256,
        source_case_sha256=source.case_sha256,
        source_judge_prompts=[PromptRef(version=v, sha256=h) for v, h in sorted(seen)],
        current_judge_prompt=PromptRef(version=prompt.version, sha256=prompt.sha256),
        started_at=started_at,
        finished_at=datetime.now(UTC),
        claimant=source.claimant,
        respondent=source.respondent,
        source_judges=source.judges,
        judges=judges,
        summary=RejudgeSummary(source=stats(source.judges), new=stats(judges)),
    )
