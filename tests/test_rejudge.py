"""Re-judge tests with fake chat models only: no network, no .env."""

import hashlib
import re
import shutil
from pathlib import Path

import pytest
from test_cli import CASE_001, FAKE_KEY, judged, saved
from test_graph import (
    JUDGE_MODEL,
    LAWYER_MODEL,
    VERDICT,
    RecordingFake,
    factory,
    fakes,
    human_text,
    reply,
)

from alteram import cli
from alteram.events import events_path, load_events
from alteram.graph import JUDGE_MODEL_ENV, LAWYER_MODEL_ENV
from alteram.loader import load_prompt
from alteram.models import RejudgeRun
from alteram.rejudge import stats

CASES_DIR = CASE_001.parent


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    monkeypatch.setenv(LAWYER_MODEL_ENV, LAWYER_MODEL)
    monkeypatch.setenv(JUDGE_MODEL_ENV, JUDGE_MODEL)


def judge_only(judge: RecordingFake):
    """A factory whose lawyers fail the test if they are ever built."""

    def build(role: str, *args: object) -> RecordingFake:
        assert role == "judge", f"the {role} must not be called when re-judging"
        return judge

    return build


def make_swap(tmp_path: Path) -> tuple[Path, RecordingFake]:
    """A real swap file (one repeat) made with fakes, and the judge that saw it."""
    models = fakes(judge=[reply(VERDICT), reply(VERDICT)])
    runs = tmp_path / "source-runs"
    assert (
        cli.main(["swap", str(CASE_001), "--repeats", "1"], factory(models), runs) == 0
    )
    [path] = saved(runs)
    return path, models["judge"]


def make_run(tmp_path: Path, order: str) -> tuple[Path, RecordingFake]:
    models = fakes()
    runs = tmp_path / "source-runs"
    argv = ["run", str(CASE_001), "--order", order]
    assert cli.main(argv, factory(models), runs) == 0
    [path] = saved(runs)
    return path, models["judge"]


def texts(judge: RecordingFake) -> list[str]:
    return [human_text(judge, i) for i in range(len(judge.seen))]


def test_rejudge_swap_file_never_calls_lawyers_and_passes_identical_arguments(
    tmp_path: Path,
) -> None:
    source, original = make_swap(tmp_path)
    judge = RecordingFake(messages=iter([reply(VERDICT), reply(VERDICT)]))
    runs = tmp_path / "runs"
    argv = ["rejudge", str(source), "--repeats", "1"]
    assert cli.main(argv, judge_only(judge), runs, CASES_DIR) == 0
    # Byte for byte what the original judge received, in both orders.
    assert texts(judge) == texts(original)
    assert len(texts(judge)) == 2


def test_rejudge_run_file(tmp_path: Path) -> None:
    source, original = make_run(tmp_path, "respondent_first")
    judge = RecordingFake(messages=iter([reply(VERDICT), reply(VERDICT)]))
    runs = tmp_path / "runs"
    argv = ["rejudge", str(source), "--repeats", "1"]
    assert cli.main(argv, judge_only(judge), runs, CASES_DIR) == 0
    # Order of the judge calls is claimant_first, then respondent_first.
    assert texts(judge)[1] == texts(original)[0]
    [path] = saved(runs)
    rejudge = RejudgeRun.model_validate_json(path.read_text(encoding="utf-8"))
    assert len(rejudge.source_judges) == 1
    assert rejudge.summary.source.winners["claimant_first"] == []
    assert rejudge.summary.source.winners["respondent_first"] == ["claimant"]
    assert "claimant_first" not in rejudge.summary.source.mean_confidence


def test_saved_file_records_source_prompts_and_every_result(tmp_path: Path) -> None:
    source, _ = make_swap(tmp_path)
    judge = RecordingFake(messages=iter([reply(VERDICT) for _ in range(4)]))
    runs = tmp_path / "runs"
    argv = ["rejudge", str(source), "--repeats", "2"]
    assert cli.main(argv, judge_only(judge), runs, CASES_DIR) == 0
    [path] = saved(runs)
    assert re.fullmatch(r"\d{8}T\d{6}Z-rejudge\.json", path.name)
    assert path.parent.name == "case-001"
    rejudge = RejudgeRun.model_validate_json(path.read_text(encoding="utf-8"))
    assert rejudge.source_path == str(source)
    assert rejudge.source_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    prompt = load_prompt("judge")
    assert rejudge.current_judge_prompt.version == prompt.version
    assert rejudge.current_judge_prompt.sha256 == prompt.sha256
    assert [p.version for p in rejudge.source_judge_prompts] == [prompt.version]
    assert len(rejudge.judges) == 4
    assert len(rejudge.source_judges) == 2
    assert rejudge.summary.new.winners["claimant_first"] == ["claimant"] * 2


