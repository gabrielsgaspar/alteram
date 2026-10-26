"""Command line: `alteram run` and `alteram swap`."""

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

from dotenv import load_dotenv
from pydantic import BaseModel

from alteram.graph import (
    JUDGE_MODEL_ENV,
    LAWYER_MODEL_ENV,
    ChatModelFactory,
    RunFailed,
    anthropic_chat_model,
    run_case,
)
from alteram.loader import load_case
from alteram.models import AgentCall, Argument, JudgeOrder, Run, SwapRun, Verdict
from alteram.swap import ORDERS, run_swap

REQUIRED_ENV = ("ANTHROPIC_API_KEY", LAWYER_MODEL_ENV, JUDGE_MODEL_ENV)


def missing_env() -> list[str]:
    return [name for name in REQUIRED_ENV if not os.environ.get(name)]


def save(model: BaseModel, runs_dir: Path, case_id: str, name: str) -> Path:
    path = runs_dir / case_id / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2), encoding="utf-8")
    return path


def format_argument(argument: Argument) -> str:
    lines = [
        f"== {argument.side.capitalize()} ==",
        f"Requested outcome: {argument.requested_outcome}",
    ]
    for point in argument.points:
        lines.append(f"  {point.label} {point.citations} {point.claim}")
        lines.append(f"      {point.reasoning}")
    against = argument.strongest_point_against
    lines.append(f"  Strongest point against {against.citations}: {against.point}")
    lines.append(f"      Answer: {against.answer}")
    return "\n".join(lines)


def format_verdict(verdict: Verdict) -> str:
    lines = [
        "== Verdict ==",
        f"Winner: {verdict.winner}  (confidence {verdict.confidence:.2f})",
    ]
    for reason in verdict.reasons:
        lines.append(f"  {reason.label} {reason.citations} {reason.finding}")
    lines.append(
        "Unsupported claims:" + ("" if verdict.unsupported_claims else " none")
    )
    for claim in verdict.unsupported_claims:
        lines.append(f"  {claim.label}: {claim.description}")
    if verdict.missing_fact:
        lines.append(f"Missing fact: {verdict.missing_fact}")
    lines.append(f"What would change: {verdict.what_would_change}")
    return "\n".join(lines)


def call_row(role: str, calls: list[AgentCall]) -> tuple[str, int, int, int]:
    return (
        role,
        sum(c.attempts for c in calls),
        sum(c.input_tokens for c in calls),
        sum(c.output_tokens for c in calls),
    )


def format_calls(rows: list[tuple[str, int, int, int]]) -> str:
    lines = ["== Calls ==", f"  {'agent':<12}{'attempts':>9}{'in':>10}{'out':>10}"]
    for role, attempts, tokens_in, tokens_out in rows:
        lines.append(f"  {role:<12}{attempts:>9}{tokens_in:>10}{tokens_out:>10}")
    return "\n".join(lines)


def format_share(share: float | None) -> str:
    return "n/a (no pairs)" if share is None else f"{share:.0%}"


def format_swap(swap: SwapRun) -> str:
    summary = swap.summary
    lines = ["== Order swap =="]
    for order in ORDERS:
        lines.append(
            f"  {order:<17} winners: {', '.join(summary.winners[order])}"
            f"  mean confidence {summary.mean_confidence[order]:.2f}"
        )
    lines.append(
        "  Disagreement within the same order (noise): "
        + format_share(summary.within_order_disagreement)
    )
    lines.append(
        "  Disagreement across orders (noise + order effect): "
        + format_share(summary.across_order_disagreement)
    )
    rows = [call_row(role, [call]) for role, call in swap.calls.items()]
    rows.append(call_row(f"judge x{len(swap.judges)}", [j.call for j in swap.judges]))
    lines.append(format_calls(rows))
    return "\n".join(lines)


def print_run(run: Run) -> None:
    print(f"Case {run.case_id}, judge order {run.judge_order}\n")
    print(format_argument(run.claimant), end="\n\n")
    print(format_argument(run.respondent), end="\n\n")
    print(format_verdict(run.verdict), end="\n\n")
    print(format_calls([call_row(r, [c]) for r, c in run.calls.items()]))


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="alteram")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run both lawyers and the judge on a case")
    run.add_argument("case", type=Path)
    run.add_argument("--order", choices=get_args(JudgeOrder), default="claimant_first")
    swap = commands.add_parser("swap", help="order-swap check on the judge")
    swap.add_argument("case", type=Path)
    swap.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args(argv)
    if args.command == "swap" and args.repeats < 1:
        parser.error("--repeats must be at least 1")
    return args


def main(
    argv: list[str] | None = None,
    chat_model: ChatModelFactory = anthropic_chat_model,
    runs_dir: Path = Path("runs"),
) -> int:
    args = parse_args(argv)
    load_dotenv()
    if missing := missing_env():
        print(
            f"Missing environment variables: {', '.join(missing)}. "
            "Set them in .env (see .env.example).",
            file=sys.stderr,
        )
        return 2
    case = load_case(args.case)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")  # no ':' for Windows
    try:
        if args.command == "run":
            run = run_case(case, args.order, chat_model)
            print_run(run)
            path = save(run, runs_dir, case.id, stamp)
        else:
            swap = run_swap(case, args.repeats, chat_model)
            print(format_swap(swap))
            path = save(swap, runs_dir, case.id, f"{stamp}-swap")
    except RunFailed as e:
        path = save(e.failed, runs_dir, case.id, f"{stamp}-failed")
        print(f"Run failed: {e}\nPartial log saved to {path}", file=sys.stderr)
        return 1
    print(f"\nSaved to {path}")
    return 0
