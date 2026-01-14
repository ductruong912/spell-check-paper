"""
TNT CheckAI - Document Quality Checker
Main Streamlit application for checking spelling, structure, and plagiarism.

UI behavior:
- Show DOCX context immediately after parsing (fast path).
- Run spell / structure / plagiarism in parallel.
- As each finishes, update its section immediately (no "wait for all").
"""
from __future__ import annotations

import html
import logging
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
from typing import Dict, List, Tuple

import streamlit as st
from dotenv import load_dotenv

# ─────────────────────────────────────────
# Logging Configuration
# ─────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
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
    """Returns: (en_count, vi_count, other_count)"""
    if not issues:
        return 0, 0, 0
    en = vi = other = 0
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
    """Adds ui_color field used by highlight_html."""
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
    # spellcheck returns {"issues": [...], "total_words": ... , "meta": ...}
    return isinstance(spell_result, dict) and "issues" in spell_result


def _badge(state: str) -> str:
    """
    state: idle|running|ok|error|timeout
    """
    if state == "ok":
        return "✅"
    if state == "running":
        return "⏳"
    if state == "timeout":
        return "⏱️"
    if state == "error":
        return "❌"
    return "•"


def _render_status_bar(placeholders: Dict[str, st.delta_generator.DeltaGenerator], states: Dict[str, Dict]):
    """
    placeholders: {"doc": empty, "spell": empty, "structure": empty, "plagiarism": empty}
    states: {"doc": {"state": ..., "msg": ...}, ...}
    """
    for k, ph in placeholders.items():
        info = states.get(k, {"state": "idle", "msg": ""})
        ph.markdown(f"**{_badge(info['state'])} {k.upper()}**  \n{info.get('msg','')}")


def _render_doc_and_spell(placeholder, *, file_name: str, text: str, word_count: int,
                          issues: List[Dict], spell_error: str | None, is_spell_ready: bool):
    placeholder.empty()
    with placeholder.container():
        if not text:
            st.info("Chưa có nội dung để hiển thị. Hãy upload DOCX và bấm **Kiểm tra**.")
            return

        st.caption(f"File: {file_name}")

        if spell_error:
            st.warning(f"**Kiểm tra chính tả lỗi:** {spell_error}")

        # Metrics: show word_count as soon as we have it (from doc_cache),
        # and spell metrics when spell is ready.
        en_count, vi_count, other_count = _count_issue_types(issues)

        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Số từ", word_count)
        with c2:
            st.metric("Lỗi chính tả (EN)", en_count if is_spell_ready else "—")
        with c3:
            st.metric("Nghi ngờ (VI)", vi_count if is_spell_ready else "—")

        if is_spell_ready and other_count > 0:
            st.caption(f"Khác: {other_count} (unavailable/metadata)")

        # Fast preview first, then upgrade to highlighted HTML when spell is ready
        if is_spell_ready:
            issues_for_ui = _decorate_issues_for_ui(issues)
            html_out = highlight_html(text, issues_for_ui)
            st.components.v1.html(
                f"<div style='max-height:800px;overflow:auto'>{html_out}</div>",
                height=820,
            )
        else:
            st.text_area(
                "Nội dung bài báo",
                value=text,
                height=820,
                label_visibility="collapsed",
            )


def _render_plagiarism(placeholder, *, data: Dict, state: str, error: str | None):
    placeholder.empty()
    with placeholder.container():
        if state == "running":
            st.info("Đang kiểm tra đạo văn…")
            st.caption("Kết quả sẽ hiện ngay khi xong.")
        elif state in ("error", "timeout") and not data:
            st.error(error or "Không lấy được kết quả đạo văn.")
        else:
            render_plagiarism_section(data or {})


def _render_structure(placeholder, *, data: Dict, state: str, error: str | None):
    placeholder.empty()
    with placeholder.container():
        if state == "running":
            st.info("Đang kiểm tra cấu trúc…")
            st.caption("Kết quả sẽ hiện ngay khi xong.")
        elif state in ("error", "timeout") and not data:
            st.error(error or "Không lấy được kết quả cấu trúc.")
        else:
            render_structure_section(data or {})


