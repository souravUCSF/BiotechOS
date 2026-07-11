"""ADME analyzer — QC's a compound's ADME panel (clearance, permeability, solubility,
stability, %F, PPB, half-life). Range/plausibility checks + interpretive banding
(low/moderate/high), a panel chart, and one deposition row per property."""
from __future__ import annotations

# per-property spec: units, plausibility range (fraction-type props), and interpretive
# bands [(lo, hi, label)]; `hi_flag` marks a value worth flagging as extreme.
_ADME = {
    "clint":                {"units": "uL/min/mg", "hi_flag": 300,
                             "bands": [(0, 10, "low clearance"), (10, 50, "moderate"), (50, 1e12, "high clearance")]},
    "intrinsic_clearance":  {"units": "uL/min/mg", "hi_flag": 300,
                             "bands": [(0, 10, "low clearance"), (10, 50, "moderate"), (50, 1e12, "high clearance")]},
    "papp":                 {"units": "1e-6 cm/s",
                             "bands": [(0, 2, "low permeability"), (2, 20, "moderate"), (20, 1e12, "high permeability")]},
    "permeability":         {"units": "1e-6 cm/s",
                             "bands": [(0, 2, "low permeability"), (2, 20, "moderate"), (20, 1e12, "high permeability")]},
    "solubility":           {"units": "uM",
                             "bands": [(0, 10, "low"), (10, 100, "moderate"), (100, 1e12, "high")]},
    "half_life":            {"units": "h", "bands": [(0, 1, "short"), (1, 6, "moderate"), (6, 1e12, "long")]},
    "t_half":               {"units": "h", "bands": [(0, 1, "short"), (1, 6, "moderate"), (6, 1e12, "long")]},
    "f":                    {"units": "%", "range": (0, 100)},
    "bioavailability":      {"units": "%", "range": (0, 100)},
    "ppb":                  {"units": "%", "range": (0, 100)},
    "plasma_protein_binding": {"units": "%", "range": (0, 100)},
    "microsomal_stability": {"units": "%", "range": (0, 100)},
    "stability":            {"units": "%", "range": (0, 100)},
    # Caco-2 / permeability report fields:
    "recovery":             {"units": "%", "low_flag": 70},   # <70% mass recovery → unreliable
    "efflux_ratio":         {"units": "", "bands": [(0, 2, "no efflux"), (2, 1e12, "efflux substrate")]},
}


def _key(prop: str) -> str:
    k = (prop or "").strip().lower().replace(" ", "_").replace("-", "_").replace("%", "").strip("_")
    # collapse directional Caco-2 suffixes (Papp_A_to_B / Recovery_B_to_A → base property)
    for suf in ("_a_to_b", "_b_to_a", "a_to_b", "b_to_a", "_ab", "_ba"):
        k = k.replace(suf, "")
    k = k.strip("_")
    if k.startswith("papp") or k == "permeability" or k == "perm":
        return "papp"
    if k.startswith("recovery"):
        return "recovery"
    if "efflux" in k:
        return "efflux_ratio"
    if k in ("clearance", "cl_int", "clint_hep"):
        return "clint"
    return k


def _band(prop_key: str, val) -> tuple[str | None, list[str]]:
    spec = _ADME.get(prop_key)
    if not spec or val is None:
        return None, []
    flags, band = [], None
    if "range" in spec:
        lo, hi = spec["range"]
        band = "in range"
        if not (lo <= val <= hi):
            flags.append(f"outside {lo}-{hi}{spec['units']}")
            band = "out of range"
    for lo, hi, label in spec.get("bands", []):
        if lo <= val < hi:
            band = label
            break
    if spec.get("hi_flag") and val is not None and val > spec["hi_flag"]:
        flags.append(f"very high ({val} {spec['units']})")
    if spec.get("low_flag") is not None and val is not None and val < spec["low_flag"]:
        flags.append(f"low recovery ({val}%) — measurement may be unreliable")
    return band, flags


def analyze(ds: dict) -> dict:
    comp = ds.get("compound")
    panel = ds.get("panel") or []
    # a single reported value with an ADME standard_type is a 1-item panel
    if not panel and ds.get("reported_value") is not None:
        panel = [{"property": ds.get("standard_type"), "value": ds.get("reported_value"),
                  "units": ds.get("units")}]
    steps, items, dep, status = [], [], [], "ok"
    for it in panel:
        prop = it.get("property") or "?"
        val, units = it.get("value"), it.get("units")
        rel = it.get("relation") or ""          # < or > (BLOD / cutoff)
        band, flags = _band(_key(prop), val)
        if rel in ("<", ">"):
            flags.append(f"reported as {rel}{val} (below/above limit of detection)")
        st = "warn" if flags else "ok"
        if flags:
            status = "warn"
        vtxt = f"{rel}{val}".strip()
        steps.append({"step": f"ADME — {comp} · {prop}", "status": st,
                      "detail": f"{prop} = {vtxt} {units or ''}"
                                + (f" → {band}" if band else "")
                                + ("; " + ", ".join(flags) if flags else "")})
        items.append({"property": prop, "value": val, "relation": rel or None, "units": units,
                      "band": band, "flagged": bool(flags)})
        dep.append({"molecule": comp, "modality": "adme", "target": ds.get("target"),
                    "standard_type": prop, "value": val, "units": units, "reported_value": val,
                    "relation": rel or None, "raw_points": None, "flags": flags})
    if not items:
        steps.append({"step": f"ADME — {comp}", "status": "warn", "detail": "no ADME properties parsed"})
        status = "warn"
    chart = {"kind": "panel", "compound": comp, "items": items} if items else None
    return {"qc_steps": steps, "chart": chart, "deposition": dep, "status": status}
