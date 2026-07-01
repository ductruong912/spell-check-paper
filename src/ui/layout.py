"""Streamlit layout helpers for structure results."""

from __future__ import annotations

import html
from typing import Any, Dict

import streamlit as st


def _format_structure_status(section_id: str, hit: Dict[str, Any]) -> str:
    ok = (hit or {}).get("status") == "ok"
    if not ok:
        return '<span class="tnt-status tnt-status--missing">Thiếu</span>'
    return '<span class="tnt-status tnt-status--ok">Có</span>'


def _structure_summary(structure: Dict[str, Any]) -> Dict[str, Any]:
    sections = (structure or {}).get("sections") or {}
    found = sum(1 for hit in sections.values() if (hit or {}).get("status") == "ok")
    total = len(sections)
    return {
        "found": found,
        "missing": max(0, total - found),
        "total": total,
    }


def structure_result_rows(structure: Dict[str, Any]) -> list[Dict[str, Any]]:
    sections = (structure or {}).get("sections") or {}
    rows = []
    for section_id, hit in sections.items():
        hit = hit or {}
        rows.append(
            {
                "section_id": section_id,
                "label": str(hit.get("label") or section_id),
                "required": bool(hit.get("required", False)),
                "status_html": _format_structure_status(section_id, hit),
            }
        )
    return rows


def render_sidebar_summary(placeholder, structure: Dict[str, Any]) -> None:
    if not structure or structure.get("error"):
        placeholder.empty()
        return

    summary = _structure_summary(structure)
    placeholder.markdown(
        '<div class="tnt-sidebar-label">Tóm tắt kiểm tra</div>'
        '<div class="tnt-sidebar-summary">'
        f'<div class="tnt-summary-card tnt-summary-card--found"><strong>{summary["found"]}</strong>Đã tìm thấy</div>'
        f'<div class="tnt-summary-card tnt-summary-card--missing"><strong>{summary["missing"]}</strong>Còn thiếu</div>'
        "</div>",
        unsafe_allow_html=True,
    )


def structure_section_html(structure: Dict[str, Any]) -> str:
    if not structure:
        return ""

    if structure.get("error"):
        message = html.escape(str(structure["error"]))
        return (
            '<div class="tnt-results tnt-results--error">'
            '<div class="tnt-results__head">'
            '<div class="tnt-results__title">Không thể kiểm tra cấu trúc</div>'
            f'<div class="tnt-results__summary">{message}</div>'
            "</div></div>"
        )

    sections = structure.get("sections") or {}
    summary = _structure_summary(structure)
    total = summary["total"]
    found = summary["found"]
    progress = (found / total * 100.0) if total else 0.0
    rows = []

    for row in structure_result_rows({"sections": sections}):
        label = html.escape(row["label"])
        required_mark = '<span class="tnt-required">*</span>' if row["required"] else ""
        rows.append(
            '<div class="tnt-result-row">'
            f'<span class="tnt-result-label">{label} {required_mark}</span>'
            f'{row["status_html"]}'
            "</div>"
        )

    
    domain_match_html = ""
    domain_match = structure.get("domain_match_suitable")
    if domain_match is not None:
        status_text = "Phù hợp" if domain_match else "Không phù hợp"
        status_class = "tnt-status--ok" if domain_match else "tnt-status--error"
        domain_match_html = (
            '<div class="tnt-results" style="margin-top: 24px;">'
            '<div class="tnt-results__head">'
            '<div class="tnt-results__title">Độ phù hợp</div>'
            '</div>'
            '<div class="tnt-result-row">'
            '<span class="tnt-result-label">Độ phù hợp với lĩnh vực</span>'
            f'<span class="tnt-status {status_class}">{status_text}</span>'
            '</div>'
            '</div>'
        )

    return (
        '<div class="tnt-results">'
        '<div class="tnt-results__head">'
        '<div class="tnt-results__title">Kết quả cấu trúc</div>'
        f'<div class="tnt-results__summary">Đã tìm thấy {found}/{total} mục yêu cầu</div>'
        '<div class="tnt-progress">'
        f'<div class="tnt-progress__bar" style="width:{progress:.1f}%"></div>'
        "</div></div>"
        f"{''.join(rows)}"
        "</div>"
        f"{domain_match_html}"
    )


def render_structure_section(structure: Dict[str, Any]) -> None:
    markup = structure_section_html(structure)
    if markup:
        st.markdown(markup, unsafe_allow_html=True)
