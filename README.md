# ResumeRoast 🔥

> AI-powered resume roaster + career coach. Upload your resume + paste a JD → get a funny (but kind) score and actionable improvements.

**Hackathon project** – live traffic, sign-ups, conversions and payments judged.

---

## Features

| Tier | What you get | Price |
|------|-------------|-------|
| **Free** | Score /100, one-line verdict, top 3 roast points | Free |
| **Paid** | Line-by-line bullet rewrites, missing keywords, cold email/LinkedIn DM draft, improved resume text | ~~₹99~~ ₹30 |

---

## Stack

- **Backend**: Python + FastAPI, Uvicorn
- **Frontend**: Vanilla HTML/CSS/JS (no build step, mobile-first)
- **LLM**: Google Gemini (via `google-genai` SDK)
- **DB**: Render Postgres (`psycopg2`)
- **Payments**: Razorpay
- **Rate limiting**: slowapi / cachetools
- **Deploy**: Render Web Service (auto-deploy on push to `main`)

---

## Local Setup

```bash
# 1. Clone & create venv
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/Mac

# 2. Install deps
pip install -r requirements.txt

# 3. Copy env vars
cp .env.example .env
# Fill in your real keys in .env

# 4. Start the server
uvicorn main:app --reload --port 8000
```

Open http://localhost:8000

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | ✅ | Google Gemini API key |
| `LLM_MODEL` | optional | Model name (default: `gemini-2.0-flash-lite`) |
| `DATABASE_URL` | ✅ | Postgres connection string |
| `RAZORPAY_KEY_ID` | ✅ | Razorpay key ID |
| `RAZORPAY_KEY_SECRET` | ✅ | Razorpay key secret |
| `RAZORPAY_WEBHOOK_SECRET` | ✅ | Razorpay webhook secret |
| `ADMIN_TOKEN` | ✅ | Secret for `/admin/stats` |
| `POSTHOG_KEY` | optional | PostHog analytics key |
| `UNLOCK_PRICE_PAISE` | optional | Price in paise (default: 3000 = ₹30) |

---

## Render Deployment

**Start command:**
```
uvicorn main:app --host 0.0.0.0 --port $PORT
```

**Razorpay Webhook URL** (add in Razorpay dashboard):
```
https://your-app.onrender.com/webhook/razorpay
```
Events to subscribe: `payment.captured`

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Frontend |
| `POST` | `/analyze` | Upload PDF + JD → free score (rate-limited 10/min/IP) |
| `POST` | `/create-order` | Create Razorpay order for unlock |
| `POST` | `/verify-payment` | Verify payment after Razorpay checkout |
| `POST` | `/webhook/razorpay` | Razorpay server webhook |
| `GET` | `/result/{report_id}` | Fetch paid analysis (server-validates payment) |
| `GET` | `/admin/stats` | Admin stats (requires `X-Admin-Token` header) |

---

## Running Tests

```bash
python tests/smoke_test.py
```

---

## Limits & Safety

- PDF max **2 MB**; resume text max **8000 chars**; JD max **4000 chars**
- Rate limit: **10 requests / minute / IP** on `/analyze`
- Resumes and JDs are **never stored** on disk or in DB – memory only, 30-min TTL
- Paid analysis is **never returned before payment is confirmed server-side**
- Webhook signatures verified with HMAC-SHA256 (idempotent)
