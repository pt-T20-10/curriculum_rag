from app.services.textbook.publisher import (
    fix_inline_display_math,
    lint_math_export_risks,
    normalize_display_math_blocks,
    normalize_formula_explanations,
    normalize_math_identifier_formatting,
    normalize_lead_in_labels,
    normalize_list_lead_in_labels,
    promote_standalone_inline_math,
    repair_mixed_math_markdown_blocks,
    wrap_bare_formula_lines,
)


def test_normalize_formula_explanations_splits_inline_trong_do_items():
    content = (
        "Trong đó: - `C_{total}` là tổng chi phí vòng đời, "
        "- `C_{dev}` là chi phí phát triển ban đầu."
    )

    normalized = normalize_formula_explanations(content)

    assert normalized == (
        "Trong đó:\n"
        "- $C_{total}$: tổng chi phí vòng đời\n"
        "- $C_{dev}$: chi phí phát triển ban đầu."
    )


def test_normalize_formula_explanations_splits_collapsed_definition_bullets():
    content = (
        "Trong đó:\n"
        "- $Q$ là chất lượng phần mềm, -$C$ là mức độ đáp ứng yêu cầu, "
        "- $E$ là hiệu quả sử dụng tài nguyên."
    )

    normalized = normalize_formula_explanations(content)

    assert normalized == (
        "Trong đó:\n"
        "- $Q$: chất lượng phần mềm\n"
        "- $C$: mức độ đáp ứng yêu cầu\n"
        "- $E$: hiệu quả sử dụng tài nguyên."
    )


def test_normalize_formula_explanations_repairs_glued_inline_math():
    content = "Trong đó $t_i$là thời gian phản hồi ở lần thứ$i$, $n$ là số lần kiểm thử."

    normalized = normalize_formula_explanations(content)

    assert normalized == (
        "Trong đó:\n"
        "- $t_i$: thời gian phản hồi ở lần thứ $i$\n"
        "- $n$: số lần kiểm thử."
    )


def test_promote_standalone_inline_math_keeps_equations_as_display_blocks():
    content = (
        "Tổng thời gian phát triển là:\n"
        "$T_{dev} = N_{sprint} \\times T_{sprint}$\n"
        "Sau đó nhóm điều chỉnh theo tiến độ."
    )

    normalized = promote_standalone_inline_math(content)

    assert normalized == (
        "Tổng thời gian phát triển là:\n"
        "$$\n"
        "T_{dev} = N_{sprint} \\times T_{sprint}\n"
        "$$\n"
        "Sau đó nhóm điều chỉnh theo tiến độ."
    )


def test_normalize_formula_explanations_converts_formula_context_backticks_only():
    content = (
        "Công thức tổng quát dùng `T_{dev}` trong phần này.\n"
        "Ví dụ module `BookManager` vẫn là định danh lập trình."
    )

    normalized = normalize_formula_explanations(content)

    assert "$T_{dev}$" in normalized
    assert "`BookManager`" in normalized


def test_normalize_formula_explanations_converts_indexed_formula_symbols():
    content = (
        "Trong đó:\n"
        "- `f_q[x, y]`: giá trị ảnh sau lượng tử hóa\n"
        "- `g[x, y]`: giá trị điểm ảnh sau khi lọc\n"
        "- `h[k, l]`: hệ số của mặt nạ lọc\n"
        "- `student_scores[\"Alice\"]`: ví dụ code không phải công thức"
    )

    normalized = normalize_formula_explanations(content)

    assert "- $f_q[x, y]$: giá trị ảnh sau lượng tử hóa" in normalized
    assert "- $g[x, y]$: giá trị điểm ảnh sau khi lọc" in normalized
    assert "- $h[k, l]$: hệ số của mặt nạ lọc" in normalized
    assert '`student_scores["Alice"]`' in normalized


def test_fix_inline_display_math_does_not_inline_short_equations():
    content = "$$\nT = N \\times S\n$$\n\n$$\nx\n$$"

    normalized = fix_inline_display_math(content)

    assert "$$\nT = N \\times S\n$$" in normalized
    assert "$x$" in normalized


def test_normalize_display_math_repairs_closing_delimiter_same_line():
    content = "$$\nI'(x, y) = \\mu + \\frac{\\sigma^2 - v^2}{\\sigma^2} [I(x, y) - \\mu]$$"

    normalized = normalize_display_math_blocks(content)
    normalized = normalize_math_identifier_formatting(normalized)

    assert normalized == (
        "$$\n"
        "I'(x, y) = \\mu + \\frac{\\sigma^2 - v^2}{\\sigma^2} [I(x, y) - \\mu]\n"
        "$$"
    )


def test_normalize_display_math_wraps_plain_multiline_equations_in_aligned():
    content = "$$\nY = 0.299R + 0.587G + 0.114B \\\\\nCb = 0.564(B - Y) \\\\\nCr = 0.713(R - Y)\n$$"

    normalized = normalize_display_math_blocks(content)

    assert "\\begin{aligned}" in normalized
    assert "Y = 0.299R + 0.587G + 0.114B \\\\" in normalized
    assert "\\end{aligned}" in normalized


