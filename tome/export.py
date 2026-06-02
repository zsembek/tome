"""Export of a document/folder as an MD bundle (zip): assembled markdown +
images. No lock — a clean markdown dump with relative links to images/."""
from __future__ import annotations

import io
import re
import zipfile

from tome.db import DB
from tome.storage import get_store
from tome.pipeline.split import slugify

_IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def export_document_bytes(db: DB, doc_id: int) -> tuple[str, bytes]:
    """Returns (filename.zip, bytes). Inside: <slug>.md + images/."""
    doc = db.get_document(doc_id)
    if not doc:
        raise ValueError("document not found")
    parts = db.get_document_parts(doc_id, None)
    md = "\n\n".join(p["content"] for p in parts)
    base = slugify(doc["title"]) or f"doc{doc_id}"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # document images → images/, redirect the links in the md
        store = get_store()
        assets = [a for a in db.list_assets(doc_id) if a["kind"] == "figure"]
        keymap = {}
        for a in assets:
            data = store.get(a["object_key"])
            if not data:
                continue
            fname = "images/" + a["object_key"].rsplit("/", 1)[-1]
            z.writestr(fname, data)
            keymap[a["object_key"]] = fname

        def fix(m):
            url = m.group(1)
            # links to /v1/assets/<key> or the key itself → local path
            key = url.split("/v1/assets/")[-1]
            return m.group(0).replace(url, keymap.get(key, url))
        md_fixed = _IMG_RE.sub(fix, md)

        front = f"---\ntitle: {doc['title']}\nsource: {doc.get('source_filename','')}\n---\n\n"
        z.writestr(f"{base}.md", front + md_fixed)
    return f"{base}.zip", buf.getvalue()


def export_folder_bytes(db: DB, ws: int, folder_id: int) -> tuple[str, bytes]:
    """Recursive export of a folder: a directory tree with one .md per document."""
    tree = {f["id"]: f for f in db.folder_tree(ws)}
    if folder_id not in tree:
        raise ValueError("folder not found")

    def path_of(fid):
        names, cur = [], fid
        while cur and cur in tree:
            names.append(slugify(tree[cur]["name"]))
            cur = tree[cur]["parent_id"]
        return "/".join(reversed(names))

    # all descendant folders (including itself)
    root_path = path_of(folder_id)
    sub_ids = [fid for fid, f in tree.items()
               if path_of(fid) == root_path or path_of(fid).startswith(root_path + "/")]

    buf = io.BytesIO()
    store = get_store()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for fid in sub_ids:
            rel = path_of(fid)
            for d in db.list_documents(fid):
                parts = db.get_document_parts(d["id"], None)
                md = "\n\n".join(p["content"] for p in parts)
                base = slugify(d["title"]) or f"doc{d['id']}"
                assets = [a for a in db.list_assets(d["id"]) if a["kind"] == "figure"]
                keymap = {}
                for a in assets:
                    data = store.get(a["object_key"])
                    if not data:
                        continue
                    fn = f"{rel}/images/{a['object_key'].rsplit('/',1)[-1]}"
                    z.writestr(fn, data)
                    keymap[a["object_key"]] = "images/" + a["object_key"].rsplit("/", 1)[-1]
                md = _IMG_RE.sub(lambda m: m.group(0).replace(
                    m.group(1), keymap.get(m.group(1).split("/v1/assets/")[-1], m.group(1))), md)
                z.writestr(f"{rel}/{base}.md", md)
    name = (root_path.rsplit("/", 1)[-1] or "folder") + ".zip"
    return name, buf.getvalue()
