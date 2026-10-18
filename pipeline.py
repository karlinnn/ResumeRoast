"""Pipeline orchestration – hash-based cache, in-memory TTL store for paid results."""
import hashlib
import logging
import time
import uuid
from typing import Any

from cachetools import TTLCache

import db
import llm
import pdf_utils

logger = logging.getLogger(__name__)

MAX_JD_CHARS = 4_000

# In-memory TTL cache: report_id → paid analysis dict (30 min)
# This holds sensitive paid content temporarily for post-payment retrieval.
_paid_cache: TTLCache = TTLCache(maxsize=500, ttl=1800)

# Free result cache: hash(resume+jd) → {report_id, score, verdict, roast}
_free_cache: TTLCache = TTLCache(maxsize=2000, ttl=3600)


def _content_hash(resume_text: str, jd_text: str) -> str:
    h = hashlib.sha256(f"{resume_text}|||{jd_text}".encode()).hexdigest()
    return h[:32]


def run_free_analysis(pdf_bytes: bytes, jd_text: str) -> dict:
    """Extract text, run free LLM analysis, persist to DB, return result."""
    # Input validation
    resume_text = pdf_utils.extract_text(pdf_bytes)

    jd_text = jd_text.strip()
    if not jd_text:
        raise ValueError("Job description cannot be empty.")
    if len(jd_text) > MAX_JD_CHARS:
        jd_text = jd_text[:MAX_JD_CHARS]

    # Check content cache (same resume+JD submitted before)
    cache_key = _content_hash(resume_text, jd_text)
    cached = _free_cache.get(cache_key)
    if cached:
        logger.info("pipeline_free_cache_hit report_id=%s", cached["report_id"])
        return cached

    # Run LLM
    result = llm.analyze_free(resume_text, jd_text)
    score = result["score"]          # already Python-computed
    verdict = str(result.get("verdict", ""))
    roast = result.get("roast", [])
    badge = result.get("badge", "")
    subscores = result.get("subscores", {})

    report_id = str(uuid.uuid4())

    # Persist to DB (best-effort)
    try:
        db.upsert_report(report_id, score, verdict, roast)
    except Exception as exc:
        logger.warning("db_upsert_failed report_id=%s exc=%s", report_id, exc)

    payload = {
        "report_id": report_id,
        "score":     score,
        "verdict":   verdict,
        "roast":     roast,
        "badge":     badge,
        "subscores": subscores,
    }
    _free_cache[cache_key] = payload

    # Pre-generate paid analysis and stash in TTL cache
    try:
        paid_data = llm.analyze_paid(resume_text, jd_text)
        _paid_cache[report_id] = paid_data
        logger.info("pipeline_paid_prefetch_ok report_id=%s", report_id)
    except Exception as exc:
        logger.warning("pipeline_paid_prefetch_failed report_id=%s exc=%s", report_id, exc)

    return payload


def get_paid_analysis(report_id: str) -> dict:
    """Return paid analysis for a confirmed-paid report_id.

    Raises ValueError if not found (cache expired, unknown ID).
    Raises PermissionError if payment not confirmed in DB.
    """
    if not db.is_paid(report_id):
        raise PermissionError("Payment not confirmed for this report.")

    data = _paid_cache.get(report_id)
    if data is None:
        raise ValueError(
            "Your paid analysis has expired (> 30 min). "
            "Please contact support or re-upload your resume for a fresh analysis."
        )
    return data
