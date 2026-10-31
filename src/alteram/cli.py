"""Command line: `alteram run`, `swap`, `rejudge`, `eval` and `cases`."""

import argparse
import os
import sys
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import get_args

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from alteram.evaluate import (
    ROLES,
    BaselineError,
    baseline_estimate,
    compare,
    current_prompts,
    estimate,
    few_cases_warning,
    format_baseline_estimate,
    format_compare,
    format_estimate,
    load_results,
    load_summary,
    past_calls,
    run_eval,
    save_baseline,
    summarize,
    summary_markdown,
)
from alteram.events import Event, EventLog, events_path, format_event, save_events
from alteram.graph import (
    JUDGE_MODEL_ENV,
    LAWYER_MODEL_ENV,
    ChatModelFactory,
    RunFailed,
    anthropic_chat_model,
    run_case,
)
from alteram.loader import load_case
from alteram.models import (
    AgentCall,
    Argument,
    Case,
    JudgeOrder,
    RejudgeRun,
    RejudgeStats,
    Run,
    SwapRun,
    Verdict,
)
from alteram.pricing import Budget, UnknownModel, run_budget_from_env
from alteram.rejudge import (
    CaseChanged,
    SourceError,
    check_case,
    load_source,
    run_rejudge,
)
from alteram.swap import ORDERS, run_swap

REQUIRED_ENV = ("ANTHROPIC_API_KEY", LAWYER_MODEL_ENV, JUDGE_MODEL_ENV)
REJUDGE_ENV = ("ANTHROPIC_API_KEY", JUDGE_MODEL_ENV)  # the lawyers are not called


def missing_env(command: str) -> list[str]:
    required = REJUDGE_ENV if command == "rejudge" else REQUIRED_ENV
    return [name for name in required if not os.environ.get(name)]


def save(model: BaseModel, runs_dir: Path, case_id: str, name: str) -> Path:
    path = runs_dir / case_id / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2), encoding="utf-8")
    return path


def save_with_events(
    model: BaseModel, events: EventLog, runs_dir: Path, case_id: str, name: str
) -> Path:
    """Save a run file and its events beside it, as `<name>.events.jsonl`."""
    path = save(model, runs_dir, case_id, name)
    save_events(events, events_path(path))
    return path


def print_event(event: Event) -> None:
    print(format_event(event), flush=True)


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


CallRow = tuple[str, int, int, int, float]


def call_row(role: str, calls: list[AgentCall]) -> CallRow:
    return (
        role,
        sum(c.attempts for c in calls),
        sum(c.input_tokens for c in calls),
        sum(c.output_tokens for c in calls),
        sum(c.cost_usd or 0.0 for c in calls),  # None only in old files
    )


def format_calls(rows: list[CallRow]) -> str:
    lines = [
        "== Calls ==",
        f"  {'agent':<12}{'attempts':>9}{'in':>10}{'out':>10}{'USD':>10}",
    ]
    for role, attempts, tokens_in, tokens_out, cost in rows:
        lines.append(
            f"  {role:<12}{attempts:>9}{tokens_in:>10}{tokens_out:>10}{cost:>10.4f}"
        )
    total = sum(row[4] for row in rows)
    lines.append(f"  {'total':<12}{'':>29}{total:>10.4f}")
    return "\n".join(lines)


def report_failure(e: RunFailed, path: Path) -> None:
    print(
        f"Run failed: {e}\nSpent before failing: ${e.failed.cost_usd:.4f}"
        f"\nPartial log saved to {path}",
        file=sys.stderr,
    )


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


def format_stats(label: str, stats: RejudgeStats) -> list[str]:
    lines = [f"  {label}"]
    for order in ORDERS:
        winners = ", ".join(stats.winners[order]) or "-"
        confidence = stats.mean_confidence.get(order)
        mean = "n/a" if confidence is None else f"{confidence:.2f}"
        lines.append(f"    {order:<17} winners: {winners}  mean confidence {mean}")
    lines.append(
        f"    within-order disagreement {format_share(stats.within_order_disagreement)}"
        f", across-order {format_share(stats.across_order_disagreement)}"
        f", retry rate {format_share(stats.retry_rate)}"
    )
    return lines


