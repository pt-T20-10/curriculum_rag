from __future__ import annotations

from pathlib import Path

from app.ingestion.uploaded_sources import (
    clean_source_text_for_embedding,
    detect_source_language,
    format_apa_numbered_references,
    infer_apa_metadata_from_text,
    merge_source_materials,
    user_source_language_profile,
    url_source_manifest,
)
from app.ingestion import uploaded_sources
from app.services.textbook.publisher import prepare_markdown_for_standalone_export


def test_url_source_manifest_formats_apa_numbered_reference() -> None:
    [entry] = url_source_manifest(["https://www.wireshark.org/docs/wsug_html_chunked/"])
    entry["status"] = "embedded"
    entry["apa"]["author"] = "Wireshark Foundation"
    entry["apa"]["year"] = "2023"
    entry["apa"]["title"] = "Wireshark User Guide"

    refs = format_apa_numbered_references([entry], language="vi")

    assert refs == [
        "[1] Wireshark Foundation. (2023). Wireshark User Guide. Wireshark. "
        "https://www.wireshark.org/docs/wsug_html_chunked/"
    ]


def test_reference_formatter_skips_failed_user_sources() -> None:
    ready, failed = url_source_manifest([
        "https://example.edu/ready",
        "https://example.edu/failed",
    ])
    ready["status"] = "embedded"
    failed["status"] = "failed"

    refs = format_apa_numbered_references([ready, failed], language="en")

    assert len(refs) == 1
    assert refs[0].startswith("[1] Example.")


def test_merge_source_materials_deduplicates_by_url_or_path() -> None:
    existing = [{"id": "a", "kind": "user_url", "url": "https://example.edu/a"}]
    additions = [
        {"id": "b", "kind": "user_url", "url": "https://example.edu/a"},
        {"id": "c", "kind": "user_file", "stored_path": "D:/tmp/source.pdf"},
    ]

    merged = merge_source_materials(existing, additions)

    assert [item["id"] for item in merged] == ["a", "c"]


def test_user_source_language_profile_prefers_vietnamese_uploaded_sources() -> None:
    assert detect_source_language("Giáo trình xử lý ảnh số và các phép lọc ảnh") == "vi"

    profile = user_source_language_profile([
        {"kind": "user_file", "language": "vi"},
        {"kind": "user_file", "language": "vi"},
        {"kind": "user_url", "url": "https://example.edu/source"},
    ])

    assert profile["preference"] == "vi"
    assert profile["language_counts"]["vi"] == 2
    assert profile["user_file_count"] == 2


def test_uploaded_file_reference_uses_cover_metadata_without_generic_note() -> None:
    apa = infer_apa_metadata_from_text(
        "\n".join([
            "BỘ LAO ĐỘNG - THƯƠNG BINH VÀ XÃ HỘI",
            "TRƯỜNG CAO ĐẲNG KỸ THUẬT CÔNG NGHỆ",
            "GIÁO TRÌNH",
            "KỸ THUẬT ĐIỆN",
            "NGHỀ: ĐIỆN CÔNG NGHIỆP",
            "Chủ biên: Nguyễn Văn A",
            "Hà Nội, 2021",
        ]),
        filename="GT-MH12-KTD-CD.pdf",
        base={"title": "GT-MH12-KTD-CD"},
    )

    refs = format_apa_numbered_references([
        {
            "kind": "user_file",
            "status": "embedded",
            "filename": "GT-MH12-KTD-CD.pdf",
            "apa": apa,
        }
    ], language="vi")

    assert "GT-MH12-KTD-CD" not in refs[0]
    assert "Tài liệu do người dùng cung cấp" not in refs[0]
    assert "Nguyễn Văn A. (2021). Giáo trình kỹ thuật điện." in refs[0]


def test_pdf_core_author_is_not_used_when_content_has_collective_author() -> None:
    apa = infer_apa_metadata_from_text(
        "\n".join([
            "TRƯỜNG CAO ĐẲNG ĐIỆN LỰC MIỀN BẮC",
            "GIÁO TRÌNH",
            "KỸ THUẬT ĐIỆN",
            "LỜI NÓI ĐẦU",
            "Nội dung gồm 3 chương:",
            "Tập thể giảng viên",
            "TỔ MÔN KỸ THUẬT CƠ SỞ - KHOA ĐIỆN",
            "Hà Nội, 2020",
        ]),
        filename="GT-MH12-KTD-CD.pdf",
        base={"title": "GT-MH12-KTD-CD", "author": "Minh Thu"},
    )

    refs = format_apa_numbered_references([
        {"kind": "user_file", "status": "embedded", "filename": "GT-MH12-KTD-CD.pdf", "apa": apa}
    ], language="vi")

    assert "Minh Thu" not in refs[0]
    assert refs[0].startswith("[1] Tập thể giảng viên")
    assert "Giáo trình kỹ thuật điện" in refs[0]


