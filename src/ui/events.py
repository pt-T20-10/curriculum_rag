from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class EventType(str, Enum):
    INGESTION_START = "ingestion_start"
    INGESTION_DONE  = "ingestion_done"
    PLANNER_DONE    = "planner_done"
    CONTENT_UPDATE  = "content_update"
    CHECKPOINT      = "checkpoint"
    PUBLISHER_DONE  = "publisher_done"
    STOPPED         = "stopped"
    ERROR           = "error"
    DONE            = "done"
    VALIDATION_FAILED = "validation_failed"

@dataclass
class WorkflowEvent:
    type: EventType

    # PLANNER_DONE
    curriculum:                Any      = None
    total_chapters:            int      = 0
    total_subsections:         int      = 0
    chapter_subsection_counts: list     = field(default_factory=list)
    # Planner outputs forwarded for the content-phase state build
    textbook_title:            str      = ""
    preface_content:           str      = ""

    # CONTENT_UPDATE / CHECKPOINT
    stage:                   str = ""
    stage_status:            str = "start"   # "start" | "done"
    chapter_idx:             int = 0
    subsection_idx:          int = 0
    subsections_in_chapter:  int = 0         # subsection count for current chapter only

    # PUBLISHER_DONE
    final_filepath:      Optional[str] = None
    final_docx_filepath: Optional[str] = None

    # ERROR
    error: Optional[Exception] = None
    validation_reason:     str = ""
    validation_suggestion: str = ""