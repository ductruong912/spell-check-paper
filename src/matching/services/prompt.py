import json
from typing import Any

from llm import create_openai_client, resolve_model
from validation import APIValidationError


class OpenAIConfigurationError(RuntimeError):
    pass


class OpenAIResponseParseError(RuntimeError):
    pass


ARTICLE_METADATA_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "keywords"],
    "properties": {
        "title": {
            "type": "object",
            "additionalProperties": False,
            "required": ["value", "evidence"],
            "properties": {
                "value": {"type": ["string", "null"]},
                "evidence": {"type": ["string", "null"]},
            },
        },
        "keywords": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["value", "evidence"],
                "properties": {
                    "value": {"type": "string"},
                    "evidence": {"type": "string"},
                },
            },
        },
    },
}


SYSTEM_PROMPT = """
Bạn là hệ thống trích xuất metadata bài báo khoa học.
Chỉ trích xuất dữ liệu xuất hiện rõ trong text được cung cấp.
Không suy luận keyword từ nội dung bài.
Nếu không thấy title rõ ràng, trả title.value là null và title.evidence là null.
Chỉ trả keywords nếu text có mục Keywords, Từ khóa, Index Terms, hoặc biến thể tương đương.
Mỗi title/keyword có giá trị phải đi kèm evidence là đoạn text nguyên văn hoặc gần nguyên văn từ bài.
""".strip()


def build_openai_input(article_text: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Trích xuất title và keywords từ text bài báo sau. "
                "Không suy luận dữ liệu không xuất hiện trong bài.\n\n"
                f"{article_text}"
            ),
        },
    ]


def parse_metadata_response(response: Any) -> dict[str, Any]:
    output_text = getattr(response, "output_text", None)
    if not isinstance(output_text, str) or not output_text.strip():
        raise OpenAIResponseParseError("OpenAI response did not include output_text.")
    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise OpenAIResponseParseError("OpenAI response was not valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise OpenAIResponseParseError("OpenAI response JSON must be an object.")
    return parsed


def _default_client() -> Any:
    """Build the shared OpenAI client, mapping config errors to this module's type."""
    try:
        return create_openai_client()
    except APIValidationError as exc:
        raise OpenAIConfigurationError(str(exc)) from exc


def extract_metadata_with_openai(
    article_text: str,
    *,
    client: Any | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    selected_model = resolve_model(model)
    openai_client = client or _default_client()
    response = openai_client.responses.create(
        model=selected_model,
        input=build_openai_input(article_text),
        text={
            "format": {
                "type": "json_schema",
                "name": "article_metadata",
                "schema": ARTICLE_METADATA_SCHEMA,
                "strict": True,
            }
        },
    )
    return parse_metadata_response(response)
