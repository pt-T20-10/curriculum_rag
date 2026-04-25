# test_classifier.py
"""
Unit test for classify_page() — Tầng 1 page classifier.

Tests against real URLs observed in previous crawl logs to verify
classification is correct before integrating into full pipeline.
No network calls for classification itself — fetches page text once
then runs classifier locally.

Usage:
    python test_classifier.py
"""

import sys
sys.path.insert(0, ".")

from src.config import setup_directories
setup_directories()

from src.ingestion.crawler import classify_page, fetch_text_from_url
from src.ingestion.crawler import _PAGE_EDUCATIONAL, _PAGE_NAVIGATION, _PAGE_JUNK

# ─────────────────────────────────────────────────────────────
# Test cases — URL + expected classification + content_type
# Drawn from previous crawl logs across all 4 content types
# ─────────────────────────────────────────────────────────────
TEST_CASES = [
    # ── Should be EDUCATIONAL ────────────────────────────────
    {
        "url":          "https://pmc.ncbi.nlm.nih.gov/articles/PMC7189875/",
        "content_type": "technical",
        "expected":     _PAGE_EDUCATIONAL,
        "note":         "Academic paper — machine learning survey",
    },
    {
        "url":          "https://www.geeksforgeeks.org/machine-learning/machine-learning/",
        "content_type": "technical",
        "expected":     _PAGE_EDUCATIONAL,
        "note":         "GFG ML tutorial — explanatory prose + examples",
    },
    {
        "url":          "https://iep.utm.edu/greekphi/",
        "content_type": "scholarly",
        "expected":     _PAGE_EDUCATIONAL,
        "note":         "Internet Encyclopedia of Philosophy — scholarly prose",
    },
    {
        "url":          "https://collegedunia.com/courses/machine-learning/syllabus",
        "content_type": "technical",
        "expected":     _PAGE_EDUCATIONAL,   # was wrongly skipped before fix
        "note":         "Syllabus page — should pass voting logic",
    },
    {
        "url":          "https://www.cs.tufts.edu/cs/135/2025s/index.html",
        "content_type": "technical",
        "expected":     _PAGE_EDUCATIONAL,
        "note":         "University course page — lecture notes + schedule",
    },

    # ── Should be NAVIGATION ─────────────────────────────────
    {
        "url":          "https://arxiv.org/abs/1805.05052",
        "content_type": "technical",
        "expected":     _PAGE_NAVIGATION,
        "note":         "arXiv abstract page — short, links to PDF",
    },
    {
        "url":          "https://www.cs.cmu.edu/~tom/mlbook.html",
        "content_type": "technical",
        "expected":     _PAGE_NAVIGATION,
        "note":         "Book landing page — links to chapters/PDFs",
    },

    # ── Should be JUNK ────────────────────────────────────────
    {
        "url":          "https://indaacademy.vn/machine-learning/giao-trinh-hoc-may-machine-learning-moi-nhat-hien-nay/",
        "content_type": "technical",
        "expected":     _PAGE_JUNK,
        "note":         "Promotional resource listing — 'thay vì tốn tiền'",
    },
    {
        "url":          "https://www.tailieubkhn.com/2022/02/nhap-mon-hoc-may-va-khai-pha-du-lieu.html",
        "content_type": "technical",
        "expected":     _PAGE_JUNK,
        "note":         "Course review blog — mentions teacher names, personal opinions",
    },
    {
        "url":          "https://skillfloor.com/blog/machine-learning-syllabus",
        "content_type": "technical",
        "expected":     _PAGE_NAVIGATION,   # borderline — lots of content but course marketing
        "note":         "Course marketing blog — may be nav or junk",
    },
]

# ─────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────
print("=" * 70)
print("TẦNG 1 — classify_page() Unit Test")
print("=" * 70)

passed = 0
failed = 0
errors = 0

for i, case in enumerate(TEST_CASES, 1):
    url          = case["url"]
    content_type = case["content_type"]
    expected     = case["expected"]
    note         = case["note"]

    print(f"\n[{i:02d}] {url[:60]}")
    print(f"      content_type={content_type} | expected={expected}")
    print(f"      note: {note}")

    try:
        text, _ = fetch_text_from_url(url)
        if not text:
            print(f"      ⚠️  Could not fetch page — skipping")
            errors += 1
            continue

        result = classify_page(text, url, content_type)

        # Thay đoạn failed print
        if result == expected:
            print(f"      ✓ PASS — got {result}")
            passed += 1
        else:
            # Fetch scores bằng cách gọi lại với debug
            import logging
            logging.getLogger("Crawler").setLevel(logging.DEBUG)
            result2 = classify_page(text, url, content_type)
            print(f"      ✗ FAIL — got {result}, expected {expected}")
            failed += 1

    except Exception as e:
        print(f"      ✗ ERROR — {e}")
        errors += 1

# ─────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────
total = passed + failed + errors
print("\n" + "=" * 70)
print(f"RESULT: {passed}/{total} passed | {failed} failed | {errors} errors")
if failed > 0:
    print("→ Adjust signal thresholds in classify_page() for failed cases")
print("=" * 70)