"""Domain models for article structure review."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class SectionHit:
    status: str  # "ok" | "missing"
    evidence: str = ""
    llm_confidence: float = 0.0
    notes: str = ""


@dataclass
class StructureReport:
    ok: bool
    sections: Dict[str, SectionHit]
    template_name: str
    template_version: int
    required_ids: Set[str]
    debug_info: Dict[str, Any]
    error: Optional[str] = None
    file: str = ""
    section_labels: Dict[str, str] = field(default_factory=dict)

    @property
    def notes(self) -> List[str]:
        notes = self.debug_info.get("notes", [])
        if isinstance(notes, list):
            return [str(note) for note in notes]
        return [str(notes)]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "ok": self.ok,
            "sections": {
                section_id: asdict(hit)
                for section_id, hit in self.sections.items()
            },
            "template_name": self.template_name,
            "template_version": self.template_version,
            "required_ids": sorted(self.required_ids),
            "debug_info": self.debug_info,
            "notes": self.notes,
            "error": self.error,
        }

    def to_ui_dict(self) -> Dict[str, Any]:
        data = self.to_dict()
        data["sections"] = {
            section_id: {
                **section,
                "label": self.section_labels.get(section_id, section_id),
                "required": section_id in self.required_ids,
            }
            for section_id, section in data["sections"].items()
        }
        return data
