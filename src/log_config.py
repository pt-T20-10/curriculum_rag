import logging
import sys
from pathlib import Path

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