# 🔥 ResumeRoast

**Get your resume roasted for free. Pay ₹30 to fix it.**

ResumeRoast is a web app for placement-season students in India. Upload a resume PDF and paste a job description (JD) to get an instant AI score and a funny-but-honest roast. For a one-time ₹30, unlock the full report: line-by-line bullet rewrites, missing keywords, a cold email/DM draft, and improved resume text.

- **Live app:** https://resumeroast-1e2c.onrender.com
- **Demo video:** https://www.boomshare.ai/shared/01M57H5WRQRR0YDC4J53AQA1NMl
- **Recognition:** Top 25 project at REVHACK 2026

## The problem

Students send resumes and hear nothing back, and nobody tells them why. Coaches charge hundreds of rupees, and free tools give generic advice that isn't tied to the job being applied for.

## How it works

|                  | Free                                                | Paid (₹30, one-time)                                                                   |
|------------------|-----------------------------------------------------|----------------------------------------------------------------------------------------|
| **What you get** | Score /100, badge, one-line verdict, 3 roast points | Bullet rewrites, missing keywords vs the JD, cold email/DM draft, improved resume text |
| **Purpose**      | Hook and shareable result                           | Revenue                                                                                |

**Money logic**

- **Paywall:** score and roast are free. The paid report is only released by the server after payment is confirmed in the database. Paid fields are never sent to the browser before that.
- **Pricing:** ₹30, shown as ~~₹99~~ ₹30 launch price. An impulse-buy price for a student. Configurable with `UNLOCK_PRICE_PAISE`.
- **Model:** one-time purchase. Students apply in bursts, so a subscription doesn't fit.
- **Price test:** after the first batch of buyers, test ₹49 and compare conversion.

## Architecture

```
Browser → POST /analyze → extract PDF text → cache check (hash of resume + JD)
        → Gemini (rubric JSON) → Python scoring + caps → save to Postgres
        → Gemini (paid report, prefetched) → held in memory (30 min) → free result returned

Unlock  → POST /create-order → Razorpay Checkout → POST /verify-payment (HMAC)
        + POST /webhook/razorpay (HMAC, backup) → mark paid in Postgres
        → GET /result/{report_id} → paid report served from memory
```

1. **Extraction:** the server extracts the text layer from the PDF with PyMuPDF. The PDF itself is never stored.
2. **Scoring:** Gemini rates five categories (keyword match, role fit, impact, clarity, completeness) and classifies role match and must-have coverage. **The final score is calculated in Python** with hard caps, so the model can't inflate it (see [Scoring](#scoring)).
3. **Caching:** free results are cached for 1 hour by a SHA-256 hash of the resume text plus the JD, to avoid repeat LLM calls.
4. **Paid report generation:** right after the free analysis, a second Gemini call generates the paid report (bullet rewrites, keywords, cold email, improved resume). The result is held **in server memory for 30 minutes** under the report ID. It is only returned by `/result/{report_id}` once the database confirms payment. The resume text itself is not kept after the request.
5. **Payments:** Razorpay Orders and Checkout. The server verifies the payment signature (HMAC-SHA256) and also handles the `payment.captured` webhook as a backup. Marking a report as paid is idempotent: one atomic SQL update that only changes rows where `paid` is still false.
6. **Analytics:** server-side events are logged to Postgres, and a token-protected `/admin/stats` endpoint reports counts per event and the number of paid reports.

## Scoring

Gemini returns sub-scores and two classifications as JSON. Python turns them into the final score.

| Dimension         | Max |
|-------------------|-----|
| Keyword match     | 30  |
| Role fit          | 25  |
| Impact            | 20  |
| Clarity           | 15  |
| Completeness      | 10  |
| **Total**         | 100 |

**Caps (the tightest cap wins):**

- Role fit below 12 → total capped at 65. Keyword match below 12 → total capped at 60.
- Role match `different` → capped at 55. `adjacent` → capped at 72.
- Must-have coverage `low` → capped at 55. `medium` → capped at 78.

**Badges:** below 40 *Needs work*, below 60 *Getting there*, below 80 *Strong*, 80 and above *Excellent*.

Every score is logged with all of its inputs (`score_debug`), so any result can be traced.

## API endpoints

| Method | Path                | Purpose                                                              |
|--------|---------------------|----------------------------------------------------------------------|
| GET    | `/`                 | Serves the app and logs a `page_view` event (with `?src=`)           |
| GET    | `/health`           | Liveness probe with a non-fatal database check                       |
| POST   | `/analyze`          | Free analysis (PDF + JD). Rate limited to 10 per minute per IP       |
| POST   | `/create-order`     | Creates a Razorpay order for a report                                |
| POST   | `/verify-payment`   | Verifies the checkout signature and marks the report paid            |
| POST   | `/webhook/razorpay` | Razorpay webhook (signature verified over the raw body), idempotent  |
| GET    | `/result/{id}`      | Returns the paid report if payment is confirmed (403 if not paid)    |
| GET    | `/admin/stats`      | Counts and events, protected by the `X-Admin-Token` header           |
| GET    | `/terms`, `/privacy`, `/refund`, `/contact` | Legal and contact pages                              |

## Tech stack

