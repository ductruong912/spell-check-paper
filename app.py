import streamlit as st
import tempfile
import os
import sys
from typing import List, Dict, Any
from pathlib import Path
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Load environment variables
load_dotenv()

BASE_DIR = Path(__file__).parent.resolve()
SRC_DIR = BASE_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

from spell_backend import (
    extract_text_from_docx,
    spellcheck_auto,
    check_plagiarism_in_file,
)
from structure_hybrid import check_structure_docx
from docx import Document
import re


st.set_page_config(page_title="ArticleCheck AI", layout="wide")


def escape_html(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def highlight_html(text: str, issues: List[Dict]):
    """Render text with highlights."""
    issues_sorted = sorted(issues, key=lambda x: x.get("offset", 0))
    out = []
    i = 0

    for it in issues_sorted:
        s = int(it.get("offset", 0))
        e = s + int(it.get("length", 0))
        if s < 0 or e <= s or s >= len(text):
            continue
        e = min(e, len(text))

        if s > i:
            out.append(escape_html(text[i:s]))

        chunk = escape_html(text[s:e])
        color = "#ffeb3b"
        out.append(f"<mark style='background:{color}; color:#000;'>{chunk}</mark>")
        i = e

    if i < len(text):
        out.append(escape_html(text[i:]))

    html = f"<div style='white-space:pre-wrap;line-height:1.6; color:inherit;'>{''.join(out)}</div>"
    return html


# --- UI ---
st.title("ArticleCheck AI")

with st.sidebar:
    st.subheader("Upload File")
    f = st.file_uploader("Choose DOCX", type=["docx"])

    st.divider()

    run_check = st.button(
        "Kiểm tra",
        type="primary",
        use_container_width=True,
        disabled=(f is None)
    )

# Session state
st.session_state.setdefault("text", "")
st.session_state.setdefault("issues", [])
st.session_state.setdefault("file_name", "")
st.session_state.setdefault("structure_check", {})
st.session_state.setdefault("plagiarism", {})

# Paths (absolute to avoid cwd issues)
PLAG_INDEX_DIR = str(SRC_DIR / "plag_index")
REPORT_DIR = str(BASE_DIR / "reports")


# Helper functions for parallel execution
def _extract_and_check_text(text_content: str):
    """Spellcheck và trả về issues."""
    return spellcheck_auto(text_content)


def normalize_text(text: str) -> str:
    """Normalize text for comparison (lowercase, remove extra spaces)."""
    return re.sub(r'\s+', ' ', text.lower().strip())


def _detect_reference_format(paragraphs: List[str]) -> str:
    """Detect reference format by analyzing reference section patterns"""
    if not paragraphs:
        return "Không xác định"
    
    # Look only in reference-like content (after finding "reference" keyword)
    ref_text = ""
    in_references = False
    
    for para in paragraphs:
        para_lower = para.lower()
        # Mark when we enter reference section
        if any(kw in para_lower for kw in ["reference", "tài liệu tham khảo", "bibliography", "thư mục"]):
            in_references = True
            continue
        # If in references section, collect the text
        if in_references:
            ref_text += para + " "
    
    # If no explicit reference section found, use last 20% of document
    if not ref_text:
        start_idx = max(0, len(paragraphs) - max(2, len(paragraphs) // 5))
        ref_text = " ".join(paragraphs[start_idx:])
    
    ref_text_lower = ref_text.lower()
    
    # Score each format
    scores = {
        "IEEE": 0,
        "APA": 0,
        "Vancouver": 0,
        "Chicago": 0,
        "Harvard": 0,
    }
    
    # IEEE: [1], [2], [3]... format or numeric citations
    if re.search(r'\[\d+\]', ref_text):
        scores["IEEE"] += 10
    # IEEE also often has URLs with "doi:" or "url:"
    if re.search(r'\bdoi:\s*|https?://', ref_text_lower):
        scores["IEEE"] += 5
    
    # APA: (Author, Year) or Author (Year) or "et al. (Year)"
    if re.search(r'\(\d{4}\)', ref_text):
        scores["APA"] += 8
        # APA often has "et al."
        if "et al" in ref_text_lower:
            scores["APA"] += 5
        # APA uses "Retrieved from"
        if "retrieved from" in ref_text_lower:
            scores["APA"] += 3
    
    # Vancouver: 1. Author, 2. Author... or [1] Author
    if re.search(r'^\s*\d+\.\s+[A-Z]', ref_text, re.MULTILINE):
        scores["Vancouver"] += 10
    
    # Harvard: Author Year or (Author, Year)
    if re.search(r'\b[A-Z][a-z]+,?\s+\d{4}\b', ref_text):
        scores["Harvard"] += 7
    
    # Chicago: superscript numbers or endnotes/footnotes
    if "endnote" in ref_text_lower or "footnote" in ref_text_lower or "note" in ref_text_lower:
        scores["Chicago"] += 8
    
    # Find the format with highest score
    max_format = "Không xác định"
    max_score = 0
    for fmt, score in scores.items():
        if score > max_score:
            max_score = score
            max_format = fmt
    
    # If score is too low, mark as unknown
    if max_score < 3:
        return "Không xác định"
    
    return max_format


def _check_file_structure_from_doc(doc) -> Dict[str, Any]:
    """Kiểm tra cấu trúc từ Document object (không mở file lại)"""
    
    try:
        all_text = []
        heading_texts = []
        all_paragraphs = []
        
        for para in doc.paragraphs:
            text = (para.text or "").strip()
            if text:
                all_text.append(normalize_text(text))
                all_paragraphs.append(text)
                # Check if heading
                if para.style and 'heading' in para.style.name.lower():
                    heading_texts.append(normalize_text(text))
        
        # Tables
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        text = (para.text or "").strip()
                        if text:
                            all_text.append(normalize_text(text))
                            all_paragraphs.append(text)
        
        full_text = " ".join(all_text)
        heading_text_combined = " ".join(heading_texts)
        
        found_sections = []
        missing_sections = []
        checklist = {}
        
        # Define sections - NOW SEPARATED (Vietnamese vs English titles)
        SECTIONS = {
            "a_title_vi": {"name": "Tiêu đề (tiếng Việt)", "keywords": ["title", "tiêu đề", "tên bài"], "required": True},
            "a_title_en": {"name": "Tiêu đề (tiếng Anh)", "keywords": ["title", "english", "tiếng anh"], "required": True},
            "b_authors": {"name": "Tác giả/Nhóm tác giả và thông tin liên hệ", "keywords": ["author", "tác giả", "contact", "liên hệ"], "required": True},
            "c_abstract_vi": {"name": "Tóm tắt (tiếng Việt)", "keywords": ["abstract", "tóm tắt"], "required": True},
            "c_abstract_en": {"name": "Tóm tắt (tiếng Anh)", "keywords": ["abstract", "english"], "required": True},
            "d_keywords_vi": {"name": "Từ khóa (tiếng Việt)", "keywords": ["keyword", "từ khóa"], "required": True},
            "d_keywords_en": {"name": "Từ khóa (tiếng Anh)", "keywords": ["keyword", "english"], "required": True},
            "e_introduction": {"name": "Giới thiệu/Đặt vấn đề", "keywords": ["introduction", "giới thiệu", "đặt vấn đề"], "required": True},
            "f_methods": {"name": "Vật liệu và/hoặc phương pháp nghiên cứu", "keywords": ["method", "phương pháp", "material"], "required": True},
            "g_results": {"name": "Kết quả và thảo luận", "keywords": ["result", "kết quả", "discussion", "thảo luận"], "required": True},
            "h_conclusion": {"name": "Kết luận", "keywords": ["conclusion", "kết luận"], "required": True},
            "i_appendix": {"name": "Phụ lục", "keywords": ["appendix", "phụ lục"], "required": False},
            "k_contribution": {"name": "Tuyên bố về đóng góp khoa học", "keywords": ["contribution", "đóng góp"], "required": False},
            "l_conflict": {"name": "Cam kết về mâu thuẫn lợi ích", "keywords": ["conflict", "mâu thuẫn"], "required": False},
            "m_acknowledgement": {"name": "Lời cảm ơn đối với cơ quan tài trợ", "keywords": ["acknowledgement", "cảm ơn", "thanks"], "required": False},
            "n_references": {"name": "Tài liệu tham khảo", "keywords": ["reference", "tài liệu tham khảo", "references", "bibliography"], "required": True},
        }
        
        for section_id, section_info in SECTIONS.items():
            found = False
            matched_keyword = None
            
            for keyword in section_info["keywords"]:
                norm_keyword = normalize_text(keyword)
                if norm_keyword in heading_text_combined:
                    found = True
                    matched_keyword = keyword
                    break
            
            if not found:
                for keyword in section_info["keywords"]:
                    norm_keyword = normalize_text(keyword)
                    if norm_keyword in full_text:
                        found = True
                        matched_keyword = keyword
                        break
            
            if found:
                found_sections.append(section_id)
                checklist[section_id] = {
                    "status": "found",
                    "name": section_info["name"],
                    "required": section_info.get("required", False),
                    "matched_keyword": matched_keyword,
                }
            else:
                missing_sections.append(section_id)
                checklist[section_id] = {
                    "status": "missing",
                    "name": section_info["name"],
                    "required": section_info.get("required", False),
                }
        
        # Detect reference format if references found
        ref_format = "Unknown"
        if checklist.get("n_references", {}).get("status") == "found":
            ref_format = _detect_reference_format(all_paragraphs)
            checklist["n_references"]["format"] = ref_format
        
        return {
            "ok": True,
            "found": found_sections,
            "missing": missing_sections,
            "checklist": checklist,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _check_file_structure(file_path: str):
    """Kiểm tra cấu trúc file DOCX - detect 13 required sections"""
    result = _check_file_structure_from_doc(Document(file_path))
    
    if not result.get("ok"):
        return {"error": result.get("error", "Unknown error"), "items": []}
    
    checklist = result.get("checklist", {})
    items = []
    
    # Display each section status - simple Có/Không only
    for section_id in sorted(checklist.keys()):
        section_info = checklist[section_id]
        name = section_info.get("name", section_id)
        status = section_info.get("status", "unknown")
        
        if status == "found":
            # Special case: show reference format
            if section_id == "n_references":
                ref_format = section_info.get("format", "Không xác định")
                display = f"Có ({ref_format})"
            else:
                display = "Có"
        else:
            display = "Không"
        
        items.append({name: display})
    
    return {"items": items}


def _check_plagiarism(file_path: str):
    """Kiểm tra đạo văn - dùng LSH pre-filter + FAISS (không dùng LLM để tránh tốn token)."""
    return check_plagiarism_in_file(
        file_path,
        index_dir=PLAG_INDEX_DIR,
        topk=10,
        make_report=False,
        use_lsh_filter=True,        # LSH pre-filtering (nhanh)
        use_fuzzy_match=False,      # Fuzzy matching (optional, disable để tốc độ)
        use_llm_verify=False,       # LLM verification (disable to save tokens)
    )


# Process file
if f and run_check:
    suffix = "." + f.name.split(".")[-1].lower()

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(f.read())
        tmp_path = tmp.name

    try:
        with st.spinner("Đang xử lý..."):
            # Read DOCX once
            doc = Document(tmp_path)
            
            # Extract text
            text = extract_text_from_docx(tmp_path)
            
            # Extract structure from same document object (already simplified)
            structure_result = _check_file_structure_from_doc(doc)
            if structure_result.get("ok"):
                # Convert to display items format
                checklist = structure_result.get("checklist", {})
                structure_items = []
                for section_id in sorted(checklist.keys()):
                    section_info = checklist[section_id]
                    name = section_info.get("name", section_id)
                    status = section_info.get("status", "unknown")
                    required = section_info.get("required", False)
                    
                    if status == "found":
                        # Special case: show reference format
                        if section_id == "n_references":
                            ref_format = section_info.get("format", "Không xác định")
                            display = f"Có ({ref_format})"
                        else:
                            display = "Có"
                    else:
                        display = "Không"
                    
                    structure_items.append({"name": name, "status": display, "required": required})
                structure_result = {"items": structure_items}
            else:
                structure_result = {"error": structure_result.get("error", "Unknown error"), "items": []}


        # Chạy 2 kiểm tra song song (chính tả + đạo văn, cấu trúc đã xong)
        issues = None
        plagiarism_result = None

        progress_placeholder = st.empty()

        with st.spinner("Đang kiểm tra"):
            with ThreadPoolExecutor(max_workers=2) as executor:
                # Submit 2 remaining tasks
                future_spellcheck = executor.submit(_extract_and_check_text, text)
                future_plagiarism = executor.submit(_check_plagiarism, tmp_path)

                # Chờ completion
                for i, future in enumerate(as_completed([
                    future_spellcheck,
                    future_plagiarism
                ])):
                    completed = i + 1
                    progress_placeholder.info(f"{completed}/2 kiểm tra hoàn tất...")

                # Lấy kết quả
                issues = future_spellcheck.result()
                plagiarism_result = future_plagiarism.result()

        # Save results to session
        st.session_state.text = text
        st.session_state.issues = issues
        st.session_state.file_name = f.name
        st.session_state.structure_check = structure_result
        st.session_state.plagiarism = plagiarism_result
        st.success("Xong!")

    except Exception as e:
        st.error(f"Error: {str(e)}")
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

# Layout
left, right = st.columns([2, 1])

with left:
    if st.session_state.file_name:
        st.caption(f"File: {st.session_state.file_name}")

    if st.session_state.text:
        words = st.session_state.text.split()
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Số từ", len(words))
        with col2:
            st.metric("Ký tự", len(st.session_state.text))
        with col3:
            st.metric("Lỗi chính tả", len(st.session_state.issues))

        html = highlight_html(st.session_state.text, st.session_state.issues)
        st.components.v1.html(
            f"<div style='max-height:800px; overflow-y:auto; border:1px solid #444; padding:15px; background:transparent; color:inherit;'>{html}</div>",
            height=850,
            scrolling=True
        )

with right:
    # --- Plagiarism block (independent of structure) ---
    st.subheader("Đạo văn")
    plag = st.session_state.plagiarism or {}

    if not plag:
        st.caption("Chưa có kết quả đạo văn. Upload file và bấm 'Kiểm tra'.")
    else:
        if not plag.get("success", False):
            st.error("Không chạy được kiểm tra đạo văn: " + str(plag.get("error", "")))
            st.caption(f"Index dir đang dùng: {PLAG_INDEX_DIR}")
        else:
            score = float(plag.get("overall_score", 0.0))
            findings = plag.get("findings", [])

            st.metric("Tỷ lệ nghi vấn (weighted)", f"{score*100:.2f}%")
            st.caption(
                f"Chunks: {plag.get('total_chunks', 0)} | "
                f"Words: {plag.get('total_words', 0)} | "
                f"Findings: {len(findings)}"
            )

            if score >= 0.30:
                st.error("Nguy cơ đạo văn cao (>= 30%)")
            elif score >= 0.20:
                st.warning("Nguy cơ đạo văn (20–30%)")
            elif score >= 0.10:
                st.info("Cần xem xét (10–20%)")
            else:
                st.success("Tương đối an toàn (< 10%)")

            if findings:
                import pandas as pd
                dfp = pd.DataFrame([{
                    "chunk_index": f0.get("chunk_index"),
                    "label": f0.get("label"),
                    "similarity": f0.get("similarity"),
                    "source_doc": f0.get("source_doc"),
                } for f0 in findings])

                st.dataframe(dfp, use_container_width=True)

                with st.expander("Xem chi tiết các đoạn nghi vấn"):
                    for i, fnd in enumerate(findings[:30]):
                        st.markdown(
                            f"**#{i+1}** — chunk {fnd.get('chunk_index')} — "
                            f"**{fnd.get('label')}** — sim={fnd.get('similarity')}"
                        )
                        st.caption(f"Nguồn: {fnd.get('source_doc')}")
                        st.write("**Đoạn trong bài nộp:**")
                        st.write(fnd.get("text", ""))
                        st.write("**Đoạn giống trong corpus:**")
                        st.write(fnd.get("source_text", ""))
                        st.divider()

    st.divider()

    # --- Structure block ---
    st.subheader("Cấu trúc bài báo")
    structure = st.session_state.structure_check or {}

    if not structure:
        st.caption("Chưa có kết quả cấu trúc. Upload file và bấm 'Kiểm tra'.")
    else:
        if structure.get("error"):
            st.error("Không chạy được kiểm tra cấu trúc: " + str(structure.get("error")))
        else:
            items = structure.get("items", [])
            if not items:
                st.caption("Không có dữ liệu cấu trúc.")
            else:
                # Render HTML table
                html_table = '<div style="overflow-y:auto; max-height:600px;">'
                html_table += '<table style="width:100%; border-collapse:collapse;">'
                html_table += '<thead><tr style="background:#f0f2f6; position:sticky; top:0;">'
                html_table += '<th style="padding:12px; text-align:left; border-bottom:2px solid #ddd;">Mục</th>'
                html_table += '<th style="padding:12px; text-align:center; border-bottom:2px solid #ddd; width:160px;">Trạng thái</th>'
                html_table += '</tr></thead><tbody>'

                for it in items:
                    # it is a dict with: {name, status, required}
                    label = it.get("name", "")
                    status = it.get("status", "")
                    required = it.get("required", False)
                    
                    # Add red asterisk for required sections
                    if required:
                        label_display = f'{label} <span style="color:red; font-weight:bold;">*</span>'
                    else:
                        label_display = label
                    
                    html_table += '<tr style="border-bottom:1px solid #eee;">'
                    html_table += f'<td style="padding:10px;">{label_display}</td>'
                    html_table += f'<td style="padding:10px; text-align:center; font-weight:700;">{status}</td>'
                    html_table += '</tr>'

                html_table += '</tbody></table></div>'

                st.components.v1.html(html_table, height=620, scrolling=True)
