"""Build → review harness tests with a fake claude command: no real calls."""

import importlib.util
import json
import shlex
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_review.py"

# Plays back scripted replies. The reviewer is the call with --json-schema.
# Each call's argv and stdin are appended to calls.jsonl next to this file.
FAKE_CLAUDE = r"""
import json, sys
from pathlib import Path

here = Path(__file__).parent
argv = sys.argv[1:]
stdin = sys.stdin.read()
role = "reviewer" if "--json-schema" in argv else "builder"
calls = here / "calls.jsonl"
done = [json.loads(x) for x in calls.read_text().splitlines()] if calls.exists() else []
n = sum(1 for c in done if c["role"] == role)
with calls.open("a") as f:
    f.write(json.dumps({"role": role, "argv": argv, "stdin": stdin}) + "\n")

replies = json.loads((here / "script.json").read_text())[role]
reply = replies[min(n, len(replies) - 1)]
for name in reply.get("write", []):
    Path(name).write_text(f"call {n}\n")
for name in reply.get("delete", []):
    Path(name).unlink()

session = "builder-session" if role == "builder" else f"reviewer-{n}"
print(json.dumps({"type": "system", "subtype": "init", "session_id": session}))
text = {"type": "text", "text": f"{role} call {n}"}
print(json.dumps({"type": "assistant", "message": {"content": [text]}}))
result = {
    "type": "result",
    "subtype": reply.get("subtype", "success"),
    "is_error": False,
    "session_id": session,
    "total_cost_usd": reply.get("cost", 0.01),
}
if "structured_output" in reply:
    result["structured_output"] = reply["structured_output"]
print(json.dumps(result))
sys.exit(reply.get("exit", 0))
"""

APPROVE = {
    "verdict": "approve",
    "must_fix": [],
    "nice_to_have": [],
    "checked": ["criterion 1: read work.txt"],
}
CHANGES = {
    "verdict": "changes",
    "must_fix": ["work.txt:1 needs fixing"],
    "nice_to_have": [],
    "checked": ["criterion 1: read work.txt"],
}
PASS = [[sys.executable, "-c", "pass"]]
# Fails while broken.txt exists, printing a recognisable message.
FAIL_IF_BROKEN = [
    [
        sys.executable,
        "-c",
        "import pathlib, sys\n"
        "if pathlib.Path('broken.txt').exists():\n"
        "    print('E999 broken.txt found'); sys.exit(1)",
    ]
]


