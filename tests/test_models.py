import pytest
from pydantic import ValidationError

from alteram.models import Point, Verdict


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
