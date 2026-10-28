"""`alteram eval`: the whole graph n times per case, summarized against `expected`."""

import random
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, quantiles, stdev
from typing import NamedTuple, get_args

from pydantic import ValidationError

from alteram.events import EventLog, events_path, save_events
from alteram.graph import MAX_TOKENS, ChatModelFactory, RunFailed, run_case
from alteram.loader import load_prompt
from alteram.models import (
    AgentCall,
    Case,
    CaseStats,
    ConfidenceStats,
    EvalFailure,
    EvalSummary,
    FailedRun,
    Interval,
    JudgeOrder,
    OverallStats,
    PromptRef,
    RejudgeRun,
    Run,
    SwapRun,
    Winner,
)
from alteram.pricing import Budget, cost_usd, worst_case_usd
from alteram.swap import ORDERS

ROLES = ("claimant", "respondent", "judge")
CALLS_PER_RUN = len(ROLES)
MIN_CASES = 10
BOOTSTRAP_REPS = 2000
SUMMARY_FILES = ("summary.json", "summary.md")
STAMP = re.compile(r"\d{8}T\d{6}Z")


class BaselineError(ValueError):
    """The summary cannot be saved as a baseline."""


class Saved(NamedTuple):
    file: str  # path relative to the eval directory
    result: Run | FailedRun


class PlannedRun(NamedTuple):
    case: Case
    repeat: int  # from 1
    judge_order: JudgeOrder


def few_cases_warning(count: int) -> str | None:
    if count >= MIN_CASES:
        return None
    return (
        f"Only {count} case(s): intervals are wide and cannot support strong "
        f"claims (fewer than {MIN_CASES})."
    )


def plan_runs(cases: list[Case], n: int) -> list[PlannedRun]:
    """Orders alternate within a case, and the first order alternates by case,
    so an odd n still balances the orders across the eval."""
    return [
        PlannedRun(case, repeat + 1, ORDERS[(i + repeat) % len(ORDERS)])
        for i, case in enumerate(cases)
        for repeat in range(n)
    ]


def run_file(planned: PlannedRun, failed: bool) -> str:
    suffix = "-failed" if failed else ""
    return f"{planned.case.id}/r{planned.repeat}-{planned.judge_order}{suffix}.json"


def run_eval(
    cases: list[Case],
    n: int,
    chat_model: ChatModelFactory,
    out_dir: Path,
    budget_limit: float,
) -> list[Saved]:
    """Run every planned run in turn; a failed run is saved and the eval goes on.

    Each run's events are saved beside it as `<run>.events.jsonl`."""
    saved: list[Saved] = []
    for planned in plan_runs(cases, n):
        result: Run | FailedRun
        events = EventLog(planned.case.id)
        try:
            result = run_case(
                planned.case,
                planned.judge_order,
                chat_model,
                Budget(budget_limit),
                events,
            )
        except RunFailed as e:
            result = e.failed
        name = run_file(planned, isinstance(result, FailedRun))
        path = out_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        save_events(events, events_path(path))
        status = "failed" if isinstance(result, FailedRun) else result.verdict.winner
        print(f"  {name}: {status}")
        saved.append(Saved(name, result))
    return saved


def load_results(out_dir: Path) -> list[Saved]:
    saved = []
    for path in sorted(out_dir.glob("*/*.json")):
        text = path.read_text(encoding="utf-8")
        model = FailedRun if path.stem.endswith("-failed") else Run
        saved.append(
            Saved(path.relative_to(out_dir).as_posix(), model.model_validate_json(text))
        )
    return saved


# --- statistics -------------------------------------------------------------


def _percentile_interval(value: float, resampled: list[float]) -> Interval:
    cuts = quantiles(resampled, n=40, method="inclusive")  # 2.5% steps
    return Interval(value=value, low=cuts[0], high=cuts[-1])


def bootstrap_mean(
    values: list[float], seed: int, reps: int = BOOTSTRAP_REPS
) -> Interval | None:
    """Mean of per-case values, with a percentile 95% interval over cases."""
    if not values:
        return None
    rng = random.Random(seed)
    resampled = [mean(rng.choices(values, k=len(values))) for _ in range(reps)]
    return _percentile_interval(mean(values), resampled)


