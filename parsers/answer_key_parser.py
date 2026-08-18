"""
Answer Key Parser — Extracts answer keys from PNG/JPG images using OCR.
Preprocesses images for better OCR accuracy, then uses regex to parse
question number → answer mappings.
"""

import re
import cv2
import pytesseract
import numpy as np
from PIL import Image


def extract_answer_key(image_path):
    """
    Extract answer key from an image file using OCR.
    Returns a dict mapping question numbers to correct answers.
    """
    # Load and preprocess the image
    image = cv2.imread(image_path)

    if image is None:
        raise ValueError(f"Could not load image: {image_path}")

    # Preprocessing pipeline
    processed = preprocess_image(image)

    # OCR extraction with multiple PSM modes for best results
    text = ""
    for psm in [6, 4, 3]:
        config = f'--psm {psm} --oem 3'
        extracted = pytesseract.image_to_string(processed, config=config)
        if len(extracted.strip()) > len(text.strip()):
            text = extracted

    # Parse the OCR text into answer key dict
    answer_key = parse_answer_key_text(text)

    return answer_key, text  # Return both parsed dict and raw text for preview


def preprocess_image(image):
    """
    Preprocess image for better OCR accuracy.
    """
    # Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Resize if too small (Tesseract works best with 300+ DPI equivalent)
    height, width = gray.shape
    if width < 1000:
        scale = 1000 / width
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    # Apply adaptive thresholding
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 11, 2
    )

    # Noise removal using morphological opening
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    cleaned = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

    # Dilation to make text bolder
    kernel_dilate = np.ones((1, 1), np.uint8)
    dilated = cv2.dilate(cleaned, kernel_dilate, iterations=1)

    return dilated


def parse_answer_key_text(text):
    """
    Parse OCR text into a question_number → answer mapping.
    Supports various formats:
        1-A, 1.A, 1) A, 1: A, 1 A, Q1: A, etc.
        Also handles tabular formats with multiple entries per line.
    """
    answer_key = {}

    # Normalize text
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    # Patterns to match (ordered by specificity)
    patterns = [
        # Q1-A, Q1. 42, Q1: 3/4, Q1) text patterns
        # Group 1: question number, Group 2: the answer (which can be a letter A-E or a number/fraction/word)
        re.compile(r'(?:Q|Q\.|Question)?\s*(\d+)\s*[).:=\-–—]\s*([A-Ea-e](?!\w)|[A-Za-z0-9/.\-]+)', re.IGNORECASE),
        # 1. A or 1. 42 patterns (no Q prefix)
        re.compile(r'(?:^|\s)(\d+)\s*[).:=\-–—]\s*([A-Ea-e](?!\w)|[A-Za-z0-9/.\-]+)', re.IGNORECASE),
        # Patterns with "Ans" keyword: 1. Ans: A
        re.compile(r'(\d+)\s*[).:=\-–—]?\s*(?:Ans(?:wer)?)\s*[).:=\-–—]?\s*([A-Ea-e](?!\w)|[A-Za-z0-9/.\-]+)', re.IGNORECASE),
    ]

    # Because numerical answers could be mistakenly parsed from random text,
    # we first look for the most explicit "Ans:" pattern.
    
    for pattern in reversed(patterns): # Start with the "Ans:" pattern, then try less specific
        matches = pattern.findall(text)
        if matches:
            for q_num_str, answer in matches:
                q_num = int(q_num_str)
                ans = answer.strip()
                # If it's a single letter, capitalize it. Otherwise leave as is.
                if len(ans) == 1 and ans.isalpha():
                    ans = ans.upper()
                answer_key[q_num] = ans

            if len(answer_key) >= 2:  # Found at least 2 answers, good enough
                break

    return answer_key


def validate_answer_key(answer_key, total_questions):
    """
    Validate the answer key against expected number of questions.
    Returns warnings for missing or extra entries.
    """
    warnings = []

    if not answer_key:
        warnings.append("No answers could be extracted from the image. Please check the image quality.")
        return warnings

    expected = set(range(1, total_questions + 1))
    found = set(answer_key.keys())

    missing = expected - found
    extra = found - expected

    if missing:
        warnings.append(f"Missing answers for questions: {sorted(missing)}")
    if extra:
        warnings.append(f"Extra answers found for questions not in the test: {sorted(extra)}")

    return warnings
