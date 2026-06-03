"""Config security self-audit. Surfaces insecure defaults; TOME_STRICT turns
them into a hard refusal to start."""
from __future__ import annotations

from tome.config import Config


def audit_config(cfg: Config) -> list[str]:
    """Return a list of human-readable security issues for the given config."""
    issues: list[str] = []
    if not cfg.tome_open and not (cfg.secret or "").strip():
        issues.append("TOME_SECRET is empty — asset URL signatures are weak; set a strong secret")
    dsn = cfg.postgres_dsn or ""
    if "postgres:postgres@" in dsn or ":postgres@" in dsn:
        issues.append("default Postgres password ('postgres') in use — change POSTGRES_PASSWORD")
    if cfg.s3_use and (cfg.s3_access_key == "minioadmin" or cfg.s3_secret_key == "minioadmin"):
        issues.append("default MinIO credentials ('minioadmin') in use — change S3_ACCESS_KEY/S3_SECRET_KEY")
    return issues


def enforce(cfg: Config, log) -> None:
    """Log issues; in TOME_STRICT mode, raise to block startup on insecure config."""
    issues = audit_config(cfg)
    for i in issues:
        log.warning("security: %s", i)
    if issues and cfg.tome_strict:
        raise RuntimeError("TOME_STRICT: refusing to start with insecure configuration: "
                           + "; ".join(issues))