def paired_bootstrap_diff(
    a: dict[str, float], b: dict[str, float], seed: int, reps: int = BOOTSTRAP_REPS
) -> Interval | None:
    """Mean of b − a over the cases both have, resampling those cases."""
    shared = sorted(a.keys() & b.keys())
    if not shared:
        return None
    diffs = [b[k] - a[k] for k in shared]
    rng = random.Random(seed)
    resampled = [mean(rng.choices(diffs, k=len(diffs))) for _ in range(reps)]
    return _percentile_interval(mean(diffs), resampled)


# --- summary ----------------------------------------------------------------


def _retry_rate(calls: list[tuple[str, AgentCall]]) -> dict[str, float]:
    rates = {}
    for role in ROLES:
        attempts = [c.attempts for r, c in calls if r == role]
        if attempts:
            rates[role] = sum(a > 1 for a in attempts) / len(attempts)
    return rates


def _mean_seconds(calls: list[tuple[str, AgentCall]]) -> dict[str, float]:
    times = {}
    for role in ROLES:
        seconds = [c.seconds for r, c in calls if r == role and c.seconds is not None]
        if seconds:
            times[role] = mean(seconds)
    return times


def _cost(result: Run | FailedRun) -> float:
    if isinstance(result, FailedRun):
        return result.cost_usd
    return sum(c.cost_usd or 0.0 for c in result.calls.values())


def _confidence(values: list[float]) -> ConfidenceStats | None:
    if not values:
        return None
    return ConfidenceStats(
        mean=mean(values),
        sd=stdev(values) if len(values) > 1 else None,
        min=min(values),
        max=max(values),
    )


def summarize_case(case: Case, saved: list[Saved]) -> CaseStats:
    runs = [r for s in saved if isinstance(r := s.result, Run)]
    failed = [(s.file, r) for s in saved if isinstance(r := s.result, FailedRun)]
    calls = [call for s in saved for call in s.result.calls.items()]
    winners = [r.verdict.winner for r in runs]
    return CaseStats(
        case_id=case.id,
        case_sha256=case.sha256,
        kind=case.kind,
        expected=case.expected,
        runs=len(saved),
        completed=len(runs),
        failed=len(failed),
        budget_stops=sum(r.budget_stop for _, r in failed),
        winners={w: winners.count(w) for w in get_args(Winner)},
        winners_by_order={
            order: [r.verdict.winner for r in runs if r.judge_order == order]
            for order in ORDERS
        },
        agreement=(
            sum(w == case.expected for w in winners) / len(winners) if winners else None
        ),
        confidence=_confidence([r.verdict.confidence for r in runs]),
        cost_usd=sum(_cost(s.result) for s in saved),
        mean_seconds=_mean_seconds(calls),
        retry_rate=_retry_rate(calls),
        failures=[
            EvalFailure(
                file=file,
                judge_order=r.judge_order,
                budget_stop=r.budget_stop,
                error=r.error,
            )
            for file, r in failed
        ],
    )


def summarize(
    cases: list[Case],
    saved: list[Saved],
    *,
    n: int,
    seed: int,
    cases_dir: str,
    models: dict[str, str],
    prompts: dict[str, PromptRef],
    run_budget_usd: float,
    created_at: datetime | None = None,
) -> EvalSummary:
    per_case = [
        summarize_case(case, [s for s in saved if s.result.case_id == case.id])
        for case in cases
    ]
    calls = [call for s in saved for call in s.result.calls.items()]
    agreements = [c.agreement for c in per_case if c.agreement is not None]
    confidences = [c.confidence.mean for c in per_case if c.confidence]
    total_cost = sum(c.cost_usd for c in per_case)
    runs = sum(c.runs for c in per_case)
    overall = OverallStats(
        cases=len(per_case),
        runs=runs,
        completed=sum(c.completed for c in per_case),
        failed=sum(c.failed for c in per_case),
        budget_stops=sum(c.budget_stops for c in per_case),
        cases_without_result=len(per_case) - len(agreements),
        accuracy=bootstrap_mean(agreements, seed),
        mean_confidence=bootstrap_mean(confidences, seed),
        cost_usd=total_cost,
        cost_per_run_usd=total_cost / runs if runs else None,
        retry_rate=_retry_rate(calls),
        mean_seconds=_mean_seconds(calls),
    )
    warning = few_cases_warning(len(cases))
    return EvalSummary(
        created_at=created_at or datetime.now(UTC),
        n=n,
        seed=seed,
        cases_dir=cases_dir,
        models=models,
        prompts=prompts,
        run_budget_usd=run_budget_usd,
        warnings=[warning] if warning else [],
        overall=overall,
        cases=per_case,
    )


