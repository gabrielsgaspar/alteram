from datetime import datetime

import pytest
from conftest import make_argument
from pydantic import ValidationError

from alteram.models import AgentCall, Point, Run, Verdict


def verdict(winner: str, missing_fact: str = "", confidence: float = 0.7) -> Verdict:
    return Verdict(
        winner=winner,
        reasons=[],
        unsupported_claims=[],
        missing_fact=missing_fact,
        what_would_change="w",
        confidence=confidence,
    )


def test_undecidable_with_missing_fact() -> None:
    assert verdict("undecidable", "the mileage").missing_fact == "the mileage"


def test_undecidable_needs_missing_fact() -> None:
    with pytest.raises(ValidationError, match="required"):
        verdict("undecidable", "  ")


@pytest.mark.parametrize("winner", ["claimant", "respondent"])
def test_missing_fact_empty_when_decided(winner: str) -> None:
    assert verdict(winner).missing_fact == ""
    with pytest.raises(ValidationError, match="must be empty"):
        verdict(winner, "something")


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_confidence_bounds(confidence: float) -> None:
    with pytest.raises(ValidationError):
        verdict("claimant", confidence=confidence)


def test_point_needs_a_citation() -> None:
    with pytest.raises(ValidationError):
        Point(claim="c", reasoning="r", citations=[])


def run(judge_order: str) -> Run:
    call = AgentCall(
        model_configured="m",
        model_reported="m",
        prompt_version=1,
        prompt_sha256="0" * 64,
        effort="high",
        max_tokens=32000,
        stop_reason="end_turn",
        attempts=1,
        input_tokens=1,
        output_tokens=1,
    )
    now = datetime.now()
    return Run(
        case_id="case-x",
        case_sha256="0" * 64,
        judge_order=judge_order,
        started_at=now,
        finished_at=now,
        claimant=make_argument("claimant", [[1]]),
        respondent=make_argument("respondent", [[1]]),
        verdict=verdict("claimant"),
        calls={"claimant": call, "respondent": call, "judge": call},
    )


@pytest.mark.parametrize("order", ["claimant_first", "respondent_first"])
def test_run_judge_order_valid(order: str) -> None:
    assert run(order).judge_order == order


def test_run_judge_order_invalid() -> None:
    with pytest.raises(ValidationError):
        run("random")
