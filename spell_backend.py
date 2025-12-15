import re
from typing import List, Dict, Tuple
from docx import Document
import pdfplumber
import win32com.client
import pythoncom

WORD_RE = re.cache = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")

def extract_text_from_docx(path: str) -> str:
    doc = Document(path)
    parts = []
    for p in doc.paragraphs:
        t = p.text.strip()
        if t:
            parts.append(t)
    return "\n".join(parts)

def extract_text_from_pdf(path: str) -> str:
    parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                parts.append(t)
    return "\n\n".join(parts)

def spellcheck_english_with_word(text: str) -> List[Dict]:
    """
    Returns issues: [{id,type,offset,length,original,suggestions,message}]
    Uses Word dictionary engine; needs at least one open doc for suggestions.
    """
    # Initialize COM for this thread
    pythoncom.CoInitialize()
    
    app = None
    base_doc = None
    
    try:
        app = win32com.client.DispatchEx("Word.Application")
        app.Visible = False
        app.DisplayAlerts = 0  # wdAlertsNone

        base_doc = app.Documents.Add()

        cache: Dict[str, Tuple[bool, List[str]]] = {}
        issues = []
        issue_id = 1

        # simple stopwords to reduce calls
        STOP = {"the","a","an","in","of","to","and","or","is","are","was","were","be","been","with","for","on","at","by","from"}

        for m in WORD_RE.finditer(text):
            w = m.group(0)
            wl = w.lower()

            if len(w) <= 2 or w.isupper() or wl in STOP:
                continue

            if wl in cache:
                ok, sugg = cache[wl]
            else:
                ok = bool(app.CheckSpelling(w))
                sugg = []
                if not ok:
                    sugg_obj = app.GetSpellingSuggestions(w)
                    sugg = [s.Name for s in sugg_obj][:5]  # limit suggestions
                cache[wl] = (ok, sugg)

            if not ok:
                issues.append({
                    "id": str(issue_id),
                    "type": "spelling",
                    "offset": m.start(),
                    "length": m.end() - m.start(),
                    "original": w,
                    "suggestions": sugg,
                    "message": "Possible spelling mistake"
                })
                issue_id += 1

        return issues

    finally:
        if base_doc is not None:
            base_doc.Close(False)
        if app is not None:
            app.Quit()
        # Uninitialize COM
        pythoncom.CoUninitialize()
