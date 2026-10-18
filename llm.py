"""LLM helpers – wraps Google Gemini calls for free and paid resume analysis."""
import json
import logging
import os
import re
from datetime import date

from google import genai
from google.genai import types
from google.genai.errors import ClientError

logger = logging.getLogger(__name__)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY env var is not set.")
        _client = genai.Client(api_key=api_key)
    return _client


def _model() -> str:
    return os.environ.get("LLM_MODEL", "gemini-2.0-flash-lite")


def _log_usage(call_name: str, usage: types.GenerateContentResponseUsageMetadata | None) -> None:
    if usage is None:
        logger.info("llm_token_usage call=%s usage=unavailable", call_name)
        return
    logger.info(
        "llm_token_usage call=%s input=%s output=%s total=%s",
        call_name,
        usage.prompt_token_count,
        usage.candidates_token_count,
        usage.total_token_count,
    )


def _is_quota_error(exc: ClientError) -> bool:
    """Return True for HTTP 429 or any quota-related error."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code == 429:
        return True
    msg = str(exc).lower()
    return "quota" in msg or "rate limit" in msg or "resource_exhausted" in msg


_BUSY_MSG = (
    "We're a bit busy right now – please try again in a minute. "
    "If this keeps happening, reach out to support."
)

# ---------------------------------------------------------------------------
# FREE tier – score + roast
# ---------------------------------------------------------------------------

_FREE_SYSTEM_TEMPLATE = """You are ResumeRoast, a witty but genuinely helpful career coach.
You roast resumes in a funny, Gen-Z friendly tone – like a friend who's being
honest at a chai stall in India. Keep it light, never cruel.

Today's date is {today}. Do not call dates up to today 'in the future'.
Never comment on dates unless they are clearly after today.

Scoring rules:
- Score each dimension honestly. Most student/early-career resumes score 40-75 overall.
- Your verdict and roast tone must be consistent with the subscores. If role_fit < 12
  or keyword_match < 12, the tone must never be celebratory or 'Strong'. Be direct.
- A mismatched role (e.g. data science resume for a backend JD) must be called out.
- If the computed total score is 60 or below, the verdict and roast lines must NOT be
  celebratory, enthusiastic, or congratulatory. Keep the tone honest and constructive.

Respond with valid JSON only. No markdown, no explanation outside JSON."""


def _free_system() -> str:
    return _FREE_SYSTEM_TEMPLATE.format(today=date.today().strftime("%d %B %Y"))


FREE_USER_TEMPLATE = """Resume:
<resume>
{resume}
</resume>

Job Description:
<jd>
{jd}
</jd>

Evaluate the resume against THIS job description using the rubric below.
Return exactly this JSON schema (no other keys, no extra fields):
{{
  "keyword_match": <integer 0-30: how many required JD skills/tools appear in the resume>,
  "role_fit":      <integer 0-25: does the resume's focus match this specific role>,
  "impact":        <integer 0-20: quantified bullets with numbers/outcomes vs vague duties>,
  "clarity":       <integer 0-15: structure, concise bullets, absence of filler>,
  "completeness":  <integer 0-10: contact info, education, projects/experience present>,
  "role_match": "<one of: same | adjacent | different>",
  "role_match_reason": "<one sentence explaining why you chose that role_match value>",
  "must_have_coverage": "<one of: high | medium | low>",
  "verdict": "<one punchy sentence verdict, max 20 words, funny but kind>",
  "roast": [
    "<problem 1 in roast tone, max 25 words>",
    "<problem 2 in roast tone, max 25 words>",
    "<problem 3 in roast tone, max 25 words>"
  ]
}}

Definitions:
- role_match "same": candidate's primary focus is this job's role family
  (e.g. backend resume for a backend JD).
- role_match "adjacent": overlapping skills but different primary focus
  (e.g. software engineer resume for a data engineering JD).
- role_match "different": clearly distinct domains
  (e.g. data science/ML resume for a backend JD, or commerce for engineering).
