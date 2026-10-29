"""Ship tests: temporary git repos with a bare origin, a fake gh and a fake
claude. No network, no real gh or claude."""

import importlib.util
import json
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from test_build_review import APPROVE, CHANGES, FAKE_CLAUDE, PASS

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

# Plays a scripted CI: state["ci"] lists one outcome per push ("pass", "fail"
# or "none"). Each call's argv is appended to gh_calls.jsonl.
FAKE_GH = r"""
import json, sys
from pathlib import Path

here = Path(__file__).parent
state_path = here / "gh.json"
state = json.loads(state_path.read_text())
argv = sys.argv[1:]
with (here / "gh_calls.jsonl").open("a") as f:
    f.write(json.dumps(argv) + "\n")


def save():
    state_path.write_text(json.dumps(state))


def flag(name):
    return argv[argv.index(name) + 1]


ci = state["ci"][min(state["ci_round"], len(state["ci"]) - 1)]
cmd = argv[:2]
if cmd == ["pr", "view"]:
    target = argv[2]
    if "state" in flag("--json"):
        merged = target in state["merged"]
        commit = {"oid": "f00d"} if merged else None
        print(json.dumps({"state": "MERGED" if merged else "OPEN",
                          "mergeCommit": commit}))
    elif target in state["prs"]:
        print(json.dumps({"url": state["prs"][target]}))
    else:
        print("no pull requests found", file=sys.stderr)
        sys.exit(1)
elif cmd == ["pr", "create"]:
    url = f"https://github.com/test/repo/pull/{len(state['prs']) + 1}"
    state["prs"][flag("--head")] = url
    state["bodies"].append(Path(flag("--body-file")).read_text())
    save()
    print(url)
elif cmd == ["pr", "comment"]:
    state["bodies"].append(Path(flag("--body-file")).read_text())
    save()
elif cmd == ["pr", "checks"]:
    if "--watch" in argv:
        state["ci_round"] += 1
        save()
        sys.exit(0 if ci == "pass" else 1)
    if ci == "none":
        print("no checks reported", file=sys.stderr)
        sys.exit(1)
    print(json.dumps([{"name": "test", "bucket": "pending"}]))
    sys.exit(8)
elif cmd == ["run", "list"]:
    print(json.dumps([{"databaseId": 42, "conclusion": "failure"}]))
elif cmd == ["run", "view"]:
    print("x" * 5000 + "\nFAILED tests/test_x.py::test_y - AssertionError")
elif cmd == ["pr", "merge"]:
    state["merged"].append(argv[2])
    save()
else:
    print(f"fake gh: unknown command {argv}", file=sys.stderr)
    sys.exit(2)
"""

TASK = """# Task: demo

## Goal

Write work.txt.

## In scope

- `work.txt`
- `fix.txt`

## Out of scope

- `other.txt` and everything else.

## Acceptance criteria

1. `work.txt` exists.
"""


@dataclass
class Env:
    launch: Path
    origin: Path
    projects: Path
    fake: Path


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


def commit(repo: Path, files: dict[str, str], message: str) -> None:
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def ship(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    spec = importlib.util.spec_from_file_location("ship", SCRIPTS / "ship.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def command(script: Path) -> str:
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ship: ModuleType) -> Env:
    """A launching checkout on main under projects/, a bare origin, fakes."""
    for var in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{var}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{var}_EMAIL", "test@example.com")
    projects = tmp_path / "projects"
    origin = tmp_path / "origin.git"
    launch = projects / "alteram"
    launch.mkdir(parents=True)
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(launch, "init", "-q", "-b", "main")
    commit(launch, {".gitignore": ".loop/\n", "tasks/demo.md": TASK}, "init")
    git(launch, "remote", "add", "origin", str(origin))
    git(launch, "push", "-q", "-u", "origin", "main")

    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "claude.py").write_text(FAKE_CLAUDE)
    (fake / "gh.py").write_text(FAKE_GH)
    monkeypatch.setenv(ship.br.CLAUDE_BIN_ENV, command(fake / "claude.py"))
    monkeypatch.setenv(ship.GH_BIN_ENV, command(fake / "gh.py"))
    monkeypatch.setattr(ship, "PROJECTS", projects)
    monkeypatch.setattr(ship, "WORKTREES", projects / "alteram-wt")
    monkeypatch.setattr(ship, "SHIP_DIR", projects / ".ship")
    monkeypatch.setattr(ship, "fs_type", lambda path: "ext2/ext3")
    monkeypatch.setattr(ship, "CHECKS_TIMEOUT", 0)
    monkeypatch.setattr(ship, "CHECKS_POLL", 0)
    monkeypatch.setattr(ship.br, "GATE", PASS)
    monkeypatch.chdir(launch)
    result = Env(launch, origin, projects, fake)
    script(result, [{"write": ["work.txt"]}], [{"structured_output": APPROVE}])
    set_ci(result, ["pass"])
    return result


