import os
import logging
from collections import deque
from typing import Deque, Optional

log_dir = "logs"
_global_log_level = logging.INFO

# Shared log buffer for UI display (1000 most recent log messages)
_log_buffer: Deque[str] = deque(maxlen=1000)
_buffer_handler_attached = False


class BufferHandler(logging.Handler):
    """Handler that stores formatted log messages in the shared buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            _log_buffer.append(msg)
        except Exception:
            self.handleError(record)

def _ensure_buffer_handler() -> None:
    """Ensure the buffer handler is attached to the root logger (called once)."""
    global _buffer_handler_attached
    if not _buffer_handler_attached:
        # Attach to the TRUE root logger (empty string) to capture ALL logs
        root_logger = logging.getLogger()
        # Set root logger to DEBUG so it doesn't filter messages before they reach handlers
        root_logger.setLevel(logging.DEBUG)
        handler = BufferHandler()
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)
        handler.setLevel(logging.DEBUG)  # Capture all levels
        root_logger.addHandler(handler)
        _buffer_handler_attached = True
        # Use a LEAF logger for this message to avoid infinite recursion
        logging.getLogger('leaf.utility.logger').info("Buffer handler attached to root logger")


def get_log_buffer() -> Deque[str]:
    """Get the shared log buffer containing recent log messages."""
    return _log_buffer


def clear_log_buffer() -> None:
    """Clear the shared log buffer."""
    _log_buffer.clear()


def set_global_log_level(level: int) -> None:
    """Set the global log level for all loggers."""
    global _global_log_level
    _global_log_level = level

def get_logger(name: str, log_file: Optional[str] = None,
               log_level: Optional[int] = None,
               error_log_file: Optional[str] = None) -> logging.Logger:
    """
    Utility to get a configured logger with optional file logging and custom log level.
    Supports separate log files for different log levels.

    Args:
        name: Name of the logger.
        log_file: Log file for general logging.
        log_level: Logging level for general logging. If None, uses global log level.
        error_log_file: Log file for error-specific logging.

    Returns:
        Configured logger instance.
    """
    # Use global log level if none specified
    if log_level is None:
        log_level = _global_log_level

    logger = logging.getLogger(name)

    if logger.hasHandlers():
        logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)


    if log_file:
        os.makedirs(log_dir, exist_ok=True)
        general_log_file = os.path.join(log_dir, log_file)
        file_handler = logging.FileHandler(general_log_file)
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    if error_log_file:
        error_log_file_path = os.path.join(log_dir, error_log_file)
        error_file_handler = logging.FileHandler(error_log_file_path)
        error_file_handler.setLevel(logging.ERROR)
        error_file_handler.setFormatter(formatter)
        logger.addHandler(error_file_handler)

    logger.setLevel(log_level)

    return logger


def set_log_dir(directory: str) -> None:
    global log_dir
    os.makedirs(directory, exist_ok=True)
    log_dir = directory


# Attach buffer handler immediately when this module is imported
# This ensures we capture ALL logs from the very beginning
_ensure_buffer_handler()
