"""The v0 graph: two lawyers in parallel, then the judge."""

import operator
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, TypedDict

import anthropic
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ValidationError

from alteram.loader import load_prompt
from alteram.models import (
    AgentCall,
    Argument,
    Case,
    FailedRun,
    JudgeOrder,
    Run,
    Side,
    Verdict,
)
from alteram.pricing import (
    DEFAULT_RUN_BUDGET_USD,
    Budget,
    BudgetExceeded,
    cost_usd,
    worst_case_usd,
)
from alteram.validate import (
    CitationError,
    CoverageError,
    LabelError,
    assign_labels,
    check_argument_citations,
    check_reason_coverage,
    check_unsupported_labels,
    check_verdict_citations,
    set_side,
)

LAWYER_MODEL_ENV = "ALTERAM_LAWYER_MODEL"
JUDGE_MODEL_ENV = "ALTERAM_JUDGE_MODEL"
LAWYER_EFFORT = "high"
JUDGE_EFFORT = "high"
MAX_TOKENS = 32000
THINKING = {"type": "adaptive", "display": "summarized"}

# Input formatting, not prompts: the prompts themselves live in prompts/*.md.
HEADINGS = {
    "claimant": "# Claimant's argument",
    "respondent": "# Respondent's argument",
}
CASE_HEADING = "# Case"
RETRY_NOTE = "Your previous answer was rejected by an automatic check: "

CHECK_ERRORS = (ValidationError, CitationError, CoverageError, LabelError)

# (role, model_id, effort, schema) -> chat model. Tests pass fakes here.
ChatModelFactory = Callable[[str, str, str, type[BaseModel]], BaseChatModel]


class AgentError(RuntimeError):
    def __init__(self, message: str, role: str, call: AgentCall | None) -> None:
        super().__init__(message)
        self.role = role
        # What the failed agent cost, for the failed-run log; None if never called.
        self.call = call


class RunFailed(RuntimeError):
    def __init__(self, failed: FailedRun) -> None:
        super().__init__(failed.error)
        self.failed = failed


def anthropic_chat_model(
    role: str, model_id: str, effort: str, schema: type[BaseModel]
) -> BaseChatModel:
    # Structured output, not forced tool use: these models reject forced tool_choice.
    output_format = {
        "type": "json_schema",
        "schema": anthropic.transform_schema(schema),
    }
    return ChatAnthropic(
        model=model_id,
        max_tokens=MAX_TOKENS,
        thinking=THINKING,
        output_config={"effort": effort, "format": output_format},
    )


class State(TypedDict, total=False):
    case: Case
    judge_order: JudgeOrder
    claimant: Argument
    respondent: Argument
    verdict: Verdict
    # Both lawyers write here in the same step, so their entries are merged.
    calls: Annotated[dict[str, AgentCall], operator.or_]


def _thinking(reply: AIMessage) -> str:
    if isinstance(reply.content, str):
        return ""
    return "\n\n".join(
        block["thinking"]
        for block in reply.content
        if isinstance(block, dict) and block.get("type") == "thinking"
    )


def _require_complete(role: str, reply: AIMessage, call: AgentCall) -> None:
    """Refusals and truncated answers are hard failures, never retried."""
    if call.stop_reason == "refusal":
        details = reply.response_metadata.get("stop_details") or {}
        message = f"{role} refused (category: {details.get('category')})"
        raise AgentError(message, role, call)
    if call.stop_reason == "max_tokens":
        message = f"{role} hit max_tokens ({MAX_TOKENS}) before finishing"
        raise AgentError(message, role, call)


def _call_agent[T: BaseModel](
    role: str,
    env_var: str,
    effort: str,
    schema: type[T],
    text: str,
    check: Callable[[T], T],
    chat_model: ChatModelFactory,
    budget: Budget,
) -> tuple[T, AgentCall]:
    """Call one agent, parse and check its answer, and retry once on a failed check."""
    prompt = load_prompt(role)
    model_id = os.environ[env_var]
    model = chat_model(role, model_id, effort, schema)
    user_text = text
    input_tokens = output_tokens = 0
    cost = seconds = 0.0
    retry_error = ""
    call: AgentCall | None = None
    for attempt in (1, 2):
        chars = len(prompt.text) + len(user_text)
        worst = worst_case_usd(model_id, chars, MAX_TOKENS)
        try:
            budget.reserve(worst)
        except BudgetExceeded as e:
            raise AgentError(f"{role} not called: {e}", role, call) from e
        start = time.monotonic()
        try:
            reply = model.invoke([SystemMessage(prompt.text), HumanMessage(user_text)])
        except Exception:
            budget.settle(worst, 0.0)  # a request that failed is not billed
            raise
        seconds += time.monotonic() - start
        usage: Any = reply.usage_metadata or {}
        model_reported = reply.response_metadata.get("model_name", "")
        # An unknown model raises here, never costs $0; the run then fails.
        attempt_cost = cost_usd(
            model_reported, usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        )
        budget.settle(worst, attempt_cost)
        input_tokens += usage.get("input_tokens", 0)
        output_tokens += usage.get("output_tokens", 0)
        cost += attempt_cost
        call = AgentCall(
            model_configured=model_id,
            model_reported=model_reported,
            prompt_version=prompt.version,
            prompt_sha256=prompt.sha256,
            effort=effort,
            max_tokens=MAX_TOKENS,
            stop_reason=reply.response_metadata.get("stop_reason", ""),
            attempts=attempt,
            retry_error=retry_error,
            thinking=_thinking(reply),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            seconds=seconds,
        )
        _require_complete(role, reply, call)
        try:
            result = check(schema.model_validate_json(reply.text))
        except CHECK_ERRORS as e:
            if attempt == 2:
                raise AgentError(f"{role} failed checks twice: {e}", role, call) from e
            retry_error = str(e)
            user_text = f"{text}\n\n{RETRY_NOTE}{e}"
            continue
        return result, call
    raise AssertionError("unreachable")


