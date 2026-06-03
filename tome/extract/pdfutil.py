"""PDF utilities built on PyMuPDF: splitting large files, extracting figures by bbox,
rendering a page to PNG (for the vision-OCR fallback)."""
from __future__ import annotations


import fitz  # PyMuPDF

RENDER_DPI = 200
INCH_TO_PT = 72.0


def page_count(pdf_bytes: bytes) -> int:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    n = doc.page_count
    doc.close()
    return n


def render_page_png(pdf_bytes: bytes, page_index0: int, dpi: int = RENDER_DPI) -> bytes:
    """Render an entire page to PNG (for reading with a vision model)."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_index0]
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    data = pix.tobytes("png")
    doc.close()
    return data


def extract_figure_png(pdf_bytes: bytes, page_index0: int, bbox: list[float] | None,
                       dpi: int = RENDER_DPI) -> bytes | None:
    """Crop the bbox region (PDF points) from a page into a PNG."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if page_index0 < 0 or page_index0 >= doc.page_count:
        doc.close()
        return None
    page = doc[page_index0]
    zoom = dpi / 72.0
    clip = None
    if bbox and len(bbox) >= 4:
        clip = fitz.Rect(*bbox[:4]) & page.rect
        if clip.is_empty or clip.width < 5 or clip.height < 5:
            doc.close()
            return None
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)
    data = pix.tobytes("png")
    doc.close()
    return data


def list_figures(pdf_bytes: bytes, page_index0: int, min_dim_pt: float = 40.0) -> list[list[float]]:
    """Rough detection of figures on a page -> list of bboxes (points)."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_index0]
    out: list[list[float]] = []
    try:
        for info in page.get_image_info():
            b = info.get("bbox")
            if not b:
                continue
            r = fitz.Rect(b)
            if r.width >= min_dim_pt and r.height >= min_dim_pt:
                out.append([r.x0, r.y0, r.x1, r.y1])
    except Exception:
        pass
    doc.close()
    return out


def split_pdf(pdf_bytes: bytes, max_pages: int) -> list[tuple[int, int, bytes]]:
    """Splits a PDF into chunks of <= max_pages. Returns [(start1based, end1based, bytes)]."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total = doc.page_count
    if total <= max_pages:
        doc.close()
        return [(1, total, pdf_bytes)]
    parts = []
    start = 0
    while start < total:
        end = min(start + max_pages, total) - 1
        sub = fitz.open()
        sub.insert_pdf(doc, from_page=start, to_page=end)
        buf = sub.tobytes()
        sub.close()
        parts.append((start + 1, end + 1, buf))
        start = end + 1
    doc.close()
    return parts
