"""Quote extractor (processor).

Reads a vendor quote in ANY format — inline prose, a per-compound × per-scale
matrix, a multi-line table, tiered pricing — and returns a fixed set of line
items. The output schema is rigid; the input format is not, so we never lock onto
one layout the way a regex parser does.

Trust is enforced deterministically, not by a second model:
  * Span grounding — the model must return the exact `source_span` it read each
    line from. We then check, in code, that the span is really in the document and
    contains the amount. This turns verification into free string-matching and is
    the primary defense against invented prices and numbers stapled to the wrong
    context. An amount absent from the source is DROPPED; weaker failures (span not
    found, field not in source) KEEP the line but mark it `flagged` for review.
  * Deterministic fallback — with no API key (or on error) the caller falls back
    to the regex line parser, so ingest still runs offline.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ...config import MODEL_EXTRACT_DEEP
from .. import llm


class QuoteLine(BaseModel):
    service: str = Field(description="the assay/service/deliverable this price is for. PRESERVE the "
                         "specific method or platform name when stated — e.g. 'ADP-Glo assay', "
                         "'HTRF binding assay', 'Caco-2 permeability', 'jump-dilution residence time', "
                         "'compound synthesis' — not a generic summary like 'assay development'.")
    amount: float = Field(description="the numeric price; MUST appear verbatim in the source")
    currency: str = "USD"
    compound: str | None = Field(default=None, description="compound/sample code if the line names one")
    quantity: float | None = Field(default=None, description="numeric quantity, e.g. 10")
    unit: str | None = Field(default=None, description="unit of the quantity: mg, g, mL, plate, target…")
    turnaround_days_min: int | None = Field(default=None, description="lead time low bound in days ('2-3 weeks' → 14)")
    turnaround_days_max: int | None = Field(default=None, description="lead time high bound in days ('2-3 weeks' → 21)")
    conditions: str | None = Field(default=None, description="validity window, discount, shipping-excluded, etc.")
    source_span: str = Field(default="", description="the EXACT verbatim substring from the quote this "
                             "line was read from — must include the price. Copy it character-for-character; "
                             "do not paraphrase. This is checked against the source.")


class QuoteExtraction(BaseModel):
    vendor: str | None = None
    lines: list[QuoteLine] = []


_SYS = (
    "You extract EVERY priced line item from ONE vendor quote for a biotech/CRO service. "
    "A quote lists prices for services/compounds at various quantities and turnarounds; the "
    "layout varies (prose, a table, a compound×scale matrix, tiered pricing). Return one "
    "QuoteLine per distinct price. Rules: (1) amount MUST be a number that appears verbatim in "
    "the text — never infer, round, or sum. (2) Keep distinct line items separate even at the "
    "same price (e.g. 10 mg vs 50 mg both $2,200). (3) Normalize turnaround to DAYS "
    "(1 week=7). (4) Put the compound/sample code in `compound` when the line names one, the "
    "quantity+unit in `quantity`/`unit`. (5) For `service`, name the SPECIFIC assay/method/platform "
    "when the quote states it (ADP-Glo, HTRF, Caco-2, jump-dilution, SPR, compound synthesis, "
    "bioconjugation…), not a generic 'assay development'. Do not "
    "emit summary totals, subtotals, or example/illustrative figures that aren't real quoted "
    "prices. (6) For EACH line, copy the exact verbatim `source_span` you read it from "
    "(character-for-character, including the price) — do not paraphrase; it is checked against "
    "the document. Return {vendor, lines:[...]}; empty lines if it is not actually a quote."
)


def _numeric_tokens(text: str) -> set[str]:
    """Every money-ish number in the source, normalized (commas stripped, cents dropped
    when .00) — used to check an extracted amount is actually present."""
    toks: set[str] = set()
    for m in re.findall(r"\$?\s?([\d,]+(?:\.\d{1,2})?)", text or ""):
        n = m.replace(",", "")
        try:
            f = float(n)
        except ValueError:
            continue
        toks.add(f"{f:.2f}")
        toks.add(f"{f:.0f}")
    return toks


def _grounded(amount: float, present: set[str]) -> bool:
    return f"{amount:.2f}" in present or f"{amount:.0f}" in present


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def _amount_strs(amount: float) -> set[str]:
    """The ways a price might be written in text: 1850, 1,850, 1850.00, 1,850.00."""
    whole = int(amount)
    out = {f"{amount:.0f}", f"{whole:,}", f"{amount:.2f}", f"{whole:,}.{int(round((amount-whole)*100)):02d}"}
    return {s.lower() for s in out}


def _verify(ln, text: str, norm_text: str, present: set[str]) -> tuple[bool, list[str]]:
    """(keep, flags). keep=False means DROP (hard hallucination: amount absent from
    source). A kept line with flags is persisted but marked for human review."""
    if ln.amount is None or not _grounded(ln.amount, present):
        return False, ["amount_not_in_source"]      # hard drop
    flags: list[str] = []
    amt_variants = _amount_strs(ln.amount)
    nspan = _norm_ws(ln.source_span)
    if not nspan:
        flags.append("no_source_span")
    else:
        # Token-overlap, not exact substring: a quote table linearizes to non-contiguous
        # text, so a faithful span often isn't a verbatim substring even though every
        # token is present. Fabricated/paraphrased context has genuinely low overlap.
        span_toks = [t for t in nspan.split() if len(t) > 1]
        overlap = sum(1 for t in span_toks if t in norm_text) / len(span_toks) if span_toks else 0
        if overlap < 0.8:
            flags.append("span_not_in_source")       # context not actually in the document
        if not any(a in nspan for a in amt_variants):
            flags.append("amount_not_in_span")        # price not actually in its own span
    if ln.compound and _norm_ws(ln.compound) not in norm_text:
        flags.append("compound_not_in_source")
    if ln.quantity is not None:
        qv = {str(int(ln.quantity)), f"{ln.quantity:g}"}
        if not any(q in norm_text for q in qv):
            flags.append("quantity_not_in_source")
    return True, flags


_PRICE_RE = re.compile(r"\$\s?[\d,]+(?:\.\d{1,2})?")


def _focus(text: str, budget: int = 40000, radius: int = 1200) -> str:
    """What to send the model. Whole text when it fits; otherwise the head plus a
    window around every price region — pricing often sits deep in a long attachment
    (past any fixed head-cut), so a blind truncation silently drops the whole quote."""
    text = text or ""
    if len(text) <= budget:
        return text
    spans, last = [text[:radius]], 0
    for m in _PRICE_RE.finditer(text):
        s = max(0, m.start() - radius)
        if s > last:
            spans.append(text[s:m.end() + radius])
        last = m.end() + radius
    out, seen = [], 0
    for sp in spans:
        out.append(sp)
        seen += len(sp)
        if seen >= budget:
            break
    return "\n…\n".join(out)


def extract_quote_lines(text: str, vendor_hint: str | None = None,
                        api_key: str | None = None) -> tuple[list[dict], bool]:
    """(line_items, used_llm). Each item matches the deterministic parser's shape so the
    ingest path is identical downstream. Amounts not found in the source are dropped."""
    user = (f"VENDOR (hint): {vendor_hint or 'unknown'}\n\nQUOTE:\n{_focus(text)}")
    res, used = llm.structured(model=MODEL_EXTRACT_DEEP, system=_SYS, user=user,
                               schema=QuoteExtraction, fallback=QuoteExtraction(),
                               api_key=api_key, max_tokens=8192, timeout=180)
    if not used:
        return [], False
    present = _numeric_tokens(text)
    norm_text = _norm_ws(text)
    items: list[dict] = []
    for ln in res.lines:
        keep, flags = _verify(ln, text, norm_text, present)
        if not keep:
            continue          # hard grounding guard: amount not in source → drop
        scope_bits = [ln.service or ""]
        if ln.conditions:
            scope_bits.append(ln.conditions)
        items.append({
            "amount": float(ln.amount),
            "service": (ln.service or None),
            "scope": " — ".join(b for b in scope_bits if b)[:200],
            "compound": ln.compound, "quantity": ln.quantity, "unit": ln.unit,
            "turnaround_raw": None,
            "turnaround_days_min": ln.turnaround_days_min,
            "turnaround_days_max": ln.turnaround_days_max,
            "source_span": (ln.source_span or "")[:300],
            "flagged": bool(flags), "flag_reasons": ",".join(flags) or None,
            "method": "llm",
        })
    return items, True
