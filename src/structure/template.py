"""Load and validate configurable paper-structure templates."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import STRUCTURE_TEMPLATE_PATH


DEFAULT_TEMPLATE_PATH = Path(__file__).with_name("templates") / "default.json"
_SECTION_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class StructureSection:
    id: str
    label: str
    required: bool
    rules: Tuple[str, ...]


@dataclass(frozen=True)
class StructureTemplate:
    name: str
    version: int
    sections: Tuple[StructureSection, ...]
    path: Path

    @property
    def targets(self) -> List[Tuple[str, str]]:
        return [(section.id, section.label) for section in self.sections]

    @property
    def target_ids(self) -> List[str]:
        return [section.id for section in self.sections]

    @property
    def required(self) -> Dict[str, bool]:
        return {section.id: section.required for section in self.sections}

    @property
    def required_ids(self) -> set[str]:
        return {section.id for section in self.sections if section.required}

    @property
    def targets_json(self) -> str:
        return json.dumps(
            [
                {
                    "id": section.id,
                    "label": section.label,
                    "required": section.required,
                }
                for section in self.sections
            ],
            ensure_ascii=False,
        )

    @property
    def field_rules_text(self) -> str:
        chunks = []
        for index, section in enumerate(self.sections, start=1):
            rules = "\n".join(f"- {rule}" for rule in section.rules)
            chunks.append(f"{index}) {section.id}:\n{rules}")
        return "\n\n".join(chunks)


def _as_non_empty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Structure template field '{field}' must be a non-empty string")
    return value.strip()


def _as_rules(value: Any, field: str) -> Tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"Structure template field '{field}' must be a non-empty list")
    rules = tuple(_as_non_empty_str(item, field) for item in value)
    return rules


def _load_sections(raw_sections: Any) -> Tuple[StructureSection, ...]:
    if not isinstance(raw_sections, list) or not raw_sections:
        raise ValueError("Structure template must contain a non-empty 'sections' list")

    seen = set()
    sections = []
    for index, raw in enumerate(raw_sections):
        if not isinstance(raw, dict):
            raise ValueError(f"Structure template section at index {index} must be an object")

        section_id = _as_non_empty_str(raw.get("id"), "sections[].id")
        if not _SECTION_ID_RE.match(section_id):
            raise ValueError(
                "Structure template section id must start with a lowercase letter "
                "and contain only lowercase letters, numbers, and underscores"
            )
        if section_id in seen:
            raise ValueError(f"Duplicate structure template section id: {section_id}")
        seen.add(section_id)

        required = raw.get("required")
        if not isinstance(required, bool):
            raise ValueError(f"Structure template section '{section_id}' requires boolean 'required'")

        sections.append(
            StructureSection(
                id=section_id,
                label=_as_non_empty_str(raw.get("label"), f"{section_id}.label"),
                required=required,
                rules=_as_rules(raw.get("rules"), f"{section_id}.rules"),
            )
        )
    return tuple(sections)


def load_structure_template(path: Optional[str | Path] = None) -> StructureTemplate:
    template_path = Path(path or STRUCTURE_TEMPLATE_PATH or DEFAULT_TEMPLATE_PATH)
    template_path = template_path.expanduser()
    if not template_path.is_file():
        raise FileNotFoundError(f"Structure template file not found: {template_path}")

    with template_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    if not isinstance(raw, dict):
        raise ValueError("Structure template root must be an object")

    version = raw.get("version", 1)
    if not isinstance(version, int):
        raise ValueError("Structure template field 'version' must be an integer")

    return StructureTemplate(
        name=_as_non_empty_str(raw.get("name", "default"), "name"),
        version=version,
        sections=_load_sections(raw.get("sections")),
        path=template_path,
    )


@lru_cache(maxsize=1)
def get_structure_template() -> StructureTemplate:
    return load_structure_template()


STRUCTURE_TEMPLATE = get_structure_template()
TARGETS = STRUCTURE_TEMPLATE.targets
TARGET_IDS = STRUCTURE_TEMPLATE.target_ids
TARGETS_JSON = STRUCTURE_TEMPLATE.targets_json
REQUIRED = STRUCTURE_TEMPLATE.required
REQUIRED_IDS = STRUCTURE_TEMPLATE.required_ids
