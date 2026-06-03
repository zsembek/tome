# Contributing to Tome

Thanks for your interest in Tome! This project is built **test-first (TDD)**.

## Core invariants (please respect)
- **Markdown is canonical.** Document content, the Atlas, and agent memory are stored
  as Markdown. Postgres holds only indexes/metadata on top. Do not introduce a
  proprietary object model as the source of truth.
- **Structure-first, RAG-optional.** Retrieval is navigation over structure + BM25;
  vectors are an enhancement, never a hard dependency.
- **No lock-in.** Extractors, LLMs, and embedders stay pluggable; heavy/optional
  dependencies are lazy-imported and declared as extras in `pyproject.toml`.
- **No secrets in the repo.** Never commit real keys; `.env` is gitignored.

## TDD workflow (every change)
1. **RED** — write a failing test that encodes the requirement; run it, watch it fail.
2. Commit the test: `test: <what it checks>`.
3. **GREEN** — write the minimal code to make it pass.
4. **REFACTOR** — clean up while tests stay green.
5. Commit: `feat: …` / `fix: …`.

No feature is "done" without a test. CI is the merge gate.

## Running tests
```bash
pip install -e ".[dev]"
# fast suite (no DB, no network):
pytest -m "not integration and not e2e" -q
# integration (needs Postgres):
TOME_TEST_DSN=postgresql://postgres:postgres@localhost:5432/tome pytest -m integration -q
# lint:
ruff check .
```

### Test taxonomy (markers)
- `unit` — pure logic, fakes, no IO.
- `contract` — invariants: Markdown-canonical, provider interfaces, dependency extras, repo hygiene.
- `integration` — against a real Postgres (`TOME_TEST_DSN`, schema `tome_test`).
- `e2e` — full docker compose stack.

Use the fixtures in `tests/conftest.py` (`fake_llm`, `fake_embedder`, `tmp_store`,
`api_client`, `sample_markdown`, …) instead of hitting real services.

## Pull requests
- One focused change per PR; include tests.
- Fill in the PR checklist (test added, CI green, docs updated, no secrets).
- Conventional-commit style messages are appreciated (`feat`, `fix`, `test`, `docs`, `chore`).

## Reporting security issues
See [SECURITY.md](SECURITY.md) — please do not open public issues for vulnerabilities.