def script(env: Env, builder: list[dict[str, Any]], reviewer: list[dict]) -> None:
    (env.fake / "script.json").write_text(
        json.dumps({"builder": builder, "reviewer": reviewer})
    )


def set_ci(env: Env, rounds: list[str], prs: dict[str, str] | None = None) -> None:
    state = {"ci": rounds, "ci_round": 0, "prs": prs or {}, "merged": []}
    (env.fake / "gh.json").write_text(json.dumps({**state, "bodies": []}))


def gh_state(env: Env) -> dict[str, Any]:
    return json.loads((env.fake / "gh.json").read_text())


def gh_calls(env: Env, *prefix: str) -> list[list[str]]:
    path = env.fake / "gh_calls.jsonl"
    if not path.exists():
        return []
    found = [json.loads(line) for line in path.read_text().splitlines()]
    return [c for c in found if c[: len(prefix)] == list(prefix)]


def claude_calls(env: Env, role: str) -> list[dict[str, Any]]:
    path = env.fake / "calls.jsonl"
    if not path.exists():
        return []
    found = [json.loads(line) for line in path.read_text().splitlines()]
    return [c for c in found if c["role"] == role]


def summary(env: Env) -> dict[str, Any]:
    (path,) = (env.projects / ".ship").glob("demo-*Z.json")
    return json.loads(path.read_text())


def remote_head(env: Env, branch: str) -> str:
    return git(env.origin, "ls-remote", str(env.origin), f"refs/heads/{branch}")


def worktree_on(env: Env, branch: str, path: Path) -> Path:
    git(env.launch, "worktree", "add", "-q", "-b", branch, str(path), "main")
    return path


# Guard


def test_guard_refuses_mnt_paths(ship: ModuleType, monkeypatch: pytest.MonkeyPatch):
    def no_stat(path: Path) -> str:
        raise AssertionError("a /mnt path must be refused before any stat")

    monkeypatch.setattr(ship, "fs_type", no_stat)
    # Refused as /mnt even if the projects folder itself were under /mnt.
    monkeypatch.setattr(ship, "PROJECTS", Path("/mnt/c/Users/someone/projects"))
    reason = ship.guard(Path("/mnt/c/Users/someone/projects/alteram"))
    assert reason and "Windows filesystem" in reason


def test_guard_refuses_paths_outside_projects(env: Env, ship: ModuleType) -> None:
    reason = ship.guard(env.projects.parent / "elsewhere")
    assert reason and "not under" in reason


def test_guard_refuses_paths_not_on_ext4(
    env: Env, ship: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ship, "fs_type", lambda path: "v9fs")
    assert ship.main(["task", "tasks/demo.md"]) == 2
    assert "not ext4" in summary(env)["reason"]
    assert not (env.projects / "alteram-wt").exists()
    assert claude_calls(env, "builder") == []


def test_guard_accepts_ext4_under_projects(env: Env, ship: ModuleType) -> None:
    assert ship.guard(env.launch) is None


# Task mode


def test_task_mode_creates_branch_and_worktree(env: Env, ship: ModuleType) -> None:
    assert ship.main(["task", "tasks/demo.md", "--no-merge"]) == 0
    worktree = env.projects / "alteram-wt" / "demo"
    assert git(worktree, "branch", "--show-current").strip() == "task/demo"
    assert git(env.launch, "branch", "--show-current").strip() == "main"
    link = env.projects / ".ship" / "demo"
    assert link.is_symlink()
    assert link.resolve() == (worktree / ".loop" / "latest").resolve()
    assert (link / "builder.log").exists()
    head = git(worktree, "rev-parse", "HEAD").strip()
    assert remote_head(env, "task/demo").startswith(head)
    (create,) = gh_calls(env, "pr", "create")
    assert create[create.index("--title") + 1] == "demo"
    body = gh_state(env)["bodies"][0]
    assert "# Task: demo" in body
    assert "criterion 1: read work.txt" in body
    assert "Loops used: 1" in body


