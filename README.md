# ArticleCheck AI

Hệ thống kiểm tra bài báo khoa học tự động với AI - công cụ toàn diện để kiểm tra cấu trúc, chính tả và đạo văn cho các bài báo khoa học tiếng Việt và tiếng Anh.

## Tính năng chính

### Kiểm tra cấu trúc

Phát hiện các phần bắt buộc còn thiếu trong bài báo: Tựa đề, Tóm tắt, Từ khóa, Tài liệu tham khảo. Hệ thống kiểm tra cả song ngữ Việt-Anh và sử dụng LLM để phân loại các phần trong văn bản một cách thông minh.

### Kiểm tra chính tả

Hệ thống sử dụng hai công cụ kiểm tra song song:

**Tiếng Anh**: Tích hợp Microsoft Word COM API để kiểm tra lỗi chính tả tiếng Anh với độ chính xác cao. Các lỗi tiếng Anh được highlight màu đỏ.

**Tiếng Việt**: Sử dụng heuristic detector để phát hiện ba loại lỗi phổ biến:
- Lỗi gõ dấu: ASCII tone marks lẫn với Unicode (ví dụ: `toan`` thay vì `toan`)
- Từ vỡ âm tiết: Cấu trúc phụ âm/nguyên âm không hợp lệ (`âbd`, `vlà`)
- Từ không tồn tại: Tổ hợp ký tự lạ (`iii`, `aaa`, `bcdfg`)

Các lỗi tiếng Việt được highlight màu vàng để phân biệt với lỗi tiếng Anh.

### Kiểm tra đạo văn

Tích hợp PlagiarismSearch API với các tính năng:
- Kiểm tra song song nhiều phần văn bản (parallel processing với 3 workers)
- Tự động chia nhỏ văn bản thành chunks tối ưu (900-1500 từ/chunk tùy độ dài)
- Cache kết quả trong 7 ngày để tránh kiểm tra lại văn bản giống nhau
- Báo cáo chi tiết nguồn trùng lặp và tỷ lệ đạo văn

## Cài đặt

### Yêu cầu

- Python 3.8 trở lên
- Windows (nếu muốn dùng Word COM spell checker)
- Microsoft Word (tùy chọn, chỉ cần cho kiểm tra tiếng Anh)

### Các bước cài đặt

Clone repository:
```bash
git clone https://github.com/yourusername/spell-check-paper.git
cd spell-check-paper
```

Cài đặt dependencies:
```bash
pip install -r requirements.txt
```

Tạo file `.env` trong thư mục gốc với nội dung:
```bash
cp .env.excample .env
```

Lấy API keys:
- OpenAI: https://platform.openai.com/api-keys
- PlagiarismSearch: https://plagiarismsearch.com/api.html

Chạy ứng dụng:
```bash
streamlit run app.py
```

Mở trình duyệt tại http://localhost:8501

## Cấu trúc dự án

```
spell-check-paper/
├── app.py                      # Streamlit main app
├── requirements.txt            # Python dependencies
├── .env                        # API configuration
├── .gitignore
│
├── src/
│   ├── document_backend.py    # Document processing orchestration
│   │
│   ├── structure/             # Structure checking
│   │   ├── classifier.py      # LLM-based section classification
│   │   └── checker.py         # Structure validation
│   │
│   ├── spell/                 # Spell checking
│   │   ├── detector.py        # Dual-engine checker (EN + VI)
│   │   ├── checker.py         # Orchestration
│   │   └── reference_finder.py # Reference detection
│   │
│   ├── plagiarism/            # Plagiarism checking
│   │   ├── api_client.py      # PlagiarismSearch API
│   │   ├── checker.py         # Check orchestration
│   │   └── chunking.py        # Text chunking
│   │
│   ├── ui/                    # UI components
│   │   ├── components.py      # HTML rendering
│   │   ├── handlers.py        # Streamlit handlers
│   │   └── layout.py          # Results display
│   │
│   └── utils/                 # Utilities
│       ├── config.py          # Configuration
│       ├── validation.py      # API validation
│       ├── rate_limiter.py    # Rate limiting
│       └── disk_cache.py      # Caching
│
└── tests/                     # Unit tests
```

## Cấu hình

### Rate Limiting

Hệ thống tự động giới hạn số lượng API calls để tránh bị ban:
- OpenAI: 50 calls mỗi phút
- PlagiarismSearch: 30 calls mỗi phút

Khi vượt giới hạn, hệ thống sẽ tự động retry với exponential backoff (2s, 4s, 8s).

### Caching

Để giảm chi phí API, hệ thống cache kết quả vào disk:
- Plagiarism cache: 7 ngày (`.cache/plagiarism/`)
- API unavailable cache: 1 giờ

Cache tự động xóa khi hết hạn.

### Logging

Mặc định logging ở mức INFO. Để debug, mở `app.py` và đổi thành:
```python
logging.basicConfig(level=logging.DEBUG)
```

## Sử dụng

Upload file DOCX (tối đa 200MB), chọn các loại kiểm tra cần thực hiện:

- **Kiểm tra cấu trúc**: Phát hiện phần thiếu (Tựa đề VI/EN, Tóm tắt, Từ khóa, Tài liệu tham khảo)
- **Kiểm tra chính tả**: Dual-engine (màu đỏ = lỗi tiếng Anh, màu vàng = nghi ngờ tiếng Việt)
- **Kiểm tra đạo văn**: Tỷ lệ trùng lặp và danh sách nguồn

Kết quả hiển thị ngay trên web interface với highlight màu cho từng loại lỗi.

## Testing

Chạy toàn bộ tests:
```bash
python tests/run_tests.py
```

Hoặc test từng module:
```bash
python -m pytest tests/test_rate_limiter.py
python -m pytest tests/test_disk_cache.py
python -m pytest tests/test_validation.py
```

## Deployment

### Local Production

```bash
pip install -r requirements.txt
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

### Docker

Tạo `Dockerfile`:
```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

Build và chạy:
```bash
docker build -t articlecheck-ai .
docker run -p 8501:8501 -v $(pwd)/.env:/app/.env articlecheck-ai
```

## Troubleshooting

### "OPENAI_API_KEY not found"

Kiểm tra file `.env` có tồn tại và key được wrap trong quotes:
```env
OPENAI_API_KEY="sk-proj-..."
```

### "Microsoft Word COM engine not available"

Cài đặt Microsoft Word trên Windows. Nếu không có Word, app vẫn chạy nhưng chỉ có Vietnamese spell checker.

### "PlagiarismSearch API NOT configured"

Thêm credentials vào `.env` hoặc comment out để skip plagiarism check:
```env
# PLAGIARISMSEARCH_API_USER="..."
# PLAGIARISMSEARCH_API_KEY="..."
```

## Performance

Một vài tips để tối ưu:

**Cache**: Plagiarism cache giảm 90% số lượng API calls cho văn bản lặp lại. Cache lưu trên disk nên persistent giữa các session.

**Parallel processing**: Plagiarism check chạy 3 chunks cùng lúc, giảm thời gian 60-70% so với tuần tự.

**Rate limiting**: Tự động retry khi hit rate limit, exponential backoff để tránh spam API.

## Security

- API keys lưu trong `.env` và không commit vào git
- Validation input (file size, format) trước khi xử lý
- Rate limiting để tránh abuse
- Cache isolation với namespace riêng cho từng feature