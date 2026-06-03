"""Progressive render helpers for the Streamlit UI."""
from __future__ import annotations

import html
from typing import Dict

import streamlit as st
import streamlit.components.v1 as components

from ui.layout import render_structure_section

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


def render_document(
    placeholder,
    *,
    file_name: str,
    text: str,
    word_count: int,
) -> None:
    placeholder.empty()
    with placeholder.container():
        st.subheader("Nội dung bài báo")
        if not text:
            st.info("Chưa có nội dung để hiển thị. Hãy upload DOCX và bấm **Kiểm tra cấu trúc**.")
            return

        st.caption(f"File: {file_name}")
        st.metric("Tổng số từ", f"{int(word_count or 0):,}")

        body = html.escape(text)
        body = body.replace("\n", "<br>")
        components.html(f"{_IFRAME_CSS}<div class='tnt-doc'>{body}</div>", height=820, scrolling=True)


def render_structure(placeholder, *, data: Dict, state: str, error: str | None) -> None:
    """Render the structure result section by state."""
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
