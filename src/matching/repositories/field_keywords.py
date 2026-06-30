import re


# Mỗi dòng trong danh mục có dạng "<số thứ tự> <từ khóa>", ví dụ "12 Pedagogy".
# Bỏ tiền tố số thứ tự (kèm dấu . hoặc ) tùy biến) để lấy đúng phần từ khóa.
_INDEX_PREFIX = re.compile(r"^\s*\d+[\.\)]?\s+")


def parse_field_keywords(text: str) -> list[str]:
    """Tách danh mục từ khóa lĩnh vực từ nội dung text (mỗi dòng một từ khóa).

    Trả về danh sách từ khóa đã loại trùng (không phân biệt hoa/thường) và giữ
    nguyên thứ tự xuất hiện. Dùng cho luồng upload: nội dung file được decode
    thành text rồi parse, embed và lưu vào vector store.
    """
    keywords: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        keyword = _INDEX_PREFIX.sub("", line).strip()
        if not keyword:
            continue
        normalized = keyword.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        keywords.append(keyword)
    return keywords
