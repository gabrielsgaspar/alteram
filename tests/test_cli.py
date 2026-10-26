"""CLI and swap tests with fake chat models only: no network, no .env."""

import re
from collections import Counter
from pathlib import Path

import pytest
from test_graph import VERDICT, factory, fakes, reply

from alteram import cli
from alteram.graph import JUDGE_MODEL_ENV, LAWYER_MODEL_ENV
from alteram.models import (
    AgentCall,
    FailedRun,
    JudgeResult,
    Run,
    SwapRun,
    Verdict,
)
from alteram.swap import summarize

CASE_001 = Path(__file__).resolve().parents[1] / "cases" / "case-001.md"
FAKE_KEY = "fake-key-value-3c9d"


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)  # never read the real .env
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    monkeypatch.setenv(LAWYER_MODEL_ENV, "fake-lawyer")
    monkeypatch.setenv(JUDGE_MODEL_ENV, "fake-judge")


def saved(runs_dir: Path) -> list[Path]:
    return list(runs_dir.rglob("*.json"))


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
    assert "judge hit max_tokens" in capsys.readouterr().err


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
    for value in (FAKE_KEY, "fake-lawyer", "fake-judge"):
        assert value not in out.err + out.out
    assert saved(tmp_path) == []


def test_repeats_must_be_positive() -> None:
    with pytest.raises(SystemExit):
        cli.main(["swap", str(CASE_001), "--repeats", "0"])
