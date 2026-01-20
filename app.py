"""Streamlit app: kiểm tra chính tả, cấu trúc và đạo văn cho DOCX."""
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

      /* Dark override */
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
from utils.cache import DocumentCache
from utils.config import MAX_WORKERS
from ui.handlers import check_structure, check_spell, check_plagiarism
from ui.components import highlight_html
from ui.layout import render_plagiarism_section, render_structure_section

# ----------------------------
# Helpers (UI)
# ----------------------------
def _count_issue_types(issues: List[Dict]) -> Tuple[int, int, int]:
    """Trả (en_count, vi_count, other_count)."""
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


import re

# Token kiểu "dieuanh.ln", "tmu.edu" (thường là mảnh của email/domain)
EMAIL_PART_RE = re.compile(r"^[a-z0-9._-]+$", re.I)


def _decorate_issues_for_ui(issues: List[Dict]) -> List[Dict]:
    """Gắn ui_color cho highlight (lọc bớt token dạng email/domain)."""
    out: List[Dict] = []
    for it in (issues or []):
        t = (it.get("type") or "").strip()
        word = (it.get("word") or it.get("text") or "").strip()

        if "." in word and EMAIL_PART_RE.match(word):
            continue

        it2 = dict(it)
        if t == "en_spelling":
            it2["ui_color"] = "red"
        elif t.startswith("vi_"):
            it2["ui_color"] = "yellow"
        else:
            continue
        out.append(it2)
    return out


def _is_spell_ok(spell_result: Dict) -> bool:
    """True nếu spell trả schema hợp lệ."""
    return isinstance(spell_result, dict) and "issues" in spell_result


def _render_status_bar(
    placeholders: Dict[str, st.delta_generator.DeltaGenerator],
    states: Dict[str, Dict],
):
    """Render status bar theo states."""
    for k, ph in placeholders.items():
        info = states.get(k, {"state": "idle", "msg": ""})
        ph.markdown(f"**{k.upper()}**  \n{info.get('msg','')}")


