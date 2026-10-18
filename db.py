"""Database helpers – Postgres via psycopg2.

Schema (auto-created on startup):
  reports      – one row per analysis (free result + paid unlock state)
  events       – server-side analytics
"""
import json
import logging
import os

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

_conn: "psycopg2.extensions.connection | None" = None


def _get_conn():
    global _conn
    if _conn is None or _conn.closed:
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL env var is not set.")
        # connect_timeout prevents hanging for the OS TCP timeout (~2 min)
        # when the DB host is reachable but not accepting connections.
        _conn = psycopg2.connect(
            url,
            cursor_factory=psycopg2.extras.RealDictCursor,
            connect_timeout=5,
        )
        _conn.autocommit = False
    return _conn


def init_db() -> None:
    """Create tables if they don't exist."""
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            report_id   TEXT PRIMARY KEY,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            score       INTEGER,
            verdict     TEXT,
            roast       JSONB,
            paid        BOOLEAN NOT NULL DEFAULT FALSE,
            order_id    TEXT,
            payment_id  TEXT
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id          BIGSERIAL PRIMARY KEY,
            ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            event       TEXT NOT NULL,
            report_id   TEXT,
            ip          TEXT,
            meta        JSONB
        );
        """)
    conn.commit()
    logger.info("db_init_ok")


def upsert_report(
    report_id: str,
    score: int,
    verdict: str,
    roast: list[str],
) -> None:
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("""
        INSERT INTO reports (report_id, score, verdict, roast)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (report_id) DO UPDATE
          SET score = EXCLUDED.score,
              verdict = EXCLUDED.verdict,
              roast = EXCLUDED.roast;
        """, (report_id, score, verdict, json.dumps(roast)))
    conn.commit()


def get_report(report_id: str) -> dict | None:
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM reports WHERE report_id = %s", (report_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def save_order(report_id: str, order_id: str) -> None:
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE reports SET order_id = %s WHERE report_id = %s",
            (order_id, report_id),
        )
    conn.commit()


def mark_paid(report_id: str, payment_id: str) -> bool:
    """Set paid=True. Returns True if this is the first time (idempotent)."""
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("""
        UPDATE reports
        SET paid = TRUE, payment_id = %s
        WHERE report_id = %s AND paid = FALSE
        RETURNING report_id
        """, (payment_id, report_id))
        updated = cur.fetchone()
    conn.commit()
    return updated is not None


def log_event(event: str, report_id: str | None, ip: str | None, meta: dict | None = None) -> None:
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO events (event, report_id, ip, meta) VALUES (%s, %s, %s, %s)",
                (event, report_id, ip, json.dumps(meta or {})),
            )
        conn.commit()
    except Exception as exc:
        logger.warning("event_log_failed event=%s exc=%s", event, exc)


def is_paid(report_id: str) -> bool:
    row = get_report(report_id)
    return bool(row and row.get("paid"))
