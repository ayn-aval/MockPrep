"""
PDF Parser — Extracts questions and options from PDF files.
Uses hybrid approach: PyMuPDF for digital PDFs, OCR fallback for scanned ones.
Supports mixed question/option formats via regex.
Preserves mathematical notation (fractions, powers, roots, etc.)
"""

import re
import unicodedata
import fitz  # PyMuPDF
from pdf2image import convert_from_path
import pytesseract


# ===== Mathematical Symbol Normalization =====

# Common Unicode math characters that PDFs may contain
MATH_REPLACEMENTS = {
    '\u00b2': '²',   # superscript 2
    '\u00b3': '³',   # superscript 3
    '\u00b9': '¹',   # superscript 1
    '\u2070': '⁰',   # superscript 0
    '\u2074': '⁴',   # superscript 4
    '\u2075': '⁵',   # superscript 5
    '\u2076': '⁶',   # superscript 6
    '\u2077': '⁷',   # superscript 7
    '\u2078': '⁸',   # superscript 8
    '\u2079': '⁹',   # superscript 9
    '\u00bd': '½',   # fraction 1/2
    '\u00bc': '¼',   # fraction 1/4
    '\u00be': '¾',   # fraction 3/4
    '\u2153': '⅓',   # fraction 1/3
    '\u2154': '⅔',   # fraction 2/3
    '\u221a': '√',   # square root
    '\u221b': '∛',   # cube root
    '\u00d7': '×',   # multiplication
    '\u00f7': '÷',   # division
    '\u2264': '≤',   # less than or equal
    '\u2265': '≥',   # greater than or equal
    '\u2260': '≠',   # not equal
    '\u03c0': 'π',   # pi
    '\u221e': '∞',   # infinity
    '\u2211': '∑',   # summation
    '\u222b': '∫',   # integral
    '\u0394': 'Δ',   # delta
    '\u03b1': 'α',   # alpha
    '\u03b2': 'β',   # beta
    '\u03b3': 'γ',   # gamma
    '\u03b8': 'θ',   # theta
    '\u2081': '₁',   # subscript 1
    '\u2082': '₂',   # subscript 2
    '\u2083': '₃',   # subscript 3
    '\u2192': '→',   # right arrow
    '\u2190': '←',   # left arrow
    '\u00b0': '°',   # degree
    '\u2030': '‰',   # per mille
    '\u2248': '≈',   # approximately
    '\u2261': '≡',   # identical
}


def normalize_math_text(text):
    """
    Preserve and normalize mathematical symbols in text.
    Converts common OCR misreads and normalizes Unicode math chars.
    """
    # Keep existing Unicode symbols as-is (they render fine in HTML)
    # Fix common OCR misreads for math
    ocr_fixes = [
        (r'(\d)\s*x\s*(\d)', r'\1 × \2'),       # 3 x 4 → 3 × 4 (multiplication context)
        (r'(\d)\s*X\s*(\d)', r'\1 × \2'),         # 3 X 4 → 3 × 4
        (r'V\s*(\d+)', r'√\1'),                   # V2 → √2 (common OCR error)
        (r'(\d+)\s*/\s*(\d+)', r'\1/\2'),          # Clean up fractions: 1 / 2 → 1/2
    ]

    for pattern, replacement in ocr_fixes:
        text = re.sub(pattern, replacement, text)

    return text

import os
from PIL import Image


def extract_text_from_pdf(pdf_path):
    """
    Extract text from a PDF using PyMuPDF first.
    Falls back to OCR if text extraction yields little content.
    Preserves mathematical notation.
    """
    # Try direct text extraction with PyMuPDF
    doc = fitz.open(pdf_path)
    pages_text = []

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        # Use "text" mode which preserves Unicode math symbols
        text = page.get_text("text")
        pages_text.append(text)

    doc.close()

    # Check if we got meaningful text
    full_text = "\n".join(pages_text)
    if len(full_text.strip()) < 50:
        # Fallback to OCR
        full_text = extract_text_ocr(pdf_path)

    # Normalize math symbols
    full_text = normalize_math_text(full_text)

    return full_text


