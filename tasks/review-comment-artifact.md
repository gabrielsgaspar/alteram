# Task: pass the agent-review comment between jobs as an artifact

## Goal

agent-review's review job hands the review comment to the post job as the job output `comment`. GitHub drops any job output that may contain a masked value ("Skip output 'comment' since it may contain secret"), so post sees an empty comment and no reason. It then posts "Agent review: stopped. The run failed before it recorded a reason." and adds needs-human, although the review succeeded. This happened on PR #42 (run 41933195429, warning on the review job's step 21), and it repeats on every re-run. Our own check had already confirmed the comment holds neither token. Pass the comment as a file instead, and make the remaining failure cases say what actually happened.

## In scope

- `.github/workflows/agent-review.yml`
- `.github/workflows/agent-build.yml`
- `.github/workflows/agent-plan.yml`
- `tests/test_agent_workflows.py`
- `docs/harness-plan.md`
- `tasks/review-comment-artifact.md`

## Required behaviour

1. In agent-review, after the existing secret checks, the review job writes the comment to a file and uploads it with actions/upload-artifact, pinned to the same commit SHA agent-build already uses (cf430e030ddbb5b0abf93d22962f4752f3646cd9, v7.0.2). Use retention-days 1 and a name that includes the run attempt, so a re-run doesn't collide. The `comment` job output is removed. `verdict`, `fixable` and the other short outputs stay.
2. The post job downloads that artifact with actions/download-artifact, pinned to the SHA agent-build uses (9000827ccba6bdab643e8b6fd33ac0654aef8333, v8.0.2), into runner.temp. Before posting, it repeats the token-value and token-prefix check on the downloaded file. post still checks out no code and runs nothing from the PR.
3. If the review job succeeded with verdict approve or changes but the file is missing or empty, post says exactly that: "the review finished but its comment could not be passed to the post job", with the run link. It does not say "failed before it recorded a reason".
4. Check agent-build.yml and agent-plan.yml for any job output that carries model-written text (plans, reports, Must fix lists). If one exists, move it to the same artifact pattern. If none does, change nothing in those files and say so in the commit message.
5. tests/test_agent_workflows.py: add tests that fail if any job in the three workflows declares an output fed from model-written text, and that check the artifact steps in agent-review are pinned to the SHAs above.
6. docs/harness-plan.md: in the Review section, replace "no CI artifact or cache is used" with a sentence saying that no artifact from CI or from PR code is used, and that the only artifact is the review comment, written by this workflow's own review job in the same run. Add the failure mode to the Limits list.

## Out of scope

- Any change to guards, permissions, the round counter, prompts or the models used.
- Any other file.

## Acceptance criteria

1. agent-review.yml has no `comment` job output. The post job reads the comment only from the downloaded artifact.
2. The artifact actions are pinned to the two SHAs above.
3. The post step's secret check runs on the downloaded file before anything is posted.
4. The missing-file case posts the new wording from behaviour 3.
5. `uv run pytest tests/test_agent_workflows.py` passes, including the new tests, and the existing checks that the shared copies are equal still pass.
6. `uv run ruff check .`, `uv run ruff format --check src tests scripts` and `uv run pytest` pass.
