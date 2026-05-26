from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from .models import Issue
from .tokenizer import Token

log = logging.getLogger(__name__)

DEFAULT_DICTIONARY_BASE = Path(__file__).resolve().parents[2] / "data" / "dictionary" / "vi-DauMoi"

@lru_cache(maxsize=4)
def _load_dictionary(dictionary_base: str):
    from spylls.hunspell import Dictionary

    return Dictionary.from_files(dictionary_base)


def _iter_uy_tone_variants(word: str):
    # Hardcoded UY tone mapping removed — do not generate special-case variants.
    return ()


def _lookup_word(dictionary, word: str) -> bool:
    if dictionary.lookup(word):
        return True
    return any(dictionary.lookup(candidate) for candidate in _iter_uy_tone_variants(word))


class VietnameseHunspellChecker:
    def __init__(self, dictionary_base: Optional[str] = None):
        self.dictionary_base = str(dictionary_base or DEFAULT_DICTIONARY_BASE)

    def _dictionary(self):
        return _load_dictionary(self.dictionary_base)

    def check(self, text: str, tokens: List[Token]) -> List[Dict]:
        aff_path = Path(self.dictionary_base + ".aff")
        dic_path = Path(self.dictionary_base + ".dic")
        if not aff_path.exists() or not dic_path.exists():
            return [
                Issue(
                    id="vi_hunspell_unavailable",
                    type="unavailable",
                    offset=0,
                    length=0,
                    original="",
                    suggestions=[],
                    message=f"Vietnamese Hunspell dictionary not found: {self.dictionary_base}",
                ).to_dict()
            ]

        try:
            dictionary = self._dictionary()
        except Exception as exc:
            log.exception("Could not load Vietnamese Hunspell dictionary")
            return [
                Issue(
                    id="vi_hunspell_unavailable",
                    type="unavailable",
                    offset=0,
                    length=0,
                    original="",
                    suggestions=[],
                    message=f"Vietnamese Hunspell dictionary failed to load: {exc}",
                ).to_dict()
            ]

        issues: List[Dict] = []
        lookup_cache: Dict[str, bool] = {}
        for token in tokens:
            word = token.text.strip()
            if not word:
                continue
            cache_key = word.lower()
            if cache_key not in lookup_cache:
                try:
                    lookup_cache[cache_key] = bool(_lookup_word(dictionary, word))
                except Exception:
                    log.debug("Hunspell lookup failed for %r", word, exc_info=True)
                    lookup_cache[cache_key] = True
            ok = lookup_cache[cache_key]
            if ok:
                continue

            issues.append(
                Issue(
                    id="vi_hunspell",
                    type="vi_spelling",
                    offset=token.start,
                    length=token.length,
                    original=word,
                    suggestions=[],
                    message="Vietnamese spelling error (Hunspell)",
                ).to_dict()
            )

        return issues
