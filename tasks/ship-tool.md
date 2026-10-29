# Task: ship tool

## Goal

One command takes a task from a task file (or an existing branch) to a merged PR: builder and reviewer loop until the reviewer approves, a merge gate is checked in code, CI must pass, and the run is visible in Herdr.

## In scope

- `scripts/build_review.py`: add `--review-first`, `--base-ref` and `--feedback`.
- `scripts/ship.py`: new; task and branch modes, guard, merge gate, PR, CI loop, merge, summary.
- `scripts/ship-herdr.sh`: new; Herdr workspace with three panes, `--print`, fallback without Herdr.
- `tests/test_build_review.py`, `tests/test_ship.py`: tests with fake `gh` and `claude`, no network.
- `docs/harness-plan.md`: a "Ship" section.
- `tasks/ship-tool.md`: this file.

## Out of scope

- Any other file, including `pyproject.toml`, `uv.lock`, `.github/`, `harness/`, `prompts/` and `src/`.
- New dependencies.

## Acceptance criteria

1. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest -q` pass; report the test count (it should be 172 plus the new tests).
2. tests/test_ship.py covers every case in item 4, and all of them pass.
   Item 4's cases: the guard refuses /mnt paths and paths not on ext4 (stat mocked); task mode creates the branch and worktree, and refuses a task file not on origin/main; branch mode reuses an existing worktree and merges origin/main first, stopping on a conflict; the scope gate rejects an out-of-scope file and an unlisted protected path; the secret scan rejects each pattern; approval plus green CI merges, `--no-merge` doesn't; failing CI sends the failure to the builder and loops; exit codes match; `ship-herdr.sh --print` prints the expected herdr commands.
3. `bash scripts/ship-herdr.sh --print task tasks/ship-tool.md` prints a workspace with three panes and the commands for each.
4. `uv run python scripts/ship.py task tasks/ship-tool.md --no-merge`, run from /mnt/c, exits 2 with the guard message (show it).
5. The diff touches only scripts/build_review.py, scripts/ship.py, scripts/ship-herdr.sh, tests/test_build_review.py, tests/test_ship.py, docs/harness-plan.md and tasks/ship-tool.md.
6. No new dependency in pyproject.toml or uv.lock.
