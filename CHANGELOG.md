# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/), and the project
aims to adhere to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Recover residual permutation-cipher garble (broken-font headers) via OCR
- Some PDFs carry TWO corrupted text layers at once: a CP1251/KOI8-R-as-Latin1 body
  (deterministically repaired by `repair_encoding`) AND a custom-font **permutation
  cipher** for section headers/titles that codepage re-decoding cannot fix. After the body
  auto-repaired, the page looked ~95% clean, so the whole-page garble check no longer fired
  and the still-garbled headers leaked into the output as junk section titles.
- New token-level detector `text_has_residual_garble` flags a page that still contains
  permutation garble after deterministic repair, so it is routed to the render+OCR
  (vision) fallback and the clean OCR result replaces it. The detector is tuned to ignore
  legitimate multi-language text — a clean Spanish/German/Polish page (México,
  Repräsentanz, SPÓLKA) and hyphenated mixed-script product names score zero garble tokens.
- Note: this recovery requires the OCR/vision fallback (`EXTRACT_FALLBACK=vision_llm`,
  default) with a vision-capable model configured; with no AI key the body is still
  repaired deterministically but permutation-only pages cannot be recovered.

### Object store: robust STORAGE_DIR + clear S3 error
- `STORAGE_DIR` is now hardened against a leaked inline comment: some `env_file`
  parsers pass `STORAGE_DIR=    # note` through verbatim, which previously made the
  store land in a junk, non-shared, non-persistent path inside the container (lost on
  recreate, not visible to other services). `LocalStore` now strips a leaked
  `# comment` and falls back to the shared `/app/_store` volume. `.env.example` keeps
  the value line clean.
- `S3_USE=true` without `boto3` installed now raises a clear, actionable `RuntimeError`
  (install the S3 extra or set `S3_USE=false`) instead of crash-looping the worker with
  a cryptic `ModuleNotFoundError`.

### Per-stage ingest metrics + higher default concurrency
- Ingestion now records wall-clock time per stage (extract / structure / name / embed /
  persist / atlas) into the job payload. Shown per file in the Processing view and
  aggregated as "Avg ingest time per stage" (last 50 docs) in Admin -> Health
  (`/v1/stats.avg_stage_ms`). Makes the real bottleneck visible instead of guessed.
- `PAGE_CONCURRENCY` default raised 4 -> 6 (faster multi-page ingest; still tunable).

### Ingestion no longer fails on NUL/control bytes
- Broken PDF text layers can contain NUL (0x00) and other C0 control bytes, which
  PostgreSQL text columns reject ("cannot contain NUL"), failing the whole import. The
  pipeline now strips them (`strip_control_chars`, keeping TAB/NEWLINE) per page during
  extraction and again in `clean()`, so such documents ingest cleanly.

### Codepage repair now actually fixes real documents (token-based + post-clean)
- `repair_encoding` is now **token-based** instead of line-based: it rewrites only the
  whitespace-delimited tokens that are dominated by accented-Latin (mojibake), so it works
  regardless of how the extractor lays out lines (a whole page on one line no longer
  defeats it) and never corrupts clean ASCII or genuinely-accented Western words.
- It is also applied to the cleaned `full_md` in the pipeline (not only per raw page),
  because the extractor's raw per-page layout could defeat detection while the cleaned
  text is reliable. Net effect: mis-decoded CP1251/KOI8-R manuals come out as correct
  Cyrillic. Verified end-to-end on a real document.

### Object store: fail loudly when not writable
- `LocalStore` now probes its directory at startup and logs a prominent ERROR (with the
  remediation command) when it isn't writable — instead of silently dropping every
  original/figure. This previously surfaced only much later as "no stored original to
  reprocess from" when the `_store` Docker volume was root-owned under the non-root
  container. (Operationally: `docker run --rm -v tome_store:/v busybox chown -R 10001:999 /v`.)

