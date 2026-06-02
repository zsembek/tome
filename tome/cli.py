"""Tome CLI: init-db, ingest, status. A thin wrapper for scripts/CI."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tome.config import get_config, redact
from tome.db import DB


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(prog="tome", description="Tome CLI")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db", help="apply the schema")
    ig = sub.add_parser("ingest", help="ingest a file")
    ig.add_argument("file")
    ig.add_argument("--folder", default=None)
    ig.add_argument("--auto", action="store_true")
    sub.add_parser("status", help="database statistics")
    ev = sub.add_parser("eval", help="quality metrics (faithfulness + retrieval)")
    ev.add_argument("--golden", default=None, help="path to the golden-set JSON")
    gc = sub.add_parser("gc", help="GC of object store orphans (dry-run by default)")
    gc.add_argument("--apply", action="store_true", help="actually delete orphans")
    dd = sub.add_parser("dedup", help="find duplicate documents by content_hash")
    dd.add_argument("--apply", action="store_true", help="delete duplicates (keep the oldest)")
    ri = sub.add_parser("reindex", help="reprocess documents (model/prompt change)")
    ri.add_argument("--all", action="store_true", help="all documents, not just stale ones")
    args = p.parse_args(argv)

    cfg = get_config()
    print("Postgres:", redact(cfg.postgres_dsn))
    db = DB(cfg)

    if args.cmd == "init-db":
        db.init_schema()
        print("OK: schema applied")
    elif args.cmd == "ingest":
        from tome.pipeline.run import ingest
        import mimetypes
        path = Path(args.file)
        data = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        doc_id = ingest(db, workspace_id=db.default_workspace(), file_bytes=data,
                        filename=path.name, mime=mime, folder_path=args.folder,
                        auto_file=args.auto)
        print(f"OK: document {doc_id}")
    elif args.cmd == "status":
        with db.pool.connection() as conn, conn.cursor() as cur:
            for t in ("folders", "documents", "sections", "retrieval_chunks"):
                cur.execute(f"SELECT count(*) n FROM {t}")
                print(f"{t}: {cur.fetchone()['n']}")
    elif args.cmd == "eval":
        from tome.evalkit import run_eval
        import json as _j
        res = run_eval(db, args.golden, db.default_workspace())
        print(_j.dumps(res, ensure_ascii=False, indent=2))
    elif args.cmd == "gc":
        from tome.gc import collect
        import json as _j
        res = collect(db, apply=args.apply)
        print(_j.dumps(res, ensure_ascii=False, indent=2))
    elif args.cmd == "dedup":
        from tome.dedup import find_duplicates, dedup
        import json as _j
        ws = db.default_workspace()
        if args.apply:
            print(_j.dumps(dedup(db, ws), ensure_ascii=False, indent=2))
        else:
            print(_j.dumps(find_duplicates(db, ws), ensure_ascii=False, indent=2))
    elif args.cmd == "reindex":
        from tome.reindex import reindex_all
        import json as _j
        res = reindex_all(db, db.default_workspace(), only_stale=not args.all)
        print(_j.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
