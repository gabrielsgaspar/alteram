"""Eval tests with fake chat models and hand-made run files: no network, no .env."""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_graph import (
    JUDGE_MODEL,
    LAWYER_MODEL,
    VERDICT,
    argument,
    factory,
    fakes,
    reply,
)

from alteram import cli
from alteram.evaluate import (
    Saved,
    bootstrap_mean,
    compare,
    load_results,
    paired_bootstrap_diff,
    plan_runs,
    summarize,
    summary_markdown,
)
from alteram.events import events_path, load_events
from alteram.graph import JUDGE_MODEL_ENV, LAWYER_MODEL_ENV, run_case
from alteram.models import (
    AgentCall,
    Argument,
    Case,
    EvalSummary,
    FailedRun,
    PromptRef,
    Run,
    Verdict,
)
from alteram.pricing import RUN_BUDGET_ENV

CASES = Path(__file__).resolve().parents[1] / "cases"
STAMP_TIME = datetime(2026, 10, 28, 14, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)  # never read the real .env
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-value-3c9d")
    monkeypatch.setenv(LAWYER_MODEL_ENV, LAWYER_MODEL)
    monkeypatch.setenv(JUDGE_MODEL_ENV, JUDGE_MODEL)


def no_model(*args: object) -> None:
    raise AssertionError("the model factory must not be called")


def two_cases(tmp_path: Path) -> Path:
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    for name in ("case-001.md", "case-002.md"):
        shutil.copy(CASES / name, cases_dir / name)
    return cases_dir


def replies(count: int) -> dict:
    return fakes(
        claimant=[reply(argument()) for _ in range(count)],
        respondent=[reply(argument()) for _ in range(count)],
        judge=[reply(VERDICT, model=JUDGE_MODEL) for _ in range(count)],
    )


# --- running ------------------------------------------------------------------


def test_plan_alternates_orders_within_and_across_cases(case: Case) -> None:
    other = case.model_copy(update={"id": "case-y"})
    planned = [
        (p.case.id, p.repeat, p.judge_order) for p in plan_runs([case, other], 3)
    ]
    assert planned == [
        ("case-x", 1, "claimant_first"),
        ("case-x", 2, "respondent_first"),
        ("case-x", 3, "claimant_first"),
        ("case-y", 1, "respondent_first"),
        ("case-y", 2, "claimant_first"),
        ("case-y", 3, "respondent_first"),
    ]


def test_eval_runs_n_per_case_with_alternating_orders(tmp_path: Path) -> None:
    models = replies(6)
    argv = ["eval", "--cases", str(two_cases(tmp_path)), "--n", "3"]
    code = cli.main(argv, factory(models), tmp_path / "runs", eval_dir=tmp_path / "e")
    assert code == 0
    [out_dir] = (tmp_path / "e" / "runs").iterdir()
    files = sorted(p.relative_to(out_dir).as_posix() for p in out_dir.rglob("r*.json"))
    assert files == [
        "case-001/r1-claimant_first.json",
        "case-001/r2-respondent_first.json",
        "case-001/r3-claimant_first.json",
        "case-002/r1-respondent_first.json",
        "case-002/r2-claimant_first.json",
        "case-002/r3-respondent_first.json",
    ]
    for path in out_dir.rglob("r*.json"):
        run = Run.model_validate_json(path.read_text(encoding="utf-8"))
        assert path.stem.endswith(run.judge_order)
    assert len(models["judge"].seen) == 6
    summary = EvalSummary.model_validate_json((out_dir / "summary.json").read_text())
    assert summary.overall.runs == 6 and summary.overall.completed == 6
    assert (out_dir / "summary.md").read_text().startswith("# Eval")


