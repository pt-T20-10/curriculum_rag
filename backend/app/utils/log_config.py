"""
Logging configuration with Celery and absolute path support.

CRITICAL FIXES:
1. force_file_handler=True: Ensures file logging works in Celery context
2. Absolute path resolution: Relative paths converted using BASE_DIR
3. logger.propagate=False: Prevents duplicate logs in Celery

Without these fixes, logs appear in terminal but not in files when
running under Celery worker.
"""

import logging
from logging.handlers import RotatingFileHandler
import sys
import threading
from datetime import datetime
from pathlib import Path

_prompt_counters: dict[str, int] = {}
_prompt_counter_lock = threading.Lock()


def setup_prompt_logger(agent_name: str, log_dir: str = "logs/prompts") -> "PromptLogger":
    """
    Create a PromptLogger for a specific agent.
    Each agent gets its own log file: logs/prompts/{agent_name}_prompts.log
    """
    return PromptLogger(agent_name=agent_name, log_dir=log_dir)


class PromptLogger:
    """
    Lightweight prompt logger — writes system + user prompt to a per-agent file,
    numbered sequentially, thread-safe.

    Usage:
        prompt_logger = setup_prompt_logger("writer")
        prompt_logger.log(
            system_prompt="You are...",
            user_prompt="Write section...",
            context_label="1.2 Tên mục"
        )
    """

    def __init__(self, agent_name: str, log_dir: str = "logs/prompts") -> None:
        # Import settings to get BASE_DIR
        from app.config import settings
        
        self.agent_name = agent_name
        self.enabled = getattr(settings, "ENABLE_PROMPT_LOGS", True)
        # Convert to absolute path using BASE_DIR
        log_dir_path = settings.BASE_DIR / log_dir if not Path(log_dir).is_absolute() else Path(log_dir)
        self.log_path = log_dir_path / f"{agent_name}_prompts.log"
        if self.enabled:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.enabled:
            return 0

        with _prompt_counter_lock:
            if agent_name not in _prompt_counters:
                _prompt_counters[agent_name] = 0

    def log(
        self,
        system_prompt: str,
        user_prompt: str = "",
        context_label: str = "",
    ) -> int:
        """
        Write one prompt entry to the log file.

        Returns:
            1-indexed sequence number of the entry written.
        """
        with _prompt_counter_lock:
            _prompt_counters[self.agent_name] += 1
            n = _prompt_counters[self.agent_name]

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header_suffix = f" | {context_label}" if context_label else ""

        lines = [
            "=" * 80,
            f"[PROMPT #{n}] {timestamp}{header_suffix}",
            "=" * 80,
            "--- SYSTEM ---",
            system_prompt.strip(),
        ]

        if user_prompt.strip():
            lines += [
                "",
                "--- USER ---",
                user_prompt.strip(),
            ]

        lines += [
            "",
            f"--- END PROMPT #{n} ---",
            "",
        ]

        entry = "\n".join(lines) + "\n"

        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(entry)

        return n


def setup_logger(
    name: str = "SystemLog", 
    logfile: str = "logs/SystemLog.log", 
    level: int = logging.INFO,
    force_file_handler: bool = True,
):
    """
    Sets up and returns a shared logger instance with both console and file handlers.
    
    Celery-compatible: Forces file handler addition even if logger already has handlers
    from Celery's own configuration. This ensures logs are written to files in both
    direct execution and Celery worker contexts.
    
    CRITICAL FIX: Resolves relative log paths to absolute paths using BASE_DIR.
    Without this, Celery workers write logs to wrong directories based on their
    working directory instead of the project root.
    
    Parameters
    ----------
    name : str, optional
        Name of the logger (default: "SystemLog").
    logfile : str, optional
        Path to the log file. Can be absolute or relative to project root.
        Examples:
            "logs/url_filter.log"           → backend/logs/url_filter.log
            "backend/logs/agents.log"       → backend/backend/logs/agents.log (if run from project root)
            "/absolute/path/to/custom.log"  → /absolute/path/to/custom.log (used as-is)
    level : int, optional
        Logging level (default: INFO).
    force_file_handler : bool, optional
        If True, adds file handler even if logger already has handlers.
        Set to True for Celery compatibility (default: True).
    
    Returns
    -------
    logging.Logger
        Configured logger instance with console and file handlers.
    
    Notes
    -----
    In Celery worker context, loggers are pre-configured with console handlers.
    Without force_file_handler=True, file logging would be skipped entirely.
    
    Relative paths are resolved to absolute using settings.BASE_DIR to ensure
    logs are written to the correct location regardless of Celery's working directory.
    """
    # ⭐ CRITICAL FIX: Resolve relative paths to absolute using BASE_DIR
    # Celery workers may run from different working directories, causing
    # relative paths like "logs/url_filter.log" to write to wrong locations.
    from app.config import settings
    
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False  # ⭐ Prevent duplicate logs in Celery
    
    # Format: Timestamp - [Level] - LoggerName - Function() - Message
    formatter = logging.Formatter(
        fmt="%(asctime)s - [%(levelname)s] - %(name)s - %(funcName)s() - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # ⭐ Convert relative paths to absolute using BASE_DIR
    # Example: "logs/url_filter.log" → "D:/Thesis/curriculum_rag/backend/logs/url_filter.log"
    log_path_input = Path(logfile)
    if log_path_input.is_absolute():
        log_path = log_path_input
    else:
        log_path = settings.BASE_DIR / logfile
    
    # Ensure log directory exists
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[LOG_CONFIG] Failed to create log directory {log_path.parent}: {e}", file=sys.stderr)
    
    # ========================================================================
    # Check if handlers already exist (Celery compatibility)
    # ========================================================================
    
    has_console = any(isinstance(h, logging.StreamHandler) and h.stream == sys.stdout 
                     for h in logger.handlers)
    has_file = any(isinstance(h, logging.FileHandler) and h.baseFilename == str(log_path.resolve())
                   for h in logger.handlers)
    
    # ========================================================================
    # 1. Console Handler (stdout)
    # ========================================================================
    if not has_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    # ========================================================================
    # 2. File Handler (ALWAYS add if force_file_handler=True)
    # ========================================================================
    if getattr(settings, "LOG_TO_FILES", True) and (force_file_handler or not has_file):
        try:
            # Remove old file handler if exists and we're forcing
            if force_file_handler and has_file:
                for handler in logger.handlers[:]:
                    if isinstance(handler, logging.FileHandler):
                        if handler.baseFilename == str(log_path.resolve()):
                            logger.removeHandler(handler)
                            handler.close()
            
            # Add new file handler
            file_handler = RotatingFileHandler(
                log_path,
                mode="a",
                maxBytes=getattr(settings, "LOG_MAX_BYTES", 10 * 1024 * 1024),
                backupCount=getattr(settings, "LOG_BACKUP_COUNT", 5),
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            
            # Debug: Print where logs are being written (only once per logger)
            if not has_file:
                print(f"[LOG_CONFIG] {name} → {log_path.resolve()}", file=sys.stderr)
            
        except Exception as e:
            print(f"[LOG_CONFIG] Failed to setup file handler for {log_path}: {e}", file=sys.stderr)
    
    return logger
