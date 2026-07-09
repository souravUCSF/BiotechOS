"""Standalone Evals editor website — served at /evals/ by the main API.

A self-contained page (no build step) to view/edit/add/delete eval cases across
all suites and run them with a live scorecard.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import runner

router = APIRouter(prefix="/evals")
_UI = Path(__file__).with_name("ui.html")


@router.get("/", response_class=HTMLResponse)
def ui():
    return _UI.read_text()


@router.get("/api/suites")
def suites():
    return [{"name": s, "count": len(runner.load_suite(s))} for s in runner.SUITES]


@router.get("/api/cases/{suite}")
def cases(suite: str):
    if suite not in runner.SUITES:
        raise HTTPException(404, f"unknown suite {suite}")
    return runner.load_suite(suite)


@router.put("/api/cases/{suite}")
def save_cases(suite: str, cases: list[dict]):
    if suite not in runner.SUITES:
        raise HTTPException(404, f"unknown suite {suite}")
    try:
        n = runner.save_suite(suite, cases)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"saved": n}


class RunReq(BaseModel):
    suites: list[str] | None = None
    repeat: int = 1


@router.post("/api/run")
def run(req: RunReq):
    return runner.run(req.suites, repeat=req.repeat)