def test_failed_run_is_recorded_and_the_eval_continues(tmp_path: Path) -> None:
    bad = {**VERDICT, "reasons": [{"label": "C1", "finding": "f", "citations": [99]}]}
    models = fakes(
        claimant=[reply(argument()) for _ in range(3)],
        respondent=[reply(argument()) for _ in range(3)],
        judge=[reply(VERDICT, model=JUDGE_MODEL)]
        + [reply(bad, model=JUDGE_MODEL) for _ in range(2)]
        + [reply(VERDICT, model=JUDGE_MODEL)],
    )
    cases_dir = two_cases(tmp_path)
    (cases_dir / "case-002.md").unlink()
    argv = ["eval", "--cases", str(cases_dir), "--n", "3"]
    code = cli.main(argv, factory(models), tmp_path / "runs", eval_dir=tmp_path / "e")
    assert code == 1
    [out_dir] = (tmp_path / "e" / "runs").iterdir()
    names = sorted(p.name for p in (out_dir / "case-001").glob("*.json"))
    assert names == [
        "r1-claimant_first.json",
        "r2-respondent_first-failed.json",
        "r3-claimant_first.json",
    ]
    # Each run, failed or not, has its events beside it; load_results ignores them.
    for name in names:
        events = load_events(events_path(out_dir / "case-001" / name))
        assert events[0].type == "state_change"
    failed_events = load_events(events_path(out_dir / "case-001" / names[1]))
    assert failed_events[-1].type == "error"
    assert len(load_results(out_dir)) == 3
    failed = FailedRun.model_validate_json(
        (out_dir / "case-001" / names[1]).read_text(encoding="utf-8")
    )
    assert failed.judge_order == "respondent_first" and not failed.budget_stop
    summary = EvalSummary.model_validate_json((out_dir / "summary.json").read_text())
    [stats] = summary.cases
    assert (stats.completed, stats.failed, stats.budget_stops) == (2, 1, 0)
    assert "failed checks twice" in stats.failures[0].error
    assert stats.retry_rate["judge"] == pytest.approx(1 / 3)


def test_budget_stops_are_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(RUN_BUDGET_ENV, "0.5")  # the judge's worst case never fits
    cases_dir = two_cases(tmp_path)
    (cases_dir / "case-002.md").unlink()
    argv = ["eval", "--cases", str(cases_dir), "--n", "2"]
    code = cli.main(
        argv, factory(replies(2)), tmp_path / "runs", eval_dir=tmp_path / "e"
    )
    assert code == 1
    [out_dir] = (tmp_path / "e" / "runs").iterdir()
    summary = EvalSummary.model_validate_json((out_dir / "summary.json").read_text())
    assert summary.overall.budget_stops == 2 and summary.overall.completed == 0
    assert summary.overall.accuracy is None
    assert summary.overall.cases_without_result == 1


def test_agent_calls_record_seconds(case: Case) -> None:
    run = run_case(case, "claimant_first", factory(fakes()))
    assert all(c.seconds is not None and c.seconds >= 0 for c in run.calls.values())


def test_n_must_be_positive() -> None:
    with pytest.raises(SystemExit):
        cli.parse_args(["eval", "--n", "0"])


# --- hand-made run files ----------------------------------------------------------


def call(role: str, attempts: int = 1, seconds: float = 10.0) -> AgentCall:
    return AgentCall(
        model_configured=JUDGE_MODEL if role == "judge" else LAWYER_MODEL,
        model_reported=JUDGE_MODEL if role == "judge" else LAWYER_MODEL,
        prompt_version=1,
        prompt_sha256="0" * 64,
        effort="high",
        max_tokens=32000,
        stop_reason="end_turn",
        attempts=attempts,
        input_tokens=1000,
        output_tokens=2000,
        cost_usd=0.0,
        seconds=seconds,
    )


def made_run(
    case_id: str,
    order: str,
    winner: str,
    confidence: float,
    cost: float,
    judge_attempts: int = 1,
) -> Run:
    """A run whose three calls cost `cost` in all, judge 20 s, lawyers 10 s."""
    calls = {
        "claimant": call("claimant"),
        "respondent": call("respondent"),
        "judge": call("judge", judge_attempts, seconds=20.0),
    }
    calls["judge"].cost_usd = cost
    verdict = {
        **VERDICT,
        "winner": winner,
        "confidence": confidence,
        "missing_fact": "the date" if winner == "undecidable" else "",
    }
    return Run(
        case_id=case_id,
        case_sha256="0" * 64,
        judge_order=order,
        started_at=STAMP_TIME,
        finished_at=STAMP_TIME,
        claimant=Argument.model_validate(argument()),
        respondent=Argument.model_validate({**argument(), "side": "respondent"}),
        verdict=Verdict.model_validate(verdict),
        calls=calls,
    )


