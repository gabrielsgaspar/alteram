"""Build → review loop: a builder agent implements a task, code runs the gate,
and a fresh read-only reviewer agent checks the result against the task file.

Usage: uv run python scripts/build_review.py tasks/<task>.md --loops 3

See docs/harness-plan.md. Standard library only. Needs Claude Code v2.1.277+
(resumed sessions report cumulative cost) and the sandbox (Linux or WSL2).
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

HARNESS = Path(__file__).resolve().parents[1] / "harness"
CLAUDE_BIN_ENV = "ALTERAM_CLAUDE_BIN"
PROTECTED_BRANCHES = {"main"}

# Bash commands run inside the OS sandbox: no network, and Read deny rules such
# as Read(./.env) become filesystem blocks. Never fall back to running unsandboxed.
SANDBOX_SETTINGS = json.dumps(
    {
        "sandbox": {
            "enabled": True,
            "allowUnsandboxedCommands": False,
            "failIfUnavailable": True,
        }
    }
)
# No MCP servers: --tools does not cover MCP tools, and the user's claude.ai
# connectors otherwise load hundreds of tool definitions into every call.
NO_MCP = ["--strict-mcp-config"]
NO_MCP_DENIED = ["mcp__*"]
BUILDER_TOOLS = "Read,Edit,Write,Glob,Grep,Bash"
BUILDER_ALLOWED = [
    "Bash(uv run pytest *)",
    "Bash(uv run ruff *)",
    "Bash(git diff *)",
    "Bash(git status *)",
]
REVIEWER_TOOLS = "Read,Grep,Glob,Bash"
REVIEWER_ALLOWED = [
    "Read",
    "Grep",
    "Glob",
    "Bash(git diff *)",
    "Bash(git log *)",
    "Bash(uv run pytest *)",
]
REVIEWER_DENIED = ["Edit", "Write", "NotebookEdit"]

# Run by this script, not by a model. Note: outside the sandbox.
GATE = [
    ["uv", "run", "ruff", "check", "."],
    ["uv", "run", "ruff", "format", "--check", "."],
    ["uv", "run", "pytest", "-q"],
]
GATE_OUTPUT_LIMIT = 4000


@dataclass
class CallResult:
    returncode: int
    result: dict[str, Any] | None  # the final stream-json "result" event

    @property
    def session_id(self) -> str | None:
        return (self.result or {}).get("session_id")

    @property
    def cost(self) -> float:
        return float((self.result or {}).get("total_cost_usd") or 0.0)

    @property
    def ok(self) -> bool:
        return (
            self.returncode == 0
            and self.result is not None
            and not self.result.get("is_error")
            and self.result.get("subtype") == "success"
        )


@dataclass
class Summary:
    task: str
    branch: str
    run_dir: str
    loops: list[dict[str, Any]] = field(default_factory=list)
    commits: list[str] = field(default_factory=list)
    verdict: str = "changes"
    stop_reason: str = ""
    cost_usd: float = 0.0


class Log:
    """Writes the same text to the run directory and to .loop/latest/."""

    def __init__(self, paths: list[Path]) -> None:
        self.files: list[TextIO] = [p.open("a", encoding="utf-8") for p in paths]

    def write(self, text: str) -> None:
        for f in self.files:
            f.write(text)
            f.flush()

    def close(self) -> None:
        for f in self.files:
            f.close()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the build → review loop.")
    parser.add_argument("task", type=Path, help="task file, e.g. tasks/foo.md")
    parser.add_argument("--loops", type=int, default=3, help="maximum loops")
    parser.add_argument(
        "--budget", type=float, default=5.0, help="total budget for the run, USD"
    )
    parser.add_argument(
        "--call-budget", type=float, default=1.0, help="budget per agent call, USD"
    )
    parser.add_argument(
        "--base", default="main", help="branch the run must not start on"
    )
    args = parser.parse_args(argv)
    if args.loops < 1:
        parser.error("--loops must be at least 1")
    if args.budget <= 0 or args.call_budget <= 0:
        parser.error("budgets must be positive")
    return args


def git(*args: str) -> str:
    done = subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", check=True
    )
    return done.stdout


def precheck(base: str) -> str | None:
    """Return a reason to refuse to start, or None if it is safe."""
    branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    if branch == "HEAD":
        return "detached HEAD: check out a working branch first"
    if branch in PROTECTED_BRANCHES | {base}:
        return f"refusing to run on '{branch}': create a working branch first"
    if git("status", "--porcelain").strip():
        return "working tree has uncommitted changes: commit or stash them first"
    return None


def claude_bin() -> list[str]:
    return shlex.split(os.environ.get(CLAUDE_BIN_ENV, "claude"))


def builder_command(session_id: str | None, call_budget: float) -> list[str]:
    cmd = [
        *claude_bin(),
        "-p",
        "Carry out the instructions given on stdin.",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "acceptEdits",
        "--permission-prompts",
        "none",
        *NO_MCP,
        "--tools",
        BUILDER_TOOLS,
        "--allowedTools",
        *BUILDER_ALLOWED,
        "--disallowedTools",
        *NO_MCP_DENIED,
        "--settings",
        SANDBOX_SETTINGS,
        "--append-system-prompt-file",
        str(HARNESS / "builder.md"),
        "--max-budget-usd",
        f"{call_budget:.2f}",
    ]
    if session_id:
        cmd += ["--resume", session_id]
    return cmd


def reviewer_command(call_budget: float) -> list[str]:
    schema = (HARNESS / "review_schema.json").read_text(encoding="utf-8")
    return [
        *claude_bin(),
        "-p",
        "Review the work described on stdin.",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "dontAsk",
        "--permission-prompts",
        "none",
        *NO_MCP,
        "--tools",
        REVIEWER_TOOLS,
        "--allowedTools",
        *REVIEWER_ALLOWED,
        "--disallowedTools",
        *REVIEWER_DENIED,
        *NO_MCP_DENIED,
        "--settings",
        SANDBOX_SETTINGS,
        "--append-system-prompt-file",
        str(HARNESS / "reviewer.md"),
        "--json-schema",
        schema,
        "--max-budget-usd",
        f"{call_budget:.2f}",
    ]


def render(event: dict[str, Any]) -> str:
    """Turn one stream-json event into readable log text."""
    kind = event.get("type")
    if kind == "system" and event.get("subtype") == "init":
        return f"[session {event.get('session_id')} model {event.get('model')}]\n"
    if kind == "assistant":
        parts = []
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "text":
                parts.append(block["text"].rstrip() + "\n")
            elif block.get("type") == "tool_use":
                args = block.get("input", {})
                detail = args.get("command") or args.get("file_path") or ""
                parts.append(f"→ {block.get('name')}: {detail}\n")
        return "".join(parts)
    if kind == "user":
        parts = []
        for block in event.get("message", {}).get("content", []):
            if isinstance(block, dict) and block.get("type") == "tool_result":
                content = block.get("content")
                text = content if isinstance(content, str) else json.dumps(content)
                flag = " (error)" if block.get("is_error") else ""
                parts.append(f"  ←{flag} {text[:300]}\n")
        return "".join(parts)
    if kind == "result":
        return (
            f"[result {event.get('subtype')}, "
            f"cost ${float(event.get('total_cost_usd') or 0):.4f}]\n"
        )
    return ""


def run_claude(cmd: list[str], prompt: str, log: Log, raw: Log) -> CallResult:
    """Run one claude -p call, streaming its output into the logs."""
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(prompt)
    proc.stdin.close()
    result = None
    for line in proc.stdout:
        raw.write(line)
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            log.write(line)
            continue
        if not isinstance(event, dict):
            continue
        log.write(render(event))
        if event.get("type") == "result":
            result = event
    return CallResult(proc.wait(), result)


def run_gate() -> tuple[bool, str]:
    """Run the checks in code. Return (passed, output of failing checks)."""
    failures = []
    for cmd in GATE:
        done = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        if done.returncode != 0:
            output = (done.stdout + done.stderr)[-GATE_OUTPUT_LIMIT:]
            failures.append(f"$ {' '.join(cmd)}  (exit {done.returncode})\n{output}")
    return not failures, "\n".join(failures)


def read_verdict(result: dict[str, Any] | None) -> dict[str, Any]:
    """Read the reviewer's verdict. Anything but a checked approval is 'changes'."""
    out = (result or {}).get("structured_output")
    if not isinstance(out, dict) or out.get("verdict") not in ("approve", "changes"):
        return {
            "verdict": "changes",
            "must_fix": [],
            "nice_to_have": [],
            "checked": [],
            "error": "reviewer returned no valid structured_output",
        }
    if out["verdict"] == "approve" and not out.get("checked"):
        return {
            **out,
            "verdict": "changes",
            "error": "approval without any checked criteria is not an approval",
        }
    return out


def builder_prompt(task: Path, feedback: str | None) -> str:
    if feedback is None:
        text = task.read_text(encoding="utf-8")
        return f"Implement this task. Task file: {task.as_posix()}\n\n{text}"
    return (
        "Your previous attempt was checked. Fix the points below and nothing "
        f"else, staying within the task file {task.as_posix()}.\n\n{feedback}"
    )


def review_feedback(verdict: dict[str, Any]) -> str:
    lines = ["The reviewer asked for changes. Must fix:"]
    lines += [f"- {item}" for item in verdict.get("must_fix", [])] or ["- (none)"]
    if verdict.get("error"):
        lines.append(
            f"Note: {verdict['error']}. Re-check your work against every "
            "acceptance criterion."
        )
    return "\n".join(lines)


def reviewer_prompt(task: Path, start: str) -> str:
    """Show only this run's changes: commits since the run started, and any
    uncommitted ones."""
    text = task.read_text(encoding="utf-8")
    committed = git("diff", f"{start}..HEAD")
    uncommitted = git("diff", "HEAD")
    return (
        f"Task file: {task.as_posix()}\n\n{text}\n\n"
        "The gate (ruff check, ruff format --check, pytest) has passed.\n\n"
        f"## Changes made in this run (git diff {start[:7]}..HEAD)\n\n"
        f"```diff\n{committed}```\n\n"
        f"## Uncommitted changes\n\n```diff\n{uncommitted or '(none)'}\n```\n"
    )