def _cleanup_old_tmp_files(ttl_seconds: int = 2 * 60 * 60) -> None:
    """
    Best-effort cleanup for temp DOCX files we kept (e.g., due to background tasks).
    This runs on every rerun, so it won't leak indefinitely.
    """
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
            # if already removed, drop it
        except Exception:
            kept.append(p)
    st.session_state["_tmp_garbage"] = kept


def _reset_results_state() -> None:
    st.session_state.text = ""
    st.session_state.issues = []
    st.session_state.word_count = 0
    st.session_state.file_name = ""
    st.session_state.structure = {}
    st.session_state.plagiarism = {}
    st.session_state.spell_check_error = None
    st.session_state.structure_check_error = None
    st.session_state.plagiarism_check_error = None


# ─────────────────────────────────────────
# Streamlit UI Configuration
# ─────────────────────────────────────────
SHOW_STATUS_BAR = False  # set True if you want the top status bar back

# ─────────────────────────────────────────
# Streamlit UI Configuration
# ─────────────────────────────────────────
# Logo path (dùng cho page_icon và header nếu tồn tại)
logo_path = Path(__file__).parent / "logo" / "logo_tringhia.jpg"
st.set_page_config(page_title="TNT Check AI", layout="wide")
st.set_page_config(page_title="TNT Check AI", page_icon=str(logo_path) if logo_path.exists() else None, layout="wide")
st.title("TNT Check AI")


_cleanup_old_tmp_files()

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
st.session_state.setdefault("_tmp_garbage", [])

# ─────────────────────────────────────────
# Layout placeholders (so we can update them incrementally)
# ─────────────────────────────────────────
if SHOW_STATUS_BAR:
    status_bar = st.container()
    with status_bar:
        s1, s2, s3, s4 = st.columns(4)
        st_doc = s1.empty()
        st_spell = s2.empty()
        st_plag = s3.empty()
        st_struct = s4.empty()
else:
    st_doc = st_spell = st_plag = st_struct = None

left, right = st.columns([2, 1])

with left:
    doc_placeholder = st.empty()

with right:
    plagiarism_placeholder = st.empty()
    st.divider()
    structure_placeholder = st.empty()

# Render current state by default (useful on rerun)
_render_doc_and_spell(
    doc_placeholder,
    file_name=st.session_state.file_name,
    text=st.session_state.text,
    word_count=st.session_state.word_count,
    issues=st.session_state.issues,
    spell_error=st.session_state.spell_check_error,
    is_spell_ready=bool(st.session_state.issues) or (st.session_state.spell_check_error is not None),
)
_render_plagiarism(
    plagiarism_placeholder,
    data=st.session_state.plagiarism or {},
    state="ok" if st.session_state.plagiarism else "idle",
    error=st.session_state.plagiarism_check_error,
)
_render_structure(
    structure_placeholder,
    data=st.session_state.structure or {},
    state="ok" if st.session_state.structure else "idle",
    error=st.session_state.structure_check_error,
)

