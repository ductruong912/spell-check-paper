"""Streamlit app: kiểm tra cấu trúc bài báo DOCX."""
from __future__ import annotations

import logging
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from typing import List

import streamlit as st
from dotenv import load_dotenv

# ----------------------------
# Logging
# ----------------------------
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

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
# Global CSS
# ----------------------------
st.markdown(
    """
    <style>
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
    </style>
    """,
    unsafe_allow_html=True,
)

# ----------------------------
# Module imports
# ----------------------------
from ui.handlers import check_structure
from ui.render import render_document, render_structure
from utils import DocumentCache
from utils.config import MAX_WORKERS


def _cleanup_old_tmp_files(ttl_seconds: int = 2 * 60 * 60) -> None:
    """Best-effort cleanup for temp DOCX files left by timed-out work."""
    garbage: List[str] = st.session_state.get("_tmp_garbage", [])
    if not garbage:
        return

    now = time.time()
    kept: List[str] = []
    for path in garbage:
        try:
            if os.path.exists(path):
                age = now - os.path.getmtime(path)
                if age > ttl_seconds:
                    os.remove(path)
                else:
                    kept.append(path)
        except Exception:
            kept.append(path)
    st.session_state["_tmp_garbage"] = kept


def _reset_results_state() -> None:
    """Reset result state before a new check run."""
    st.session_state.text = ""
    st.session_state.word_count = 0
    st.session_state.file_name = ""
    st.session_state.structure = {}
    st.session_state.structure_check_error = None


# ----------------------------
# Streamlit UI
# ----------------------------
st.title("TNT Check AI")

_cleanup_old_tmp_files()

with st.sidebar:
    st.subheader("Upload bài báo")
    uploaded_file = st.file_uploader("Chọn file DOCX", type=["docx"])
    st.divider()
    run_check = st.button(
        "Kiểm tra cấu trúc",
        type="primary",
        use_container_width=True,
        disabled=(uploaded_file is None),
    )

st.session_state.setdefault("text", "")
st.session_state.setdefault("word_count", 0)
st.session_state.setdefault("file_name", "")
st.session_state.setdefault("file_size", 0)
st.session_state.setdefault("structure", {})
st.session_state.setdefault("structure_check_error", None)
st.session_state.setdefault("_tmp_garbage", [])
st.session_state.setdefault("checked_file_sig", None)

left, right = st.columns([2, 1])

with left:
    doc_placeholder = st.empty()

with right:
    structure_placeholder = st.empty()

render_document(
    doc_placeholder,
    file_name=st.session_state.file_name,
    text=st.session_state.text,
    word_count=st.session_state.word_count,
)
render_structure(
    structure_placeholder,
    data=st.session_state.structure or {},
    state="ok" if st.session_state.structure else "idle",
    error=st.session_state.structure_check_error,
)

# ----------------------------
# Main workflow
# ----------------------------
if uploaded_file and run_check:
    uploaded_file.seek(0)
    current_file_content = uploaded_file.read()
    current_file_size = len(current_file_content)
    uploaded_file.seek(0)

    _reset_results_state()
    st.session_state.file_size = current_file_size
    st.session_state.checked_file_sig = (uploaded_file.name, current_file_size)

    logger.info("Starting structure check on file: %s (size: %d bytes)", uploaded_file.name, current_file_size)

    suffix = "." + uploaded_file.name.split(".")[-1]
    tmp_path = None
    keep_tmp_for_timeout = False
    executor: ThreadPoolExecutor | None = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(current_file_content)
            tmp_path = tmp.name

        parse_started = time.monotonic()
        doc_cache = DocumentCache.from_docx(tmp_path)
        parse_elapsed = time.monotonic() - parse_started

        st.session_state.text = doc_cache.text
        st.session_state.word_count = int(getattr(doc_cache, "word_count", 0) or 0)
        st.session_state.file_name = uploaded_file.name

        render_document(
            doc_placeholder,
            file_name=st.session_state.file_name,
            text=st.session_state.text,
            word_count=st.session_state.word_count,
        )
        render_structure(structure_placeholder, data={}, state="running", error=None)

        executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        future = executor.submit(check_structure, tmp_path, doc_cache)

        try:
            result = future.result(timeout=120)
        except TimeoutError:
            keep_tmp_for_timeout = True
            future.cancel()
            st.session_state.structure = {
                "ok": False,
                "sections": {},
                "notes": [],
                "error": "Quá thời gian xử lý (>120s)",
            }
            st.session_state.structure_check_error = "Quá thời gian xử lý (>120s)"
            render_structure(
                structure_placeholder,
                data=st.session_state.structure,
                state="timeout",
                error=st.session_state.structure_check_error,
            )
        else:
            st.session_state.structure = result or {}
            st.session_state.structure_check_error = (
                st.session_state.structure.get("error")
                if not st.session_state.structure.get("ok", False)
                else None
            )
            render_structure(
                structure_placeholder,
                data=st.session_state.structure,
                state="ok",
                error=st.session_state.structure_check_error,
            )

        logger.info(
            "Finished structure check: parse_seconds=%.2f total_words=%s",
            parse_elapsed,
            st.session_state.word_count,
        )

    except Exception as exc:
        logger.error("Structure check failed: %s", exc, exc_info=True)
        st.error(f"Lỗi: {str(exc)}")
    finally:
        if tmp_path:
            if keep_tmp_for_timeout:
                st.session_state["_tmp_garbage"].append(tmp_path)
                logger.warning("Keeping temp file for deferred cleanup: %s", tmp_path)
            else:
                try:
                    os.remove(tmp_path)
                except Exception as exc:
                    logger.warning("Could not remove temp file %s: %s", tmp_path, exc)

        if executor is not None:
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