def commit_loop(n: int, task: Path) -> str | None:
    """Commit everything the builder changed. Return the sha, or None."""
    git("add", "-A")
    if not git("status", "--porcelain").strip():
        return None
    git("commit", "-q", "-m", f"harness: loop {n} builder\n\nTask: {task.as_posix()}")
    return git("rev-parse", "--short", "HEAD").strip()


def open_logs(run_dir: Path, latest: Path, name: str) -> tuple[Log, Log]:
    readable = Log([run_dir / f"{name}.log", latest / f"{name}.log"])
    raw = Log([run_dir / f"{name}.jsonl", latest / f"{name}.jsonl"])
    return readable, raw


def make_run_dir() -> tuple[Path, Path]:
    root = Path(git("rev-parse", "--show-toplevel").strip()) / ".loop"
    run_dir = root / datetime.now().strftime("%Y%m%d-%H%M%S")
    latest = root / "latest"
    run_dir.mkdir(parents=True)
    shutil.rmtree(latest, ignore_errors=True)
    latest.mkdir()
    return run_dir, latest


def run_loop(args: argparse.Namespace, summary: Summary, logs: dict[str, Log]) -> None:
    start = git("rev-parse", "HEAD").strip()
    builder_session: str | None = None
    builder_cost = 0.0  # latest cumulative total of the resumed builder session
    reviewer_cost = 0.0
    feedback: str | None = None

    def remaining() -> float:
        summary.cost_usd = builder_cost + reviewer_cost
        return args.budget - summary.cost_usd

    for n in range(1, args.loops + 1):
        if remaining() <= 0:
            summary.stop_reason = "budget"
            return
        record: dict[str, Any] = {"loop": n}
        summary.loops.append(record)

        print(f"loop {n}: builder")
        logs["builder"].write(f"\n===== loop {n} =====\n")
        call = run_claude(
            builder_command(builder_session, min(args.call_budget, remaining())),
            builder_prompt(args.task, feedback),
            logs["builder"],
            logs["builder_raw"],
        )
        builder_session = call.session_id or builder_session
        builder_cost = max(builder_cost, call.cost)
        record["builder_cost_usd"] = call.cost
        sha = commit_loop(n, args.task)
        if sha:
            summary.commits.append(sha)
        if not call.ok:
            subtype = (call.result or {}).get("subtype", "no result")
            record["error"] = f"builder failed: exit {call.returncode}, {subtype}"
            summary.stop_reason = "error"
            return

        print(f"loop {n}: gate")
        passed, gate_output = run_gate()
        record["gate_passed"] = passed
        if not passed:
            logs["builder"].write(f"\n[gate failed]\n{gate_output}\n")
            feedback = f"The gate failed. Make it pass.\n\n{gate_output}"
            continue

        if remaining() <= 0:
            summary.stop_reason = "budget"
            return
        print(f"loop {n}: reviewer")
        logs["reviewer"].write(f"\n===== loop {n} =====\n")
        review = run_claude(
            reviewer_command(min(args.call_budget, remaining())),
            reviewer_prompt(args.task, start),
            logs["reviewer"],
            logs["reviewer_raw"],
        )
        reviewer_cost += review.cost
        verdict = read_verdict(review.result)
        record["reviewer_cost_usd"] = review.cost
        record["review"] = verdict
        logs["reviewer"].write(f"[verdict]\n{json.dumps(verdict, indent=2)}\n")
        summary.verdict = verdict["verdict"]
        if summary.verdict == "approve":
            summary.stop_reason = "approve"
            return
        feedback = review_feedback(verdict)

    remaining()
    summary.stop_reason = "loops"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if not args.task.is_file():
        print(f"task file not found: {args.task}", file=sys.stderr)
        return 2
    refusal = precheck(args.base)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2

    run_dir, latest = make_run_dir()
    summary = Summary(
        task=args.task.as_posix(),
        branch=git("rev-parse", "--abbrev-ref", "HEAD").strip(),
        run_dir=run_dir.as_posix(),
    )
    logs: dict[str, Log] = {}
    for name in ("builder", "reviewer"):
        logs[name], logs[f"{name}_raw"] = open_logs(run_dir, latest, name)
    try:
        run_loop(args, summary, logs)
    finally:
        for log in logs.values():
            log.close()
        if summary.verdict != "approve":
            summary.verdict = "changes"
        text = json.dumps(summary.__dict__, indent=2)
        (run_dir / "summary.json").write_text(text, encoding="utf-8")
        (latest / "summary.json").write_text(text, encoding="utf-8")

    print(
        f"\nverdict: {summary.verdict} (stopped: {summary.stop_reason})\n"
        f"loops used: {len(summary.loops)}\n"
        f"cost: ${summary.cost_usd:.4f} of ${args.budget:.2f}\n"
        f"commits: {', '.join(summary.commits) or 'none'}\n"
        f"logs: {run_dir.as_posix()}/builder.log, {run_dir.as_posix()}/reviewer.log"
    )
    return 0 if summary.verdict == "approve" else 1


if __name__ == "__main__":
    sys.exit(main())