def _render_metric_card(title: str, value: str | int, accent: str | None = None) -> None:
    """Metric card tuỳ biến (hợp light/dark)."""
    accent_class = ""
    if accent == "red":
        accent_class = "tnt-accent-red"
    elif accent == "yellow":
        accent_class = "tnt-accent-yellow"

    st.markdown(
        f"""
        <div class="tnt-metric">
          <div class="tnt-metric-title {accent_class}">
            {html.escape(title)}
          </div>
          <div class="tnt-metric-value">
            {html.escape(str(value))}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_doc_and_spell(
    placeholder,
    *,
    file_name: str,
    text: str,
    word_count: int,
    issues: List[Dict],
    spell_error: str | None,
    is_spell_ready: bool,
):
    placeholder.empty()
    with placeholder.container():
        if not text:
            st.info("Chưa có nội dung để hiển thị. Hãy upload DOCX và bấm **Kiểm tra**.")
            return

        st.caption(f"File: {file_name}")

        if spell_error:
            st.warning(f"**Kiểm tra chính tả lỗi:** {spell_error}")

        en_count, vi_count, other_count = _count_issue_types(issues)

        c1, c2, c3 = st.columns(3)
        with c1:
            _render_metric_card("Số từ", word_count)
        with c2:
            _render_metric_card("Lỗi chính tả (EN)", en_count if is_spell_ready else "—", accent="red")
        with c3:
            _render_metric_card("Nghi ngờ (VI)", vi_count if is_spell_ready else "—", accent="yellow")

        # Khi spell xong thì render highlight; chưa xong thì show text_area nhanh
        if is_spell_ready:
            issues_for_ui = _decorate_issues_for_ui(issues)
            html_out = highlight_html(text, issues_for_ui)

            iframe_css = """
            <style>
            html, body { margin:0; padding:0; }
            body {
              font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
              font-size: 16px;
              line-height: 1.55;
            }
            .tnt-doc {
              padding: 14px 16px;
              max-height: 800px;
              overflow: auto;
              border-radius: 12px;
            }
            .tnt-doc span { color: inherit; }

            @media (prefers-color-scheme: light) {
              body { background: #ffffff; color: #111827; }
              .tnt-doc { background: #ffffff; }
            }
            @media (prefers-color-scheme: dark) {
              body { background: #0e1117; color: rgba(255,255,255,0.92); }
              .tnt-doc { background: #0e1117; }
            }

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
              width: 18px;
              height: 18px;
              border-radius: 50%;
              border: 3px solid rgba(255,255,255,0.25);
              border-top-color: rgba(255,255,255,0.9);
              animation: tnt-rotate 0.8s linear infinite;
            }
            @keyframes tnt-rotate { to { transform: rotate(360deg); } }
            </style>
            """

            st.components.v1.html(
                f"<!doctype html><html><head>{iframe_css}</head>"
                f"<body><div class='tnt-doc'>{html_out}</div></body></html>",
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
    """Render section đạo văn theo state."""
    placeholder.empty()
    with placeholder.container():
        st.subheader("Kiểm tra đạo văn")
        if state == "running":
            st.markdown(
                """
                <div class="tnt-loading">
                  <div class="tnt-spin"></div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        elif state in ("error", "timeout") and not data:
            st.error(error or "Không lấy được kết quả đạo văn.")
        elif state == "ok":
            render_plagiarism_section(data or {})
        else:
            st.caption("Chưa có kết quả.")


def _render_structure(placeholder, *, data: Dict, state: str, error: str | None):
    """Render section cấu trúc theo state."""
    placeholder.empty()
    with placeholder.container():
        st.subheader("Cấu trúc bài báo")
        if state == "running":
            st.markdown(
                """
                <div class="tnt-loading">
                  <div class="tnt-spin"></div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        elif state in ("error", "timeout") and not data:
            st.error(error or "Không lấy được kết quả cấu trúc.")
        elif state == "ok":
            render_structure_section(data or {})
        else:
            st.caption("Chưa có kết quả.")


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


# ----------------------------
# Streamlit UI
# ----------------------------
st.title("TNT Check AI")

_cleanup_old_tmp_files()

SHOW_STATUS_BAR = False  # bật nếu muốn status bar phía trên

# ----------------------------
# Sidebar - upload
# ----------------------------
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

# ----------------------------
# Layout placeholders
# ----------------------------
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

# Render state hiện tại (hữu ích khi rerun)
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

        status_states["doc"] = {"state": "ok", "msg": f"Đã đọc DOCX ({t_parse:.2f}s)"}
        status_states["spell"] = {"state": "running", "msg": "Đang kiểm tra…"}
        status_states["structure"] = {"state": "running", "msg": "Đang kiểm tra…"}
        status_states["plagiarism"] = {"state": "running", "msg": "Đang kiểm tra…"}

        if SHOW_STATUS_BAR:
            _render_status_bar(
                {"doc": st_doc, "spell": st_spell, "structure": st_struct, "plagiarism": st_plag},
                status_states,
            )

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

        # 3) Chạy song song + timeout guard
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

                    if name == "structure":
                        st.session_state.structure = {
                            "ok": False,
                            "sections": {},
                            "notes": [],
                            "error": "Quá thời gian xử lý (>120s)",
                        }
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
                            is_spell_ready=True,
                        )

                    elif name == "plagiarism":
                        st.session_state.plagiarism = {
                            "success": False,
                            "overall_score": 0.0,
                            "findings": [],
                            "error": "Quá thời gian xử lý (>900s)",
                        }
                        st.session_state.plagiarism_check_error = "Quá thời gian xử lý (>900s)"
                        status_states["plagiarism"] = {"state": "timeout", "msg": "Timeout >900s"}
                        _render_plagiarism(plagiarism_placeholder, data=st.session_state.plagiarism, state="timeout", error=st.session_state.plagiarism_check_error)

                    if SHOW_STATUS_BAR:
                        _render_status_bar(
                            {"doc": st_doc, "spell": st_spell, "structure": st_struct, "plagiarism": st_plag},
                            status_states,
                        )

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
                        st.session_state.structure_check_error = (
                            st.session_state.structure.get("error")
                            if not st.session_state.structure.get("ok", False)
                            else None
                        )
                        status_states["structure"] = {"state": "ok", "msg": f"Xong ({elapsed:.1f}s)"}
                        _render_structure(structure_placeholder, data=st.session_state.structure, state="ok", error=st.session_state.structure_check_error)

                    elif name == "spell":
                        spell_ok = _is_spell_ok(res)
                        spell_error = (res.get("error") if isinstance(res, dict) else "Unknown error") if not spell_ok else None
                        st.session_state.spell_check_error = spell_error
                        st.session_state.issues = (res.get("issues", []) if isinstance(res, dict) else []) or []
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
                        st.session_state.plagiarism_check_error = (
                            st.session_state.plagiarism.get("error")
                            if not st.session_state.plagiarism.get("success", False)
                            else None
                        )
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