def test_changed_case_is_refused_unless_allowed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source, _ = make_swap(tmp_path)
    cases = tmp_path / "cases"
    cases.mkdir()
    changed = cases / "case-001.md"
    shutil.copy(CASE_001, changed)
    changed.write_text(changed.read_text(encoding="utf-8") + "\n[16] New.\n")
    runs = tmp_path / "runs"
    judge = RecordingFake(messages=iter([reply(VERDICT), reply(VERDICT)]))

    code = cli.main(["rejudge", str(source)], judge_only(judge), runs, cases)
    err = capsys.readouterr().err
    assert code != 0
    assert "changed" in err and "--allow-changed-case" in err
    assert hashlib.sha256(CASE_001.read_bytes()).hexdigest() in err  # saved hash
    assert judge.seen == [] and saved(runs) == []

    argv = ["rejudge", str(source), "--repeats", "1", "--allow-changed-case"]
    assert cli.main(argv, judge_only(judge), runs, cases) == 0
    assert len(judge.seen) == 2
    [path] = saved(runs)
    events = load_events(events_path(path))
    assert [e.agent for e in events if e.type == "agent_call_started"] == ["judge"] * 2
    assert events[-1].payload == {"from": "deciding", "to": "decided"}


def test_failed_run_file_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    models = fakes(judge=[reply(VERDICT, stop_reason="max_tokens")])
    cli.main(["run", str(CASE_001)], factory(models), tmp_path / "source-runs")
    [failed] = saved(tmp_path / "source-runs")
    code = cli.main(["rejudge", str(failed)], judge_only(models["judge"]), tmp_path)
    assert code != 0
    assert "failed run" in capsys.readouterr().err


def test_missing_case_file_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source, _ = make_swap(tmp_path)
    judge = RecordingFake(messages=iter([]))
    code = cli.main(["rejudge", str(source)], judge_only(judge), tmp_path, tmp_path)
    assert code != 0
    assert "case file" in capsys.readouterr().err


def test_rejudge_needs_no_lawyer_model_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _ = make_swap(tmp_path)
    monkeypatch.delenv(LAWYER_MODEL_ENV)
    judge = RecordingFake(messages=iter([reply(VERDICT), reply(VERDICT)]))
    argv = ["rejudge", str(source), "--repeats", "1"]
    assert cli.main(argv, judge_only(judge), tmp_path / "runs", CASES_DIR) == 0


def test_rejudge_names_missing_judge_variable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(JUDGE_MODEL_ENV, "")
    code = cli.main(["rejudge", str(tmp_path / "x.json")], None, tmp_path)  # type: ignore[arg-type]
    assert code != 0
    err = capsys.readouterr().err
    assert JUDGE_MODEL_ENV in err and LAWYER_MODEL_ENV not in err


def test_failed_judge_saves_completed_results(tmp_path: Path) -> None:
    source, _ = make_swap(tmp_path)
    bad = reply(VERDICT, stop_reason="max_tokens")
    judge = RecordingFake(messages=iter([reply(VERDICT), bad]))
    runs = tmp_path / "runs"
    code = cli.main(["rejudge", str(source)], judge_only(judge), runs, CASES_DIR)
    assert code == 1
    [path] = saved(runs)
    assert path.name.endswith("-failed.json")


def test_repeats_must_be_positive() -> None:
    with pytest.raises(SystemExit):
        cli.main(["rejudge", "x.json", "--repeats", "0"])


def test_stats_on_a_hand_made_example() -> None:
    retried = judged("respondent_first", "claimant", 0.9)
    retried.call.attempts = 2
    source = stats(
        [
            judged("claimant_first", "claimant", 0.8),
            judged("respondent_first", "respondent", 0.4),
        ]
    )
    # One verdict per order: no same-order pairs; the one cross pair differs.
    assert source.winners == {
        "claimant_first": ["claimant"],
        "respondent_first": ["respondent"],
    }
    assert source.mean_confidence == pytest.approx(
        {"claimant_first": 0.8, "respondent_first": 0.4}
    )
    assert source.within_order_disagreement is None
    assert source.across_order_disagreement == 1.0
    assert source.retry_rate == 0

    new = stats(
        [
            judged("claimant_first", "claimant", 0.6),
            judged("claimant_first", "claimant", 0.8),
            judged("respondent_first", "respondent", 0.5),
            retried,
        ]
    )
    assert new.winners == {
        "claimant_first": ["claimant", "claimant"],
        "respondent_first": ["respondent", "claimant"],
    }
    assert new.mean_confidence == pytest.approx(
        {"claimant_first": 0.7, "respondent_first": 0.7}
    )
    # Within: claimant_first 0 of 1 pairs differ, respondent_first 1 of 1.
    assert new.within_order_disagreement == pytest.approx(1 / 2)
    # Across: (c,r) (c,c) (c,r) (c,c) -> 2 of 4 differ.
    assert new.across_order_disagreement == pytest.approx(2 / 4)
    assert new.retry_rate == pytest.approx(1 / 4)


def test_stats_with_one_order_only_has_no_across_pairs() -> None:
    result = stats([judged("respondent_first", "claimant", 0.5)])
    assert result.mean_confidence == {"respondent_first": 0.5}
    assert result.across_order_disagreement is None
