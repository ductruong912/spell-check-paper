# ArticleCheck AI

Ứng dụng kiểm tra cấu trúc bài báo khoa học từ file DOCX/PDF, so khớp title/keywords với kho bài báo hợp lệ theo từng lĩnh vực, và gợi ý chuyên gia phản biện dựa trên title.

## Tính Năng Chính

- Giao diện Streamlit để upload DOCX/PDF, xem trước tài liệu và kiểm tra cấu trúc bài báo.
- API FastAPI cho kiểm tra cấu trúc và quản lý kho bài báo hợp lệ.
- Trích xuất text DOCX/PDF local bằng `python-docx` và PyMuPDF.
- Xem trước PDF/DOCX local. DOCX ưu tiên chuyển sang PDF bằng LibreOffice, fallback sang HTML bằng Mammoth.
- Phân loại cấu trúc bằng OpenAI, với template cấu trúc có thể cấu hình qua JSON.
- So khớp title và keywords bằng dense embedding, sparse BM25 vector trong Qdrant, và reranker tùy chọn.
- Gợi ý chuyên gia phản biện từ title bài đã viết và title bài đã từng phản biện.

Các mục cấu trúc mặc định nằm trong [src/structure/templates/default.json](src/structure/templates/default.json).

## Cài Đặt

Yêu cầu:

- Python 3.10 trở lên
- OpenAI API key
- LibreOffice nếu muốn preview DOCX gần bản gốc hơn

Tạo môi trường và cài dependency:

```bash
python -m venv venv
venv\Scripts\python -m pip install --upgrade pip
venv\Scripts\python -m pip install -r requirements.txt
```

Tạo file `.env` từ `.env.example`:

```bash
cp .env.example .env
```

## Chạy Ứng Dụng

Streamlit:

```bash
streamlit run app.py
```

FastAPI:

```bash
python main.py
# hoặc
uvicorn main:app --reload
```

## Cấu Trúc Dự Án

```text
.
├── app.py                     # Streamlit UI
├── main.py                    # FastAPI entrypoint
├── requirements.txt
├── src/
│   ├── config.py              # Settings, ValidPaperConfig, ReviewerConfig và helper đọc biến môi trường
│   ├── services.py            # Orchestration cho parse, preview, structure check
│   ├── validation.py          # Validate API key, tạo OpenAI client, map lỗi
│   ├── documents/
│   │   ├── parser.py          # Parse DOCX/PDF thành DocumentView
│   │   ├── extract.py         # Text extraction wrapper
│   │   ├── preview.py         # Preview PDF/DOCX
│   │   └── temp_files.py
│   ├── structure/
│   │   ├── classifier.py      # Gọi OpenAI và chuẩn hóa output
│   │   ├── checker.py         # Áp ngưỡng confidence và tạo StructureReport
│   │   ├── models.py
│   │   ├── prompt.py
│   │   ├── template.py
│   │   └── templates/default.json
│   ├── matching/
│   │   ├── models/matching.py
│   │   ├── repositories/valid_paper_store.py
│   │   └── services/
│   │       ├── embeddings.py
│   │       ├── preprocessing.py
│   │       └── valid_paper_match.py
│   ├── reviewers/
│   │   ├── models.py
│   │   ├── repositories/reviewer_store.py
│   │   └── services/reviewer_suggestion.py
│   └── ui/
│       ├── layout.py
│       ├── render.py
│       └── theme.py
└── tests/
```

## API

### `POST /check-structure?id=csce`

Multipart request with query parameter:

- `id` (query): domain id dùng để so khớp với kho bài hợp lệ; hệ thống tự trim và chuyển về chữ thường
- `file`: file DOCX/PDF

Response là JSON đã chuẩn hóa từ classifier:

- `sections`: từng mục có `present`, `confidence`, `evidence`, `reason`
- `extracted`: title và keywords theo tiếng Việt/tiếng Anh
- `metadata`: title/keywords đã gộp, ưu tiên tiếng Anh cho bài song ngữ
- `domain_match`: điểm so khớp với kho bài hợp lệ nếu kho đã được nạp

Các API có `id` đều nhận `id` bằng query parameter bắt buộc (`?id=csce`), gồm:
`/valid-papers/ingest/batch`, `/valid-papers/match`,
`/reviewers/ingest`, `/reviewers/suggest` và `/check-structure`.
`id` không phân biệt hoa thường và được chuẩn hóa thành chữ thường trước khi lấy kho dữ liệu.

`POST /valid-papers/ingest/batch` nhận toàn bộ title + keywords và thay thế toàn bộ kho của domain. Hệ thống build embedding vào kho tạm trước; chỉ khi build thành công mới thay kho cũ. Nếu build lỗi, kho cũ được giữ nguyên.

