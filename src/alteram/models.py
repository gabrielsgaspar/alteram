"""Typed inputs and outputs for every agent, plus the run log."""

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

Side = Literal["claimant", "respondent"]
Winner = Literal["claimant", "respondent", "undecidable"]
Kind = Literal["one-sided", "balanced", "missing-fact"]
JudgeOrder = Literal["claimant_first", "respondent_first"]


class Case(BaseModel):
    id: str
    title: str
    kind: Kind  # evaluation only; never shown to an agent
    expected: Winner  # evaluation only; never shown to an agent
    paragraphs: dict[int, str]
    sha256: str  # hash of the whole file, LF line endings

    @model_validator(mode="after")
    def _numbered_from_one(self) -> Self:
        numbers = list(self.paragraphs)
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError(f"paragraphs must be numbered 1..n in order: {numbers}")
        if any(not text.strip() for text in self.paragraphs.values()):
            raise ValueError("paragraph text must not be empty")
        return self

    def agent_text(self) -> str:
        """The case as agents see it: numbered paragraphs only, no frontmatter."""
        return "\n\n".join(f"[{n}] {text}" for n, text in self.paragraphs.items())


class Point(BaseModel):
    label: str = ""  # assigned by code, never trusted from the model
    claim: str
    reasoning: str
    citations: list[int] = Field(min_length=1)


class CounterPoint(BaseModel):
    point: str
    answer: str
    citations: list[int] = Field(min_length=1)


class Argument(BaseModel):
    side: Side
    points: list[Point] = Field(min_length=1)
    strongest_point_against: CounterPoint
    requested_outcome: str


class Reason(BaseModel):
    label: str
    finding: str
    citations: list[int]


class UnsupportedClaim(BaseModel):
    label: str
    description: str


class Verdict(BaseModel):
    winner: Winner
    reasons: list[Reason]
    unsupported_claims: list[UnsupportedClaim]
    missing_fact: str = ""
    what_would_change: str
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _missing_fact_only_if_undecidable(self) -> Self:
        if self.winner == "undecidable" and not self.missing_fact.strip():
            raise ValueError("missing_fact is required when winner is undecidable")
        if self.winner != "undecidable" and self.missing_fact:
            raise ValueError("missing_fact must be empty unless winner is undecidable")
        return self


class Prompt(BaseModel):
    name: str
    version: int
    text: str  # what the model sees: the file without its version line
    sha256: str  # hash of the whole file, LF line endings


class AgentCall(BaseModel):
    model_configured: str
    model_reported: str
    prompt_version: int
    prompt_sha256: str
    effort: str
    max_tokens: int
    stop_reason: str
    attempts: int  # 2 if the first answer failed a check and was retried
    retry_error: str = ""  # why the first attempt was rejected, if it was
    thinking: str = ""  # logged only; never passed to another agent
    input_tokens: int  # summed over attempts
    output_tokens: int  # summed over attempts


class Run(BaseModel):
    case_id: str
    case_sha256: str
    judge_order: JudgeOrder
    started_at: datetime
    finished_at: datetime
    claimant: Argument
    respondent: Argument
    verdict: Verdict
    calls: dict[str, AgentCall]  # keys: claimant, respondent, judge


class JudgeResult(BaseModel):
    judge_order: JudgeOrder
    verdict: Verdict
    call: AgentCall


class SwapSummary(BaseModel):
    winners: dict[JudgeOrder, list[Winner]]
    mean_confidence: dict[JudgeOrder, float]
    # Share of verdict pairs whose winners differ; None when there are no pairs.
    within_order_disagreement: float | None  # noise: same order, same arguments
    across_order_disagreement: float | None  # noise plus any order effect


class SwapRun(BaseModel):
    case_id: str
    case_sha256: str
    started_at: datetime
    finished_at: datetime
    claimant: Argument
    respondent: Argument
    calls: dict[str, AgentCall]  # keys: claimant, respondent
    judges: list[JudgeResult]
    summary: SwapSummary


class FailedRun(BaseModel):
    """Whatever completed before a run or swap failed, plus the error."""

    command: Literal["run", "swap"]
    case_id: str
    case_sha256: str
    started_at: datetime
    finished_at: datetime
    error: str
    claimant: Argument | None = None
    respondent: Argument | None = None
    calls: dict[str, AgentCall] = Field(default_factory=dict)  # incl. a failed call
    judges: list[JudgeResult] = Field(default_factory=list)  # swap only
