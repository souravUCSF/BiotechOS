"""Dose-response analyzer — re-derives IC50/EC50 from raw points and compares to the
vendor's reported value (the core "check what the vendor says" QC). Uses scipy 4PL."""
from __future__ import annotations

from ... import curvefit


def analyze(ds: dict) -> dict:
    comp = ds.get("compound")
    rep = ds.get("reported_value")
    units = ds.get("units") or "nM"
    st = ds.get("standard_type") or "IC50"
    conc = ds.get("concentrations") or []
    resp = ds.get("responses") or []

    rel = ds.get("relation") or ""
    modality = ds.get("modality", "biochemical_ic50")

    def _dep(value, flags, raw=None):
        return [{"molecule": comp, "modality": modality, "target": ds.get("target"),
                 "standard_type": st, "value": value, "units": units, "reported_value": rep,
                 "relation": rel or None, "raw_points": raw, "flags": flags}]

    if len(conc) >= 4 and len(resp) == len(conc):
        # 1) The curve must actually reach ~50% inhibition to define an IC50. A flat/
        #    inactive curve (resistant compound) has NO determinable IC50 — the vendor's
        #    ">Xng/mL" is a censored value, not a discrepancy.
        maxresp = max(resp)
        if maxresp < 45:
            steps = [{"step": f"Dose-response — {comp}", "status": "warn",
                      "detail": f"max inhibition {maxresp:.0f}% < 50% — IC50 not determinable "
                                f"(inactive/resistant here); vendor reports {rel}{rep} {units}"}]
            return {"qc_steps": steps, "chart": None,
                    "deposition": _dep(rep, ["IC50 not determinable (<50% inhibition)"]), "status": "warn"}
        chk = curvefit.rederivation_check(conc, resp, rep if rep else 1.0)
        fit = chk.get("fit", {})
        rederived = chk.get("fitted_ic50")
        cmin, cmax = min(conc), max(conc)
        # 2) Only trust the re-derivation if the fit is good AND the IC50 is within the
        #    tested range — otherwise a garbage fit must NOT masquerade as a discrepancy.
        reliable = ("error" not in fit and (fit.get("r2") or 0) >= 0.8
                    and rederived and cmin * 0.1 <= rederived <= cmax * 10)
        if reliable:
            flagged = bool(chk.get("flagged"))
            status = "fail" if flagged else "ok"
            steps = [{"step": f"Re-fit 4PL — {comp}", "status": status,
                      "detail": (f"re-derived {st} {rederived} {units} vs vendor {rep} "
                                 f"(R²={fit.get('r2')}, {chk.get('fold_difference')}×)"
                                 + (" — DISCREPANCY, review before trusting" if flagged
                                    else " — agrees with vendor"))}]
            chart = {"kind": "dose_response", "compound": comp, "target": ds.get("target"),
                     "units": units, "points": [[float(c), float(r)] for c, r in zip(conc, resp)],
                     "fit": fit, "reported_ic50": rep, "rederived_ic50": rederived,
                     "fold": chk.get("fold_difference"), "flagged": flagged}
            return {"qc_steps": steps, "chart": chart,
                    "deposition": _dep(rederived, [] if not flagged else [chk.get("note")],
                                       {"concentration": conc, "response": resp}), "status": status}
        # fit unreliable → keep the vendor value, warn (NOT a discrepancy)
        steps = [{"step": f"Dose-response — {comp}", "status": "warn",
                  "detail": f"4PL fit unreliable (R²={fit.get('r2')}); could not independently "
                            f"re-derive — kept vendor {rel}{rep} {units}"}]
        return {"qc_steps": steps, "chart": None,
                "deposition": _dep(rep, ["curve fit unreliable"]), "status": "warn"}
    # No raw curve at all → fall back to generic single-value QC, with a note.
    from . import generic
    g = generic.analyze(ds)
    g["qc_steps"] = [{"step": f"Dose-response — {comp}", "status": "warn",
                      "detail": "no usable raw dose-response points; kept vendor-reported value "
                                "(cannot independently re-derive)"}] + g["qc_steps"]
    if g["status"] == "ok":
        g["status"] = "warn"
    return g