### Never fabricate over garbled text (safety)
- The structure LLM is no longer run on a garbled/mojibake text layer (custom-font
  permutation, mis-decoded codepage). Previously it would invent plausible-but-wrong
  content and write placeholders like "[unreadable]" — dangerous in a technical manual.
  Garbled pages are now kept verbatim (honest) and routed to the extractor's OCR fallback;
  the LLM still structures genuine noisy text as before.

### One-click Reprocess (apply extraction fixes to existing documents)
- New `POST /v1/documents/{id}/reprocess` and a **Reprocess** button in the document view
  re-run the current extraction pipeline on the document's stored original -- so encoding/
  mojibake/OCR fixes apply to already-imported documents without a manual re-upload.
  Redeploying the worker does not reprocess old documents; this does. Audited as
  `document.reprocess`. Backed by `reindex.reindex_one()`.

### Much faster ingestion
- **Parallel per-page processing**: structuring, faithfulness verify, and figure vision now
  run across pages concurrently (bounded by `PAGE_CONCURRENCY`, default 4) instead of strictly
  one page at a time -- the dominant cost on multi-page documents. Per-page checkpoints,
  resume, page order, and token/faithfulness accounting are all preserved. Typical multi-page
  PDFs ingest several times faster.
- **Single-call vision**: figures are classified and described in one LLM round-trip instead
  of two (`vision_combined` prompt), halving vision calls per figure. New `VISION_ENABLED=false`
  switch for text-only (no figure description) imports.
- **Smarter LLM-skip**: clean prose pages (typical digital PDFs) now skip the restructuring LLM
  even without Markdown headings -- only genuinely noisy/short-line pages go through it.
- **Optional escalation**: the second-pass re-structuring on a faithfulness miss is now gated by
  `STRUCTURE_ESCALATE` (default on) so it can be turned off for maximum speed.

### Custom-font CMap permutations detected -> OCR
- A third mojibake class: a PDF whose font renders correct Cyrillic glyphs but whose text
  layer is a substitution cipher to arbitrary ASCII letters/brackets (e.g. "MUJLJ" for a
  chapter heading). The bytes are plain ASCII, so the symbol/accent detectors and codepage
  re-decode all missed it. `text_looks_garbled()` now also flags this by bracket/backslash
  density and lowercase->UPPERCASE mid-word transitions, routing the page to render+OCR.
  (A false positive is harmless -- it only re-reads a page via OCR, which is still correct.)
- Restored live per-page progress on the floating status widget during parallel
  structuring (it no longer sticks at "structuring 30%" while pages complete).

### Mis-decoded codepage text layers repaired deterministically
- A second mojibake class: a CP1251/KOI8-R (Cyrillic) PDF text layer decoded as Latin-1,
  where almost every character becomes an accented-Latin letter (often with no symbol
  glyphs), so the first detector missed it. `text_looks_garbled()` now also flags
  overwhelming accented-Latin density.
- New `repair_encoding()` recovers such text by re-encoding Latin-1 and re-decoding the
  real codepage -- exact Cyrillic, no OCR/LLM cost. It works **line by line** and runs on
  every page, so MIXED pages (a garbled header next to clean ASCII and already-correct
  Cyrillic body) are fixed without disturbing the clean lines. Real Cyrillic and accented
  Western text are left untouched (a large, confident Cyrillic-ratio gain is required).
  Pages still garbled afterwards (custom-font CMap permutation) fall through to render+OCR.

### Broken-font (mojibake) PDFs now recovered via OCR
- A PDF whose embedded font lacks a proper ToUnicode CMap used to extract as garbage
  (Cyrillic words come out as random accented-Latin glyphs) and shipped silently -- the
  page had plenty of text, so the "poor page" check passed it through.
- Added `text_looks_garbled()`: detects mojibake by the density of Latin-1 symbol glyphs
  (superscripts/fractions) and accented-Latin runs that real prose (even German/French)
  never produces.
