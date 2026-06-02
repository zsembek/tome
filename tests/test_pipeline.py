"""Unit tests for the pure pipeline stages (no DB / external APIs)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tome.pipeline.clean import clean
from tome.pipeline.split import build_sections, split_parts, slugify
from tome.pipeline.chunk import chunk_section
from tome.pipeline.verify import verify
from tome.pipeline.structure import looks_clean


def test_clean_removes_page_meta_and_converts_table():
    src = '<!-- PageHeader="x" -->\n# H\nтекст\n<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>'
    out = clean(src)
    assert "PageHeader" not in out
    assert "| A | B |" in out


def test_split_hierarchy():
    secs = build_sections("# A\nта\n## A1\nтб\n# B\nтв")
    assert [s.level for s in secs] == [1, 2, 1]
    assert secs[1].parent_order_index == 0          # A1 → child of A
    assert secs[2].parent_order_index is None       # B → root


def test_split_large_section():
    big = "# H\n" + ("абзац текста. " * 50 + "\n\n") * 40
    secs = build_sections(big, max_chars=1000)
    assert len(secs) > 1                              # the large section was split up


def test_split_parts_no_infinite_loop():
    parts = split_parts("a" * 250000, 100000)
    assert sum(len(p) for p in parts) == 250000


def test_chunk_overlap():
    chs = chunk_section(0, "word " * 2000, chunk_tokens=100, overlap=10)
    assert len(chs) > 1
    assert all(c.token_count <= 100 for c in chs)


def test_faithfulness_passes_when_complete():
    r = verify("Давление 0.7 МПа на входе", "# П\nДавление 0.7 МПа на входе", min_score=0.85)
    assert r.passed and r.numbers_ok


def test_faithfulness_catches_dropped_number():
    r = verify("Давление 0.7 МПа, мощность 11 kW", "Давление 0.7 МПа", min_score=0.85)
    assert not r.passed
    assert "11" in r.missing_numbers


def test_faithfulness_catches_cjk_residue():
    r = verify("Параметр 5", "Параметр 5 技术参数", min_score=0.85, target_lang="ru")
    assert not r.clean


def test_slugify():
    assert slugify("Раздел 1. Общие сведения") != ""
    assert " " not in slugify("a b c")


def test_looks_clean():
    assert looks_clean("# Заголовок\n\nНормальный длинный абзац текста про оборудование и режимы.")
    assert not looks_clean("сло\nва\nпо\nод\nно\nму")
