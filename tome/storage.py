"""Object store: local FS (default) or S3/MinIO. A single interface.

Stores original documents and extracted images (figures). Keys are written
to the assets table; consistency with the DB is maintained via the outbox (deletion)."""
from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path

from tome.config import Config, get_config

log = logging.getLogger(__name__)

_INLINE_COMMENT = re.compile(r"\s#")


def _strip_inline_comment(value: str) -> str:
    """Drop a leaked inline comment from an env value.

    docker-compose's ``env_file`` parser can pass a line like
    ``STORAGE_DIR=    # note`` through verbatim, so the value arrives as
    ``"# note ..."``. A ``#`` that begins the value, or is preceded by
    whitespace, is treated as a comment marker; a ``#`` embedded inside a
    token (e.g. a path like ``/data#1``) is kept."""
    value = value.strip()
    if value.startswith("#"):
        return ""
    m = _INLINE_COMMENT.search(value)
    if m:
        return value[:m.start()].strip()
    return value


class LocalStore:
    """Filesystem backend (default). Suitable for personal/single-node."""
    backend = "local"

    def __init__(self, cfg: Config):
        # IMPORTANT: Path("") == Path(".") and it is truthy — you cannot rely on
        # `Path(x) or default`. Take STORAGE_DIR from env only if non-empty,
        # otherwise _store next to the package (in Docker — the shared volume /app/_store).
        sd = (os.environ.get("STORAGE_DIR", "") or
              str(cfg.__dict__.get("storage_dir", ""))).strip()
        # Defensive: docker-compose's env_file may pass an inline comment from
        # .env verbatim (`STORAGE_DIR=    # note`). Strip a leaked comment so the
        # store never lands in a junk, non-shared, non-persistent path.
        sd = _strip_inline_comment(sd)
        self.root = Path(sd) if sd else (Path(__file__).resolve().parent.parent / "_store")
        self.root.mkdir(parents=True, exist_ok=True)
        self._root_resolved = self.root.resolve()
        # Fail LOUDLY (not silently) if the store dir isn't writable — e.g. a stale
        # root-owned Docker volume mounted under a non-root container. Otherwise every
        # original/figure is dropped and only surfaces much later as "no stored original".
        self.writable = self._probe_writable()
        if not self.writable:
            log.error("object store at %s is NOT writable — originals/figures will be lost. "
                      "Fix the directory ownership/permissions (e.g. `docker run --rm -v "
                      "tome_store:/v busybox chown -R 10001:999 /v`) or set S3_USE=true.",
                      self.root)

    def _probe_writable(self) -> bool:
        probe = self.root / ".write_probe"
        try:
            probe.write_bytes(b"")
            probe.unlink()
            return True
        except Exception:
            return False

    def _safe(self, key: str) -> Path:
        """Path-traversal protection: the key must not escape the store root.
        Any `..`/absolute path/symbolic escape → ValueError."""
        p = (self.root / key).resolve()
        if p != self._root_resolved and self._root_resolved not in p.parents:
            raise ValueError(f"key escapes store root: {key!r}")
        return p

    def put(self, key: str, data: bytes, mime: str = "") -> str:
        p = self._safe(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return key

    def get(self, key: str) -> bytes | None:
        try:
            p = self._safe(key)
        except ValueError:
            log.warning("rejected unsafe store key: %r", key)
            return None
        return p.read_bytes() if p.exists() and p.is_file() else None

    def delete(self, key: str) -> None:
        try:
            p = self._safe(key)
        except ValueError:
            return
        if p.exists():
            p.unlink()

    def list_keys(self, prefix: str = "") -> list[str]:
        base = self.root / prefix
        if not base.exists():
            return []
        return [str(p.relative_to(self.root)).replace("\\", "/")
                for p in self.root.rglob("*") if p.is_file()]


class S3Store:
    """S3/MinIO backend (boto3). Enabled with S3_USE=true."""
    backend = "s3"

    def __init__(self, cfg: Config):
        try:
            import boto3
        except ImportError as exc:
            # S3_USE=true is an explicit opt-in; never silently fall back to the
            # local store (that would split data across backends). Fail with a
            # clear, actionable message instead of a cryptic crash-loop.
            raise RuntimeError(
                "S3_USE=true but boto3 is not installed. Install the S3 extra "
                "(`pip install tome[s3]` / add boto3 to the image) or set "
                "S3_USE=false to use the local filesystem store."
            ) from exc
        self.bucket = cfg.s3_bucket
        self.client = boto3.client(
            "s3", endpoint_url=cfg.s3_endpoint,
            aws_access_key_id=cfg.s3_access_key,
            aws_secret_access_key=cfg.s3_secret_key,
        )
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            try:
                self.client.create_bucket(Bucket=self.bucket)
            except Exception as exc:
                log.warning("bucket %s: %s", self.bucket, exc)

    def put(self, key: str, data: bytes, mime: str = "") -> str:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data,
                               ContentType=mime or "application/octet-stream")
        return key

    def get(self, key: str) -> bytes | None:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception:
            return None

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception:
            pass

    def list_keys(self, prefix: str = "") -> list[str]:
        out, token = [], None
        while True:
            kw = {"Bucket": self.bucket, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            r = self.client.list_objects_v2(**kw)
            out += [o["Key"] for o in r.get("Contents", [])]
            if not r.get("IsTruncated"):
                break
            token = r.get("NextContinuationToken")
        return out


_store = None


def get_store(cfg: Config | None = None):
    global _store
    if _store is not None:
        return _store
    cfg = cfg or get_config()
    _store = S3Store(cfg) if cfg.s3_use else LocalStore(cfg)
    # Transparency: log exactly where binaries (originals/figures/snapshots) live.
    if _store.backend == "local":
        log.info("object store: local FS at %s (set STORAGE_DIR to relocate, or "
                 "S3_USE=true for MinIO/S3 in production)", _store.root)
    else:
        log.info("object store: s3/minio bucket=%s", _store.bucket)
    return _store


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
