"""Pluggable extract layer: a single interface over Tika/Azure DI/vision-LLM/etc."""
from tome.extract.base import ExtractResult, Extractor, Figure, Page
from tome.extract.registry import extract_document, get_extractor

__all__ = ["Extractor", "ExtractResult", "Page", "Figure", "get_extractor", "extract_document"]