def format_rejudge(rejudge: RejudgeRun) -> str:
    old = ", ".join(
        f"v{p.version} {p.sha256[:8]}" for p in rejudge.source_judge_prompts
    )
    new = rejudge.current_judge_prompt
    lines = [
        "== Re-judge ==",
        f"  Source: {rejudge.source_path}",
        f"  Judge prompt: source {old} -> current v{new.version} {new.sha256[:8]}",
    ]
    lines += format_stats("Source verdicts", rejudge.summary.source)
    lines += format_stats("New verdicts", rejudge.summary.new)
    rows = [call_row(f"judge x{len(rejudge.judges)}", [j.call for j in rejudge.judges])]
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
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {version('alteram')}"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run both lawyers and the judge on a case")
    run.add_argument("case", type=Path)
    run.add_argument("--order", choices=get_args(JudgeOrder), default="claimant_first")
    run.add_argument(
        "--follow", action="store_true", help="print events as they happen"
    )
    swap = commands.add_parser("swap", help="order-swap check on the judge")
    swap.add_argument("case", type=Path)
    swap.add_argument("--repeats", type=int, default=3)
    rejudge = commands.add_parser(
        "rejudge", help="current judge prompt on the arguments of an earlier file"
    )
    rejudge.add_argument("source", type=Path, help="a run or swap file")
    rejudge.add_argument("--repeats", type=int, default=5)
    rejudge.add_argument("--allow-changed-case", action="store_true")
    evaluate = commands.add_parser(
        "eval", help="the whole graph n times per case, scored against `expected`"
    )
    evaluate.add_argument("--cases", type=Path, default=Path("cases"))
    evaluate.add_argument("--n", type=int, default=3, help="runs per case")
    evaluate.add_argument("--seed", type=int, default=0, help="bootstrap seed")
    evaluate.add_argument(
        "--dry-run", action="store_true", help="print the plan and cost; no calls"
    )
    eval_commands = evaluate.add_subparsers(dest="eval_command")
    baseline = eval_commands.add_parser(
        "baseline", help="copy a summary.json to eval/baselines/"
    )
    baseline.add_argument("summary", type=Path)
    comparison = eval_commands.add_parser(
        "compare", help="differences between two eval summaries, b - a"
    )
    comparison.add_argument("a", type=Path)
    comparison.add_argument("b", type=Path)
    comparison.add_argument("--seed", type=int, default=0, help="bootstrap seed")
    cases = commands.add_parser("cases", help="list the cases in cases/")
    cases_commands = cases.add_subparsers(dest="cases_command", required=True)
    cases_commands.add_parser("list", help="one line per case: id, kind, title")
    args = parser.parse_args(argv)
    if args.command in ("swap", "rejudge") and args.repeats < 1:
        parser.error("--repeats must be at least 1")
    if args.command == "eval" and args.n < 1:
        parser.error("--n must be at least 1")
    return args


def rejudge_command(
    args: argparse.Namespace,
    chat_model: ChatModelFactory,
    runs_dir: Path,
    cases_dir: Path,
    stamp: str,
    budget: Budget,
) -> int:
    try:
        source = load_source(args.source)
        case_path = cases_dir / f"{source.case_id}.md"
        if not case_path.is_file():
            raise SourceError(f"{args.source}: its case file {case_path} is missing")
        case = load_case(case_path)
        if not args.allow_changed_case:
            check_case(case, source)
    except (SourceError, CaseChanged) as e:
        print(f"Refused: {e}", file=sys.stderr)
        return 2
    events = EventLog(case.id)
    try:
        rejudge = run_rejudge(case, source, args.repeats, chat_model, budget, events)
    except RunFailed as e:
        path = save_with_events(e.failed, events, runs_dir, case.id, f"{stamp}-failed")
        report_failure(e, path)
        return 1
    print(format_rejudge(rejudge))
    path = save_with_events(rejudge, events, runs_dir, case.id, f"{stamp}-rejudge")
    print(f"\nSaved to {path}")
    return 0


def format_case_line(case: Case) -> str:
    return f"{case.id}  {case.kind:<12}  {case.title}"  # never `expected`


def cases_command(cases_dir: Path) -> int:
    cases = [load_case(path) for path in sorted(cases_dir.glob("*.md"))]
    if not cases:
        print(f"No cases found in {cases_dir}", file=sys.stderr)
        return 2
    for case in sorted(cases, key=lambda c: c.id):
        print(format_case_line(case))
    return 0


def compare_command(args: argparse.Namespace) -> int:
    try:
        a, b = load_summary(args.a), load_summary(args.b)
    except (OSError, ValidationError) as e:
        print(f"Refused: not a readable eval summary: {e}", file=sys.stderr)
        return 2
    print(format_compare(*compare(a, b, args.seed)))
    return 0