def test_task_mode_refuses_task_not_on_origin_main(env: Env, ship: ModuleType) -> None:
    commit(env.launch, {"tasks/local.md": TASK}, "local only")
    assert ship.main(["task", "tasks/local.md"]) == 2
    assert not (env.projects / "alteram-wt" / "local").exists()
    assert claude_calls(env, "builder") == []


def test_task_mode_refuses_existing_branch(env: Env, ship: ModuleType) -> None:
    git(env.launch, "branch", "task/demo")
    assert ship.main(["task", "tasks/demo.md"]) == 2


# Branch mode


def test_branch_mode_reuses_worktree_and_merges_origin_main(
    env: Env, ship: ModuleType
) -> None:
    feature = worktree_on(env, "feature/x", env.projects / "feature-wt")
    commit(feature, {"work.txt": "done\n"}, "work")
    commit(env.launch, {"main.txt": "new on main\n"}, "main moves on")
    git(env.launch, "push", "-q", "origin", "main")

    args = ["branch", "feature/x", "--task", "tasks/demo.md", "--no-merge"]
    assert ship.main(args) == 0
    assert not (env.projects / "alteram-wt").exists()
    git(feature, "merge-base", "--is-ancestor", "origin/main", "HEAD")
    # Review first: the reviewer approved the existing diff, so no builder call.
    assert claude_calls(env, "builder") == []
    stdin = claude_calls(env, "reviewer")[0]["stdin"]
    assert "work.txt" in stdin
    assert "main.txt" not in stdin
    assert summary(env)["worktree"] == str(feature)


def test_branch_mode_creates_worktree_when_none(env: Env, ship: ModuleType) -> None:
    git(env.launch, "branch", "feature/y")
    script(
        env,
        [{"write": ["work.txt"]}],
        [{"structured_output": CHANGES}, {"structured_output": APPROVE}],
    )
    args = ["branch", "feature/y", "--task", "tasks/demo.md", "--no-merge"]
    assert ship.main(args) == 0
    worktree = env.projects / "alteram-wt" / "feature-y"
    assert git(worktree, "branch", "--show-current").strip() == "feature/y"
    assert len(claude_calls(env, "builder")) == 1


def test_branch_mode_stops_on_merge_conflict(env: Env, ship: ModuleType) -> None:
    feature = worktree_on(env, "feature/x", env.projects / "feature-wt")
    commit(feature, {"work.txt": "branch version\n"}, "branch")
    commit(env.launch, {"work.txt": "main version\n"}, "main")
    git(env.launch, "push", "-q", "origin", "main")

    assert ship.main(["branch", "feature/x", "--task", "tasks/demo.md"]) == 3
    assert "conflict" in summary(env)["reason"]
    assert git(feature, "status", "--porcelain") == ""
    assert claude_calls(env, "reviewer") == []


# Merge gate


def test_scope_gate_rejects_out_of_scope_file(env: Env, ship: ModuleType) -> None:
    script(
        env, [{"write": ["work.txt", "other.txt"]}], [{"structured_output": APPROVE}]
    )
    assert ship.main(["task", "tasks/demo.md"]) == 3
    gate = summary(env)["gate"]
    assert gate["scope"]["ok"] is False
    assert any("other.txt" in p for p in gate["scope"]["problems"])
    assert remote_head(env, "task/demo") == ""
    assert gh_calls(env, "pr") == []


def test_in_scope_patterns_reads_only_that_section(ship: ModuleType) -> None:
    assert ship.in_scope_patterns(TASK) == ["work.txt", "fix.txt"]
    text = "## In scope\n\n- `src/*.py`, `docs/`, and run `uv run pytest`\n"
    assert ship.in_scope_patterns(text) == ["src/*.py", "docs/"]


