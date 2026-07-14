from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.textbook import publisher  # noqa: E402
from app.services.textbook.language import get_language_profile  # noqa: E402


def _extract_title(markdown: str, fallback: str) -> str:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", markdown, flags=re.DOTALL)
    if not match:
        return fallback
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() in {"title", "title-meta"}:
            return value.strip().strip('"').strip("'") or fallback
    return fallback


def _warn_em_dash_lines(markdown: str, source: Path) -> None:
    hits = [
        (i, line.strip())
        for i, line in enumerate(markdown.splitlines(), start=1)
        if "—" in line
    ]
    if not hits:
        return

    print(
        f"WARNING: {source} contains {len(hits)} line(s) with em dash (—). "
        "This CLI does not rewrite old prose; regenerate/review content to clean it.",
        file=sys.stderr,
    )
    for line_no, line in hits[:20]:
        preview = line[:180] + ("..." if len(line) > 180 else "")
        print(f"  line {line_no}: {preview}", file=sys.stderr)
    if len(hits) > 20:
        print(f"  ... {len(hits) - 20} more line(s)", file=sys.stderr)


def _unique_output_path(output_dir: Path, stem: str) -> Path:
    candidate = output_dir / f"{stem}_preview.docx"
    if not candidate.exists():
        return candidate
    for i in range(2, 1000):
        candidate = output_dir / f"{stem}_preview_{i}.docx"
        if not candidate.exists():
            return candidate
    raise RuntimeError("Could not choose a unique output filename")


def convert_markdown_to_docx(md_path: Path, output_dir: Path, language: str) -> Path:
    source = md_path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Markdown file not found: {source}")
    if source.suffix.lower() != ".md":
        raise ValueError(f"Expected a .md file, got: {source}")
    if publisher.pypandoc is None:
        raise RuntimeError("pypandoc is not installed; cannot convert to DOCX")

    profile = get_language_profile(language)
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    markdown = source.read_text(encoding="utf-8")
    _warn_em_dash_lines(markdown, source)

    title = _extract_title(markdown, source.stem)
    markdown = publisher.prepare_markdown_for_standalone_export(
        markdown,
        language=profile.code,
        enable_images=True,
    )
    output_path = _unique_output_path(output_dir, source.stem)

    tmp_dir = Path(tempfile.mkdtemp(prefix="docx_preview_"))
    try:
        word_md = tmp_dir / f"{source.stem}_word.md"
        word_md.write_text(
            publisher._prepare_word_md(
                markdown,
                title=title,
                enable_images=True,
                language=profile.code,
            ),
            encoding="utf-8",
        )

        word_args = ["--toc", "--toc-depth=3"]
        ref_doc = publisher._get_word_reference_doc(tmp_dir)
        if ref_doc:
            word_args += ["--reference-doc", str(ref_doc)]

        publisher.pypandoc.convert_file(
            str(word_md),
            to="docx",
            outputfile=str(output_path),
            extra_args=word_args,
        )
        if not publisher._valid_artifact(output_path, ".docx"):
            raise RuntimeError("Pandoc returned without creating a valid DOCX file")
        publisher.finalize_word_docx(
            output_path,
            profile.toc_label,
            page_start_heading=profile.preface_heading,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert an existing Markdown textbook file to DOCX for preview."
    )
    parser.add_argument("md_path", type=Path, help="Absolute or relative path to a .md file")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Folder for the generated DOCX. Defaults to ./docx_preview beside the input file.",
    )
    parser.add_argument(
        "--language",
        default="vi",
        choices=("vi", "en"),
        help="Language profile used for TOC labels and Word front matter.",
    )
    args = parser.parse_args()

    output_dir = args.output_dir
    if output_dir is None:
        output_dir = args.md_path.expanduser().resolve().parent / "docx_preview"

    try:
        output_path = convert_markdown_to_docx(args.md_path, output_dir, args.language)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
