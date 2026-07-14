from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import textwrap
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.textbook import publisher  # noqa: E402
from app.services.textbook.language import get_language_profile  # noqa: E402
from scripts.convert_markdown_to_docx import (  # noqa: E402
    _extract_title,
    _warn_em_dash_lines,
)


def _unique_output_paths(output_dir: Path, stem: str) -> tuple[Path, Path]:
    for suffix in [""] + [f"_{i}" for i in range(2, 1000)]:
        base = output_dir / f"{stem}_preview{suffix}"
        pdf = base.with_suffix(".pdf")
        docx = base.with_suffix(".docx")
        if not pdf.exists() and not docx.exists():
            return pdf, docx
    raise RuntimeError("Could not choose unique output filenames")


def _write_typst_header(tmp_dir: Path) -> Path:
    header = tmp_dir / "typst_header.typ"
    header.write_text(
        textwrap.dedent("""\
            #let conf(
              title: none,
              authors: none,
              date: none,
              abstract: none,
              cols: 1,
              margin: (x: 1.25in, y: 1.25in),
              paper: "us-letter",
              lang: "en",
              region: "US",
              font: (),
              fontsize: 11pt,
              sectionnumbering: none,
              doc,
              ..args,
            ) = {
              set page(
                paper: paper,
                margin: margin,
                numbering: none,
              )
              set par(justify: true)
              set text(lang: lang,
                       region: region,
                       font: font,
                       size: fontsize)
              set heading(numbering: sectionnumbering)
              if cols == 1 { doc } else { columns(cols, doc) }
            }
        """),
        encoding="utf-8",
    )
    return header


def convert_markdown_to_pdf_docx(
    md_path: Path,
    output_dir: Path,
    language: str,
) -> dict[str, Path]:
    source = md_path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Markdown file not found: {source}")
    if source.suffix.lower() != ".md":
        raise ValueError(f"Expected a .md file, got: {source}")
    if publisher.pypandoc is None:
        raise RuntimeError("pypandoc is not installed; cannot convert artifacts")

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
    pdf_path, docx_path = _unique_output_paths(output_dir, source.stem)

    tmp_dir = Path(tempfile.mkdtemp(prefix="pdf_docx_preview_"))
    try:
        typst_header = _write_typst_header(tmp_dir)
        typst_root = source.anchor or publisher.BASE_DIR.anchor
        typst_bin = shutil.which("typst") or "typst"
        pdf_md = tmp_dir / f"{source.stem}_pdf.md"
        pdf_md.write_text(markdown, encoding="utf-8")

        publisher.pypandoc.convert_file(
            str(pdf_md),
            to="pdf",
            outputfile=str(pdf_path),
            extra_args=[
                f"--pdf-engine={typst_bin}",
                "--pdf-engine-opt=--root",
                f"--pdf-engine-opt={typst_root}",
                "--include-in-header",
                str(typst_header),
                "--resource-path",
                str(source.parent),
                "-V",
                "margin-left=2.5cm",
                "-V",
                "margin-right=2.5cm",
                "-V",
                "margin-top=2cm",
                "-V",
                "margin-bottom=2cm",
            ],
        )
        if not publisher._valid_artifact(pdf_path, ".pdf"):
            raise RuntimeError("Pandoc returned without creating a valid PDF file")

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

        word_args = ["--toc", "--toc-depth=3", "--resource-path", str(source.parent)]
        ref_doc = publisher._get_word_reference_doc(tmp_dir)
        if ref_doc:
            word_args += ["--reference-doc", str(ref_doc)]

        publisher.pypandoc.convert_file(
            str(word_md),
            to="docx",
            outputfile=str(docx_path),
            extra_args=word_args,
        )
        if not publisher._valid_artifact(docx_path, ".docx"):
            raise RuntimeError("Pandoc returned without creating a valid DOCX file")
        publisher.finalize_word_docx(
            docx_path,
            profile.toc_label,
            page_start_heading=profile.preface_heading,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {"pdf": pdf_path, "word": docx_path}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert an existing Markdown textbook file to PDF and DOCX for preview."
    )
    parser.add_argument("md_path", type=Path, help="Absolute or relative path to a .md file")
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Folder for the generated PDF and DOCX preview files.",
    )
    parser.add_argument(
        "--language",
        default="vi",
        choices=("vi", "en"),
        help="Language profile used for TOC labels and Word front matter.",
    )
    args = parser.parse_args()

    try:
        artifacts = convert_markdown_to_pdf_docx(
            args.md_path,
            args.output_dir,
            args.language,
        )
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"PDF: {artifacts['pdf']}")
    print(f"Word: {artifacts['word']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
