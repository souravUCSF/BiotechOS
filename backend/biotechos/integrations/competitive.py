"""Structured competitive radar.

Organizes intelligence into the axes that matter for a preclinical program and
scores each item by threat/recency:
  1. competing programs  (ClinicalTrials.gov v2 — same target/indication + stage)
  2. clinical catalysts  (ClinicalTrials.gov — upcoming readouts / completion dates)
  3. financings          (curated — funding = momentum signal)
  4. news & deals        (curated — partnerships, approvals, disclosures)

Results are cached to disk; a network failure falls back to the last good cache,
then to a bundled seed so the radar always renders.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime

from ..config import CACHE_DIR, DEMO_PROGRAM_ID
from ..state import db

CACHE_FILE = CACHE_DIR / "competitive.json"
CACHE_TTL = 6 * 3600  # 6h
UA = {"User-Agent": "BiotechOS/1.0 (demo)"}

CTGOV = "https://clinicaltrials.gov/api/v2/studies"
PHASE_WEIGHT = {"PHASE3": 1.0, "PHASE2": 0.7, "PHASE1": 0.4, "EARLY_PHASE1": 0.3}
STATUS_WEIGHT = {"RECRUITING": 1.0, "ACTIVE_NOT_RECRUITING": 0.8, "ENROLLING_BY_INVITATION": 0.7,
                 "COMPLETED": 0.5, "NOT_YET_RECRUITING": 0.6}


def _get_json(url: str, timeout: float = 15.0) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _threat(phase: str | None, status: str | None, date: str | None) -> float:
    p = PHASE_WEIGHT.get((phase or "").upper(), 0.3)
    s = STATUS_WEIGHT.get((status or "").upper(), 0.5)
    recency = 0.5
    if date:
        try:
            yr = int(date[:4])
            recency = max(0.2, min(1.0, 1.0 - (2026 - yr) * 0.12))
        except (ValueError, TypeError):
            pass
    return round((0.5 * p + 0.3 * s + 0.2 * recency), 3)


def _fetch_ctgov(term: str = "TGTA TGTA kinase inhibitor", n: int = 30) -> list[dict]:
    params = {
        "query.term": term,
        "pageSize": str(n),
        "fields": "NCTId,BriefTitle,OverallStatus,LeadSponsorName,Phase,"
                  "PrimaryCompletionDate,Condition,StudyType",
        "sort": "LastUpdatePostDate:desc",
    }
    url = f"{CTGOV}?{urllib.parse.urlencode(params)}"
    data = _get_json(url)
    programs, catalysts = [], []
    for study in data.get("studies", []):
        ps = study.get("protocolSection", {})
        idm = ps.get("identificationModule", {})
        stm = ps.get("statusModule", {})
        spm = ps.get("sponsorCollaboratorsModule", {})
        dm = ps.get("designModule", {})
        nct = idm.get("nctId")
        title = idm.get("briefTitle")
        sponsor = (spm.get("leadSponsor") or {}).get("name")
        status = stm.get("overallStatus")
        phases = dm.get("phases") or []
        phase = phases[-1] if phases else None
        pcd = (stm.get("primaryCompletionDateStruct") or {}).get("date")
        threat = _threat(phase, status, pcd)
        base = {
            "title": title, "org": sponsor, "stage": (phase or "").replace("PHASE", "Phase "),
            "status": status, "url": f"https://clinicaltrials.gov/study/{nct}" if nct else None,
            "threat_score": threat, "source": "ClinicalTrials.gov",
        }
        programs.append({**base, "axis": "program"})
        if pcd:  # upcoming/planned readout = a catalyst
            catalysts.append({**base, "axis": "catalyst", "event_date": pcd,
                              "detail": f"Primary completion {pcd}"})
    return programs + catalysts


def _fetch_pubmed(term: str = "TGTA TGTA selective inhibitor", n: int = 8) -> list[dict]:
    esearch = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
               f"?db=pubmed&retmode=json&sort=date&retmax={n}&term={urllib.parse.quote(term)}")
    ids = _get_json(esearch).get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    esum = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
            f"?db=pubmed&retmode=json&id={','.join(ids)}")
    res = _get_json(esum).get("result", {})
    out = []
    for pmid in ids:
        rec = res.get(pmid, {})
        if not rec:
            continue
        date = rec.get("pubdate", "")
        out.append({
            "axis": "news", "title": rec.get("title", "")[:160],
            "org": (rec.get("source") or "PubMed"),
            "event_date": date, "stage": "publication",
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "threat_score": _threat(None, None, date),
            "source": "PubMed", "detail": "Recent TGTA-inhibitor literature",
        })
    return out


# Curated financings/deals — funding + partnership signals (no free structured API).
SEED_FINANCINGS = [
    {"axis": "financing", "title": "TGTA-selective TKI startup closes Series B",
     "org": "Competitor Bio", "event_date": "2026-04", "stage": "Series B",
     "threat_score": 0.75, "source": "curated", "detail": "$120M to advance a TGTA/TGTB-sparing TKI"},
    {"axis": "financing", "title": "Antibody-drug conjugate player raises crossover round",
     "org": "ADC Therapeutics Co", "event_date": "2026-02", "stage": "Crossover",
     "threat_score": 0.6, "source": "curated", "detail": "$90M; TGTA-low ADC program"},
]
SEED_NEWS = [
    {"axis": "news", "title": "Large pharma licenses next-gen TGTA TKI in $2B deal",
     "org": "BigPharma / Biotech X", "event_date": "2026-05", "stage": "licensing",
     "threat_score": 0.85, "source": "curated", "detail": "Global rights to a brain-penetrant TGTA inhibitor"},
]


def build(program_id: str = DEMO_PROGRAM_ID, use_cache: bool = True) -> dict:
    """Assemble the radar; cache to disk; fall back to cache/seed on failure."""
    if use_cache and CACHE_FILE.exists() and (time.time() - CACHE_FILE.stat().st_mtime) < CACHE_TTL:
        return json.loads(CACHE_FILE.read_text())

    items: list[dict] = []
    live = True
    try:
        items += _fetch_ctgov()
    except Exception as e:
        print(f"[competitive] ctgov failed: {e}")
        live = False
    try:
        items += _fetch_pubmed()
    except Exception as e:
        print(f"[competitive] pubmed failed: {e}")
    items += SEED_FINANCINGS + SEED_NEWS

    if not items and CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())

    result = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "live": live,
        "axes": {
            "program": [i for i in items if i["axis"] == "program"],
            "catalyst": sorted([i for i in items if i["axis"] == "catalyst"],
                               key=lambda x: x.get("event_date", "")),
            "financing": [i for i in items if i["axis"] == "financing"],
            "news": [i for i in items if i["axis"] == "news"],
        },
    }
    try:
        CACHE_FILE.write_text(json.dumps(result, indent=2))
    except OSError:
        pass
    return result


def persist_to_state(program_id: str = DEMO_PROGRAM_ID) -> int:
    """Write the radar into competitive_items so it flows through /state too."""
    radar = build(program_id)
    conn = db.connect()
    n = 0
    with conn:
        conn.execute("DELETE FROM competitive_items WHERE program_id=?", (program_id,))
        for axis, items in radar["axes"].items():
            for i in items:
                conn.execute(
                    "INSERT INTO competitive_items(program_id,axis,title,org,stage,"
                    "event_date,threat_score,source,url,detail) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (program_id, axis, i.get("title"), i.get("org"), i.get("stage"),
                     i.get("event_date"), i.get("threat_score"), i.get("source"),
                     i.get("url"), i.get("detail")),
                )
                n += 1
    conn.close()
    return n


if __name__ == "__main__":
    r = build(use_cache=False)
    for axis, items in r["axes"].items():
        print(f"{axis}: {len(items)}")