def test_multiline_bien_soan_authors_are_collected_and_normalized() -> None:
    apa = infer_apa_metadata_from_text(
        "\n".join([
            "TRƯỜNG ĐẠI HỌC SƯ PHẠM KỸ THUẬT TP. HCM",
            "KHOA ĐIỆN",
            "GIÁO TRÌNH",
            "KỸ THUẬT ĐIỆN",
            "BIÊN SOẠN: ThS. NGUYỄN TRỌNG THẮNG",
            "ThS. LÊ THỊ THANH HOÀNG",
            "TP. Hồ Chí Minh, 2008",
        ]),
        filename="kythuatdien_939.pdf",
        base={"title": "kythuatdien_939"},
    )

    assert apa["author"] == "Nguyễn Trọng Thắng, Lê Thị Thanh Hoàng"
    assert apa["year"] == "2008"


def test_mojibake_author_is_suppressed_with_review_warning() -> None:
    apa = infer_apa_metadata_from_text(
        "\n".join([
            "TRƯỜNG ĐẠI HỌC SƯ PHẠM KỸ THUẬT TP. HCM",
            "GIÁO TRÌNH",
            "KỸ THUẬT ĐIỆN",
            "BIÊN SOẠN: ThS. NGUYEÃN TROÏNG THAÉNG",
            "TP. Hồ Chí Minh, 2008",
        ]),
        filename="kythuatdien_939.pdf",
        base={"title": "kythuatdien_939"},
    )

    refs = format_apa_numbered_references([
        {"kind": "user_file", "status": "embedded", "filename": "kythuatdien_939.pdf", "apa": apa}
    ], language="vi")

    assert "NGUYEÃN" not in refs[0]
    assert apa["needs_review"] is True
    assert any("lỗi font" in warning for warning in apa["warnings"])


def test_ptit_lecture_cover_extracts_author_title_year_and_publisher() -> None:
    apa = infer_apa_metadata_from_text(
        "\n".join([
            "BỘ THÔNG TIN VÀ TRUYỀN THÔNG",
            "HỌC VIỆN CÔNG NGHỆ BƯU CHÍNH VIỄN THÔNG",
            "PTIT",
            "NGUYỄN VĂN HẬU- NGUYỄN THỊ VIỆT LÊ",
            "BÀI GIẢNG",
            "KẾ TOÁN CÔNG",
            "Tháng 12/2018",
        ]),
        filename="ke-toan-cong.pdf",
        base={"title": "ke-toan-cong"},
    )

    refs = format_apa_numbered_references([
        {"kind": "user_file", "status": "embedded", "filename": "ke-toan-cong.pdf", "apa": apa}
    ], language="vi")

    assert apa["author"] == "Nguyễn Văn Hậu, Nguyễn Thị Việt Lê"
    assert apa["title"] == "Bài giảng kế toán công"
    assert apa["year"] == "2018"
    assert apa["publisher"] == "HỌC VIỆN CÔNG NGHỆ BƯU CHÍNH VIỄN THÔNG"
    assert refs[0].startswith("[1] Nguyễn Văn Hậu, Nguyễn Thị Việt Lê. (2018). Bài giảng kế toán công.")


def test_ptit_lecture_cover_keeps_roman_title_and_strips_academic_titles() -> None:
    apa = infer_apa_metadata_from_text(
        "\n".join([
            "BỘ THÔNG TIN VÀ TRUYỀN THÔNG",
            "HỌC VIỆN CÔNG NGHỆ BƯU CHÍNH VIỄN THÔNG",
            "ĐINH XUÂN DŨNG",
            "BÀI GIẢNG",
            "KẾ TOÁN TÀI CHÍNH III",
            "Tháng 12/2018",
        ]),
        filename="kt-tai-chinh-iii.pdf",
        base={"title": "kt-tai-chinh-iii"},
    )

    assert apa["author"] == "Đinh Xuân Dũng"
    assert apa["title"] == "Bài giảng kế toán tài chính III"
    assert apa["year"] == "2018"

    edited = infer_apa_metadata_from_text(
        "\n".join([
            "HỌC VIỆN CÔNG NGHỆ BƯU CHÍNH VIỄN THÔNG",
            "TS. VŨ QUANG KẾT",
            "(Hiệu chỉnh)",
            "BÀI GIẢNG",
            "KẾ TOÁN QUẢN TRỊ 2",
            "HÀ NỘI 12-2019",
        ]),
        filename="ke-toan-quan-tri-2.pdf",
        base={"title": "ke-toan-quan-tri-2"},
    )

    assert edited["author"] == "Vũ Quang Kết"
    assert edited["title"] == "Bài giảng kế toán quản trị 2"
    assert edited["year"] == "2019"


