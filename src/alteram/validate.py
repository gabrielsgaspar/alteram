"""Checks done in code, so no model is asked to check them."""

from collections import Counter

from alteram.models import Argument, Case, Side, Verdict


class CitationError(ValueError):
    pass


class CoverageError(ValueError):
    pass


class LabelError(ValueError):
    pass


def set_side(argument: Argument, side: Side) -> Argument:
    """Set side from the lawyer that produced it. Run before assign_labels."""
    return argument.model_copy(update={"side": side})


def assign_labels(argument: Argument) -> Argument:
    """Label points C1, C2… or R1, R2…, ignoring any labels from the model."""
    prefix = "C" if argument.side == "claimant" else "R"
    points = [
        p.model_copy(update={"label": f"{prefix}{i}"})
        for i, p in enumerate(argument.points, start=1)
    ]
    return argument.model_copy(update={"points": points})


def _require_labels(*arguments: Argument) -> None:
    for argument in arguments:
        if any(not p.label for p in argument.points):
            raise LabelError(f"{argument.side} argument has unlabelled points")


def _check(label: str, citations: list[int], case: Case) -> None:
    for n in citations:
        if n not in case.paragraphs:
            raise CitationError(
                f"{label} cites paragraph {n}, which does not exist in {case.id}"
            )


def check_argument_citations(argument: Argument, case: Case) -> None:
    _require_labels(argument)
    for point in argument.points:
        _check(point.label, point.citations, case)
    against = argument.strongest_point_against
    _check(f"{argument.side} strongest_point_against", against.citations, case)


def check_verdict_citations(verdict: Verdict, case: Case) -> None:
    for reason in verdict.reasons:
        _check(f"judge reason {reason.label}", reason.citations, case)


def check_reason_coverage(
    verdict: Verdict, claimant: Argument, respondent: Argument
) -> None:
    """The verdict must give exactly one reason for every point label."""
    _require_labels(claimant, respondent)
    expected = {p.label for p in claimant.points + respondent.points}
    counts = Counter(r.label for r in verdict.reasons)
    missing = sorted(expected - counts.keys())
    unknown = sorted(counts.keys() - expected)
    duplicated = sorted(label for label, c in counts.items() if c > 1)
    if missing or unknown or duplicated:
        raise CoverageError(
            f"verdict reasons: missing {missing}, unknown {unknown}, "
            f"duplicated {duplicated}"
        )


def check_unsupported_labels(
    verdict: Verdict, claimant: Argument, respondent: Argument
) -> None:
    """Every label in unsupported_claims must be a real point label."""
    _require_labels(claimant, respondent)
    real = {p.label for p in claimant.points + respondent.points}
    unknown = sorted({u.label for u in verdict.unsupported_claims} - real)
    if unknown:
        raise LabelError(f"unsupported_claims has unknown labels {unknown}")
