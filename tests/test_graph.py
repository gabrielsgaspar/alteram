"""Graph tests with fake chat models only: no network, no API key."""

import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import Field

from alteram.events import Event, EventLog
from alteram.graph import (
    JUDGE_MODEL_ENV,
    LAWYER_MODEL_ENV,
    MAX_TOKENS,
    RETRY_NOTE,
    THINKING,
    AgentError,
    RunFailed,
    anthropic_chat_model,
    judge_input,
    run_case,
    run_lawyer,
)
from alteram.loader import load_case, load_prompt
from alteram.models import Argument, Case, Run
from alteram.pricing import Budget, BudgetExceeded, UnknownModel, worst_case_usd

SIDES = ("claimant", "respondent")
CASE_001 = Path(__file__).resolve().parents[1] / "cases" / "case-001.md"
MARKER = "PRIVATE-THINKING-7f3a"
# Real IDs, because an unpriced model is an error; the fakes never call the API.
LAWYER_MODEL = "claude-sonnet-5-5"
JUDGE_MODEL = "claude-opus-5-5"


class RecordingFake(GenericFakeChatModel):
    """GenericFakeChatModel that keeps every list of messages it was sent."""

    seen: list[list[BaseMessage]] = Field(default_factory=list)

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        self.seen.append(messages)
        return super()._generate(messages, *args, **kwargs)


def reply(
    obj: dict,
    thinking: str | None = "some thinking",
    stop_reason: str = "end_turn",
    stop_details: dict | None = None,
    model: str = LAWYER_MODEL,
) -> AIMessage:
    text = {"type": "text", "text": json.dumps(obj)}
    content: Any = [text]
    if thinking is not None:
        content = [{"type": "thinking", "thinking": thinking, "signature": "s"}, text]
    return AIMessage(
        content=content,
        response_metadata={
            "model_name": model,
            "stop_reason": stop_reason,
            "stop_details": stop_details,
        },
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )


def argument(citation: int = 1) -> dict:
    return {
        "side": "claimant",  # code overrides this
        "points": [
            {"label": "", "claim": "c", "reasoning": "r", "citations": [citation]}
        ],
        "strongest_point_against": {"point": "p", "answer": "a", "citations": [2]},
        "requested_outcome": "win",
    }


VERDICT = {
    "winner": "claimant",
    "reasons": [
        {"label": "C1", "finding": "f", "citations": [1]},
        {"label": "R1", "finding": "f", "citations": [2]},
    ],
    "unsupported_claims": [],
    "missing_fact": "",
    "what_would_change": "w",
    "confidence": 0.7,
}


@pytest.fixture(autouse=True)
def model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LAWYER_MODEL_ENV, LAWYER_MODEL)
    monkeypatch.setenv(JUDGE_MODEL_ENV, JUDGE_MODEL)


def fakes(
    claimant: list[AIMessage] | None = None,
    respondent: list[AIMessage] | None = None,
    judge: list[AIMessage] | None = None,
) -> dict[str, RecordingFake]:
    replies = {
        "claimant": claimant or [reply(argument(), thinking=MARKER)],
        "respondent": respondent or [reply(argument(), thinking=MARKER)],
        "judge": judge or [reply(VERDICT)],
    }
    return {role: RecordingFake(messages=iter(r)) for role, r in replies.items()}


def factory(models: dict[str, RecordingFake]):
    return lambda role, model_id, effort, schema: models[role]


def human_text(fake: RecordingFake, call: int = 0) -> str:
    return next(m.text for m in fake.seen[call] if isinstance(m, HumanMessage))


@pytest.mark.parametrize("order", ["claimant_first", "respondent_first"])
def test_full_run(case: Case, order: str) -> None:
    run = run_case(case, order, factory(fakes()))
    assert run.judge_order == order
    assert run.case_id == case.id and run.case_sha256 == case.sha256
    assert run.claimant.side == "claimant" and run.claimant.points[0].label == "C1"
    assert run.respondent.side == "respondent"
    assert run.respondent.points[0].label == "R1"
    assert run.verdict.winner == "claimant"
    assert set(run.calls) == {"claimant", "respondent", "judge"}
    for role, call in run.calls.items():
        expected_model = JUDGE_MODEL if role == "judge" else LAWYER_MODEL
        assert call.model_configured == expected_model
        assert call.model_reported == LAWYER_MODEL
        assert (call.effort, call.max_tokens) == ("high", MAX_TOKENS)
        assert (call.stop_reason, call.attempts) == ("end_turn", 1)
        assert (call.input_tokens, call.output_tokens) == (10, 5)
        assert call.prompt_version >= 1


