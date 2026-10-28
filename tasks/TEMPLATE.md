# Task: <short name>

Copy this file to `tasks/<name>.md`, fill it in, commit it, then run:
`uv run python scripts/build_review.py tasks/<name>.md --loops 3`

## Goal

One or two sentences: what should be true when this is done, and why.

## In scope

- Files or modules the builder may change.
- Behaviour to add or change.

## Out of scope

- What the builder must not touch, even if it looks related.

## Acceptance criteria

Numbered, each one checkable by reading code or running a command.

1. ...
2. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass.
