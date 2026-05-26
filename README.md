# ArticleCheck AI

Hệ thống kiểm tra bài báo khoa học tự động với AI - công cụ toàn diện để kiểm tra cấu trúc, chính tả và đạo văn cho các bài báo khoa học tiếng Việt và tiếng Anh.

## Tính năng chính

### Kiểm tra cấu trúc

Phát hiện các phần bắt buộc còn thiếu trong bài báo: Tựa đề, Tóm tắt, Từ khóa, Tài liệu tham khảo. Hệ thống kiểm tra cả song ngữ Việt-Anh và sử dụng LLM để phân loại các phần trong văn bản một cách thông minh.

### Kiểm tra chính tả

Người dùng chọn ngôn ngữ kiểm tra trong sidebar. App chỉ chạy checker tương ứng với ngôn ngữ đã chọn:

**Tiếng Anh**: Tích hợp LanguageTool local server để kiểm tra lỗi chính tả tiếng Anh. Các lỗi tiếng Anh được highlight màu đỏ.

**Tiếng Việt**: Sử dụng Hunspell với từ điển tiếng Việt để kiểm tra lỗi chính tả theo danh sách từ hợp lệ.

Khi chọn tiếng Anh, lỗi được highlight màu đỏ. Khi chọn tiếng Việt, lỗi được highlight màu vàng.

### Kiểm tra đạo văn

Tích hợp API kiểm soát đạo văn Turnitin/iThenticate chuẩn quốc tế với các tính năng:
- Upload nguyên file DOCX lên Turnitin/iThenticate như một submission duy nhất.
- Poll trạng thái report đến khi Turnitin/iThenticate trả kết quả hoàn tất.
- Chuẩn hóa kết quả trả về để UI hiển thị tỷ lệ trùng lặp, nguồn liên quan và link report.

## Cài đặt

### Yêu cầu

- Python 3.8 trở lên
- Java 17 trở lên (dùng cho LanguageTool local server)

### Các bước cài đặt

Clone repository:
```bash
git clone https://github.com/ductruong912/spell-check-paper.git
cd spell-check-paper
```

Cài đặt dependencies Python:
```bash
python -m venv venv
python.exe -m pip install --upgrade pip
pip install -r requirements.txt
```

Tạo file `.env` trong thư mục gốc với nội dung:
```bash
cp .env.excample .env
```

Lấy API keys:
- OpenAI: https://platform.openai.com/api-keys
- Turnitin/iThenticate: Cung cấp API Key và Secret do trường đại học hoặc tổ chức cấp.

Chạy ứng dụng:
```bash
streamlit run app.py
```

Mở trình duyệt tại http://localhost:8502

Port mặc định được cấu hình trong `.streamlit/config.toml`:

```toml
[server]
address = "0.0.0.0"
port = 8502
```

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
│   │   ├── checker.py         # Orchestration
│   │   └── pipeline.py        # Language-selected spell pipeline (EN or VI)
│   │
│   ├── plagiarism/            # Plagiarism checking
│   │   ├── api_client.py      # Turnitin/iThenticate API
│   │   ├── checker.py         # Check orchestration
│   │
│   ├── ui/                    # UI components
│   │   ├── components.py      # HTML rendering
│   │   ├── handlers.py        # Streamlit handlers
│   │   └── layout.py          # Results display
│   │
│   └── utils/                 # Utilities
│       ├── config.py          # Configuration
│       ├── validation.py      # API validation
│
└── tests/                     # Unit tests
```

## Cấu hình


### Logging

Mặc định logging ở mức INFO. Để debug, mở `app.py` và đổi thành:
```python
logging.basicConfig(level=logging.DEBUG)
```

## Sử dụng

Upload file DOCX (tối đa 200MB), chọn các loại kiểm tra cần thực hiện:

- **Kiểm tra cấu trúc**: Phát hiện phần thiếu (Tựa đề VI/EN, Tóm tắt, Từ khóa, Tài liệu tham khảo)
- **Kiểm tra chính tả**: Chọn Tiếng Anh hoặc Tiếng Việt; app chỉ chạy checker của ngôn ngữ đã chọn.
- **Kiểm tra đạo văn**: Tỷ lệ trùng lặp và danh sách nguồn

Kết quả hiển thị ngay trên web interface với highlight màu cho từng loại lỗi.