@pytest.mark.parametrize(
    ("path", "patterns", "ok"),
    [
        ("src/a.py", ["src/*.py"], True),
        ("src/a.py", ["src/"], True),
        ("src/a.py", ["docs/*"], False),
        ("README.md", [], False),
    ],
)
def test_scope_problems(ship: ModuleType, path: str, patterns: list, ok: bool):
    assert (ship.scope_problems([path], patterns) == []) is ok


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "config/.env.local",
        ".claude/settings.json",
        ".github/workflows/ci.yml",
        "prompts/judge.md",
        "cases/case-001.md",
        "pyproject.toml",
        "uv.lock",
    ],
)
def test_scope_gate_rejects_protected_path_not_listed(ship: ModuleType, path: str):
    # A glob that covers the path is not an explicit listing.
    assert ship.scope_problems([path], ["*", "**/*"]) == []
    assert ship.protected_problems([path], ["*", "**/*", ".*"])
    assert ship.protected_problems([path], [path]) == []


def test_protected_directory_named_explicitly(ship: ModuleType) -> None:
    assert ship.protected_problems(["prompts/judge.md"], ["prompts/"]) == []


SECRETS = [
    "sk-" + "ant-api03-abcdef",
    "lsv2" + "_pt_abcdef",
    "ghp" + "_abcdef",
    "github" + "_pat_abcdef",
    "-----" + "BEGIN OPENSSH PRIVATE KEY-----",
    "ANTHROPIC_API_" + "KEY=" + "a" * 16,
    "GH_" + "TOKEN = '" + "b" * 20 + "'",
]


@pytest.mark.parametrize("secret", SECRETS)
def test_secret_scan_rejects_each_pattern(ship: ModuleType, secret: str) -> None:
    diff = f"diff --git a/app.py b/app.py\n+++ b/app.py\n+x = 1\n+{secret}\n"
    problems = ship.secret_problems(diff)
    assert len(problems) == 1
    assert problems[0].startswith("app.py:")
    assert secret not in problems[0]


def test_secret_scan_ignores_short_values_and_removed_lines(ship: ModuleType):
    diff = (
        "+++ b/app.py\n"
        f"+API_{'KEY'}=short\n"
        f"-{SECRETS[0]}\n"
        "+ANTHROPIC_API_KEY=\n"
        "+key = os.environ['ANTHROPIC_API_KEY']\n"
    )
    assert ship.secret_problems(diff) == []


def test_secret_in_branch_stops_before_push(env: Env, ship: ModuleType) -> None:
    feature = worktree_on(env, "feature/s", env.projects / "feature-wt")
    commit(feature, {"work.txt": SECRETS[0] + "\n"}, "oops")
    args = ["branch", "feature/s", "--task", "tasks/demo.md", "--no-merge"]
    assert ship.main(args) == 3
    assert summary(env)["gate"]["secrets"]["ok"] is False
    assert remote_head(env, "feature/s") == ""


# Reviewer, CI and merge


def test_approval_and_green_ci_merges(env: Env, ship: ModuleType) -> None:
    assert ship.main(["task", "tasks/demo.md"]) == 0
    (merge,) = gh_calls(env, "pr", "merge")
    assert {"--merge", "--delete-branch"} <= set(merge)
    assert merge[merge.index("--repo") + 1] == "test/repo"
    result = summary(env)
    assert result["merge_sha"] == "f00d"
    assert result["ci"] == "pass"
    assert result["exit_code"] == 0
    # ship.py created the worktree, so it removes it but keeps the logs.
    assert not (env.projects / "alteram-wt" / "demo").exists()
    assert git(env.launch, "branch", "--list", "task/demo") == ""
    assert (env.projects / ".ship" / "demo" / "builder.log").exists()


def test_no_merge_does_not_merge(env: Env, ship: ModuleType) -> None:
    assert ship.main(["task", "tasks/demo.md", "--no-merge"]) == 0
    assert gh_calls(env, "pr", "merge") == []
    assert (env.projects / "alteram-wt" / "demo").exists()
    assert summary(env)["merge_sha"] == ""


def test_reused_worktree_is_kept_after_merge(env: Env, ship: ModuleType) -> None:
    feature = worktree_on(env, "feature/x", env.projects / "feature-wt")
    commit(feature, {"work.txt": "done\n"}, "work")
    assert ship.main(["branch", "feature/x", "--task", "tasks/demo.md"]) == 0
    assert feature.exists()
    assert gh_calls(env, "pr", "merge")