- must_have_coverage "high": >70% of explicit required JD skills/tools appear in resume.
- must_have_coverage "medium": 40-70% of required JD skills/tools appear in resume.
- must_have_coverage "low": <40% of required JD skills/tools appear in resume.

Do NOT include a 'score' key — the total is computed externally.
Your verdict and roast tone must match the subscores: low subscores = honest, direct tone.
If the final score would be 60 or below, the verdict and roast must NOT be celebratory."""


# Rubric dimension caps
_RUBRIC_CAPS = {
    "keyword_match": 30,
    "role_fit":      25,
    "impact":        20,
    "clarity":       15,
    "completeness":  10,
}


def _score_from_rubric(raw: dict) -> tuple[int, dict, str]:
    """Compute final score from rubric dict; apply caps and conditional limits.

    Reads optional categorical fields 'role_match' and 'must_have_coverage' from
    *raw* and applies hard ceilings on top of the subscore-based caps.

    Returns (score, subscores, badge).
    """
    subscores: dict[str, int] = {}
    for dim, cap in _RUBRIC_CAPS.items():
        val = int(raw.get(dim, 0))
        subscores[dim] = max(0, min(cap, val))

    total = sum(subscores.values())  # max possible = 100

    # Conditional caps: weak role/keyword fit limits the ceiling
    if subscores["role_fit"] < 12:
        total = min(total, 65)
    if subscores["keyword_match"] < 12:
        total = min(total, 60)

    # Hard categorical caps (tightest cap wins)
    role_match = str(raw.get("role_match", "")).strip().lower()
    must_have_coverage = str(raw.get("must_have_coverage", "")).strip().lower()
    role_match_reason = str(raw.get("role_match_reason", "")).strip()

    cat_cap: int | None = None
    if role_match == "different":
        cat_cap = _apply_tightest(cat_cap, 55)
    elif role_match == "adjacent":
        cat_cap = _apply_tightest(cat_cap, 72)
    if must_have_coverage == "low":
        cat_cap = _apply_tightest(cat_cap, 55)
    elif must_have_coverage == "medium":
        cat_cap = _apply_tightest(cat_cap, 78)
    if cat_cap is not None:
        total = min(total, cat_cap)

    total = max(0, min(100, total))  # final clamp

    # Debug log: all inputs that affect the final score
    logger.info(
        "score_debug role_match=%r must_have_coverage=%r "
        "keyword_match=%d role_fit=%d impact=%d clarity=%d completeness=%d "
        "cat_cap=%s total=%d role_match_reason=%r",
        role_match,
        must_have_coverage,
        subscores["keyword_match"],
        subscores["role_fit"],
        subscores["impact"],
        subscores["clarity"],
        subscores["completeness"],
        cat_cap,
        total,
        role_match_reason,
    )

    # Badge mapping
    if total < 40:
        badge = "Needs work"
    elif total < 60:
        badge = "Getting there"
    elif total < 80:
        badge = "Strong"
    else:
        badge = "Excellent"

    return total, subscores, badge


def _apply_tightest(current: int | None, candidate: int) -> int:
    """Return the tighter (lower) of two cap values."""
    return candidate if current is None else min(current, candidate)


def analyze_free(resume_text: str, jd_text: str) -> dict:
    """Return free-tier analysis: score, verdict, roast, subscores, badge,
    role_match, and must_have_coverage."""
    prompt = FREE_USER_TEMPLATE.format(resume=resume_text, jd=jd_text)
    raw = _call_gemini(
        call_name="analyze_free",
        system=_free_system(),
        prompt=prompt,
        max_output_tokens=700,
        temperature=0.2,
    )
    score, subscores, badge = _score_from_rubric(raw)
    return {
        "score":               score,
        "verdict":             str(raw.get("verdict", "")),
        "roast":               list(raw.get("roast", [])),
        "badge":               badge,
        "subscores":           subscores,
        "role_match":          str(raw.get("role_match", "")).strip().lower(),
        "must_have_coverage":  str(raw.get("must_have_coverage", "")).strip().lower(),
    }


# ---------------------------------------------------------------------------
# PAID tier – deep analysis
# ---------------------------------------------------------------------------

_PAID_SYSTEM_TEMPLATE = """You are ResumeRoast PRO, an elite career coach and technical recruiter.
Give actionable, specific, honest advice. Write in plain English.

