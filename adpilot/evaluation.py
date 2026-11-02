"""Objective-specific evaluation, evidence quality, and the two decisions:

1. Best-Performing Advertisement  (measured results only)
2. Best Advertisement to Test Next (uncertainty + creative opportunity + promise)
"""
from __future__ import annotations
import math

from .metrics import LOWER_IS_BETTER, METRIC_DEFINITIONS, compute_metrics
from .strategy import OBJECTIVES

# metric weights per objective. 'primary' must be available for ALL compared ads to rank them.
OBJECTIVE_SPECS = {
    "awareness": {"primary": "view_rate", "weights": {"view_rate": 0.5, "cpv": 0.3, "completion_rate": 0.2},
                  "why": "Awareness is judged on how many people watch (view rate) and what each view costs, not on immediate purchases.",
                  "rate": ("views", "impressions")},
    "reach": {"primary": "cpm", "weights": {"cpm": 1.0},
              "why": "Reach is judged on how cheaply you put the ad in front of people (CPM).", "rate": None},
    "engagement": {"primary": "view_rate", "weights": {"view_rate": 0.35, "completion_rate": 0.4, "cpv": 0.25},
                   "why": "Engagement is judged on view rate, how much of the video people finish, and cost per view.",
                   "rate": ("views", "impressions")},
    "traffic": {"primary": "cpc", "weights": {"cpc": 0.6, "ctr": 0.4},
                "why": "Traffic is judged on cost per click and click-through rate together; CTR alone can reward cheap, low-intent clicks.",
                "rate": ("clicks", "impressions")},
    "leads": {"primary": "cpa", "weights": {"cpa": 0.6, "conv_rate": 0.4},
              "why": "Lead generation is judged on cost per lead (CPA) and how many clicks become leads.",
              "rate": ("conversions", "clicks")},
    "sales": {"primary": "roas", "weights": {"roas": 0.5, "cpa": 0.3, "conv_rate": 0.2},
              "why": "Sales are judged on return on ad spend, cost per acquisition and conversion rate; CTR is not used to rank.",
              "rate": ("conversions", "clicks")},
    "consideration": {"primary": "cpc", "weights": {"cpc": 0.35, "ctr": 0.25, "view_rate": 0.2, "completion_rate": 0.2},
                      "why": "Consideration blends click cost, click-through and viewing depth, because people are still deciding.",
                      "rate": ("clicks", "impressions")},
}
# the 'sample size' fields that make a result trustworthy for each objective
MIN_SAMPLE = {"impressions": 10000, "clicks": 100, "conversions": 30, "views": 500}
SAMPLE_FIELD = {"awareness": "views", "reach": "impressions", "engagement": "views", "traffic": "clicks",
                "leads": "conversions", "sales": "conversions", "consideration": "clicks"}
MARGIN_REQUIRED = 0.05  # leader must be 5 points ahead (0-1 scale) of runner-up


def _fmt(metric, v):
    if v is None:
        return "n/a"
    return f"{v:,.2f}" + ("%" if metric in ("ctr", "conv_rate", "view_rate", "completion_rate") else "x" if metric == "roas" else "")


def evidence_quality(totals: dict, objective: str) -> dict:
    """High / Moderate / Limited based on sample size for the objective's key outcome."""
    f = SAMPLE_FIELD.get(objective, "clicks")
    need = MIN_SAMPLE[f]
    have = totals.get(f)
    reasons = []
    if have is None:
        return {"level": "Limited", "score": 0.0, "reasons": [f"No {f} data supplied; {objective} results cannot be judged."]}
    ratio = min(have / need, 2.0) / 2.0  # 0..1, saturates at 2x the minimum
    cov = totals.get("_coverage", {}).get(f)
    if cov and cov[1] and cov[0] < cov[1]:
        ratio *= cov[0] / cov[1]
        reasons.append(f"Only {cov[0]} of {cov[1]} records include {f}.")
    if have < need:
        reasons.append(f"{have:,.0f} {f} is below the {need:,} used as a minimum for {objective} comparisons.")
    elif have >= 2 * need:
        reasons.append(f"{have:,.0f} {f} comfortably exceeds the {need:,} minimum.")
    else:
        reasons.append(f"{have:,.0f} {f} meets the {need:,} minimum.")
    level = "High" if ratio >= 0.9 else "Moderate" if ratio >= 0.5 else "Limited"
    return {"level": level, "score": round(ratio, 3), "reasons": reasons}


