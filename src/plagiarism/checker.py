# plagiarism/checker.py
from __future__ import annotations

from typing import Dict, Any, List, Optional, Tuple
import re
import os
import requests
import json
from difflib import SequenceMatcher

import numpy as np
from sentence_transformers import SentenceTransformer
from datasketch import MinHash

from .io_extract import extract_text
from .normalize import normalize_text, has_citation, text_for_embedding
from .chunking import chunk_text
from .index_store import IndexStore

# Cache global để không load model mỗi lần
_model_cache: Dict[str, SentenceTransformer] = {}

# LLM config for verification
def _get_llm_config() -> Optional[Dict[str, str]]:
    """Get LLM config from environment if available."""
    api_key = os.getenv("OPENAI_API_KEY")
    api_url = os.getenv("OPENAI_API_URL", "https://api.openai.com/v1/chat/completions")
    api_model = os.getenv("OPENAI_API_MODEL", "gpt-4o-mini")
    
    if api_key:
        return {"api_key": api_key, "api_url": api_url, "model": api_model}
    return None

_NOISE_RE = re.compile(
    r"\b("
    r"mục lục|issn|e-issn|ruot so|pm page|page|"
    r"mã số|ý kiến trao đổi|khoa học|thương mại|"
    r"ngày nhận|ngày duyệt|ngày nhận lại|"
    r"jel|doi|email"
    r")\b",
    re.IGNORECASE
)

def is_noise_chunk(ch: str) -> bool:
    if not ch:
        return True

    low = ch.lower()

    # keyword noise
    if _NOISE_RE.search(low):
        return True

    # chunk có quá nhiều <NUM> -> thường là header/mục lục
    if ch.count("<NUM>") >= 8:
        return True

    # nhiều pattern kiểu mã số (".1SMET.1132", ".2BMkt.21"...) => rất hay là mục lục
    if re.search(r"\.\d+[a-z]{2,}\w*\.\d+", low):
        return True

    # chunk quá ngắn nhưng toàn viết HOA (title/journal headings)
    letters = re.sub(r"[^A-Za-zÀ-Ỵà-ỹ]", "", ch)
    if letters:
        upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if len(ch.split()) < 60 and upper_ratio > 0.65:
            return True

    return False



def shingles(words, n=5):
    for i in range(len(words) - n + 1):
        yield " ".join(words[i:i + n])


def build_minhash(text: str, ngram=5, num_perm=128) -> MinHash:
    mh = MinHash(num_perm=num_perm)
    words = text.split()
    if len(words) < ngram:
        return mh
    for sh in shingles(words, ngram):
        mh.update(sh.encode("utf-8"))
    return mh


def classify(sim: float, cited: bool, fuzzy_sim: Optional[float] = None) -> str:
    """Classify plagiarism with fuzzy matching support."""
    # Fuzzy matching (typo/character replacement detection)
    if fuzzy_sim is not None and fuzzy_sim >= 0.88:
        if cited:
            return "verbatim_with_citation"
        if fuzzy_sim >= 0.95:
            return "verbatim"
        return "paraphrase"
    
    # Semantic similarity
    if cited:
        if sim >= 0.95:
            return "verbatim_with_citation"
        return "ignored"

    if sim >= 0.92:
        return "verbatim"
    if sim >= 0.80:
        return "paraphrase"
    return "clean"


