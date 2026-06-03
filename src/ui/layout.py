"""Streamlit layout helpers for structure results."""

from __future__ import annotations

import html
import sys
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from structure.checker import REQUIRED, TARGETS

TARGET_LABELS = dict(TARGETS)


def _format_structure_status(section_id: str, hit: Dict[str, Any]) -> str:
    ok = (hit or {}).get("status") == "ok"
    if not ok:
        return "<span style='color:red; font-weight:bold;'>Không</span>"

    if section_id == "references":
        style = str((hit or {}).get("references_style") or "Unknown").strip() or "Unknown"
        return f"Có ({html.escape(style)})"

    return "Có"


def render_structure_section(structure: Dict[str, Any]) -> None:
    if not structure:
        st.caption("Chưa có kết quả.")
        return

    if structure.get("error"):
        st.error(structure["error"])
        return

    sections = structure.get("sections") or {}
    html_rows: List[str] = []

    for section_id in TARGET_LABELS:
        hit = sections.get(section_id, {}) or {}
        required = REQUIRED.get(section_id, False)

        label = html.escape(TARGET_LABELS.get(section_id, section_id))
        if required:
            label += " <span style='color:red; font-weight:bold;'>*</span>"

        status = _format_structure_status(section_id, hit)
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