def two_proportion_p(x1, n1, x2, n2):
    """Two-sided two-proportion z-test p-value, or None if not computable."""
    if not n1 or not n2 or n1 <= 0 or n2 <= 0 or x1 is None or x2 is None:
        return None
    p1, p2 = x1 / n1, x2 / n2
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return None
    z = (p1 - p2) / se
    return math.erfc(abs(z) / math.sqrt(2))


def evaluate_ads(ads: list, objective: str) -> dict:
    """ads: [{id,name,totals(dict|None),creative(dict|None)}] -> evaluation with best performer & ranking."""
    spec = OBJECTIVE_SPECS.get(objective) or OBJECTIVE_SPECS["sales"]
    notes = []
    rows = []
    for ad in ads:
        t = ad.get("totals")
        m = compute_metrics(t) if t else {"values": {}, "missing": {}}
        rows.append({"id": ad["id"], "name": ad["name"], "totals": t, "metrics": m["values"], "missing": m["missing"],
                     "evidence": evidence_quality(t, objective) if t else {"level": "Limited", "score": 0.0, "reasons": ["No campaign data supplied for this advertisement."]}})
    with_data = [r for r in rows if r["totals"]]
    # usable metrics = weighted metrics available for EVERY ad that has data
    usable = {k: w for k, w in spec["weights"].items() if with_data and all(r["metrics"].get(k) is not None for r in with_data)}
    dropped = [k for k in spec["weights"] if k not in usable]
    primary_ok = spec["primary"] in usable
    result = {"objective": objective, "objective_label": OBJECTIVES.get(objective, objective), "why_these_metrics": spec["why"],
              "metrics_used": list(usable), "metrics_dropped": dropped, "ranking": [], "best_performer": None,
              "provisional_leader": None, "status": "inconclusive", "reasons": notes, "ads": rows}
    if dropped and with_data:
        notes.append("Not used because at least one advertisement lacks the data: " + ", ".join(METRIC_DEFINITIONS[k][0] for k in dropped) + ".")

    if len(with_data) == 0:
        notes.append("No advertisement has campaign performance data, so no measured winner can be named. Use the 'Next Best Test' recommendation instead.")
        return result
    if len(with_data) < 2:
        notes.append("Only one advertisement has performance data; there is nothing to compare it against.")
        return result
    if not primary_ok:
        notes.append(f"The key metric for {result['objective_label']} ({METRIC_DEFINITIONS[spec['primary']][0]}) is missing for at least one advertisement, so a fair ranking is not possible.")
        return result

    # Only ads with adequate evidence compete for "best performer"; Limited-evidence ads are shown
    # with an indicative score but cannot win, because tiny samples produce extreme ratios.
    contenders = [r for r in with_data if r["evidence"]["level"] != "Limited"]
    excluded_limited = [r["name"] for r in with_data if r["evidence"]["level"] == "Limited"]
    if excluded_limited and len(contenders) >= 2:
        notes.append("Not eligible to be named best performer because their evidence is Limited: " + ", ".join(excluded_limited) + ". They are candidates for testing instead.")
    base = contenders if len(contenders) >= 2 else with_data
    best = {}
    for k in usable:
        vals = [r["metrics"][k] for r in base]
        best[k] = min(vals) if k in LOWER_IS_BETTER else max(vals)
    wsum = sum(usable.values())
    for r in with_data:
        comp, parts = 0.0, {}
        for k, w in usable.items():
            v = r["metrics"][k]
            s_k = (best[k] / v) if (k in LOWER_IS_BETTER and v > 0) else (1.0 if k in LOWER_IS_BETTER else ((v / best[k]) if best[k] > 0 else 0.0))
            s_k = min(s_k, 1.0)
            parts[k] = round(s_k, 3)
            comp += w * s_k
        r["objective_score"] = round(comp / wsum, 3)
        r["score_parts"] = parts
    ranked = sorted(base, key=lambda r: -r["objective_score"])
    result["ranking"] = [{"id": r["id"], "name": r["name"], "objective_score": r["objective_score"], "eligible": r in contenders}
                         for r in sorted(with_data, key=lambda r: -r["objective_score"])]
    if len(contenders) < 2:
        notes.append("Fewer than two advertisements have enough evidence to be compared fairly, so no winner can be established.")
        result["provisional_leader"] = {"id": ranked[0]["id"], "name": ranked[0]["name"]}
        return result
    top, second = ranked[0], ranked[1]
    margin = top["objective_score"] - second["objective_score"]
    result["margin"] = round(margin, 3)
    result["provisional_leader"] = {"id": top["id"], "name": top["name"]}

    lvl_ok = True
    pnum = None
    if spec["rate"]:
        a, b = spec["rate"]
        t1, t2 = top["totals"], second["totals"]
        pnum = two_proportion_p(t1.get(a), t1.get(b), t2.get(a), t2.get(b))
    result["p_value"] = None if pnum is None else round(pnum, 4)
    result["test_used"] = None if not spec["rate"] else f"Two-proportion z-test on {spec['rate'][0]}/{spec['rate'][1]} (top two eligible ads)"

    if margin < MARGIN_REQUIRED:
        notes.append(f"The top two scores are within {MARGIN_REQUIRED:.2f} of each other (gap {margin:.3f}); the difference is too small to call.")
    if pnum is not None and pnum >= 0.05:
        notes.append(f"The difference in the underlying rate is not statistically distinguishable (p = {pnum:.3f}).")
    if lvl_ok and margin >= MARGIN_REQUIRED and (pnum is None or pnum < 0.05):
        result["status"] = "established"
        result["best_performer"] = {"id": top["id"], "name": top["name"]}
        if pnum is None:
            notes.append("No significance test applies to this cost/ratio-based objective; the call rests on sample size and the size of the gap. Treat it as strong but not statistically proven.")
    else:
        result["status"] = "inconclusive"
    # comparison text
    result["comparison"] = [{"name": r["name"], "objective_score": r["objective_score"], "eligible": r in contenders,
                             "key_metrics": {k: _fmt(k, r["metrics"].get(k)) for k in usable}} for r in sorted(with_data, key=lambda r: -r["objective_score"])]
    return result