def test_failing_ci_sends_failure_to_builder_and_loops(
    env: Env, ship: ModuleType
) -> None:
    set_ci(env, ["fail", "pass"])
    script(
        env,
        [{"write": ["work.txt"]}, {"write": ["fix.txt"]}],
        [{"structured_output": APPROVE}],
    )
    assert ship.main(["task", "tasks/demo.md", "--no-merge"]) == 0
    builder = claude_calls(env, "builder")
    assert len(builder) == 2
    assert "FAILED tests/test_x.py::test_y" in builder[1]["stdin"]
    assert "x" * 4001 not in builder[1]["stdin"]
    assert len(claude_calls(env, "reviewer")) == 2
    worktree = env.projects / "alteram-wt" / "demo"
    head = git(worktree, "rev-parse", "HEAD").strip()
    assert remote_head(env, "task/demo").startswith(head)
    # One PR, then a comment for the second push.
    assert len(gh_calls(env, "pr", "create")) == 1
    assert len(gh_calls(env, "pr", "comment")) == 1
    assert summary(env)["loops"] == 2


def test_failing_ci_with_no_loops_left_exits_3(env: Env, ship: ModuleType) -> None:
    set_ci(env, ["fail"])
    assert ship.main(["task", "tasks/demo.md", "--loops", "1"]) == 3
    assert "no loops remain" in summary(env)["reason"]
    assert len(claude_calls(env, "builder")) == 1


def test_no_checks_exits_3(env: Env, ship: ModuleType) -> None:
    set_ci(env, ["none"])
    assert ship.main(["task", "tasks/demo.md"]) == 3
    assert "no CI checks" in summary(env)["reason"]
    assert gh_calls(env, "pr", "merge") == []


def test_reviewer_changes_exits_3(env: Env, ship: ModuleType) -> None:
    script(env, [{"write": ["work.txt"]}], [{"structured_output": CHANGES}])
    assert ship.main(["task", "tasks/demo.md", "--loops", "2"]) == 3
    assert summary(env)["verdict"] == "changes"
    assert remote_head(env, "task/demo") == ""


def test_budget_reached_exits_4(env: Env, ship: ModuleType) -> None:
    script(
        env,
        [{"write": ["work.txt"], "cost": 0.6}],
        [{"structured_output": CHANGES, "cost": 0.5}],
    )
    assert ship.main(["task", "tasks/demo.md", "--budget", "1"]) == 4
    assert summary(env)["cost_usd"] == pytest.approx(1.1)


def test_existing_pr_gets_a_comment(env: Env, ship: ModuleType) -> None:
    url = "https://github.com/test/repo/pull/7"
    set_ci(env, ["pass"], prs={"task/demo": url})
    assert ship.main(["task", "tasks/demo.md", "--no-merge"]) == 0
    assert gh_calls(env, "pr", "create") == []
    (comment,) = gh_calls(env, "pr", "comment")
    assert comment[2] == url
    assert "criterion 1: read work.txt" in gh_state(env)["bodies"][0]


def test_summary_records_the_run(env: Env, ship: ModuleType) -> None:
    ship.main(["task", "tasks/demo.md", "--no-merge"])
    result = summary(env)
    assert result["mode"] == "task"
    assert result["branch"] == "task/demo"
    assert result["pr_url"] == "https://github.com/test/repo/pull/1"
    assert result["verdict"] == "approve"
    assert all(v["ok"] for v in result["gate"].values())


# ship-herdr.sh


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.parametrize(
    "args",
    [
        ["task", "tasks/ship-tool.md", "--no-merge"],
        ["branch", "tooling/ship", "--task", "tasks/ship-tool.md"],
    ],
)
def test_ship_herdr_print(tmp_path: Path, args: list[str]) -> None:
    done = subprocess.run(
        ["bash", str(SCRIPTS / "ship-herdr.sh"), "--print", *args],
        capture_output=True,
        text=True,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert done.returncode == 0, done.stderr
    out = done.stdout
    ship_dir = f"{tmp_path}/projects/.ship/ship-tool"
    assert out.count("herdr workspace create") == 1
    assert '--label "ship ship-tool"' in out
    assert out.count("herdr pane split") == 2
    assert "--direction right" in out
    assert "--direction down" in out
    assert out.count("herdr pane run") == 3
    assert f"uv run python scripts/ship.py {' '.join(args)}" in out
    assert f"tail -F {ship_dir}/builder.log" in out
    assert f"tail -F {ship_dir}/reviewer.log" in out
