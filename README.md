# ArticleCheck AI

An intelligent AI-powered system for scientific manuscript structure verification, domain-scoped title/keyword validation, and peer reviewer recommendations.

---

## Key Features

- **Document Ingestion & Preview**: Local text extraction and document preview for DOCX and PDF manuscripts using `python-docx` and `PyMuPDF` (with LibreOffice PDF rendering fallback to HTML via Mammoth).
- **Manuscript Structure Analysis**: LLM-driven section extraction and structure compliance checking via OpenAI, fully customizable through JSON templates.
- **Domain-Scoped Relevance Matching**: Hybrid dense retrieval (`sentence-transformers`), lexical sparse vectors (BM25), and cross-encoder reranking within Qdrant local vector stores.
- **Intelligent Reviewer Recommendation**: Recommends candidate reviewers grouped into prioritized pools based on published manuscript history and past review experience.
- **Dual Interface**:
  - **Streamlit Web UI**: Interactive dashboard for uploading manuscripts, previewing pages, and inspecting structure validation reports in real time.
  - **FastAPI Backend**: Production-ready RESTful endpoints for integration into editorial and publishing workflows.

---

## Architecture & Project Structure

```text
.
├── app.py                     # Streamlit web UI
├── main.py                    # FastAPI entrypoint
├── requirements.txt           # Python dependencies
├── src/
│   ├── config.py              # Configuration & settings management
│   ├── services.py            # Orchestration layer for document processing
│   ├── validation.py          # Input validation, OpenAI client setup, error mapping
│   ├── domain_ids.py          # Domain ID normalization and store path handling
│   ├── documents/
│   │   ├── parser.py          # Document parsing (DOCX / PDF to unified DocumentView)
│   │   ├── extract.py         # Text extraction routines
│   │   ├── preview.py         # PDF rendering & DOCX-to-HTML/PDF preview
│   │   └── temp_files.py      # Lifecycle management for temporary files
│   ├── structure/
│   │   ├── classifier.py      # LLM section classification & output normalization
│   │   ├── checker.py         # Confidence thresholding & StructureReport generation
│   │   ├── models.py          # Data models for structure checking
│   │   ├── prompt.py          # LLM prompts for section extraction
│   │   ├── template.py        # Structure template loader & validator
│   │   └── templates/
│   │       └── default.json   # Default manuscript sections template
│   ├── matching/
│   │   ├── models/matching.py # Data schemas for manuscript matching
│   │   ├── repositories/
│   │   │   └── valid_paper_store.py # Domain-scoped Qdrant store for valid papers
│   │   └── services/
│   │       ├── embeddings.py        # Dense & sparse vector embeddings
│   │       ├── preprocessing.py     # Text cleaning & normalization
│   │       └── valid_paper_match.py # Hybrid retrieval & scoring engine
│   ├── reviewers/
│   │   ├── models.py          # Data models for reviewer profiles & suggestions
│   │   ├── repositories/
│   │   │   └── reviewer_store.py    # Vector repository for reviewer expertise
│   │   └── services/
│   │       └── reviewer_suggestion.py # Scoring, reranking, and pool organization
│   └── ui/
│       ├── layout.py          # Layout components for Streamlit
│       ├── render.py          # HTML/CSS renderers for preview and reports
│       └── theme.py           # Design tokens, color palette, and stylesheet
└── tests/
```

---

## Getting Started

### Prerequisites

- **Python**: 3.10 or later
- **OpenAI API Key**: Required for structure classification (`OPENAI_API_KEY`)
- **LibreOffice** *(Optional)*: Recommended for high-fidelity DOCX-to-PDF rendering

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/ductruong912/spell-check-paper.git
   cd spell-check-paper
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On Linux/macOS:
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Configure environment variables**:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and set your `OPENAI_API_KEY`.

---

## Running the Application

### Streamlit Web Interface

```bash
streamlit run app.py
```
Open your browser at `http://localhost:8501` to use the interactive manuscript review interface.

### FastAPI Server

```bash
python main.py
# or using uvicorn directly:
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```
Access the interactive Swagger API documentation at:
- `http://127.0.0.1:8000/docs`

---

## REST API Reference

All domain-specific endpoints require an `id` query parameter (e.g., `?id=sample_domain`). Domain IDs are case-insensitive and automatically trimmed and lowercased.

### 1. Manuscript Structure Check

`POST /check-structure?id=sample_domain`

