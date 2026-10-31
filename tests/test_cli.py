"""CLI and swap tests with fake chat models only: no network, no .env."""

import importlib.metadata
import re
from collections import Counter
from pathlib import Path

import pytest
from test_graph import JUDGE_MODEL, LAWYER_MODEL, VERDICT, factory, fakes, reply

from alteram import cli
from alteram.events import events_path, format_event, load_events
from alteram.graph import JUDGE_MODEL_ENV, LAWYER_MODEL_ENV
from alteram.models import (
    AgentCall,
    FailedRun,
    JudgeResult,
    Run,
    SwapRun,
    Verdict,
)
from alteram.pricing import RUN_BUDGET_ENV
from alteram.swap import summarize

CASE_001 = Path(__file__).resolve().parents[1] / "cases" / "case-001.md"
FAKE_KEY = "fake-key-value-3c9d"


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)  # never read the real .env
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    monkeypatch.setenv(LAWYER_MODEL_ENV, LAWYER_MODEL)
    monkeypatch.setenv(JUDGE_MODEL_ENV, JUDGE_MODEL)
    monkeypatch.delenv(RUN_BUDGET_ENV, raising=False)


def saved(runs_dir: Path) -> list[Path]:
    return list(runs_dir.rglob("*.json"))


def test_version_prints_package_version_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def no_model(*args: object) -> None:
        raise AssertionError("--version must not build a model")

    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"], no_model)
    assert exc.value.code == 0
    assert importlib.metadata.version("alteram") in capsys.readouterr().out


def test_run_help_does_not_list_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["run", "--help"])
    assert "--version" not in capsys.readouterr().out


def test_run_saves_valid_run_with_windows_safe_name(tmp_path: Path) -> None:
    code = cli.main(["run", str(CASE_001)], factory(fakes()), tmp_path)
    assert code == 0
    [path] = saved(tmp_path)
    assert path.parent == tmp_path / "case-001"
    assert re.fullmatch(r"\d{8}T\d{6}Z\.json", path.name)
    run = Run.model_validate_json(path.read_text(encoding="utf-8"))
    assert run.case_id == "case-001" and run.judge_order == "claimant_first"


def test_run_respects_order(tmp_path: Path) -> None:
    cli.main(
        ["run", str(CASE_001), "--order", "respondent_first"],
        factory(fakes()),
        tmp_path,
    )
    [path] = saved(tmp_path)
    run = Run.model_validate_json(path.read_text(encoding="utf-8"))
    assert run.judge_order == "respondent_first"


def test_swap_runs_lawyers_once_and_judge_twice_per_repeat(tmp_path: Path) -> None:
    models = fakes(judge=[reply(VERDICT) for _ in range(6)])
    code = cli.main(
        ["swap", str(CASE_001), "--repeats", "3"], factory(models), tmp_path
    )
    assert code == 0
    assert len(models["claimant"].seen) == 1
    assert len(models["respondent"].seen) == 1
    assert len(models["judge"].seen) == 6
    [path] = saved(tmp_path)
    assert re.fullmatch(r"\d{8}T\d{6}Z-swap\.json", path.name)
    swap = SwapRun.model_validate_json(path.read_text(encoding="utf-8"))
    assert Counter(j.judge_order for j in swap.judges) == {
        "claimant_first": 3,
        "respondent_first": 3,
    }
    assert set(swap.calls) == {"claimant", "respondent"}


def judged(order: str, winner: str, confidence: float) -> JudgeResult:
    verdict = Verdict.model_validate(
        VERDICT
        | {
            "winner": winner,
            "confidence": confidence,
            "missing_fact": "m" if winner == "undecidable" else "",
        }
    )
    call = AgentCall(
        model_configured="m",
        model_reported="m",
        prompt_version=1,
        prompt_sha256="0",
        effort="high",
        max_tokens=1,
        stop_reason="end_turn",
        attempts=1,
        input_tokens=0,
        output_tokens=0,
    )
    return JudgeResult(judge_order=order, verdict=verdict, call=call)


