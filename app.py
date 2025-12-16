import streamlit as st
import tempfile
import os
import sys
import requests
from typing import List, Dict
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from spell_backend import (
    extract_text_from_docx,
    extract_text_from_pdf,
    spellcheck_auto,
)
from structure_checker import check_structure
from google_plagiarism_checker import GooglePlagiarismChecker
from text_section_extractor import (
    find_sections,
    filter_sections_for_plagiarism_check,
    get_section_summary,
    get_main_content_only
)

st.set_page_config(
    page_title="Kiểm tra chính tả và cấu trúc bài báo",
    layout="wide"
)

def highlight_html(text: str, issues: List[Dict]):
    """Render text with highlights."""
    issues_sorted = sorted(issues, key=lambda x: x["offset"])
    out = []
    i = 0
    for it in issues_sorted:
        s = it["offset"]
        e = s + it["length"]
        if s > i:
            out.append(text[i:s].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        chunk = text[s:e].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        color = "#ffeb3b"
        out.append(
            f"<mark style='background:{color};'>{chunk}</mark>"
        )
        i = e
    if i < len(text):
        out.append(text[i:].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    html = f"<div style='white-space:pre-wrap;line-height:1.6;'>{''.join(out)}</div>"
    return html

def check_plagiarism_google(text: str, api_key: str, search_engine_id: str, max_queries: int = 10) -> Dict:
    """
    Check plagiarism using Google Custom Search API (FREE - 100 searches/day).
    Returns plagiarism score and sources.
    """
    if not api_key or not search_engine_id:
        return {"error": "API key and Search Engine ID are required"}
    
    try:
        checker = GooglePlagiarismChecker(api_key, search_engine_id)
        result = checker.check_plagiarism(text, max_queries=max_queries, delay=1.0)
        return result
    except Exception as e:
        return {
            "success": False,
            "error": f"Error: {str(e)}"
        }

# --- UI ---
st.title("Kiểm tra chính tả và cấu trúc bài báo")

with st.sidebar:
    st.subheader("Upload File")
    f = st.file_uploader("Choose DOCX or PDF", type=["docx", "pdf"])
    
    st.divider()
    
    # Plagiarism checker
    st.subheader("Kiểm tra đạo văn")
    
    google_api_key = os.getenv("GOOGLE_API_KEY", "")
    google_engine_id = os.getenv("GOOGLE_SEARCH_ENGINE_ID", "")
    
    if google_api_key and google_engine_id:
        enable_plagiarism = st.checkbox(
            "Bật kiểm tra đạo văn",
            value=False,
            help="100 searches miễn phí/ngày"
        )
        
        if enable_plagiarism:
            max_queries = st.slider(
                "Số lượng truy vấn", 
                5, 20, 10,
                help="Mỗi truy vấn = 1 lần tìm kiếm Google. Miễn phí: 100 searches/ngày"
            )
            
            # Section selection
            st.markdown("**Chọn phần cần kiểm tra:**")
            check_mode = st.radio(
                "Chế độ kiểm tra:",
                ["Chỉ nội dung chính", "Tùy chọn sections", "Toàn bộ văn bản"],
                index=0,
                help="Nội dung chính = Mở đầu + Phương pháp + Kết quả + Thảo luận + Kết luận (bỏ qua Tóm tắt, Tài liệu tham khảo)"
            )
            
            # Show section selector if mode is "Tùy chọn sections" and sections exist
            if check_mode == "Tùy chọn sections":
                if st.session_state.sections:
                    st.markdown("**Chọn sections:**")
                    selected = []
                    for section in st.session_state.sections:
                        if st.checkbox(
                            f"{section['title']} ({section['word_count']} từ)",
                            key=f"section_{section['title']}"
                        ):
                            selected.append(section['title'])
                    st.session_state.selected_sections = selected
                else:
                    st.info("ℹ️ Upload file và nhấn 'Kiểm tra' lần đầu để thấy danh sách sections")
        else:
            max_queries = 10
            check_mode = "Chỉ nội dung chính"
    else:
        st.warning("⚠️ Thiếu Google API credentials trong .env")
        st.info("📝 Xem hướng dẫn trong file GOOGLE_SETUP.md")
        enable_plagiarism = False
        max_queries = 10
    
    st.divider()
    
    run_check = st.button(
        "Kiểm tra",
        type="primary",
        use_container_width=True,
        disabled=(f is None)
    )

# Session state
if "text" not in st.session_state:
    st.session_state.text = ""
if "issues" not in st.session_state:
    st.session_state.issues = []
if "file_name" not in st.session_state:
    st.session_state.file_name = ""
if "structure_check" not in st.session_state:
    st.session_state.structure_check = {}
if "plagiarism_result" not in st.session_state:
    st.session_state.plagiarism_result = None
if "sections" not in st.session_state:
    st.session_state.sections = []
if "selected_sections" not in st.session_state:
    st.session_state.selected_sections = []

# Process file
if f and run_check:
    suffix = "." + f.name.split(".")[-1].lower()
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(f.read())
        tmp_path = tmp.name

    try:
        with st.spinner("Processing..."):
            if suffix == ".docx":
                text = extract_text_from_docx(tmp_path)
            else:
                text = extract_text_from_pdf(tmp_path)
            
            # Spell check with auto language detection
            issues = spellcheck_auto(text)
            
            # Structure check
            structure_result = check_structure(text)
            
            # Extract sections
            sections = find_sections(text)
            
            # Plagiarism check if enabled
            plagiarism_result = None
            if enable_plagiarism:
                # Determine what text to check based on mode
                text_to_check = text
                
                if check_mode == "Chỉ nội dung chính":
                    text_to_check = get_main_content_only(text)
                    st.info(f"📝 Đang kiểm tra chỉ nội dung chính (đã loại bỏ Tóm tắt, Tài liệu tham khảo, v.v.)")
                elif check_mode == "Tùy chọn sections":
                    # Get selected sections from session state
                    if st.session_state.selected_sections:
                        selected_contents = []
                        for section in sections:
                            if section['title'] in st.session_state.selected_sections:
                                selected_contents.append(section['content'])
                        text_to_check = '\n\n'.join(selected_contents)
                        st.info(f"📝 Đang kiểm tra {len(st.session_state.selected_sections)} sections đã chọn")
                    else:
                        st.warning("⚠️ Chưa chọn section nào, sẽ kiểm tra nội dung chính")
                        text_to_check = get_main_content_only(text)
                else:
                    st.info("📝 Đang kiểm tra toàn bộ văn bản")
                
                with st.spinner("Checking plagiarism with Google Search (FREE)..."):
                    plagiarism_result = check_plagiarism_google(
                        text_to_check, 
                        google_api_key, 
                        google_engine_id,
                        max_queries=max_queries
                    )

        st.session_state.text = text
        st.session_state.issues = issues
        st.session_state.file_name = f.name
        st.session_state.structure_check = structure_result
        st.session_state.plagiarism_result = plagiarism_result
        st.session_state.sections = sections

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
    st.subheader("Xem trước văn bản với đánh dấu lỗi chính tả")
    
    if st.session_state.file_name:
        st.caption(f"File: {st.session_state.file_name}")
    
    # Word count statistics
    if st.session_state.text:
        words = st.session_state.text.split()
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Số từ", len(words))
        with col2:
            st.metric("Ký tự", len(st.session_state.text))
        with col3:
            st.metric("Lỗi", len(st.session_state.issues))
        with col4:
            st.metric("Sections", len(st.session_state.sections))
    
    # Show sections summary
    if st.session_state.sections:
        with st.expander("Danh sách sections"):
            filtered_sections = filter_sections_for_plagiarism_check(st.session_state.sections)
            
            st.markdown("**Sections được tìm thấy:**")
            for i, section in enumerate(st.session_state.sections, 1):
                is_filtered = section in filtered_sections
                icon = "✅" if is_filtered else "⏭️"
                status = "Sẽ check" if is_filtered else "Bỏ qua"
                st.write(f"{icon} {i}. **{section['title']}** - {section['word_count']} từ ({status})")
            
            st.caption("✅ = Sẽ kiểm tra khi chọn 'Chỉ nội dung chính' | ⏭️ = Bỏ qua (tham khảo, tóm tắt...)")
    
    # Plagiarism check results
    if st.session_state.plagiarism_result:
        st.divider()
        st.subheader("Kết quả kiểm tra đạo văn")
        
        result = st.session_state.plagiarism_result
        
        if result.get("success"):
            col1, col2, col3 = st.columns(3)
            
            with col1:
                plagiarism_score = result.get("plagiarism_score", 0)
                st.metric(
                    "Tỷ lệ trùng lặp",
                    f"{plagiarism_score}%",
                    delta=None,
                    help="% số truy vấn tìm thấy kết quả tương tự"
                )
            
            with col2:
                queries_checked = result.get("queries_checked", 0)
                st.metric("Truy vấn đã kiểm tra", queries_checked)
            
            with col3:
                sources_found = result.get("sources_found", 0)
                st.metric("Nguồn tìm thấy", sources_found)
            
            st.caption(result.get("message", ""))
            
            # Show sources if available
            sources = result.get("sources", [])
            if sources:
                with st.expander(f"Nguồn trùng lặp ({len(sources)})"):
                    for idx, source in enumerate(sources, 1):
                        st.write(f"**{idx}. {source.get('title', 'Unknown')}**")
                        st.caption(f"{source.get('url', 'N/A')}")
                        st.caption(f"Độ tương tự: {source.get('similarity', 0)}%")
                        
                        # Show snippet
                        snippet = source.get('snippet', '')
                        if snippet:
                            st.text(f"{snippet[:200]}...")
                        
                        # Show query that matched
                        query = source.get('query', '')
                        if query:
                            with st.expander("Văn bản gốc"):
                                st.text(query)
                        
                        st.divider()
            else:
                st.info("Không tìm thấy nguồn trùng lặp rõ ràng")
        else:
            st.error(f"{result.get('error', 'Unknown error')}")
        
        st.divider()
    
    if not st.session_state.text:
        st.info("Upload a file and click Run Check")
    else:
        # Debug: show issues info
        if st.session_state.issues:
            with st.expander("Chi tiết lỗi phát hiện"):
                for issue in st.session_state.issues[:10]:  # Show first 10
                    st.write(f"**Lỗi #{issue['id']}**: {issue['message']}")
                    st.write(f"- Từ: '{issue['original']}' (vị trí: {issue['offset']}, độ dài: {issue['length']})")
                    if issue['suggestions']:
                        st.write(f"- Đề xuất: {', '.join(issue['suggestions'][:3])}")
                    st.divider()
        
        html = highlight_html(st.session_state.text, st.session_state.issues)
        st.components.v1.html(
            f"<div style='max-height:800px; overflow-y:auto; border:1px solid #ddd; padding:15px; background:white;'>{html}</div>",
            height=850,
            scrolling=True
        )

with right:
    st.subheader("Kiểm tra cấu trúc bài báo")
    
    structure = st.session_state.structure_check
    
    if not structure:
        st.info("Upload a file and run check to see structure analysis")
    else:
        # Check if document is not a research paper
        if "Loại văn bản" in structure and "❌" in str(structure.get("Loại văn bản", "")):
            st.error("⚠️ " + structure.get("Loại văn bản", ""))
            st.warning(structure.get("Lý do", ""))
            st.info(structure.get("Hướng dẫn", ""))
        else:
            # Prepare data for table
            import pandas as pd
            
            rows = []
            for key, value in structure.items():
                # Determine if required
                is_required = key.endswith("*")
                field_name = key.replace(" *", "")
                
                # Add red asterisk for required fields
                if is_required:
                    field_display = f"{field_name} <span style='color:red;'>*</span>"
                else:
                    field_display = field_name
                
                # Handle different value types
                if isinstance(value, bool):
                    # Boolean values
                    status = "✅ Có" if value else "❌ Không"
                elif isinstance(value, int):
                    # Integer values (like citation count)
                    status = str(value)
                elif isinstance(value, str):
                    # String values (like reference style, DOI ratio)
                    status = value if value else "Không xác định"
                else:
                    # Fallback
                    status = str(value)
                
                rows.append({
                    "Cấu trúc": field_display,
                    "Trạng thái": status
                })
            
            # Create DataFrame - maintain original order (no sorting)
            df = pd.DataFrame(rows)
            
            # Display table using HTML to render red asterisk
            html_table = '<div style="height:90vh; overflow-y:auto;"><table style="width:100%; border-collapse:collapse;">'
            html_table += '<thead><tr style="background:#f0f2f6; position:sticky; top:0;">'
            html_table += '<th style="padding:12px; text-align:left; border-bottom:2px solid #ddd;">Cấu trúc</th>'
            html_table += '<th style="padding:12px; text-align:left; border-bottom:2px solid #ddd;">Trạng thái</th>'
            html_table += '</tr></thead><tbody>'
            
            for idx, row in df.iterrows():
                html_table += '<tr style="border-bottom:1px solid #eee;">'
                html_table += f'<td style="padding:10px;">{row["Cấu trúc"]}</td>'
                html_table += f'<td style="padding:10px;">{row["Trạng thái"]}</td>'
                html_table += '</tr>'
            
            html_table += '</tbody></table></div>'
            
            st.components.v1.html(html_table, height=1000, scrolling=False)
