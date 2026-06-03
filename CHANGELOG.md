# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/), and the project
aims to adhere to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Test harness (`tests/conftest.py`) with fakes (LLM, embedder), a tmp object store,
  sample fixtures, and an integration `api_client`.
- Contract tests: Markdown-canonical invariant, dependency/lazy-import contract,
  repo hygiene (no secrets, English sources), and positioning docs.
- Pluggable-extractor optional dependencies as `pyproject` extras
  (`docling`, `marker`, `azure`, `aws`, `gcp`, `local`, `cohere`, `all`).
- GitHub Actions CI: ruff lint, unit/contract tests, integration tests (Postgres
  service), and Docker image builds.
- Project hygiene: `CONTRIBUTING.md` (TDD workflow), `SECURITY.md`, issue/PR templates.
- `STORAGE_DIR` documented; object-store location made explicit (logged at startup).

### Changed
- README/PRODUCT positioning sharpened: structure-first / RAG-optional,
  Markdown-canonical, and a "Tome vs. assembling your own stack" comparison.

### Sprint 1 — Extraction fidelity & local-first
- Migrated the gateway to a FastAPI `lifespan` handler (no deprecated `on_event`)
  and close the DB pool cleanly on shutdown; `GET /` no longer advertises an
  unmounted `/ui`. Tightened ruff (now flags unused imports).
- Docling is first-class: verified it emits faithful GFM Markdown (tables, reading
  order, figures); added contract + gated real-PDF tests.
- Extractor catalog with **verified / experimental** status + required extra,
  exposed via `GET /v1/extractors`; clear errors for unconfigured adapters.
- Local-first embedders: `hash` (deterministic, zero-dependency, offline) and
  `fastembed` (light ONNX) — hybrid search now works with **no cloud keys**.
- Verified the hybrid path end-to-end: embeddings → HNSW → ANN, RRF fusion,
  pluggable reranker.
- `docker-compose.local.yml` zero-egress overlay (Tika + local embedder + optional
  Ollama) and docs.

### Sprint 2 — Security hardening
- **MCP fail-closed**: binds to localhost unless `MCPO_API_KEY` is set or `TOME_OPEN=true`
  (`mcp_server.launch`); no unauthenticated write tools exposed by default.
- **Webhooks**: HMAC-SHA256 signing (`X-Tome-Signature`) + SSRF protection
  (private/loopback/link-local/metadata IPs and non-http(s) blocked; optional allowlist).
- **Rate limiting** (token bucket → 429) and an **upload size cap** (→ 413).
- **Secure-by-default audit**: surfaces empty `TOME_SECRET` / default Postgres/MinIO
  credentials; `TOME_STRICT=true` refuses to start on insecure config.
- **Security test matrix**: RBAC scope enforcement (viewer/editor/admin), plus webhook
  signing/SSRF, rate-limit, and audit unit tests.
- CI: `ci-canary/**` + `workflow_dispatch` triggers and a nightly `extras` job that
  runs the gated Docling/fastembed/reranker tests for real.
- Surfaced `extract_confidence` on the document detail endpoint.

### Branding & docs
- Added the Tome logo (`assets/logo.svg` + PNGs, `webui/public/favicon.*`), wired the
  favicon/apple-touch icon into the Library UI and used the mark in the UI header/login.
- Polished the README (centered logo header, badges, highlights) for a production look.

