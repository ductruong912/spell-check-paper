import streamlit as st
import tempfile
import os
import sys
from typing import List, Dict, Any
from pathlib import Path
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

# ─────────────────────────────────────────
# Environment
# ─────────────────────────────────────────
load_dotenv()

BASE_DIR = Path(__file__).parent.resolve()
SRC_DIR = BASE_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

# ─────────────────────────────────────────
# Backend imports
# ─────────────────────────────────────────
from spell_backend import extract_text_from_docx, check_plagiarism_in_file
from check_vi_en_docx import spellcheck_auto
from structure_hybrid import check_structure_docx, TARGETS, REQUIRED

# ─────────────────────────────────────────
# UI config
# ─────────────────────────────────────────
st.set_page_config(page_title="ArticleCheck AI", layout="wide")
st.title("ArticleCheck AI")

TARGET_LABELS = dict(TARGETS)

# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────
def escape_html(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def highlight_html(text: str, issues: List[Dict]):
    issues_sorted = sorted(issues, key=lambda x: x.get("offset", 0))
    out, i = [], 0

    for it in issues_sorted:
        s = int(it.get("offset", 0))
        e = s + int(it.get("length", 0))
        if s < 0 or e <= s or s >= len(text):
            continue
        e = min(e, len(text))

        if s > i:
            out.append(escape_html(text[i:s]))

        chunk = escape_html(text[s:e])
        out.append(f"<mark style='background:#ffeb3b;color:#000'>{chunk}</mark>")
        i = e

    if i < len(text):
        out.append(escape_html(text[i:]))

    return (
        "<div style='white-space:pre-wrap;line-height:1.6;'>"
        + "".join(out)
        + "</div>"
    )


# ─────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────
with st.sidebar:
    st.subheader("Upload bài báo")
    f = st.file_uploader("Chọn file DOCX", type=["docx"])
    st.divider()
    run_check = st.button(
        "Kiểm tra",
        type="primary",
        width="stretch",   # <-- replace use_container_width=True
        disabled=(f is None),
    )

# ─────────────────────────────────────────
# Session state
# ─────────────────────────────────────────
st.session_state.setdefault("text", "")
st.session_state.setdefault("issues", [])
st.session_state.setdefault("word_count", 0)
st.session_state.setdefault("file_name", "")
st.session_state.setdefault("structure", {})
st.session_state.setdefault("plagiarism", {})

PLAG_INDEX_DIR = str(SRC_DIR / "plag_index")

# ─────────────────────────────────────────
# Parallel tasks
# ─────────────────────────────────────────
def _check_structure(file_path: str):
    report = check_structure_docx(file_path)
    return {
        "ok": report.ok,
        "sections": {k: asdict(v) for k, v in report.sections.items()},
        "notes": report.notes,
    }


def _check_spell(text: str):
    result = spellcheck_auto(text)
    return {
        "issues": result.get("issues", []),
        "word_count": result.get("word_count", 0),
    }


def _check_plagiarism(file_path: str):
    return check_plagiarism_in_file(
        file_path,
        index_dir=PLAG_INDEX_DIR,
        topk=10,
        make_report=False,
        use_lsh_filter=True,
        use_fuzzy_match=False,
        use_llm_verify=False,
    )


# ─────────────────────────────────────────
# Run checks
# ─────────────────────────────────────────
if f and run_check:
    suffix = "." + f.name.split(".")[-1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(f.read())
        tmp_path = tmp.name

    try:
        with st.spinner("Đang xử lý..."):
            text = extract_text_from_docx(tmp_path)

            with ThreadPoolExecutor(max_workers=3) as ex:
                fut_structure = ex.submit(_check_structure, tmp_path)
                fut_spell = ex.submit(_check_spell, text)
                fut_plag = ex.submit(_check_plagiarism, tmp_path)

                structure = fut_structure.result()
                spell_result = fut_spell.result()
                plagiarism = fut_plag.result()

            issues = spell_result.get("issues", [])
            word_count = spell_result.get("word_count", 0)

        st.session_state.text = text
        st.session_state.issues = issues
        st.session_state.word_count = word_count
        st.session_state.file_name = f.name
        st.session_state.structure = structure
        st.session_state.plagiarism = plagiarism

    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass

# ─────────────────────────────────────────
# Layout
# ─────────────────────────────────────────
left, right = st.columns([2, 1])

# ───────── LEFT: Text + Spell ─────────
with left:
    if st.session_state.text:
        st.caption(f"File: {st.session_state.file_name}")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Số từ", st.session_state.word_count)
        with col2:
            st.metric("Số lỗi chính tả", len(st.session_state.issues))

        html = highlight_html(st.session_state.text, st.session_state.issues)
        st.components.v1.html(
            f"<div style='max-height:800px;overflow:auto'>{html}</div>",
            height=820,
        )

# ───────── RIGHT: Structure + Plagiarism ─────────
with right:
    # --- Plagiarism ---
    st.subheader("Kiểm tra đạo văn")
    plag = st.session_state.plagiarism or {}

    if not plag:
        st.caption("Chưa có kết quả.")
    elif not plag.get("success", False):
        st.error("Lỗi: " + str(plag.get("error", "Unknown")))
    else:
        score = float(plag.get("overall_score", 0.0))  # 0..1
        findings = plag.get("findings", [])

        st.metric("Tỷ lệ trùng lặp", f"{score * 100:.1f}%")

        if plag.get("note"):
            st.caption(plag.get("note"))

        # Risk buckets (based on overall)
        if score >= 0.30:
            st.error("Nguy cơ đạo văn cao (>= 30%)")
        elif score >= 0.20:
            st.warning("Nguy cơ đạo văn (20-30%)")
        elif score >= 0.10:
            st.info("Cần xem xét (10-20%)")
        else:
            st.success("An toàn (< 10%)")

        if findings:
            with st.expander(f"Chi tiết ({len(findings)} section đã kiểm tra)"):
                for i, fd in enumerate(findings[:20]):
                    label = fd.get("label", "")
                    sim = float(fd.get("similarity", 0.0))  # % 0..100
                    cw = fd.get("checked_words", 0)

                    st.markdown(f"**{i+1}. {label}** — {sim:.2f}%  _(checked_words={cw})_")

                    top = fd.get("top_source")
                    if top and (top.get("title") or top.get("url")):
                        ts_title = top.get("title") or "Top source"
                        ts_pl = float(top.get("plagiat", 0.0))
                        ts_url = top.get("url") or ""
                        st.caption(f"Top source: {ts_title} — {ts_pl:.2f}%")
                        if ts_url:
                            st.caption(ts_url)

                    link = fd.get("report_link")
                    if link:
                        st.caption(f"Report: {link}")

                    preview = fd.get("text", "")
                    if preview:
                        st.text(preview[:300] + ("..." if len(preview) > 300 else ""))

                    st.divider()

    st.divider()

    # --- Structure ---
    st.subheader("Cấu trúc bài báo")

    structure = st.session_state.structure or {}

    if not structure:
        st.caption("Chưa có kết quả.")
    elif structure.get("error"):
        st.error(structure["error"])
    else:
        rows = []
        for sid in TARGET_LABELS:
            hit = structure["sections"].get(sid, {})
            ok = hit.get("status") == "ok"
            required = REQUIRED.get(sid, False)

            label = TARGET_LABELS.get(sid, sid)
            if required:
                label += " *"

            rows.append({"Mục": label, "Trạng thái": "Có" if ok else "Không"})

        # replace use_container_width=True
        st.dataframe(rows, width="stretch")