def test_preface_group_authors_are_collected_when_cover_has_no_author() -> None:
    apa = infer_apa_metadata_from_text(
        "\n".join([
            "HỌC VIỆN CÔNG NGHỆ BƯU CHÍNH VIỄN THÔNG",
            "BÀI GIẢNG",
            "KIỂM TOÁN TÀI CHÍNH",
            "(3 tín chỉ)",
            "Hà nội, tháng 12 năm 2018",
            "MỞ ĐẦU",
            "Bài giảng kiểm toán tài chính gồm 10 chương được biên soạn bởi nhóm tác giả:",
            "TS. Lê Thị Ngọc Phương",
            "Chương 1: Tổng quan về kiểm toán tài chính",
            "Chương 2: Quy trình kiểm toán tài chính",
            "Ths. Nguyễn Thị Chinh Lam",
            "Chương 5: Kiểm toán chu trình tài sản cố định và đầu tư dài hạn",
            "Trong quá trình soạn thảo không tránh khỏi những sai sót.",
        ]),
        filename="kiem-toan-tai-chinh.pdf",
        base={"title": "kiem-toan-tai-chinh"},
    )

    assert apa["author"] == "Lê Thị Ngọc Phương, Nguyễn Thị Chinh Lam"
    assert apa["title"] == "Bài giảng kiểm toán tài chính"
    assert apa["year"] == "2018"
    assert apa["needs_review"] is False


def test_preface_publication_year_beats_regulation_years() -> None:
    apa = infer_apa_metadata_from_text(
        "\n".join([
            "MỞ ĐẦU",
            "Bài giảng Kế toán công được biên soạn theo Quyết định số 485/QĐ-HV ngày 17 tháng 5 năm 2016.",
            "Nội dung sử dụng hệ thống tài khoản theo Thông tư số 107/2017/TT-BTC.",
            "Bài giảng được biên soạn bởi TS. Nguyễn Văn Hậu; TS. Nguyễn Thị Việt Lê.",
            "Hà Nội, tháng 12 năm 2018",
            "TẬP THỂ TÁC GIẢ",
        ]),
        filename="ke-toan-cong.pdf",
        base={"title": "ke-toan-cong"},
    )

    assert apa["title"] == "Bài giảng kế toán công"
    assert apa["year"] == "2018"
    assert apa["author"] == "Nguyễn Văn Hậu, Nguyễn Thị Việt Lê"


def test_english_network_forensics_metadata_from_loc_and_copyright() -> None:
    apa = infer_apa_metadata_from_text(
        "\n".join([
            "Network Forensics",
            "Tracking Hackers through Cyberspace",
            "Sherri Davidoff",
            "Jonathan Ham",
            "Upper Saddle River, NJ • Boston • Indianapolis • San Francisco",
            "Library of Congress Cataloging-in-Publication Data",
            "Davidoff, Sherri.",
            "Network forensics : tracking hackers through cyberspace / Sherri Davidoff, Jonathan Ham.",
            "ISBN 0-13-256471-8",
            "Copyright © 2012 Pearson Education, Inc.",
        ]),
        filename="Network Forensics - Tracking Hackers Through Cyberspace.pdf",
        base={"title": "Network Forensics - Tracking Hackers Through Cyberspace"},
    )

    refs = format_apa_numbered_references([
        {"kind": "user_file", "status": "embedded", "filename": "network.pdf", "apa": apa}
    ], language="en")

    assert apa["title"] == "Network Forensics: Tracking Hackers through Cyberspace"
    assert apa["author"] == "Sherri Davidoff, Jonathan Ham"
    assert apa["year"] == "2012"
    assert apa["publisher"] == "Pearson"
    assert refs[0] == (
        "[1] Sherri Davidoff, Jonathan Ham. (2012). "
        "Network Forensics: Tracking Hackers through Cyberspace. Pearson."
    )


