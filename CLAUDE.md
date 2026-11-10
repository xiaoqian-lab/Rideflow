# CLAUDE.md

Guidance for Claude Code working in this repository.

## Working agreement

- **Never run git write operations** (`git add`, `git commit`, `git push`, `git tag`, branch changes). The user makes their own commits; Claude edits files only and leaves git state to the user.
- Implementation is **test-first** (TDD red→green), testing at the seams named in the Testing Decisions section of `docs/spec.md`.

## What this is

Rideflow — a personal, single-user, agent-driven long-distance cycling planner. The MVP turns a natural-language trip intent into a day-by-day route skeleton.

## Read before implementing

- `docs/spec.md` — the build-ready spec: product decisions, data model, testing seams.
- `docs/tickets/` — implementation tickets (tracer bullets, numbered in dependency order); work the frontier.
- `docs/wayfinder/map.md` — decision map and the rationale behind decisions; consult when a "why" is in question.

## Toolchain

- Python 3.12, managed with **uv** (venv in `.venv`).
- Backend: FastAPI + SQLite, package `rideflow/`; tests in `tests/`.

## Commands

- `uv run python -m pytest` — run tests.
- `uv run uvicorn rideflow.main:app --reload` — run the API locally.

