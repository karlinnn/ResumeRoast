# 🔥 ResumeRoast

**Get your resume roasted for free. Pay ₹30 to fix it.**

ResumeRoast is a web app for placement-season students in India. Upload a resume PDF and paste a job description to get an instant AI score and a funny-but-honest roast. For a one-time ₹30, unlock the full report: line-by-line bullet rewrites, missing keywords, a cold email/DM draft, and improved resume text.

- **Live app:** https://resumeroast-1e2c.onrender.com
- **Demo video:** https://www.boomshare.ai/shared/01M57H5WRQRR0YDC4J53AQA1NMl

## The problem

Students send resumes and hear nothing back, and nobody tells them why. Coaches charge hundreds of rupees, and free tools give generic advice that isn't tied to the job being applied for.

## How it works

| | Free | Paid (₹30, one-time) |
|---|---|---|
| **What you get** | Score /100, badge, one-line verdict, 3 roast points | Bullet rewrites, missing keywords vs the JD, cold email/DM draft, improved resume text |
| **Purpose** | Hook and shareable result | Revenue |

**Money logic**
- **Paywall:** score and roast are free. The full report is generated only after payment is confirmed server-side.
- **Pricing:** ₹30, shown as ~~₹99~~ ₹30 launch price. An impulse-buy price for a student.
- **Model:** one-time purchase. Students apply in bursts, so a subscription doesn't fit.
- **Price test:** after the first batch of buyers, test ₹49 and compare conversion.

## Architecture

```
Browser → POST /analyze → extract PDF text → cache check → Gemini (rubric JSON)
        → Python scoring + caps → free result
Unlock  → POST /create-order → Razorpay Checkout → POST /verify-payment
        (+ Razorpay webhook as backup) → mark paid → second Gemini call → full report
```

1. **Extraction:** the server extracts the text layer from the PDF. The PDF itself is never stored.
2. **Scoring:** Gemini rates five categories (keyword match, role fit, impact, clarity, completeness) and classifies role match and must-have coverage. **The final score is calculated in Python**, with hard caps (for example, a different role family caps the total at 55), so the model can't inflate it.
3. **Caching:** results are cached by a hash of the resume text plus the JD, to avoid repeat LLM calls.
4. **Payments:** Razorpay Orders and Checkout. The server verifies the payment signature (HMAC-SHA256) and also handles the `payment.captured` webhook, which is idempotent. Paid fields are never sent to the browser before payment is confirmed.
5. **Paid report:** a second Gemini call, run only after payment, using the resume text held in memory.
6. **Analytics:** server-side events are logged to Postgres, and a token-protected `/admin/stats` endpoint reports counts and conversion by traffic source.

## Tech stack

- **Backend:** Python, FastAPI, PyMuPDF (PDF text extraction)
- **Frontend:** vanilla HTML, CSS and JavaScript (no build step), mobile-first
- **AI:** Google Gemini (`google-genai` SDK), model set by `LLM_MODEL`
- **Database:** Render Postgres
- **Payments:** Razorpay
- **Hosting:** Render Web Service plus Render Postgres

## Use of Render

The app runs as a **Render Web Service** with a **Render Postgres** database, auto-deployed from this repo on every push to `main`. The analysis pipeline (extract, score, post-payment generation) is implemented as separate step functions inside the web service. **Render Workflows are not used in this version.**

## Project structure

```
main.py          # FastAPI routes
llm.py           # Gemini calls, prompts, rubric scoring
pdf_utils.py     # PDF text extraction and limits
pipeline.py      # orchestration, caching, short-lived in-memory store
db.py            # Postgres tables and event logging
payments.py      # Razorpay orders and signature verification
static/          # index.html, app.js, style.css, legal pages
tests/           # smoke tests
```

## Environment variables

Set these in a local `.env` (never committed) and in Render's Environment tab:

| Name | Purpose |
|---|---|
| `GEMINI_API_KEY` | Google Gemini API key |
| `LLM_MODEL` | Gemini model name (for example `gemini-3.1-flash-lite`) |
| `DATABASE_URL` | Postgres connection URL |
| `RAZORPAY_KEY_ID` | Razorpay Key ID |
| `RAZORPAY_KEY_SECRET` | Razorpay Key Secret (server only) |
| `RAZORPAY_WEBHOOK_SECRET` | Secret used to verify Razorpay webhooks |
| `UNLOCK_PRICE_PAISE` | Price in paise (`3000` = ₹30) |
| `ADMIN_TOKEN` | Token for `/admin/stats` |
| `CONTACT_EMAIL` | Email shown on the Contact page |
| `PYTHON_VERSION` | Python version for Render (`3.12.3`) |

## Run locally

```bash
python -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
# create a .env file with the variables above
uvicorn main:app --reload --port 8000
```

Open `http://localhost:8000`. The app starts without a database, but events and payment status won't be saved. Use Razorpay **test keys** locally and live keys only in production.

Run the tests with `python tests/smoke_test.py`.

## Privacy

- Resumes and job descriptions are **not stored** in the database or on disk.
- Resume text is held **in memory for up to 30 minutes** so a paid report can be generated after payment.
- The text is sent to Google Gemini to generate results.
- We store anonymous usage events and payment status. Card and UPI details are handled by Razorpay.

## Cost controls

PDF limit 2 MB, resume text capped at 8,000 characters, JD at 4,000, per-IP rate limiting, result caching, and token-usage logging per call. Measured cost per paid report: **[₹X]**.

## Known limitations

- Scanned or image-only PDFs aren't supported (no OCR).
- Two-column or heavily designed templates can break text extraction and reduce feedback quality.
- The score is an **AI estimate, not a real ATS result**, and a small model can vary between runs.
- AI-written rewrites can contain mistakes or invented details, so users must verify every line.
- In-memory data is lost on server restart or after 30 minutes, so users may need to re-upload.
- LLM provider rate limits can slow or block requests under heavy traffic.
- The AI sees only extracted text, so it can't judge visual formatting.
- No Render Workflows, and analytics are custom server-side events rather than a third-party tool.

## What's next

OCR for scanned resumes, role-specific scoring (service company vs startup), Render Workflows for the pipeline, and partnerships with college placement cells.

## Contact
karlinfrancis@gmail.com