def current_prompts() -> dict[str, PromptRef]:
    refs = {}
    for role in ROLES:
        prompt = load_prompt(role)
        refs[role] = PromptRef(version=prompt.version, sha256=prompt.sha256)
    return refs


# --- formatting -------------------------------------------------------------


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _interval(iv: Interval | None, fmt: str = "{:.0%}") -> tuple[str, str]:
    if iv is None:
        return "n/a", "n/a"
    return fmt.format(iv.value), f"[{fmt.format(iv.low)}, {fmt.format(iv.high)}]"


def _per_role(values: dict[str, float], fmt: str) -> str:
    return ", ".join(f"{r} {fmt.format(v)}" for r, v in values.items()) or "n/a"


def summary_markdown(summary: EvalSummary) -> str:
    o = summary.overall
    accuracy, accuracy_iv = _interval(o.accuracy)
    confidence, confidence_iv = _interval(o.mean_confidence, "{:.2f}")
    per_run = "n/a" if o.cost_per_run_usd is None else f"${o.cost_per_run_usd:.4f}"
    lines = [f"# Eval {summary.created_at:%Y-%m-%d %H:%M} UTC", ""]
    lines += [f"> **Warning:** {w}" for w in summary.warnings]
    lines += [
        "",
        f"n = {summary.n} per case, seed {summary.seed}, cases from "
        f"`{summary.cases_dir}`, run budget ${summary.run_budget_usd:.2f}.",
        "Models: " + ", ".join(f"{k} `{v}`" for k, v in summary.models.items()),
        "Prompts: "
        + ", ".join(
            f"{k} v{p.version} `{p.sha256[:8]}`" for k, p in summary.prompts.items()
        ),
        "",
        "| Metric | Value | 95% interval (over cases) |",
        "| --- | --- | --- |",
        f"| Accuracy against `expected` | {accuracy} | {accuracy_iv} |",
        f"| Mean confidence | {confidence} | {confidence_iv} |",
        f"| Runs (completed / failed / budget stops) | {o.runs} ({o.completed} / "
        f"{o.failed} / {o.budget_stops}) | |",
        f"| Cases without a completed run | {o.cases_without_result} | |",
        f"| Total cost | ${o.cost_usd:.4f} | |",
        f"| Cost per run | {per_run} | |",
        f"| Retry rate | {_per_role(o.retry_rate, '{:.0%}')} | |",
        f"| Mean seconds per call | {_per_role(o.mean_seconds, '{:.1f}')} | |",
        "",
        "| Case | Kind | Expected | Winners c/r/u | Agreement | Confidence "
        "mean ± sd | Cost | Retry rate | Failed |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c in summary.cases:
        w = c.winners
        conf = "n/a"
        if c.confidence:
            sd = "n/a" if c.confidence.sd is None else f"{c.confidence.sd:.2f}"
            conf = f"{c.confidence.mean:.2f} ± {sd}"
        lines.append(
            f"| {c.case_id} | {c.kind} | {c.expected} | {w['claimant']}/"
            f"{w['respondent']}/{w['undecidable']} | {_pct(c.agreement)} | {conf} | "
            f"${c.cost_usd:.4f} | {_per_role(c.retry_rate, '{:.0%}')} | {c.failed} |"
        )
    failures = [f for c in summary.cases for f in c.failures]
    if failures:
        lines += ["", "## Failures", ""]
        for f in failures:
            stop = " (budget stop)" if f.budget_stop else ""
            lines.append(f"- `{f.file}`{stop}: {f.error}")
    return "\n".join(lines) + "\n"


# --- dry run ----------------------------------------------------------------


class RoleEstimate(NamedTuple):
    role: str
    planned_calls: int
    past_calls: int  # 0: priced at worst case instead
    usd_per_call: float


def _calls_in(path: Path) -> list[tuple[str, AgentCall]]:
    """Every agent call logged in a run, swap, rejudge or failed file."""
    text = path.read_text(encoding="utf-8")
    for model in (Run, SwapRun, RejudgeRun, FailedRun):
        try:
            result = model.model_validate_json(text)
        except ValidationError:
            continue
        calls = list(getattr(result, "calls", {}).items())
        calls += [("judge", j.call) for j in getattr(result, "judges", [])]
        return calls
    return []  # summary files and anything else


def past_calls(dirs: list[Path]) -> list[tuple[str, AgentCall]]:
    calls = []
    for d in dirs:
        for path in sorted(d.rglob("*.json")):
            if path.name not in SUMMARY_FILES:
                calls += _calls_in(path)
    return calls


def estimate(
    cases: list[Case],
    n: int,
    calls: list[tuple[str, AgentCall]],
    models: dict[str, str | None],
) -> list[RoleEstimate]:
    """Mean past tokens per role, priced at the configured model if set."""
    planned = len(cases) * n
    estimates = []
    for role in ROLES:
        past = [c for r, c in calls if r == role]
        model = models[role]
        if past:
            per_call = mean(
                cost_usd(
                    model or c.priced_as or c.model_reported,
                    c.input_tokens,
                    c.output_tokens,
                )
                for c in past
            )
        else:
            if model is None:
                raise ValueError(f"no past {role} calls and no model configured")
            # No history: a generous prompt size and a full max_tokens reply.
            chars = len(load_prompt(role).text) + 3 * max(
                len(case.agent_text()) for case in cases
            )
            per_call = worst_case_usd(model, chars, MAX_TOKENS)
        estimates.append(RoleEstimate(role, planned, len(past), per_call))
    return estimates


def format_estimate(
    cases: list[Case],
    n: int,
    estimates: list[RoleEstimate],
    sources: list[Path],
    run_budget_usd: float,
) -> str:
    runs = len(cases) * n
    lines = [
        "== Eval plan (dry run) ==",
        f"  {len(cases)} case(s) x n={n} = {runs} runs, "
        f"{runs * CALLS_PER_RUN} model calls "
        f"(up to {runs * CALLS_PER_RUN * 2} if every call retries once)",
        f"  Estimate from past calls in: {', '.join(str(s) for s in sources)}",
        f"  {'agent':<12}{'calls':>7}{'past':>7}{'USD/call':>11}{'USD':>10}",
    ]
    total = 0.0
    for e in estimates:
        cost = e.planned_calls * e.usd_per_call
        total += cost
        note = "" if e.past_calls else "  (worst case: no past calls)"
        lines.append(
            f"  {e.role:<12}{e.planned_calls:>7}{e.past_calls:>7}"
            f"{e.usd_per_call:>11.4f}{cost:>10.4f}{note}"
        )
    lines += [
        f"  {'total':<37}{total:>10.4f}",
        f"  If every call retried once: about ${2 * total:.2f}",
        f"  Hard ceiling ({runs} runs x ${run_budget_usd:.2f} run budget): "
        f"${runs * run_budget_usd:.2f}",
    ]
    if warning := few_cases_warning(len(cases)):
        lines.append(f"  Warning: {warning}")
    lines.append("  No model calls were made.")
    return "\n".join(lines)


# --- compare ----------------------------------------------------------------


class MetricDiff(NamedTuple):
    metric: str
    a: float | None
    b: float | None
    interval: Interval | None  # of b − a, where defined


def _prompt(ref: PromptRef | None) -> str:
    return "none" if ref is None else f"v{ref.version} {ref.sha256[:8]}"


def _value(interval: Interval | None) -> float | None:
    return None if interval is None else interval.value


def _diff(metric: str, a: float | None, b: float | None) -> MetricDiff:
    return MetricDiff(metric, a, b, None)


def compare(
    a: EvalSummary, b: EvalSummary, seed: int
) -> tuple[list[MetricDiff], list[str]]:
    """Differences b − a per metric, and warnings about what differs besides."""
    ca = {c.case_id: c for c in a.cases}
    cb = {c.case_id: c for c in b.cases}
    notes = []
    if ca.keys() != cb.keys():
        notes.append(
            f"Case sets differ: only in a {sorted(ca.keys() - cb.keys())}, "
            f"only in b {sorted(cb.keys() - ca.keys())}. Intervals use shared cases."
        )
    for k in sorted(ca.keys() & cb.keys()):
        if ca[k].case_sha256 != cb[k].case_sha256:
            notes.append(f"{k}: case file changed between a and b")
    for role in sorted(a.prompts.keys() | b.prompts.keys()):
        pa, pb = a.prompts.get(role), b.prompts.get(role)
        if pa != pb:
            notes.append(f"Prompt {role}: {_prompt(pa)} -> {_prompt(pb)}")
    for key in sorted(a.models.keys() | b.models.keys()):
        if a.models.get(key) != b.models.get(key):
            notes.append(f"Model {key}: {a.models.get(key)} -> {b.models.get(key)}")

    agree_a = {k: c.agreement for k, c in ca.items() if c.agreement is not None}
    agree_b = {k: c.agreement for k, c in cb.items() if c.agreement is not None}
    conf_a = {k: c.confidence.mean for k, c in ca.items() if c.confidence}
    conf_b = {k: c.confidence.mean for k, c in cb.items() if c.confidence}
    oa, ob = a.overall, b.overall
    diffs = [
        MetricDiff(
            "accuracy",
            _value(oa.accuracy),
            _value(ob.accuracy),
            paired_bootstrap_diff(agree_a, agree_b, seed),
        ),
        MetricDiff(
            "mean confidence",
            _value(oa.mean_confidence),
            _value(ob.mean_confidence),
            paired_bootstrap_diff(conf_a, conf_b, seed),
        ),
        _diff("cost per run (USD)", oa.cost_per_run_usd, ob.cost_per_run_usd),
        _diff(
            "failed share",
            oa.failed / oa.runs if oa.runs else None,
            ob.failed / ob.runs if ob.runs else None,
        ),
        _diff("budget stops", oa.budget_stops, ob.budget_stops),
    ]
    for role in ROLES:
        diffs.append(
            _diff(
                f"retry rate {role}", oa.retry_rate.get(role), ob.retry_rate.get(role)
            )
        )
    for role in ROLES:
        diffs.append(
            _diff(
                f"mean seconds {role}",
                oa.mean_seconds.get(role),
                ob.mean_seconds.get(role),
            )
        )
    for k in sorted(ca.keys() & cb.keys()):
        diffs.append(_diff(f"{k} agreement", ca[k].agreement, cb[k].agreement))
        diffs.append(_diff(f"{k} confidence", conf_a.get(k), conf_b.get(k)))
    return diffs, notes


def format_compare(diffs: list[MetricDiff], notes: list[str]) -> str:
    def num(x: float | None) -> str:
        return "n/a" if x is None else f"{x:.3f}"

    lines = ["== Eval compare (b - a) =="]
    lines += [f"  Note: {note}" for note in notes]
    lines.append(f"  {'metric':<28}{'a':>9}{'b':>9}{'b - a':>9}  95% interval")
    for d in diffs:
        delta = None if d.a is None or d.b is None else d.b - d.a
        iv = (
            ""
            if d.interval is None
            else f"[{d.interval.low:.3f}, {d.interval.high:.3f}]"
        )
        lines.append(f"  {d.metric:<28}{num(d.a):>9}{num(d.b):>9}{num(delta):>9}  {iv}")
    return "\n".join(lines)


# --- baseline ---------------------------------------------------------------


def load_summary(path: Path) -> EvalSummary:
    return EvalSummary.model_validate_json(path.read_text(encoding="utf-8"))


def save_baseline(source: Path, baselines_dir: Path) -> Path:
    """Copy a summary.json, named by its eval's timestamp; never overwrite."""
    try:
        summary = load_summary(source)
    except (OSError, ValidationError) as e:
        raise BaselineError(f"{source} is not a readable eval summary: {e}") from e
    stamp = source.parent.name
    if not STAMP.fullmatch(stamp):
        stamp = f"{summary.created_at:%Y%m%dT%H%M%SZ}"
    target = baselines_dir / f"{stamp}.json"
    if target.exists():
        raise BaselineError(f"{target} already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target
