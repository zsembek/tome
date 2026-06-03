<p align="center"><img src="assets/logo.svg" alt="Tome" width="96" /></p>

# Tome — the knowledge base that AI agents read

> **Tome turns any documents into a clean, structured, verifiable Markdown
> knowledge base built for LLMs and AI agents** — universal extraction, LLM
> structuring with a completeness guarantee, a navigable folder → document →
> section hierarchy, hybrid search, and a living knowledge map (the Atlas).
> Self-hosted, any model, no vector-store lock-in.

This document describes the product: what Tome is, the problem it solves, why it is
the right foundation for agentic knowledge, and where it is going.

---

## 1. What it is and who it's for

**The problem.** To let an AI agent or a RAG system answer questions over real
documents, teams today stitch together 5–6 libraries: parse dozens of formats, clean
OCR noise, slice content into pieces, organize it somehow, and give the model a way to
navigate it. The result is usually bolted onto a vector database that is expensive,
imprecise on exact terms and codes, prone to "proximity hallucinations," and has to be
rebuilt from scratch every time. Nothing verifies that the ingested base actually
matches the source.

**The solution.** Tome is a self-hosted platform that owns the whole path from
*"raw document → knowledge base for an LLM"* out of the box: any extractor, any LLM,
any embedder; a Markdown-native structure plus a hierarchical Atlas for agent
navigation; powerful hybrid search (keywords + semantics + reranking); a faithfulness
guarantee on every document; and seamless editing and versioning so the base stays
alive.

**Who it's for**
- Teams building AI assistants over internal documentation — technical manuals,
  policies, SOPs, legal, support, research.
- AI-agent developers who need a reliable, navigable *knowledge layer* instead of an
  opaque vector index.
- Integrators and products that need an embeddable, self-hostable knowledge backend.

**One-line positioning**
> *The agent-native knowledge OS — any extractor, any model, Markdown-native, hybrid
> search, fully self-hosted.*

---

## 2. Why Tome is the right foundation

1. **Agent-native.** An agent both *reads* (Atlas → folders → documents → sections,
   plus hybrid search) and *writes* (creates folders, ingests, edits sections) over MCP.
   It's a knowledge base agents can navigate and curate, not a black box they query.
2. **A living, hierarchical Atlas.** A knowledge map generated from the database that an
   agent reads first to orient itself instantly across tens of thousands of documents.
3. **Trust through a faithfulness gate.** Tome verifies that the structured output
   preserves the source — content coverage, reconciled numbers/units, no OCR noise — and
   stores a faithfulness score per document. For technical, legal, and medical content
   this is the decisive criterion, and almost no RAG tool guarantees it.
4. **Hybrid search as a strength.** BM25 for exact terms and codes + embeddings for
   semantics and cross-lingual reach + a reranker on top. Not "either/or" — the best of
   both, with the option of a fully local embedder.
5. **No lock-in at three layers.** Any extractor, any LLM, any embedder — all behind a
   single interface, switchable by configuration. Graceful degradation: no vectors →
   BM25; no LLM → raw text.
6. **Clean Markdown + real sections.** Headings, tables, breadcrumbs, and inline image
   descriptions — a structure LLMs understand far better than anonymous chunks.
7. **A living base.** Editing, moving, splitting/merging sections, versioning, rollback,
   and source re-import with conflict resolution. Most "document → KB" tools can't do
   this at all.
8. **Self-hosted, data stays in your perimeter.** Your Postgres, your object store, and —
   if you want — fully local models. Open source.

### Comparison with alternatives

| Capability | **Tome** | Onyx/Danswer | R2R / Morphik | LlamaIndex/-Parse | Unstructured |
|---|---|---|---|---|---|
| Markdown-native structure + sections | ✅ | partial | partial | by hand | ❌ (elements) |
| Hierarchical Atlas for agents | ✅ unique | ❌ | ❌ | ❌ | ❌ |
| Seamless editing + versions | ✅ | ❌ | partial | ❌ | ❌ |
| Pluggable extractor (top-10) | ✅ | limited | limited | own parser | is the extractor |
| Hybrid search (BM25 + vector + rerank) | ✅ | ✅ | ✅ | ✅ | n/a |
| MCP tools (read **and write**) | ✅ | limited | ❌ | ❌ | ❌ |
| **Faithfulness guarantee** | ✅ unique | ❌ | ❌ | ❌ | ❌ |
| Personal mode (offline, local models) | ✅ | heavy | heavy | a library | a library |
| Fully self-hosted + local models | ✅ | ✅ | ✅ | depends | ✅ |

