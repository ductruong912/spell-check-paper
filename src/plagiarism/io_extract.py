from typing import List
from docx import Document
import pdfplumber

# NEW
import fitz  # PyMuPDF


def extract_text(path: str) -> str:
    path = path.lower()
    if path.endswith(".pdf"):
        return extract_text_from_pdf_layout_aware(path)
    if path.endswith(".docx"):
        return extract_text_from_docx(path)
    raise ValueError(f"Unsupported file type: {path}")


# -----------------------------
# DOCX (skip headers/footers to reduce noise)
# -----------------------------
def extract_text_from_docx(path: str) -> str:
    doc = Document(path)
    parts: List[str] = []
    
    # Get all header/footer paragraphs to exclude them
    header_footer_paras = set()
    for section in doc.sections:
        # Skip header paragraphs
        for para in section.header.paragraphs:
            header_footer_paras.add(id(para))
        # Skip footer paragraphs
        for para in section.footer.paragraphs:
            header_footer_paras.add(id(para))

    # Extract main body paragraphs (skip header/footer)
    for p in doc.paragraphs:
        if id(p) not in header_footer_paras:
            t = (p.text or "").strip()
            if t:
                parts.append(t)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    t = (p.text or "").strip()
                    if t:
                        parts.append(t)

    return "\n".join(parts)


# -----------------------------
# PDF – Layout aware (2-column safe)
# -----------------------------
def extract_text_from_pdf_layout_aware(path: str) -> str:
    doc = fitz.open(path)
    pages_out: List[str] = []

    for page in doc:
        blocks = page.get_text("blocks")
        blocks = [b for b in blocks if b[4].strip()]

        width = page.rect.width
        mid_x = width / 2

        left = []
        right = []

        for b in blocks:
            x0, y0, x1, y1, text, *_ = b
            cx = (x0 + x1) / 2
            clean = " ".join(text.split())
            if not clean:
                continue
            if cx < mid_x:
                left.append((y0, x0, clean))
            else:
                right.append((y0, x0, clean))

        left.sort()
        right.sort()

        page_text: List[str] = []
        for _, _, t in left:
            page_text.append(t)
        for _, _, t in right:
            page_text.append(t)

        if page_text:
            pages_out.append("\n".join(page_text))

    return "\n\n".join(pages_out)
