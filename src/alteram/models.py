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
    # Summed over attempts, priced from model_reported (see pricing.py).
    # None only in files written before costs were logged.
    cost_usd: float | None = None
    # Wall time of the model calls, summed over attempts; None in older files.
    seconds: float | None = None


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

    command: Literal["run", "swap", "rejudge"]
    case_id: str
    case_sha256: str
    started_at: datetime
    finished_at: datetime
    error: str
    cost_usd: float = 0  # everything spent before the failure, from the budget
    judge_order: JudgeOrder | None = None  # run only
    budget_stop: bool = False  # run only: refused by the budget, not a bad answer
    claimant: Argument | None = None
    respondent: Argument | None = None
    calls: dict[str, AgentCall] = Field(default_factory=dict)  # incl. a failed call
    judges: list[JudgeResult] = Field(default_factory=list)  # swap and rejudge


class PromptRef(BaseModel):
    version: int
    sha256: str


class RejudgeStats(BaseModel):
    """One set of judge results, summarized; orders with no result are left out."""

    winners: dict[JudgeOrder, list[Winner]]
    mean_confidence: dict[JudgeOrder, float]
    within_order_disagreement: float | None
    across_order_disagreement: float | None
    retry_rate: float  # share of judge calls whose first answer failed a check


class RejudgeSummary(BaseModel):
    source: RejudgeStats
    new: RejudgeStats


class RejudgeRun(BaseModel):
    """The current judge prompt run again on the arguments of an earlier file."""

    case_id: str
    case_sha256: str  # the case file as it was when re-judging
    source_path: str
    source_sha256: str  # hash of the source file's bytes
    source_case_sha256: str
    source_judge_prompts: list[PromptRef]
    current_judge_prompt: PromptRef
    started_at: datetime
    finished_at: datetime
    claimant: Argument
    respondent: Argument
    source_judges: list[JudgeResult]
    judges: list[JudgeResult]
    summary: RejudgeSummary


class Interval(BaseModel):
    """A point value and its 95% bootstrap interval over cases."""

    value: float
    low: float
    high: float


class ConfidenceStats(BaseModel):
    mean: float
    sd: float | None  # sample SD; None with fewer than two verdicts
    min: float
    max: float


class EvalFailure(BaseModel):
    file: str
    judge_order: JudgeOrder | None
    budget_stop: bool
    error: str


class CaseStats(BaseModel):
    case_id: str
    case_sha256: str
    kind: Kind
    expected: Winner
    runs: int
    completed: int
    failed: int
    budget_stops: int
    winners: dict[Winner, int]
    winners_by_order: dict[JudgeOrder, list[Winner]]
    agreement: float | None  # share of completed runs whose winner is `expected`
    confidence: ConfidenceStats | None
    cost_usd: float  # completed and failed runs
    mean_seconds: dict[str, float]  # per agent, over calls that logged a time
    retry_rate: dict[str, float]  # per agent: share of calls with a second attempt
    failures: list[EvalFailure]


class OverallStats(BaseModel):
    cases: int
    runs: int
    completed: int
    failed: int
    budget_stops: int
    cases_without_result: int  # no completed run, so left out of accuracy
    accuracy: Interval | None  # mean over cases of per-case agreement
    mean_confidence: Interval | None  # mean over cases of per-case mean confidence
    cost_usd: float
    cost_per_run_usd: float | None
    retry_rate: dict[str, float]  # pooled over every call
    mean_seconds: dict[str, float]  # pooled over every call


class EvalSummary(BaseModel):
    """summary.json of one `alteram eval`; baselines are copies of it."""

    format: Literal[1] = 1
    created_at: datetime
    n: int
    seed: int
    cases_dir: str
    models: dict[str, str]  # lawyer, judge: model IDs configured
    prompts: dict[str, PromptRef]  # claimant, respondent, judge
    run_budget_usd: float
    warnings: list[str]
    overall: OverallStats
    cases: list[CaseStats]
