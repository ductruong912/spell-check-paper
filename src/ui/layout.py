"""UI Streamlit: hiển thị kết quả cấu trúc và đạo văn."""

from __future__ import annotations

import html
import sys
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st

# ----------------------------
# Bootstrap import (add src to path)
# ----------------------------
root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from structure.checker import TARGETS, REQUIRED
from utils.config import MAX_PLAGIARISM_FINDINGS_DISPLAY, PLAGIARISM_PREVIEW_LENGTH

TARGET_LABELS = dict(TARGETS)


# ----------------------------
# Helpers
# ----------------------------
def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _fmt_pct(x: Any, digits: int = 2) -> str:
    try:
        return f"{float(x):.{digits}f}%"
    except Exception:
        return "—"


def _overall_to_percent(overall_score: Any) -> float:
    v = _safe_float(overall_score, 0.0)
    return v * 100.0 if v <= 1.0 else v


def _extract_top_sources(fd: Dict[str, Any], k: int = 3) -> List[Dict[str, Any]]:
    """Đọc top sources theo nhiều schema khác nhau."""
    top_sources = fd.get("top_sources")
    out: List[Dict[str, Any]] = []

    if isinstance(top_sources, list) and top_sources:
        for s in top_sources[:k]:
            if not isinstance(s, dict):
                continue
            title = (s.get("title") or "").strip() or "(Không có tiêu đề)"
            url = (s.get("url") or "").strip()
            score = _safe_float(s.get("score") or s.get("plagiat") or s.get("plagiarism") or 0.0, 0.0)
            if title or url:
                out.append({"title": title, "url": url, "score": score})
        if out:
            return out

    # Fallback: top_source_* fields
    url = (fd.get("top_source_url") or "").strip()
    title = (fd.get("top_source_title") or "").strip() or "Nguồn hàng đầu"
    score = _safe_float(fd.get("top_source_score") or 0.0, 0.0)
    if url or title:
        out.append({"title": title, "url": url, "score": score})

    # Fallback: top_source dict
    top = fd.get("top_source")
    if isinstance(top, dict):
        title2 = (top.get("title") or "").strip() or "Nguồn hàng đầu"
        url2 = (top.get("url") or "").strip()
        score2 = _safe_float(top.get("plagiat") or top.get("plagiarism") or 0.0, 0.0)
        if url2 or title2:
            if not out or (url2 and url2 != out[0].get("url")):
                out.append({"title": title2, "url": url2, "score": score2})

    return out[:k]


def _render_sources_table(sources: List[Dict[str, Any]], *, key_prefix: str) -> None:
    if not sources:
        st.caption("Không có nguồn để hiển thị.")
        return

    for idx, s in enumerate(sources, start=1):
        title = (s.get("title") or "").strip() or "(Không có tiêu đề)"
        url = (s.get("url") or "").strip()
        score = _safe_float(s.get("score"), 0.0)

        c1, c2, c3 = st.columns([7, 2, 2])
        with c1:
            st.write(f"**{idx}. {title}**")
            st.caption(url if url else "(Không có URL)")
        with c2:
            st.write(_fmt_pct(score, 2))
        with c3:
            btn_key = f"{key_prefix}_open_{idx}"
            if url:
                st.link_button("Mở nguồn", url, use_container_width=True)
            else:
                st.button("Mở nguồn", disabled=True, use_container_width=True, key=btn_key)


