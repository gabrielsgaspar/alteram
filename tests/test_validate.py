import pytest
from conftest import make_argument

from alteram.models import Argument, Case, Reason, Verdict
from alteram.validate import (
    CitationError,
    CoverageError,
    assign_labels,
    check_argument_citations,
    check_reason_coverage,
    check_verdict_citations,
)


def verdict(*reasons: tuple[str, list[int]]) -> Verdict:
    return Verdict(
        winner="claimant",
        reasons=[Reason(label=lab, finding="f", citations=c) for lab, c in reasons],
        unsupported_claims=[],
        what_would_change="w",
        confidence=0.8,
    )


def test_assign_labels_ignores_model_labels() -> None:
    claimant = assign_labels(make_argument("claimant", [[1], [2]]))
    respondent = assign_labels(make_argument("respondent", [[3]]))
    assert [p.label for p in claimant.points] == ["C1", "C2"]
    assert [p.label for p in respondent.points] == ["R1"]


def test_argument_citations_pass(case: Case) -> None:
    check_argument_citations(assign_labels(make_argument("claimant", [[1, 3]])), case)


def test_argument_citation_missing_paragraph(case: Case) -> None:
    arg = assign_labels(make_argument("claimant", [[1], [2, 17]]))
    with pytest.raises(CitationError, match="C2 cites paragraph 17"):
        check_argument_citations(arg, case)


def test_strongest_point_against_citation_checked(case: Case) -> None:
    arg = make_argument("respondent", [[1]])
    arg.strongest_point_against.citations = [9]
    with pytest.raises(CitationError, match="paragraph 9"):
        check_argument_citations(arg, case)


def test_verdict_citations_pass(case: Case) -> None:
    check_verdict_citations(verdict(("C1", [1]), ("R1", [2, 3])), case)


def test_verdict_citation_missing_paragraph(case: Case) -> None:
    with pytest.raises(CitationError, match="R1 cites paragraph 0"):
        check_verdict_citations(verdict(("C1", [1]), ("R1", [0])), case)


@pytest.fixture
def sides() -> tuple[Argument, Argument]:
    return (
        assign_labels(make_argument("claimant", [[1], [2]])),
        assign_labels(make_argument("respondent", [[3]])),
    )


def test_coverage_pass(sides: tuple[Argument, Argument]) -> None:
    check_reason_coverage(verdict(("C1", [1]), ("C2", [2]), ("R1", [3])), *sides)


@pytest.mark.parametrize(
    ("labels", "message"),
    [
        (["C1", "R1"], r"missing \['C2'\]"),
        (["C1", "C2", "R1", "R2"], r"unknown \['R2'\]"),
        (["C1", "C1", "C2", "R1"], r"duplicated \['C1'\]"),
    ],
)
def test_coverage_fails(
    sides: tuple[Argument, Argument], labels: list[str], message: str
) -> None:
    with pytest.raises(CoverageError, match=message):
        check_reason_coverage(verdict(*[(lab, [1]) for lab in labels]), *sides)