`POST /reviewers/ingest?id=csce` cũng nhận toàn bộ reviewer của domain và thay thế toàn bộ kho reviewer theo cùng cơ chế kho tạm/swap an toàn.

### `POST /reviewers/ingest?id=CSCE`

Nạp kho chuyên gia theo từng domain id:

```json
[
  {
    "user_id": 1,
    "user": "admin",
    "article": "The Example 1, The Example 2",
    "article_review": ["The Example 3", "The Example 4"]
  }
]
```

`article` và `article_review` nhận chuỗi phân tách bằng dấu phẩy/chấm phẩy hoặc list string. Mỗi title được lưu vào Qdrant local store kèm payload `user_id`, `user`, `articles`, `reviewed_articles`.

### `POST /reviewers/suggest?id=CSCE`

Gợi ý chuyên gia phản biện theo title bản thảo:

```json
{
  "title": "The submitted article title",
  "explain": true
}
```

Hệ thống tính điểm toàn bộ chuyên gia đã nạp và trả về toàn bộ danh sách, sắp xếp theo `score` giảm dần. Frontend có thể default select all để người dùng tự bỏ chọn. Khi `explain=true`, response có thêm các title gần nhất trong `matched_articles` và `matched_reviewed_articles`.

Điểm mặc định ưu tiên nhẹ kinh nghiệm phản biện:

```text
score = max(authored_score, reviewed_score)
```

Reviewer được tính điểm theo nguồn có title phù hợp cao hơn: bài đã viết hoặc bài đã phản biện.
Hệ thống luôn lấy candidate rộng hơn bằng `REVIEWER_RERANK_CANDIDATES`, chấm lại bằng reranker, rồi mới lấy `REVIEWER_TOP_MATCHES` title tốt nhất để tính điểm.
Điểm mỗi title sau rerank được kết hợp theo công thức `retrieval_score * REVIEWER_RETRIEVAL_SCORE_WEIGHT + reranker_score * REVIEWER_RERANKER_SCORE_WEIGHT`.

```json
{
  "suggestions": [
    {
      "user_id": 2,
      "user": "admin2",
      "score": 0.87,
      "authored_score": 0.82,
      "reviewed_score": 0.91,
      "matched_articles": ["The Example 1"],
      "matched_reviewed_articles": ["The Example 3"]
    }
  ]
}
```

## Cấu Hình Chính

- `DEFAULT_LLM_MODEL`: model OpenAI dùng cho classifier
- `OPENAI_MAX_TOKENS`: giới hạn output tokens khi gọi OpenAI
- `OPENAI_TEMPERATURE`: temperature khi gọi OpenAI
- `STRUCTURE_TEMPLATE_PATH`: đường dẫn template cấu trúc thay thế
- `STRUCTURE_TIMEOUT_SECONDS`: timeout kiểm tra cấu trúc
- `VALID_PAPER_STORE_PATH`: thư mục lưu Qdrant local store cho kho bài hợp lệ, mặc định `data_valid_paper_store`
- `VALID_MODEL_NAME`: model dense embedding
- `VALID_TOP_K`, `VALID_EVAL_TOP_N`: số lượng candidate và số match dùng tính điểm
- `VALID_TITLE_*`, `VALID_KEYWORD_*`: trọng số semantic/lexical và trọng số tổng hợp
- `VALID_RETRIEVAL_SCORE_WEIGHT`, `VALID_RERANKER_SCORE_WEIGHT`: trọng số fusion giữa điểm retrieval và reranker khi reranker được bật
- `REVIEWER_STORE_PATH`: thư mục lưu Qdrant local store cho kho chuyên gia, mặc định `data_reviewer_store`
- `REVIEWER_COLLECTION`: tên collection lưu title chuyên gia
- `REVIEWER_TOP_MATCHES`: số title gần nhất dùng để giải thích và lấy trung bình điểm mỗi nhóm
- `REVIEWER_RERANKER_MODEL_NAME`: model cross-encoder dùng để rerank reviewer title candidates
- `REVIEWER_RERANK_CANDIDATES`: số candidate mỗi nhóm được rerank trước khi lấy `REVIEWER_TOP_MATCHES`, mặc định `10`
- `REVIEWER_RETRIEVAL_SCORE_WEIGHT`, `REVIEWER_RERANKER_SCORE_WEIGHT`: trọng số kết hợp retrieval và reranker, mặc định lần lượt `0.4` và `0.6`

## Kiểm Thử

```bash
venv\Scripts\python -m pytest -q
```
