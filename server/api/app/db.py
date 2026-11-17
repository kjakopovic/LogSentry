import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

log = logging.getLogger("demoapp.db")

DATABASE_URL = os.environ["DATABASE_URL"]
MAX_FAILURES = int(os.getenv("DB_MAX_FAILURES", "5"))

_lock = threading.Lock()
_consecutive_failures = 0
failures_total = 0


def fatal_exit() -> None:
    """Ruši proces da ga Docker ponovno pokrene, pa nginx u međuvremenu vraća 502."""
    logging.shutdown()
    os._exit(1)


def _record_failure() -> None:
    global _consecutive_failures, failures_total
    with _lock:
        _consecutive_failures += 1
        failures_total += 1
        reached_limit = _consecutive_failures >= MAX_FAILURES
    if reached_limit:
        log.critical("Database unreachable after %d attempts, shutting down", MAX_FAILURES)
        fatal_exit()


def _record_success() -> None:
    global _consecutive_failures
    with _lock:
        _consecutive_failures = 0


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=2, row_factory=dict_row) as conn:
            yield conn
    except psycopg.OperationalError:
        _record_failure()
        raise
    _record_success()
