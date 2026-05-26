"""Các hàm render progressive cho từng section UI."""
from __future__ import annotations

import html
import re
from typing import Dict, List, Tuple

import streamlit as st

from ui.components import highlight_html
from ui.layout import render_plagiarism_section, render_structure_section

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_IFRAME_CSS = """
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
</style>
"""

# ---------------------------------------------------------------------------
# Helpers (nội bộ)
# ---------------------------------------------------------------------------
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


def _decorate_issues_for_ui(issues: List[Dict]) -> List[Dict]:
    """Gắn ui_color cho highlight (lọc bớt token dạng email/domain)."""
    out: List[Dict] = []
    for it in (issues or []):
        t = (it.get("type") or "").strip()
        word = (it.get("word") or it.get("text") or it.get("original") or "").strip()

        it2 = dict(it)
        if t in {"en_spelling", "en_misspelling"}:
            it2["ui_color"] = "red"
        elif t.startswith("vi_"):
            it2["ui_color"] = "yellow"
        else:
            continue
        out.append(it2)
    return out

# ---------------------------------------------------------------------------
# Public helpers (dùng ở cả render lẫn workflow)
# ---------------------------------------------------------------------------

def count_issue_types(issues: List[Dict]) -> Tuple[int, int]:
    """Trả (en_count, vi_count)."""
    if not issues:
        return 0, 0
    en = vi = 0
    for it in issues:
        t = (it.get("type") or "").strip()
        if t in {"en_spelling", "en_misspelling"}:
            en += 1
        elif t.startswith("vi_"):
            vi += 1
    return en, vi

# ---------------------------------------------------------------------------
# Render functions
# ---------------------------------------------------------------------------

def render_doc_and_spell(
    placeholder,
    *,
    file_name: str,
    text: str,
    word_count: int,
    issues: List[Dict],
    spell_error: str | None,
    is_spell_ready: bool,
    spell_language: str = "en",
) -> None:
    placeholder.empty()
    with placeholder.container():
        if not text:
            st.info("Chưa có nội dung để hiển thị. Hãy upload DOCX và bấm **Kiểm tra**.")
            return

        st.caption(f"File: {file_name}")

        if spell_error:
            st.warning(f"**Kiểm tra chính tả lỗi:** {spell_error}")

        en_count, vi_count = count_issue_types(issues)

        selected_lang = "vi" if spell_language == "vi" else "en"
        selected_count = vi_count if selected_lang == "vi" else en_count
        selected_label = "Lỗi chính tả (VI)" if selected_lang == "vi" else "Lỗi chính tả (EN)"
        selected_accent = "yellow" if selected_lang == "vi" else "red"

        c1, c2 = st.columns(2)
        with c1:
            _render_metric_card("Số từ", word_count)
        with c2:
            _render_metric_card(selected_label, selected_count if is_spell_ready else "—", accent=selected_accent)

        # Khi spell xong thì render highlight; chưa xong thì show text_area nhanh
        if is_spell_ready:
            issues_for_ui = _decorate_issues_for_ui(issues)
            html_out = highlight_html(text, issues_for_ui)

            st.components.v1.html(
                f"<!doctype html><html><head>{_IFRAME_CSS}</head>"
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


def render_plagiarism(placeholder, *, data: Dict, state: str, error: str | None) -> None:
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


def render_structure(placeholder, *, data: Dict, state: str, error: str | None) -> None:
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