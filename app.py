"""
ArticleCheck AI - Document Quality Checker
Main Streamlit application for checking spelling, structure, and plagiarism.
"""
import streamlit as st
import tempfile
import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Tuple

# ─────────────────────────────────────────
# Logging Configuration
# ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# Silence verbose third-party libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)

# ─────────────────────────────────────────
# Environment Setup
# ─────────────────────────────────────────
load_dotenv()

BASE_DIR = Path(__file__).parent.resolve()
SRC_DIR = BASE_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

logger.debug(f"Base directory: {BASE_DIR}")
logger.debug(f"Source directory: {SRC_DIR}")

# ─────────────────────────────────────────
# Module Imports
# ─────────────────────────────────────────
from utils.cache import DocumentCache
from utils.config import MAX_WORKERS
from ui.handlers import check_structure, check_spell, check_plagiarism
from ui.components import highlight_html
from ui.layout import render_plagiarism_section, render_structure_section

# ─────────────────────────────────────────
# Helpers (UI)
# ─────────────────────────────────────────
def _count_issue_types(issues: List[Dict]) -> Tuple[int, int, int]:
    """
    Returns: (en_count, vi_count, other_count)
    """
    if not issues:
        return 0, 0, 0

    en = 0
    vi = 0
    other = 0
    for it in issues:
        t = (it.get("type") or "").strip()
        if t == "en_spelling":
            en += 1
        elif t.startswith("vi_"):
            vi += 1
        else:
            other += 1
    return en, vi, other


def _decorate_issues_for_ui(issues: List[Dict]) -> List[Dict]:
    """
    Adds ui_color field used by highlight_html.
    """
    out: List[Dict] = []
    for it in (issues or []):
        t = (it.get("type") or "").strip()
        it2 = dict(it)
        if t == "en_spelling":
            it2["ui_color"] = "red"
        elif t.startswith("vi_"):
            it2["ui_color"] = "yellow"
        else:
            it2["ui_color"] = "gray"
        out.append(it2)
    return out


def _is_spell_ok(spell_result: Dict) -> bool:
    # Your spellcheck returns {"issues": [...], "total_words": ... , "meta": ...}
    return isinstance(spell_result, dict) and "issues" in spell_result


# ─────────────────────────────────────────
# Streamlit UI Configuration
# ─────────────────────────────────────────
st.set_page_config(page_title="ArticleCheck AI", layout="wide")
st.title("ArticleCheck AI")

# ─────────────────────────────────────────
# Sidebar - File Upload
# ─────────────────────────────────────────
with st.sidebar:
    st.subheader("Upload bài báo")
    f = st.file_uploader("Chọn file DOCX", type=["docx"])
    st.divider()
    run_check = st.button(
        "Kiểm tra",
        type="primary",
        use_container_width=True,
        disabled=(f is None),
    )

# ─────────────────────────────────────────
# Session State Initialization
# ─────────────────────────────────────────
st.session_state.setdefault("text", "")
st.session_state.setdefault("issues", [])
st.session_state.setdefault("word_count", 0)
st.session_state.setdefault("file_name", "")
st.session_state.setdefault("structure", {})
st.session_state.setdefault("plagiarism", {})
st.session_state.setdefault("spell_check_error", None)
st.session_state.setdefault("structure_check_error", None)
st.session_state.setdefault("plagiarism_check_error", None)

