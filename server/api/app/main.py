import hashlib
import logging
import os
import random
import secrets
import time
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal

import psycopg
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from app import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")

log = logging.getLogger("demoapp.api")
http_log = logging.getLogger("demoapp.http")

SLOW_REQUEST_MS = float(os.getenv("SLOW_REQUEST_MS", "1000"))
SLOW_REPORT_RATE = float(os.getenv("SLOW_REPORT_RATE", "0.1"))

started_at = time.monotonic()
responses_by_status: Counter[int] = Counter()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        with db.connection() as conn:
            conn.execute("SELECT 1")
    except psycopg.OperationalError:
        log.critical("Database unavailable at startup", exc_info=True)
        db.fatal_exit()
    log.info("API started")
    yield
    log.info("API stopping")


app = FastAPI(title="demoapp", lifespan=lifespan)


@app.middleware("http")
async def observe_requests(request: Request, call_next) -> Response:
    # Healthcheck se poziva svakih par sekundi i samo bi zatrpao log.
    if request.url.path == "/health":
        return await call_next(request)

    method, path = request.method, request.url.path
    client_ip = request.headers.get("x-real-ip") or request.client.host

    start = time.perf_counter()
    try:
        response = await call_next(request)
    except psycopg.OperationalError as exc:
        log.exception("Database error on %s %s: %s", method, path, exc)
        response = JSONResponse({"detail": "Database unavailable"}, status_code=503)
    except Exception:
        log.exception("Unhandled error on %s %s", method, path)
        response = JSONResponse({"detail": "Internal server error"}, status_code=500)

    duration_ms = (time.perf_counter() - start) * 1000
    responses_by_status[response.status_code] += 1
    level = logging.WARNING if duration_ms >= SLOW_REQUEST_MS else logging.INFO
    label = "Slow request" if level == logging.WARNING else "Request"
    http_log.log(
        level,
        "%s %s %s -> %d (%.1f ms)",
        label,
        method,
        path,
        response.status_code,
        duration_ms,
        extra={
            "fields": {
                "method": method,
                "path": path,
                "status": response.status_code,
                "duration_ms": round(duration_ms, 1),
                "client_ip": client_ip,
            }
        },
    )
    return response


@app.get("/health")
def health() -> Response:
    uptime = round(time.monotonic() - started_at, 1)
    try:
        with db.connection() as conn:
            conn.execute("SELECT 1")
    except psycopg.OperationalError as exc:
        log.error("Health check failed: %s", exc)
        return JSONResponse(
            {"status": "degraded", "database": "down", "uptime_seconds": uptime},
            status_code=503,
        )
    return JSONResponse({"status": "ok", "database": "up", "uptime_seconds": uptime})


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    lines = [
        f'demoapp_responses_total{{status="{status}"}} {count}'
        for status, count in sorted(responses_by_status.items())
    ]
    lines.append(f"demoapp_db_failures_total {db.failures_total}")
    lines.append(f"demoapp_uptime_seconds {time.monotonic() - started_at:.1f}")
    return PlainTextResponse("\n".join(lines) + "\n")


class Credentials(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=200)


class NewOrder(BaseModel):
    user_id: int
    item: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


@app.post("/login")
def login(credentials: Credentials) -> dict[str, str]:
    digest = hashlib.sha256(credentials.password.encode()).hexdigest()
    with db.connection() as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE username = %s AND password_sha256 = %s",
            (credentials.username, digest),
        ).fetchone()
    if user is None:
        # %r escapira prijelome retka, korisnik ne može podmetnuti lažni zapis u log.
        log.warning("Failed login for user %r", credentials.username)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    log.info("User %r logged in", credentials.username)
    return {"token": secrets.token_hex(16)}


@app.get("/users/{user_id}")
def get_user(user_id: int) -> dict:
    with db.connection() as conn:
        user = conn.execute("SELECT id, username FROM users WHERE id = %s", (user_id,)).fetchone()
    if user is None:
        log.warning("User %d not found", user_id)
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.get("/orders")
def list_orders(limit: int = Query(default=20, ge=1, le=200)) -> list[dict]:
    with db.connection() as conn:
        return conn.execute(
            "SELECT id, user_id, item, amount, created_at FROM orders ORDER BY id DESC LIMIT %s",
            (limit,),
        ).fetchall()


@app.post("/orders", status_code=201)
def create_order(order: NewOrder) -> dict:
    try:
        with db.connection() as conn:
            return conn.execute(
                "INSERT INTO orders (user_id, item, amount) VALUES (%s, %s, %s) "
                "RETURNING id, user_id, item, amount, created_at",
                (order.user_id, order.item, order.amount),
            ).fetchone()
    except psycopg.errors.ForeignKeyViolation:
        log.warning("Order rejected, user %d does not exist", order.user_id)
        raise HTTPException(status_code=404, detail="User not found") from None


@app.get("/reports/daily")
def daily_report() -> list[dict]:
    with db.connection() as conn:
        if random.random() < SLOW_REPORT_RATE:
            conn.execute("SELECT pg_sleep(1.2)")
        return conn.execute(
            "SELECT created_at::date AS day, count(*) AS orders, sum(amount) AS total "
            "FROM orders GROUP BY 1 ORDER BY 1 DESC LIMIT 7"
        ).fetchall()


@app.get("/reports/average")
def average_per_day(days: int = 7) -> dict:
    with db.connection() as conn:
        total = conn.execute("SELECT coalesce(sum(amount), 0) AS t FROM orders").fetchone()["t"]
    # Namjerno bez provjere: days=0 daje pravi traceback u logovima.
    return {"days": days, "average_per_day": round(float(total) / days, 2)}
