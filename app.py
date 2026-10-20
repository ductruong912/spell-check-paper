"""Streamlit app: kiểm tra cấu trúc bài báo DOCX/PDF."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import streamlit as st

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

BASE_DIR = Path(__file__).parent.resolve()
SRC_DIR = BASE_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

from config import settings
from documents.preview import DocumentPreview
from documents.temp_files import cleanup_old_tmp_files
from services import file_signature, prepare_document
from services import check_structure as run_structure_review
from ui import APP_CSS, document_action_state
from ui import render_document, render_structure, render_workspace_header

st.set_page_config(page_title=settings.app_title, layout="wide")


def _cleanup_old_tmp_files(ttl_seconds: int = settings.temp_cleanup_ttl_seconds) -> None:
    """Best-effort cleanup for temp files left by timed-out work."""
    garbage = st.session_state.get("_tmp_garbage", [])
    if not garbage:
        return
    st.session_state["_tmp_garbage"] = cleanup_old_tmp_files(garbage, ttl_seconds)


def _reset_analysis_state() -> None:
    st.session_state.structure = {}
    st.session_state.structure_check_error = None


def _reset_document_state() -> None:
    st.session_state.preview = None
    st.session_state.word_count = 0
    st.session_state.file_name = ""
    st.session_state.file_size = 0
    st.session_state.file_content = b""
    st.session_state.file_signature = None
    st.session_state.document_cache = None
    st.session_state.prepared_document = None
    st.session_state.review_state = "idle"
    _reset_analysis_state()


def _prepare_uploaded_document(
    file_name: str,
    content: bytes,
    signature: tuple[str, int, str] | None = None,
) -> bool:
    """Prepare local preview/cache for a newly selected file."""
    signature = signature or file_signature(file_name, content)
    if signature == st.session_state.file_signature:
        return False

    _reset_document_state()
    st.session_state.file_name = file_name
    st.session_state.file_size = len(content)
    st.session_state.file_content = content
    st.session_state.file_signature = signature

    try:
        prepared = prepare_document(file_name, content)
        st.session_state.prepared_document = prepared
        st.session_state.document_cache = prepared.document_view
        st.session_state.preview = prepared.preview
        st.session_state.word_count = prepared.word_count
        st.session_state.review_state = "ready"
        logger.info(
            "Prepared preview: file=%s words=%s",
            file_name,
            st.session_state.word_count,
        )
    except Exception as exc:
        logger.error("Document preparation failed: %s", exc, exc_info=True)
        st.session_state.preview = DocumentPreview(
            kind="unavailable",
            content=None,
            warning=f"Không thể chuẩn bị tài liệu: {exc}",
        )
        st.session_state.review_state = "error"
        st.session_state.structure_check_error = str(exc)
    return True


def _queue_uploaded_document(uploaded_file) -> bool:
    """Queue uploaded bytes so the UI can render a busy state before parsing."""
    if uploaded_file is None:
        return False

    content = uploaded_file.getvalue()
    signature = file_signature(uploaded_file.name, content)
    pending = st.session_state.get("pending_upload")
    pending_signature = pending.get("signature") if isinstance(pending, dict) else None
    if signature == st.session_state.file_signature or signature == pending_signature:
        return False

    st.session_state.pending_upload = {
        "file_name": uploaded_file.name,
        "content": content,
        "signature": signature,
    }
    st.session_state.review_state = "preparing"
    _reset_analysis_state()
    return True


def _prepare_pending_upload() -> bool:
    pending = st.session_state.get("pending_upload")
    if not isinstance(pending, dict):
        return False

    st.session_state.pending_upload = None
    return _prepare_uploaded_document(
        pending["file_name"],
        pending["content"],
        pending["signature"],
    )


def _request_structure_check() -> bool:
    if st.session_state.review_state != "ready":
        return False
    st.session_state.review_state = "running"
    st.session_state.structure_check_requested = True
    st.session_state.structure_check_error = None
    return True


def _run_structure_check() -> None:
    if st.session_state.review_state not in ("ready", "running"):
        return

    st.session_state.review_state = "running"
    st.session_state.structure_check_requested = False
    try:
        if st.session_state.prepared_document is None:
            raise RuntimeError("Tài liệu chưa được chuẩn bị để kiểm tra.")

        report = run_structure_review(st.session_state.prepared_document)
        result = report.to_ui_dict()
        deferred_tmp_path = (result.get("debug_info") or {}).get("deferred_tmp_path")
        if deferred_tmp_path:
            st.session_state["_tmp_garbage"].append(deferred_tmp_path)
            logger.warning("Keeping temp file for deferred cleanup: %s", deferred_tmp_path)

        st.session_state.structure = result
        st.session_state.structure_check_error = (
            result.get("error")
            if not result.get("ok", False)
            else None
        )
        if st.session_state.structure_check_error:
            st.session_state.review_state = (
                "timeout"
                if st.session_state.structure_check_error.startswith("Quá thời gian")
                else "error"
            )
        else:
            st.session_state.review_state = "completed"
        logger.info("Finished structure check: file=%s", st.session_state.file_name)
    except Exception as exc:
        logger.error("Structure check failed: %s", exc, exc_info=True)
        st.session_state.review_state = "error"
        st.session_state.structure_check_error = str(exc)


def _run_pending_work() -> None:
    """Run queued expensive work only after busy UI has been rendered."""
    if st.session_state.get("pending_upload") is not None:
        _prepare_pending_upload()
        st.rerun()

    if (
        st.session_state.get("structure_check_requested")
        and st.session_state.review_state == "running"
    ):
        _run_structure_check()
        st.rerun()


for key, value in {
    "preview": None,
    "word_count": 0,
    "file_name": "",
    "file_size": 0,
    "file_content": b"",
    "file_signature": None,
    "document_cache": None,
    "prepared_document": None,
    "structure": {},
    "structure_check_error": None,
    "review_state": "idle",
    "uploader_version": 0,
    "pending_upload": None,
    "structure_check_requested": False,
    "_tmp_garbage": [],
}.items():
    st.session_state.setdefault(key, value)

st.markdown(APP_CSS, unsafe_allow_html=True)

_cleanup_old_tmp_files()

upload_key = f"document_upload_{st.session_state.uploader_version}"

workspace = st.container(key="review_workspace")
uploaded_file = None
check_clicked = False
upload_queued = False
check_requested = False
with workspace:
    action_col, preview_col, results_col = st.columns(
        [0.15, 0.62, 0.23],
        gap="medium",
    )

    with action_col:
        st.markdown(
            '<div class="app-appbar">'
            '<div class="app-brand">'
            f'<div><div class="app-brand__name">{settings.brand_label}</div>'
            "</div>"
            "</div></div>",
            unsafe_allow_html=True,
        )
        action_state = document_action_state(st.session_state.review_state)
        action_panel_key = (
            "document_actions_idle"
            if st.session_state.review_state == "idle"
            else "document_actions_active"
        )
        with st.container(border=True, key=action_panel_key):
            st.markdown(
                '<div class="app-document-actions">'
                '<div class="app-document-actions__eyebrow">Thao tác</div>'
                f'<div class="app-document-actions__title">{action_state.title}</div>'
                f'<div class="app-document-actions__subtitle">{action_state.subtitle}</div>'
                "</div>",
                unsafe_allow_html=True,
            )
            uploaded_file = st.file_uploader(
                (
                    "Chọn tài liệu"
                    if st.session_state.review_state == "idle"
                    else "Đổi tài liệu"
                ),
                type=list(settings.supported_extensions),
                key=upload_key,
                label_visibility="collapsed",
            )

            if action_state.show_structure_check:
                check_clicked = st.button(
                    "Kiểm tra cấu trúc",
                    type="primary",
                    use_container_width=True,
                )

    upload_queued = _queue_uploaded_document(uploaded_file)
    if check_clicked:
        check_requested = _request_structure_check()

    with preview_col:
        workspace_header_placeholder = st.empty()
        render_workspace_header(
            workspace_header_placeholder,
            file_name=st.session_state.file_name,
            file_size=st.session_state.file_size,
            word_count=st.session_state.word_count,
            state=st.session_state.review_state,
        )
        doc_placeholder = st.empty()

    with results_col:
        structure_placeholder = st.empty()

render_structure(
    structure_placeholder,
    data=st.session_state.structure or {},
    state=(
        st.session_state.review_state
        if st.session_state.review_state in ("preparing", "running", "error", "timeout", "ready")
        else "ok" if st.session_state.structure else "idle"
    ),
    error=st.session_state.structure_check_error,
)

render_document(
    doc_placeholder,
    file_name=st.session_state.file_name,
    preview=st.session_state.preview,
    word_count=st.session_state.word_count,
)

if upload_queued or check_requested:
    st.rerun()

_run_pending_work()
