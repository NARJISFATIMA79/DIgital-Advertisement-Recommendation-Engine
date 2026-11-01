"""CSV / row validation. Nothing is silently dropped: every exclusion is reported."""
from __future__ import annotations
import csv
import io
import statistics

from .metrics import ALL_NUMERIC, COUNT_FIELDS, MONEY_FIELDS

ALIASES = {
    "ad_name": ["ad_name", "ad", "advertisement", "ad name", "creative", "creative_name", "ad_id", "advertisement_name"],
    "date": ["date", "day"],
    "impressions": ["impressions", "impr", "impr."],
    "views": ["views", "video_views", "view"],
    "clicks": ["clicks", "click"],
    "spend": ["spend", "cost", "ad_spend", "advertising_spend", "amount_spent"],
    "conversions": ["conversions", "conv", "conv.", "leads", "orders"],
    "revenue": ["revenue", "attributed_revenue", "conversion_value", "conv_value"],
    "avg_watch_seconds": ["avg_watch_seconds", "average_watch_time", "avg_watch_time", "avg_watch_time_seconds"],
    "completion_25": ["completion_25", "video_played_to_25", "played_25"],
    "completion_50": ["completion_50", "video_played_to_50", "played_50"],
    "completion_75": ["completion_75", "video_played_to_75", "played_75"],
    "completion_100": ["completion_100", "video_played_to_100", "played_100", "completed_views"],
}
REQUIRED = ["ad_name"]
USEFUL = ["impressions", "clicks", "spend"]
TEMPLATE_HEADER = ["date", "ad_name", "impressions", "views", "clicks", "spend", "conversions", "revenue",
                   "avg_watch_seconds", "completion_25", "completion_50", "completion_75", "completion_100"]


def normalise_header(h):
    h = (h or "").strip().lower().replace("-", "_").replace(" ", "_")
    for canon, names in ALIASES.items():
        if h == canon or h in [n.replace(" ", "_") for n in names]:
            return canon
    return h


def parse_csv_text(text: str):
    text = text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return [], []
    mapping = {h: normalise_header(h) for h in reader.fieldnames}
    rows = []
    for r in reader:
        rows.append({mapping[k]: (v.strip() if isinstance(v, str) else v) for k, v in r.items() if k in mapping})
    return list(mapping.values()), rows


def _to_number(raw):
    if raw is None:
        return None, None
    s = str(raw).strip().replace(",", "")
    for sym in ("PKR", "Rs.", "Rs", "$", "USD", "EUR", "GBP"):
        s = s.replace(sym, "")
    s = s.strip()
    if s == "" or s.lower() in ("na", "n/a", "null", "none", "-"):
        return None, None
    try:
        return float(s), None
    except ValueError:
        return None, f"'{raw}' is not a number"


def _summary(rows, clean, excluded, warnings, errors):
    return {
        "clean_rows": clean, "excluded": excluded, "errors": errors,
        "warnings": warnings[:50] + ([f"... and {len(warnings) - 50} more warnings."] if len(warnings) > 50 else []),
        "summary": {"uploaded_rows": len(rows), "clean_rows": len(clean), "excluded_rows": len(excluded), "warning_count": len(warnings)},
    }


def validate_rows(columns: list, rows: list) -> dict:
    """Return clean_rows, excluded (with reasons), warnings, errors, summary."""
    errors, warnings, excluded, clean = [], [], [], []
    present = set(columns)
    for req in REQUIRED:
        if req not in present:
            errors.append(f"Required column '{req}' is missing. Accepted names: {', '.join(ALIASES[req])}.")
    if not any(c in present for c in ALL_NUMERIC):
        errors.append("No performance columns found. Add at least impressions, clicks or spend.")
    if errors:
        return _summary(rows, clean, excluded, warnings, errors)

    missing_useful = [c for c in USEFUL if c not in present]
    if missing_useful:
        warnings.append(f"Columns not supplied: {', '.join(missing_useful)}. Metrics that need them will show as unavailable.")

    seen = {}
    for i, raw in enumerate(rows, start=2):  # row 1 is the header
        row = {"row_number": i, "ad_name": (raw.get("ad_name") or "").strip(), "date": raw.get("date")}
        if not row["ad_name"]:
            excluded.append({"row": i, "reason": "ad_name is empty, so the record cannot be attributed to an advertisement."})
            continue
        bad = []
        for f in ALL_NUMERIC:
            if f not in present:
                row[f] = None
                continue
            val, err = _to_number(raw.get(f))
            if err:
                bad.append(f"{f}: {err}")
            row[f] = val
        if bad:
            excluded.append({"row": i, "reason": "Invalid numeric value(s) - " + "; ".join(bad) + "."})
            continue
        neg = [f for f in COUNT_FIELDS + MONEY_FIELDS if row.get(f) is not None and row[f] < 0]
        if neg:
            excluded.append({"row": i, "reason": f"Negative value in {', '.join(neg)}; counts and spend cannot be negative."})
            continue
        if row["clicks"] is not None and row["impressions"] is not None and row["clicks"] > row["impressions"]:
            excluded.append({"row": i, "reason": f"Clicks ({row['clicks']:g}) exceed impressions ({row['impressions']:g}); this is impossible, so the row was excluded."})
            continue
        if row["views"] is not None and row["impressions"] is not None and row["views"] > row["impressions"]:
            warnings.append(f"Row {i}: views exceed impressions. Some YouTube formats count views differently; check the metric definition before comparing.")
        if row["conversions"] is not None and row["clicks"] is not None and row["conversions"] > row["clicks"]:
            warnings.append(f"Row {i}: conversions exceed clicks. This can happen with view-through conversions, so conversion rate may be overstated.")
        if row["conversions"] and row["revenue"] is None and "revenue" in present:
            warnings.append(f"Row {i}: conversions recorded but revenue is empty. ROAS will not include this row's revenue.")
        if row["impressions"] == 0:
            warnings.append(f"Row {i}: zero impressions; rate metrics are unavailable for this row.")
        key = (row["ad_name"], row.get("date"), tuple(row.get(f) for f in ALL_NUMERIC))
        if key in seen:
            excluded.append({"row": i, "reason": f"Exact duplicate of row {seen[key]}; excluded to avoid double counting."})
            continue
        seen[key] = i
        clean.append(row)

    cpcs = [(r["row_number"], r["spend"] / r["clicks"]) for r in clean if r.get("spend") is not None and r.get("clicks")]
    if len(cpcs) >= 8:
        med = statistics.median(v for _, v in cpcs)
        for rn, v in cpcs:
            if med > 0 and (v > 5 * med or v < med / 5):
                warnings.append(f"Row {rn}: cost per click is {v:.2f}, far from the typical {med:.2f}. Kept in the analysis; please check it.")
    return _summary(rows, clean, excluded, warnings, errors)


def validate_csv_text(text: str) -> dict:
    columns, rows = parse_csv_text(text)
    if not columns:
        return _summary([], [], [], [], ["The file is empty or has no header row."])
    if not rows:
        return _summary([], [], [], [], ["The file has a header but no data rows."])
    return validate_rows(columns, rows)


def template_csv() -> str:
    lines = [",".join(TEMPLATE_HEADER),
             "2026-09-01,Example ad A,20000,6400,310,18500,14,52000,16.2,5200,3600,2500,1800",
             "2026-09-02,Example ad A,21000,6700,322,19400,16,59800,16.0,5400,3700,2600,1900",
             "2026-09-01,Example ad B,19000,5100,260,17900,9,31500,12.1,3900,2600,1700,1100"]
    return "\n".join(lines) + "\n"