Today's date is {today}. Do not call dates up to today 'in the future'.
Never comment on dates unless they are clearly after today.

Scoring context: most student/early-career resumes score 40-75 overall. Reserve
85+ only for exceptionally strong, well-targeted resumes. A mismatched role must
never be described in a celebratory or 'Strong' tone in your prose.

Respond with valid JSON only. No markdown, no explanation outside JSON."""


def _paid_system() -> str:
    return _PAID_SYSTEM_TEMPLATE.format(today=date.today().strftime("%d %B %Y"))


PAID_USER_TEMPLATE = """Resume:
<resume>
{resume}
</resume>

Job Description:
<jd>
{jd}
</jd>

Provide a comprehensive paid analysis. Return exactly this JSON schema (no other keys):
{{
  "bullet_rewrites": [
    {{"original": "<exact original bullet or line>", "improved": "<rewritten version with metrics/impact, max 30 words>"}},
    ... (cover the 5-8 weakest bullets)
  ],
  "missing_keywords": [
    "<keyword or phrase from the JD not found in resume>"
    ... (list 5-10 keywords)
  ],
  "cold_email": "<a ready-to-send concise cold email or LinkedIn DM, ~120 words, personalised to the JD>",
  "improved_resume_text": "<full improved resume as plain text, keeping original structure but with stronger language, max 800 words>"
}}"""


def analyze_paid(resume_text: str, jd_text: str) -> dict:
    """Return paid-tier analysis: bullet rewrites, keywords, email, improved text."""
    prompt = PAID_USER_TEMPLATE.format(resume=resume_text, jd=jd_text)
    return _call_gemini(
        call_name="analyze_paid",
        system=_paid_system(),
        prompt=prompt,
        max_output_tokens=2048,
    )


# ---------------------------------------------------------------------------
# Shared Gemini call helper
# ---------------------------------------------------------------------------

def _call_gemini(
    call_name: str,
    system: str,
    prompt: str,
    max_output_tokens: int,
    temperature: float | None = None,
) -> dict:
    """Call Gemini with JSON mode; retry once on bad JSON; surface quota errors nicely."""
    client = _get_client()
    config_kwargs: dict = dict(
        system_instruction=system,
        max_output_tokens=max_output_tokens,
        response_mime_type="application/json",
    )
    if temperature is not None:
        config_kwargs["temperature"] = temperature
    config = types.GenerateContentConfig(**config_kwargs)

    for attempt in range(2):  # attempt 0 = first try, attempt 1 = single retry
        try:
            resp = client.models.generate_content(
                model=_model(),
                contents=prompt,
                config=config,
            )
        except ClientError as exc:
            if _is_quota_error(exc):
                logger.warning("llm_quota_error call=%s exc=%s", call_name, exc)
                raise ValueError(_BUSY_MSG) from None
            logger.error("llm_api_error call=%s exc=%s", call_name, exc)
            raise ValueError(
                "Something went wrong with the AI service. Please try again."
            ) from None

        _log_usage(call_name, getattr(resp, "usage_metadata", None))
        raw = resp.text.strip() if resp.text else ""

        try:
            return _parse_json(raw, call_name)
        except ValueError:
            if attempt == 0:
                logger.warning(
                    "llm_json_retry call=%s attempt=%d raw=%r",
                    call_name,
                    attempt,
                    raw[:200],
                )
                continue  # retry once
            raise  # second failure → propagate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_json(raw: str, call_name: str) -> dict:
    """Extract and parse the first JSON object from the model response."""
    # Strip markdown code fences if present
    raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\n?```$", "", raw, flags=re.MULTILINE)
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("llm_json_parse_error call=%s raw=%r exc=%s", call_name, raw[:200], exc)
        raise ValueError("The AI returned an unexpected response. Please try again.")
