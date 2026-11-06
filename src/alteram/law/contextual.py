"""Contextual headers for law chunks (design 6.3, docs/milestones/M3.md 6.5).

One model call per new chunk writes a short header that is added to the chunk
before it is indexed. Results are cached in a JSONL file so reruns are free,
and every call is costed through `pricing.py` against a `Budget`.
"""

import hashlib
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from alteram.law.models import LawChunk, in_force_on
from alteram.loader import PROMPTS_DIR, load_prompt
from alteram.models import ContextualHeader, Prompt
from alteram.pricing import (
    Budget,
    cost_usd,
    priced_model,
    worst_case_usd,
)

PROMPT_NAME = "contextual_header"
MAX_TOKENS = 400  # a 600-character header needs far fewer
MAX_HEADER_CHARS = 600
COPY_RUN_CHARS = 80
_SEP = "\x1f"


class HeaderCheckFailed(RuntimeError):
    """The model's header failed a code check twice."""


def document_context(
    chunks: Sequence[LawChunk], as_of: date, limit_chars: int = 180_000
) -> str:
    """The chunks in force on `as_of`, in ID order, each under its heading path."""
    live = sorted((c for c in chunks if in_force_on(c, as_of)), key=lambda c: c.id)
    text = "\n\n".join(
        " > ".join(c.heading_path) + "\n" + c.text_original for c in live
    )
    if len(text) > limit_chars:
        raise ValueError(
            f"document context is {len(text)} characters, over the limit {limit_chars}"
        )
    return text


def contextual_text(header: str, original: str) -> str:
    return f"{header}\n\n{original}"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _copies_chunk(header: str, original: str) -> bool:
    n = COPY_RUN_CHARS
    return any(original[i : i + n] in header for i in range(len(original) - n + 1))


def _check(header: str, chunk: LawChunk) -> str | None:
    """The name of the failed check, or None if the header passes."""
    if not header.strip():
        return "the header was empty"
    if len(header) > MAX_HEADER_CHARS:
        return (
            f"the header was {len(header)} characters; the limit is {MAX_HEADER_CHARS}"
        )
    if _copies_chunk(header, chunk.text_original):
        return f"the header copied a run of {COPY_RUN_CHARS} characters from the chunk"
    return None


def _reply_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "".join(
        b.get("text", "") if isinstance(b, dict) else str(b) for b in content
    )


def _parse_header(content: Any) -> str:
    """`ContextualHeader` from a JSON reply; plain text stands for the header."""
    text = _reply_text(content).strip()
    try:
        return ContextualHeader.model_validate(json.loads(text)).header
    except (ValueError, ValidationError):
        return text


class HeaderWriter:
    def __init__(
        self,
        model: BaseChatModel,
        model_id: str,
        cache_path: Path,
        budget: Budget,
        prompts_dir: Path = PROMPTS_DIR,
    ) -> None:
        self.model = model
        self.model_id = model_id
        self.cache_path = cache_path
        self.budget = budget
        self.prompt: Prompt = load_prompt(PROMPT_NAME, prompts_dir)
        self._cache: dict[str, str] = {}
        if cache_path.exists():
            for line in cache_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self._cache[row["key"]] = row["header"]

    def key(self, chunk: LawChunk, document: str) -> str:
        parts = [
            self.model_id,
            self.prompt.sha256,
            _sha256(document),
            chunk.chunk_sha256,
        ]
        return _sha256(_SEP.join(parts))

    def write(self, chunk: LawChunk, document: str) -> str:
        key = self.key(chunk, document)
        if key in self._cache:
            return self._cache[key]
        header = self._write_checked(chunk, document)
        self._append(key, header)
        return header

    def _messages(
        self, chunk: LawChunk, document: str, failure: str | None
    ) -> list[Any]:
        blocks: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": f"<document>\n{document}\n</document>",
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": (
                    f"<heading_path>\n{' > '.join(chunk.heading_path)}\n"
                    f"</heading_path>\n<chunk>\n{chunk.text_original}\n</chunk>"
                ),
            },
        ]
        if failure:
            blocks.append(
                {
                    "type": "text",
                    "text": f"Your last header was rejected: {failure}. "
                    "Write it again so that it passes.",
                }
            )
        return [SystemMessage(self.prompt.text), HumanMessage(content=blocks)]

    def _call(self, messages: list[Any], prompt_chars: int) -> str:
        worst = worst_case_usd(self.model_id, prompt_chars, MAX_TOKENS)
        self.budget.reserve(worst)  # raises BudgetExceeded before any call
        try:
            reply = self.model.invoke(messages)
        except Exception:
            self.budget.settle(worst, 0.0)  # a request that failed is not billed
            raise
        usage: Any = reply.usage_metadata or {}
        priced_as = priced_model(
            reply.response_metadata.get("model_name", ""), self.model_id
        )
        actual = cost_usd(
            priced_as, usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        )
        self.budget.settle(worst, actual)
        return _parse_header(reply.content)

    def _write_checked(self, chunk: LawChunk, document: str) -> str:
        prompt_chars = len(self.prompt.text) + len(document) + len(chunk.text_original)
        failure: str | None = None
        for _ in (1, 2):
            messages = self._messages(chunk, document, failure)
            header = self._call(messages, prompt_chars + 500)
            failure = _check(header, chunk)
            if failure is None:
                return header
        raise HeaderCheckFailed(f"{chunk.id}: {failure}")

    def _append(self, key: str, header: str) -> None:
        row = {
            "key": key,
            "model_id": self.model_id,
            "prompt_version": self.prompt.version,
            "header": header,
        }
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with self.cache_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        self._cache[key] = header
