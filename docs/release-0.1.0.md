# Tome v0.1.0 — first public release

**The agent-native knowledge OS.** Turn messy documents (PDFs, scans, DOCX) into a clean,
*verifiable*, **Markdown** knowledge base that LLMs and AI agents read, search, and curate —
over **REST · MCP · a React Library UI**.

## Highlights

- **Structure-first ingestion** — `extract → structure (LLM) → verify faithfulness →
  sections + chunks → hierarchical Atlas`. Markdown is the single source of truth; vectors
  are an optional enhancement, never the core.
- **Faithfulness guarantee** — the assembled Markdown is checked against the raw extract
  (content coverage, number reconciliation, cleanliness); a per-document score is stored.
- **Pluggable extraction (top-10)** — Tika, Docling, Marker, Azure DI, AWS Textract, Google
  Document AI, Mistral OCR, Unstructured, LlamaParse, vision-LLM — with smart
  `primary → fallback` routing, large-PDF splitting, and auto language detection.
- **Broken-font / mojibake recovery** — deterministic CP1251/KOI8-R repair plus render+OCR
  for custom-font permutation pages, run **in parallel** across pages.
- **Hybrid retrieval** — BM25 + optional pgvector + knowledge graph fused with RRF and an
  optional reranker. Graceful degradation: no pgvector → BM25; no LLM key → raw text.
- **Read *and* write over MCP** (33 tools) + full REST API + React Library UI
  (Library, Search, Atlas, conflict review, versions, admin).
- **Editable & versioned** — optimistic-locked section editing, full history, folder ops,
  per-section 3-way conflict resolution on re-import.
- **Agent memory** (Markdown-native) — remember / recall / observe / consolidate / forget.
- **Secure-by-default** — opt-in auth, MCP fail-closed, signed asset URLs, webhook HMAC +
  SSRF guard, rate limiting, upload caps, non-root containers, fully-local mode.

## Quick start

```bash
git clone https://github.com/zsembek/tome.git && cd tome
cp .env.example .env          # add an LLM key, or run fully local
docker compose up -d --build
# Library UI → http://localhost:3000   ·   REST → http://localhost:8080   ·   MCP → http://localhost:8765
```

See the [README](../README.md) for configuration, the MCP tool list, and the local
(zero-egress) profile. Full change log in [CHANGELOG.md](../CHANGELOG.md).

## Stack

FastAPI gateway · MCP server (mcpo) · React + Vite + nginx UI · Postgres (pgvector + ltree)
· Tika · MinIO/FS storage · worker. Bring any LLM (OpenAI, Azure, Anthropic, Ollama/vLLM)
and any embedder.
