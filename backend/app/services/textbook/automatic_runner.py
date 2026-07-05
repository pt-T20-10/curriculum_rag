"""Standalone, end-to-end textbook workflow runner used by the CLI."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable

from app.config import settings
from app.schemas.curriculum import AgentState, build_initial_state
from app.services.runtime_config import environment_only_runtime_config


ProgressCallback = Callable[[str, dict[str, Any]], None]


def _emit(
    callback: ProgressCallback | None,
    stage: str,
    **payload: Any,
) -> None:
    if callback is not None:
        callback(stage, payload)


def _curriculum_counts(curriculum: Any) -> tuple[int, int]:
    if not curriculum:
        return 0, 0
    chapters = (
        curriculum.chapters
        if hasattr(curriculum, "chapters")
        else curriculum.get("chapters", [])
    )
    subsection_count = 0
    for chapter in chapters:
        subsections = (
            chapter.subsections
            if hasattr(chapter, "subsections")
            else chapter.get("subsections", [])
        )
        subsection_count += len(subsections)
    return len(chapters), subsection_count


def _find_artifacts(state: dict[str, Any]) -> dict[str, str]:
    """Return only output artefacts that actually exist on disk."""
    explicit = {
        "markdown": state.get("final_markdown_filepath"),
        "pdf": state.get("final_pdf_filepath") or state.get("final_filepath"),
        "word": state.get("final_docx_filepath"),
    }
    artifacts = {
        name: str(Path(value).resolve())
        for name, value in explicit.items()
        if value and Path(value).is_file() and Path(value).stat().st_size > 0
    }

    candidates = [value for value in explicit.values() if value]
    existing = [Path(value) for value in candidates if value and Path(value).is_file()]
    if not existing:
        return {}

    # Compatibility for older/fake publishers that only return final_filepath:
    # discover sibling artifacts by stem, then validate their existence.
    stem = existing[0].with_suffix("")
    sibling_paths = {
        "markdown": stem.with_suffix(".md"),
        "pdf": stem.with_suffix(".pdf"),
        "word": stem.with_suffix(".docx"),
    }
    for name, path in sibling_paths.items():
        if name not in artifacts and path.is_file() and path.stat().st_size > 0:
            artifacts[name] = str(path.resolve())
    return artifacts


def _document_stats(markdown_path: str | None) -> dict[str, int]:
    if not markdown_path:
        return {"word_count": 0, "character_count": 0, "image_count": 0}
    try:
        content = Path(markdown_path).read_text(encoding="utf-8")
    except OSError:
        return {"word_count": 0, "character_count": 0, "image_count": 0}
    return {
        "word_count": len(re.findall(r"\b\w+\b", content, flags=re.UNICODE)),
        "character_count": len(content),
        "image_count": len(re.findall(r"!\[[^\]]*\]\([^\)]+\)", content)),
    }


def _cleanup_rag_after_export(state: dict[str, Any]) -> None:
    if not getattr(settings, "CLEANUP_RAG_COLLECTION_AFTER_EXPORT", True):
        return

    collection_name = str(state.get("rag_collection_name") or "")
    if not collection_name:
        return

    try:
        from app.services.textbook.ingester import cleanup_rag_collection

        cleanup_rag_collection(collection_name)
    except Exception:
        pass


def _context_failure_error(state: dict[str, Any]) -> str:
    chapter = int(state.get("current_chapter_index", 0) or 0) + 1
    subsection = int(state.get("current_subsection_index", 0) or 0) + 1
    audit = state.get("rag_source_audit") or {}
    warnings = audit.get("warnings") if isinstance(audit, dict) else None
    warning = ""
    if isinstance(warnings, list) and warnings:
        warning = f" {str(warnings[0])}"
    return (
        f"Insufficient RAG context for Chapter {chapter}.{subsection}; "
        "stopped before writing to avoid unsupported content."
        f"{warning}"
    )


def run_automatic_textbook_workflow(
    *,
    query: str,
    num_chapters: int = 3,
    content_level: str = "Trung Bình",
    max_subsections_per_chapter: int = 5,
    enable_images: bool = False,
    ui_language: str = "vi",
    progress_callback: ProgressCallback | None = None,
    _validator: Callable[[str, str], dict[str, Any]] | None = None,
    _workflow_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Validate and generate a textbook without web, DB, Redis, or Celery.

    Underscored dependency parameters are test seams; normal callers should not
    provide them.
    """
    started = time.monotonic()
    query = query.strip()
    result: dict[str, Any] = {
        "success": False,
        "status": "error",
        "query": query,
        "validation": {},
        "title": "",
        "language": ui_language,
        "stats": {},
        "artifacts": {},
        "error": None,
    }

    try:
        with environment_only_runtime_config():
            if _validator is None:
                from app.services.textbook.validator import validate_topic

                _validator = validate_topic

            _emit(progress_callback, "validating", query=query)
            validation = _validator(query, ui_language)
            result["validation"] = validation
            result["language"] = validation.get("target_language", ui_language)

            if not validation.get("valid", False):
                result.update({
                    "status": "invalid_query",
                    "error": validation.get("reason") or "Query is not suitable",
                    "stats": {"elapsed_seconds": round(time.monotonic() - started, 2)},
                })
                _emit(
                    progress_callback,
                    "validation_rejected",
                    reason=result["error"],
                    suggestion=validation.get("suggestion", ""),
                )
                return result

            _emit(
                progress_callback,
                "validation_accepted",
                core_topic=validation.get("core_topic", query),
                language=result["language"],
            )

            initial_state: AgentState = build_initial_state(  # type: ignore[assignment]
                request=query,
                num_chapters=num_chapters,
                enable_images=enable_images,
                content_level=content_level,
                max_subsections_per_chapter=max_subsections_per_chapter,
                content_type=validation.get("content_type", "technical"),
                core_topic=validation.get("core_topic") or query,
                user_requirements=validation.get("user_requirements", ""),
                language=result["language"],
                advanced_config={},
                export_formats=["PDF", "Word"],
            )
            initial_state["rag_collection_name"] = f"dynamic_context_cli_{time.time_ns()}"  # type: ignore[index]

            if _workflow_factory is None:
                from app.services.textbook.orchestrator import create_workflow

                _workflow_factory = create_workflow

            workflow = _workflow_factory()
            cumulative_state: dict[str, Any] = dict(initial_state)
            all_messages: list[str] = []
            publisher_started = False

            for event in workflow.stream(
                initial_state,
                {"recursion_limit": settings.CONTENT_WORKFLOW_RECURSION_LIMIT},
            ):
                for node_name, node_output in event.items():
                    if isinstance(node_output, dict):
                        cumulative_state.update(node_output)
                        messages = node_output.get("messages", [])
                        if isinstance(messages, list):
                            all_messages.extend(str(message) for message in messages)
                    if node_name == "publisher":
                        publisher_started = True
                    _emit(
                        progress_callback,
                        "workflow_node",
                        node=node_name,
                        chapter=int(cumulative_state.get("current_chapter_index", 0)) + 1,
                        subsection=int(cumulative_state.get("current_subsection_index", 0)) + 1,
                    )

            ingestion_error = next(
                (message for message in all_messages if message.startswith("✗ Ingestion failed")),
                None,
            )
            if ingestion_error:
                result["error"] = ingestion_error.removeprefix("✗ ")
                result["stats"] = {
                    "elapsed_seconds": round(time.monotonic() - started, 2)
                }
                _emit(progress_callback, "failed", error=result["error"])
                _cleanup_rag_after_export(cumulative_state)
                return result

            if (
                not publisher_started
                and cumulative_state.get("context_quality") == "insufficient"
            ):
                result["error"] = _context_failure_error(cumulative_state)
                result["stats"] = {
                    "elapsed_seconds": round(time.monotonic() - started, 2)
                }
                _emit(progress_callback, "failed", error=result["error"])
                _cleanup_rag_after_export(cumulative_state)
                return result

            artifacts = _find_artifacts(cumulative_state)
            if "markdown" not in artifacts:
                result["error"] = "Publisher did not create a Markdown output file"
                result["stats"] = {
                    "elapsed_seconds": round(time.monotonic() - started, 2)
                }
                _emit(progress_callback, "failed", error=result["error"])
                _cleanup_rag_after_export(cumulative_state)
                return result

            missing_exports = [
                label
                for key, label in (("pdf", "PDF"), ("word", "DOCX"))
                if key not in artifacts
            ]
            if missing_exports:
                result["error"] = (
                    "Publisher did not create required export(s): "
                    + ", ".join(missing_exports)
                )
                result["artifacts"] = artifacts
                result["stats"] = {
                    "elapsed_seconds": round(time.monotonic() - started, 2)
                }
                _emit(progress_callback, "failed", error=result["error"])
                _cleanup_rag_after_export(cumulative_state)
                return result

            curriculum = cumulative_state.get("curriculum")
            chapter_count, subsection_count = _curriculum_counts(curriculum)
            stats = _document_stats(artifacts.get("markdown"))
            stats.update({
                "chapter_count": chapter_count,
                "subsection_count": subsection_count,
                "elapsed_seconds": round(time.monotonic() - started, 2),
            }) #type: ignore
            result.update({
                "success": True,
                "status": "completed",
                "title": cumulative_state.get("textbook_title") or validation.get("core_topic") or query,
                "language": cumulative_state.get("language", result["language"]),
                "stats": stats,
                "artifacts": artifacts,
                "error": None,
            })
            _cleanup_rag_after_export(cumulative_state)
            _emit(progress_callback, "completed", title=result["title"], stats=stats)
            return result

    except Exception as exc:
        result["error"] = str(exc) or exc.__class__.__name__
        result["stats"] = {"elapsed_seconds": round(time.monotonic() - started, 2)}
        _emit(progress_callback, "failed", error=result["error"])
        cleanup_state = locals().get("cumulative_state") or locals().get("initial_state") or {}
        _cleanup_rag_after_export(cleanup_state)
        return result