- Garbled pages are now flagged poor, so the render+OCR fallback (`vision_llm` by default)
  rasterizes the page and re-reads the real glyphs, replacing the junk text layer even
  when it isn't shorter. Clean OCR is required before a page is replaced.

### Crash-proof ingestion (server rebuild/restart safe)
- Ingestion now survives a worker being killed mid-import (e.g. `docker compose up
  --build`). A **heartbeat lease** replaces the old 30-minute stale timeout: a live worker
  touches its running job every `JOB_HEARTBEAT_SECONDS` (15s); any job whose heartbeat is
  older than `JOB_LEASE_SECONDS` (90s) is treated as orphaned, requeued, and **resumed from
  its last completed page** — never stuck for 30 minutes, never silently broken.
- Workers reclaim orphaned jobs at startup and sweep every ~lease/3 seconds; the heartbeat
  runs on a background timer so even a slow page keeps the lease fresh (no double-processing).
- The in-process worker (dev) and the standalone worker now share one code path
  (`tome.worker.run_once`), so both get identical heartbeat + resume behavior.

### Admin & Memory overhaul
- **Memory UI is fully functional**: a "New memory" composer (Markdown body + tier +
  shared/agent scope) writes via `POST /v1/memory`; browse-by-tier, recall search,
  Markdown rendering, and forget all work end-to-end.
- **User administration**: admins can edit roles, enable/disable, delete, and **set/reset
  another user's password** (`PATCH /v1/users/{id}` with `password`) from the UI.
- **API keys** no longer auto-create on scope click — you pick read/write/admin scopes
  and press **Create**; the secret is shown once. Chosen scopes are honored exactly.
- **Webhooks redone**: choose target URL + secret + subscribed events (`document.ready`,
  `document.deleted`), with URL/SSRF validation; per-row **Send test** delivers a signed
  test event synchronously and reports the status code.
- **Audit log** (`GET /v1/audit`, admin): key/webhook/user mutations and logins are
  recorded with actor + action + detail, surfaced in an Admin → Logs tab.
- **Rich Health** (`GET /v1/stats`): documents/folders/sections/chunks/entities/memories/
  users/keys/webhooks counts, token usage, job-status breakdown, pgvector + schema-ready
  flags, active provider config, and the latest faithfulness eval.

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

### Sprint 3 — Agent memory (Markdown-native)
- **Agent memory** (`tome/memory.py`, `agent_memory` table): long-term memory stored as
  canonical **Markdown**, kept separate from the document KB (no Atlas/folder pollution)
  yet searched by the same hybrid BM25 (+ optional pgvector) machinery.
- **Tiers + consolidation**: working → episodic → semantic → procedural; `observe`
  logs raw notes, `consolidate` distils a session into an episodic summary and promotes
  durable facts (LLM when configured, deterministic raw roll-up offline).
- **Hygiene**: secret redaction before storage (`tome/redact.py` — API keys, tokens,
  PEM, `<private>…</private>`); recall reinforces importance; time-decay + GC eviction
  (`tome memory-gc`); contradiction resolution via `mkey` supersession; append-only
  `memory_audit` trail for deletions.
- **Per-agent scoping**: `shared` (workspace) vs `agent` (private) visibility, selected
  by `MEMORY_SCOPE` and the `X-Agent-Id` header / `agent_id` param.
- **Surfaces**: REST `/v1/memory` (+ `recall`/`observe`/`consolidate`), 6 new MCP tools
  (`remember · recall · list_memory · observe · consolidate · forget`), and a **Memory**
  tab in the Library UI.
- **Auto-capture**: a drop-in Claude Code hook (`examples/hooks/`) that `observe`s on
  tool use and `consolidate`s at the end of a turn — agent memory with zero code.
- Locked the Markdown-canonical contract for memory (`test_memory_namespace_is_markdown`
  is now a real passing test, no longer xfail).