# ─────────────────────────────────────────
# Main Workflow - progressive results
# ─────────────────────────────────────────
if f and run_check:
    _reset_results_state()

    # Initial status
    status_states = {
        "doc": {"state": "running", "msg": "Đang đọc DOCX…"},
        "spell": {"state": "idle", "msg": ""},
        "structure": {"state": "idle", "msg": ""},
        "plagiarism": {"state": "idle", "msg": ""},
    }
    if SHOW_STATUS_BAR:
            _render_status_bar(
            {"doc": st_doc, "spell": st_spell, "structure": st_struct, "plagiarism": st_plag},
        status_states,
    )

    logger.info("Starting checks on file: %s", f.name)

    suffix = "." + f.name.split(".")[-1]
    tmp_path = None
    any_timeout = False

    try:
        # Save upload to a temp file once
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(f.read())
            tmp_path = tmp.name

        # 1) Parse DOCX (fast) and show context immediately
        t0 = time.monotonic()
        doc_cache = DocumentCache.from_docx(tmp_path)
        t_parse = time.monotonic() - t0

        st.session_state.text = doc_cache.text
        st.session_state.word_count = int(getattr(doc_cache, "word_count", 0) or 0)
        st.session_state.file_name = f.name

        status_states["doc"] = {"state": "ok", "msg": f"Đã đọc DOCX ({t_parse:.2f}s)"}
        status_states["spell"] = {"state": "running", "msg": "Đang kiểm tra…"}
        status_states["structure"] = {"state": "running", "msg": "Đang kiểm tra…"}
        status_states["plagiarism"] = {"state": "running", "msg": "Đang kiểm tra…"}
        if SHOW_STATUS_BAR:
                _render_status_bar(
                {"doc": st_doc, "spell": st_spell, "structure": st_struct, "plagiarism": st_plag},
            status_states,
        )

        # Render doc right after parsing (no highlight yet)
        _render_doc_and_spell(
            doc_placeholder,
            file_name=st.session_state.file_name,
            text=st.session_state.text,
            word_count=st.session_state.word_count,
            issues=[],
            spell_error=None,
            is_spell_ready=False,
        )
        _render_plagiarism(plagiarism_placeholder, data={}, state="running", error=None)
        _render_structure(structure_placeholder, data={}, state="running", error=None)

        # 2) Run checks in parallel; update UI as each completes
        timeouts = {"spell": 60, "structure": 120, "plagiarism": 900}
        starts = {k: time.monotonic() for k in timeouts}

        ex = ThreadPoolExecutor(max_workers=MAX_WORKERS)

        futures: Dict[str, object] = {}
        futures["structure"] = ex.submit(check_structure, tmp_path, doc_cache)
        futures["spell"] = ex.submit(check_spell, doc_cache)
        futures["plagiarism"] = ex.submit(check_plagiarism, tmp_path, doc_cache)

        rev = {fut: name for name, fut in futures.items()}
        pending = set(rev.keys())
        finished: set[str] = set()


        while pending:
            done, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)

            # timeout guard
            now = time.monotonic()
            for name, fut in futures.items():
                if name in finished:
                    continue
                if (now - starts[name]) > timeouts[name]:
                    any_timeout = True
                    finished.add(name)
                    # best effort cancel (won't stop if already running)
                    try:
                        fut.cancel()
                    except Exception:
                        pass

                    if name == "structure":
                        st.session_state.structure = {"ok": False, "sections": {}, "notes": [], "error": "Quá thời gian xử lý (>120s)"}
                        st.session_state.structure_check_error = "Quá thời gian xử lý (>120s)"
                        status_states["structure"] = {"state": "timeout", "msg": "Timeout >120s"}
                        _render_structure(structure_placeholder, data=st.session_state.structure, state="timeout", error=st.session_state.structure_check_error)

                    elif name == "spell":
                        st.session_state.issues = []
                        st.session_state.spell_check_error = "Quá thời gian xử lý (>60s)"
                        status_states["spell"] = {"state": "timeout", "msg": "Timeout >60s"}
                        _render_doc_and_spell(
                            doc_placeholder,
                            file_name=st.session_state.file_name,
                            text=st.session_state.text,
                            word_count=st.session_state.word_count,
                            issues=st.session_state.issues,
                            spell_error=st.session_state.spell_check_error,
                            is_spell_ready=True,  # show metrics as error state
                        )

                    elif name == "plagiarism":
                        st.session_state.plagiarism = {"success": False, "overall_score": 0.0, "findings": [], "error": "Quá thời gian xử lý (>900s)"}
                        st.session_state.plagiarism_check_error = "Quá thời gian xử lý (>900s)"
                        status_states["plagiarism"] = {"state": "timeout", "msg": "Timeout >900s"}
                        _render_plagiarism(plagiarism_placeholder, data=st.session_state.plagiarism, state="timeout", error=st.session_state.plagiarism_check_error)

                    if SHOW_STATUS_BAR:
                            _render_status_bar(
                            {"doc": st_doc, "spell": st_spell, "structure": st_struct, "plagiarism": st_plag},
                        status_states,
                    )

            # handle completed futures
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
                        status_states["structure"] = {"state": "error", "msg": f"Lỗi ({elapsed:.1f}s)"}
                        _render_structure(structure_placeholder, data=st.session_state.structure, state="error", error=msg)

                    elif name == "spell":
                        st.session_state.issues = []
                        st.session_state.spell_check_error = msg
                        status_states["spell"] = {"state": "error", "msg": f"Lỗi ({elapsed:.1f}s)"}
                        _render_doc_and_spell(
                            doc_placeholder,
                            file_name=st.session_state.file_name,
                            text=st.session_state.text,
                            word_count=st.session_state.word_count,
                            issues=st.session_state.issues,
                            spell_error=st.session_state.spell_check_error,
                            is_spell_ready=True,
                        )

                    elif name == "plagiarism":
                        st.session_state.plagiarism = {"success": False, "overall_score": 0.0, "findings": [], "error": msg}
                        st.session_state.plagiarism_check_error = msg
                        status_states["plagiarism"] = {"state": "error", "msg": f"Lỗi ({elapsed:.1f}s)"}
                        _render_plagiarism(plagiarism_placeholder, data=st.session_state.plagiarism, state="error", error=msg)

                else:
                    if name == "structure":
                        st.session_state.structure = res or {}
                        st.session_state.structure_check_error = st.session_state.structure.get("error") if not st.session_state.structure.get("ok", False) else None
                        status_states["structure"] = {"state": "ok", "msg": f"Xong ({elapsed:.1f}s)"}
                        _render_structure(structure_placeholder, data=st.session_state.structure, state="ok", error=st.session_state.structure_check_error)

                    elif name == "spell":
                        spell_ok = _is_spell_ok(res)
                        spell_error = (res.get("error") if isinstance(res, dict) else "Unknown error") if not spell_ok else None
                        st.session_state.spell_check_error = spell_error
                        st.session_state.issues = (res.get("issues", []) if isinstance(res, dict) else []) or []
                        # prefer spell_result total_words if present; fallback to doc_cache.word_count
                        st.session_state.word_count = int((res.get("total_words", 0) if isinstance(res, dict) else 0) or st.session_state.word_count)

                        status_states["spell"] = {"state": "ok" if spell_error is None else "error", "msg": f"Xong ({elapsed:.1f}s)"}
                        _render_doc_and_spell(
                            doc_placeholder,
                            file_name=st.session_state.file_name,
                            text=st.session_state.text,
                            word_count=st.session_state.word_count,
                            issues=st.session_state.issues,
                            spell_error=st.session_state.spell_check_error,
                            is_spell_ready=True,
                        )

                    elif name == "plagiarism":
                        st.session_state.plagiarism = res or {}
                        st.session_state.plagiarism_check_error = st.session_state.plagiarism.get("error") if not st.session_state.plagiarism.get("success", False) else None
                        status_states["plagiarism"] = {"state": "ok", "msg": f"Xong ({elapsed:.1f}s)"}
                        _render_plagiarism(plagiarism_placeholder, data=st.session_state.plagiarism, state="ok", error=st.session_state.plagiarism_check_error)

                finished.add(name)
                if SHOW_STATUS_BAR:
                        _render_status_bar(
                        {"doc": st_doc, "spell": st_spell, "structure": st_struct, "plagiarism": st_plag},
                    status_states,
                )

        en_count, vi_count, _ = _count_issue_types(st.session_state.issues)
        logger.info("Hoàn tất kiểm tra: EN=%s, VI_suspects=%s, tổng từ=%s", en_count, vi_count, st.session_state.word_count)

    except Exception as e:
        logger.error("Lỗi trong quá trình kiểm tra: %s", e, exc_info=True)
        st.error(f"Lỗi: {str(e)}")
        status_states["doc"] = {"state": "error", "msg": "Lỗi khi xử lý"}
        if SHOW_STATUS_BAR:
                _render_status_bar(
                {"doc": st_doc, "spell": st_spell, "structure": st_struct, "plagiarism": st_plag},
            status_states,
        )
    finally:
        # IMPORTANT:
        # - If any task timed out, the worker thread might still be running and may still need tmp_path.
        # - We keep the tmp file and clean it up later via _cleanup_old_tmp_files().
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

        # Don't block the UI waiting for threads (some may already be finished).
        try:
            ex.shutdown(wait=False, cancel_futures=True)  # type: ignore[name-defined]
        except Exception:
            pass