def test_lawyer_thinking_never_reaches_judge(case: Case) -> None:
    models = fakes()
    run = run_case(case, "claimant_first", factory(models))
    assert run.calls["claimant"].thinking == MARKER
    assert run.calls["respondent"].thinking == MARKER
    for messages in models["judge"].seen:
        for message in messages:
            assert MARKER not in message.text


def test_evaluation_metadata_never_reaches_a_model() -> None:
    case = load_case(CASE_001)
    models = fakes()
    run_case(case, "claimant_first", factory(models))
    for fake in models.values():
        for messages in fake.seen:
            for message in messages:
                assert "kind:" not in message.text
                assert "expected:" not in message.text
                assert f": {case.expected}" not in message.text
                # "balanced" etc. can be ordinary words in a prompt; not in input.
                if isinstance(message, HumanMessage):
                    assert case.kind not in message.text


def test_bad_citation_is_retried_once(case: Case) -> None:
    models = fakes(claimant=[reply(argument(citation=99)), reply(argument())])
    run = run_case(case, "claimant_first", factory(models))
    assert run.calls["claimant"].attempts == 2
    assert run.calls["claimant"].input_tokens == 20
    assert "paragraph 99" in run.calls["claimant"].retry_error
    assert run.calls["respondent"].retry_error == ""
    retry_text = human_text(models["claimant"], call=1)
    assert RETRY_NOTE in retry_text and "paragraph 99" in retry_text


def test_bad_citation_twice_fails(case: Case) -> None:
    bad = reply(argument(citation=99))
    models = fakes(claimant=[bad, bad])
    with pytest.raises(RunFailed, match="claimant failed checks twice"):
        run_case(case, "claimant_first", factory(models))
    assert len(models["claimant"].seen) == 2
    assert models["judge"].seen == []


@pytest.mark.parametrize(
    ("order", "first", "second"),
    [
        ("claimant_first", "Claimant's argument", "Respondent's argument"),
        ("respondent_first", "Respondent's argument", "Claimant's argument"),
    ],
)
def test_judge_sees_arguments_in_judge_order(
    case: Case, order: str, first: str, second: str
) -> None:
    models = fakes()
    run_case(case, order, factory(models))
    text = human_text(models["judge"])
    assert text.startswith("# Case\n\n[1] ")
    assert text.index(first) < text.index(second)
    first_side = first.split("'")[0].lower()
    after_first = text[text.index(first) :]
    assert (
        Argument.model_validate_json(
            after_first.split("\n\n", 1)[1].split("\n\n#")[0]
        ).side
        == first_side
    )


def test_refusal_fails_without_retry(case: Case) -> None:
    refused = reply(argument(), stop_reason="refusal", stop_details={"category": "bio"})
    models = fakes(claimant=[refused, reply(argument())])
    with pytest.raises(RunFailed, match=r"claimant refused \(category: bio\)"):
        run_case(case, "claimant_first", factory(models))
    assert len(models["claimant"].seen) == 1


def test_max_tokens_fails_without_retry(case: Case) -> None:
    cut = reply(argument(), stop_reason="max_tokens")
    models = fakes(judge=[cut, reply(VERDICT)])
    with pytest.raises(RunFailed, match="judge hit max_tokens"):
        run_case(case, "claimant_first", factory(models))
    assert len(models["judge"].seen) == 1


def test_reply_without_thinking_logs_empty_string(case: Case) -> None:
    models = fakes(judge=[reply(VERDICT, thinking=None)])
    run = run_case(case, "claimant_first", factory(models))
    assert run.calls["judge"].thinking == ""


def test_anthropic_chat_model_settings() -> None:
    model = anthropic_chat_model("judge", "claude-test", "high", Argument)
    assert model.model == "claude-test"
    assert model.max_tokens == MAX_TOKENS
    assert model.thinking == THINKING
    assert model.temperature is None
    assert model.output_config["effort"] == "high"
    assert model.output_config["format"]["type"] == "json_schema"
    schema = model.output_config["format"]["schema"]
    assert schema["additionalProperties"] is False


def test_every_call_logs_its_cost(case: Case) -> None:
    models = fakes(claimant=[reply(argument(citation=99)), reply(argument())])
    run = run_case(case, "claimant_first", factory(models))
    # Each fake reply reports 10 tokens in and 5 out at Sonnet's $2 / $10.
    one_reply = (10 * 2 + 5 * 10) / 1_000_000
    assert run.calls["claimant"].cost_usd == pytest.approx(2 * one_reply)  # retried
    assert run.calls["respondent"].cost_usd == pytest.approx(one_reply)
    assert run.calls["judge"].cost_usd == pytest.approx(one_reply)


