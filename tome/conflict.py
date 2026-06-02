"""Per-section resolution of re-import vs. manual-edit conflicts.

When a document has manual edits, a re-import is stored as a pending revision
(a snapshot of the new markdown in store). Here we do a per-section comparison
of the current document against the incoming snapshot (matched by heading) and
apply the user's choice for each section: keep_manual | take_import.
"""
from __future__ import annotations

import logging

from tome.db import DB
from tome.storage import get_store
from tome.pipeline.split import build_sections
from tome import edit as ed

log = logging.getLogger("tome.conflict")


def _incoming_sections(db: DB, doc_id: int) -> list:
    pend = db.get_pending_version(doc_id)
    if not pend or not pend.get("snapshot_object_key"):
        return []
    raw = get_store().get(pend["snapshot_object_key"])
    if not raw:
        return []
    md = raw.decode("utf-8", "replace")
    cfg_max = 8000
    return build_sections(md, max_chars=cfg_max)


def diff_sections(db: DB, doc_id: int) -> dict:
    """3-way comparison by heading: current vs incoming. Returns a list of
    sections with a change flag and both texts."""
    cur = db.list_sections(doc_id, max_depth=6)
    cur_full = {s["id"]: db.get_section(s["id"]) for s in cur}
    cur_by_head = {(_norm(s["heading"])): cur_full[s["id"]] for s in cur}

    inc = _incoming_sections(db, doc_id)
    inc_by_head = {_norm(s.heading): s for s in inc}

    rows = []
    heads = list(dict.fromkeys(list(cur_by_head) + list(inc_by_head)))
    for h in heads:
        c = cur_by_head.get(h)
        i = inc_by_head.get(h)
        c_txt = (c["content"] if c else None)
        i_txt = (i.content if i else None)
        status = ("unchanged" if c_txt == i_txt else
                  "added" if c is None else
                  "removed" if i is None else "changed")
        rows.append({
            "heading": (c["heading"] if c else i.heading),
            "section_id": (c["id"] if c else None),
            "status": status,
            "manually_edited": bool(c["manually_edited"]) if c else False,
            "current": c_txt, "incoming": i_txt,
        })
    return {"sections": rows,
            "has_conflict": any(r["status"] != "unchanged" for r in rows)}


def resolve_sections(db: DB, doc_id: int, choices: dict[str, str]) -> dict:
    """choices: {heading: 'keep_manual'|'take_import'}. Applies take_import to
    the selected sections (update_section for existing ones; adding new ones),
    leaving keep_manual unchanged. Clears the pending revision after applying."""
    diff = diff_sections(db, doc_id)
    applied = []
    for r in diff["sections"]:
        head = r["heading"]
        choice = choices.get(head, "keep_manual")
        if choice != "take_import" or r["status"] in ("unchanged", "removed"):
            continue
        if r["section_id"] and r["incoming"] is not None:
            cur = db.get_section(r["section_id"])
            db.update_section(r["section_id"], r["incoming"], rev=cur["rev"], author="import")
            applied.append({"heading": head, "action": "updated"})
        elif r["section_id"] is None and r["incoming"] is not None:
            # new section from the import — append at the end
            ed.insert_section(db, doc_id, after_section_id=None,
                              heading=head, content=r["incoming"], level=2, author="import")
            applied.append({"heading": head, "action": "added"})
    db.discard_pending(doc_id)
    return {"applied": applied, "count": len(applied), "resolved": True}


def _norm(h: str) -> str:
    return " ".join((h or "").lower().split())