def made_failed(case_id: str, order: str, cost: float) -> FailedRun:
    return FailedRun(
        command="run",
        case_id=case_id,
        case_sha256="0" * 64,
        started_at=STAMP_TIME,
        finished_at=STAMP_TIME,
        error="AgentError: judge failed checks twice: bad citation",
        cost_usd=cost,
        judge_order=order,
        calls={"judge": call("judge", attempts=2, seconds=30.0)},
    )


def made_cases(case: Case) -> list[Case]:
    return [case, case.model_copy(update={"id": "case-y", "expected": "undecidable"})]


def write(out_dir: Path, name: str, result: Run | FailedRun) -> None:
    path = out_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")


def made_summary(cases: list[Case], saved: list[Saved]) -> EvalSummary:
    return summarize(
        cases,
        saved,
        n=3,
        seed=0,
        cases_dir="cases",
        models={"lawyer": LAWYER_MODEL, "judge": JUDGE_MODEL},
        prompts={"judge": PromptRef(version=2, sha256="a" * 64)},
        run_budget_usd=5.0,
        created_at=STAMP_TIME,
    )


def test_summary_on_hand_made_run_files(tmp_path: Path, case: Case) -> None:
    files = {
        "case-x/r1-claimant_first.json": made_run(
            "case-x", "claimant_first", "claimant", 0.8, 0.10
        ),
        "case-x/r2-respondent_first.json": made_run(
            "case-x", "respondent_first", "respondent", 0.6, 0.10, judge_attempts=2
        ),
        "case-x/r3-claimant_first-failed.json": made_failed(
            "case-x", "claimant_first", 0.05
        ),
        "case-y/r1-respondent_first.json": made_run(
            "case-y", "respondent_first", "undecidable", 0.5, 0.10
        ),
        "case-y/r2-claimant_first.json": made_run(
            "case-y", "claimant_first", "undecidable", 0.7, 0.10
        ),
    }
    for name, result in files.items():
        write(tmp_path, name, result)

    summary = made_summary(made_cases(case), load_results(tmp_path))

    x, y = summary.cases
    assert (x.runs, x.completed, x.failed, x.budget_stops) == (3, 2, 1, 0)
    assert x.winners == {"claimant": 1, "respondent": 1, "undecidable": 0}
    assert x.winners_by_order == {
        "claimant_first": ["claimant"],
        "respondent_first": ["respondent"],
    }
    assert x.agreement == 0.5
    assert x.confidence is not None
    assert x.confidence.mean == pytest.approx(0.7)
    assert x.confidence.sd == pytest.approx(0.1414, abs=1e-4)  # sample SD of .8, .6
    assert (x.confidence.min, x.confidence.max) == (0.6, 0.8)
    assert x.cost_usd == pytest.approx(0.25)
    assert x.retry_rate == {"claimant": 0.0, "respondent": 0.0, "judge": 2 / 3}
    assert x.mean_seconds == {
        "claimant": 10.0,
        "respondent": 10.0,
        "judge": pytest.approx(70 / 3),
    }
    [failure] = x.failures
    assert failure.file == "case-x/r3-claimant_first-failed.json"
    assert failure.judge_order == "claimant_first" and not failure.budget_stop

    assert y.agreement == 1.0 and y.expected == "undecidable"
    assert y.confidence is not None and y.confidence.mean == pytest.approx(0.6)

    o = summary.overall
    assert (o.cases, o.runs, o.completed, o.failed, o.budget_stops) == (2, 5, 4, 1, 0)
    assert o.cases_without_result == 0
    assert o.accuracy is not None and o.accuracy.value == pytest.approx(0.75)
    assert o.accuracy.low <= 0.75 <= o.accuracy.high
    assert o.mean_confidence is not None
    assert o.mean_confidence.value == pytest.approx(0.65)
    assert o.cost_usd == pytest.approx(0.45)
    assert o.cost_per_run_usd == pytest.approx(0.09)
    assert o.retry_rate == {"claimant": 0.0, "respondent": 0.0, "judge": 0.4}
    assert o.mean_seconds["judge"] == pytest.approx(22.0)  # 20, 20, 30, 20, 20
    assert len(summary.warnings) == 1 and "Only 2 case(s)" in summary.warnings[0]

    markdown = summary_markdown(summary)
    assert "| Accuracy against `expected` | 75% |" in markdown
    assert "case-x/r3-claimant_first-failed.json" in markdown


