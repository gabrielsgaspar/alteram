"""Event model, log, file format and the --follow line."""

from datetime import UTC, datetime
from pathlib import Path

from alteram.events import (
    EventLog,
    draft,
    emitter,
    events_path,
    format_event,
    load_events,
    save_events,
    state_change,
)


def test_log_numbers_events_from_one_and_sets_case_id() -> None:
    seen = []
    log = EventLog("case-x", on_event=seen.append)
    state_change(log.add, None, "arguing")
    emitter(log.add, "arguing", "claimant_lawyer", "claimant")("retry", attempt=2)
    assert [e.seq for e in log.events] == [1, 2]
    assert {e.case_id for e in log.events} == {"case-x"}
    assert seen == log.events
    assert log.events[1].payload == {"attempt": 2}
    assert (log.events[1].agent, log.events[1].side) == ("claimant_lawyer", "claimant")


def test_events_file_parses_back_into_events(tmp_path: Path) -> None:
    log = EventLog("case-x")
    state_change(log.add, None, "arguing")
    emit = emitter(log.add, "deciding", "judge", None)
    emit("agent_call_started", attempt=1, input="text", model="m")
    emit(
        "agent_call_finished",
        attempt=1,
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.5,
    )
    emit("check_failed", attempt=1, error="bad")
    emit("error", error="boom", exception="AgentError", budget_stop=False)
    path = save_events(log, tmp_path / "runs" / "x.events.jsonl")
    assert len(path.read_text(encoding="utf-8").splitlines()) == 5
    assert load_events(path) == log.events


def test_events_path_sits_beside_the_run_file() -> None:
    run = Path("runs/case-001/20261028T120000Z-failed.json")
    assert events_path(run) == Path(
        "runs/case-001/20261028T120000Z-failed.events.jsonl"
    )


def test_format_event() -> None:
    log = EventLog("case-x")
    fields = draft(
        "arguing",
        "claimant_lawyer",
        "claimant",
        "agent_call_finished",
        {"attempt": 1, "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.0001},
    )
    fields["ts"] = datetime(2026, 10, 28, 12, 1, 3, tzinfo=UTC)
    log.add(fields)
    state_change(log.add, "arguing", "deciding")
    line, change = (format_event(e) for e in log.events)
    assert line.startswith("#1   12:01:03  arguing  claimant_lawyer")
    assert line.endswith("agent_call_finished attempt 1 in=10 out=5 $0.0001")
    assert change.endswith("state_change        arguing -> deciding")
