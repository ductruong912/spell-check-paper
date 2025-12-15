import os
import re
import json
from pathlib import Path
import win32com.client

WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")

def extract_text_from_docx_via_word(docx_path: str) -> str:
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    doc = None
    try:
        doc = word.Documents.Open(str(Path(docx_path).resolve()), ReadOnly=True, AddToRecentFiles=False)
        text = doc.Content.Text
        return text
    finally:
        if doc is not None:
            doc.Close(False)
        word.Quit()

def spellcheck_english_text_with_word_engine(text: str):
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0  # wdAlertsNone

    doc = None
    try:
        # Mở document trống để Word cho phép GetSpellingSuggestions
        doc = word.Documents.Add()

        results = []
        for m in WORD_RE.finditer(text):
            w = m.group(0)

            if len(w) <= 2 or w.isupper():
                continue

            ok = bool(word.CheckSpelling(w))
            if not ok:
                # Lấy suggestions (giờ sẽ không lỗi)
                sugg_obj = word.GetSpellingSuggestions(w)
                sugg = [s.Name for s in sugg_obj][:10]

                context_window = 35
                start, end = m.start(), m.end()
                ctx_start = max(0, start - context_window)
                ctx_end = min(len(text), end + context_window)

                results.append({
                "type": "spelling",
                "word": w,
                "offset": start,
                "length": end - start,
                "suggestions": sugg,
                "context": text[ctx_start:ctx_end]
                })

        return results

    finally:
        if doc is not None:
            doc.Close(False)
        word.Quit()

if __name__ == "__main__":
    path = r".\test\english.docx"
    path_abs = str(Path(path).resolve())
    if not os.path.exists(path_abs):
        raise FileNotFoundError(path_abs)

    text = extract_text_from_docx_via_word(path_abs)
    errors = spellcheck_english_text_with_word_engine(text)

    print(json.dumps(errors, ensure_ascii=False, indent=2))