#### Carried debt closed (from Sprints 0–2)
- **Immediate revocation**: the auth scope cache is now invalidated on logout, user
  disable/role change, and api-key deletion (no ≤30s stale-access window).
- **Offline embeddings out of the box**: a `TOME_EXTRAS` Docker build arg bakes the
  `fastembed` extra into the local/air-gapped image (`docker-compose.local.yml`) — no
  manual rebuild to switch `EMBED_PROVIDER=fastembed`.
- Verified the gated `extras` path (real fastembed embedder) locally.

### Sprint 4 — Library UI v2 & ingestion parity (MLP)
- **Folder tree v2**: real recursive tree with per-node actions (new subfolder, rename,
  delete, upload-here), inline creation at any depth, drag-a-document-to-move, and
  drag-a-file-to-upload-into-folder. Selected folder is the default upload target.
- **Document reader v2**: a table-of-contents sidebar + content pane; read the full
  document or any individual section/chunk, with inline section editing, version history,
  export, and per-section conflict resolution.
- **Atlas v2**: a real navigable hierarchy (named folders → children → documents,
  clickable) plus the generated Markdown overview — no more flat `<pre>` dump.
- **Admin v2**: tabbed Users / API keys / Webhooks with proper tables, validation,
  copy-once keys, last-used/last-login, webhook event selection, and toasts.
- **Accurate progress**: finer-grained per-page progress in the pipeline; the UI shows a
  real stage timeline and surfaces success/error/conflict as toasts.
- **Ingestion parity (REST)**: `POST /v1/documents/markdown` ingests ready Markdown into
  a folder (`folder_path` cascade or exact `folder_id`); `POST /v1/folders` creates a
  subfolder by `name` + `parent_id`; documents move by `folder_id`; `GET /v1/atlas/tree`
  returns the structured hierarchy; file upload accepts a target `folder_id`.
- **Ingestion parity (MCP)**: `ingest_markdown` (ready Markdown, no processing) and
  `ingest_file` (base64 bytes → full extraction pipeline), both into a folder tree.
- Design system: reusable Tabs, Menu, Toast, Spinner, EmptyState primitives.
- Test hygiene: the suite now hard-neutralizes any local LLM/cloud credentials so it runs
  fully offline, deterministically, and for free.

### Sprint 6 — Knowledge graph (derived 3rd retrieval signal)
- **Knowledge graph** (`tome/graph.py`, `graph_entities`/`graph_mentions`/`graph_edges`):
  entities (key phrases, model codes, acronyms) and co-occurrence relations are extracted
  **deterministically** from Markdown (no LLM required, no graph DB) and fused into hybrid
  search as a **third RRF signal** alongside BM25 + vectors. Fully rebuildable
  (`tome graph-rebuild`, `POST /v1/graph/rebuild`).
- REST `/v1/graph/entities`, `/v1/graph/entities/{id}` (mentions + neighbors); MCP
  `list_entities` / `get_entity`; a **Graph** tab in the Library UI to browse entities,
  pivot to the sections that mention them, and to related entities.

### Sprint 7 — Ingestion hygiene & connectors
- **AI language pre-analysis** (`tome/lang.py`): detect a document's real language(s)
  (LLM when available, deterministic Unicode-script + stop-word heuristic otherwise) and
  **re-scan OCR with the correct engine languages** — fixes garbled multi-language scans.
  The detected language is recorded on the document.
- **Ingestion-time PII/secret redaction** (`INGEST_REDACT`): strip secrets from document
  text during ingestion (faithfulness compared fairly on redacted text).
- **Transcript import**: `POST /v1/memory/transcript` + MCP `import_transcript` turn a
  conversation (string, lines, or {role,text}) into memory (observe + consolidate).

### Sprint 8 — Operations
- `tome demo-seed` (sample documents for first-run/demos) and `tome export-all <dir>`
  (Markdown backup of every document). Admin gained a **Health** tab (usage + corpus
  faithfulness eval).