def eval_command(
    args: argparse.Namespace,
    chat_model: ChatModelFactory,
    runs_dir: Path,
    eval_dir: Path,
) -> int:
    if args.eval_command == "baseline":
        try:
            target = save_baseline(args.summary, eval_dir / "baselines")
        except BaselineError as e:
            print(f"Refused: {e}", file=sys.stderr)
            return 2
        print(f"Baseline saved to {target}. Commit it to keep it.")
        return 0
    if args.eval_command == "compare":
        return compare_command(args)
    cases = [load_case(path) for path in sorted(args.cases.glob("*.md"))]
    if not cases:
        print(f"No cases found in {args.cases}", file=sys.stderr)
        return 2
    try:
        limit = run_budget_from_env()
    except ValueError as e:
        print(f"{e} (see .env.example).", file=sys.stderr)
        return 2
    lawyer, judge = os.environ.get(LAWYER_MODEL_ENV), os.environ.get(JUDGE_MODEL_ENV)
    if args.dry_run:  # no API key needed, and the model factory is never touched
        sources = [runs_dir, eval_dir / "runs"]
        models = {"claimant": lawyer, "respondent": lawyer, "judge": judge}
        calls = past_calls(sources)
        no_history = [r for r in ROLES if all(role != r for role, _ in calls)]
        baselines = eval_dir / "baselines"
        if no_history and (base := baseline_estimate(baselines, lawyer, judge)):
            print(format_baseline_estimate(cases, args.n, base, no_history, limit))
            return 0
        try:
            estimates = estimate(cases, args.n, calls, models)
        except (UnknownModel, ValueError) as e:
            print(f"Cannot estimate: {e}", file=sys.stderr)
            return 2
        print(format_estimate(cases, args.n, estimates, sources, limit))
        return 0
    if missing := missing_env(args.command):
        print(
            f"Missing environment variables: {', '.join(missing)}. "
            "Set them in .env (see .env.example).",
            file=sys.stderr,
        )
        return 2
    if warning := few_cases_warning(len(cases)):
        print(f"Warning: {warning}", file=sys.stderr)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = eval_dir / "runs" / stamp
    prompts = current_prompts()  # before the runs, in case a file changes meanwhile
    print(f"Eval: {len(cases)} case(s) x n={args.n}, into {out_dir}")
    run_eval(cases, args.n, chat_model, out_dir, limit)
    summary = summarize(
        cases,
        load_results(out_dir),  # summarize what was saved, nothing else
        n=args.n,
        seed=args.seed,
        cases_dir=args.cases.as_posix(),
        models={"lawyer": lawyer or "", "judge": judge or ""},
        prompts=prompts,
        run_budget_usd=limit,
    )
    markdown = summary_markdown(summary)
    (out_dir / "summary.json").write_text(
        summary.model_dump_json(indent=2), encoding="utf-8"
    )
    (out_dir / "summary.md").write_text(markdown, encoding="utf-8")
    print(f"\n{markdown}\nSaved to {out_dir}")
    return 1 if summary.overall.failed else 0


def main(
    argv: list[str] | None = None,
    chat_model: ChatModelFactory = anthropic_chat_model,
    runs_dir: Path = Path("runs"),
    cases_dir: Path = Path("cases"),
    eval_dir: Path = Path("eval"),
) -> int:
    args = parse_args(argv)
    if args.command == "cases":  # needs no env, budget or model
        return cases_command(cases_dir)
    load_dotenv()
    if args.command == "eval":
        return eval_command(args, chat_model, runs_dir, eval_dir)
    if missing := missing_env(args.command):
        print(
            f"Missing environment variables: {', '.join(missing)}. "
            "Set them in .env (see .env.example).",
            file=sys.stderr,
        )
        return 2
    try:
        budget = Budget(run_budget_from_env())
    except ValueError as e:
        print(f"{e} (see .env.example).", file=sys.stderr)
        return 2
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")  # no ':' for Windows
    if args.command == "rejudge":
        return rejudge_command(args, chat_model, runs_dir, cases_dir, stamp, budget)
    case = load_case(args.case)
    follow = args.command == "run" and args.follow
    events = EventLog(case.id, print_event if follow else None)
    try:
        if args.command == "run":
            run = run_case(case, args.order, chat_model, budget, events)
            if follow:
                print()
            print_run(run)
            path = save_with_events(run, events, runs_dir, case.id, stamp)
        else:
            swap = run_swap(case, args.repeats, chat_model, budget, events)
            print(format_swap(swap))
            path = save_with_events(swap, events, runs_dir, case.id, f"{stamp}-swap")
    except RunFailed as e:
        path = save_with_events(e.failed, events, runs_dir, case.id, f"{stamp}-failed")
        report_failure(e, path)
        return 1
    print(f"\nSaved to {path}")
    return 0