Upload a manuscript (`.docx` or `.pdf`) to extract metadata and verify required sections against the structure template.

**Form Data:**
- `file`: Multipart binary file (`.docx` or `.pdf`)

**Response:**
```json
{
  "sections": {
    "title_en": {
      "present": true,
      "confidence": 0.98,
      "evidence": "Deep Learning Approaches for Natural Language Processing",
      "reason": "Clear standalone title found in header."
    },
    "abstract_en": {
      "present": true,
      "confidence": 0.95,
      "evidence": "This paper presents...",
      "reason": "Abstract section detected with accompanying summary text."
    }
  },
  "extracted": {
    "title_en": "Deep Learning Approaches for Natural Language Processing",
    "keywords_en": ["deep learning", "nlp", "transformers"]
  },
  "metadata": {
    "title": "Deep Learning Approaches for Natural Language Processing",
    "keywords": ["deep learning", "nlp", "transformers"],
    "language": "en"
  },
  "domain_match": {
    "overall_score": 0.86,
    "title_score": 0.84,
    "keyword_score": 0.88,
    "is_suitable": true
  }
}
```

---

### 2. Valid Papers Ingestion

`POST /valid-papers/ingest/batch?id=sample_domain`

Batch-ingest reference manuscripts into the vector store for a specific domain. Uses safe-swap staging to guarantee atomic index updates.

**Request Body:**
```json
[
  {
    "title": "Attention Is All You Need",
    "keywords": ["attention mechanism", "neural networks", "transformer"]
  }
]
```

---

### 3. Reviewer Profiles Ingestion

`POST /reviewers/ingest?id=sample_domain`

Populate reviewer profiles for a domain, including authored papers and previous review assignments.

**Request Body:**
```json
[
  {
    "user_id": 101,
    "user": "reviewer_alex",
    "article": "A Survey on Graph Neural Networks, Transformer Optimization",
    "article_review": ["Attention Models in Vision", "Self-Supervised Speech"]
  }
]
```

---

### 4. Reviewer Recommendation

`POST /reviewers/suggest?id=sample_domain`

Recommends suitable reviewers ranked by relevance to the submitted manuscript title.

**Request Body:**
```json
{
  "title": "Self-Supervised Vision Transformers for Biomedical Imaging",
  "explain": true
}
```

**Response:**
Reviewers are categorized into three prioritized pools:
1. **Pool 1**: Reviewers with matching experience in *both* authored papers and past peer reviews.
2. **Pool 2**: Reviewers with matching experience in *past peer reviews*.
3. **Pool 3**: Reviewers with matching experience in *authored papers*.

```json
{
  "suggestions": {
    "pool_1": [
      {
        "user_id": 101,
        "user": "reviewer_alex",
        "score": 0.91,
        "authored_score": 0.88,
        "reviewed_score": 0.93,
        "matched_articles": ["Transformer Optimization"],
        "matched_reviewed_articles": ["Attention Models in Vision"]
      }
    ],
    "pool_2": [],
    "pool_3": []
  }
}
```

---

## Configuration Reference

Key settings configurable via environment variables in `.env`:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `OPENAI_API_KEY` | *(None)* | OpenAI API key for manuscript structure classification |
| `DEFAULT_LLM_MODEL` | `gpt-4.1-mini` | LLM model used for classification |
| `DEFAULT_MIN_CONFIDENCE` | `0.70` | Minimum confidence score to accept an extracted section |
| `STRUCTURE_TEMPLATE_PATH` | *(Default)* | Custom JSON template file for section criteria |
| `VALID_PAPER_STORE_PATH` | `data_valid_paper_store` | Path for domain-scoped valid paper Qdrant stores |
| `VALID_MODEL_NAME` | `BAAI/bge-small-en-v1.5` | Dense embedding model for manuscripts |
| `VALID_RERANKER_MODEL_NAME` | `cross-encoder/stsb-distilroberta-base` | Cross-encoder model for reranking candidates |
| `VALID_SUITABLE_THRESHOLD` | `0.50` | Threshold score for domain suitability decision |
| `REVIEWER_STORE_PATH` | `data_reviewer_store` | Path for Qdrant reviewer expertise stores |
| `REVIEWER_RERANKER_MODEL_NAME`| `cross-encoder/stsb-distilroberta-base` | Cross-encoder model for reviewer candidate scoring |

---

## Testing

Run unit and integration tests using `pytest`:

```bash
pytest -q
```

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
