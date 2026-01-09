"""Streamlit UI layout components for structure and plagiarism sections."""
import streamlit as st
from typing import Dict, Any
import sys
from pathlib import Path

# Add src to path
root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from structure.checker import TARGETS, REQUIRED
from utils.config import MAX_PLAGIARISM_FINDINGS_DISPLAY, PLAGIARISM_PREVIEW_LENGTH

# Create label dictionary for display
TARGET_LABELS = dict(TARGETS)


def render_plagiarism_section(plagiarism: Dict[str, Any]) -> None:
    """Render the plagiarism check results section."""
    st.subheader("Kiểm tra đạo văn")

    if not plagiarism:
        st.caption("Chưa có kết quả.")
    elif not plagiarism.get("success", False):
        st.error("Lỗi: " + str(plagiarism.get("error", "Không xác định")))
    else:
        score = float(plagiarism.get("overall_score", 0.0))
        findings = plagiarism.get("findings", [])

        st.metric("Tỷ lệ trùng lặp", f"{score * 100:.1f}%")

        if findings:
            with st.expander(f"Chi tiết ({len(findings)} phần đã kiểm tra)"):
                for i, fd in enumerate(findings[:MAX_PLAGIARISM_FINDINGS_DISPLAY]):
                    label = fd.get("label", "")
                    sim = float(fd.get("similarity", 0.0))

                    st.markdown(f"**{i+1}. {label}** — {sim:.2f}%")

                    top = fd.get("top_source")
                    if top and (top.get("title") or top.get("url")):
                        ts_title = top.get("title") or "Nguồn hàng đầu"
                        ts_pl = float(top.get("plagiat", 0.0))
                        ts_url = top.get("url") or ""
                        st.caption(f"Nguồn chính: {ts_title} — {ts_pl:.2f}%")
                        if ts_url:
                            st.caption(ts_url)

                    link = fd.get("report_link")
                    if link:
                        st.caption(f"Báo cáo: {link}")

                    preview = fd.get("text", "")
                    if preview:
                        st.text(
                            preview[:PLAGIARISM_PREVIEW_LENGTH]
                            + ("..." if len(preview) > PLAGIARISM_PREVIEW_LENGTH else "")
                        )

                    st.divider()


def render_structure_section(structure: Dict[str, Any]) -> None:
    """Render the structure check results section."""
    st.subheader("Cấu trúc bài báo")

    if not structure:
        st.caption("Chưa có kết quả.")
    elif structure.get("error"):
        st.error(structure["error"])
    else:
        # Build HTML table with colored text
        html_rows = []
        for sid in TARGET_LABELS:
            hit = structure["sections"].get(sid, {})
            ok = hit.get("status") == "ok"
            required = REQUIRED.get(sid, False)

            label = TARGET_LABELS.get(sid, sid)
            if required:
                label += " <span style='color:red; font-weight:bold;'>*</span>"
            
            status = "Có" if ok else "<span style='color:red; font-weight:bold;'>Không</span>"
            
            html_rows.append(f"<tr><td>{label}</td><td>{status}</td></tr>")

        table_html = f"""
        <table style='width:100%; border-collapse: collapse;'>
            <thead>
                <tr style='border-bottom: 2px solid var(--text-color);'>
                    <th style='padding: 8px; text-align: left; color: var(--text-color);'>Yêu cầu</th>
                    <th style='padding: 8px; text-align: left; color: var(--text-color);'>Trạng thái</th>
                </tr>
            </thead>
            <tbody style='color: var(--text-color);'>
                {''.join(html_rows)}
            </tbody>
        </table>
        """
        
        st.markdown(table_html, unsafe_allow_html=True)
