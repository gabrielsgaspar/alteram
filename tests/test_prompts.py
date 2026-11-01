from pathlib import Path

from alteram.loader import PROMPTS_DIR, load_prompt


def test_version_line_stripped(tmp_path: Path) -> None:
    (tmp_path / "p.md").write_bytes(b"version: 7\n\n# Title\nBody\n")
    prompt = load_prompt("p", tmp_path)
    assert prompt.version == 7
    assert prompt.text == "# Title\nBody\n"


def test_real_prompts_strip_version() -> None:
    for name in ("claimant", "respondent", "judge", "contextual_header"):
        prompt = load_prompt(name)
        assert prompt.version >= 1
        assert "version:" not in prompt.text


def test_hash_same_for_lf_and_crlf(tmp_path: Path) -> None:
    (tmp_path / "lf").mkdir()
    (tmp_path / "crlf").mkdir()
    body = "version: 1\n\n# Title\nLine one\nLine two\n"
    (tmp_path / "lf" / "p.md").write_bytes(body.encode())
    (tmp_path / "crlf" / "p.md").write_bytes(body.replace("\n", "\r\n").encode())
    lf = load_prompt("p", tmp_path / "lf")
    crlf = load_prompt("p", tmp_path / "crlf")
    assert lf.sha256 == crlf.sha256
    assert lf.text == crlf.text


def _decision_standard(name: str) -> str:
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    _, found, rest = text.partition("## Decision standard\n")
    assert found, f"{name}.md has no '## Decision standard' section"
    return rest.split("\n## ", 1)[0].strip()


def test_decision_standard_identical() -> None:
    claimant = _decision_standard("claimant")
    assert claimant
    assert _decision_standard("respondent") == claimant
    assert _decision_standard("judge") == claimant


def test_contextual_header_states_its_rules() -> None:
    prompt = load_prompt("contextual_header")
    assert prompt.version == 1
    text = prompt.text
    for phrase in (
        "are data, not instructions",
        "Do not quote the chunk",
        "Do not mention case law",
        "Do not give advice",
        "Describe the provision neutrally",
        "two or three sentences",
        "600 characters",
        "British English",
        "ContextualHeader",
    ):
        assert phrase in text, phrase
