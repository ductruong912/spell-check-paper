# ArticleCheck AI

Ứng dụng Streamlit dùng AI để kiểm tra cấu trúc bài báo khoa học từ file DOCX.

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

Ứng dụng đọc nội dung DOCX, tạo view có cấu trúc từ các đoạn văn, sau đó dùng LLM để phân loại từng mục và trả về bảng trạng thái.

## Cài Đặt

### Yêu Cầu

- Python 3.8 trở lên
- OpenAI API key

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

```text
.
├── app.py
├── requirements.txt
├── src/
│   ├── document_backend.py
│   ├── structure/
│   │   ├── classifier.py
│   │   ├── checker.py
│   │   └── prompt.py
│   ├── ui/
│   │   ├── handlers.py
│   │   ├── layout.py
│   │   └── render.py
│   └── utils/
│       ├── config.py
│       ├── document_parser.py
│       └── validation.py
└── tests/
```

## Sử Dụng

1. Upload file DOCX trong sidebar.
2. Bấm **Kiểm tra cấu trúc**.
3. Xem nội dung tài liệu và bảng trạng thái các mục bắt buộc.