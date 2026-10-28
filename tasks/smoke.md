# Task: smoke test the harness

## Goal

Check that the build → review harness works end to end with a trivial change.

## In scope

- `src/alteram/__init__.py`: add a one-line module docstring.

## Out of scope

- Every other file.
- Any other change to `src/alteram/__init__.py`.

## Acceptance criteria

1. `src/alteram/__init__.py` starts with a module docstring that is a single line and describes the package (Alteram, AI adjudication of small disputes).
2. Nothing else in `src/alteram/__init__.py` changed, and no other file changed.
3. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass.
