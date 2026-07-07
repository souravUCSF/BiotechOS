"""4-parameter logistic (4PL) dose-response fitting.

Powers the re-derivation catch: given raw dose-response points from a CRO, we
re-fit the curve and derive IC50 ourselves, then compare to the reported IC50.
A meaningful discrepancy is flagged for human review before the data is trusted.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import curve_fit


def four_pl(x, bottom, top, ic50, hill):
    return bottom + (top - bottom) / (1.0 + (x / ic50) ** hill)


def fit_ic50(concentrations: list[float], responses: list[float]) -> dict:
    """Fit 4PL to (concentration, % response) points; return fitted params + IC50.

    Responses are % inhibition (0-100). Returns {ic50, hill, top, bottom, r2} or
    {error} if the fit fails.
    """
    x = np.asarray(concentrations, dtype=float)
    y = np.asarray(responses, dtype=float)
    if len(x) < 4:
        return {"error": "need >=4 points"}
    try:
        p0 = [float(y.min()), float(y.max()), float(np.median(x)), 1.0]
        bounds = ([-20, 50, x.min() / 100, 0.2], [50, 120, x.max() * 100, 5.0])
        popt, _ = curve_fit(four_pl, x, y, p0=p0, bounds=bounds, maxfev=10000)
        bottom, top, ic50, hill = popt
        resid = y - four_pl(x, *popt)
        ss_res = float(np.sum(resid ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        return {"ic50": float(ic50), "hill": float(hill), "top": float(top),
                "bottom": float(bottom), "r2": round(r2, 4)}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def rederivation_check(concentrations, responses, reported_ic50, tol_fold=1.5) -> dict:
    """Fit the curve, compare fitted IC50 to reported. Flag if they disagree by
    more than `tol_fold` fold. Returns the fit + discrepancy verdict."""
    fit = fit_ic50(concentrations, responses)
    if "error" in fit:
        return {"fit": fit, "flagged": False, "note": "fit failed"}
    fitted = fit["ic50"]
    fold = max(fitted, reported_ic50) / max(min(fitted, reported_ic50), 1e-9)
    flagged = fold > tol_fold
    return {
        "fit": fit,
        "reported_ic50": reported_ic50,
        "fitted_ic50": round(fitted, 2),
        "fold_difference": round(fold, 2),
        "flagged": flagged,
        "note": (
            f"Reported IC50 {reported_ic50} nM disagrees with re-derived "
            f"{round(fitted, 1)} nM ({round(fold, 1)}x) — recommend review."
            if flagged else
            f"Re-derived IC50 {round(fitted, 1)} nM matches reported within tolerance."
        ),
    }


def synth_curve(ic50: float, hill: float = 1.0, noise: float = 2.0,
                seed: int | None = None) -> tuple[list[float], list[float]]:
    """Generate a realistic dose-response series around a true IC50 (for demo CRO data)."""
    rng = np.random.default_rng(seed)
    conc = [ic50 * f for f in (0.01, 0.03, 0.1, 0.3, 1, 3, 10, 30, 100)]
    resp = [float(four_pl(c, 0, 100, ic50, hill) + rng.normal(0, noise)) for c in conc]
    return conc, resp
