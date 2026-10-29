"""Ship: take a task from a task file (or an existing branch) to a merged PR.

Usage:
  uv run python scripts/ship.py task tasks/<name>.md [--loops 3] [--budget 5]
  uv run python scripts/ship.py branch <branch> --task tasks/<name>.md [...]
  (either mode takes --no-merge)

Runs the build → review loop (scripts/build_review.py) in a worktree, checks the
merge gate in code, pushes, opens or updates the PR, waits for CI (feeding a CI
failure back to the builder while loops remain) and merges. See the "Ship"
section of docs/harness-plan.md. Standard library only; Linux or WSL2.

Exit codes: 0 merged (or approved with --no-merge), 2 refused, 3 needs you,
4 budget reached.
"""

import argparse
import fnmatch
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_review as br  # noqa: E402

PROJECTS = Path.home() / "projects"
WORKTREES = PROJECTS / "alteram-wt"
SHIP_DIR = PROJECTS / ".ship"
GH_BIN_ENV = "ALTERAM_GH_BIN"
BASE_BRANCH = "main"
BASE_REF = "origin/main"
# `stat -f -c %T` reports ext4 as "ext2/ext3".
LINUX_FS = {"ext2/ext3"}

MERGED, REFUSED, NEEDS_ME, BUDGET = 0, 2, 3, 4

# Paths a task may change only when its In-scope list names them explicitly.
PROTECTED_DIRS = (".claude/", ".github/", "prompts/", "cases/")
PROTECTED_FILES = ("pyproject.toml", "uv.lock")
GLOB_CHARS = set("*?[")

# Split literals, so this file and its tests do not trip their own scan.
SECRET_PATTERNS = [
    ("Anthropic key prefix", re.compile(re.escape("sk-" + "ant-"))),
    ("LangSmith key prefix", re.compile(re.escape("lsv2" + "_"))),
    ("GitHub token prefix", re.compile(re.escape("ghp" + "_"))),
    ("GitHub fine-grained token prefix", re.compile(re.escape("github" + "_pat_"))),
    ("PEM block", re.compile(re.escape("-----" + "BEGIN"))),
    (
        "KEY= or TOKEN= assignment with a long value",
        re.compile(r"(?:KEY|TOKEN)\s*=\s*['\"]?[^\s'\"]{16,}"),
    ),
]

CHECKS_TIMEOUT = 180  # seconds to wait for CI checks to appear
CHECKS_POLL = 10
CI_LOG_LIMIT = 4000