def test_english_practical_packet_analysis_metadata_from_title_page() -> None:
    apa = infer_apa_metadata_from_text(
        "\n".join([
            "PRACTICAL PACKET ANALYSIS",
            "Using Wireshark to Solve",
            "Real-World Network",
            "Problems",
            "by Chris Sanders",
            "San Francisco",
            "PRACTICAL PACKET ANALYSIS. Copyright © 2007 by Chris Sanders.",
            "No Starch Press, Inc.",
            "Library of Congress Cataloging-in-Publication Data",
            "Sanders, Chris, 1986-",
            "Practical packet analysis : using Wireshark to solve real-world network problems / Chris Sanders.",
        ]),
        filename="No Starch Press - Practical Packet Analysis.pdf",
        base={"title": "No Starch Press - Practical Packet Analysis"},
    )

    refs = format_apa_numbered_references([
        {"kind": "user_file", "status": "embedded", "filename": "packet.pdf", "apa": apa}
    ], language="en")

    assert apa["title"] == "Practical Packet Analysis: Using Wireshark to Solve Real-World Network Problems"
    assert apa["author"] == "Chris Sanders"
    assert apa["year"] == "2007"
    assert apa["publisher"] == "No Starch Press"
    assert refs[0].startswith(
        "[1] Chris Sanders. (2007). Practical Packet Analysis: Using Wireshark"
    )


def test_english_book_edition_is_included_when_present() -> None:
    apa = infer_apa_metadata_from_text(
        "\n".join([
            "Practical Packet Analysis",
            "Fourth Edition",
            "Practical packet analysis : using Wireshark to solve real-world network problems / Chris Sanders.",
            "Copyright © 2023 by Chris Sanders.",
            "No Starch Press, Inc.",
        ]),
        filename="packet-4e.pdf",
        base={"title": "packet-4e"},
    )

    refs = format_apa_numbered_references([
        {"kind": "user_file", "status": "embedded", "filename": "packet-4e.pdf", "apa": apa}
    ], language="en")

    assert apa["edition"] == "4th ed."
    assert "Practical Packet Analysis: Using Wireshark to Solve Real-World Network Problems (4th ed.)." in refs[0]