# ----------------------------
# Public render functions
# ----------------------------
def render_plagiarism_section(plagiarism: Dict[str, Any]) -> None:
    if not plagiarism:
        return

    if not plagiarism.get("success", False):
        st.error("Lỗi: " + str(plagiarism.get("error", "Không xác định")))
        return

    note = (plagiarism.get("note") or "").strip()
    if note:
        st.info(note)

    overall_pct = _overall_to_percent(plagiarism.get("overall_score", 0.0))
    findings = plagiarism.get("findings", []) or []
    if not isinstance(findings, list):
        st.warning("Dữ liệu findings không đúng định dạng.")
        st.json(plagiarism)
        return

    st.metric("Tỷ lệ trùng lặp", f"{overall_pct:.1f}%")

    if not findings:
        st.caption("Không có phần nào được kiểm tra.")
        return

    with st.expander(f"Chi tiết ({len(findings)} phần đã kiểm tra)", expanded=True):
        for i, fd in enumerate(findings[:MAX_PLAGIARISM_FINDINGS_DISPLAY], start=1):
            if not isinstance(fd, dict):
                st.warning(f"Finding #{i} không hợp lệ.")
                continue

            chunk_index = fd.get("chunk_index", i)
            label = fd.get("label") or f"Phần {chunk_index}"
            sim = _safe_float(fd.get("similarity", 0.0), 0.0)
            key_prefix = f"plg_{chunk_index}_{i}"

            with st.expander(f"{i}. {label} — {_fmt_pct(sim, 2)}", expanded=(i == 1)):
                # Container scrollable (HTML) để không kéo cả trang
                scrollable_html = """
                <div style="
                    max-height: 500px;
                    overflow-y: auto;
                    border: 1px solid rgba(255,255,255,0.1);
                    border-radius: 8px;
                    padding: 12px;
                    background: rgba(0,0,0,0.2);
                ">
                """

                report_link = (fd.get("report_link") or "").strip()
                if report_link:
                    scrollable_html += (
                        f'<p><a href="{report_link}" target="_blank" '
                        f'style="color: #0099ff; text-decoration: none;">'
                        f"<strong>🔗 Xem báo cáo (PlagiarismSearch)</strong></a></p>"
                    )
                else:
                    scrollable_html += '<p style="color: #999;">Không có link báo cáo.</p>'

                scrollable_html += '<p style="margin-top: 12px; margin-bottom: 8px;"><strong>Nguồn nghi ngờ:</strong></p>'

                sources = _extract_top_sources(fd, k=3)
                if sources:
                    scrollable_html += '<table style="width: 100%; border-collapse: collapse;">'
                    for idx, s in enumerate(sources, 1):
                        title = (s.get("title") or "").strip() or "(Không có tiêu đề)"
                        url = (s.get("url") or "").strip()
                        score = _safe_float(s.get("score"), 0.0)

                        if url:
                            url_display = url[:70] + "..." if len(url) > 70 else url
                            url_link = (
                                f'<a href="{url}" target="_blank" '
                                f'style="color: #0099ff; text-decoration: none;">{url_display}</a>'
                            )
                        else:
                            url_link = "(Không có URL)"

                        scrollable_html += (
                            '<tr style="border-bottom: 1px solid rgba(255,255,255,0.1);">'
                            f'<td style="padding: 8px; width: 70%;">'
                            f"<strong>{idx}. {title}</strong><br/>"
                            f'<span style="font-size: 12px; color: #999;">{url_link}</span>'
                            "</td>"
                            f'<td style="padding: 8px; text-align: center;">{_fmt_pct(score, 2)}</td>'
                            "</tr>"
                        )
                    scrollable_html += "</table>"
                else:
                    scrollable_html += '<p style="color: #999;">Không có nguồn để hiển thị.</p>'

                preview = (fd.get("text") or "").strip()
                if preview:
                    scrollable_html += '<p style="margin-top: 12px; margin-bottom: 8px;"><strong>Đoạn kiểm tra (preview):</strong></p>'
                    preview_text = preview[:PLAGIARISM_PREVIEW_LENGTH] + ("..." if len(preview) > PLAGIARISM_PREVIEW_LENGTH else "")
                    preview_text = html.escape(preview_text)
                    scrollable_html += (
                        "<pre style="
                        '"background: rgba(0,0,0,0.3); padding: 10px; border-radius: 4px; '
                        'overflow-x: auto; font-size: 13px; line-height: 1.5;">'
                        f"{preview_text}</pre>"
                    )
                else:
                    scrollable_html += '<p style="color: #999;">Không có preview.</p>'

                scrollable_html += "</div>"
                st.markdown(scrollable_html, unsafe_allow_html=True)


def render_structure_section(structure: Dict[str, Any]) -> None:
    if not structure:
        st.caption("Chưa có kết quả.")
        return

    if structure.get("error"):
        st.error(structure["error"])
        return

    sections = structure.get("sections") or {}
    html_rows: List[str] = []

    for sid in TARGET_LABELS:
        hit = sections.get(sid, {}) or {}
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