**What makes it defensible.** Individual features are copyable. Tome's strength is the
*combination* competitors don't offer together: (1) **trust** via a measured
faithfulness gate, (2) **agent-native read + write** over MCP, and (3) **one product
from a personal offline base to enterprise scale** on a single codebase. On top of that
is an execution advantage — extraction, structuring, editor, search, Atlas, and MCP
integrated into one coherent product. No-lock-in is deliberate: Tome competes on quality
and UX, not by trapping your data.

---

### Structure-first, RAG-optional

Tome is deliberately **not RAG-first**. Agents reach knowledge by navigating a
folder → document → section hierarchy and the Atlas, and by exact-term BM25 — the way a
person reads a manual. Vector similarity is an **optional enhancement** layered on top
(hybrid search), never the core. This avoids the classic failure modes of vector-first
RAG (proximity hallucinations, weak on codes/terms, opaque retrieval) and keeps the
system fully functional with zero embeddings.

### Tome vs. assembling your own stack

The market sells the three layers Tome unifies as **separate** products, so the usual
"alternative" is gluing several together and maintaining the seams:

| Layer | Typical point solution | In Tome |
|---|---|---|
| Document extraction / structuring | **Docling**, Unstructured, Azure DI, Google Document AI | built-in, pluggable, normalized to faithful **Markdown** |
| Stateful agent memory / runtime | **Letta**, LangGraph, Mem0 | agent memory as Markdown documents, read/write over MCP |
| Knowledge surface & retrieval | a vector DB + a custom API/UI | hierarchy + Atlas + hybrid search + REST/MCP/UI, one transactional path |

A common "Tome-like" build is **Docling + Letta/LangGraph + a vector database** wired by
hand. Tome delivers that operating model as **one self-hosted product** — with a
faithfulness guarantee, editing/versioning, and a Markdown-canonical core — so there are
no seams to own and nothing locks your data in.

## 3. Core capabilities

### Faithfulness — ingestion you can trust
OCR and LLM structuring routinely drop tables, numbers, and whole sections — silently.
Tome verifies the assembled Markdown against the raw extract (content coverage, number
reconciliation, cleanliness), escalates to a stronger pass when a document falls short,
and records a faithfulness score. You know the knowledge base reflects the source.

### The Atlas — a living knowledge map
The source of truth is the database; the Atlas is a generated, always-current
representation of it. It is **hierarchical** so it scales:

- A small **index** node lists the top-level folders with one line each — the agent reads
  it first.
- Per-branch nodes describe a folder's documents and summaries, loaded on demand as the
  agent drills down.
- Updates are **delta-based** — adding a document rebuilds only the affected branch — so
  the map stays cheap to maintain and cheap to read.

Example of an index node:

```markdown
# Atlas — Equipment Manuals knowledge base
_Updated: 2026-06-02 · 12 folders · 480 documents_

## Filling line A — vendor X (complete bottling complex)
Blow molding, filling, capping, cooling, conveyors, inspection, labeling.
- **Cooler manual** — commissioning, lubrication, hygiene, conveyors. (470 sections)
- **Filler manual** — washing, CIP, pressure parameters. (1500 sections)
- … 7 more documents
→ Topics: feed pressure, CIP cleaning, lubricants, alarms

## Packaging line B — vendor Y
…
```

An agent reads the index in one call, sees the whole map, then loads only the branch it
needs — instant orientation without scanning lists or bloating context.

### Structured, agent-native retrieval
Knowledge is exposed as a navigable tree — **folders → documents → sections** — with
breadcrumbs, plus separate retrieval chunks for semantic search. Agents fetch whole,
coherent sections (traceable to a real heading), not stitched fragments — which sharply
reduces hallucination.

