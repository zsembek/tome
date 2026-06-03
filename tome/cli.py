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
    mg = sub.add_parser("memory-gc", help="decay + evict stale low-value agent memories")
    mg.add_argument("--agent", default=None, help="restrict to one agent_id")
    sub.add_parser("graph-rebuild", help="rebuild the knowledge graph from documents")
    sub.add_parser("demo-seed", help="seed a few sample documents (for demos / first run)")
    ex = sub.add_parser("export-all", help="export every document as Markdown (backup)")
    ex.add_argument("dir", help="output directory")
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
    elif args.cmd == "memory-gc":
        from tome import memory
        import json as _j
        res = memory.decay_and_gc(db, ws=db.default_workspace(), agent_id=args.agent)
        print(_j.dumps(res, ensure_ascii=False, indent=2))
    elif args.cmd == "graph-rebuild":
        from tome.graph import rebuild_graph
        import json as _j
        res = rebuild_graph(db, db.default_workspace())
        print(_j.dumps(res, ensure_ascii=False, indent=2))
    elif args.cmd == "demo-seed":
        import dataclasses
        from tome.pipeline.run import ingest
        ws = db.default_workspace()
        cfg2 = dataclasses.replace(cfg, extract_primary="passthrough", extract_fallback="")
        samples = [
            ("Manuals/Pumps", "Centrifugal Pump NTs-100",
             "# Centrifugal Pump NTs-100\n\n## Specifications\n\nPressure 0.7 MPa, power 11 kW, "
             "flow 36000 L/h.\n\n## Operation\n\nCheck the oil level before start.\n"),
            ("Manuals/Valves", "Gate Valve DN50",
             "# Gate Valve DN50\n\n## Overview\n\nThe Gate Valve DN50 controls flow in the main "
             "line.\n\n## Maintenance\n\nInspect the seal yearly.\n"),
            ("Safety", "Safety Guidelines",
             "# Safety Guidelines\n\n## PPE\n\nWear protective equipment and gloves.\n\n## Lockout"
             "\n\nFollow lockout-tagout before service.\n"),
        ]
        for folder, title, md in samples:
            ingest(db, workspace_id=ws, file_bytes=md.encode("utf-8"), filename=f"{title}.md",
                   mime="text/markdown", folder_path=folder, title_override=title, cfg=cfg2)
        print(f"OK: seeded {len(samples)} demo documents")
    elif args.cmd == "export-all":
        outdir = Path(args.dir)
        outdir.mkdir(parents=True, exist_ok=True)
        ws = db.default_workspace()
        n = 0
        for d in db.list_all_documents(ws):
            md = "\n\n".join(p["content"] for p in db.get_document_parts(d["id"], None))
            safe = "".join(c if (c.isalnum() or c in " -_.") else "_" for c in d["title"])[:80]
            (outdir / f"{d['id']}_{safe or 'doc'}.md").write_text(md, encoding="utf-8")
            n += 1
        print(f"OK: exported {n} documents to {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
