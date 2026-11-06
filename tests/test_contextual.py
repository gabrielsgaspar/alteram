import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from pydantic import Field

from alteram.law.contextual import (
    HeaderCheckFailed,
    HeaderWriter,
    contextual_text,
    document_context,
)
from alteram.law.models import LawChunk, chunk_sha256, library_id
from alteram.pricing import Budget, BudgetExceeded

MODEL = "claude-haiku-5-5"
PATH = "ukpga/2015/15/section/9/1"
START = date(2015, 10, 1)
GOOD = "From the Consumer Rights Act 2015, section 9, on the quality of goods."
LONG_TEXT = (
    "Goods supplied under a contract must be of satisfactory quality always. " * 3
)


class RecordingFake(GenericFakeChatModel):
    seen: list[list[BaseMessage]] = Field(default_factory=list)

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        self.seen.append(messages)
        return super()._generate(messages, *args, **kwargs)


def make_chunk(
    text: str = "Goods must be of satisfactory quality.",
    path: str = PATH,
    start: date = START,
    end: date | None = None,
) -> LawChunk:
    heading = ["Consumer Rights Act 2015", "Section 9"]
    return LawChunk(
        id=library_id(path, start),
        source="cra-2015",
        source_url="https://example.test/cra",
        doc_type="statute",
        authority_tier="statute",
        jurisdiction="uk",
        extent=None,
        heading_path=heading,
        in_force_from=start,
        in_force_to=end,
        text_original=text,
        text_contextual=None,
        licence="OGL v3.0",
        attribution="x",
        source_sha256="0" * 64,
        chunk_sha256=chunk_sha256(heading, text),
    )


def fake(*headers: str) -> RecordingFake:
    msgs = [
        AIMessage(
            content=json.dumps({"header": h}),
            response_metadata={"model_name": MODEL},
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )
        for h in headers
    ]
    return RecordingFake(messages=iter(msgs))


def writer(
    model: RecordingFake,
    tmp_path: Path,
    model_id: str = MODEL,
    budget: Budget | None = None,
    **kw: Any,
) -> HeaderWriter:
    return HeaderWriter(
        model, model_id, tmp_path / "h.jsonl", budget or Budget(5.0), **kw
    )


def retry_text(model: RecordingFake) -> str:
    return str(model.seen[1][1].content)


def test_cache_hit_makes_no_second_call(tmp_path: Path) -> None:
    model = fake(GOOD)
    w = writer(model, tmp_path)
    chunk = make_chunk()
    first = w.write(chunk, "doc")
    assert w.write(chunk, "doc") == first == GOOD
    assert len(model.seen) == 1
    # A new writer reads the file and also makes no call.
    again = fake()
    assert writer(again, tmp_path).write(chunk, "doc") == GOOD
    assert again.seen == []


def test_document_block_is_marked_for_caching(tmp_path: Path) -> None:
    model = fake(GOOD)
    writer(model, tmp_path).write(make_chunk(), "doc")
    blocks = model.seen[0][1].content
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "<document>" in blocks[0]["text"]
    assert "<chunk>" in blocks[1]["text"]


def test_miss_when_model_id_changes(tmp_path: Path) -> None:
    chunk = make_chunk()
    writer(fake(GOOD), tmp_path).write(chunk, "doc")
    model = fake(GOOD)
    writer(model, tmp_path, model_id="claude-sonnet-5-5").write(chunk, "doc")
    assert len(model.seen) == 1


def test_miss_when_document_changes(tmp_path: Path) -> None:
    chunk = make_chunk()
    writer(fake(GOOD), tmp_path).write(chunk, "doc")
    model = fake(GOOD)
    writer(model, tmp_path).write(chunk, "other doc")
    assert len(model.seen) == 1


def test_miss_when_chunk_changes(tmp_path: Path) -> None:
    writer(fake(GOOD), tmp_path).write(make_chunk(), "doc")
    model = fake(GOOD)
    writer(model, tmp_path).write(make_chunk("Different text."), "doc")
    assert len(model.seen) == 1


def test_miss_when_prompt_version_changes(tmp_path: Path) -> None:
    chunk = make_chunk()
    writer(fake(GOOD), tmp_path).write(chunk, "doc")
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "contextual_header.md").write_text("version: 99\n\nWrite a header.\n")
    model = fake(GOOD)
    writer(model, tmp_path, prompts_dir=prompts).write(chunk, "doc")
    assert len(model.seen) == 1
    rows = [json.loads(x) for x in (tmp_path / "h.jsonl").read_text().splitlines()]
    assert len(rows) == 2
    assert rows[-1]["prompt_version"] == 99


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        ("  ", "empty"),
        ("x" * 601, "601 characters"),
        (LONG_TEXT[:80] + " plus", "copied"),
    ],
)
def test_bad_header_retried_once_then_fails(
    tmp_path: Path, bad: str, reason: str
) -> None:
    model = fake(bad, bad)
    with pytest.raises(HeaderCheckFailed):
        writer(model, tmp_path).write(make_chunk(LONG_TEXT), "doc")
    assert len(model.seen) == 2
    assert reason in retry_text(model)
    assert not (tmp_path / "h.jsonl").exists()


def test_retry_can_succeed(tmp_path: Path) -> None:
    model = fake("", GOOD)
    assert writer(model, tmp_path).write(make_chunk(), "doc") == GOOD
    assert len(model.seen) == 2


def test_plain_text_reply_is_the_header(tmp_path: Path) -> None:
    model = RecordingFake(messages=iter([AIMessage(content=GOOD)]))
    assert writer(model, tmp_path).write(make_chunk(), "doc") == GOOD


def test_tiny_budget_raises_before_any_call(tmp_path: Path) -> None:
    model = fake(GOOD)
    with pytest.raises(BudgetExceeded):
        writer(model, tmp_path, budget=Budget(0.000001)).write(make_chunk(), "doc")
    assert model.seen == []


def test_budget_is_settled_to_actual_cost(tmp_path: Path) -> None:
    budget = Budget(5.0)
    writer(fake(GOOD), tmp_path, budget=budget).write(make_chunk(), "doc")
    assert 0 < budget.spent_usd < 0.001
    assert budget._reserved_usd == pytest.approx(0.0)


def test_document_context_over_limit_raises() -> None:
    with pytest.raises(ValueError, match="over the limit"):
        document_context([make_chunk()], START, limit_chars=10)


def test_document_context_filters_by_span_and_sorts() -> None:
    old = make_chunk("Old wording.", end=date(2020, 1, 1))
    new = make_chunk("New wording.", start=date(2020, 1, 1))
    other = make_chunk("Earlier section.", path="ukpga/2015/15/section/8/1")
    text = document_context([new, old, other], date(2015, 12, 1))
    assert "Old wording." in text
    assert "New wording." not in text
    assert text.index("Earlier section.") < text.index("Old wording.")
    assert "Consumer Rights Act 2015 > Section 9" in text
    later = document_context([new, old], date(2021, 1, 1))
    assert "New wording." in later
    assert "Old wording." not in later


def test_contextual_text_format() -> None:
    assert contextual_text("H", "O") == "H\n\nO"