def test_summarize_disagreement() -> None:
    judges = [
        judged("claimant_first", "claimant", 0.8),
        judged("claimant_first", "claimant", 0.6),
        judged("claimant_first", "respondent", 0.4),
        judged("respondent_first", "respondent", 0.5),
        judged("respondent_first", "respondent", 0.5),
        judged("respondent_first", "respondent", 0.8),
    ]
    summary = summarize(judges)
    assert summary.winners["claimant_first"] == ["claimant", "claimant", "respondent"]
    assert summary.mean_confidence["claimant_first"] == pytest.approx(0.6)
    assert summary.mean_confidence["respondent_first"] == pytest.approx(0.6)
    # Within: claimant_first has 2 of 3 pairs differing, respondent_first 0 of 3.
    assert summary.within_order_disagreement == pytest.approx(2 / 6)
    # Across: the two "claimant" verdicts differ from all 3 others: 6 of 9 pairs.
    assert summary.across_order_disagreement == pytest.approx(6 / 9)


def test_summarize_one_repeat_has_no_within_pairs() -> None:
    summary = summarize(
        [
            judged("claimant_first", "claimant", 1),
            judged("respondent_first", "claimant", 1),
        ]
    )
    assert summary.within_order_disagreement is None
    assert summary.across_order_disagreement == 0


