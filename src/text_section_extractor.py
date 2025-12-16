"""
Extract sections from research paper text for selective plagiarism checking.
"""

import re
from typing import List, Dict, Tuple


# Common section titles in Vietnamese research papers
SECTION_TITLES_VI = [
    "Mở đầu",
    "Giới thiệu",
    "Đặt vấn đề",
    "Cơ sở lý luận",
    "Cơ sở lý thuyết",
    "Tổng quan nghiên cứu",
    "Phương pháp nghiên cứu",
    "Vật liệu và phương pháp",
    "Phương pháp",
    "Kết quả nghiên cứu",
    "Kết quả",
    "Kết quả và thảo luận",
    "Thảo luận",
    "Bàn luận",
    "Kết luận",
    "Kết luận và kiến nghị",
]

# English section titles
SECTION_TITLES_EN = [
    "Introduction",
    "Background",
    "Literature Review",
    "Related Work",
    "Methodology",
    "Methods",
    "Materials and Methods",
    "Results",
    "Results and Discussion",
    "Discussion",
    "Conclusion",
    "Conclusions",
]

# Sections to skip (should not check for plagiarism)
SKIP_SECTIONS = [
    "Tài liệu tham khảo",
    "References",
    "Bibliography",
    "Phụ lục",
    "Appendix",
    "Appendices",
    "Lời cảm ơn",
    "Acknowledgements",
    "Acknowledgments",
]


def normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    return re.sub(r'\s+', ' ', (text or '').strip()).lower()


def find_sections(text: str) -> List[Dict[str, str]]:
    """
    Extract sections from research paper text.
    
    Returns:
        List of dicts with 'title', 'content', 'start_pos', 'end_pos'
    """
    all_titles = SECTION_TITLES_VI + SECTION_TITLES_EN
    skip_titles = SKIP_SECTIONS
    
    # Create normalized title mapping
    title_map = {}
    for title in all_titles + skip_titles:
        title_map[normalize_text(title)] = title
    
    lines = text.splitlines()
    sections = []
    
    # Find section start positions
    section_starts = []
    
    for i, line in enumerate(lines):
        line_norm = normalize_text(line)
        
        # Check if line is a section title
        if line_norm in title_map:
            original_title = title_map[line_norm]
            
            # Skip if it's in skip list
            if original_title in skip_titles:
                # Mark end of content
                section_starts.append((i, "END_OF_CONTENT", line.strip()))
                break
            
            section_starts.append((i, original_title, line.strip()))
    
    if not section_starts:
        # No sections found, return whole text as "Document"
        return [{
            'title': 'Toàn bộ văn bản',
            'content': text.strip(),
            'start_pos': 0,
            'end_pos': len(text),
            'word_count': len(text.split())
        }]
    
    # Extract content between sections
    for idx, (line_idx, title, original_line) in enumerate(section_starts):
        if title == "END_OF_CONTENT":
            break
        
        # Find end of this section (start of next section or end of list)
        if idx + 1 < len(section_starts):
            end_line_idx = section_starts[idx + 1][0]
        else:
            end_line_idx = len(lines)
        
        # Get content (skip title line)
        content_lines = lines[line_idx + 1:end_line_idx]
        content = '\n'.join(content_lines).strip()
        
        # Skip empty sections
        if not content or len(content) < 100:
            continue
        
        sections.append({
            'title': title,
            'original_title': original_line,
            'content': content,
            'start_pos': line_idx,
            'end_pos': end_line_idx,
            'word_count': len(content.split()),
            'char_count': len(content)
        })
    
    return sections


def filter_sections_for_plagiarism_check(sections: List[Dict]) -> List[Dict]:
    """
    Filter sections that should be checked for plagiarism.
    Skip: Abstract, Keywords, Acknowledgements, References, etc.
    
    Returns:
        Filtered list of sections
    """
    skip_keywords = [
        'tóm tắt', 'abstract', 'từ khóa', 'keywords',
        'tài liệu tham khảo', 'references', 'bibliography',
        'lời cảm ơn', 'acknowledgement', 'phụ lục', 'appendix'
    ]
    
    filtered = []
    for section in sections:
        title_lower = section['title'].lower()
        
        # Skip if title contains skip keywords
        if any(kw in title_lower for kw in skip_keywords):
            continue
        
        # Skip if too short (likely not main content)
        if section['word_count'] < 50:
            continue
        
        filtered.append(section)
    
    return filtered


def get_main_content_only(text: str) -> str:
    """
    Extract only main content (excluding references, abstract, etc.)
    
    Returns:
        Main content text
    """
    sections = find_sections(text)
    filtered = filter_sections_for_plagiarism_check(sections)
    
    # Combine all filtered sections
    main_content = '\n\n'.join([s['content'] for s in filtered])
    return main_content


def get_section_summary(sections: List[Dict]) -> str:
    """
    Get a summary of sections for display.
    
    Returns:
        Formatted summary string
    """
    if not sections:
        return "Không tìm thấy section"
    
    lines = []
    for i, section in enumerate(sections, 1):
        lines.append(
            f"{i}. {section['title']} "
            f"({section['word_count']} từ, {section['char_count']} ký tự)"
        )
    
    return '\n'.join(lines)


if __name__ == '__main__':
    # Test
    sample_text = """
    Tóm tắt
    Đây là phần tóm tắt của bài báo.
    
    Từ khóa: AI, Machine Learning
    
    Mở đầu
    Đây là phần mở đầu với nội dung dài hơn nhiều để test extraction.
    Lorem ipsum dolor sit amet consectetur adipiscing elit.
    
    Phương pháp nghiên cứu
    Phương pháp được sử dụng trong nghiên cứu này.
    
    Kết quả
    Kết quả nghiên cứu cho thấy...
    
    Tài liệu tham khảo
    1. Reference 1
    2. Reference 2
    """
    
    sections = find_sections(sample_text)
    print("All sections:")
    print(get_section_summary(sections))
    
    print("\n" + "="*60)
    print("Sections for plagiarism check:")
    filtered = filter_sections_for_plagiarism_check(sections)
    print(get_section_summary(filtered))
