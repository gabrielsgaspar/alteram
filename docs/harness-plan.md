# Build → review harness: plan

_Proposed 27 October 2026. Not built yet. It is item 4 in the brief's post-v0 list, brought forward as tooling for all later coding work._

## Goal

Hand a coding task to an automatic loop: a **builder** agent implements it, code runs the tests, a **reviewer** agent checks the result against the task, and the builder fixes what the reviewer found. This repeats up to N times, or until the reviewer approves. Gabriel watches it in three panes and stays the only one who merges.

## Layout (Herdr, one tab, three panes)

```
┌──────────────────────┬──────────────────────┐
│                      │  2. Builder          │
│  1. Your shell       │  (live builder log)  │
│  (run the loop,      ├──────────────────────┤
│   git, tests)        │  3. Reviewer         │
│                      │  (live reviewer log) │
└──────────────────────┴──────────────────────┘
```

Herdr (herdr.dev, v0.9.x, native Windows supported) gives the panes and shows each agent's state. **The loop itself does not depend on Herdr.** Panes 2 and 3 only display log files the loop writes, so the loop works the same in a plain terminal or in CI.

## Why a script with `claude -p`, not Herdr driving interactive agents

Herdr can send prompts into interactive Claude Code panes and wait for them (`herdr pane run`, `herdr agent wait --until done`). But:

- **State detection is heuristic.** Its docs flag a race where `agent wait` can see a stale "done" before the new prompt starts.
- **An interactive pane can stop on a permission prompt** with nobody there to answer it.
- **Reading results means scraping terminal output.**
- **Herdr's API is pre-1.0 and may change.**

`claude -p` (headless Claude Code) instead gives exit codes, JSON output, a schema-checked verdict (`--json-schema`), a cost figure (`total_cost_usd`) and a spend cap (`--max-budget-usd`). That is deterministic enough to loop on. Herdr's community loop plugins (e.g. herdr-review-loop, herdr-peer-review) exist but are unverified.

## The loop

Run from pane 1: `uv run python scripts/build_review.py tasks/<task>.md --loops 3`

0. **Pre-checks.** Refuse to start on `main` or with uncommitted changes. Create `.loop/<timestamp>/` (gitignored).
1. **Builder.** Runs `claude -p` with the task file, the `AGENTS.md` rules (loaded through `CLAUDE.md` as usual) and, from loop 2 on, the reviewer's must-fix list plus any test failures.
   - Settings: `--permission-mode acceptEdits`, `--allowedTools` limited to the repo's commands (`Bash(uv run *)`, `Bash(git diff *)`, `Bash(git status *)`), `--max-budget-usd`, `--output-format stream-json --verbose`.
   - The same builder session is resumed across loops (`--resume <session_id>`), so it remembers what it did.
2. **Gate, in code rather than by a model.** The script runs `uv run ruff check .` and `uv run pytest` itself. If either fails, the output goes back to the builder and counts as a loop, and the reviewer isn't called.
3. **Reviewer.** A **fresh** `claude -p` session each loop, so it judges independently.
   - Read-only: Read, Grep, Glob, `Bash(git diff *)` and `Bash(uv run pytest *)`; no Edit or Write.
   - It gets the task file and `git diff main...HEAD` plus uncommitted changes.
   - It returns a schema-checked verdict: `{"verdict": "approve" | "changes", "must_fix": [...], "nice_to_have": [...], "checked": [...]}`.
4. **Stop on approval, or after N loops.**
   - The script prints a summary: loops used, cost, final verdict, and where the logs are.
   - It commits each loop on the branch with a message naming the loop, so every round's diff is reviewable. It never pushes and never merges.
5. **Logs.** Each agent's stream is written as readable text to `.loop/<timestamp>/builder.log` and `reviewer.log`, with the raw JSON alongside. Panes 2 and 3 run `Get-Content -Wait .loop\latest\builder.log` and `...\reviewer.log`.

## Guardrails