def _get_model(model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2") -> SentenceTransformer:
    """Load model từ cache hoặc tải nếu chưa có."""
    if model_name not in _model_cache:
        _model_cache[model_name] = SentenceTransformer(model_name)
    return _model_cache[model_name]


def _fuzzy_match(text1: str, text2: str, threshold: float = 0.85) -> Tuple[bool, float]:
    """
    Fuzzy string matching để bắt lỗi typo, character replacement (a→ă).
    Returns: (is_match, similarity_score)
    """
    ratio = SequenceMatcher(None, text1.lower(), text2.lower()).ratio()
    return ratio >= threshold, ratio


def _verify_with_llm(suspicious_text: str, source_text: str, llm_config: Optional[Dict]) -> Optional[str]:
    """
    Use LLM to verify if suspected plagiarism is true positive.
    Returns: None if can't verify, or confidence score string
    """
    if not llm_config:
        return None
    
    try:
        prompt = f"""Analyze if this suspected plagiarism is accurate. 
Suspicious text (from input):
"{suspicious_text[:300]}"

Source text (from corpus):
"{source_text[:300]}"

Is this plagiarism or just coincidental similarity?
Answer with ONLY one word: "yes" (plagiarism), "no" (not plagiarism), or "uncertain"."""

        response = requests.post(
            llm_config["api_url"],
            headers={
                "Authorization": f"Bearer {llm_config['api_key']}",
                "Content-Type": "application/json"
            },
            json={
                "model": llm_config["model"],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 10,
            },
            timeout=5
        )
        
        if response.status_code == 200:
            result = response.json()
            answer = result.get("choices", [{}])[0].get("message", {}).get("content", "").lower().strip()
            return answer
    except Exception:
        pass
    
    return None


def run_plagiarism_check(
    input_path: str,
    index_dir: str = "./src/plag_index",
    topk: int = 10,
    min_chunk_words: int = 20,
    use_lsh_filter: bool = True,
    use_fuzzy_match: bool = False,  # OFF for speed (only 5-10% extra accuracy)
    use_llm_verify: bool = False,    # OFF for speed (would add 5-10s)
    batch_size: int = 64,            # Larger batch = faster embedding
) -> Dict[str, Any]:

    store = IndexStore.load(index_dir)
    model = _get_model()
    llm_config = _get_llm_config() if use_llm_verify else None

    raw = extract_text(input_path)
    norm = normalize_text(raw)
    chunks = chunk_text(norm)

    if not chunks:
        return {"overall_score": 0.0, "findings": [], "total_chunks": 0, "total_words": 0, "lsh_filtered": 0}

    # ✅ lọc noise trước khi embed
    filtered_chunks: List[str] = []
    kept_original_idx: List[int] = []
    minhashes: List[MinHash] = []
    
    for i, ch in enumerate(chunks):
        if is_noise_chunk(ch):
            continue
        if len(ch.split()) < min_chunk_words:
            continue
        filtered_chunks.append(ch)
        kept_original_idx.append(i)
        minhashes.append(build_minhash(ch))

    if not filtered_chunks:
        return {"overall_score": 0.0, "findings": [], "total_chunks": 0, "total_words": 0, "lsh_filtered": 0}

    # embedding: loại token kỹ thuật để giảm nhiễu
    embed_texts = [text_for_embedding(c) for c in filtered_chunks]
    
    # Batch embedding để tối ưu (larger batch = faster)
    vecs = model.encode(
        embed_texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
        batch_size=batch_size
    ).astype("float32")

    findings: List[Dict[str, Any]] = []
    total_words = sum(len(c.split()) for c in filtered_chunks) or 1
    suspicious_weighted_words = 0.0
    lsh_filtered_count = 0

    for local_i, ch in enumerate(filtered_chunks):
        orig_idx = kept_original_idx[local_i]
        words = ch.split()
        cited = has_citation(ch)
        mh = minhashes[local_i]

        # ⚡ LSH pre-filtering: bỏ qua chunks không có match nào trong LSH
        if use_lsh_filter:
            lsh_candidates = store.lsh.query(mh)
            if not lsh_candidates:
                lsh_filtered_count += 1
                continue

        # FAISS semantic search
        D, I = store.faiss.search(vecs[local_i].reshape(1, -1), topk)

        best_sim = float(D[0][0])
        best_i = int(I[0][0])
        best_meta = store.meta[best_i][1]  # {"doc_path":..., "chunk_text":...}
        best_source_text = best_meta.get("chunk_text", "")

        # anti false-positive: chunk ngắn + sim thấp
        if best_sim < 0.85 and len(words) < 25:
            continue

        label = classify(best_sim, cited)
        if label in ("clean", "ignored"):
            continue

        # Optional: 🔍 Fuzzy matching (slower, skip by default)
        fuzzy_sim = None
        if use_fuzzy_match:
            fuzzy_match, fuzzy_sim = _fuzzy_match(ch, best_source_text, threshold=0.85)
            # Re-classify with fuzzy result
            label = classify(best_sim, cited, fuzzy_sim if fuzzy_match else None)
            if label in ("clean", "ignored"):
                continue

        # Optional: 🤖 LLM verification (slower, skip by default)
        llm_verified = None
        if use_llm_verify and label in ("verbatim", "paraphrase"):
            llm_verified = _verify_with_llm(ch, best_source_text, llm_config)
            if llm_verified == "no":
                continue

        # trọng số: copy = 1.0, paraphrase = 0.6, citation = 0.3
        if label == "verbatim":
            weight = 1.0
        elif label == "paraphrase":
            weight = 0.6
        else:  # verbatim_with_citation
            weight = 0.3

        suspicious_weighted_words += len(words) * weight

        finding = {
            "chunk_index": orig_idx,                 
            "label": label,
            "similarity": round(best_sim, 4),
            "source_doc": best_meta.get("doc_path", ""),
            "source_text": best_source_text,
            "text": ch,
        }
        # Add optional fields only if they exist
        if fuzzy_sim is not None:
            finding["fuzzy_similarity"] = round(fuzzy_sim, 4)
        if llm_verified:
            finding["llm_verified"] = llm_verified
        findings.append(finding)

    overall = suspicious_weighted_words / total_words
    return {
        "overall_score": round(overall, 4),
        "findings": findings,
        "total_chunks": len(chunks),               
        "total_words": total_words,
        "lsh_filtered": lsh_filtered_count,
        "semantic_filtered": len(filtered_chunks),
    }