# --- bootstrap ----------------------------------------------------------------------


def test_bootstrap_is_reproducible_with_the_seed() -> None:
    values = [1.0, 0.0, 0.5, 1.0, 0.25]
    first = bootstrap_mean(values, seed=7)
    assert first == bootstrap_mean(values, seed=7)
    assert first is not None and first.low <= first.value <= first.high
    assert first.low < first.high


def test_bootstrap_is_one_one_when_every_case_is_correct() -> None:
    interval = bootstrap_mean([1.0, 1.0, 1.0, 1.0], seed=0)
    assert interval is not None
    assert (interval.value, interval.low, interval.high) == (1.0, 1.0, 1.0)


def test_bootstrap_of_nothing_is_none() -> None:
    assert bootstrap_mean([], seed=0) is None
    assert paired_bootstrap_diff({"a": 1.0}, {"b": 1.0}, seed=0) is None


# --- dry run ------------------------------------------------------------------------


def test_dry_run_never_calls_the_model_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY")  # a dry run needs no key
    runs_dir = tmp_path / "runs"
    past = made_run("case-x", "claimant_first", "claimant", 0.8, 0.10)
    write(runs_dir, "case-x/20261026T000000Z.json", past)
    argv = ["eval", "--dry-run", "--n", "2", "--cases", str(CASES)]
    assert cli.main(argv, no_model, runs_dir, eval_dir=tmp_path / "e") == 0
    out = capsys.readouterr().out
    assert "4 case(s) x n=2 = 8 runs, 24 model calls" in out
    # Past tokens re-priced: Sonnet 1000 in, 2000 out = $0.022; Opus = $0.044.
    assert "claimant          8      1     0.0220    0.1760" in out
    assert "judge             8      1     0.0440    0.3520" in out
    assert "Hard ceiling (8 runs x $5.00 run budget): $40.00" in out
    assert "Only 4 case(s)" in out and "No model calls were made." in out
    assert not (tmp_path / "e").exists()


