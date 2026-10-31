---
name: Agent task
about: A task an agent can plan. Same sections as tasks/TEMPLATE.md.
title: "Task: "
# No labels here on purpose. Adding the `agent-plan` label is a deliberate
# step by someone with write access; it is what starts the planner.
labels: []
---

<!--
Fill in each section. Write it as if a stranger will read it: the planner sees
this issue text and the repository, nothing else. Read AGENTS.md first; tasks
outside the current scope (v1: M3, M4, M5, then M2) will be sent back.
-->

## Goal

One or two sentences: what should be true when this is done, and why.

## In scope

- Files or modules that may change.
- Behaviour to add or change.

## Out of scope

- What must not be touched, even if it looks related.

## Done when

Numbered, each one checkable by reading code or running a command, with no paid API calls.

1. ...
2. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass.
