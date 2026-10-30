# Task: eval compare and dry-run estimate fixes

## Goal

`alteram eval compare` must compute its point estimates on the same cases as its intervals, so that b - a always matches its interval. `alteram eval --dry-run` must give a realistic cost in a fresh worktree, where there are no past run logs. Today the 4-case vs 9-case compare prints b - a = +0.056 (all cases) next to an interval of [-0.250, 0.000] (shared cases), and a fresh-worktree dry run estimated $35.53 for a run that cost $3.04.

## In scope

- `src/alteram/evaluate.py`
- `src/alteram/cli.py`
- `tests/test_evaluate.py`
- `tests/test_cli.py`
- `tasks/eval-compare-fix.md`

## Required behaviour

1. Compare, accuracy and mean confidence rows: a and b are the means of per-case values over the shared cases (in both summaries, with a value in both), the same values the paired bootstrap uses. So b - a equals the interval's point estimate. Label them "accuracy (shared, n=K)" and "mean confidence (shared, n=K)", with K the number of shared cases.
2. When the case sets differ, also print "accuracy (all cases)" and "mean confidence (all cases)" rows with each summary's overall values and b - a, and no interval. The existing case-set note says the intervals and the shared rows use shared cases only. When the case sets are the same, these rows are not printed.
3. Dry run: when any role has no past calls, and the newest summary in the baselines folder (by file name) has the same lawyer and judge models as those configured, the estimate is planned runs times that baseline's overall cost per run. The output names the baseline file and says the estimate is from a baseline. If a model is not configured, the newest baseline is still used and the output says the models are taken from it. The worst-case estimate is used only when no usable baseline exists, labelled as it is now. When every role has past calls, behaviour is unchanged.

## Out of scope

- Prompts, cases, baselines, the graph, pricing, the harness and ship scripts, docs.
- Changing how a single eval summary is computed or stored.

## Acceptance criteria

1. A test builds two summaries in the shape of the committed baselines: a has cases 001-004 with agreements 1, 1, 1/3, 1; b has cases 001-009, with 001-004 at 1, 1, 0, 1 and 005-009 at 1. The shared accuracy row shows a 0.833, b 0.750, b - a -0.083, with an interval containing -0.083. The all-cases accuracy row shows a 0.833, b 0.889, b - a 0.056, with no interval.
2. For every row with an interval, the interval's value equals b - a for that row (tested).
3. Comparing a summary with itself gives the current zero-width result and no all-cases rows (tested).
4. `uv run alteram eval compare eval/baselines/20261029T185846Z.json eval/baselines/20261029T215010Z.json` prints the shared accuracy row 0.833 / 0.750 / -0.083 with an interval that contains it, and the all-cases accuracy row 0.833 / 0.889 / 0.056.
5. A test with no past calls and a baselines folder holding a summary at $0.1125 per run gets 27 runs x $0.1125 for 9 cases at n=3, and the output names that file. A test with no past calls and no baseline still gets the worst-case estimate.
6. In a checkout with no `runs/` and no `eval/runs/` (such as this worktree), `uv run alteram eval --dry-run` estimates about $3.04 for 27 runs and names `eval/baselines/20261029T215010Z.json`.
7. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass.