def extract_images_from_pdf(pdf_path, upload_folder):
    """
    Extract embedded images from each page of a PDF using PyMuPDF.
    Saves images to upload_folder and returns a dict mapping page_number -> [image_paths].
    Only extracts images above a minimum size to filter out icons/decorations.
    """
    page_images = {}
    doc = fitz.open(pdf_path)
    timestamp = os.path.basename(pdf_path).split('_')[0]  # reuse timestamp from filename

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        image_list = page.get_images(full=True)

        if not image_list:
            continue

        page_imgs = []
        for img_idx, img_info in enumerate(image_list):
            xref = img_info[0]
            try:
                base_image = doc.extract_image(xref)
                if not base_image:
                    continue

                image_bytes = base_image["image"]
                image_ext = base_image.get("ext", "png")
                width = base_image.get("width", 0)
                height = base_image.get("height", 0)

                # Skip tiny images (icons, bullets, decorations)
                if width < 50 or height < 50:
                    continue

                # Save the image
                img_filename = f"{timestamp}_page{page_num + 1}_img{img_idx + 1}.{image_ext}"
                img_path = os.path.join(upload_folder, img_filename)

                with open(img_path, "wb") as f:
                    f.write(image_bytes)

                # Store relative path for web serving
                relative_path = f"uploads/{img_filename}"
                page_imgs.append(relative_path)

            except Exception as e:
                print(f"Failed to extract image {img_idx} from page {page_num}: {e}")
                continue

        if page_imgs:
            page_images[page_num] = page_imgs

    doc.close()
    return page_images


def extract_text_and_images_from_pdf(pdf_path, upload_folder):
    """
    Combined extraction: text per page + images per page.
    Returns (full_text, page_texts, page_images).
    - full_text: merged text from all pages
    - page_texts: list of (page_num, text) tuples with character offsets
    - page_images: dict mapping page_num -> [relative_image_paths]
    """
    doc = fitz.open(pdf_path)
    pages_text = []
    page_boundaries = []  # (page_num, start_offset, end_offset)

    offset = 0
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        text = page.get_text("text")
        start = offset
        pages_text.append(text)
        offset += len(text) + 1  # +1 for the \n join separator
        page_boundaries.append((page_num, start, offset - 1))

    doc.close()

    full_text = "\n".join(pages_text)

    # If too little text, fall back to OCR
    if len(full_text.strip()) < 50:
        full_text = extract_text_ocr(pdf_path)
        # With OCR, we can't reliably map pages, so put everything on page 0
        page_boundaries = [(0, 0, len(full_text))]

    full_text = normalize_math_text(full_text)

    # Extract images
    page_images = extract_images_from_pdf(pdf_path, upload_folder)

    return full_text, page_boundaries, page_images


def extract_text_ocr(pdf_path):
    """Extract text from PDF using OCR (pdf2image + pytesseract)."""
    try:
        images = convert_from_path(pdf_path, dpi=300)
        full_text = []
        for img in images:
            # Use both default and math-friendly configs
            text = pytesseract.image_to_string(img, config='--psm 6 --oem 3')
            full_text.append(text)
        return "\n".join(full_text)
    except Exception as e:
        print(f"OCR extraction failed: {e}")
        return ""



def parse_questions(text):
    """
    Parse extracted text into structured questions with options.
    Supports multiple question and option formats.
    Handles questions with no options (numerical/text answer type).
    """
    questions = []

    # Normalize the text
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    # --- Strategy: Split text into question blocks ---
    # Match question patterns (more robust):
    # Q1. / Q.1 / Q1) / Q 1. / 1. / 1) / Question 1 / Question 1: / Q.No.1 etc.
    question_pattern = re.compile(
        r'(?:^|\n)\s*'
        r'(?:'
        r'(?:Q(?:uestion)?\.?\s*(?:No\.?\s*)?(\d+)\s*[).:,\-]?\s*)'  # Q1. Q.1 Q1) Question 1: Q.No.1
        r'|'
        r'(?:(\d+)\s*[.)]\s+)'  # 1. or 1) followed by space (require space to avoid matching "3/4")
        r')',
        re.IGNORECASE | re.MULTILINE
    )

    # Find all question positions
    matches = list(question_pattern.finditer(text))

    # Filter out false matches (numbers that are part of math expressions)
    filtered_matches = []
    for match in matches:
        # Get context before the match to check if it's part of math
        pre_context = text[max(0, match.start() - 5):match.start()]
        # Skip if preceded by math operators or digits (e.g., "= 3." or "/ 4)")
        if re.search(r'[=+\-×÷*/^(,]\s*$', pre_context):
            continue
        # Skip if the number is too large (unlikely to be a question number)
        q_num = match.group(1) or match.group(2)
        if q_num and int(q_num) > 500:
            continue
        filtered_matches.append(match)

    matches = filtered_matches

    if not matches:
        # Try a more lenient pattern - just numbered lines at start
        question_pattern = re.compile(
            r'(?:^|\n)\s*(\d{1,3})\s*[.):\-]\s+\S',
            re.MULTILINE
        )
        matches = list(question_pattern.finditer(text))

    if not matches:
        return questions

    # Deduplicate: if same question number appears multiple times, keep only the first
    seen_nums = set()
    deduped_matches = []
    for match in matches:
        q_num = match.group(1) or (match.group(2) if match.lastindex >= 2 else None) or '0'
        q_num = int(q_num)
        if q_num not in seen_nums:
            seen_nums.add(q_num)
            deduped_matches.append(match)
    matches = deduped_matches

    # Extract question blocks
    for i, match in enumerate(matches):
        q_num_group1 = match.group(1) if match.lastindex >= 1 and match.group(1) else None
        q_num_group2 = match.group(2) if match.lastindex >= 2 and match.group(2) else None
        q_num = int(q_num_group1 or q_num_group2 or (i + 1))

        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end].strip()

        if not block or len(block) < 3:
            continue

        # Parse the block into question text and options
        parsed = parse_question_block(block, q_num)
        if parsed:
            questions.append(parsed)

    # Re-number questions sequentially if numbers are messy
    for i, q in enumerate(questions):
        q['question_number'] = i + 1

    return questions