def recommend_next_test(ads_eval: dict, creatives: dict, strategy: dict, objective: str, total_budget: float, reserve: float, currency: str) -> dict:
    """Which ad / variation to test next, with hypothesis, metric and decision rule.

    priority = 0.45*uncertainty + 0.35*creative_opportunity + 0.20*promise
    * uncertainty: 1 - evidence score (what we don't yet know)
    * creative opportunity: 1 - (creative overall/100); unknown creative counts as 0.5
    * promise: relative objective score when measured, else 0.5 (unknown)
    """
    rows = ads_eval["ads"]
    if not rows:
        return {"status": "no_ads", "message": "Add at least one advertisement to get a test recommendation."}
    est = ads_eval.get("best_performer")
    scored = []
    for r in rows:
        cr = creatives.get(r["id"]) or {}
        overall = cr.get("overall")
        opp = 0.5 if overall is None else 1 - overall / 100
        unc = 1 - r["evidence"]["score"]
        promise = r.get("objective_score", 0.5)
        pr = 0.45 * unc + 0.35 * opp + 0.20 * promise
        # an established winner already has its answer; testing it again adds little
        if est and est["id"] == r["id"]:
            pr -= 0.10
        scored.append({"id": r["id"], "name": r["name"], "priority": round(pr, 3), "uncertainty": round(unc, 3),
                       "creative_opportunity": round(opp, 3), "promise": round(promise, 3), "creative": cr})
    scored.sort(key=lambda s: -s["priority"])
    pick = scored[0]
    cr = pick["creative"]
    weakest = (cr.get("weakest") or [None])[0]
    dim_label = cr.get("dimensions", {}).get(weakest, {}).get("label") if weakest else None
    spec = OBJECTIVE_SPECS.get(objective, OBJECTIVE_SPECS["sales"])
    primary = METRIC_DEFINITIONS[spec["primary"]][0]
    exps = strategy.get("experiments", [])
    change = dim_label or "opening hook"
    suggestion = exps[0] if exps else "two different openings"
    has_data = any(r["totals"] for r in rows)
    basis = []
    if pick["uncertainty"] > 0.5:
        basis.append("its results are still uncertain (limited data)")
    if pick["creative_opportunity"] > 0.3 and cr.get("overall") is not None:
        basis.append(f"the creative checklist found room to improve ({dim_label or 'several areas'})")
    if pick["promise"] >= 0.8 and has_data:
        basis.append("its measured results are promising relative to the others")
    if not basis:
        basis.append("it has the highest combined priority across uncertainty, creative opportunity and measured promise")
    sample = SAMPLE_FIELD.get(objective, "clicks")
    need = MIN_SAMPLE[sample]
    test_budget = reserve if reserve and reserve > 0 else None
    return {
        "status": "ok", "ad_id": pick["id"], "ad_name": pick["name"],
        "different_from_best": bool(est and est["id"] != pick["id"]),
        "why": "Selected because " + "; ".join(basis) + ".",
        "hypothesis": f"Changing the {change.lower()} of '{pick['name']}' will improve {primary} compared with the current version. This is a hypothesis to test, not a prediction.",
        "what_to_change": f"{change}. Starting idea for this category: {suggestion}.",
        "primary_metric": primary,
        "test_budget": test_budget,
        "test_budget_note": (f"{currency} {test_budget:,.0f} is your experimentation reserve." if test_budget else "No experimentation reserve was set; set one so the test has funding."),
        "decision_rule": [
            f"Run both versions in parallel with the same audience and dates until each has at least {need:,} {sample} (or the planned duration ends).",
            f"Scale the new version only if its {primary} is better by a margin you set in advance (for example 10%) and the sample minimum is met.",
            "Keep the original if the difference is smaller than that margin; stop and revise if the new version is clearly worse.",
            "Do not declare a winner earlier than the sample minimum; early swings are usually noise.",
        ],
        "ranking": [{"name": s["name"], "priority": s["priority"], "uncertainty": s["uncertainty"], "creative_opportunity": s["creative_opportunity"], "promise": s["promise"]} for s in scored],
        "evidence_basis": "Measured performance + creative checklist + industry hypotheses" if has_data else "Creative checklist + industry hypotheses (no performance data supplied)",
    }


