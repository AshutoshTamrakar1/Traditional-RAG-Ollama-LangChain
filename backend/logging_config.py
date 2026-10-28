import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional, Callable, Any
from config import get_settings
import functools
import asyncio
from fastapi import HTTPException as FastAPIHTTPException

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
DEFAULT_LOG_FILE = os.path.join(LOG_DIR, "app.log")


def configure_logging(level: int = logging.INFO, log_file: Optional[str] = None) -> None:
    """Configure root logger (console + rotating file). Call early in startup."""
    if log_file is None:
        log_file = DEFAULT_LOG_FILE

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(filename)s:%(lineno)d | %(funcName)s | %(message)s"
    )

    root = logging.getLogger()
    root.setLevel(level)

    # Remove any existing handlers to avoid duplicate logs
    while root.handlers:
        root.removeHandler(root.handlers[0])

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(formatter)
    root.addHandler(ch)

    # Rotating file handler
    fh = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(formatter)
    root.addHandler(fh)

    # Reduce noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def init_from_settings():
    """Initialize logging using Settings.LOG_LEVEL if present, otherwise INFO."""
    settings = get_settings()
    level = getattr(settings, "LOG_LEVEL", None)
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    if level is None:
        level = logging.INFO
    configure_logging(level=level)


def get_logger(name: str):
    return logging.getLogger(name)


def _handle_exception(exc: Exception, func: Any, custom_logger: Optional[logging.Logger] = None) -> None:
    """Log caught exception with appropriate log level."""
    log = custom_logger or logging.getLogger(func.__module__)
    func_name = getattr(func, "__name__", str(func))
    # Treat FastAPI HTTPExceptions as expected control-flow (e.g., auth failures)
    # Log them at WARNING without full traceback to avoid noisy ERROR logs.
    if isinstance(exc, FastAPIHTTPException):
        log.warning("HTTPException in %s: %s", func_name, getattr(exc, "detail", str(exc)))
    else:
        log.exception("Unhandled exception in %s: %s", func_name, exc)


def log_exceptions(_func=None, logger: Optional[logging.Logger] = None):
    """
    Decorator that logs unhandled exceptions. Usable as:
      @log_exceptions
    or
      @log_exceptions(logger)
    """
    def _decorator(func):
        @functools.wraps(func)
        async def _async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                _handle_exception(e, func, logger)
                raise

        @functools.wraps(func)
        def _sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                _handle_exception(e, func, logger)
                raise

        return _async_wrapper if asyncio.iscoroutinefunction(func) else _sync_wrapper

    # If used as @log_exceptions without args
    if callable(_func):
        return _decorator(_func)
    # If used as @log_exceptions(logger) or @log_exceptions()
    return _decorator
