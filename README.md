# Invoice Chaser
Claude (via MCP) creates invoices; this app hosts, edits, tracks views and chases payment. **No AI keys or AI calls anywhere.**

## Run locally
    pip install -r requirements.txt
    uvicorn app:app --reload

## Deploy (Render, free tier)
1. Push this folder to GitHub. New → Web Service → connect repo.
2. Build: `pip install -r requirements.txt`  Start: `uvicorn app:app --host 0.0.0.0 --port $PORT`
3. Env vars: `SECRET` (random string), `CRON_KEY` (random string), `BASE_URL` (your public URL, no trailing slash).
   Optional: `RESEND_API_KEY`, `MAIL_FROM` for reminder emails.
4. Persistence: add a Render Disk mounted at `/data` and set `DB_PATH=/data/invoices.db` (otherwise data resets on redeploy).
5. Reminders: schedule a daily POST to `https://YOUR_URL/cron/remind?key=CRON_KEY` (cron-job.org is free).

## Connect to Claude
1. Open the live app, log in (test: `demo@invoicechaser.app` / `demo1234`).
2. Copy the MCP URL shown on the dashboard (`https://YOUR_URL/mcp/<token>`).
3. Claude → Settings → Connectors → Add custom connector → paste URL.
4. Ask: "Invoice Acme Corp for 40 hours of design at ₹2,000/hour, due in 15 days."
5. Refresh the dashboard, open the invoice, edit it, and open the client link.
