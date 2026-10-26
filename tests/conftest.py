import pytest

from alteram.models import Argument, Case, CounterPoint, Point


@pytest.fixture
def case() -> Case:
    return Case(
        id="case-x",
        title="Small case",
        kind="balanced",
        expected="claimant",
        paragraphs={1: "One.", 2: "Two.", 3: "Three."},
    )


def make_argument(side: str, citations: list[list[int]]) -> Argument:
    """An argument whose points carry a wrong model-supplied label."""
    return Argument(
        side=side,
        points=[
            Point(label="X9", claim="c", reasoning="r", citations=c) for c in citations
        ],
        strongest_point_against=CounterPoint(point="p", answer="a", citations=[1]),
        requested_outcome="win",
    )
