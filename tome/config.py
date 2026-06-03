"""Tome configuration. Everything via env (.env), with sensible defaults.

Three pluggable layers (extractor / LLM / embedder) + limits/thresholds — all here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

_HERE = Path(__file__).resolve().parent
load_dotenv()
load_dotenv(_HERE.parent / ".env")


def _b(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


def _i(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


@dataclass
class Config:
    # ── Postgres ──
    postgres_dsn: str = field(default_factory=lambda: _dsn_from_env())
    db_schema: str = field(default_factory=lambda: os.environ.get("TOME_SCHEMA", "tome"))

    # ── Object store (MinIO/S3) ──
    s3_endpoint: str = field(default_factory=lambda: os.environ.get("S3_ENDPOINT", "http://localhost:9000"))
    s3_access_key: str = field(default_factory=lambda: os.environ.get("S3_ACCESS_KEY", "minioadmin"))
    s3_secret_key: str = field(default_factory=lambda: os.environ.get("S3_SECRET_KEY", "minioadmin"))
    s3_bucket: str = field(default_factory=lambda: os.environ.get("S3_BUCKET", "tome"))
    s3_use: bool = field(default_factory=lambda: _b("S3_USE", False))  # without MinIO — store in DB/FS
    storage_dir: str = field(default_factory=lambda: os.environ.get("STORAGE_DIR", ""))

    # ── LLM ──
    llm_provider: str = field(default_factory=lambda: os.environ.get("LLM_PROVIDER", "openai"))
    llm_structure_model: str = field(default_factory=lambda: os.environ.get("LLM_STRUCTURE_MODEL", "gpt-4o"))
    llm_vision_model: str = field(default_factory=lambda: os.environ.get("LLM_VISION_MODEL", "gpt-4o"))
    llm_naming_model: str = field(default_factory=lambda: os.environ.get("LLM_NAMING_MODEL", "gpt-4o-mini"))
    llm_atlas_model: str = field(default_factory=lambda: os.environ.get("LLM_ATLAS_MODEL", "gpt-4o"))
    llm_max_completion_tokens: int = field(default_factory=lambda: _i("LLM_MAX_COMPLETION_TOKENS", 16000))
    # Resilience: a slow/unreachable LLM must NOT freeze ingestion. Per-request timeout
    # and a small retry cap (with bounded backoff) — tune down for tests/offline.
    llm_timeout_sec: float = field(default_factory=lambda: _f("LLM_TIMEOUT", 60.0))
    llm_max_retries: int = field(default_factory=lambda: _i("LLM_MAX_RETRIES", 2))

    # OpenAI-compatible (openai/azure/xai/ollama/vllm)
    openai_api_key: str = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY", ""))
    openai_base_url: str = field(default_factory=lambda: os.environ.get("OPENAI_BASE_URL", ""))
    azure_openai_endpoint: str = field(default_factory=lambda: os.environ.get("AZURE_OPENAI_ENDPOINT", ""))
    azure_openai_key: str = field(default_factory=lambda: os.environ.get("AZURE_OPENAI_KEY", ""))
    azure_openai_api_version: str = field(default_factory=lambda: os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"))
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))

    # ── Embedder ──
    embed_provider: str = field(default_factory=lambda: os.environ.get("EMBED_PROVIDER", "openai"))
    embed_model: str = field(default_factory=lambda: os.environ.get("EMBED_MODEL", "text-embedding-3-small"))
    embed_enabled: bool = field(default_factory=lambda: _b("EMBED_ENABLED", True))
    reranker: str = field(default_factory=lambda: os.environ.get("RERANKER", "none"))
    cohere_api_key: str = field(default_factory=lambda: os.environ.get("COHERE_API_KEY", ""))

    # ── Extractor ──
    extract_primary: str = field(default_factory=lambda: os.environ.get("EXTRACT_PRIMARY", "tika"))
    extract_scanned: str = field(default_factory=lambda: os.environ.get("EXTRACT_SCANNED", ""))
    extract_fallback: str = field(default_factory=lambda: os.environ.get("EXTRACT_FALLBACK", "vision_llm"))
    extract_ocr_lang: str = field(default_factory=lambda: os.environ.get("EXTRACT_OCR_LANG", "eng+rus"))
    # AI language pre-analysis: detect the document's real language(s) and re-scan with
    # the correct OCR languages (fixes garbled multi-language scans). On by default.
    extract_auto_lang: bool = field(default_factory=lambda: _b("EXTRACT_AUTO_LANG", True))
    extract_lang_sample_chars: int = field(default_factory=lambda: _i("EXTRACT_LANG_SAMPLE_CHARS", 4000))
    extract_max_pages: int = field(default_factory=lambda: _i("EXTRACT_MAX_PAGES", 200))
    tika_url: str = field(default_factory=lambda: os.environ.get("TIKA_URL", "http://localhost:9998"))
    azure_di_endpoint: str = field(default_factory=lambda: os.environ.get("AZURE_DI_ENDPOINT", ""))
    azure_di_key: str = field(default_factory=lambda: os.environ.get("AZURE_DI_KEY", ""))
    # remaining top-10 extractor providers (keys in env)
    mistral_api_key: str = field(default_factory=lambda: os.environ.get("MISTRAL_API_KEY", ""))
    unstructured_api_key: str = field(default_factory=lambda: os.environ.get("UNSTRUCTURED_API_KEY", ""))
    unstructured_api_url: str = field(default_factory=lambda: os.environ.get("UNSTRUCTURED_API_URL", "https://api.unstructured.io/general/v0/general"))
    llamaparse_api_key: str = field(default_factory=lambda: os.environ.get("LLAMAPARSE_API_KEY", ""))
    google_docai_processor: str = field(default_factory=lambda: os.environ.get("GOOGLE_DOCAI_PROCESSOR", ""))
    aws_region: str = field(default_factory=lambda: os.environ.get("AWS_REGION", "us-east-1"))

    # ── Limits/thresholds (all configurable) ──
    target_lang: str = field(default_factory=lambda: os.environ.get("TARGET_LANG", "auto"))
    structure_smart: bool = field(default_factory=lambda: _b("STRUCTURE_SMART", True))
    # Master switch for LLM restructuring. Off → keep the extracted text as-is (no LLM
    # cost); useful for already-clean Markdown sources and for fast offline tests.
    structure_enabled: bool = field(default_factory=lambda: _b("STRUCTURE_ENABLED", True))
    faithfulness_min: float = field(default_factory=lambda: _f("FAITHFULNESS_MIN", 0.85))
    max_md_chars: int = field(default_factory=lambda: _i("MAX_MD_CHARS", 100000))
    max_section_chars: int = field(default_factory=lambda: _i("MAX_SECTION_CHARS", 8000))
    min_section_chars: int = field(default_factory=lambda: _i("MIN_SECTION_CHARS", 40))
    fts_config: str = field(default_factory=lambda: os.environ.get("FTS_CONFIG", "simple"))
    chunk_tokens: int = field(default_factory=lambda: _i("CHUNK_TOKENS", 512))
    chunk_overlap: int = field(default_factory=lambda: _i("CHUNK_OVERLAP", 64))
    worker_concurrency: int = field(default_factory=lambda: _i("WORKER_CONCURRENCY", 2))
    provider_min_interval_sec: float = field(default_factory=lambda: _f("PROVIDER_MIN_INTERVAL_SEC", 0.0))
    pipeline_version: str = field(default_factory=lambda: os.environ.get("PIPELINE_VERSION", "v1"))

    # ── Access / worker ──
    api_key: str = field(default_factory=lambda: os.environ.get("TOME_API_KEY", ""))
    run_inprocess_worker: bool = field(default_factory=lambda: _b("RUN_INPROCESS_WORKER", True))
    job_stale_minutes: int = field(default_factory=lambda: _i("JOB_STALE_MINUTES", 30))
    # ── Identity (secure-by-default) ──
    # tome_open=true → open mode (no authentication); OTHERWISE a session/key is required.
    tome_open: bool = field(default_factory=lambda: _b("TOME_OPEN", False))
    secret: str = field(default_factory=lambda: os.environ.get("TOME_SECRET", ""))
    session_ttl_hours: int = field(default_factory=lambda: _i("SESSION_TTL_HOURS", 168))
    admin_email: str = field(default_factory=lambda: os.environ.get("TOME_ADMIN_EMAIL", ""))
    admin_password: str = field(default_factory=lambda: os.environ.get("TOME_ADMIN_PASSWORD", ""))
    # ── Agent memory (Markdown-native) ──
    memory_enabled: bool = field(default_factory=lambda: _b("MEMORY_ENABLED", True))
    # 'shared' → new memories visible to every agent in the workspace;
    # 'isolated' → new memories private to the writing agent_id by default.
    memory_scope: str = field(default_factory=lambda: os.environ.get("MEMORY_SCOPE", "shared"))
    memory_default_agent: str = field(default_factory=lambda: os.environ.get("MEMORY_DEFAULT_AGENT", "default"))
    memory_redact: bool = field(default_factory=lambda: _b("MEMORY_REDACT", True))
    memory_decay_half_life_days: float = field(default_factory=lambda: _f("MEMORY_DECAY_HALF_LIFE_DAYS", 30.0))
    memory_working_cap: int = field(default_factory=lambda: _i("MEMORY_WORKING_CAP", 500))
    memory_min_importance: float = field(default_factory=lambda: _f("MEMORY_MIN_IMPORTANCE", 0.05))

    # ── Ingestion hygiene / connectors ──
    # Redact secrets (API keys, tokens, PEM, <private>…</private>) from document text
    # during ingestion. Off by default (documents are usually trusted); turn on for
    # untrusted sources or compliance.
    ingest_redact: bool = field(default_factory=lambda: _b("INGEST_REDACT", False))

    # ── Knowledge graph (derived 3rd retrieval signal) ──
    graph_enabled: bool = field(default_factory=lambda: _b("GRAPH_ENABLED", True))
    graph_min_entity_len: int = field(default_factory=lambda: _i("GRAPH_MIN_ENTITY_LEN", 3))
    graph_max_entities_per_section: int = field(default_factory=lambda: _i("GRAPH_MAX_ENTITIES_PER_SECTION", 30))

    # ── Hardening ──
    tome_strict: bool = field(default_factory=lambda: _b("TOME_STRICT", False))
    rate_limit_per_min: int = field(default_factory=lambda: _i("RATE_LIMIT_PER_MIN", 120))
    rate_limit_burst: int = field(default_factory=lambda: _i("RATE_LIMIT_BURST", 0))
    max_upload_mb: int = field(default_factory=lambda: _i("MAX_UPLOAD_MB", 200))
    webhook_allow_hosts: str = field(default_factory=lambda: os.environ.get("WEBHOOK_ALLOW_HOSTS", ""))

    @property
    def model_id(self) -> str:
        return f"{self.llm_provider}:{self.llm_structure_model}"


def _dsn_from_env() -> str:
    dsn = os.environ.get("POSTGRES_DSN")
    if dsn:
        return dsn
    host = os.environ.get("PGHOST", "localhost")
    port = os.environ.get("PGPORT", "5432")
    user = os.environ.get("PGUSER", "postgres")
    pw = os.environ.get("PGPASSWORD", "")
    db = os.environ.get("PGDATABASE", "tome")
    auth = f"{user}:{pw}@" if pw else f"{user}@"
    return f"postgresql://{auth}{host}:{port}/{db}"


_cfg: Config | None = None


def get_config() -> Config:
    global _cfg
    if _cfg is None:
        _cfg = Config()
    return _cfg


def redact(dsn: str) -> str:
    import re
    return re.sub(r"://([^:]+):[^@]*@", r"://\1:***@", dsn)
