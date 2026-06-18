# ArticleCheck AI

Ứng dụng Streamlit dùng AI để kiểm tra cấu trúc bài báo khoa học từ file DOCX hoặc PDF.

## Tính Năng Chính

### Kiểm Tra Cấu Trúc

Hệ thống phát hiện các phần bắt buộc trong bài báo khoa học:

- Tiêu đề tiếng Việt
- Tiêu đề tiếng Anh
- Tác giả và thông tin liên hệ
- Tóm tắt tiếng Việt
- Tóm tắt tiếng Anh
- Từ khóa tiếng Việt
- Từ khóa tiếng Anh
- Giới thiệu
- Vật liệu và/hoặc phương pháp nghiên cứu
- Kết quả và thảo luận
- Kết luận
- Tài liệu tham khảo

Ứng dụng đọc nội dung DOCX/PDF, tạo view có cấu trúc từ các đoạn văn, sau đó dùng LLM để phân loại từng mục và trả về bảng trạng thái. PDF được xử lý local bằng PyMuPDF, phù hợp với bài báo có text layer như PDF xuất từ LaTeX.

## Cài Đặt

### Yêu Cầu

- Python 3.8 trở lên
- OpenAI API key
- LibreOffice (không bắt buộc) để chuyển DOCX sang PDF xem trước gần bản gốc

### Xem Trước Tài Liệu Local

- PDF được render local thành các trang preview PNG độ phân giải cao, không có nút zoom.
- DOCX ưu tiên chuyển sang PDF bằng LibreOffice headless, sau đó render thành preview trang.
- Nếu không có LibreOffice, DOCX được chuyển sang HTML local bằng Mammoth.
- Bản xem trước UI tách biệt với text layer gốc dùng cho backend kiểm tra cấu trúc.

Có thể cấu hình đường dẫn LibreOffice trong `.env`:

```bash
LIBREOFFICE_PATH=C:\Program Files\LibreOffice\program\soffice.exe
DOCX_PREVIEW_TIMEOUT_SECONDS=60
```

### Tạo Môi Trường

```bash
python -m venv venv
python.exe -m pip install --upgrade pip
pip install -r requirements.txt
```

Tạo file `.env` trong thư mục gốc:

```bash
OPENAI_API_KEY=sk-...
```

### Chạy Ứng Dụng

```bash
streamlit run app.py
```

Mở trình duyệt tại địa chỉ Streamlit hiển thị trong terminal.

## Cấu Trúc Dự Án

Dự án gộp hai phần dùng chung một cây mã nguồn trong `src/`:

- **App kiểm tra cấu trúc** (Streamlit) — entrypoint `app.py`.
- **Dịch vụ trích metadata & gợi ý tạp chí** (FastAPI) — entrypoint `main.py`, code trong `src/matching/`.

Hai phần chia sẻ các tiện ích chung: `config.py` (Settings + helper biến môi trường + nạp `.env`), `validation.py` (validate API key + tạo OpenAI client), và `documents/` (trích xuất text PDF/DOCX).

```text
.
├── app.py                     # Streamlit: kiểm tra cấu trúc bài báo
├── main.py                    # FastAPI: /extract-metadata (metadata + matching)
├── requirements.txt
├── src/
│   ├── config.py              # Settings + helper biến môi trường (.env)
│   ├── services.py
│   ├── validation.py          # Validate API key + tạo OpenAI client + map lỗi
│   ├── documents/
│   │   ├── parser.py
│   │   ├── extract.py         # Trích text dùng chung (PDF/DOCX → text)
│   │   ├── preview.py
│   │   └── temp_files.py
│   ├── structure/
│   │   ├── classifier.py
│   │   ├── checker.py
│   │   ├── models.py
│   │   ├── prompt.py
│   │   ├── template.py
│   │   └── templates/default.json
│   ├── ui/
│   │   ├── layout.py
│   │   ├── render.py
│   │   └── theme.py
│   └── matching/              # Engine gợi ý tạp chí (gộp từ src1)
│       ├── config.py          # MatchingConfig (biến MATCH_*)
│       ├── models/matching.py
│       ├── repositories/      # article.py, matching_index.py
│       ├── services/          # embeddings, matching_engine, metadata_validation, prompt, text_extractors
│       └── scripts/rebuild_matching_index.py
└── tests/
```

## Sử Dụng

### App kiểm tra cấu trúc (Streamlit)

1. Upload file DOCX hoặc PDF trong sidebar.
2. Bấm **Kiểm tra cấu trúc**.
3. Xem nội dung tài liệu và bảng trạng thái các mục bắt buộc.

### API (FastAPI)

```bash
# Chạy API
python main.py            # hoặc: uvicorn main:app --reload

# Tạo chỉ mục matching từ data/journal_articles.json
python src/matching/scripts/rebuild_matching_index.py
```

Hai endpoint, đều nhận file DOCX/PDF (multipart) và trả JSON:

- `POST /extract-metadata` — trả title, keywords và (nếu đã build chỉ mục) kết quả gợi ý tạp chí. Cấu hình ngưỡng matching qua các biến `MATCH_*` trong `.env`.
- `POST /check-structure` — trả về **nguyên JSON thô của LLM classifier**: mỗi mục có `present` (bool), `confidence` (0–1), `evidence`, `reason`. Không áp ngưỡng confidence và không có cờ tổng `ok` (client tự quyết dựa trên `confidence`). Mục `references` chỉ kiểm tra có/thiếu, không phân loại kiểu trích dẫn.

Ví dụ kết quả `POST /check-structure`:

```json
{
  "sections": {
    "title_vi": {"present": true, "confidence": 0.95, "evidence": "...", "reason": "..."},
    "references": {"present": true, "confidence": 0.9, "evidence": "[1] ...", "reason": "..."},
    "abstract_en": {"present": false, "confidence": 0.0, "evidence": "", "reason": "..."}
  }
}
```
