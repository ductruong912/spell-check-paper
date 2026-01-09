"""Spell checking module."""
from .checker import spellcheck_auto
from .reference_finder import find_references_span

__all__ = ["spellcheck_auto", "find_references_span"]