def test_dry_run_without_history_uses_the_worst_case(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["eval", "--dry-run", "--cases", str(CASES)]
    assert cli.main(argv, no_model, tmp_path / "runs", eval_dir=tmp_path / "e") == 0
    assert "(worst case: no past calls)" in capsys.readouterr().out


# --- baseline and compare -----------------------------------------------------------


def summary_pair(case: Case) -> tuple[EvalSummary, EvalSummary]:
    """b fixes case-x's second run and costs more per run."""
    cases = made_cases(case)
    y = [
        Saved("y1", made_run("case-y", "respondent_first", "undecidable", 0.5, 0.1)),
        Saved("y2", made_run("case-y", "claimant_first", "undecidable", 0.7, 0.1)),
    ]
    a = made_summary(
        cases,
        [
            Saved("x1", made_run("case-x", "claimant_first", "claimant", 0.8, 0.1)),
            Saved(
                "x2", made_run("case-x", "respondent_first", "respondent", 0.6, 0.1, 2)
            ),
            *y,
        ],
    )
    b = made_summary(
        cases,
        [
            Saved("x1", made_run("case-x", "claimant_first", "claimant", 0.8, 0.3)),
            Saved("x2", made_run("case-x", "respondent_first", "claimant", 0.9, 0.3)),
            *y,
        ],
    )
    return a, b


def test_compare_shows_the_right_differences(case: Case) -> None:
    a, b = summary_pair(case)
    diffs, notes = compare(a, b, seed=0)
    by_name = {d.metric: d for d in diffs}
    accuracy = by_name["accuracy"]
    assert (accuracy.a, accuracy.b) == (pytest.approx(0.75), pytest.approx(1.0))
    assert accuracy.interval is not None
    assert accuracy.interval.value == pytest.approx(0.25)  # per case: +0.5 and 0
    assert 0 <= accuracy.interval.low <= accuracy.interval.high <= 0.5
    assert by_name["cost per run (USD)"].a == pytest.approx(0.1)
    assert by_name["cost per run (USD)"].b == pytest.approx(0.2)
    assert by_name["cost per run (USD)"].interval is None
    assert (by_name["retry rate judge"].a, by_name["retry rate judge"].b) == (0.25, 0)
    assert by_name["case-x agreement"].a == 0.5
    assert by_name["case-x agreement"].b == 1.0
    assert by_name["case-y agreement"].a == by_name["case-y agreement"].b == 1.0
    assert notes == []


def test_compare_identical_summaries_has_zero_interval(case: Case) -> None:
    a, _ = summary_pair(case)
    diffs, _ = compare(a, a, seed=0)
    interval = diffs[0].interval
    assert interval is not None and (interval.low, interval.high) == (0.0, 0.0)


def test_compare_warns_about_cases_prompts_and_models(case: Case) -> None:
    a, b = summary_pair(case)
    b = b.model_copy(
        update={
            "cases": b.cases[:1],
            "prompts": {"judge": PromptRef(version=3, sha256="b" * 64)},
            "models": {"lawyer": LAWYER_MODEL, "judge": "claude-fable-5-1"},
        }
    )
    _, notes = compare(a, b, seed=0)
    assert any("only in a ['case-y']" in n for n in notes)
    assert "Prompt judge: v2 aaaaaaaa -> v3 bbbbbbbb" in notes
    assert f"Model judge: {JUDGE_MODEL} -> claude-fable-5-1" in notes


def test_compare_command_prints_table(
    tmp_path: Path, case: Case, capsys: pytest.CaptureFixture[str]
) -> None:
    a, b = summary_pair(case)
    (tmp_path / "a.json").write_text(a.model_dump_json(), encoding="utf-8")
    (tmp_path / "b.json").write_text(b.model_dump_json(), encoding="utf-8")
    argv = ["eval", "compare", str(tmp_path / "a.json"), str(tmp_path / "b.json")]
    assert cli.main(argv, no_model, tmp_path, eval_dir=tmp_path / "e") == 0
    out = capsys.readouterr().out
    assert "accuracy" in out and "0.750" in out and "1.000" in out and "0.250" in out


def test_baseline_copies_and_never_overwrites(tmp_path: Path, case: Case) -> None:
    a, _ = summary_pair(case)
    source = tmp_path / "e" / "runs" / "20261028T140000Z" / "summary.json"
    source.parent.mkdir(parents=True)
    source.write_text(a.model_dump_json(indent=2), encoding="utf-8")
    argv = ["eval", "baseline", str(source)]
    assert cli.main(argv, no_model, tmp_path, eval_dir=tmp_path / "e") == 0
    target = tmp_path / "e" / "baselines" / "20261028T140000Z.json"
    assert target.read_bytes() == source.read_bytes()
    assert cli.main(argv, no_model, tmp_path, eval_dir=tmp_path / "e") == 2


def test_baseline_refuses_a_file_that_is_not_a_summary(tmp_path: Path) -> None:
    source = tmp_path / "summary.json"
    source.write_text(json.dumps({"not": "a summary"}), encoding="utf-8")
    argv = ["eval", "baseline", str(source)]
    assert cli.main(argv, no_model, tmp_path, eval_dir=tmp_path / "e") == 2
    assert not (tmp_path / "e").exists()
