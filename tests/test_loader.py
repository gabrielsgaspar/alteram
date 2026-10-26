import re
from pathlib import Path

import pytest

from alteram.loader import CaseFormatError, load_case

ROOT = Path(__file__).resolve().parents[1]
CASES = sorted((ROOT / "cases").glob("*.md"))
FIXTURES = Path(__file__).parent / "fixtures"


def test_at_least_three_real_cases() -> None:
    assert len(CASES) >= 3


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_real_case_loads(path: Path) -> None:
    case = load_case(path)
    assert case.id == path.stem
    assert case.title
    assert list(case.paragraphs) == list(range(1, len(case.paragraphs) + 1))
    assert re.fullmatch(r"[0-9a-f]{64}", case.sha256)


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("bad-numbering", "numbered 1..n"),
        ("missing-field", "expected"),
        ("no-frontmatter", "frontmatter"),
    ],
)
def test_malformed_case_rejected(name: str, message: str) -> None:
    with pytest.raises(CaseFormatError, match=message):
        load_case(FIXTURES / f"{name}.md")


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_agent_text_hides_evaluation_metadata(path: Path) -> None:
    case = load_case(path)
    text = case.agent_text()
    # "claimant" etc. appear in ordinary case prose, so check the key: value pairs.
    for secret in ("kind:", "expected", case.kind, f": {case.expected}", "---"):
        assert secret not in text
    assert text.startswith("[1] ")
    assert f"[{len(case.paragraphs)}] " in text


def test_case_hash_same_for_lf_and_crlf(tmp_path: Path) -> None:
    body = CASES[0].read_bytes().decode("utf-8").replace("\r\n", "\n")
    (tmp_path / "lf.md").write_bytes(body.encode())
    (tmp_path / "crlf.md").write_bytes(body.replace("\n", "\r\n").encode())
    lf = load_case(tmp_path / "lf.md")
    assert lf.sha256 == load_case(tmp_path / "crlf.md").sha256
    assert lf.sha256 == load_case(CASES[0]).sha256