### Pluggable extraction (top-10 providers)
A single normalized interface in front of the strongest engines — Apache Tika, Docling,
Marker, Azure Document Intelligence, AWS Textract, Google Document AI, Mistral OCR,
Unstructured, LlamaParse, and a vision-LLM fallback. Smart routing sends digital pages to
a fast parser and scanned/complex pages to OCR or a vision model; large files are split
to fit limits. Figures are classified, and meaningful ones are described by a vision
model so they're searchable.

### Pluggable models, no lock-in
The LLM (OpenAI, Azure OpenAI, Anthropic, xAI, Ollama, vLLM) and the embedder
(OpenAI-compatible or a local BGE/e5) are both swappable by configuration, with separate
models allowed for structuring, vision, naming, and the Atlas. Everything can run fully
locally for air-gapped deployments.

### Hybrid search
BM25 (exact terms and codes) ∪ vector ANN (semantics, cross-lingual) fused with
Reciprocal Rank Fusion and an optional reranker. Without a vector extension it degrades
gracefully to pure BM25 — search keeps working.

### Seamless editing and versioning
Humans and agents edit section content and structure — insert, delete, move, split,
merge — atomically, with optimistic locking and a full revision history. Re-importing an
updated source detects conflicts with manual edits and offers **per-section resolution**
(keep the manual edit vs. take the new import); nothing is silently lost.

### Three access surfaces
- **REST API** — for services, pipelines, and integrations.
- **MCP** — read *and* write tools so AI agents can both consume and grow the base
  (Claude Desktop, Cursor, or any MCP client; stdio and HTTP/OpenAPI).
- **Library UI** — a full web application for people: folder tree, drag-and-drop upload
  with live progress, viewer, section editor, search, the Atlas, and version history.

All three run on one consistent, transactional path.

### Secure and self-hosted
Identity is **secure-by-default**: users, roles (admin · editor · viewer), sessions, and
scope-based access control; a first-run administrator bootstrap; service API keys.
Assets are served through short-lived signed URLs. Everything is self-hosted — your
database, your object store, your models — so data never leaves your perimeter.

---

## 4. Architecture (high level)

```
   Access surfaces                         Tome
 ┌──────────────────┐        ┌───────────────────────────────────────┐
 │ REST  (services) │ ─────▶ │  Gateway (FastAPI, auth)               │
 │ MCP   (agents)   │ ─────▶ │     │ enqueue                          │
 │ Library UI (web) │ ─────▶ │     ▼                                  │
 └──────────────────┘        │  Pipeline workers                      │
                             │   extract → structure → verify →       │
                             │   vision → name → split → index → atlas│
                             │     │                                   │
                             │     ▼                                   │
                             │  PostgreSQL            Object store      │
                             │  (ltree tree,          (local FS or      │
                             │   tsvector BM25,        MinIO/S3):        │
                             │   pgvector ANN,         originals,        │
                             │   sections, versions,   figures,          │
                             │   Atlas, jobs, outbox)  snapshots)         │
                             └───────────────────────────────────────┘
```

- **Gateway** (FastAPI) — uploads, folder/document/section operations, search, auth, and
  job enqueuing.
- **Workers** — the ingestion pipeline; scale horizontally.
- **MCP server** — read + write/edit tools for agents (stdio and HTTP/OpenAPI).
- **PostgreSQL** is the backbone — folder tree (`ltree`), full-text BM25 (`tsvector`),
  optional semantic ANN (`pgvector`), sections, versions, the Atlas, the job queue, and a
  transactional outbox. No separate vector database required.
- **Object store** — local filesystem by default, or MinIO/S3 for production; kept
  consistent with the database via the outbox and orphan garbage collection.
- **Library UI** — React + Vite.

The ingestion pipeline, by stage:

```
file → extract → structure (LLM) → verify (faithfulness) → vision → name → split → index → atlas → ready
```

---

## 5. Operating modes: personal → enterprise