class Stop(Exception):
    def __init__(self, code: int, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


@dataclass
class Run:
    mode: str
    name: str
    branch: str = ""
    worktree: str = ""
    pr_url: str = ""
    loops: int = 0
    cost_usd: float = 0.0
    verdict: str = ""
    checked: list[str] = field(default_factory=list)
    gate: dict[str, Any] = field(default_factory=dict)
    ci: str = ""
    merge_sha: str = ""
    exit_code: int = 0
    reason: str = ""


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Take a task to a merged PR.")
    modes = parser.add_subparsers(dest="mode", required=True)
    task = modes.add_parser("task", help="new branch task/<name> from origin/main")
    task.add_argument("task", help="task file on origin/main, e.g. tasks/foo.md")
    branch = modes.add_parser("branch", help="an existing branch")
    branch.add_argument("branch")
    branch.add_argument("--task", required=True, help="task file, e.g. tasks/foo.md")
    for sub in (task, branch):
        sub.add_argument("--loops", type=int, default=3, help="maximum loops in all")
        sub.add_argument("--budget", type=float, default=5.0, help="total USD")
        sub.add_argument("--no-merge", action="store_true", help="stop before merge")
    args = parser.parse_args(argv)
    if args.loops < 1:
        parser.error("--loops must be at least 1")
    if args.budget <= 0:
        parser.error("--budget must be positive")
    return args


def run_cmd(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )


def git(cwd: Path, *args: str) -> str:
    done = run_cmd(["git", *args], cwd)
    if done.returncode != 0:
        raise Stop(NEEDS_ME, f"git {' '.join(args)} failed:\n{done.stderr.strip()}")
    return done.stdout


def git_ok(cwd: Path, *args: str) -> bool:
    return run_cmd(["git", *args], cwd).returncode == 0


def gh(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run_cmd([*shlex.split(os.environ.get(GH_BIN_ENV, "gh")), *args], cwd)


def fs_type(path: Path) -> str:
    """Filesystem type of path, or of its nearest existing ancestor."""
    while not path.exists():
        path = path.parent
    done = subprocess.run(
        ["stat", "-f", "-c", "%T", str(path)], capture_output=True, text=True
    )
    return done.stdout.strip() or "unknown"


def guard(path: Path) -> str | None:
    """Return a reason to refuse working in path, or None if it is safe."""
    resolved = path.resolve()
    if resolved == Path("/mnt") or Path("/mnt") in resolved.parents:
        return (
            f"refusing {resolved}: it is under /mnt (the Windows filesystem). "
            f"Run from a checkout under {PROJECTS} on the Linux filesystem."
        )
    if not resolved.is_relative_to(PROJECTS.resolve()):
        return f"refusing {resolved}: it is not under {PROJECTS}"
    kind = fs_type(resolved)
    if kind not in LINUX_FS:
        return f"refusing {resolved}: it is on {kind}, not ext4"
    return None


def require_safe(path: Path) -> None:
    refusal = guard(path)
    if refusal:
        raise Stop(REFUSED, refusal)


def sanitise(branch: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip("-")


def find_worktree(repo: Path, branch: str) -> Path | None:
    """The worktree that has branch checked out, if any."""
    current: Path | None = None
    for line in git(repo, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            current = Path(line.removeprefix("worktree "))
        elif line == f"branch refs/heads/{branch}":
            return current
    return None


def prepare_task(root: Path, task: Path, run: Run) -> tuple[Path, bool]:
    """Create branch task/<name> and its worktree from origin/main."""
    run.branch = f"task/{run.name}"
    worktree = WORKTREES / run.name
    require_safe(worktree)
    if not git_ok(root, "cat-file", "-e", f"{BASE_REF}:{task.as_posix()}"):
        raise Stop(REFUSED, f"{task} is not on {BASE_REF}: commit and merge it first")
    for ref in (f"refs/heads/{run.branch}", f"refs/remotes/origin/{run.branch}"):
        if git_ok(root, "show-ref", "--verify", "--quiet", ref):
            raise Stop(REFUSED, f"branch {run.branch} already exists: use branch mode")
    if worktree.exists():
        raise Stop(REFUSED, f"{worktree} already exists")
    worktree.parent.mkdir(parents=True, exist_ok=True)
    git(
        root,
        "worktree",
        "add",
        "-q",
        "--no-track",
        "-b",
        run.branch,
        str(worktree),
        BASE_REF,
    )
    return worktree, True


def prepare_branch(root: Path, branch: str, run: Run) -> tuple[Path, bool]:
    """Find or create the branch's worktree, then merge origin/main into it."""
    run.branch = branch
    worktree = find_worktree(root, branch)
    created = worktree is None
    if worktree is None:
        worktree = WORKTREES / sanitise(branch)
        require_safe(worktree)
        if worktree.exists():
            raise Stop(REFUSED, f"{worktree} already exists")
        worktree.parent.mkdir(parents=True, exist_ok=True)
        if git_ok(root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"):
            git(root, "worktree", "add", "-q", str(worktree), branch)
        elif git_ok(
            root, "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}"
        ):
            git(
                root,
                "worktree",
                "add",
                "-q",
                "-b",
                branch,
                str(worktree),
                f"origin/{branch}",
            )
        else:
            raise Stop(REFUSED, f"branch {branch} not found locally or on origin")
    else:
        require_safe(worktree)
    if git(worktree, "status", "--porcelain").strip():
        raise Stop(REFUSED, f"{worktree} has uncommitted changes")
    merge = run_cmd(["git", "merge", "--no-edit", BASE_REF], worktree)
    if merge.returncode != 0:
        run_cmd(["git", "merge", "--abort"], worktree)
        raise Stop(
            NEEDS_ME,
            f"merging {BASE_REF} into {branch} conflicts; merge aborted. "
            f"Resolve it in {worktree} and run again.\n{merge.stdout.strip()}",
        )
    return worktree, created


def link_logs(name: str, target: Path) -> None:
    """Point SHIP_DIR/<name> at target, so log viewers can tail a fixed path."""
    SHIP_DIR.mkdir(parents=True, exist_ok=True)
    link = SHIP_DIR / name
    if link.is_symlink():
        link.unlink()
    elif link.exists():
        raise Stop(REFUSED, f"{link} exists and is not a symlink")
    link.symlink_to(target)


def harness(
    run: Run,
    args: argparse.Namespace,
    worktree: Path,
    task: Path,
    *,
    review_first: bool = False,
    feedback: Path | None = None,
) -> None:
    """Run build_review.py in worktree with the loops and budget that remain."""
    loops = args.loops - run.loops
    budget = args.budget - run.cost_usd
    if budget < 0.01:
        raise Stop(BUDGET, f"budget reached: ${run.cost_usd:.4f} of ${args.budget:.2f}")
    if loops < 1:
        raise Stop(NEEDS_ME, f"no loops remain ({run.loops} of {args.loops} used)")
    argv = [task.as_posix(), "--loops", str(loops), "--budget", f"{budget:.4f}"]
    argv += ["--base-ref", BASE_REF]
    if review_first:
        argv.append("--review-first")
    if feedback:
        argv += ["--feedback", str(feedback)]
    here = Path.cwd()
    os.chdir(worktree)
    try:
        code = br.main(argv)
    finally:
        os.chdir(here)
    path = worktree / ".loop" / "latest" / "summary.json"
    if code == 2 or not path.exists():
        raise Stop(REFUSED, "build_review.py refused to start (see its message)")
    result = json.loads(path.read_text(encoding="utf-8"))
    run.loops += len(result["loops"])
    run.cost_usd += result["cost_usd"]
    reviews = [loop["review"] for loop in result["loops"] if "review" in loop]
    run.verdict = result["verdict"]
    run.checked = reviews[-1].get("checked", []) if reviews else []
    if result["stop_reason"] == "budget":
        raise Stop(BUDGET, f"budget reached: ${run.cost_usd:.4f} of ${args.budget:.2f}")
    if result["verdict"] != "approve":
        raise Stop(
            NEEDS_ME,
            f"reviewer did not approve (stopped: {result['stop_reason']}); "
            f"logs in {result['run_dir']}",
        )


def in_scope_patterns(task_text: str) -> list[str]:
    """Backticked paths and globs in the task file's "## In scope" section."""
    match = re.search(r"^## In scope\s*$(.*?)(?=^## |\Z)", task_text, re.M | re.S)
    if not match:
        return []
    return [t for t in re.findall(r"`([^`]+)`", match.group(1)) if " " not in t]


def matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/"):
        return path.startswith(pattern)
    return path == pattern or fnmatch.fnmatchcase(path, pattern)


def scope_problems(files: list[str], patterns: list[str]) -> list[str]:
    if not files:
        return [f"no changes against {BASE_REF}"]
    return [
        f"{f} is not in the task's In-scope list"
        for f in files
        if not any(matches(f, p) for p in patterns)
    ]


def is_protected(path: str) -> bool:
    return (
        PurePosixPath(path).name.startswith(".env")
        or path.startswith(PROTECTED_DIRS)
        or path in PROTECTED_FILES
    )


def protected_problems(files: list[str], patterns: list[str]) -> list[str]:
    """A protected path needs an exact path or directory in scope, not a glob."""
    explicit = [p for p in patterns if not GLOB_CHARS & set(p)]
    return [
        f"{f} is a protected path the In-scope list does not name explicitly"
        for f in files
        if is_protected(f) and not any(matches(f, p) for p in explicit)
    ]


def secret_problems(diff: str) -> list[str]:
    """Scan added lines. Report the file and pattern, never the match."""
    problems = []
    current = "?"
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line.removeprefix("+++ ").removeprefix("b/")
        elif line.startswith("+"):
            for label, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    problems.append(f"{current}: added line matches {label}")
    return problems


def merge_gate(run: Run, worktree: Path, task_text: str) -> None:
    files = git(worktree, "diff", f"{BASE_REF}...HEAD", "--name-only").split()
    patterns = in_scope_patterns(task_text)
    approved = run.verdict == "approve" and bool(run.checked)
    results = {
        "approved": [] if approved else ["final verdict is not a checked approval"],
        "scope": scope_problems(files, patterns),
        "protected": protected_problems(files, patterns),
        "secrets": secret_problems(git(worktree, "diff", f"{BASE_REF}...HEAD")),
    }
    run.gate = {k: {"ok": not v, "problems": v} for k, v in results.items()}
    problems = [p for v in results.values() for p in v]
    if problems:
        raise Stop(
            NEEDS_ME, "merge gate failed:\n" + "\n".join(f"  - {p}" for p in problems)
        )


def pr_title(task_text: str, fallback: str) -> str:
    for line in task_text.splitlines():
        if line.startswith("# "):
            return line.removeprefix("# ").removeprefix("Task:").strip() or fallback
    return fallback


def pr_body(run: Run, task_text: str) -> str:
    checked = "\n".join(f"- {c}" for c in run.checked) or "- (none)"
    return (
        f"{task_text.rstrip()}\n\n---\n\n## Reviewer checked\n\n{checked}\n\n"
        f"Loops used: {run.loops}. Cost: ${run.cost_usd:.4f}.\n\n"
        "Shipped by `scripts/ship.py`.\n"
    )


def publish_pr(run: Run, worktree: Path, task_text: str) -> None:
    """Create the PR, or comment on it if it already exists."""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(pr_body(run, task_text))
    try:
        found = gh(worktree, "pr", "view", run.branch, "--json", "url")
        if found.returncode == 0:
            run.pr_url = json.loads(found.stdout)["url"]
            done = gh(worktree, "pr", "comment", run.pr_url, "--body-file", f.name)
        else:
            title = pr_title(task_text, run.branch)
            done = gh(
                worktree,
                "pr",
                "create",
                "--head",
                run.branch,
                "--base",
                BASE_BRANCH,
                "--title",
                title,
                "--body-file",
                f.name,
            )
            if done.returncode == 0:
                run.pr_url = done.stdout.strip().splitlines()[-1]
    finally:
        os.unlink(f.name)
    if done.returncode != 0:
        raise Stop(NEEDS_ME, f"gh failed to publish the PR:\n{done.stderr.strip()}")


def wait_for_ci(worktree: Path, url: str) -> str:
    """Return "pass", "fail" or "none" (no checks appeared in time)."""
    deadline = time.monotonic() + CHECKS_TIMEOUT
    while True:
        listed = gh(worktree, "pr", "checks", url, "--json", "name,bucket")
        try:
            appeared = bool(json.loads(listed.stdout or "[]"))
        except json.JSONDecodeError:
            appeared = False
        if appeared:
            break
        if time.monotonic() >= deadline:
            return "none"
        time.sleep(CHECKS_POLL)
    watched = gh(worktree, "pr", "checks", url, "--watch", "--fail-fast")
    return "pass" if watched.returncode == 0 else "fail"


def ci_failure_log(worktree: Path) -> str:
    sha = git(worktree, "rev-parse", "HEAD").strip()
    listed = gh(
        worktree, "run", "list", "--commit", sha, "--json", "databaseId,conclusion"
    )
    try:
        runs = json.loads(listed.stdout or "[]")
    except json.JSONDecodeError:
        runs = []
    failed = [r for r in runs if r.get("conclusion") == "failure"] or runs
    if not failed:
        return "(no failed run log found)"
    log = gh(worktree, "run", "view", str(failed[0]["databaseId"]), "--log-failed")
    return (log.stdout + log.stderr)[-CI_LOG_LIMIT:]


def merge(run: Run, worktree: Path) -> None:
    # --repo stops gh from deleting or switching local branches: it would try
    # to check out main inside the worktree. ship.py cleans up locally itself.
    slug = re.match(r"https?://[^/]+/([^/]+/[^/]+)/pull/\d+", run.pr_url)
    if not slug:
        raise Stop(NEEDS_ME, f"cannot read the repository from {run.pr_url}")
    gh(
        worktree,
        "pr",
        "merge",
        run.pr_url,
        "--merge",
        "--delete-branch",
        "--repo",
        slug[1],
    )
    view = gh(worktree, "pr", "view", run.pr_url, "--json", "state,mergeCommit")
    try:
        info = json.loads(view.stdout)
    except json.JSONDecodeError:
        info = {}
    if info.get("state") != "MERGED":
        raise Stop(
            NEEDS_ME, f"PR is not merged: {view.stdout.strip() or view.stderr.strip()}"
        )
    run.merge_sha = (info.get("mergeCommit") or {}).get("oid", "")


def clean_up(run: Run, root: Path, worktree: Path, stamp: str) -> None:
    """Keep the logs, remove the worktree and delete the merged local branch."""
    logs = SHIP_DIR / f"{run.name}-{stamp}-logs"
    if (worktree / ".loop").exists():
        shutil.copytree(worktree / ".loop", logs, symlinks=True)
        link_logs(run.name, logs / "latest")
    git(root, "worktree", "remove", "--force", str(worktree))
    git(root, "branch", "-D", run.branch)
    run.worktree += " (removed)"


def pull_launch(launch: Path) -> None:
    on_main = git(launch, "rev-parse", "--abbrev-ref", "HEAD").strip() == BASE_BRANCH
    if on_main and not git(launch, "status", "--porcelain").strip():
        git(launch, "pull", "-q", "--ff-only")


def ship(args: argparse.Namespace, run: Run, stamp: str) -> None:
    launch = Path.cwd()
    require_safe(launch)
    root = Path(git(launch, "rev-parse", "--show-toplevel").strip())
    task = Path(args.task)
    if task.is_absolute():
        task = task.resolve().relative_to(root)
    git(root, "fetch", "-q", "origin")
    if args.mode == "task":
        worktree, created = prepare_task(root, task, run)
    else:
        worktree, created = prepare_branch(root, args.branch, run)
    run.worktree = str(worktree)
    if not (worktree / task).is_file():
        raise Stop(REFUSED, f"task file not found in {worktree}: {task}")
    task_text = (worktree / task).read_text(encoding="utf-8")
    link_logs(run.name, worktree / ".loop" / "latest")

    harness(run, args, worktree, task, review_first=args.mode == "branch")
    merge_gate(run, worktree, task_text)
    while True:
        git(worktree, "push", "-q", "-u", "origin", "HEAD")
        publish_pr(run, worktree, task_text)
        run.ci = wait_for_ci(worktree, run.pr_url)
        if run.ci == "pass":
            break
        if run.ci == "none":
            raise Stop(NEEDS_ME, f"no CI checks appeared within {CHECKS_TIMEOUT}s")
        if run.loops >= args.loops:
            raise Stop(NEEDS_ME, "CI failed and no loops remain")
        feedback = SHIP_DIR / f"{run.name}-{stamp}-ci.txt"
        log = ci_failure_log(worktree)
        feedback.write_text(f"CI failed. Must fix:\n\n{log}\n", encoding="utf-8")
        harness(run, args, worktree, task, feedback=feedback)
        merge_gate(run, worktree, task_text)

    if args.no_merge:
        return
    merge(run, worktree)
    pull_launch(launch)
    if created:
        clean_up(run, root, worktree, stamp)


def write_summary(run: Run, stamp: str) -> Path | None:
    path = SHIP_DIR / f"{run.name}-{stamp}.json"
    try:
        SHIP_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(run), indent=2), encoding="utf-8")
    except OSError as error:
        print(f"could not write the summary to {path}: {error}", file=sys.stderr)
        return None
    return path


OUTCOMES = {MERGED: "done", REFUSED: "refused", NEEDS_ME: "needs you", BUDGET: "budget"}


def print_summary(run: Run, path: Path | None, no_merge: bool) -> None:
    gate = ", ".join(f"{k} {'ok' if v['ok'] else 'FAIL'}" for k, v in run.gate.items())
    done = "approved, not merged (--no-merge)" if no_merge else "merged"
    outcome = done if run.exit_code == MERGED else OUTCOMES.get(run.exit_code, "?")
    lines = [
        f"\nship {run.name}: exit {run.exit_code} ({outcome})",
        f"  mode:      {run.mode}",
        f"  branch:    {run.branch or '-'}",
        f"  worktree:  {run.worktree or '-'}",
        f"  PR:        {run.pr_url or '-'}",
        f"  loops:     {run.loops}",
        f"  cost:      ${run.cost_usd:.4f}",
        f"  verdict:   {run.verdict or '-'} ({len(run.checked)} checked)",
        f"  gate:      {gate or '-'}",
        f"  CI:        {run.ci or '-'}",
        f"  merge SHA: {run.merge_sha or '-'}",
        f"  summary:   {path or '-'}",
    ]
    if run.reason:
        lines.append(f"  reason:    {run.reason}")
    print("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    run = Run(mode=args.mode, name=Path(args.task).stem)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    try:
        ship(args, run, stamp)
    except Stop as stop:
        run.exit_code, run.reason = stop.code, stop.reason
        print(stop.reason, file=sys.stderr)
    print_summary(run, write_summary(run, stamp), args.no_merge)
    return run.exit_code


if __name__ == "__main__":
    sys.exit(main())
