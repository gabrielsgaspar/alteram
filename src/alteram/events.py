"""Typed events: every agent step emits one, and each run saves them as JSON Lines."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from alteram.models import Side

# The v0 subset of the event types in ALTERAM_V1_DESIGN.md section 10.3.
EventType = Literal[
    "agent_call_started",
    "agent_call_finished",
    "check_failed",
    "retry",
    "warning",
    "state_change",
    "error",
]
# The v0 subset of the lifecycle states in section 4.2.
Stage = Literal["arguing", "deciding", "decided"]

# Where an emitted event goes before it has a seq: inside the graph, LangGraph's
# custom stream writer; outside it, EventLog.add.
Sink = Callable[[dict[str, Any]], None]
Emit = Callable[..., None]  # emit(type, **payload)


class Event(BaseModel):
    case_id: str
    seq: int  # strictly increasing within one run, from 1
    ts: datetime
    stage: Stage
    agent: str | None  # claimant_lawyer, respondent_lawyer, judge; None for the run
    side: Side | None  # None for the judge and the run
    type: EventType
    payload: dict[str, Any]


def draft(
    stage: Stage,
    agent: str | None,
    side: Side | None,
    type: EventType,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """An event without case_id and seq, stamped now."""
    return {
        "ts": datetime.now(UTC),
        "stage": stage,
        "agent": agent,
        "side": side,
        "type": type,
        "payload": payload,
    }


def emitter(sink: Sink, stage: Stage, agent: str | None, side: Side | None) -> Emit:
    def emit(type: EventType, **payload: Any) -> None:
        sink(draft(stage, agent, side, type, payload))

    return emit


def state_change(sink: Sink, old: Stage | None, new: Stage) -> None:
    sink(draft(new, None, None, "state_change", {"from": old, "to": new}))


class EventLog:
    """The events of one run, numbered in the order they arrive."""

    def __init__(
        self, case_id: str, on_event: Callable[[Event], None] | None = None
    ) -> None:
        self.case_id = case_id
        self.on_event = on_event
        self.events: list[Event] = []

    def add(self, fields: dict[str, Any]) -> None:
        # Seq is assigned here, on the one thread that reads the stream, so it
        # is strictly increasing even though the lawyers run in parallel.
        event = Event(case_id=self.case_id, seq=len(self.events) + 1, **fields)
        self.events.append(event)
        if self.on_event:
            self.on_event(event)


def events_path(run_path: Path) -> Path:
    """runs/case-001/X.json -> runs/case-001/X.events.jsonl"""
    return run_path.with_suffix(".events.jsonl")


def save_events(log: EventLog, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [event.model_dump_json() + "\n" for event in log.events]
    path.write_text("".join(lines), encoding="utf-8")
    return path


def load_events(path: Path) -> list[Event]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [Event.model_validate_json(line) for line in lines if line]


def _summary(event: Event) -> str:
    p = event.payload
    match event.type:
        case "state_change":
            return f"{p['from']} -> {p['to']}"
        case "agent_call_started" | "retry":
            return f"attempt {p['attempt']}"
        case "agent_call_finished":
            return (
                f"attempt {p['attempt']} in={p['input_tokens']} "
                f"out={p['output_tokens']} ${p['cost_usd']:.4f}"
            )
        case "check_failed" | "error":
            return p["error"]
        case "warning":
            return p["message"]


def format_event(event: Event) -> str:
    return (
        f"#{event.seq:<3} {event.ts:%H:%M:%S}  {event.stage:<8} "
        f"{event.agent or '-':<17} {event.type:<19} {_summary(event)}"
    )
