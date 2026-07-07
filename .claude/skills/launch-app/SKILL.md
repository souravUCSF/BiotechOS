---
name: launch-app
description: Launch and drive the BiotechOS app (FastAPI backend + Next.js frontend) to see a change working. Use when asked to run, start, or screenshot BiotechOS, or to confirm a change works in the real app.
---

# Launch BiotechOS

Two servers, two ports. Neither auto-reloads data — re-run the loader after
any schema/ingest change. Port 8000 is often occupied by an unrelated local
process on this machine; **use 8010** for the backend.

## 1. Start the backend (FastAPI)

```bash
cd /Users/Founder/BiotechOS/backend
uv run uvicorn biotechos.api.main:app --port 8010 > /tmp/uvicorn.log 2>&1 &
sleep 2
curl -s http://localhost:8010/healthz   # expect {"ok":true}
```

If the DB doesn't exist yet or you changed the schema/loader:

```bash
cd /Users/Founder/BiotechOS/backend
uv run python -m biotechos.ingest.table_loader   # ~20-30s, reads data/raw/*.csv.gz
uv run python -m biotechos.engine.tpp            # seeds default TPP + sanity recompute
```

## 2. Start the frontend (Next.js)

```bash
cd /Users/Founder/BiotechOS/frontend
npm run dev > /tmp/nextdev.log 2>&1 &
sleep 4
```

Frontend reads `NEXT_PUBLIC_API_BASE` from `frontend/.env.local`
(defaults to `http://localhost:8010`). Runs on `http://localhost:3000`.

## 3. Drive it — don't just launch it

Use Playwright (installed via `npx playwright install chromium` if needed)
to actually load pages and read rendered text/screenshot, not just curl:

```js
// /tmp/shot.mjs
import { chromium } from "playwright";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
await page.goto("http://localhost:3000/molecules", { waitUntil: "networkidle" });
await page.screenshot({ path: "/tmp/molecules.png" });
console.log(await page.innerText("body"));
await browser.close();
```

```bash
cd /tmp && node shot.mjs   # requires `npm install playwright` once in /tmp or a scratch dir
```

Then use the Read tool on the PNG to actually look at it — a blank frame
or an error boundary is a failure to launch, not a success.

## 4. Stop everything

```bash
pkill -f "uvicorn biotechos" 2>/dev/null
pkill -f "next dev" 2>/dev/null
```

## Known gotchas

- **Port 8000 collision**: something else on this machine listens on 8000
  (`irdmi` service). Always use 8010 for the API, and pass that through
  `NEXT_PUBLIC_API_BASE` if it ever changes.
- **CORS**: the API only allows `http://localhost:3000` by default
  (`biotechos/api/main.py`). If you change the frontend port, update
  `allow_origins` too.
- **Stale data**: `GET /state` reads whatever's in `data/biotechos.db`
  (gitignored). If molecules/TPP look wrong, re-run the loader — it fully
  resets the DB each time (`reset=True` default).
- **First run per machine**: `uv run` in `backend/` installs deps
  automatically from `uv.lock`; no manual `pip install` needed.