- **Cost:** a per-call `--max-budget-usd` and a total budget for the run. Stop when it's reached.
- **Safety:** never `main`; never push; never read `.env`. The existing `.claude/settings.json` deny rules still apply in `-p` mode. Don't use `--bare`, which skips `CLAUDE.md`/`AGENTS.md` and needs an API key instead of the Claude Code login.
- **Scope:** a task file must say what is in and out of scope and how to check the work is done (acceptance criteria). The reviewer judges against that file, not against taste.
- **Honesty:** the reviewer must say which acceptance criteria it actually checked. "Looks good" without checks is not an approval.

## Files to create

- `scripts/build_review.py`: the loop (standard library only, works on native Windows).
- `harness/builder.md`, `harness/reviewer.md`: role prompts, kept apart from Alteram's own `prompts/`.
- `harness/review_schema.json`: the verdict schema.
- `tasks/TEMPLATE.md`: goal, in scope, out of scope, acceptance criteria.
- `.gitignore`: add `.loop/`.
- Tests for the script's pure logic (argument parsing, the stop rule, reading the verdict) using a fake `claude` command; no real calls in tests.

## Claude Code prompt (phase 1 = research and plan only)

> Read AGENTS.md and docs/harness-plan.md. We're building the build→review harness it describes. **Phase 1 only:** check the current Claude Code CLI docs and confirm, with links, the flags the plan relies on: `-p`, `--output-format stream-json`/`json`, `--json-schema` and `structured_output`, `--resume` with `session_id`, `--permission-mode acceptEdits`, `--allowedTools` and `--disallowedTools` rule syntax, `--max-budget-usd`, `--permission-prompts none`, `--append-system-prompt-file`, `total_cost_usd`. Also confirm that `.claude/settings.json` deny rules apply in `-p` mode. Then show me a plan for the files listed in the doc. Don't write files until I approve. No new dependencies.

## First tasks to run through it

1. The judge reason-coverage fix: small, testable, and already specified in `docs/prompt-log.md`.
2. Step 10, GitHub Actions CI.
3. `alteram rejudge` (see `docs/IDEAS.md`).

## Open questions

