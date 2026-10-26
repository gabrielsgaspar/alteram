import pytest
from conftest import make_argument

from alteram.models import Argument, Case, Reason, UnsupportedClaim, Verdict
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


def verdict(*reasons: tuple[str, list[int]], unsupported: list[str] = ()) -> Verdict:
    return Verdict(
        winner="claimant",
        reasons=[Reason(label=lab, finding="f", citations=c) for lab, c in reasons],
        unsupported_claims=[
            UnsupportedClaim(label=lab, description="d") for lab in unsupported
        ],
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


def unlabelled(side: str) -> Argument:
    arg = make_argument(side, [[1]])
    points = [p.model_copy(update={"label": ""}) for p in arg.points]
    return arg.model_copy(update={"points": points})


def test_set_side_overrides_model() -> None:
    arg = set_side(make_argument("claimant", [[1]]), "respondent")
    assert arg.side == "respondent"
    assert [p.label for p in assign_labels(arg).points] == ["R1"]


def test_citation_check_refuses_unlabelled(case: Case) -> None:
    with pytest.raises(LabelError, match="claimant argument has unlabelled"):
        check_argument_citations(unlabelled("claimant"), case)


def test_coverage_refuses_unlabelled(sides: tuple[Argument, Argument]) -> None:
    with pytest.raises(LabelError, match="respondent"):
        check_reason_coverage(verdict(("C1", [1])), sides[0], unlabelled("respondent"))


@pytest.mark.parametrize("labels", [[], ["C2"], ["C1", "R1"]])
def test_unsupported_labels_pass(
    sides: tuple[Argument, Argument], labels: list[str]
) -> None:
    check_unsupported_labels(verdict(unsupported=labels), *sides)


def test_unsupported_label_unknown(sides: tuple[Argument, Argument]) -> None:
    with pytest.raises(LabelError, match=r"\['C9'\]"):
        check_unsupported_labels(verdict(unsupported=["C1", "C9"]), *sides)


def test_unsupported_refuses_unlabelled(sides: tuple[Argument, Argument]) -> None:
    with pytest.raises(LabelError, match="unlabelled"):
        check_unsupported_labels(verdict(), unlabelled("claimant"), sides[1])
