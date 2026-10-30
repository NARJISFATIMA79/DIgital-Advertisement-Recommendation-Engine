"""Campaign metric formulas.

Every formula returns ``None`` (not 0) when it cannot be computed, and
``compute_metrics`` also returns a ``missing`` dict that says *why*, so the UI
can explain what data is required instead of silently showing zeros.
"""
from __future__ import annotations

COUNT_FIELDS = ["impressions", "views", "clicks", "conversions"]
MONEY_FIELDS = ["spend", "revenue"]
OPTIONAL_FIELDS = ["avg_watch_seconds", "completion_25", "completion_50", "completion_75", "completion_100"]
ALL_NUMERIC = COUNT_FIELDS + MONEY_FIELDS + OPTIONAL_FIELDS

METRIC_DEFINITIONS = {
    "ctr": ("CTR (%)", "Clicks / Impressions x 100", ["clicks", "impressions"]),
    "cpc": ("CPC", "Spend / Clicks", ["spend", "clicks"]),
    "cpa": ("CPA", "Spend / Conversions", ["spend", "conversions"]),
    "conv_rate": ("Conversion rate (%)", "Conversions / Clicks x 100", ["conversions", "clicks"]),
    "roas": ("ROAS", "Attributed revenue / Spend", ["revenue", "spend"]),
    "view_rate": ("View rate (%)", "Views / Impressions x 100 (views as reported for the ad format)", ["views", "impressions"]),
    "cpv": ("Cost per view", "Spend / Views", ["spend", "views"]),
    "cpm": ("CPM", "Spend / Impressions x 1000", ["spend", "impressions"]),
    "completion_rate": ("Completion rate (%)", "Completed views / Views x 100", ["completion_100", "views"]),
}
LOWER_IS_BETTER = {"cpc", "cpa", "cpv", "cpm"}


def _num(x):
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    return v


def safe_div(n, d, scale=1.0):
    """n/d*scale, or None when either input is missing or d is zero/negative."""
    n, d = _num(n), _num(d)
    if n is None or d is None or d <= 0:
        return None
    return n / d * scale


def ctr(clicks, impressions):
    return safe_div(clicks, impressions, 100)


def cpc(spend, clicks):
    return safe_div(spend, clicks)


def cpa(spend, conversions):
    return safe_div(spend, conversions)


def conversion_rate(conversions, clicks):
    return safe_div(conversions, clicks, 100)


def roas(revenue, spend):
    return safe_div(revenue, spend)


def compute_metrics(totals: dict) -> dict:
    """Compute every metric the supplied totals allow.

    Returns {"values": {metric: float|None}, "missing": {metric: reason}}.
    """
    t = {k: _num(totals.get(k)) for k in ALL_NUMERIC}
    values = {
        "ctr": ctr(t["clicks"], t["impressions"]),
        "cpc": cpc(t["spend"], t["clicks"]),
        "cpa": cpa(t["spend"], t["conversions"]),
        "conv_rate": conversion_rate(t["conversions"], t["clicks"]),
        "roas": roas(t["revenue"], t["spend"]),
        "view_rate": safe_div(t["views"], t["impressions"], 100),
        "cpv": safe_div(t["spend"], t["views"]),
        "cpm": safe_div(t["spend"], t["impressions"], 1000),
        "completion_rate": safe_div(t["completion_100"], t["views"], 100),
    }
    missing = {}
    for m, v in values.items():
        if v is not None:
            continue
        label, _formula, needs = METRIC_DEFINITIONS[m]
        absent = [n for n in needs if t.get(n) is None]
        zero = [n for n in needs if t.get(n) is not None and t[n] <= 0]
        if absent:
            missing[m] = f"{label} needs {', '.join(absent)} (not provided)."
        elif zero:
            missing[m] = f"{label} cannot be calculated because {', '.join(zero)} is zero."
        else:
            missing[m] = f"{label} cannot be calculated from the supplied values."
    return {"values": values, "missing": missing}


def aggregate_rows(rows: list) -> dict:
    """Sum rows per field. A field absent from every row stays None (not 0)."""
    totals, coverage = {}, {}
    for f in ALL_NUMERIC:
        present = [v for v in (_num(r.get(f)) for r in rows) if v is not None]
        totals[f] = sum(present) if present else None
        coverage[f] = [len(present), len(rows)]
    totals["_coverage"] = coverage
    totals["row_count"] = len(rows)
    return totals