# ─────────────────────────────────────────
# Main Workflow - Run Checks
# ─────────────────────────────────────────
if f and run_check:
    logger.info(f"Starting checks on file: {f.name}")
    suffix = "." + f.name.split(".")[-1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(f.read())
        tmp_path = tmp.name

    logger.debug(f"File saved to temporary path: {tmp_path}")

    try:
        with st.spinner("Đang xử lý..."):
            # Parse DOCX once and cache (avoids 3 separate file reads)
            logger.debug("Creating shared document cache...")
            doc_cache = DocumentCache.from_docx(tmp_path)
            logger.debug(f"Document cache ready: {doc_cache.word_count} words")

            # Run checks in parallel (structure + spell + plagiarism)
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
                logger.debug("Starting parallel checks (structure, spell, plagiarism)")

                fut_structure = ex.submit(check_structure, tmp_path, doc_cache)
                fut_spell = ex.submit(check_spell, doc_cache)
                fut_plag = ex.submit(check_plagiarism, tmp_path, doc_cache)

                # Collect results with timeout & safe fallbacks
                try:
                    structure = fut_structure.result(timeout=120)
                except TimeoutError:
                    logger.error("Kiểm tra cấu trúc timeout (120s)")
                    structure = {"ok": False, "sections": {}, "notes": [], "error": "Quá thời gian xử lý (>120s)"}
                except Exception as e:
                    logger.error(f"Kiểm tra cấu trúc lỗi: {str(e)[:100]}")
                    structure = {"ok": False, "sections": {}, "notes": [], "error": str(e)[:160]}

                try:
                    spell_result = fut_spell.result(timeout=60)
                except TimeoutError:
                    logger.error("Kiểm tra chính tả timeout (60s)")
                    spell_result = {"issues": [], "total_words": 0, "error": "Quá thời gian xử lý (>60s)"}
                except Exception as e:
                    logger.error(f"Kiểm tra chính tả lỗi: {str(e)[:100]}")
                    spell_result = {"issues": [], "total_words": 0, "error": str(e)[:160]}

                try:
                    plagiarism = fut_plag.result(timeout=900)
                except TimeoutError:
                    logger.error("Kiểm tra đạo văn timeout (900s)")
                    plagiarism = {"success": False, "overall_score": 0.0, "findings": [], "error": "Quá thời gian xử lý (>900s)"}
                except Exception as e:
                    logger.error(f"Kiểm tra đạo văn lỗi: {str(e)[:100]}")
                    plagiarism = {"success": False, "overall_score": 0.0, "findings": [], "error": str(e)[:160]}

            # Extract spell results
            issues = spell_result.get("issues", []) if isinstance(spell_result, dict) else []
            word_count = spell_result.get("total_words", 0) if isinstance(spell_result, dict) else 0

            # Errors for UI
            spell_ok = _is_spell_ok(spell_result)
            spell_error = (spell_result.get("error") if isinstance(spell_result, dict) else "Unknown error") if not spell_ok else None

            structure_error = structure.get("error") if not structure.get("ok", False) else None
            plagiarism_error = plagiarism.get("error") if not plagiarism.get("success", False) else None

            en_count, vi_count, _ = _count_issue_types(issues)
            logger.info(f"Hoàn tất kiểm tra: EN={en_count}, VI_suspects={vi_count}, tổng từ={word_count}")

        # Update session state
        st.session_state.text = doc_cache.text
        st.session_state.issues = issues
        st.session_state.word_count = word_count
        st.session_state.file_name = f.name
        st.session_state.structure = structure
        st.session_state.plagiarism = plagiarism
        st.session_state.spell_check_error = spell_error
        st.session_state.structure_check_error = structure_error
        st.session_state.plagiarism_check_error = plagiarism_error

    except Exception as e:
        logger.error(f"Lỗi trong quá trình kiểm tra: {e}", exc_info=True)
        st.error(f"Lỗi: {str(e)}")
    finally:
        try:
            os.remove(tmp_path)
            logger.debug(f"Đã xóa file tạm: {tmp_path}")
        except Exception as e:
            logger.warning(f"Không thể xóa file tạm {tmp_path}: {e}")

# ─────────────────────────────────────────
# Results Display Layout
# ─────────────────────────────────────────
left, right = st.columns([2, 1])

# ───── Left Column: Document Text + Spell Check ─────
with left:
    if st.session_state.text:
        st.caption(f"File: {st.session_state.file_name}")

        if st.session_state.spell_check_error:
            st.warning(f"**Kiểm tra chính tả lỗi:** {st.session_state.spell_check_error}")

        # Metrics
        en_count, vi_count, other_count = _count_issue_types(st.session_state.issues)

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Số từ", st.session_state.word_count)
        with col2:
            st.metric("Lỗi chính tả (EN)", en_count)
        with col3:
            st.metric("Nghi ngờ (VI)", vi_count)

        if other_count > 0:
            st.caption(f"Khác: {other_count} (unavailable/metadata)")

        # Highlighted text
        issues_for_ui = _decorate_issues_for_ui(st.session_state.issues)
        html = highlight_html(st.session_state.text, issues_for_ui)

        st.components.v1.html(
            f"<div style='max-height:800px;overflow:auto'>{html}</div>",
            height=820,
        )

# ───── Right Column: Plagiarism + Structure ─────
with right:
    render_plagiarism_section(st.session_state.plagiarism or {})
    st.divider()
    render_structure_section(st.session_state.structure or {})