### Visual knowledge graph
- The Graph tab is now an **interactive force-directed network** (`GET /v1/graph`):
  entities as nodes (size = mentions, colour = kind), co-occurrence relations as edges
  (width = weight). Drag to pan, wheel/buttons to zoom, click a node to highlight its
  links and open its documents/neighbors — instead of the previous flat lists.

### Folders: no orphaned documents
- **Deleting a non-empty folder is refused** (409) — including a parent whose *subfolder*
  holds documents (counted over the ltree subtree). The UI shows a clear message; move or
  delete the documents first. Previously delete cascaded and orphaned the documents
  (`folder_id → NULL`) with no way to re-file them.
- **Unfiled documents are surfaced** (`GET /v1/unfiled` + an "Unfiled" section in the
  sidebar) and can be **drag-and-dropped** back into any folder (the tree already supports
  dragging documents between folders).

### Processing / Jobs view
- **Durable Processing view** (`GET /v1/jobs` + a Library UI "Processing" tab): every
  ingestion job listed per file with live status, stage, **per-page progress**
  (`page X/N`), faithfulness, attempts and errors. Server-backed, so it **survives a page
  reload** and shows multiple files side by side (the old in-memory bottom widget lost
  state on refresh and showed no real progress).
- **Download originals**: `GET /v1/documents/{id}/source` returns the original uploaded
  file; the Processing view exposes a download button per document.

### Fixes (resilience & performance)
- **Resumable ingestion (per-page checkpoints).** Large documents are processed page by
  page, and each page's result is checkpointed (`ingestion_page_results`). If a job fails
  mid-document it is retried (bounded budget) and **resumes from the last completed page**
  instead of restarting from page 1 — and the staged bytes + checkpoints are kept across
  retries (previously the bytes were deleted on error, making resume impossible).
- **Original file now linked.** `source_object_key` is persisted on the document (it was
  always empty), so stored originals can be reprocessed/`reindex`ed.
- **True per-page PDF extraction (critical).** The Tika path collapsed a whole PDF into
  one "logical page" (Tika gives no reliable page breaks), so an 84-page book became a
  single ~140k-token LLM call (summarized) and figures were only detected on page 1. PDFs
  with a text layer are now extracted **page by page via PyMuPDF** (each page keeps its
  own text + its own figures); scanned PDFs get per-page OCR via the fallback. Non-PDF
  formats still go through Tika.
- **Content-preservation guarantee (critical).** LLM structuring could silently drop
  most of a document — an 84-page book collapsed to ~7 pages because an over-eager model
  summarized pages (or judged noisy scans as "noise → empty"); the pipeline only logged
  the coverage drop and stored the fragment. Now, if a page's structured output is
  drastically shorter than the source (< `STRUCTURE_MIN_LENGTH_RATIO`, default 0.35), the
  **raw extracted text is kept verbatim** — no page is ever summarized away.
- **LLM no longer freezes ingestion.** A slow/unreachable model used to stall each page
  ~100s (5× exponential-backoff retries + the SDK's own retries). Added a per-request
  `LLM_TIMEOUT` and a bounded `LLM_MAX_RETRIES` (SDK internal retries disabled).
- **Smart-skip actually works now.** The `_NOISE_HINT` regex ended in `[-￿]` — a range
  matching nearly every character — so clean Markdown was never recognized as clean and
  the LLM ran on every page. Fixed; clean pages skip the LLM.
- `STRUCTURE_ENABLED` master switch to keep extracted text as-is (no LLM cost) for
  already-clean Markdown sources.

### Branding & docs
- Added the Tome logo (`assets/logo.svg` + PNGs, `webui/public/favicon.*`), wired the
  favicon/apple-touch icon into the Library UI and used the mark in the UI header/login.
- Polished the README (centered logo header, badges, highlights) for a production look.

