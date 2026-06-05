<div align="center">

<img src="assets/logo.png" alt="Tome logo" width="128" />

# Tome

**The agent-native knowledge OS** — turn messy documents (PDFs, scans, DOCX) into a
clean, *verifiable*, **Markdown** knowledge base that LLMs and AI agents read, search,
and curate.

[![CI](https://github.com/zsembek/tome/actions/workflows/ci.yml/badge.svg)](https://github.com/zsembek/tome/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-2ea44f.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%2B-3776ab.svg)
![Postgres](https://img.shields.io/badge/postgres-pgvector%20%2B%20ltree-336791.svg)
![MCP](https://img.shields.io/badge/MCP-read%20%2B%20write-7c3aed.svg)

*Self-hosted · any LLM · any embedder · **structure-first, RAG-optional** · no vector lock-in*

</div>

---

<div align="center">

### ▶ Demo — see it in action

<img src="assets/social-preview.png" alt="Tome — the agent-native knowledge OS" width="820" />

<sub>📹 <b>A live demo GIF goes here.</b> Record a 30–60s capture of the Library UI and an
agent walking the Atlas (folder → document → section over MCP), save it as
<code>docs/demo.gif</code>, and uncomment the line below — it renders automatically.</sub>

<!-- <img src="docs/demo.gif" alt="Tome demo: the Library UI and an agent navigating the Atlas over MCP" width="820" /> -->

</div>

---

> **Why Tome?** Most "chat with your docs" stacks shred files into anonymous vector
> chunks and hope similarity search returns the right one — losing structure, dropping
> tables and numbers, impossible to correct. Tome keeps the document's real
> **structure**, **proves** it didn't silently lose content (a faithfulness gate), and
> exposes the base the way an agent actually navigates knowledge:
> **folder → document → section** + a living **Atlas** — over **REST · MCP · a React
> Library UI**. Vectors are an optional enhancement, never the core.

```text
extract → structure (LLM) → verify faithfulness → sections + retrieval chunks
   → hybrid search (BM25 + vectors + reranker) → hierarchical Atlas
   → REST + MCP + Library UI
```

**Highlights:** 📄 pluggable extraction (top-10) · ✅ faithfulness guarantee ·
🌍 **auto language detection** (right OCR languages per doc) · 🧭 hierarchical Atlas ·
🔎 hybrid search (BM25 + pgvector + **knowledge graph** → RRF + reranker) · ✍️ full
editing & versioning · 🧠 **agent memory** (Markdown-native, auto-capture) · 🤖 read
**and write** over MCP · 🔒 secure-by-default · 🏠 fully-local mode.

Product overview, goals & strategy: **[PRODUCT.md](PRODUCT.md)**.

---

## What is Tome?

Most "chat with your docs" stacks shred a file into anonymous vector chunks and
hope similarity search returns the right fragment. That loses structure, drops
tables and numbers during OCR, can't be corrected, and feeds agents
context-free snippets they tend to hallucinate around.

Tome takes a different path. It runs each document through a transparent pipeline
that **preserves the document's real structure** (folders → documents → sections),
**proves the result didn't silently lose content** (a faithfulness gate), and
**exposes the base the way an agent actually navigates knowledge** — read the map,
open a folder, list a document's sections, fetch the exact section. It's not a
one-shot index: documents stay **editable, versioned, and re-importable** with
conflict resolution, so corrections survive.

## Why Tome — key advantages

- **Agents read structured documents, not opaque chunks.** Over MCP an agent calls
  `get_atlas → list_folders → list_documents → list_sections → get_section`,
  retrieving whole coherent sections with headings and breadcrumbs. Answers are
  traceable to a real section, not stitched from 200-token fragments → far less
  hallucination.
- **A faithfulness guarantee you can trust.** OCR and LLM structuring silently drop
  tables, numbers, and whole sections. Tome verifies the assembled Markdown against
  the raw extract — content coverage, number reconciliation, cleanliness — escalates
  on failure, and stores a per-document faithfulness score. You *know* the KB matches
  the source.
- **No vector lock-in — runs on plain Postgres.** Tree (`ltree`), full-text BM25
  (`tsvector`), and optional semantic ANN (`pgvector`) live in one database; hybrid
  search fuses them with RRF + an optional reranker. Bring any LLM (OpenAI, Azure,
  Anthropic, local Ollama/vLLM) and any embedder. **Graceful degradation:** no
  pgvector → pure BM25; no LLM key → raw text. One dependency, your models, your infra.
- **Handles real-world documents.** Pluggable extraction with a **top-10** roster —
  Tika, Docling, Marker, Azure Document Intelligence, AWS Textract, Google Document AI,
  Mistral OCR, Unstructured, LlamaParse, vision-LLM — with smart `primary → fallback`
  routing for scanned or poor-quality pages, plus large-PDF splitting.
- **A living knowledge base, not a frozen index.** Humans and agents edit sections
  (optimistic `rev` locking, full revision history), reorganize folders, and re-import
  updated sources with **per-section 3-way conflict resolution** (keep manual edits vs.
  take the new import). Corrections persist across re-ingests.
- **Built-in agent memory (Markdown-native).** Tome doubles as an agent's long-term
  memory: `remember / recall / observe / consolidate / forget` over REST and MCP.
  Memories are plain Markdown (no proprietary store), tiered **working → episodic →
  semantic → procedural** with LLM consolidation, scoped per agent (shared or private),
  secret-redacted on write, reinforced on recall, and fade via decay/GC. A drop-in
  [auto-capture hook](examples/hooks) gives any agent memory with zero code.
- **Three first-class interfaces.** A REST API, **30 MCP tools** (read + write + memory,
  so agents can grow the base *and* remember across sessions — including `ingest_markdown`
  for ready Markdown and `ingest_file` for binary files-with-processing, both into a
  folder tree), and a polished **React Library UI** with a real folder tree (create /
  rename / move / drag-to-file), a TOC-based document reader, a navigable Atlas map, a
  tabbed Admin, search, and a Memory browser.
- **A map for agents (the Atlas).** A generated, always-current overview of the whole
  base (folder tree, document counts, summaries) that an agent reads first to orient
  itself — which markedly improves multi-step retrieval.
- **Secure and self-hosted by default.** Identity with users / roles (admin · editor ·
  viewer) / sessions, scope-based RBAC, short-lived signed asset URLs (no token in the
  URL), non-root containers, and internal services kept off the network. Your data
  never leaves your perimeter.

## How it works

```
        ┌─────────── ingest ───────────┐
file →  extract  →  structure (LLM)  →  verify (faithfulness gate)  →  vision
            │            │                      │ pass/escalate          │ (figures
         top-10       headings,                 ▼                         │  described
        routing       sections                name + auto-folder          │  & classified)
                                                 │
                                       split → index (BM25 + chunks + embeddings) → Atlas
                                                 │
                          ┌──────────────────────┼───────────────────────┐
                       REST API               MCP tools               Library UI
                     (apps, CI)            (Claude/Cursor/agents)     (humans)
```

Everything persists in PostgreSQL: folder tree, documents, sections, revisions,
retrieval chunks, Atlas, jobs, and a transactional outbox for object-store/webhook
consistency.

## 🧠 Agent memory (Markdown-native)

Tome isn't only a document KB — it's also a **persistent memory** an agent can grow
and reuse, stored as ordinary **Markdown** (never a proprietary object model). Memory
lives in its own namespace, so it never pollutes the document tree or Atlas, yet it's
searched by the same hybrid (BM25 + optional vectors) machinery.

- **Tiers (automatic consolidation).** `working` (raw observations) → `episodic`
  (per-session summary) → `semantic` (durable facts) → `procedural` (how-tos).
  `consolidate` distils a session's observations into an episodic summary and promotes
  durable facts — via the configured LLM, or a deterministic raw roll-up offline.
- **Hygiene built in.** Secrets (API keys, tokens, PEM blocks, `<private>…</private>`)
  are **redacted before storage**; recall **reinforces** importance; old low-value
  memories **decay and are evicted** (`tome memory-gc`); contradictions are resolved by
  **supersession** (write with the same `mkey`).
- **Per-agent scoping.** `shared` memories are workspace-wide; `agent` memories are
  private to the writing `agent_id` (`X-Agent-Id` header / `agent_id` param). Default is
  set by `MEMORY_SCOPE` (`shared` | `isolated`).
- **Surfaces.** REST `POST /v1/memory`, `GET /v1/memory/recall?q=`, `/observe`,
  `/consolidate`, `GET/DELETE /v1/memory/{id}`; MCP tools `remember · recall ·
  list_memory · observe · consolidate · forget`; a **Memory** tab in the Library UI.
- **Zero-code auto-capture.** Drop in the [Claude Code hook](examples/hooks) to
  `observe` on tool use and `consolidate` at the end of a turn.

```bash
# remember a fact (redacted, Markdown), then recall it later
curl -XPOST localhost:8080/v1/memory -H 'Content-Type: application/json' \
  -H 'X-Agent-Id: my-agent' -d '{"content":"## Pref\n\nUser prefers metric units.","mkey":"user.units"}'
curl 'localhost:8080/v1/memory/recall?q=units' -H 'X-Agent-Id: my-agent'
```

## Tome vs. a traditional vector-RAG stack

| | Traditional vector RAG | **Tome** |
|---|---|---|
| Retrieval unit | anonymous text chunks | whole **sections** with headings & breadcrumbs |
| Source fidelity | no guarantee (silent OCR/parse loss) | **faithfulness gate** + stored score |
| Editing | re-embed everything | section edits, **versioning**, conflict resolution |
| Agent access | similarity search only | **navigable hierarchy** + search over MCP |
| Infrastructure | app + separate vector DB (+ more) | a **single Postgres** |
| Lock-in | embedder + vector store | **pluggable**; BM25 works with no vectors at all |
| Access model | usually bolted on later | **secure-by-default** identity + RBAC |

## Use cases

- **Technical documentation & manuals** (Tome's origin: industrial-equipment manuals,
  full of scanned tables and figures) made queryable by an AI assistant.
- **Internal knowledge bases** for support, ops, or engineering agents.
- **Agent long-term memory** — first-class, Markdown-native memory (tiers, decay,
  redaction, per-agent scoping) an agent reads and curates via MCP/REST, with drop-in
  auto-capture.
- **Regulated / air-gapped environments** that need everything self-hosted, with no data
  leaving the network and no third-party vector service.

---

## Features

- **Pluggable extraction** (`tome/extract/`): top-10 — Tika, Docling, Marker,
  Azure DI, AWS Textract, Google DocAI, Mistral OCR, Unstructured, LlamaParse,
  vision-LLM (+ passthrough for md/txt/html). Routing: primary → fallback for
  scanned/poor pages. Docling is the recommended path for complex docs (faithful
  GFM tables + reading order). Each adapter is labeled **verified** vs.
  **experimental** — see `GET /v1/extractors`; install only the extras you use.
- **Pluggable LLM** (`tome/llm/`): OpenAI / Azure OpenAI / Anthropic / xAI /
  Ollama / vLLM. Separate models for structuring / vision / naming / atlas.
- **Pluggable embedder** (`tome/embed/`): OpenAI-compatible + local BGE/e5.
- **Pipeline** (`tome/pipeline/`): extract → structure → **verify (faithfulness)**
  → vision (+ image classification) → name → split (+ section normalization) →
  index (tsvector + retrieval chunks + embeddings) → atlas.
- **PostgreSQL** (`tome/db.py`, `tome/store.py`): folder tree (ltree), documents,
  versions, sections (hierarchy), retrieval chunks (pgvector), Atlas, jobs, outbox.
  Atomic document writes. Hybrid search (BM25 ∪ ANN → RRF → reranker).
- **Seamless editing**: section edits with `rev` (optimistic locking → 409),
  revisions, `manually_edited` flag, document versions, per-section re-import
  conflict resolution.
- **Identity & access (secure-by-default)**: users + passwords (pbkdf2-sha256),
  opaque session tokens, roles → scope RBAC, first-run bootstrap, master key +
  service API keys; assets via short-lived signed URLs; non-root containers.
- **REST API** (`api/`, FastAPI) + **MCP** (`mcp_server/`) + **Library UI**
  (`webui/`, React + Vite).
- **Agent memory** (`tome/memory.py`): Markdown-native, tiered (working/episodic/
  semantic/procedural), per-agent scoping, secret redaction, decay/GC, supersession —
  over REST + MCP, with a drop-in auto-capture hook (`examples/hooks/`).
- **Knowledge graph** (`tome/graph.py`): entities + co-occurrence relations derived
  deterministically from Markdown (no graph DB), fused into hybrid search as a third
  signal; browse it in the UI or over MCP (`list_entities`/`get_entity`).
- **Multilingual OCR** (`tome/lang.py`): AI language pre-analysis detects each document's
  real language(s) and re-scans with the correct OCR engine languages — no more garbled
  mixed-language scans.
- **CLI** (`tome/cli.py`): `tome init-db | ingest | status | eval | gc | dedup |
  reindex | memory-gc | graph-rebuild | demo-seed | export-all`.

## Quick start (Docker)

```bash
cp .env.example .env       # set LLM keys + TOME_SECRET (see Configuration)
docker compose up -d --build
# Library UI:    http://localhost:3000
# REST + Swagger: http://localhost:8080/docs
# MCP / OpenAPI: http://localhost:8765/docs
```
Stack: gateway, worker×2, mcp, postgres (pgvector), tika, minio, webui.
Only gateway (8080), mcp (8765), and webui (3000) are published; postgres, tika,
and minio stay on the internal Compose network.

### First run (secure-by-default)

Tome requires authentication unless `TOME_OPEN=true`. On first launch the Library UI
shows a **"Create the first administrator"** screen. Or via API:

```bash
curl -X POST localhost:8080/v1/auth/bootstrap \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"change-me-8+"}'
```
You can also seed the admin from env on first start with `TOME_ADMIN_EMAIL` /
`TOME_ADMIN_PASSWORD`. For a personal localhost-only instance, set `TOME_OPEN=true`
to disable auth entirely.

## Local development

```bash
python -m venv .venv && . .venv/Scripts/activate      # Windows: .venv\Scripts\activate
pip install -e .
cp .env.example .env                                   # set POSTGRES_DSN + an LLM key
tome init-db
uvicorn api.main:app --reload --port 8080              # gateway + UI + in-process worker
# MCP separately:  python -m mcp_server.server         # stdio (Claude Desktop / Cursor)
```

### Personal mode (offline, local models)
```bash
LLM_PROVIDER=ollama
OPENAI_BASE_URL=http://localhost:11434/v1
EMBED_PROVIDER=local
EMBED_MODEL=BAAI/bge-m3
EXTRACT_PRIMARY=tika
TOME_OPEN=true                        # personal localhost mode, no sign-in
```
Data never leaves your perimeter; a knowledge base for a personal LLM agent over MCP.

### Fully local / air-gapped (zero cloud keys)

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
```
This overlay needs **no cloud keys**: Tika extraction + a local embedder + (optional)
Ollama for structuring. It defaults to the **`hash`** embedder (deterministic,
zero-download lexical semantics). The overlay **bakes the `fastembed` extra into the
image** (via the `TOME_EXTRAS=fastembed` build arg), so switching to real semantic
embeddings needs **no manual rebuild** — just set `EMBED_PROVIDER=fastembed`
(fastembed downloads a small ONNX model on first use). For structuring, run Ollama and
`ollama pull` a model (otherwise structuring falls back to raw text). Hybrid search
works either way (BM25 + vectors → RRF).

## Configuration

Everything is set via `.env` (see `.env.example`): providers (LLM / embed / extract),
limits/thresholds (faithfulness, section/chunk sizes, concurrency), and access.

### Azure OpenAI

In Azure the model name is the **deployment name** (not `gpt-4o`). If you have a
single deployment, use its name for all four `LLM_*_MODEL` values:

```env
LLM_PROVIDER=azure_openai
LLM_STRUCTURE_MODEL=<deployment-name>
LLM_VISION_MODEL=<deployment-name>        # deployment must be multimodal
LLM_NAMING_MODEL=<deployment-name>
LLM_ATLAS_MODEL=<deployment-name>
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
AZURE_OPENAI_KEY=<key>
AZURE_OPENAI_API_VERSION=2024-12-01-preview
# embeddings via Azure (if you have a text-embedding-* deployment):
EMBED_PROVIDER=azure_openai
EMBED_MODEL=<embeddings-deployment-name>
# no embeddings deployment? → EMBED_ENABLED=false (search falls back to BM25)
```
Reasoning models (gpt-5.x / o-series) are handled automatically: the adapter sends
`max_completion_tokens` and omits `temperature`.

### Where files are stored

Document **metadata, sections, and search indexes** live in PostgreSQL. **Binary
blobs** (original uploads, extracted figures, version snapshots) go to an object
store under keys like `sources/<id>/<file>` and `pending/<id>/<hash>.md`:

- **Default (local FS):** written under `_store/` (gitignored). In Docker this is the
  named volume `/app/_store` — it lives in Docker's volume area, **not** in your repo
  or working tree. Set `STORAGE_DIR=/abs/path` to relocate it (e.g. `/var/lib/tome`).
- **Production:** set `S3_USE=true` (MinIO/S3) so nothing is written to local disk.

Tome never writes data files into the source tree. (If you ran an early local build
and see stray `sources/`/`pending/` folders in the project root, they are pre-`_store`
artifacts — safe to delete; they are gitignored.)

## Connecting to Claude Desktop / Cursor (MCP)

```json
{
  "mcpServers": {
    "tome": {
      "command": "python", "args": ["-m", "mcp_server.server"],
      "env": { "POSTGRES_DSN": "postgresql://...", "OPENAI_API_KEY": "..." }
    }
  }
}
```
Recommended agent flow: `get_atlas → list_folders → list_documents → list_sections
→ get_section` (with `search` when the target isn't known yet).

## Tests

```bash
pip install pytest
# unit (no DB):
python -m pytest tests/test_pipeline.py tests/test_units2.py -q
# integration (needs Postgres; creates/drops the tome_test schema):
TOME_TEST_DSN=postgresql://... python -m pytest tests/test_integration.py -q
```
Unit suites cover clean/split/chunk/faithfulness, the extractor registry, conflict
diff, export, GC, dedup, rate-limit, Atlas, password hashing, and signed-URL
verification (incl. expiry/tamper). Integration runs against real Postgres.

## Project layout

```
tome/
├── tome/                 # core (config, db, store, schema.sql, signing, cli, worker)
│   ├── llm/              #   pluggable LLM providers
│   ├── extract/          #   pluggable extractors (+ pdfutil)
│   ├── embed/            #   pluggable embedders
│   ├── prompts/          #   system prompts (files)
│   └── pipeline/         #   pipeline stages + orchestrator run.py
├── api/                  # FastAPI gateway (REST + auth)
├── mcp_server/           # MCP (read + write)
├── webui/                # React + Vite Library UI (nginx, proxies /v1 → gateway)
├── tests/                # unit + integration tests
├── Dockerfile, docker-compose.yml, .env.example
└── PRODUCT.md            # product overview & strategy
```

## Status

This is a working MVP, verified end-to-end (ingest → faithfulness → search → edit →
export; identity + RBAC; Docker Compose stack; unit + integration tests green).
Contributions and issues welcome.

## License

[MIT](LICENSE) © 2026 zsembek.
