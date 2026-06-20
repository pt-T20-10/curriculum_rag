"""Command-line interface for standalone textbook generation."""

from __future__ import annotations

import json
import sys
from contextlib import redirect_stdout
from typing import Any

import click


CONTENT_LEVELS = {
    "short": "Ngắn",
    "medium": "Trung Bình",
    "long": "Dài",
    "very-long": "Rất Dài",
}


def _progress_reporter() -> Any:
    last_section: tuple[int, int] | None = None

    def report(stage: str, payload: dict[str, Any]) -> None:
        nonlocal last_section
        if stage == "validating":
            click.echo("[1/5] Đang kiểm tra query...", err=True)
        elif stage == "validation_accepted":
            click.echo("      Query hợp lệ. Đang lập cấu trúc...", err=True)
        elif stage == "workflow_node":
            node = payload.get("node")
            if node == "planner":
                click.echo("[2/5] Đã tạo cấu trúc giáo trình.", err=True)
            elif node == "ingestion":
                click.echo("[3/5] Đã thu thập dữ liệu tham khảo.", err=True)
            elif node == "query_formulator":
                section = (payload.get("chapter", 1), payload.get("subsection", 1))
                if section != last_section:
                    last_section = section
                    click.echo(
                        f"[4/5] Đang viết chương {section[0]}, mục {section[1]}...",
                        err=True,
                    )
            elif node == "publisher":
                click.echo("[5/5] Đang xuất Markdown, PDF và Word...", err=True)

    return report


def _print_human_result(result: dict[str, Any]) -> None:
    if result["status"] == "invalid_query":
        click.echo(f"Query không phù hợp: {result.get('error', '')}", err=True)
        suggestion = result.get("validation", {}).get("suggestion")
        if suggestion:
            click.echo(f"Gợi ý: {suggestion}", err=True)
        return

    if not result["success"]:
        click.echo(f"Không thể tạo giáo trình: {result.get('error', 'Lỗi không xác định')}", err=True)
        return

    stats = result["stats"]
    artifacts = result["artifacts"]
    click.echo("\nĐã tạo xong giáo trình.")
    click.echo(f"Tiêu đề: {result['title']}")
    click.echo(f"Ngôn ngữ: {result['language']}")
    click.echo(
        f"Thống kê: {stats['chapter_count']} chương, "
        f"{stats['subsection_count']} mục, {stats['word_count']} từ, "
        f"{stats['character_count']} ký tự, {stats['image_count']} hình"
    )
    click.echo(f"Thời gian: {stats['elapsed_seconds']:.2f} giây")
    click.echo("Tệp đã lưu:")
    for label, key in (("Markdown", "markdown"), ("PDF", "pdf"), ("Word", "word")):
        path = artifacts.get(key)
        if path:
            click.echo(f"  {label}: {path}")
        else:
            click.echo(f"  {label}: không tạo được", err=True)


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--query", required=True, type=str, help="Chủ đề/yêu cầu của giáo trình.")
@click.option(
    "--images/--no-images",
    default=False,
    show_default=True,
    help="Cho phép chèn hình ảnh vào giáo trình.",
)
@click.option(
    "--chapters",
    default=3,
    show_default=True,
    type=click.IntRange(2, 12),
    help="Số chương.",
)
@click.option(
    "--length",
    "length_key",
    default="medium",
    show_default=True,
    type=click.Choice(list(CONTENT_LEVELS), case_sensitive=False),
    help="Độ dài nội dung.",
)
@click.option(
    "--sections",
    default=5,
    show_default=True,
    type=click.IntRange(2, 8),
    help="Số mục tối đa trong mỗi chương.",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Xuất một JSON object trên stdout để dùng trong automation.",
)
@click.pass_context
def cli(
    ctx: click.Context,
    query: str,
    images: bool,
    chapters: int,
    length_key: str,
    sections: int,
    json_output: bool,
) -> None:
    """Tạo giáo trình tự động từ query, không cần chạy web server."""
    query = query.strip()
    if not query:
        raise click.BadParameter("không được để trống", param_hint="--query")

    try:
        # Existing agent loggers and a few legacy print statements use stdout.
        # Route them to stderr so --json always owns stdout exclusively.
        with redirect_stdout(sys.stderr):
            from app.services.textbook.automatic_runner import (
                run_automatic_textbook_workflow,
            )

            result = run_automatic_textbook_workflow(
                query=query,
                num_chapters=chapters,
                content_level=CONTENT_LEVELS[length_key.lower()],
                max_subsections_per_chapter=sections,
                enable_images=images,
                progress_callback=None if json_output else _progress_reporter(),
            )
    except KeyboardInterrupt:
        click.echo("Đã dừng theo yêu cầu người dùng.", err=True)
        ctx.exit(130)

    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False))
    else:
        _print_human_result(result)

    if result["status"] == "invalid_query":
        ctx.exit(2)
    if not result["success"]:
        ctx.exit(1)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()