def test_failed_judge_saves_completed_arguments(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    models = fakes(judge=[reply(VERDICT, stop_reason="max_tokens")])
    code = cli.main(["run", str(CASE_001)], factory(models), tmp_path)
    assert code == 1
    [path] = saved(tmp_path)
    assert re.fullmatch(r"\d{8}T\d{6}Z-failed\.json", path.name)
    failed = FailedRun.model_validate_json(path.read_text(encoding="utf-8"))
    assert failed.command == "run"
    assert "judge hit max_tokens" in failed.error
    assert failed.claimant is not None and failed.claimant.points[0].label == "C1"
    assert failed.respondent is not None
    assert set(failed.calls) == {"claimant", "respondent", "judge"}
    assert failed.calls["judge"].output_tokens == 5
    # The judge's truncated answer was still paid for.
    paid = sum(call.cost_usd or 0 for call in failed.calls.values())
    assert paid > 0 and failed.cost_usd == pytest.approx(paid)
    err = capsys.readouterr().err
    assert "judge hit max_tokens" in err
    assert f"Spent before failing: ${paid:.4f}" in err


def test_failed_swap_saves_completed_judges(tmp_path: Path) -> None:
    bad = reply(VERDICT, stop_reason="max_tokens")
    models = fakes(judge=[reply(VERDICT), bad])
    code = cli.main(["swap", str(CASE_001)], factory(models), tmp_path)
    assert code == 1
    [path] = saved(tmp_path)
    failed = FailedRun.model_validate_json(path.read_text(encoding="utf-8"))
    assert failed.command == "swap"
    assert [j.judge_order for j in failed.judges] == ["claimant_first"]
    assert failed.calls["judge"].stop_reason == "max_tokens"


@pytest.mark.parametrize("command", ["run", "swap"])
def test_missing_env_names_vars_without_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    monkeypatch.delenv(LAWYER_MODEL_ENV)
    monkeypatch.setenv(JUDGE_MODEL_ENV, "")

    def no_model(*args: object) -> None:
        raise AssertionError("no model may be built without the env vars")

    code = cli.main([command, str(CASE_001)], no_model, tmp_path)
    assert code != 0
    out = capsys.readouterr()
    assert LAWYER_MODEL_ENV in out.err and JUDGE_MODEL_ENV in out.err
    assert "ANTHROPIC_API_KEY" not in out.err  # it is set
    for value in (FAKE_KEY, LAWYER_MODEL, JUDGE_MODEL):
        assert value not in out.err + out.out
    assert saved(tmp_path) == []


def test_repeats_must_be_positive() -> None:
    with pytest.raises(SystemExit):
        cli.main(["swap", str(CASE_001), "--repeats", "0"])


def test_run_prints_cost_per_agent_and_total(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["run", str(CASE_001)], factory(fakes()), tmp_path)
    out = capsys.readouterr().out
    # Each fake reply: 10 in, 5 out at Sonnet's $2 / $10 = $0.00007.
    for role in ("claimant", "respondent", "judge"):
        assert re.search(rf"{role}\s+1\s+10\s+5\s+0\.0001$", out, re.M)
    assert re.search(r"total\s+0\.0002$", out, re.M)  # 3 x $0.00007


def test_swap_prints_total_cost(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    models = fakes(judge=[reply(VERDICT) for _ in range(2)])
    cli.main(["swap", str(CASE_001), "--repeats", "1"], factory(models), tmp_path)
    out = capsys.readouterr().out
    assert re.search(r"judge x2\s+2\s+20\s+10\s+0\.0001$", out, re.M)
    assert re.search(r"total\s+0\.0003$", out, re.M)  # 4 x $0.00007


@pytest.mark.parametrize("command", ["run", "swap"])
def test_budget_stop_is_saved_as_a_failed_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    # Each lawyer's worst case on case-001 is about $0.33, the judge's over $0.65.
    # In a swap the lawyers run in turn and fit, and the judge is refused. In a
    # run they start together and, depending on timing, the second lawyer or
    # the judge is refused. The judge never fits.
    monkeypatch.setenv(RUN_BUDGET_ENV, "0.5")
    models = fakes()
    code = cli.main([command, str(CASE_001)], factory(models), tmp_path)
    assert code == 1
    assert models["judge"].seen == []
    lawyer_replies = len(models["claimant"].seen) + len(models["respondent"].seen)
    if command == "swap":
        assert lawyer_replies == 2
    [path] = saved(tmp_path)
    failed = FailedRun.model_validate_json(path.read_text(encoding="utf-8"))
    assert "not called: budget $0.50 could be exceeded" in failed.error
    one_reply = (10 * 2 + 5 * 10) / 1_000_000
    assert failed.cost_usd == pytest.approx(lawyer_replies * one_reply)
    assert "Spent before failing: $0.0001" in capsys.readouterr().err


@pytest.mark.parametrize("raw", ["five", "0"])
def test_bad_budget_env_stops_before_any_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    raw: str,
) -> None:
    monkeypatch.setenv(RUN_BUDGET_ENV, raw)

    def no_model(*args: object) -> None:
        raise AssertionError("no model may be built with a bad budget")

    assert cli.main(["run", str(CASE_001)], no_model, tmp_path) == 2
    assert RUN_BUDGET_ENV in capsys.readouterr().err
    assert saved(tmp_path) == []


@pytest.mark.parametrize(
    ("argv", "judge", "suffix", "last"),
    [
        (["run"], [reply(VERDICT)], "", "decided"),
        (["swap", "--repeats", "1"], [reply(VERDICT)] * 2, "-swap", "decided"),
        (["run"], [reply(VERDICT, stop_reason="max_tokens")], "-failed", "error"),
    ],
    ids=["run", "swap", "failed-run"],
)
def test_events_are_saved_beside_the_run_file(
    tmp_path: Path, argv: list[str], judge: list, suffix: str, last: str
) -> None:
    argv = [argv[0], str(CASE_001), *argv[1:]]
    cli.main(argv, factory(fakes(judge=judge)), tmp_path)
    [path] = saved(tmp_path)
    assert path.name.endswith(f"{suffix}.json")
    events = load_events(events_path(path))
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert {e.case_id for e in events} == {"case-001"}
    assert events[-1].payload.get("to", events[-1].type) == last


def test_run_follow_prints_events_as_they_happen(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(["run", str(CASE_001), "--follow"], factory(fakes()), tmp_path)
    assert code == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.startswith("#")]
    [path] = saved(tmp_path)
    events = load_events(events_path(path))
    assert lines == [format_event(e) for e in events]
    assert out.index(lines[-1]) < out.index("== Claimant ==")  # before the summary


def test_run_without_follow_prints_no_events(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["run", str(CASE_001)], factory(fakes()), tmp_path)
    assert "agent_call_started" not in capsys.readouterr().out