Tome is **domain-agnostic** — nothing in the core is tied to an industry; it works equally
for technical manuals, legal, finance, support, research, or personal notes. Optional
document-type templates ("manual", "contract", "article", "note") tune structuring hints,
tag schemas, and faithfulness thresholds via settings rather than hard-coded rules.
Auto-naming and auto-filing orient on the workspace's existing folder tree.

| | **Personal** | **Enterprise** |
|---|---|---|
| Who | one person, a private base for their own LLM | a team or company, many users |
| Scale | hundreds–thousands of documents | tens of thousands+, many workspaces |
| Models | local (Ollama + a local embedder) — data never leaves | any, by configuration |
| Access | localhost open mode or a single token | users, roles, API keys, RBAC |
| MCP | a personal Claude Desktop / Cursor | a shared endpoint for the team and its agents |

Personal mode is a **"second brain" for personal LLMs**: drop in documents → Tome
structures, organizes, and maps them → a personal agent walks the base over MCP, fully
offline if you use local models. The same codebase scales up to a multi-workspace
enterprise deployment — an adoption funnel from individual to organization.

---

## 6. Quality, measured

Quality is proven with numbers, not claimed. A built-in evaluation harness covers:

- **Faithfulness %** — extraction completeness (no loss, correct numbers), per document
  and aggregated across the corpus.
- **Retrieval recall@k / precision@k** — whether search returns the right sections, over a
  golden "query → relevant sections" set.
- **End-to-end QA** — whether an agent answers correctly over the base, judged against a
  golden "question → reference answer + source" set.
- **Extraction diff** — regressions when changing the extractor or model.
- **Cost / latency** — tokens, $/document, seconds/page.

This makes configuration choices (e.g. one extractor vs. another, a cloud model vs. a
local one) an objective comparison rather than a guess.

---

## 7. Reliability at scale

- **Postgres for tens of thousands of documents / millions of chunks** — partitioning by
  workspace, an HNSW vector index, read replicas for retrieval load, and large text kept
  out of hot tables.
- **Throughput** — configurable worker concurrency and per-provider rate limits, retries
  with backoff, stuck-job detection and requeue, and a content-hash cache so repeats and
  unchanged re-imports are skipped.
- **Consistency** between the database and the object store via a transactional outbox,
  plus background orphan garbage collection.
- **Everything configurable** — provider limits, token budgets, chunk/section sizes, and
  faithfulness thresholds live in settings, not in code.

---

## 8. Roadmap and strategy

The core is in place: pluggable extraction, LLM structuring with the faithfulness gate,
the section/chunk model, editing and versioning with conflict resolution, the
hierarchical Atlas, hybrid search, secure-by-default identity, and the REST + MCP +
Library UI surfaces. Strategic direction from here:

| Area | Why it matters |
|---|---|
| Source connectors (SharePoint / Drive / S3) | scheduled or on-demand import from where documents already live |
| Translation | multilingual bases; answers in the user's language |
| PII redaction | mask sensitive data before storing or sending to a model |
| Per-tenant quotas & cost controls | predictable spend in shared deployments |
| Backup / restore | a consistent database + object-store snapshot |
| Observability & cost dashboards | tokens and $ per document, alerts |
| Managed cloud offering | a hosted option on top of the open-source core |

**Strategy.** Win on *trust* (the faithfulness guarantee), *agent-nativeness* (read +
write over MCP and the Atlas), and *freedom* (any model, self-hosted, no lock-in). Grow
bottom-up: individuals adopt the personal mode for their own agents and bring Tome into
their organizations, where it scales to a shared, governed knowledge OS.

---

## 9. Summary

Tome is a self-hosted, agent-native knowledge OS: **universal extraction → LLM
structuring into clean, verified Markdown → a Postgres-backed hierarchy of sections →
hybrid search → a living Atlas → REST, MCP, and a Library UI** — with any model and no
vector lock-in. Services, agents, and people all populate and curate the same base;
agents orient themselves through the Atlas and retrieve exactly the right sections. The
result is a knowledge layer AI agents can actually trust, read, and maintain.
