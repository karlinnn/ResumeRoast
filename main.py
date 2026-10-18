"""FastAPI application – all routes."""
import json
import logging
import os
from contextlib import asynccontextmanager

# Load .env in local dev (no-op when env vars already set, e.g. on Render)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

import db
import payments
import pipeline

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiter (slowapi)
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        db.init_db()
    except Exception as exc:
        logger.warning("db_init_skipped exc=%s", exc)
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="ResumeRoast", lifespan=lifespan)
app.state.limiter = limiter

app.mount("/static", StaticFiles(directory="static"), name="static")


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"error": "Too many requests. Please wait a minute and try again."},
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    logger.exception("unhandled_error path=%s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "Something went wrong on our end. Please try again."},
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    return forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Lightweight liveness probe – always returns 200.

    Includes a non-fatal DB connectivity check so monitors can see DB state
    without the endpoint itself failing when DB is unavailable.
    """
    db_ok = False
    try:
        conn = db._get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        db_ok = True
    except Exception as exc:
        logger.warning("health_db_unavailable exc=%s", exc)

    return JSONResponse(
        status_code=200,
        content={"status": "ok", "db": "ok" if db_ok else "unavailable"},
    )


@app.get("/")
async def index(request: Request, src: str | None = None):
    db.log_event("page_view", None, _ip(request), {"src": src})
    return FileResponse("static/index.html")


@app.get("/terms")
async def terms():
    return FileResponse("static/terms.html")


@app.get("/privacy")
async def privacy():
    return FileResponse("static/privacy.html")


@app.get("/refund")
async def refund():
    return FileResponse("static/refund.html")


@app.get("/contact")
async def contact():
    contact_email = os.environ.get("CONTACT_EMAIL", "karlinfrancis@gmail.com")
    with open("static/contact.html", encoding="utf-8") as f:
        html = f.read()
    html = html.replace("{contact_email}", contact_email)
    return HTMLResponse(content=html)


@app.post("/analyze")
@limiter.limit("10/minute")
async def analyze(
    request: Request,
    resume: UploadFile = File(...),
    jd: str = Form(...),
):
    ip = _ip(request)
    db.log_event("resume_uploaded", None, ip, {"filename": resume.filename})

    # Read PDF bytes
    pdf_bytes = await resume.read()

    try:
        result = pipeline.run_free_analysis(pdf_bytes, jd)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    db.log_event("score_generated", result["report_id"], ip, {"score": result["score"]})

    return JSONResponse(content=result)


@app.post("/create-order")
async def create_order(request: Request):
    body = await request.json()
    report_id = body.get("report_id", "")
    if not report_id:
        raise HTTPException(status_code=400, detail="report_id is required.")

    # Verify report exists
    report = db.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")

    if report.get("paid"):
        # Already paid – return existing order info so client can skip checkout
        return JSONResponse(content={"already_paid": True})

    try:
        order_info = payments.create_order(report_id)
    except Exception as exc:
        logger.error("create_order_error report_id=%s exc=%s", report_id, exc)
        raise HTTPException(status_code=500, detail="Could not create payment order. Please try again.")

    db.save_order(report_id, order_info["order_id"])
    db.log_event("unlock_clicked", report_id, _ip(request))

    return JSONResponse(content=order_info)


@app.post("/verify-payment")
async def verify_payment(request: Request):
    """Called by the frontend after Razorpay checkout succeeds."""
    body = await request.json()
    order_id = body.get("razorpay_order_id", "")
    payment_id = body.get("razorpay_payment_id", "")
    signature = body.get("razorpay_signature", "")
    report_id = body.get("report_id", "")

    if not all([order_id, payment_id, signature, report_id]):
        raise HTTPException(status_code=400, detail="Missing payment fields.")

    if not payments.verify_payment_signature(order_id, payment_id, signature):
        logger.warning("payment_sig_invalid report_id=%s payment_id=%s", report_id, payment_id)
        raise HTTPException(status_code=400, detail="Payment verification failed.")

    first_time = db.mark_paid(report_id, payment_id)
    if first_time:
        db.log_event("payment_success", report_id, _ip(request), {"payment_id": payment_id})
        logger.info("payment_verified_ok report_id=%s payment_id=%s", report_id, payment_id)

    return JSONResponse(content={"status": "ok"})


@app.post("/webhook/razorpay")
async def razorpay_webhook(request: Request):
    """Razorpay server-side webhook – secondary confirmation."""
    body = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")

    if not payments.verify_webhook_signature(body, signature):
        logger.warning("webhook_sig_invalid")
        raise HTTPException(status_code=400, detail="Invalid webhook signature.")

    event = json.loads(body)
    event_name = event.get("event", "")

    if event_name == "payment.captured":
        payment_entity = event.get("payload", {}).get("payment", {}).get("entity", {})
        payment_id = payment_entity.get("id", "")
        notes = payment_entity.get("notes", {})
        report_id = notes.get("report_id", "")

        if report_id and payment_id:
            first_time = db.mark_paid(report_id, payment_id)
            logger.info(
                "webhook_payment_captured report_id=%s payment_id=%s first_time=%s",
                report_id, payment_id, first_time,
            )

    return JSONResponse(content={"status": "ok"})


@app.get("/result/{report_id}")
async def get_paid_result(report_id: str, request: Request):
    """Return paid analysis. Only works after payment is confirmed server-side."""
    try:
        data = pipeline.get_paid_analysis(report_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return JSONResponse(content=data)


# ---------------------------------------------------------------------------
# Admin – basic stats (token protected)
# ---------------------------------------------------------------------------
@app.get("/admin/stats")
async def admin_stats(request: Request, x_admin_token: str | None = Header(default=None)):
    expected = os.environ.get("ADMIN_TOKEN", "")
    if not expected or x_admin_token != expected:
        raise HTTPException(status_code=403, detail="Forbidden.")
    try:
        conn = db._get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total_reports FROM reports;")
            reports = cur.fetchone()
            cur.execute("SELECT COUNT(*) AS paid_reports FROM reports WHERE paid = TRUE;")
            paid = cur.fetchone()
            cur.execute("SELECT event, COUNT(*) AS cnt FROM events GROUP BY event ORDER BY cnt DESC;")
            events = cur.fetchall()
        return JSONResponse(content={
            "total_reports": reports["total_reports"],
            "paid_reports": paid["paid_reports"],
            "events": [dict(r) for r in events],
        })
    except Exception as exc:
        logger.error("admin_stats_error exc=%s", exc)
        raise HTTPException(status_code=500, detail="DB error.")