def test_uploaded_source_text_debug_log_writes_metadata_and_text(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "uploaded_source_text.log"
    monkeypatch.setattr(uploaded_sources, "UPLOADED_SOURCE_TEXT_LOG", log_path)
    monkeypatch.setattr(uploaded_sources, "UPLOADED_SOURCE_TEXT_LOG_MAX_CHARS", 80)

    uploaded_sources._log_uploaded_source_text(
        {
            "id": "src123",
            "filename": "ke-toan-cong.pdf",
            "type": "pdf",
            "language": "vi",
            "apa": {
                "title": "Bài giảng kế toán công",
                "author": "Nguyễn Văn Hậu",
                "year": "2018",
                "publisher": "HỌC VIỆN CÔNG NGHỆ BƯU CHÍNH VIỄN THÔNG",
            },
        },
        "MỞ ĐẦU\n" + ("Nội dung đã extract. " * 20),
        page=2,
    )

    logged = Path(log_path).read_text(encoding="utf-8")

    assert "[UPLOADED SOURCE TEXT]" in logged
    assert '"filename": "ke-toan-cong.pdf"' in logged
    assert '"page": 2' in logged
    assert "Bài giảng kế toán công" in logged
    assert "MỞ ĐẦU" in logged
    assert "[TRUNCATED:" in logged


def test_source_text_embedding_cleanup_removes_front_matter_and_references() -> None:
    text = "\n".join([
        "BỘ THÔNG TIN VÀ TRUYỀN THÔNG",
        "BÀI GIẢNG",
        "KẾ TOÁN CÔNG",
        "MỞ ĐẦU",
        "Phần mở đầu chỉ dùng để nhận dạng metadata, không dùng làm RAG context.",
        "MỤC LỤC",
        "Chương 1 Tổng quan ................................ 5",
        "Chương 2 Nội dung ................................ 20",
        "Chương 1 Tổng quan về kế toán công",
        "Đây là đoạn nội dung chương có đủ ý nghĩa để đưa vào embedding.",
        "Nội dung này giải thích khái niệm, nguyên tắc và cách áp dụng trong đơn vị.",
        "TÀI LIỆU THAM KHẢO",
        "[1] Một tài liệu tham khảo. (2020). Nhà xuất bản.",
    ])

    cleaned, stats = clean_source_text_for_embedding(text)

    assert "MỞ ĐẦU" not in cleaned
    assert "MỤC LỤC" not in cleaned
    assert "Phần mở đầu chỉ dùng" not in cleaned
    assert cleaned.startswith("Chương 1 Tổng quan về kế toán công")
    assert "TÀI LIỆU THAM KHẢO" not in cleaned
    assert "[1] Một tài liệu" not in cleaned
    assert stats["removed_chars"] > 0


def test_source_text_embedding_cleanup_preserves_standalone_chapter_heading() -> None:
    text = "\n".join([
        "Network Forensics",
        "Preface",
        "This front matter is useful for citation metadata only.",
        "Contents",
        "Chapter 1, Practical Investigative Strategies, presents core techniques.",
        "Chapter 2, Technical Fundamentals, provides the background.",
        "Chapter 1",
        "Practical Investigative Strategies",
        "Evidence scattered around the world. Not enough time. Not enough staff.",
        "This is the actual chapter body and should be embedded.",
        "References",
        "Oxford Dictionaries Online.",
    ])

    cleaned, stats = clean_source_text_for_embedding(text)

    assert cleaned.startswith("Chapter 1\nPractical Investigative Strategies")
    assert "Preface" not in cleaned
    assert "Contents" not in cleaned
    assert "presents core techniques" not in cleaned
    assert "Oxford Dictionaries" not in cleaned
    assert stats["removed_chars"] > 0


def test_source_text_embedding_cleanup_keeps_text_without_content_marker() -> None:
    text = (
        "Báo cáo chuyên đề không có heading chương rõ ràng.\n"
        "Nội dung vẫn có các đoạn phân tích dài và không nên bị xóa nhầm."
    )

    cleaned, stats = clean_source_text_for_embedding(text)

    assert cleaned == text
    assert stats["removed_chars"] == 0


def test_exercise_labels_and_formulas_are_exported_as_blocks() -> None:
    markdown = (
        "### 2.3.3 Bài tập thực hành\n"
        "Để rèn luyện: **Bài tập 1:** Một mạch điện. Hãy xác định:\n"
        "a) Biên độ dòng điện.\n"
        "**Hướng dẫn giải:** a) Biên độ dòng điện:\n"
        "I_{max} = \\frac{U_{max}}{R} = 2\\sqrt{2}\n"
        "**Bài tập 2:** Cho mạch điện khác."
    )

    prepared = prepare_markdown_for_standalone_export(
        markdown,
        language="vi",
        enable_images=False,
    )

    assert "\n\n**Bài tập 1:**\n\nMột mạch điện" in prepared
    assert "\n\n**Hướng dẫn giải:**\n\n" in prepared
    assert "\n\n$$\nI_{max} = \\frac{U_{max}}{R} = 2\\sqrt{2}\n$$\n\n" in prepared


def test_glued_subquestions_orphan_math_and_tables_are_repaired() -> None:
    markdown = (
        "Bảng so sánh nhanh:\n"
        "| Đặc tính | Nhánh thuần trở | Nhánh thuần cảm |\n"
        "|---|---|---|\n"
        "| Đại lượng quyết định | $R$|$L$ |\n"
        "Theo định luật cảm ứng:\n"
        "u(t) = L \\frac{di(t)}{dt}\n"
        "$$\n"
        "Trong đó:\n"
        "- $L$: điện cảm\n"
        "**Hướng dẫn giải:**\n"
        "- a) Tính $I$:\n"
        "  - $I = \\frac{U}{\\omega L} \\approx 3{,}5\\,\\mathrm{A}$- b)$I_m = I \\sqrt{2} \\approx 3{,}5 \\times 1{,}414} \\approx 4{,}95\\,\\mathrm{A}$\n"
        "- c) Công suất tiêu thụ thực:\n"
        "  - $P = 0$.\n"
    )

    prepared = prepare_markdown_for_standalone_export(
        markdown,
        language="vi",
        enable_images=False,
    )

    assert "Bảng so sánh nhanh:\n\n| Đặc tính" in prepared
    assert "| Đại lượng quyết định | $R$|$L$ |\n\nTheo định luật" in prepared
    assert "u(t) = L \\frac{di(t)}{dt}" in prepared
    assert "Trong đó:" in prepared
    assert "\na)" in prepared
    assert "Tính $I$:" in prepared
    assert "$- b)" not in prepared
    assert "\n\nb)\n$$\nI_m = I \\sqrt{2}" in prepared
    assert "1{,}414}" not in prepared
    assert "\n\nc) Công suất tiêu thụ thực:" in prepared