def test_dated_reported_model_priced_as_configured_and_warns(case: Case) -> None:
    dated = f"{LAWYER_MODEL}-20261001"
    models = fakes(claimant=[reply(argument(), model=dated)])
    log = EventLog(case.id)
    run = run_case(case, "claimant_first", factory(models), events=log)
    claimant = run.calls["claimant"]
    assert (claimant.model_reported, claimant.priced_as) == (dated, LAWYER_MODEL)
    assert claimant.cost_usd == pytest.approx((10 * 2 + 5 * 10) / 1_000_000)
    for role in ("respondent", "judge"):
        assert run.calls[role].priced_as == run.calls[role].model_reported
    assert kinds(log.events, "claimant_lawyer") == [
        "agent_call_started",
        "agent_call_finished",
        "warning",
    ]
    [warning] = [e for e in log.events if e.type == "warning"]
    assert warning.payload["model_reported"] == dated
    assert warning.payload["priced_as"] == LAWYER_MODEL
    assert dated in warning.payload["message"]


def test_both_models_unknown_fails_before_any_call(
    case: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(LAWYER_MODEL_ENV, "claude-unpriced")
    unpriced = reply(argument(), model="claude-unpriced-20261001")
    models = fakes(claimant=[unpriced], respondent=[unpriced])
    with pytest.raises(RunFailed, match="claude-unpriced") as info:
        run_case(case, "claimant_first", factory(models))
    assert isinstance(info.value.__cause__, UnknownModel)
    assert models["claimant"].seen == [] and models["respondent"].seen == []


def lawyer_worst_case(case: Case, side: str) -> float:
    chars = len(load_prompt(side).text) + len(case.agent_text())
    return worst_case_usd(LAWYER_MODEL, chars, MAX_TOKENS)


def judge_worst_case(case: Case, run: Run) -> float:
    text = judge_input(case, run.claimant, run.respondent, run.judge_order)
    chars = len(load_prompt("judge").text) + len(text)
    return worst_case_usd(JUDGE_MODEL, chars, MAX_TOKENS)


def test_budget_stops_before_the_call_that_could_exceed_it(case: Case) -> None:
    # A run with no real limit gives the lawyers' cost and the judge's input.
    ok = run_case(case, "claimant_first", factory(fakes()))
    lawyers_cost = sum(ok.calls[side].cost_usd or 0 for side in SIDES)
    limit = lawyers_cost + judge_worst_case(case, ok) - 1e-9  # judge just won't fit
    # Both lawyers' worst cases fit at once, since they run in parallel.
    assert sum(lawyer_worst_case(case, side) for side in SIDES) <= limit

    models = fakes()
    with pytest.raises(RunFailed) as info:
        run_case(case, "claimant_first", factory(models), Budget(limit))
    assert models["judge"].seen == []  # stopped before the call, not after
    assert isinstance(info.value.__cause__, AgentError)
    assert isinstance(info.value.__cause__.__cause__, BudgetExceeded)
    failed = info.value.failed
    assert "judge not called: budget" in failed.error
    assert set(failed.calls) == {"claimant", "respondent"}
    assert failed.cost_usd == pytest.approx(lawyers_cost)  # spent so far

    models = fakes()
    run_case(case, "claimant_first", factory(models), Budget(limit + 2e-9))
    assert len(models["judge"].seen) == 1  # with the worst case covered, it runs


def test_budget_stop_on_retry_logs_the_first_attempt(case: Case) -> None:
    models = fakes(claimant=[reply(argument(citation=99)), reply(argument())])
    # Room for the first attempt only: the retry's worst case is larger still.
    budget = Budget(lawyer_worst_case(case, "claimant"))
    with pytest.raises(AgentError, match="claimant not called: budget") as info:
        run_lawyer(case, "claimant", factory(models), budget, EventLog(case.id).add)
    assert len(models["claimant"].seen) == 1
    call = info.value.call
    assert call is not None and call.attempts == 1 and call.cost_usd
    assert budget.spent_usd == pytest.approx(call.cost_usd)


# --- events -----------------------------------------------------------------


def run_events(case: Case, models: dict[str, RecordingFake]) -> list[Event]:
    log = EventLog(case.id)
    try:
        run_case(case, "claimant_first", factory(models), events=log)
    except RunFailed:
        pass
    return log.events


def kinds(events: list[Event], agent: str | None) -> list[str]:
    return [e.type for e in events if e.agent == agent]


def test_event_order_for_a_full_run(case: Case) -> None:
    events = run_events(case, fakes())
    changes = [(e.payload["from"], e.payload["to"]) for e in events if e.agent is None]
    assert changes == [
        (None, "arguing"),
        ("arguing", "deciding"),
        ("deciding", "decided"),
    ]
    assert events[0].type == "state_change" and events[-1].payload["to"] == "decided"
    for side in SIDES:
        agent = f"{side}_lawyer"
        assert kinds(events, agent) == ["agent_call_started", "agent_call_finished"]
        assert {(e.stage, e.side) for e in events if e.agent == agent} == {
            ("arguing", side)
        }
    # Judge events sit between "deciding" and "decided", after every lawyer event.
    deciding = next(
        i for i, e in enumerate(events) if e.payload.get("to") == "deciding"
    )
    lawyer = [i for i, e in enumerate(events) if e.agent and e.agent != "judge"]
    judge = [i for i, e in enumerate(events) if e.agent == "judge"]
    assert max(lawyer) < deciding < min(judge) and max(judge) == len(events) - 2
    assert kinds(events, "judge") == ["agent_call_started", "agent_call_finished"]
    assert {(e.stage, e.side) for e in events if e.agent == "judge"} == {
        ("deciding", None)
    }
    assert {e.case_id for e in events} == {case.id}
    finished = next(e for e in events if e.type == "agent_call_finished")
    assert (finished.payload["input_tokens"], finished.payload["output_tokens"]) == (
        10,
        5,
    )
    assert finished.payload["cost_usd"] == pytest.approx((10 * 2 + 5 * 10) / 1e6)


@pytest.mark.parametrize(
    "models",
    [
        lambda: fakes(),
        lambda: fakes(claimant=[reply(argument(citation=99)), reply(argument())]),
        lambda: fakes(judge=[reply(VERDICT, stop_reason="max_tokens")]),
    ],
    ids=["ok", "retry", "failed"],
)
def test_seq_is_strictly_increasing(case: Case, models: Any) -> None:
    events = run_events(case, models())
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert len(events) >= 5  # not vacuous: run, both lawyers and judge


def test_retry_emits_check_failed_then_retry(case: Case) -> None:
    models = fakes(claimant=[reply(argument(citation=99)), reply(argument())])
    events = run_events(case, models)
    assert kinds(events, "claimant_lawyer") == [
        "agent_call_started",
        "agent_call_finished",
        "check_failed",
        "retry",
        "agent_call_started",
        "agent_call_finished",
    ]
    claimant = [e for e in events if e.agent == "claimant_lawyer"]
    assert "paragraph 99" in claimant[2].payload["error"]
    assert claimant[3].payload == {"attempt": 2}
    assert claimant[4].payload["attempt"] == 2
    assert RETRY_NOTE in claimant[4].payload["input"]


def test_judge_call_started_payload_has_no_lawyer_thinking(case: Case) -> None:
    events = run_events(case, fakes())  # both lawyers think MARKER
    [started] = [
        e for e in events if e.agent == "judge" and e.type == "agent_call_started"
    ]
    # Not vacuous: the payload carries the judge's whole input, arguments included.
    assert "Claimant's argument" in started.payload["input"]
    assert "Respondent's argument" in started.payload["input"]
    assert MARKER not in json.dumps(started.payload)
    assert all(MARKER not in e.model_dump_json() for e in events)


def test_failed_check_twice_ends_with_error_event(case: Case) -> None:
    bad = reply(argument(citation=99))
    events = run_events(case, fakes(claimant=[bad, bad]))
    assert kinds(events, "claimant_lawyer")[-2:] == ["check_failed", "error"]
    error = [e for e in events if e.type == "error"][-1]
    assert "failed checks twice" in error.payload["error"]
    assert error.payload["budget_stop"] is False
    assert not any(e.payload.get("to") == "decided" for e in events)


def test_budget_stop_emits_error_event(case: Case) -> None:
    budget = Budget(lawyer_worst_case(case, "claimant"))  # first attempt only
    models = fakes(claimant=[reply(argument(citation=99)), reply(argument())])
    log = EventLog(case.id)
    with pytest.raises(AgentError):
        run_lawyer(case, "claimant", factory(models), budget, log.add)
    assert [e.type for e in log.events][-3:] == ["check_failed", "retry", "error"]
    assert log.events[-1].payload["budget_stop"] is True