@pytest.fixture
def br() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_review", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, br: ModuleType) -> Path:
    """A git repo on a work branch, with the fake claude and a passing gate."""
    for var in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{var}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{var}_EMAIL", "test@example.com")
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / ".gitignore").write_text(".loop/\n")
    (repo / "task.md").write_text("# Task\n\n## Acceptance criteria\n\n1. work\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    git(repo, "switch", "-q", "-c", "work")

    fake_dir = tmp_path / "fake"
    fake_dir.mkdir()
    (fake_dir / "claude.py").write_text(FAKE_CLAUDE)
    command = (
        f"{shlex.quote(sys.executable)} {shlex.quote(str(fake_dir / 'claude.py'))}"
    )
    monkeypatch.setenv(br.CLAUDE_BIN_ENV, command)
    monkeypatch.setattr(br, "GATE", PASS)
    monkeypatch.chdir(repo)
    return repo


def script(repo: Path, builder: list[dict[str, Any]], reviewer: list[dict]) -> None:
    fake_dir = repo.parent / "fake"
    (fake_dir / "script.json").write_text(
        json.dumps({"builder": builder, "reviewer": reviewer})
    )


def calls(repo: Path, role: str | None = None) -> list[dict[str, Any]]:
    path = repo.parent / "fake" / "calls.jsonl"
    if not path.exists():
        return []
    found = [json.loads(line) for line in path.read_text().splitlines()]
    return [c for c in found if role is None or c["role"] == role]


def summary(repo: Path) -> dict[str, Any]:
    return json.loads((repo / ".loop" / "latest" / "summary.json").read_text())


def flag_values(argv: list[str], flag: str) -> list[str]:
    """Values after a variadic flag, up to the next --flag."""
    start = argv.index(flag) + 1
    values = []
    for arg in argv[start:]:
        if arg.startswith("--"):
            break
        values.append(arg)
    return values


def test_refuses_on_main(repo: Path, br: ModuleType) -> None:
    git(repo, "switch", "-q", "main")
    script(repo, [{}], [{}])
    assert br.main(["task.md"]) == 2
    assert calls(repo) == []


def test_refuses_with_dirty_tree(repo: Path, br: ModuleType) -> None:
    (repo / "stray.txt").write_text("uncommitted\n")
    script(repo, [{}], [{}])
    assert br.main(["task.md"]) == 2
    assert calls(repo) == []


def test_stops_on_approve_and_commits(repo: Path, br: ModuleType) -> None:
    script(repo, [{"write": ["work.txt"]}], [{"structured_output": APPROVE}])
    assert br.main(["task.md", "--loops", "3"]) == 0
    result = summary(repo)
    assert result["verdict"] == "approve"
    assert result["stop_reason"] == "approve"
    assert len(result["loops"]) == 1
    assert len(calls(repo, "builder")) == 1
    assert len(calls(repo, "reviewer")) == 1
    assert "harness: loop 1 builder" in git(repo, "log", "--format=%s")
    assert git(repo, "status", "--porcelain") == ""
    assert (repo / ".loop" / "latest" / "builder.log").exists()
    assert (repo / ".loop" / "latest" / "reviewer.log").exists()


def test_stops_after_loops_with_changes(repo: Path, br: ModuleType) -> None:
    script(repo, [{"write": ["work.txt"]}], [{"structured_output": CHANGES}])
    assert br.main(["task.md", "--loops", "2"]) == 1
    result = summary(repo)
    assert result["verdict"] == "changes"
    assert result["stop_reason"] == "loops"
    assert len(result["loops"]) == 2
    builder_calls = calls(repo, "builder")
    assert len(builder_calls) == 2
    assert "work.txt:1 needs fixing" in builder_calls[1]["stdin"]
    assert len(calls(repo, "reviewer")) == 2


def test_failing_gate_skips_reviewer_and_feeds_builder(
    repo: Path, br: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(br, "GATE", FAIL_IF_BROKEN)
    script(
        repo,
        [{"write": ["broken.txt"]}, {"delete": ["broken.txt"], "write": ["ok.txt"]}],
        [{"structured_output": APPROVE}],
    )
    assert br.main(["task.md", "--loops", "3"]) == 0
    result = summary(repo)
    assert result["loops"][0]["gate_passed"] is False
    assert "review" not in result["loops"][0]
    assert result["loops"][1]["gate_passed"] is True
    assert len(calls(repo, "reviewer")) == 1
    assert "E999 broken.txt found" in calls(repo, "builder")[1]["stdin"]


def test_missing_structured_output_is_changes_with_error(
    repo: Path, br: ModuleType
) -> None:
    script(repo, [{"write": ["work.txt"]}], [{}])
    assert br.main(["task.md", "--loops", "1"]) == 1
    result = summary(repo)
    assert result["verdict"] == "changes"
    review = result["loops"][0]["review"]
    assert review["verdict"] == "changes"
    assert "structured_output" in review["error"]


def test_approve_without_checks_is_changes(repo: Path, br: ModuleType) -> None:
    unchecked = {**APPROVE, "checked": []}
    script(repo, [{"write": ["work.txt"]}], [{"structured_output": unchecked}])
    assert br.main(["task.md", "--loops", "1"]) == 1
    assert summary(repo)["loops"][0]["review"]["error"]


def test_stops_at_total_budget(repo: Path, br: ModuleType) -> None:
    # The builder reports its session's cumulative cost, as resumed sessions do.
    script(
        repo,
        [{"write": ["work.txt"], "cost": 0.6}],
        [{"structured_output": CHANGES, "cost": 0.5}],
    )
    assert br.main(["task.md", "--loops", "5", "--budget", "1.0"]) == 1
    result = summary(repo)
    assert result["stop_reason"] == "budget"
    assert result["cost_usd"] == pytest.approx(1.1)
    assert len(calls(repo, "builder")) == 1
    assert len(calls(repo, "reviewer")) == 1


def test_call_budget_is_capped_by_what_remains(repo: Path, br: ModuleType) -> None:
    script(
        repo,
        [{"write": ["work.txt"], "cost": 0.7}],
        [{"structured_output": APPROVE}],
    )
    br.main(["task.md", "--budget", "1.0", "--call-budget", "0.5"])
    builder_argv = calls(repo, "builder")[0]["argv"]
    reviewer_argv = calls(repo, "reviewer")[0]["argv"]
    assert flag_values(builder_argv, "--max-budget-usd") == ["0.50"]
    assert flag_values(reviewer_argv, "--max-budget-usd") == ["0.30"]


def test_builder_resumed_and_reviewer_fresh(repo: Path, br: ModuleType) -> None:
    script(repo, [{"write": ["work.txt"]}], [{"structured_output": CHANGES}])
    br.main(["task.md", "--loops", "3"])
    builder_calls = calls(repo, "builder")
    assert len(builder_calls) == 3
    assert "--resume" not in builder_calls[0]["argv"]
    for call in builder_calls[1:]:
        assert flag_values(call["argv"], "--resume") == ["builder-session"]
    for call in calls(repo, "reviewer"):
        assert "--resume" not in call["argv"]
        assert "--continue" not in call["argv"]


def test_reviewer_cannot_edit_or_write(repo: Path, br: ModuleType) -> None:
    script(repo, [{"write": ["work.txt"]}], [{"structured_output": APPROVE}])
    br.main(["task.md"])
    argv = calls(repo, "reviewer")[0]["argv"]
    allowed = flag_values(argv, "--allowedTools")
    assert allowed
    assert not any(t.startswith(("Edit", "Write")) for t in allowed)
    assert {"Edit", "Write"} <= set(flag_values(argv, "--disallowedTools"))
    assert "Edit" not in flag_values(argv, "--tools")[0].split(",")


def test_failed_builder_call_stops(repo: Path, br: ModuleType) -> None:
    script(repo, [{"subtype": "error_max_budget_usd", "exit": 1}], [{}])
    assert br.main(["task.md"]) == 1
    result = summary(repo)
    assert result["stop_reason"] == "error"
    assert calls(repo, "reviewer") == []


def test_both_agents_run_sandboxed(repo: Path, br: ModuleType) -> None:
    script(repo, [{"write": ["work.txt"]}], [{"structured_output": APPROVE}])
    br.main(["task.md"])
    for call in calls(repo):
        settings = json.loads(flag_values(call["argv"], "--settings")[0])
        assert settings["sandbox"]["enabled"] is True
        assert settings["sandbox"]["allowUnsandboxedCommands"] is False


@pytest.mark.parametrize(
    ("result", "verdict"),
    [
        (None, "changes"),
        ({"structured_output": {"verdict": "maybe"}}, "changes"),
        ({"structured_output": APPROVE}, "approve"),
        ({"structured_output": CHANGES}, "changes"),
    ],
)
def test_read_verdict(
    br: ModuleType, result: dict[str, Any] | None, verdict: str
) -> None:
    assert br.read_verdict(result)["verdict"] == verdict


def test_review_schema_matches_read_verdict(br: ModuleType) -> None:
    schema = json.loads((br.HARNESS / "review_schema.json").read_text())
    assert schema["properties"]["verdict"]["enum"] == ["approve", "changes"]
    assert set(schema["required"]) == set(APPROVE)
