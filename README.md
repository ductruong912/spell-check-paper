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
- **Dịch vụ kiểm tra cấu trúc + so khớp với kho bài hợp lệ** (FastAPI) — entrypoint `main.py`, code trong `src/structure/` và `src/matching/`.

Hai phần chia sẻ các tiện ích chung: `config.py` (Settings + helper biến môi trường + nạp `.env`), `validation.py` (validate API key + tạo OpenAI client), và `documents/` (trích xuất text PDF/DOCX).

```text
.
├── app.py                     # Streamlit: kiểm tra cấu trúc bài báo
├── main.py                    # FastAPI: /check-structure + /valid-papers/{ingest,match}
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
│   └── matching/              # So title + keywords với kho bài hợp lệ
│       ├── config.py          # ValidPaperConfig (biến VALID_*) + FieldRelevanceConfig (script offline)
│       ├── models/matching.py # ValidPaperResult/Match, FieldRelevanceResult
│       ├── repositories/      # valid_paper_store, field_vector_store, field_keywords
│       └── services/          # embeddings, bm25, valid_paper_match, field_relevance
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
```

Ba endpoint trả JSON:

- `POST /check-structure` (file DOCX/PDF, multipart) — trả về **nguyên JSON thô của LLM classifier**:
  - `sections`: mỗi mục có `present` (bool), `confidence` (0–1), `evidence`, `reason`. Không áp ngưỡng confidence và không có cờ tổng `ok` (client tự quyết). Mục `references` chỉ kiểm tra có/thiếu.
  - `extracted`: title + list keywords **đầy đủ** theo từng ngôn ngữ (`title_vi`, `title_en`, `keywords_vi`, `keywords_en`).
  - `metadata`: bản gộp **ưu tiên EN** cho bài song ngữ (`title`, `keywords`, `language`, `title_source`, `keywords_source`) — dùng làm input cho `/valid-papers/match`.
- `POST /valid-papers/ingest` (JSON) — nạp các bài **hợp lệ** vào kho vector (mỗi bài cần đủ `title` + ≥1 `keyword`). Body: `{"papers": [{"title": "...", "keywords": ["..."]}]}`. Trả `{ingested_papers, total_papers}`.
- `POST /valid-papers/match` (JSON) — so `title` + `keywords` bản thảo với kho bài hợp lệ. `keywords` nhận **mảng** hoặc **chuỗi** phân tách `,`/`;`. Thêm `"explain": true` để xem chi tiết `matches`. Phải có ít nhất `title` hoặc một `keyword` (nếu không → 400).

`/valid-papers/match` tách truy vấn thành **2 vector** (1 vector title, 1 vector gộp list keywords) rồi so độc lập với hai collection của kho. Điểm mỗi bản ghi = `VALID_SEMANTIC_WEIGHT`·cosine + `VALID_LEXICAL_WEIGHT`·BM25 (đã normalize 0–1 theo điểm cao nhất của truy vấn); lấy trung bình **top-`VALID_TOP_K`** bản ghi cao điểm nhất ra điểm từng mặt. `overall_score` = trung bình điểm title + keywords. Mặc định 0.7 semantic / 0.3 BM25, top-5. Kết quả:

```json
{
  "overall_score": 0.83,
  "title":    { "score": 0.81, "matches": [{"text": "...", "score": 0.81, "semantic": 0.86, "lexical": 0.70}] },
  "keywords": { "score": 0.85, "matches": [{"text": "...", "score": 0.85, "semantic": 0.88, "lexical": 0.78}] }
}
```

`matches` chỉ xuất hiện khi `explain=true`. Dùng chung model SBERT đa ngữ với field relevance (`FIELD_MODEL_NAME`); đổi model thì phải nạp lại kho. Các biến `FIELD_*` còn lại chỉ phục vụ script hiệu chỉnh offline `src/matching/scripts/calibrate_field_thresholds.py`, không còn endpoint.

Ví dụ kết quả `POST /check-structure`:

```json
{
  "sections": {
    "title_vi": {"present": true, "confidence": 0.95, "evidence": "...", "reason": "..."},
    "abstract_en": {"present": false, "confidence": 0.0, "evidence": "", "reason": "..."}
  },
  "extracted": {
    "title_en": "Machine Learning in Healthcare",
    "keywords_en": ["machine learning", "healthcare"]
  },
  "metadata": {
    "language": "bilingual",
    "title": "Machine Learning in Healthcare",
    "keywords": ["machine learning", "healthcare"],
    "title_source": "en",
    "keywords_source": "en"
  }
}
```