def run_lawyer(
    case: Case, side: Side, chat_model: ChatModelFactory, budget: Budget
) -> tuple[Argument, AgentCall]:
    def check(argument: Argument) -> Argument:
        argument = assign_labels(set_side(argument, side))
        check_argument_citations(argument, case)
        return argument

    return _call_agent(
        side,
        LAWYER_MODEL_ENV,
        LAWYER_EFFORT,
        Argument,
        case.agent_text(),
        check,
        chat_model,
        budget,
    )


def _lawyer(
    side: Side, chat_model: ChatModelFactory, budget: Budget
) -> Callable[[State], dict]:
    def node(state: State) -> dict:
        argument, call = run_lawyer(state["case"], side, chat_model, budget)
        return {side: argument, "calls": {side: call}}

    return node


def judge_input(
    case: Case, claimant: Argument, respondent: Argument, order: str
) -> str:
    """The judge sees the case and the two arguments, never any thinking."""
    arguments = {"claimant": claimant, "respondent": respondent}
    sides = ["claimant", "respondent"]
    if order == "respondent_first":
        sides.reverse()
    parts = [f"{CASE_HEADING}\n\n{case.agent_text()}"] + [
        f"{HEADINGS[side]}\n\n{arguments[side].model_dump_json(indent=2)}"
        for side in sides
    ]
    return "\n\n".join(parts)


def run_judge(
    case: Case,
    claimant: Argument,
    respondent: Argument,
    judge_order: JudgeOrder,
    chat_model: ChatModelFactory,
    budget: Budget,
) -> tuple[Verdict, AgentCall]:
    """The judge alone, on arguments already written; the swap check reuses it."""

    def check(verdict: Verdict) -> Verdict:
        check_verdict_citations(verdict, case)
        check_reason_coverage(verdict, claimant, respondent)
        check_unsupported_labels(verdict, claimant, respondent)
        return verdict

    text = judge_input(case, claimant, respondent, judge_order)
    return _call_agent(
        "judge", JUDGE_MODEL_ENV, JUDGE_EFFORT, Verdict, text, check, chat_model, budget
    )


def _judge(chat_model: ChatModelFactory, budget: Budget) -> Callable[[State], dict]:
    def node(state: State) -> dict:
        verdict, call = run_judge(
            state["case"],
            state["claimant"],
            state["respondent"],
            state["judge_order"],
            chat_model,
            budget,
        )
        return {"verdict": verdict, "calls": {"judge": call}}

    return node


def build_graph(chat_model: ChatModelFactory, budget: Budget):
    graph = StateGraph(State)
    graph.add_node("claimant", _lawyer("claimant", chat_model, budget))
    graph.add_node("respondent", _lawyer("respondent", chat_model, budget))
    graph.add_node("judge", _judge(chat_model, budget))
    graph.add_edge(START, "claimant")
    graph.add_edge(START, "respondent")
    graph.add_edge(["claimant", "respondent"], "judge")  # runs once, after both
    graph.add_edge("judge", END)
    return graph.compile()


def run_case(
    case: Case,
    judge_order: JudgeOrder,
    chat_model: ChatModelFactory = anthropic_chat_model,
    budget: Budget | None = None,
) -> Run:
    """Run the graph on one case; on failure raise RunFailed with what completed."""
    budget = budget or Budget(DEFAULT_RUN_BUDGET_USD)
    started_at = datetime.now(UTC)
    inputs: State = {"case": case, "judge_order": judge_order}
    result = inputs
    try:
        # "values" yields the whole state after each step, so a failure keeps
        # the arguments of a step that finished.
        graph = build_graph(chat_model, budget)
        for state in graph.stream(inputs, stream_mode="values"):
            result = state
    except Exception as e:
        calls = dict(result.get("calls", {}))
        if isinstance(e, AgentError) and e.call:
            calls[e.role] = e.call
        raise RunFailed(
            FailedRun(
                command="run",
                case_id=case.id,
                case_sha256=case.sha256,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                error=f"{type(e).__name__}: {e}",
                cost_usd=budget.spent_usd,
                judge_order=judge_order,
                budget_stop=isinstance(e.__cause__, BudgetExceeded),
                claimant=result.get("claimant"),
                respondent=result.get("respondent"),
                calls=calls,
            )
        ) from e
    return Run(
        case_id=case.id,
        case_sha256=case.sha256,
        judge_order=judge_order,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        claimant=result["claimant"],
        respondent=result["respondent"],
        verdict=result["verdict"],
        calls=result["calls"],
    )
