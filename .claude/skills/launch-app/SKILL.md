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

## Driving the demo

The full closed loop lives on the **Inbox** (`/`). To run/record it:
1. `POST /demo/reset` (or the "Reset demo" button) re-stages the inbox: two
   biology-CRO items (lead-candidate flip + re-derivation QC catch), a chem
   update, and a vendor quote.
2. Approve the **lead-candidate** item → one molecule crosses to MEETS TPP
   (visible on `/tpp` and `/molecules`), a go/no-go memo drafts, Decision Log
   (`/ledger`) appends.
3. The **QC catch** item shows the reported-vs-refit dose-response overlay.
4. Approve the **vendor quote** → PO issues + vendor email draft + budget
   commitment (`/cfo`); the matching invoice then appears — reconcile it to
   release funds. All approvals land in the Decision Log.

`/competitive` fetches live from ClinicalTrials.gov + PubMed (needs network);
it caches to `data/cache/competitive.json` and falls back to cache/seed offline.

## Deferred (wired behind interfaces)

- **Boltz co-folds**: `engine/structure.py:enqueue_fold` is a no-op until
  `boltz-api` is authenticated (`boltz-cli-setup`). Until then the 3D viewer
  serves the real TGTA reference structure (`data/reference/placeholder_ref.pdb`).
- **LLM features** (TPP Builder, memos, vendor email): use the real model when
  `ANTHROPIC_API_KEY` is set, else a deterministic fallback — the demo runs keyless.
- **Vendor email**: composed + shown as a draft; not sent.

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
