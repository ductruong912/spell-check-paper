"""UI components and handlers."""
from .components import highlight_html
from .handlers import check_structure, check_spell, check_plagiarism
from .layout import render_plagiarism_section, render_structure_section

__all__ = [
    "highlight_html", 
    "check_structure", 
    "check_spell", 
    "check_plagiarism",
    "render_plagiarism_section",
    "render_structure_section"
]
