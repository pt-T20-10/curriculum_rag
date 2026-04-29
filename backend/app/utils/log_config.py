import logging
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
        self.agent_name = agent_name
        self.log_path = Path(log_dir) / f"{agent_name}_prompts.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
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


def setup_logger(name: str = "SystemLog", logfile: str = "logs/SystemLog.log", level: int = logging.INFO):
    """
    Sets up and returns a shared logger instance.
    
    Parameters
    ----------
    name : str, optional
        Name of the logger (default: "SystemLog").
    logfile : str, optional
        Path to the log file.
    level : int, optional
        Logging level (default: INFO).
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Prevent adding handlers multiple times if they already exist
    if logger.hasHandlers():
        return logger

    # Ensure log directory exists
    log_path = Path(logfile)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"Failed to create log directory: {e}")

    # Format: Timestamp - [Level] - LoggerName - Function() - Message
    formatter = logging.Formatter(
        fmt="%(asctime)s - [%(levelname)s] - %(name)s - %(funcName)s() - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 1. Console Handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 2. File Handler
    try:
        file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Failed to setup file handler: {e}")

    return logger