"""Graph tests with fake chat models only: no network, no API key."""

import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import Field

from alteram.graph import (
    JUDGE_MODEL_ENV,
    LAWYER_MODEL_ENV,
    MAX_TOKENS,
    RETRY_NOTE,
    THINKING,
    AgentError,
    anthropic_chat_model,
    run_case,
)
from alteram.loader import load_case
from alteram.models import Argument, Case

CASE_001 = Path(__file__).resolve().parents[1] / "cases" / "case-001.md"
MARKER = "PRIVATE-THINKING-7f3a"


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
) -> AIMessage:
    text = {"type": "text", "text": json.dumps(obj)}
    content: Any = [text]
    if thinking is not None:
        content = [{"type": "thinking", "thinking": thinking, "signature": "s"}, text]
    return AIMessage(
        content=content,
        response_metadata={
            "model_name": "fake-reported",
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
    monkeypatch.setenv(LAWYER_MODEL_ENV, "fake-lawyer")
    monkeypatch.setenv(JUDGE_MODEL_ENV, "fake-judge")


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
        expected_model = "fake-judge" if role == "judge" else "fake-lawyer"
        assert call.model_configured == expected_model
        assert call.model_reported == "fake-reported"
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
    retry_text = human_text(models["claimant"], call=1)
    assert RETRY_NOTE in retry_text and "paragraph 99" in retry_text


def test_bad_citation_twice_fails(case: Case) -> None:
    bad = reply(argument(citation=99))
    models = fakes(claimant=[bad, bad])
    with pytest.raises(AgentError, match="claimant failed checks twice"):
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
    with pytest.raises(AgentError, match=r"claimant refused \(category: bio\)"):
        run_case(case, "claimant_first", factory(models))
    assert len(models["claimant"].seen) == 1


def test_max_tokens_fails_without_retry(case: Case) -> None:
    cut = reply(argument(), stop_reason="max_tokens")
    models = fakes(judge=[cut, reply(VERDICT)])
    with pytest.raises(AgentError, match="judge hit max_tokens"):
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