- **Backend:** Python, FastAPI, PyMuPDF (PDF text extraction), slowapi (rate limiting), cachetools (TTL caches)
- **Frontend:** vanilla HTML, CSS and JavaScript (no build step), mobile-first
- **AI:** Google Gemini (`google-genai` SDK), model set by `LLM_MODEL` (code default: `gemini-2.0-flash-lite`)
- **Database:** PostgreSQL via psycopg2 (Render Postgres)
- **Payments:** Razorpay
- **Hosting:** Render Web Service plus Render Postgres

## Database

Two tables, created automatically on startup:

- `reports`: `report_id`, `created_at`, `score`, `verdict`, `roast`, `paid`, `order_id`, `payment_id`
- `events`: `id`, `ts`, `event`, `report_id`, `ip`, `meta`

Events logged: `page_view`, `resume_uploaded`, `score_generated`, `unlock_clicked`, `payment_success`. Resume text and JD text are never written to either table.

## Use of Render

The app runs as a **Render Web Service** with a **Render Postgres** database, auto-deployed from this repo on every push to `main`. The analysis pipeline (extract, score, paid-report generation) is implemented as step functions inside the web service. **Render Workflows are not used in this version.**

## Project structure

```
main.py          # FastAPI routes, error handlers, rate limiter
llm.py           # Gemini calls, prompts, rubric scoring with caps
pdf_utils.py     # PDF text extraction and limits
pipeline.py      # orchestration, hash cache, short-lived in-memory store
db.py            # Postgres tables, payment state, event logging
payments.py      # Razorpay orders and signature verification
static/          # index.html, app.js, style.css, legal pages
tests/           # smoke tests
```

## Environment variables

Set these in a local `.env` (never committed) and in Render's Environment tab:

| Name                      | Purpose                                                          |
|---------------------------|------------------------------------------------------------------|
| `GEMINI_API_KEY`          | Google Gemini API key                                            |
| `LLM_MODEL`               | Gemini model name (falls back to `gemini-2.0-flash-lite`)        |
| `DATABASE_URL`            | Postgres connection URL                                          |
| `RAZORPAY_KEY_ID`         | Razorpay Key ID (also sent to the browser to open Checkout)      |
| `RAZORPAY_KEY_SECRET`     | Razorpay Key Secret (server only, verifies payment signatures)   |
| `RAZORPAY_WEBHOOK_SECRET` | Separate secret used to verify Razorpay webhooks                 |
| `UNLOCK_PRICE_PAISE`      | Price in paise (`3000` = ₹30)                                    |
| `ADMIN_TOKEN`             | Token for `/admin/stats`                                         |
| `CONTACT_EMAIL`           | Email shown on the Contact page                                  |
| `PYTHON_VERSION`          | Python version for Render (`3.12.3`)                             |

## Run locally

```
python -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
# create a .env file with the variables above
uvicorn main:app --reload --port 8000
```

Open `http://localhost:8000`. The app starts without a database, but events and payment status won't be saved, and unlocking a report requires the database. Use Razorpay **test keys** locally and live keys only in production.

Run the tests with `python tests/smoke_test.py`.

## Security

- Secrets live in environment variables only.
- Payment signatures are verified server-side with HMAC-SHA256 and a constant-time comparison. Missing secrets make verification fail closed.
- Webhooks are verified over the raw request body with a separate secret.
- All SQL uses parameterised queries.
- User-facing text (file names, AI output) is escaped before it is rendered.
- Input limits: 2 MB PDF, 8,000 resume characters, 4,000 JD characters.
- Report IDs are random UUIDs.

## Privacy

- Resumes and job descriptions are **not stored** in the database or on disk.
- The resume text is processed in memory during the request and is not kept afterwards.
- Generated results are held **in server memory**: the free result for up to 1 hour and the paid report for up to 30 minutes. They are lost on restart.
- Resume and JD text are sent to Google Gemini to generate results (twice per analysis: free and paid).
- We store anonymous usage events, the score and roast, and payment status. Card and UPI details are handled by Razorpay and never reach our server.

## Cost controls

PDF limit 2 MB, resume text capped at 8,000 characters, JD at 4,000, per-IP rate limiting on `/analyze`, result caching by content hash, and token-usage logging for every LLM call (`llm_token_usage`). Because the paid report is generated for every new analysis (so unlocking is instant), cost per visitor is higher than cost per buyer. Cost per analysis can be calculated from the token logs.

## Known limitations

- Scanned or image-only PDFs aren't supported (no OCR).
- Two-column or heavily designed templates can break text extraction and reduce feedback quality.
- The score is an **AI estimate, not a real ATS result**, and a small model can vary between runs.
- AI-written rewrites can contain mistakes or invented details, so users must verify every line.
- **The paid report must be opened within 30 minutes of the analysis.** After that, or after a server restart, it can no longer be retrieved and the user has to re-upload. A payment made after that window needs a refund or re-analysis through support.
- Caches and rate limits live in process memory, so they are per instance and reset on restart. The app is designed to run as a single instance.
- LLM provider rate limits can slow or block requests under heavy traffic.
- The AI sees only extracted text, so it can't judge visual formatting.
- Analytics are custom server-side events rather than a third-party tool.

## What's next

- Store the generated paid report safely (with an expiry) so a late payment never loses it
- Redis for shared caches and rate limits, plus a connection pool and async handling for LLM and database calls
- Bind each payment to its report on verification and check the paid amount
- OCR for scanned resumes
- Role-specific scoring (service company vs startup)
- Render Workflows for the pipeline
- Partnerships with college placement cells

## Contact

karlinfrancis@gmail.com
