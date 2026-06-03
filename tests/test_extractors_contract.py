"""Contract: extractor registry — interface, verified/experimental labeling,
clear errors for unknown/unconfigured adapters."""
import importlib

import pytest

from tome.extract import registry as reg

pytestmark = pytest.mark.contract


def test_status_partition_covers_all_builders():
    names = set(reg._BUILDERS)
    assert reg.VERIFIED_EXTRACTORS | reg.EXPERIMENTAL_EXTRACTORS == names
    assert not (reg.VERIFIED_EXTRACTORS & reg.EXPERIMENTAL_EXTRACTORS)


def test_extractor_status_values():
    assert reg.extractor_status("tika") == "verified"
    assert reg.extractor_status("marker") == "experimental"
    assert reg.extractor_status("does_not_exist") == "unknown"


def test_list_extractors_shape():
    items = reg.list_extractors()
    assert len(items) == len(reg._BUILDERS)
    tika = next(i for i in items if i["name"] == "tika")
    assert tika["status"] == "verified" and tika["requires"] is None
    docling = next(i for i in items if i["name"] == "docling")
    assert docling["status"] == "verified" and docling["requires"] == "docling"


def test_all_adapters_expose_interface():
    for name, (mod, cls) in reg._BUILDERS.items():
        k = getattr(importlib.import_module(mod), cls)
        for attr in ("name", "supports", "extract"):
            assert hasattr(k, attr), f"{name}: missing {attr}"


def test_unknown_extractor_raises_value_error():
    with pytest.raises(ValueError):
        reg.get_extractor("nope_not_real")


def test_key_gated_adapters_raise_clear_runtime_error():
    # httpx-based cloud adapters with no API key configured -> clear RuntimeError
    # (these always import cleanly, so the failure mode is deterministic).
    for name in ("mistral_ocr", "unstructured", "llamaparse"):
        reg._cache.pop(name, None)
        with pytest.raises(RuntimeError):
            reg.get_extractor(name)
