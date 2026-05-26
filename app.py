"""Streamlit app: kiểm tra chính tả, cấu trúc và đạo văn cho DOCX."""
from __future__ import annotations

import logging
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
from typing import Dict, List

import streamlit as st
from dotenv import load_dotenv

# ----------------------------
# Logging
# ----------------------------
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# Giảm log ồn từ lib ngoài
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)

# ----------------------------
# Env / paths
# ----------------------------
load_dotenv()

BASE_DIR = Path(__file__).parent.resolve()
SRC_DIR = BASE_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

# ----------------------------
# Streamlit page config
# ----------------------------
logo_path = BASE_DIR / "logo" / "logo_tringhia.jpg"
st.set_page_config(
    page_title="TNT Check AI",
    page_icon=str(logo_path) if logo_path.exists() else None,
    layout="wide",
)

# ----------------------------
# Global CSS (light/dark)
# ----------------------------
st.markdown(
    """
    <style>
      /* Metric card */
      .tnt-metric {
        padding: 0.6rem 0.9rem;
        border-radius: 14px;
        border: 1px solid rgba(0,0,0,0.08);
        background: rgba(255,255,255,0.65);
        backdrop-filter: blur(6px);
      }
      .tnt-metric-title {
        font-size: 0.85rem;
        font-weight: 800;
        margin-bottom: 0.25rem;
        color: rgba(49,51,63,0.65);
      }
      .tnt-metric-value {
        font-size: 2.2rem;
        font-weight: 900;
        line-height: 1.0;
        color: rgba(49,51,63,0.95);
      }

      /* Accent */
      .tnt-accent-red { color: #ff4d4f !important; }
      .tnt-accent-yellow { color: #d4b106 !important; }

      /* Spinner */
      .tnt-loading {
        display: inline-flex;
        align-items: center;
        gap: 0;
        padding: 0;
        border: 0;
        border-radius: 0;
        background: transparent;
      }
      .tnt-spin {
        width: 24px;
        height: 24px;
        border-radius: 50%;
        border: 3px solid rgba(255,255,255,0.25);
        border-top-color: #0099ff;
        animation: tnt-rotate 0.8s linear infinite;
      }
      @keyframes tnt-rotate { to { transform: rotate(360deg); } }

      /* Dark override — spinner màu xanh ở Streamlit page scope */
      @media (prefers-color-scheme: dark) {
        .tnt-metric {
          border: 1px solid rgba(255,255,255,0.12);
          background: rgba(20,22,26,0.55);
        }
        .tnt-metric-title { color: rgba(255,255,255,0.72); }
        .tnt-metric-value { color: rgba(255,255,255,0.95); }
        .tnt-accent-yellow { color: #fadb14 !important; }
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# ----------------------------
# Module imports
# ----------------------------
from utils import DocumentCache
from utils.config import MAX_WORKERS
from ui.handlers import check_structure, check_spell, check_plagiarism
from ui.render import (
    count_issue_types,
    render_doc_and_spell,
    render_plagiarism,
    render_structure,
)

# ----------------------------
# Helpers (workflow)
# ----------------------------
def _is_spell_ok(spell_result: Dict) -> bool:
    """True nếu spell trả schema hợp lệ."""
    return isinstance(spell_result, dict) and "issues" in spell_result




def _cleanup_old_tmp_files(ttl_seconds: int = 2 * 60 * 60) -> None:
    """Dọn temp DOCX cũ (best-effort, chạy mỗi rerun)."""
    garbage: List[str] = st.session_state.get("_tmp_garbage", [])
    if not garbage:
        return

    now = time.time()
    kept: List[str] = []
    for p in garbage:
        try:
            if os.path.exists(p):
                age = now - os.path.getmtime(p)
                if age > ttl_seconds:
                    os.remove(p)
                else:
                    kept.append(p)
        except Exception:
            kept.append(p)
    st.session_state["_tmp_garbage"] = kept


def _reset_results_state() -> None:
    """Reset state khi bấm 'Kiểm tra'."""
    st.session_state.text = ""
    st.session_state.issues = []
    st.session_state.word_count = 0
    st.session_state.file_name = ""
    st.session_state.structure = {}
    st.session_state.plagiarism = {}
    st.session_state.spell_check_error = None
    st.session_state.structure_check_error = None
    st.session_state.plagiarism_check_error = None
    st.session_state.spell_checked = False


# ----------------------------
# Streamlit UI
# ----------------------------
st.title("TNT Check AI")

_cleanup_old_tmp_files()

# ----------------------------
# Sidebar - upload
# ----------------------------
with st.sidebar:
    st.subheader("Upload bài báo")
    f = st.file_uploader("Chọn file DOCX", type=["docx"])
    spell_language_label = st.radio(
        "Ngôn ngữ kiểm tra chính tả",
        options=["Tiếng Anh", "Tiếng Việt"],
        horizontal=True,
    )
    spell_language = "vi" if spell_language_label == "Tiếng Việt" else "en"
    st.divider()
    run_check = st.button(
        "Kiểm tra",
        type="primary",
        use_container_width=True,
        disabled=(f is None),
    )

# ----------------------------
# Session state
# ----------------------------
st.session_state.setdefault("text", "")
st.session_state.setdefault("issues", [])
st.session_state.setdefault("word_count", 0)
st.session_state.setdefault("file_name", "")
st.session_state.setdefault("file_size", 0)
st.session_state.setdefault("structure", {})
st.session_state.setdefault("plagiarism", {})
st.session_state.setdefault("spell_check_error", None)
st.session_state.setdefault("structure_check_error", None)
st.session_state.setdefault("plagiarism_check_error", None)
st.session_state.setdefault("_tmp_garbage", [])
st.session_state.setdefault("spell_checked", False)
st.session_state.setdefault("checked_file_sig", None)
st.session_state.setdefault("checked_spell_language", None)
st.session_state.spell_language = spell_language

# ----------------------------
# Layout placeholders
# ----------------------------
left, right = st.columns([2, 1])

with left:
    doc_placeholder = st.empty()

with right:
    plagiarism_placeholder = st.empty()
    st.divider()
    structure_placeholder = st.empty()

# Render state hiện tại (hữu ích khi rerun)
render_doc_and_spell(
    doc_placeholder,
    file_name=st.session_state.file_name,
    text=st.session_state.text,
    word_count=st.session_state.word_count,
    issues=st.session_state.issues,
    spell_error=st.session_state.spell_check_error,
    is_spell_ready=st.session_state.spell_checked,
    spell_language=st.session_state.spell_language,
)
render_plagiarism(
    plagiarism_placeholder,
    data=st.session_state.plagiarism or {},
    state="ok" if st.session_state.plagiarism else "idle",
    error=st.session_state.plagiarism_check_error,
)
render_structure(
    structure_placeholder,
    data=st.session_state.structure or {},
    state="ok" if st.session_state.structure else "idle",
    error=st.session_state.structure_check_error,
)

# ----------------------------
# Main workflow (progressive)
# ----------------------------
if f and run_check:
    # Đọc nội dung file để detect thay đổi + lưu temp
    f.seek(0)
    current_file_content = f.read()
    current_file_size = len(current_file_content)
    f.seek(0)

    _reset_results_state()
    st.session_state.file_size = current_file_size
    st.session_state.checked_file_sig = (f.name, current_file_size)
    st.session_state.checked_spell_language = st.session_state.spell_language

    logger.info("Starting checks on file: %s (size: %d bytes)", f.name, current_file_size)

    suffix = "." + f.name.split(".")[-1]
    tmp_path = None
    any_timeout = False
    ex: ThreadPoolExecutor | None = None

    try:
        # 1) Lưu file upload vào temp
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(current_file_content)
            tmp_path = tmp.name

        # 2) Parse DOCX (nhanh) để show text ngay
        t0 = time.monotonic()
        doc_cache = DocumentCache.from_docx(tmp_path)
        t_parse = time.monotonic() - t0

        st.session_state.text = doc_cache.text
        st.session_state.word_count = int(getattr(doc_cache, "word_count", 0) or 0)
        st.session_state.file_name = f.name

        render_doc_and_spell(
            doc_placeholder,
            file_name=st.session_state.file_name,
            text=st.session_state.text,
            word_count=st.session_state.word_count,
            issues=[],
            spell_error=None,
            is_spell_ready=False,
            spell_language=st.session_state.spell_language,
        )
        render_plagiarism(plagiarism_placeholder, data={}, state="running", error=None)
        render_structure(structure_placeholder, data={}, state="running", error=None)

        # 3) Chạy song song + timeout guard
        timeouts = {"spell": 60, "structure": 120, "plagiarism": 900}
        starts = {k: time.monotonic() for k in timeouts}

        ex = ThreadPoolExecutor(max_workers=MAX_WORKERS)

        futures: Dict[str, object] = {}
        futures["structure"] = ex.submit(check_structure, tmp_path, doc_cache)
        futures["spell"] = ex.submit(check_spell, doc_cache, st.session_state.spell_language)
        futures["plagiarism"] = ex.submit(check_plagiarism, tmp_path, doc_cache)

        rev = {fut: name for name, fut in futures.items()}
        pending = set(rev.keys())
        finished: set[str] = set()

        while pending:
            done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)

            now = time.monotonic()
            for name, fut in futures.items():
                if name in finished:
                    continue
                if (now - starts[name]) > timeouts[name]:
                    any_timeout = True
                    finished.add(name)
                    try:
                        fut.cancel()
                    except Exception:
                        pass
                    
                    pending.discard(fut)

                    if name == "structure":
                        st.session_state.structure = {
                            "ok": False,
                            "sections": {},
                            "notes": [],
                            "error": "Quá thời gian xử lý (>120s)",
                        }
                        st.session_state.structure_check_error = "Quá thời gian xử lý (>120s)"
                        render_structure(structure_placeholder, data=st.session_state.structure, state="timeout", error=st.session_state.structure_check_error)

                    elif name == "spell":
                        st.session_state.issues = []
                        st.session_state.spell_check_error = "Quá thời gian xử lý (>60s)"
                        st.session_state.spell_checked = True
                        render_doc_and_spell(
                            doc_placeholder,
                            file_name=st.session_state.file_name,
                            text=st.session_state.text,
                            word_count=st.session_state.word_count,
                            issues=st.session_state.issues,
                            spell_error=st.session_state.spell_check_error,
                            is_spell_ready=st.session_state.spell_checked,
                            spell_language=st.session_state.spell_language,
                        )

                    elif name == "plagiarism":
                        st.session_state.plagiarism = {
                            "success": False,
                            "overall_score": 0.0,
                            "findings": [],
                            "error": "Quá thời gian xử lý (>900s)",
                        }
                        st.session_state.plagiarism_check_error = "Quá thời gian xử lý (>900s)"
                        render_plagiarism(plagiarism_placeholder, data=st.session_state.plagiarism, state="timeout", error=st.session_state.plagiarism_check_error)

            for fut in done:
                name = rev[fut]
                if name in finished:
                    continue

                elapsed = time.monotonic() - starts[name]
                try:
                    res = fut.result()
                except Exception as e:
                    msg = str(e)[:160]
                    logger.error("%s failed: %s", name, msg)

                    if name == "structure":
                        st.session_state.structure = {"ok": False, "sections": {}, "notes": [], "error": msg}
                        st.session_state.structure_check_error = msg
                        render_structure(structure_placeholder, data=st.session_state.structure, state="error", error=msg)

                    elif name == "spell":
                        st.session_state.issues = []
                        st.session_state.spell_check_error = msg
                        st.session_state.spell_checked = True
                        render_doc_and_spell(
                            doc_placeholder,
                            file_name=st.session_state.file_name,
                            text=st.session_state.text,
                            word_count=st.session_state.word_count,
                            issues=st.session_state.issues,
                            spell_error=st.session_state.spell_check_error,
                            is_spell_ready=st.session_state.spell_checked,
                            spell_language=st.session_state.spell_language,
                        )

                    elif name == "plagiarism":
                        st.session_state.plagiarism = {"success": False, "overall_score": 0.0, "findings": [], "error": msg}
                        st.session_state.plagiarism_check_error = msg
                        render_plagiarism(plagiarism_placeholder, data=st.session_state.plagiarism, state="error", error=msg)

                else:
                    if name == "structure":
                        st.session_state.structure = res or {}
                        st.session_state.structure_check_error = (
                            st.session_state.structure.get("error")
                            if not st.session_state.structure.get("ok", False)
                            else None
                        )
                        render_structure(structure_placeholder, data=st.session_state.structure, state="ok", error=st.session_state.structure_check_error)

                    elif name == "spell":
                        spell_ok = _is_spell_ok(res)
                        spell_error = (res.get("error") if isinstance(res, dict) else "Unknown error") if not spell_ok else None
                        st.session_state.spell_check_error = spell_error
                        st.session_state.issues = (res.get("issues", []) if isinstance(res, dict) else []) or []
                        st.session_state.word_count = int((res.get("total_words", 0) if isinstance(res, dict) else 0) or st.session_state.word_count)
                        st.session_state.spell_checked = True

                        render_doc_and_spell(
                            doc_placeholder,
                            file_name=st.session_state.file_name,
                            text=st.session_state.text,
                            word_count=st.session_state.word_count,
                            issues=st.session_state.issues,
                            spell_error=st.session_state.spell_check_error,
                            is_spell_ready=st.session_state.spell_checked,
                            spell_language=st.session_state.spell_language,
                        )

                    elif name == "plagiarism":
                        st.session_state.plagiarism = res or {}
                        st.session_state.plagiarism_check_error = (
                            st.session_state.plagiarism.get("error")
                            if not st.session_state.plagiarism.get("success", False)
                            else None
                        )
                        render_plagiarism(plagiarism_placeholder, data=st.session_state.plagiarism, state="ok", error=st.session_state.plagiarism_check_error)

                finished.add(name)

        en_count, vi_count = count_issue_types(st.session_state.issues)
        selected_errors = vi_count if st.session_state.spell_language == "vi" else en_count
        logger.info(
            "Hoàn tất kiểm tra: spell_language=%s, spelling_errors=%s, tổng từ=%s",
            st.session_state.spell_language,
            selected_errors,
            st.session_state.word_count,
        )

    except Exception as e:
        logger.error("Lỗi trong quá trình kiểm tra: %s", e, exc_info=True)
        st.error(f"Lỗi: {str(e)}")
    finally:
        # Nếu có timeout: giữ tmp để thread còn dùng, dọn sau bằng _cleanup_old_tmp_files()
        if tmp_path:
            if any_timeout:
                st.session_state["_tmp_garbage"].append(tmp_path)
                logger.warning("Keeping temp file for deferred cleanup (due to timeout): %s", tmp_path)
            else:
                try:
                    os.remove(tmp_path)
                    logger.debug("Đã xóa file tạm: %s", tmp_path)
                except Exception as e:
                    logger.warning("Không thể xóa file tạm %s: %s", tmp_path, e)

        if ex is not None:
            try:
                ex.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass