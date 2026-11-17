import gzip
import json
import logging
import os
import shutil
import sys
import time
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from typing import Any

# Podaci o trenutnom zahtjevu, dodaju se u svaki JSON zapis.
request_context: ContextVar[dict[str, Any] | None] = ContextVar("request_context", default=None)

TEXT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **(request_context.get() or {}),
            **getattr(record, "fields", {}),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def _gzip_rotator(source: str, dest: str) -> None:
    with open(source, "rb") as src, gzip.open(dest, "wb") as dst:
        shutil.copyfileobj(src, dst)
    os.remove(source)


def setup_logging() -> None:
    """Tekst s tracebackovima ide na stdout, JSON u datoteku s rotacijom."""
    text_formatter = logging.Formatter(TEXT_FORMAT)
    text_formatter.converter = time.gmtime
    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(text_formatter)

    log_file = RotatingFileHandler(
        os.environ["LOG_FILE"],
        maxBytes=int(os.getenv("LOG_MAX_BYTES", str(5 * 1024 * 1024))),
        backupCount=int(os.getenv("LOG_BACKUP_COUNT", "5")),
        encoding="utf-8",
    )
    log_file.setFormatter(JsonFormatter())
    log_file.namer = lambda name: f"{name}.gz"
    log_file.rotator = _gzip_rotator

    root = logging.getLogger()
    root.setLevel(os.getenv("LOG_LEVEL", "INFO"))
    root.handlers[:] = [stdout, log_file]

    # Uvicorn postavlja vlastite handlere, a njegovi zapisi trebaju ići istim putem.
    # uvicorn.access ostaje isključen, zahtjeve bilježi middleware.
    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