def test_normalize_display_math_does_not_wrap_cases_or_matrices():
    content = (
        "$$\n"
        "\\begin{cases}\n"
        "1, & x > 0 \\\\\n"
        "0, & x \\leq 0\n"
        "\\end{cases}\n"
        "$$\n\n"
        "$$\n"
        "\\begin{bmatrix}\n"
        "1 & 0 \\\\\n"
        "0 & 1\n"
        "\\end{bmatrix}\n"
        "$$"
    )

    normalized = normalize_display_math_blocks(content)

    assert normalized.count("\\begin{aligned}") == 0
    assert "\\begin{cases}" in normalized
    assert "\\begin{bmatrix}" in normalized


def test_normalize_lead_in_labels_splits_hard_break_paragraphs():
    content = "**Bài tập thực hành:**  \nChọn một ảnh số bất kỳ và thực hiện các bước."

    normalized = normalize_lead_in_labels(content)

    assert normalized == (
        "**Bài tập thực hành:**\n\n"
        "Chọn một ảnh số bất kỳ và thực hiện các bước."
    )


def test_repair_mixed_math_markdown_blocks_splits_swallowed_list_steps():
    content = (
        "1. Tổng quang thông cần thiết:\n"
        "$$\n"
        "\\Phi_{total} = 300~lux \\times 40~m^2 = 12,000~lm\n\n"
        "2. Quang thông của một đèn:\n"
        "\\Phi_{den} = 20~W \\times 100~lm/W = 2,000~lm\n\n"
        "3. Số lượng đèn:\n"
        "N = \\frac{12,000~lm}{2,000~lm} = 6~đèn\n"
        "$$"
    )

    repaired = repair_mixed_math_markdown_blocks(content)

    assert repaired.count("$$") == 6
    assert "2. Quang thông của một đèn:" in repaired
    assert "$$\n\\Phi_{den} = 20~W \\times 100~lm/W = 2,000~lm\n$$" in repaired
    assert "$$\nN = \\frac{12,000~lm}{2,000~lm} = 6~đèn\n$$" in repaired


def test_wrap_bare_formula_lines_wraps_strong_formula_only():
    content = (
        "Quang thông của một đèn:\n"
        "\\Phi_{den} = 20~W \\times 100~lm/W = 2,000~lm\n"
        "Đây là một dòng văn xuôi bình thường."
    )

    wrapped = wrap_bare_formula_lines(content)

    assert "$$\n\\Phi_{den} = 20~W \\times 100~lm/W = 2,000~lm\n$$" in wrapped
    assert "Đây là một dòng văn xuôi bình thường." in wrapped


def test_lint_math_export_risks_repairs_double_equals_in_formula():
    content = "$$\nI_{tong} = = \\frac{P}{U}\n$$"

    linted = lint_math_export_risks(content)

    assert "I_{tong} = \\frac{P}{U}" in linted
    assert "= =" not in linted


def test_normalize_list_lead_in_labels_keeps_numbered_bold_label_inline():
    content = "3. **Áp dụng các định luật Kirchhoff trong miền phức:** Các định luật được áp dụng trực tiếp."

    normalized = normalize_list_lead_in_labels(content)

    assert normalized == content


def test_normalize_list_lead_in_labels_merges_detached_formula_items():
    content = (
        "Trong đó:\n\n"
        "- $A$:\n\n"
        "  ma trận biểu diễn ảnh gốc\n\n"
        "- $G_x$, $G_y$:\n\n"
        "  ảnh gradient theo phương ngang và dọc"
    )

    normalized = normalize_list_lead_in_labels(content)

    assert normalized == (
        "Trong đó:\n\n"
        "- $A$: ma trận biểu diễn ảnh gốc\n"
        "- $G_x$, $G_y$: ảnh gradient theo phương ngang và dọc"
    )


def test_normalize_list_lead_in_labels_merges_detached_prose_labels():
    content = (
        "Ví dụ minh họa:\n\n"
        "Tại vị trí $(x, y)$, giá trị điểm ảnh được tính theo công thức trên.\n\n"
        "Một số hệ màu phổ biến:\n\n"
        "- **RGB (Red, Green, Blue):**\n\n"
        "  Hệ màu gốc cho hầu hết các thiết bị hiển thị.\n"
        "- **HSV (Hue, Saturation, Value):** hệ màu dựa trên cảm nhận thị giác."
    )

    normalized = normalize_list_lead_in_labels(content)

    assert "Ví dụ minh họa: Tại vị trí $(x, y)$" in normalized
    assert "Một số hệ màu phổ biến:\n\n- **RGB" in normalized
    assert "- **RGB (Red, Green, Blue):** Hệ màu gốc" in normalized
    assert "- **HSV (Hue, Saturation, Value):** hệ màu dựa" in normalized