def parse_question_block(block, q_num):
    """
    Parse a single question block into question text and options.
    Now correctly handles:
    - Multiline questions with options on separate lines
    - Inline options on same line
    - Questions with NO options (numerical/fill-in-the-blank type)
    - Mathematical expressions within options
    """
    # Option patterns to try (ordered by specificity)
    option_patterns = [
        # (A) text / (a) text / (1) text — on their own line OR inline
        re.compile(
            r'(?:^|\n)\s*\(([A-Ea-e1-5])\)\s*(.*?)(?=(?:^|\n)\s*\([A-Ea-e1-5]\)|\Z)',
            re.DOTALL | re.MULTILINE
        ),
        # A) text / a) text — on their own line
        re.compile(
            r'(?:^|\n)\s*([A-Ea-e])\)\s*(.*?)(?=(?:^|\n)\s*[A-Ea-e]\)|\Z)',
            re.DOTALL | re.MULTILINE
        ),
        # A. text / a. text — on their own line (be careful not to match decimal numbers)
        re.compile(
            r'(?:^|\n)\s*([A-Ea-e])\.\s+(.*?)(?=(?:^|\n)\s*[A-Ea-e]\.\s|\Z)',
            re.DOTALL | re.MULTILINE
        ),
        # (i) (ii) (iii) (iv) format
        re.compile(
            r'(?:^|\n)\s*\((i{1,3}v?|iv|v)\)\s*(.*?)(?=(?:^|\n)\s*\((i{1,3}v?|iv|v)\)|\Z)',
            re.DOTALL | re.IGNORECASE | re.MULTILINE
        ),
        # A text / B text (single capital letter at start of line followed by 2+ spaces or tab)
        re.compile(
            r'(?:^|\n)\s*([A-E])(?:\s{2,}|\t)(.*?)(?=(?:^|\n)\s*[A-E](?:\s{2,}|\t)|\Z)',
            re.DOTALL | re.MULTILINE
        ),
    ]

    options = {}
    question_text = block
    option_label_map = {
        '1': 'A', '2': 'B', '3': 'C', '4': 'D', '5': 'E',
        'i': 'A', 'ii': 'B', 'iii': 'C', 'iv': 'D', 'v': 'E',
    }

    for pattern in option_patterns:
        found_options = list(pattern.finditer(block))
        if len(found_options) >= 2:  # At least 2 options to be valid
            # Extract the question text (everything before first option)
            question_text = block[:found_options[0].start()].strip()

            for opt_match in found_options:
                label = opt_match.group(1).strip()
                opt_text = opt_match.group(2).strip()

                # Clean up option text — remove trailing newlines but preserve math
                opt_text = re.sub(r'\n\s*$', '', opt_text).strip()

                # Normalize label to A/B/C/D/E
                normalized = label.upper()
                if normalized in option_label_map:
                    normalized = option_label_map[normalized]
                elif normalized.lower() in option_label_map:
                    normalized = option_label_map[normalized.lower()]

                if normalized in ['A', 'B', 'C', 'D', 'E']:
                    options[normalized] = opt_text

            break  # Use first pattern that works

    # If no multiline options found, try inline options (all on one line)
    if not options:
        # Pattern: (A) text (B) text (C) text (D) text  — all inline
        inline_pattern = re.compile(
            r'\(([A-Ea-e])\)\s*([^(]+?)(?=\([A-Ea-e]\)|$)',
            re.DOTALL
        )
        inline_matches = list(inline_pattern.finditer(block))
        if len(inline_matches) >= 2:
            question_text = block[:inline_matches[0].start()].strip()
            for opt_match in inline_matches:
                label = opt_match.group(1).upper()
                opt_text = opt_match.group(2).strip()
                if label in ['A', 'B', 'C', 'D', 'E']:
                    options[label] = opt_text

    # If still no options, try: a) text  b) text — inline with lowercase
    if not options:
        inline_lower = re.compile(
            r'([a-e])\)\s*([^a-e)]+?)(?=[a-e]\)|$)',
            re.DOTALL
        )
        inline_matches = list(inline_lower.finditer(block))
        if len(inline_matches) >= 2:
            question_text = block[:inline_matches[0].start()].strip()
            for opt_match in inline_matches:
                label = opt_match.group(1).upper()
                opt_text = opt_match.group(2).strip()
                if label in ['A', 'B', 'C', 'D', 'E']:
                    options[label] = opt_text

    # Clean up question text — preserve line breaks for readability but normalize excess whitespace
    question_text = re.sub(r'[ \t]+', ' ', question_text)  # collapse horizontal whitespace only
    question_text = re.sub(r'\n{3,}', '\n\n', question_text)  # max 2 consecutive newlines
    question_text = question_text.strip()

    if not question_text:
        return None

    # Determine if this is an MCQ or text-answer question
    has_options = bool(options)

    return {
        'question_number': q_num,
        'question_text': question_text,
        'question_type': 'mcq' if has_options else 'text',  # NEW: question type
        'option_a': options.get('A', ''),
        'option_b': options.get('B', ''),
        'option_c': options.get('C', ''),
        'option_d': options.get('D', ''),
        'option_e': options.get('E', ''),
    }


