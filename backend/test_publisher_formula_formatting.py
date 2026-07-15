from app.services.textbook.publisher import (
    fix_inline_display_math,
    normalize_formula_explanations,
    promote_standalone_inline_math,
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
