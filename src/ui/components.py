import html
from typing import List, Dict

"""Các tiện ích UI nhỏ: tạo HTML highlight cho các lỗi trong văn bản."""

def highlight_html(text: str, issues: List[Dict]) -> str:
    if not text:
        return ""

    safe_text = text
    issues = issues or []

    # Validate & normalize
    spans = []
    for it in issues:
        try:
            start = int(it.get("offset", 0))
            length = int(it.get("length", 0))
            if length <= 0:
                continue
            end = start + length
            if start < 0 or end > len(safe_text):
                continue
            spans.append({
                "start": start,
                "end": end,
                "message": str(it.get("message") or ""),
                "type": str(it.get("type") or ""),
                "color": str(it.get("ui_color") or "gray"),
            })
        except Exception:
            continue

    if not spans:
        return "<pre style='white-space:pre-wrap; font-family:inherit'>" + html.escape(safe_text) + "</pre>"

    # Sắp theo start; nếu chồng chéo, giữ phần sớm nhất và bỏ phần sau
    spans.sort(key=lambda x: (x["start"], -(x["end"] - x["start"])))

    merged = []
    last_end = -1
    for s in spans:
        if s["start"] < last_end:
            # overlap: skip (or you can merge if you want)
            continue
        merged.append(s)
        last_end = s["end"]

    # Color map
    bg_map = {
        "red": "#ff4d4f",
        "yellow": "#fadb14",
        "gray": "#777777",
    }
    fg_map = {
        "red": "#000000",
        "yellow": "#000000",
        "gray": "#ffffff",
    }

    out = []
    cursor = 0

    for s in merged:
        # plain chunk before span
        if cursor < s["start"]:
            out.append(html.escape(safe_text[cursor:s["start"]]))

        chunk = html.escape(safe_text[s["start"]:s["end"]])
        bg = bg_map.get(s["color"], "#777777")
        fg = fg_map.get(s["color"], "#ffffff")
        tooltip = html.escape(f'{s["type"]}: {s["message"]}')

        out.append(
            f"<span title='{tooltip}' "
            f"style='background:{bg}; color:{fg}; padding:0 2px; border-radius:3px;'>"
            f"{chunk}</span>"
        )
        cursor = s["end"]

    # tail chunk
    if cursor < len(safe_text):
        out.append(html.escape(safe_text[cursor:]))

    return "<pre style='white-space:pre-wrap; font-family:inherit; line-height:1.45'>" + "".join(out) + "</pre>"
