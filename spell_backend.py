import re
from typing import List, Dict, Tuple
from docx import Document
import pdfplumber
import win32com.client
import pythoncom

try:
    import language_tool_python
    LANGUAGE_TOOL_AVAILABLE = True
except ImportError:
    LANGUAGE_TOOL_AVAILABLE = False

WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
VIETNAMESE_CHARS = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ]")

# Cache for LanguageTool instances
_language_tool_cache = {}

def extract_text_from_docx(path: str) -> str:
    """Extract text from DOCX."""
    doc = Document(path)
    parts = []
    for p in doc.paragraphs:
        t = p.text.strip()
        if t:
            parts.append(t)
    return "\n".join(parts)

def extract_text_from_pdf(path: str) -> str:
    """Extract text from PDF."""
    parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                parts.append(t)
    return "\n\n".join(parts)

def detect_language(text: str) -> str:
    """Detect if text is primarily Vietnamese or English.
    Returns: 'vi' or 'en'
    """
    # Count Vietnamese characters
    vietnamese_count = len(VIETNAMESE_CHARS.findall(text))
    # Count English words
    english_count = len(WORD_RE.findall(text))
    
    # If has Vietnamese chars, consider it Vietnamese
    if vietnamese_count > 10:
        return 'vi'
    return 'en'

def spellcheck_vietnamese(text: str) -> List[Dict]:
    """Vietnamese spell checking is not supported.
    Returns: empty list (no checks performed)
    """
    # Unfortunately, there is no good Vietnamese spell checker available
    # LanguageTool doesn't support Vietnamese
    # Word COM API doesn't support Vietnamese well
    # Return empty list - no spell checking for Vietnamese
    return []

def spellcheck_english_with_languagetool(text: str) -> List[Dict]:
    """Check English spelling using LanguageTool.
    Returns: [{id,type,offset,length,original,suggestions,message}]
    """
    if not LANGUAGE_TOOL_AVAILABLE:
        # Fallback to Word COM API
        return spellcheck_english_with_word(text)
    
    try:
        # Use cached LanguageTool instance
        if 'en' not in _language_tool_cache:
            _language_tool_cache['en'] = language_tool_python.LanguageTool('en-US')
        
        tool = _language_tool_cache['en']
        matches = tool.check(text)
        
        issues = []
        for idx, match in enumerate(matches, 1):
            # Filter out some noise - only spelling errors
            if match.ruleId.startswith('MORFOLOGIK_RULE') or 'SPELLER' in match.ruleId:
                issues.append({
                    "id": str(idx),
                    "type": "spelling",
                    "offset": match.offset,
                    "length": match.errorLength,
                    "original": text[match.offset:match.offset + match.errorLength],
                    "suggestions": match.replacements[:5] if match.replacements else [],
                    "message": match.message
                })
        
        return issues
        
    except Exception as e:
        # Fallback to Word COM API
        return spellcheck_english_with_word(text)

def spellcheck_english_with_word(text: str) -> List[Dict]:
    """Check spelling and return issues.
    Returns: [{id,type,offset,length,original,suggestions,message}]
    """
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

def spellcheck_auto(text: str) -> List[Dict]:
    """Automatically detect language and use appropriate spell checker.
    Returns: [{id,type,offset,length,original,suggestions,message}]
    """
    lang = detect_language(text)
    
    if lang == 'vi':
        # Vietnamese: no spell checking available
        return spellcheck_vietnamese(text)
    else:
        # English: use LanguageTool (or Word COM as fallback)
        return spellcheck_english_with_languagetool(text)