def plan_concept_tests(concepts: list, objective: str, strategy: dict, test_budget=None, currency: str = "PKR") -> dict:
    """Experiment plan for people with NO measured results. Produces a design, never a winner."""
    if not concepts:
        return {"status": "no_concepts", "message": "Select at least one concept to get a test plan."}
    spec = OBJECTIVE_SPECS.get(objective, OBJECTIVE_SPECS["sales"])
    primary = METRIC_DEFINITIONS[spec["primary"]][0]
    sample = SAMPLE_FIELD.get(objective, "clicks")
    need = MIN_SAMPLE[sample]
    names = [c.get("title") or c.get("approach") for c in concepts]
    weakest = {}
    for c in concepts:
        cr = c.get("creative") or {}
        w = (cr.get("weakest") or [None])[0]
        if w:
            weakest[c["id"]] = cr["dimensions"][w]["label"]
    out = {
        "status": "ok", "kind": "concept_test",
        "headline": f"Test {len(concepts)} concept{'s' if len(concepts) != 1 else ''} against each other" if len(concepts) > 1 else f"Test '{names[0]}' against a second version",
        "hypothesis": (f"At least one of these concepts will give a better {primary} than the others for this audience. Which one is unknown until real data exists; "
                       "AdPilot is not predicting a winner."),
        "what_changes": "Only the creative concept (hook, message and approach). Keep audience, dates, format, landing page and budget per concept identical.",
        "primary_metric": primary,
        "minimum_sample": f"{need:,} {sample} per concept before comparing (a working minimum, not a guarantee of reliability).",
        "test_budget": test_budget, "currency": currency,
        "decision_rule": [
            f"Run all concepts in parallel with equal budgets until each has at least {need:,} {sample}, or the planned dates end.",
            f"Pick the concept with the better {primary} only if the gap is larger than a margin you set before starting (for example 10 to 20 percent).",
            "If the gap is smaller than that margin, treat it as a tie and test a new variable (hook, offer) rather than choosing arbitrarily.",
            "Do not judge by views or likes alone. Public popularity is not your conversion result.",
        ],
        "follow_ups": [f"Then test hook alternatives on the strongest concept: {e}" for e in strategy.get("experiments", [])[:2]],
        "checklist_gaps": [f"'{c.get('title')}': weakest checklist area is {weakest[c['id']].lower()}." for c in concepts if c["id"] in weakest],
        "evidence_basis": "Your inputs and the industry framework (hypotheses). No measured performance exists yet.",
    }
    if not test_budget:
        out["budget_note"] = "Set a budget to see how much each concept would get."
    return out