- Should the builder see the reviewer's full output or only `must_fix`? Start with `must_fix` only, to avoid scope creep.
- One reviewer, or two from different model families (the brief's "reviewers → aggregator")? Start with one; add Codex later as a second reviewer.

## Ship

`scripts/ship.py` takes a task all the way to a merged PR: it runs the build → review loop in a worktree, checks a merge gate in code, pushes, opens or updates the PR, waits for CI and merges. `build_review.py` itself still never pushes or merges; `ship.py` does, and only after the gate passes.

### Usage

```bash
# New work: the task file must already be on origin/main.
uv run python scripts/ship.py task tasks/<name>.md [--loops 3] [--budget 5] [--no-merge]

# An existing branch: reviewer first, builder only if the reviewer asks for changes.
uv run python scripts/ship.py branch <branch> --task tasks/<name>.md [--loops 3] [--budget 5] [--no-merge]

# The same, in a Herdr workspace (or straight in this terminal if Herdr is not running).
bash scripts/ship-herdr.sh task tasks/<name>.md
bash scripts/ship-herdr.sh --print task tasks/<name>.md   # only print the herdr commands
```

- **task mode** creates branch `task/<name>` and worktree `~/projects/alteram-wt/<name>` from `origin/main`, then runs `build_review.py` there.
- **branch mode** uses the worktree that already has the branch checked out, or creates `~/projects/alteram-wt/<branch, sanitised>`. It first merges `origin/main` into the branch; on a conflict it aborts the merge and stops (exit 3). Then it runs `build_review.py --review-first`.
- `--loops` and `--budget` cover the whole run, including loops spent fixing CI.
- The reviewer always sees `git diff origin/main...HEAD`, the whole branch.
- `ship.py` never switches the branch of the worktree it is launched from. It removes a worktree only if it created it, after copying `.loop/` to `~/projects/.ship/<name>-<stamp>-logs/`.
- `~/projects/.ship/<name>` is a symlink to the worktree's `.loop/latest`, so log viewers can tail a fixed path. Each run writes `~/projects/.ship/<name>-<UTC stamp>.json`: mode, branch, PR URL, loops, cost, verdict, gate results, CI result, merge SHA and exit code.
- `gh` and `claude` come from `ALTERAM_GH_BIN` and `ALTERAM_CLAUDE_BIN` (defaults `gh` and `claude`); the tests substitute fakes.

### Guard

`ship.py` refuses (exit 2) if the current directory or a target worktree is under `/mnt`, is not under `~/projects/`, or is not on ext4 (`stat -f -c %T` must say `ext2/ext3`).

### Merge gate

Checked in code after every reviewer approval. All four must pass, or `ship.py` stops before pushing, says why, and exits 3:

1. The final reviewer verdict is `approve` with a non-empty `checked` list.
2. Every file in `git diff origin/main...HEAD --name-only` matches a backticked path or glob in the task file's `## In scope` section. A pattern ending in `/` is a directory.
3. No changed file is under `.env*`, `.claude/`, `.github/`, `prompts/`, `cases/`, `pyproject.toml` or `uv.lock`, unless the In-scope list names it explicitly: an exact path or directory, not a glob.
4. A secret scan of the added lines finds no Anthropic, LangSmith or GitHub token prefix, no PEM block header, and no `KEY=` or `TOKEN=` assignment with a value of 16 or more characters. It reports the file and the kind of match, never the match itself.

### CI and merge

After the gate, `ship.py` runs `git push -u origin HEAD` and creates the PR with the task file's title and a body holding the task file, the reviewer's `checked` list, the loops used and the cost. If a PR already exists, the same goes in a comment instead. It then waits for `gh pr checks --watch --fail-fast`:

- No checks within 3 minutes: exit 3.
- CI fails and loops remain: the failed log (`gh run view --log-failed`, last 4000 characters) goes to the builder as must-fix, then the gate and reviewer run again and the branch is pushed again. No loops left: exit 3.
- CI passes: unless `--no-merge`, `gh pr merge --merge --delete-branch` (with `--repo`, so gh does not touch local branches or try to check out `main` inside the worktree). Then, if the launching worktree is on `main` with a clean tree, `git pull --ff-only` there.

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Merged, or approved and green with `--no-merge` |
| 2 | Refused: guard, task file not on `origin/main`, branch or worktree already exists |
| 3 | Needs you: no approval, merge gate failed, merge conflict, CI failed or never started |
| 4 | Budget reached |

### Herdr layout

`scripts/ship-herdr.sh` takes the same arguments and creates a Herdr workspace labelled `ship <name>`:

```
┌──────────────────────┬──────────────────────────────────────────────┐
│                      │ tail -F ~/projects/.ship/<name>/builder.log  │
│  ship.py <args>      ├──────────────────────────────────────────────┤
│                      │ tail -F ~/projects/.ship/<name>/reviewer.log │
└──────────────────────┴──────────────────────────────────────────────┘
```

If `herdr` is not installed or no server is running, it says so and runs `ship.py` in the current terminal.

### Trigger from Windows

From PowerShell:

```powershell
wsl.exe -- bash -lic 'cd ~/projects/alteram && git pull --ff-only && bash scripts/ship-herdr.sh task tasks/<name>.md'
```

## GitHub flow: issue → plan comment → build PR → review comment

A second, GitHub-side entry point in three stages. `agent-plan` only plans. Once a person has read the plan, `agent-build` implements it and opens a PR. When CI passes on that PR, `agent-review` posts one advisory review comment and a label. Nothing in it approves or merges.

### Plan: agent-plan label → plan comment

1. Someone opens an issue from the **Agent task** template (`.github/ISSUE_TEMPLATE/agent-task.md`). It has the same sections as `tasks/TEMPLATE.md`: Goal, In scope, Out of scope, Done when.
2. A person with admin or write access adds the `agent-plan` label. Run `bash scripts/create_labels.sh` once to create `agent-plan`, `agent-build`, `needs-human` and `agent-approved`; it is safe to run again.
3. `.github/workflows/agent-plan.yml` runs on `issues: labeled` and nothing else. A guard step checks the repo permission of both the labelling user and the issue author first, and stops if either is not admin or write, or if the lookup fails.
4. Claude (Opus, read-only: `Read`, `Grep`, `Glob`, and `git log`) reads `AGENTS.md`, the design docs and the issue, and returns a structured result. A later step posts it as **one comment** on the issue: a plan (files, steps, risks, a "Done when" checklist that needs no paid API calls), or a plain statement that the issue is unclear or out of scope under `AGENTS.md`. Before posting, that step refuses to continue if the comment contains either token value or a `sk-ant-`, `ghp_`, `ghs_` or `github_pat_` string.

The issue text is treated as data, not instructions. Reads are fenced to the checkout: `permissions.blockReadsOutsideWorkingDirectories` is on for `Read`, `Grep` and `Glob`, and deny rules cover `/proc`, `/etc`, `/root`, `/tmp` and the runner's `/home/runner` credential and temp paths. `git diff` is not allowed, because it reads a file outside the repo when given such a path (with or without `--no-index`); use `git log -p`. `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` strips credentials from Bash subprocesses, but not from the Claude process itself. Bash deny rules are not a security boundary. The agent cannot post, edit files, or change labels or settings; a plain workflow step posts the comment with the job token (`contents: read`, `issues: write`). Because that token is `GITHUB_TOKEN`, the comment does not trigger any other workflow. The workflow only runs once it is on `main`.

### Build: agent-build label → PR

5. A person with admin or write access reads the plan and adds the `agent-build` label. `.github/workflows/agent-build.yml` runs on `issues: labeled` only and has four jobs:
   - **build**: The guard runs first, the same as in agent-plan. The job then refuses to start unless the newest `## Agent plan: ` comment by `github-actions[bot]` is a Plan, the issue has not been edited since, and branch `agent/issue-<n>` does not exist yet. Then come the same sandbox setup as agent-plan and `uv sync --locked`, both outside the sandbox. Claude (Sonnet, `claude-sonnet-5-5`) reads the issue and plan from `.agent-build/` as data and commits on `agent/issue-<n>`. Its tools are Read, Grep, Glob, and Edit/Write inside the checkout only (never `.git/`). Bash is limited to `uv sync`, `uv run ruff *`, `uv run pytest *`, `git status`, `git diff`, `git add *` and `git commit -m *`: no push, `gh`, curl or network tools. Then two plain steps check the result. The first reads Claude's structured result; it holds the token values for the leak check, so it runs no git. The second has no secrets: it refuses any nested `.git`, gitlink or `.gitmodules` change, checks that everything is committed on the branch, and hands the commits and the plan to the next job as a git bundle. A last step deletes the checkout, because `actions/checkout`'s post-job step would otherwise run git in it with the job token.
   - **verify** (no secrets, fresh checkout): Every check runs on every commit from main to the head, one at a time, not only on the net diff, because publish pushes all of them: a change made in one commit and undone in the next is still in the pushed history. A merge commit is read against its first parent. First, a secret scan of each commit: the raw commit object (author, committer, other headers, message; a commit with an `encoding` header or a NUL byte is refused, since a UTF-16 message would hide a match), every changed file name, and every added line of its patch made with `git show --text`, so neither a binary file nor a `-diff` attribute can hide content. Patterns: `sk-ant-` (Anthropic keys and Claude Code OAuth tokens), `lsv2_`, `ghp_`/`gho_`/`ghu_`/`ghs_`/`ghr_`, `github_pat_`, PEM headers (so a signed commit fails too), and long `KEY=`/`TOKEN=` values. It runs before the path check so that no step prints a file name holding a token. Then the path check: every path any commit changes must be listed under the plan's "Files to change", as an exact path or a directory ending in `/`. Files under `.github/`, `.claude/`, `prompts/` and `cases/`, `pyproject.toml` and `uv.lock`, and any `.gitattributes` need their exact file path; a directory entry never unlocks them. No file whose name starts with `.env` is allowed except `.env.example`. Gitlinks, `.gitmodules` changes and binary changes in any commit are refused. Each problem names the first commit that has it. Then `ruff check`, `ruff format --check` and `pytest`.
   - **publish**: Runs no repository code. It checks the bundle is the one verify passed, then pushes with a one-hour token from our own GitHub App (no force, hooks off). It opens a PR titled from the issue, whose body holds `Closes #<n>`, the plan's "Done when" list and a run link.
   - **report**: If any job failed after the guard passed, it posts one short comment on the issue and adds `needs-human`. A failed guard posts nothing, the same as agent-plan.
6. CI runs on the PR, because an App token, unlike `GITHUB_TOKEN`, starts workflows. When it passes, `agent-review` comments (see Review below). A person reviews and merges. To run the build again, delete the branch or close its PR, then remove and re-add the label.

Permissions per job: build `contents: read` and `issues: read`; verify and publish `contents: read`; report `issues: write`. No job has `id-token`. The App token has only contents and pull-requests write, on this repo only.

**Git in Claude's checkout.** No step that runs git, or anything else, in a checkout Claude's code has touched has a secret in its env. Every such git call runs with `-c core.fsmonitor=false -c core.hooksPath=/dev/null -c submodule.recurse=false` and ignores submodules, because a nested repo's config could otherwise run a command outside the sandbox. In agent mode `claude-code-action` runs no git after Claude exits, and its post-Claude comment step is turned off with `classify_inline_comments: "false"`.

**Cache.** Both `setup-uv` steps keep `enable-cache: false`. Issue-triggered jobs share main's cache scope, which `ci.yml` restores from, so saving a cache here could poison CI. That stops the workflow from saving one, not Claude's code: in verify, code under pytest runs unsandboxed and can reach `ACTIONS_RUNTIME_TOKEN` (see Limits), which can write a cache entry in main's scope under the key `ci.yml` restores (`enable-cache: true`). So code Claude writes can still change what a later CI run installs. `ci.yml` holds no secrets and its token is `contents: read`, so the risk is wrong CI results (a check that passes or fails when it should not), not a leak. Closing it needs a change to `ci.yml` (such as turning its cache off) or running verify's checks as an unprivileged user without sudo; neither is in this PR.

**Why not the Claude GitHub App token.** The action writes whatever token it is given into the origin URL in `.git/config`, where Claude can read it. It revokes the App token when the action step ends, and the token includes Workflows write. So Claude gets only the read-only job token, and a separate job pushes.

**What protects the OAuth token while Claude's tests run.** In build, `CLAUDE_CODE_OAUTH_TOKEN` lives in the Claude process only. `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` removes it from Bash subprocesses and runs them in their own PID namespace, so `/proc/<pid>/environ` of the Claude process is not visible (checked locally: a sandboxed shell sees only its own processes). `sandbox.credentials` also unsets it and the GitHub and Actions token variables, and hides `~/.claude/.credentials.json` and `~/.claude.json`. Read, Grep and Glob are fenced to the checkout with deny rules on `/proc` and the runner paths. Bash cannot reach `github.com` or `api.github.com`; only PyPI is open. What remains:
- a sandbox or kernel escape;
- a way to the token that these layers do not cover (the scrub is name- and value-based; the docs call it one layer, not the only control);
- data leaving through PyPI requests.

The job token Claude can see is read-only on a public repo. Anything Claude commits must still pass verify, CI and a person.

**Limits.**
- A plan that changes `.github/workflows/` will fail at push, because the App has no Workflows permission, and ends with `needs-human`.
- Bash permission rules are not a security boundary: `uv run pytest` runs whatever code Claude writes, inside the sandbox. A rule matches its text literally up to the first `*`, so `Bash(git commit -m *)` cannot stop an option after the message (`-m x -aF file`). The deny rules catch the usual spellings of `-F`, `--file`, `-t` and `--template`. Anything such a message could read, pytest code in the same sandbox could read too. What limits the damage is the sandbox, verify's per-commit scan of messages and diffs, and the person who reviews the PR.
- **Title edits after the plan may not be detected.** build compares the issue's `lastEditedAt` with the plan comment's time. That field probably tracks body edits only, not title renames, and this is unverified. The title reaches Claude (in `.agent-build/issue.md`) and becomes the PR title. If you rename an issue after its plan, run agent-plan again before adding `agent-build`. A fuller check would also look for `RENAMED_TITLE_EVENT` timeline items after the plan.
- In verify, pytest runs Claude's code outside any sandbox, on a runner with passwordless sudo. That code can usually reach `ACTIONS_RUNTIME_TOKEN` and the read-only job token. verify holds no other secrets, and deleting the checkout at the end does not change this.

**One-time setup** (repo admin): create a GitHub App with repository permissions Contents and Pull requests read and write, and nothing else. Install it on this repository only. Add its client ID as the Actions variable `AGENT_APP_CLIENT_ID` and a private key as the secret `AGENT_APP_PRIVATE_KEY`.

### Review: CI passes → review comment

7. `.github/workflows/agent-review.yml` runs on `workflow_run` when the CI workflow completes for a branch matching `agent/**`. It has two jobs, `review` and `post`. The comment is advisory: nothing in this stage approves, merges, pushes or loops back to the builder.

**Why `workflow_run` and not `pull_request`.**
- **Which file runs:** `pull_request` runs the workflow file from the PR's merge commit, so a PR (or anyone with write access who pushes to the branch) could rewrite the guard. `workflow_run` always runs the default branch's copy, and only once the file is on `main` ([events: workflow_run](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run), [securely using pull_request_target](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target)).
- **The price is secrets:** `workflow_run` "is able to access secrets and write tokens, even if the previous workflow was not", fork PRs included. That is the "pwn request" risk: a privileged workflow that checks out or downloads untrusted PR code and runs it ([Security Lab](https://securitylab.github.com/resources/github-actions-preventing-pwn-requests/), [secure use](https://docs.github.com/en/actions/reference/security/secure-use#mitigating-the-risks-of-untrusted-code-checkout)).
- **What we do about it:** the job condition and the guard keep to same-repo `agent/` branches pushed only by our App. No step checks out, builds or runs PR code, and no CI artifact or cache is used. The change reaches Claude only as a diff file from the compare API, and tests are trusted from CI's result.

**review** (`contents: read` for the merge-base checkout and the compare and activity APIs; `pull-requests: read` to find the PR; `issues: read` for the issue, plan comment and label events; `checks: read` for the `test` runs):
- **Job condition:** CI's run came from a `pull_request` event (CI also runs on `push`, so this avoids two reviews per commit), the head repository is this one, and the branch starts with `agent/`.
- **Guard first.** It fails silently, as in the other agent workflows. It checks that:
  - CI was started by `alteram-agent[bot]`, or re-run by someone with admin or write;
  - there is exactly one open PR from this same-repo branch to `main`, opened by the App, whose head is the commit CI tested. The pulls API ignores a `head` filter it does not recognise, so the match is checked locally;
  - the branch activity API shows only `push` and `branch_creation` by the App (no other pusher, no force push), and the newest push is the tested commit;
  - the branch is `agent/issue-<n>`, and the issue's author and whoever last added `agent-build` have admin or write.
- **Wait for CI.** Every `test` check run on the head commit from GitHub Actions (app 15368, the check the `protect-main` ruleset requires) must finish and pass. The step polls for up to 10 minutes, because the `push`-event run may still be going. If CI failed, Claude does not run.
- **Data**, all from the API into `.agent-review/`:
  - the issue (`issue.md`, context only);
  - the newest `## Agent plan: Plan` comment (`plan.md`), with the same edited-after check as agent-build, and it must be older than the PR;
  - its "Done when" items with ids D1, D2, … (`done-when.json`);
  - the diff of `main...<tested sha>` (`pr.diff`, at most 500 KB and fewer than 300 files);
  - CI's result (`ci.md`).
- **Path check in code**, with verify's rules: every changed path (both sides of a rename) must be under the plan's "Files to change". The checkout is the merge base (a commit on `main`), so `AGENTS.md`, `CLAUDE.md` and `.claude/settings.json` are main's and the diff applies to what Claude reads.
- **Claude** (Opus, `claude-opus-5-5`, read-only) has agent-plan's tools (`Read`, `Grep`, `Glob`, `Bash(git log *)`), Read deny rules, sandbox setup and subprocess scrub. It also gets four things from agent-build:
  - the deny on `Read(./.git/config)`;
  - the sandbox `credentials` block;
  - github.com and api.github.com denied for Bash;
  - `classify_inline_comments: "false"`.

  `allowed_bots: alteram-agent[bot]` is needed because the action refuses bot actors. It returns `{verdict, must_fix[], nice_to_have[], checked[]}`, with each `checked` entry holding an id, a status (`verified`, `not_met` or `not_verifiable_without_running_code`) and how it was checked.
- **Verdict rules, applied in code.** The path check's problems are added to `must_fix`. The result is `approve` only if the model said `approve`, `checked` has every Done when id, none is `not_met`, and `must_fix` is empty. Otherwise it is `changes`, and the comment says why it was overruled. The prompt also tells Claude to put files outside the plan and any clear correctness or quality problem in `must_fix`, even when every item is verified. `not_verifiable_without_running_code` does not block an approval; the comment shows it.
- **Secret check.** The step that builds the comment holds both token values and runs no git. It refuses the comment if either value or a token prefix (`sk-ant-`, `lsv2_`, `gh[pousr]_`, `github_pat_`, `-----BEGIN`) is in it.

**post** (`issues: write` for one comment and our labels, since PRs are issues; `pull-requests: read` to re-read the head):
- **After the review:** it posts one comment with `GITHUB_TOKEN`, as github-actions[bot]: the verdict, the reviewed commit, the Done when table, Must fix and Nice to have. It adds `agent-approved` or `needs-human` and removes the other.
- **After a failure past the guard** (CI failed, the plan or diff could not be read, an unusable result): a short "stopped" comment and `needs-human`.
- **After a failed guard on a matched PR** (for example a push by someone other than the App): it only removes `agent-approved`, with no comment.
- **Stale runs:** it skips posting if the PR has moved to a newer commit, since that commit's CI run starts its own review.

**Why `GITHUB_TOKEN` and not our App.**
- **No approval.** Creating a review needs Pull requests write and merging needs Contents write ([permissions for Apps](https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps)), and the poster has neither. The repo setting "Allow GitHub Actions to create and approve pull requests" is also off.
- **No merge.** The `protect-main` ruleset needs 0 approvals plus `test`, so any token with Contents write could merge a green agent PR. The App's token has Contents write.
- **No loops.** Events made with `GITHUB_TOKEN` start no workflows ([GITHUB_TOKEN](https://docs.github.com/en/actions/concepts/security/github_token)), so the label and comment cannot trigger anything.
- **Separate roles.** The builder and the reviewer are different identities.

**Limits.**
- **It only runs from `main`.** To try it after merging, re-run the `pull_request`-event CI run of an open agent PR.
- **Unverified:** `issues: write` alone should comment on and label a PR with `GITHUB_TOKEN`. The REST tables accept Issues *or* Pull requests write for both endpoints, but this has not been seen working yet. If it fails, the fix is `pull-requests: write`, which still cannot merge; approving stays blocked by the repo setting.
- **Prompt injection in the diff could produce an `approve`.** `agent-approved` is a signal, not a merge gate, and a person still reviews and merges.
- **Hard-coded names:** the App's bot login (`alteram-agent[bot]`) and GitHub Actions' app id (15368) are written into the workflow.
- **Activity API timing:** the guard trusts it to record a push before CI finishes. If it lags, the guard fails and nothing is posted; re-run CI.
- **The sandbox setup step is now copied in three workflows.** A shared composite action would remove the copies, but that is its own change.
- **To do: give agent-plan the same `sandbox.credentials` block and github.com / api.github.com deny as agent-build and agent-review.** It has neither today.

How it relates to the local ship tool: `ship.py` runs a builder and a reviewer and can merge. `agent-build` never merges, and `agent-review` only comments. A person reviews the PR, or locally with `scripts/ship.py branch agent/issue-<n> --task tasks/<name>.md`.