def detect_sections(text):
    """
    Try to detect section headers in the text.
    Returns a dict mapping question ranges to section names.
    """
    section_patterns = [
        re.compile(r'(?:Section|Part|SECTION|PART)\s*[-:]?\s*([A-Za-z0-9]+)\s*[-:.]?\s*(.*)', re.IGNORECASE),
        re.compile(r'(Quantitative\s*Aptitude|Data\s*Interpretation|Logical\s*Reasoning|Verbal\s*Ability|'
                   r'Reading\s*Comprehension|English\s*Language|General\s*Knowledge|'
                   r'Numerical\s*Ability|Analytical\s*Reasoning)',
                   re.IGNORECASE),
    ]

    sections = []
    for pattern in section_patterns:
        for match in pattern.finditer(text):
            sections.append({
                'position': match.start(),
                'name': match.group(0).strip(),
            })

    return sections


def assign_sections_to_questions(questions, text):
    """
    Assign section names to questions based on detected section headers.
    """
    sections = detect_sections(text)

    if not sections:
        return questions

    # Sort sections by position
    sections.sort(key=lambda s: s['position'])

    # For each question, find which section it falls under
    # This is approximate — based on text position
    for q in questions:
        q['section_name'] = sections[0]['name'] if sections else 'General'

    # More sophisticated assignment would need position mapping
    # For now, distribute evenly if multiple sections found
    if len(sections) > 1:
        questions_per_section = len(questions) // len(sections)
        if questions_per_section > 0:
            for i, q in enumerate(questions):
                section_idx = min(i // questions_per_section, len(sections) - 1)
                q['section_name'] = sections[section_idx]['name']

    return questions


def assign_images_to_questions(questions, text, page_boundaries, page_images):
    """
    Assign extracted images to questions based on which PDF page the question came from.
    Uses page_boundaries to determine the page for each question's text position,
    then looks up images from page_images dict.
    
    Args:
        questions: list of question dicts (must have 'question_text')
        text: the full extracted text
        page_boundaries: list of (page_num, start_offset, end_offset)
        page_images: dict mapping page_num -> [relative_image_paths]
    """
    if not page_images or not page_boundaries:
        return questions

    for q in questions:
        q_text = q.get('question_text', '')
        if not q_text:
            continue

        # Find where this question's text starts in the full text
        q_pos = text.find(q_text[:min(60, len(q_text))])  # match first 60 chars
        if q_pos == -1:
            continue

        # Determine which page this position falls on
        for page_num, start, end in page_boundaries:
            if start <= q_pos <= end:
                # Assign all images from this page to this question
                if page_num in page_images:
                    # Join multiple image paths with comma separator
                    q['question_image'] = ','.join(page_images[page_num])
                break

    return questions
