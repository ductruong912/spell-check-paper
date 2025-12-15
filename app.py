import streamlit as st
import tempfile
import os
from typing import List, Dict
from docx import Document
from io import BytesIO

from spell_backend import (
    extract_text_from_docx,
    extract_text_from_pdf,
    spellcheck_english_with_word,
)

st.set_page_config(
    page_title="Spell Checker",
    layout="wide"
)

def highlight_html(text: str, issues: List[Dict], active_id: str | None):
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
        border = "border:2px solid #333;" if (active_id == it["id"]) else ""
        out.append(
            f"<mark id='iss-{it['id']}' style='background:{color};{border}'>{chunk}</mark>"
        )
        i = e
    if i < len(text):
        out.append(text[i:].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    js = ""
    if active_id:
        js = f"""
        <script>
          const el = document.getElementById("iss-{active_id}");
          if (el) el.scrollIntoView({{behavior:"smooth", block:"center"}});
        </script>
        """
    html = f"<div style='white-space:pre-wrap;line-height:1.6;'>{''.join(out)}</div>{js}"
    return html

def save_to_docx(text: str, file_path: str):
    """Save text back to DOCX file."""
    doc = Document()
    for line in text.split('\n'):
        doc.add_paragraph(line)
    doc.save(file_path)

def apply_suggestion(text: str, issues: List[Dict], issue_id: str, suggestion: str):
    """Apply suggestion and shift offsets."""
    target = next(i for i in issues if i["id"] == issue_id)
    start = target["offset"]
    end = start + target["length"]

    new_text = text[:start] + suggestion + text[end:]
    delta = len(suggestion) - target["length"]

    new_issues = []
    for it in issues:
        if it["id"] == issue_id:
            continue
        if it["offset"] > start:
            it = {**it, "offset": it["offset"] + delta}
        new_issues.append(it)

    return new_text, new_issues

# --- UI ---
st.title("English Spell Checker")
st.caption("Powered by Microsoft Word")

with st.sidebar:
    st.subheader("Upload File")
    f = st.file_uploader("Choose DOCX or PDF", type=["docx", "pdf"])
    
    st.divider()
    
    st.subheader("Settings")
    show_context = st.checkbox("Show context", value=True)
    
    st.divider()
    
    run_check = st.button(
        "Run Check",
        type="primary",
        use_container_width=True,
        disabled=(f is None)
    )
    
    st.divider()
    st.caption("Uses Microsoft Word dictionary")
    st.caption("Vietnamese text is skipped")

# Session state
if "text" not in st.session_state:
    st.session_state.text = ""
if "issues" not in st.session_state:
    st.session_state.issues = []
if "file_name" not in st.session_state:
    st.session_state.file_name = ""
if "active_id" not in st.session_state:
    st.session_state.active_id = None
if "file_path" not in st.session_state:
    st.session_state.file_path = None
if "original_suffix" not in st.session_state:
    st.session_state.original_suffix = None

# Process file
if f and run_check:
    suffix = "." + f.name.split(".")[-1].lower()
    
    # Save file to uploads folder
    uploads_dir = "uploads"
    os.makedirs(uploads_dir, exist_ok=True)
    file_path = os.path.join(uploads_dir, f.name)
    
    with open(file_path, "wb") as file:
        file.write(f.read())
    
    tmp_path = file_path

    try:
        with st.spinner("Processing..."):
            if suffix == ".docx":
                text = extract_text_from_docx(tmp_path)
            else:
                text = extract_text_from_pdf(tmp_path)
            
            issues = spellcheck_english_with_word(text)

        st.session_state.text = text
        st.session_state.issues = issues
        st.session_state.file_name = f.name
        st.session_state.active_id = issues[0]["id"] if issues else None
        st.session_state.file_path = file_path
        st.session_state.original_suffix = suffix
        
        if issues:
            st.success(f"Found {len(issues)} issue(s)")
        else:
            st.success("No errors found")

    except Exception as e:
        st.error(f"Error: {str(e)}")

# Layout
left, right = st.columns([2, 1])

with left:
    st.subheader("Preview")
    
    if st.session_state.file_name:
        st.caption(f"File: {st.session_state.file_name}")
    
    # Word count statistics
    if st.session_state.text:
        words = st.session_state.text.split()
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Words", len(words))
        with col2:
            st.metric("Characters", len(st.session_state.text))
        with col3:
            st.metric("Issues", len(st.session_state.issues))

    if not st.session_state.text:
        st.info("Upload a file and click Run Check")
    else:
        html = highlight_html(st.session_state.text, st.session_state.issues, st.session_state.active_id)
        st.components.v1.html(
            f"<div style='height:70vh; overflow:auto; border:1px solid #ddd; padding:15px;'>{html}</div>",
            height=600,
            scrolling=False
        )

with right:
    st.subheader("Issues")
    issues = st.session_state.issues
    
    if issues:
        st.write(f"{len(issues)} issue(s)")
    else:
        st.success("No issues")

    if issues:
        q = st.text_input("Search", placeholder="filter")
        filtered = [it for it in issues if (q.lower() in it["original"].lower())] if q else issues
        
        st.caption(f"Showing {len(filtered)}")
        st.divider()

        for idx, it in enumerate(filtered[:50]):
            with st.container(border=True):
                st.markdown(f"**{it['original']}**")
                
                if show_context:
                    ctx_start = max(0, it["offset"] - 30)
                    ctx_end = min(len(st.session_state.text), it["offset"] + it["length"] + 30)
                    ctx = st.session_state.text[ctx_start:ctx_end]
                    st.caption(f"...{ctx}...")
                
                if it["suggestions"]:
                    st.caption(f"Suggestions: {', '.join(it['suggestions'][:3])}")
                else:
                    st.caption("No suggestions")
                
                if st.button("Focus", key=f"f-{it['id']}", use_container_width=True):
                    st.session_state.active_id = it["id"]
                    st.rerun()
        
        if len(filtered) > 50:
            st.info(f"Showing first 50 of {len(filtered)}")
