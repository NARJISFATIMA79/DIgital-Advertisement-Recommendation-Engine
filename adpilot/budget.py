"""Explainable, constraint-respecting budget allocation.

Method (simple on purpose, so it can be explained):
1. Split the budget into: test reserve, proven/main pool, and (only if caps force it) unallocated.
2. Ads with enough measured evidence ("established") share the main pool in proportion to
   weight = objective_score^perf_exp * evidence_score^ev_exp.   (score comes from evaluation.py)
3. Ads with no/limited evidence ("test candidates") share the test reserve in proportion to
   their next-test priority. With no measured data at all the allocation is labelled exploratory.
4. Minimum / maximum limits per ad are enforced by iterative water-filling.
5. Amounts are rounded in cents (largest remainder) so lines + unallocated == total exactly.
"""
from __future__ import annotations

SCENARIOS = {
    "conservative": {"label": "Conservative", "perf_exp": 3.0, "ev_exp": 2.0, "default_reserve": 0.05,
                     "summary": "Leans on the best-supported historical results and keeps a small test reserve."},
    "balanced": {"label": "Balanced", "perf_exp": 2.0, "ev_exp": 1.0, "default_reserve": 0.10,
                 "summary": "Spreads funds between established performers and a moderate test reserve."},
    "growth": {"label": "Growth-focused", "perf_exp": 1.0, "ev_exp": 0.5, "default_reserve": 0.20,
               "summary": "Flatter weighting and a larger test reserve to learn faster. More exposure to unproven results."},
}


class BudgetError(ValueError):
    pass


def _waterfill(pool, weights, lo, hi):
    """Distribute pool by weights within [lo, hi]. Returns (alloc list, leftover)."""
    n = len(weights)
    if sum(lo) > pool + 1e-9:
        raise BudgetError(f"The minimum allocations add up to {sum(lo):,.0f}, which is more than the {pool:,.0f} available. Lower a minimum or raise the budget.")
    alloc = list(lo)
    remaining = pool - sum(lo)
    active = [i for i in range(n) if weights[i] > 0 and alloc[i] < hi[i] - 1e-9]
    while remaining > 1e-9 and active:
        wsum = sum(weights[i] for i in active)
        clamped = False
        for i in list(active):
            share = remaining * weights[i] / wsum
            if alloc[i] + share > hi[i] + 1e-9:
                remaining -= (hi[i] - alloc[i])
                alloc[i] = hi[i]
                active.remove(i)
                clamped = True
                break  # recompute shares after each clamp
        if not clamped:
            for i in active:
                alloc[i] += remaining * weights[i] / wsum
            remaining = 0.0
            break
    return alloc, max(remaining, 0.0)


def _round_cents(values, target_total):
    cents = [v * 100 for v in values]
    floors = [int(c // 1) for c in cents]
    diff = int(round(target_total * 100)) - sum(floors)
    order = sorted(range(len(values)), key=lambda i: -(cents[i] - floors[i]))
    for k in range(max(diff, 0)):
        floors[order[k % len(order)]] += 1
    return [f / 100 for f in floors]


def allocate(evaluation: dict, creatives: dict, next_test: dict, total: float, currency: str = "PKR",
             scenario: str = "balanced", min_alloc=None, max_alloc=None, reserve_amount=None, reserve_pct=None) -> dict:
    if total is None or total <= 0:
        raise BudgetError("Enter a total budget greater than zero.")
    sc = SCENARIOS[scenario]
    rows = evaluation["ads"]
    n = len(rows)
    if n == 0:
        raise BudgetError("Add at least one advertisement before allocating a budget.")
    user_reserve = reserve_amount is not None or reserve_pct is not None
    if reserve_amount is not None:
        reserve = float(reserve_amount)
    elif reserve_pct is not None:
        reserve = total * float(reserve_pct) / 100.0
    else:
        reserve = total * sc["default_reserve"]
    if reserve < 0 or reserve > total:
        raise BudgetError("The experimentation reserve must be between zero and the total budget.")

    def _bound(spec, i, default):
        if spec is None:
            return default
        if isinstance(spec, dict):
            v = spec.get(rows[i]["id"], spec.get("*"))
        else:
            v = spec
        return default if v in (None, "", 0) else float(v)
    mins = [_bound(min_alloc, i, 0.0) for i in range(n)]
    maxs = [_bound(max_alloc, i, float("inf")) for i in range(n)]
    for i in range(n):
        if maxs[i] < mins[i]:
            raise BudgetError(f"'{rows[i]['name']}': the maximum is below the minimum.")

    established = [i for i, r in enumerate(rows) if r.get("objective_score") is not None and r["evidence"]["level"] != "Limited"]
    cands = [i for i in range(n) if i not in established]
    prio = {s["name"]: s["priority"] for s in next_test.get("ranking", [])} if next_test else {}
    exploratory = len(established) == 0
    notes = []

    # ----- test reserve first (so min/max can include it)
    test = [0.0] * n
    reserve_line = None
    if reserve > 0:
        pool_idx = cands if cands else []
        if pool_idx:
            w = [max(prio.get(rows[i]["name"], 0.1), 0.01) if i in pool_idx else 0 for i in range(n)]
            t_alloc, left = _waterfill(reserve, w, [0.0] * n, [maxs[i] for i in range(n)])
            test = t_alloc
            if left > 0:
                reserve_line = left
        else:
            reserve_line = reserve
    # ----- main pool
    main_pool = total - reserve
    w = [0.0] * n
    if exploratory:
        has_creative = any((creatives.get(r["id"]) or {}).get("overall") is not None for r in rows)
        for i, r in enumerate(rows):
            ov = (creatives.get(r["id"]) or {}).get("overall")
            w[i] = (0.5 + (ov or 50) / 100.0) if has_creative else 1.0
        notes.append("No advertisement has enough measured evidence, so this allocation is EXPLORATORY. It is a provisional starting split to be tested, not a forecast." +
                     (" Weights come from the creative checklist, which is not proof of performance." if has_creative else " With no creative or performance information the split is equal by necessity."))
    else:
        for i in established:
            r = rows[i]
            w[i] = (r["objective_score"] ** sc["perf_exp"]) * (max(r["evidence"]["score"], 0.1) ** sc["ev_exp"])
    lo = [max(0.0, mins[i] - test[i]) for i in range(n)]
    hi = [maxs[i] - test[i] if maxs[i] != float("inf") else float("inf") for i in range(n)]
    if any(h < -1e-9 for h in hi):
        raise BudgetError("A maximum allocation is smaller than that advertisement's test share. Raise the maximum or lower the reserve.")
    hi = [max(h, 0.0) for h in hi]
    main, leftover = _waterfill(main_pool, w, lo, hi)
    unallocated = leftover
    if unallocated > 0.005:
        notes.append(f"{currency} {unallocated:,.0f} is left unallocated because the maximum limits prevent spending it on the available advertisements. Raise a maximum or add another advertisement.")

    totals_i = [main[i] + test[i] for i in range(n)]
    extra = reserve_line or 0.0
    lines_total = sum(totals_i) + extra
    values = _round_cents(totals_i + ([extra] if extra else []), round(lines_total, 2))
    unalloc_r = round(total - sum(values), 2)

    lines = []
    for i, r in enumerate(rows):
        role = "established" if i in established else ("exploratory" if exploratory else "test")
        why = []
        m = r["metrics"]
        if role == "established":
            why.append(f"Measured objective score {r['objective_score']:.2f} (1.00 = best on every metric used); evidence {r['evidence']['level']}.")
            why.append("Weight = score^{:g} x evidence^{:g} in the {} scenario.".format(sc["perf_exp"], sc["ev_exp"], sc["label"]))
        elif role == "exploratory":
            why.append("Provisional share: no measured evidence yet." )
        else:
            why.append(f"Evidence is {r['evidence']['level']} ({'; '.join(r['evidence']['reasons'][:1])}), so it is funded as a test rather than as a proven performer.")
        if test[i] > 0:
            why.append(f"Includes {currency} {test[i]:,.0f} from the experimentation reserve.")
        if mins[i] > 0 or maxs[i] != float("inf"):
            bits = []
            if mins[i] > 0: bits.append(f"min {mins[i]:,.0f}")
            if maxs[i] != float("inf"): bits.append(f"max {maxs[i]:,.0f}")
            why.append("Your limits: " + ", ".join(bits) + ".")
        proj = None
        if role == "established" and m.get("cpa"):
            proj = {"label": "Illustrative forecast (not observed)", "conversions": round(values[i] / m["cpa"], 1),
                    "assumption": "Assumes the observed CPA stays constant. Costs usually rise as spend increases, so treat this as an upper-bound illustration, not a promise."}
        lines.append({"ad_id": r["id"], "name": r["name"], "role": role, "amount": values[i],
                      "percent": round(values[i] / total * 100, 1), "test_part": round(test[i], 2),
                      "reasons": why, "observed": {k: m.get(k) for k in ("ctr", "cpc", "cpa", "conv_rate", "roas", "view_rate") if m.get(k) is not None},
                      "forecast": proj})
    if extra:
        nt = next_test.get("ad_name") if next_test else None
        lines.append({"ad_id": None, "name": f"Test reserve: new variation of '{nt}'" if nt else "Test reserve", "role": "test", "amount": values[-1],
                      "percent": round(values[-1] / total * 100, 1), "test_part": values[-1],
                      "reasons": ["Held for a controlled test of a new creative variation, because every current advertisement already has an evidence-based role."], "observed": {}, "forecast": None})
    if unalloc_r > 0.005:
        lines.append({"ad_id": None, "name": "Unallocated", "role": "unallocated", "amount": unalloc_r, "percent": round(unalloc_r / total * 100, 1),
                      "test_part": 0, "reasons": ["Held back because of maximum limits."], "observed": {}, "forecast": None})
    if user_reserve:
        notes.append("Your experimentation reserve was applied exactly in every scenario; scenarios differ only in how the main pool is weighted.")
    else:
        notes.append(f"No reserve was set, so the {sc['label']} scenario's default of {sc['default_reserve']*100:.0f}% was used as a starting assumption.")
    return {
        "scenario": scenario, "scenario_label": sc["label"], "scenario_summary": sc["summary"], "currency": currency, "total": round(total, 2),
        "reserve": round(sum(test) + (extra or 0), 2), "main_pool": round(main_pool, 2), "unallocated": max(unalloc_r, 0.0),
        "mode": "exploratory" if exploratory else "evidence-based", "lines": lines, "notes": notes,
        "reconciles": abs(sum(l["amount"] for l in lines) - total) < 0.011,
        "disclaimer": "An allocation is a recommendation based on past results and assumptions. It does not guarantee any return.",
    }


def scenarios(evaluation, creatives, next_test, total, currency="PKR", **kw) -> dict:
    out = {}
    for key in SCENARIOS:
        try:
            out[key] = allocate(evaluation, creatives, next_test, total, currency, scenario=key, **kw)
        except BudgetError as e:
            out[key] = {"error": str(e), "scenario": key, "scenario_label": SCENARIOS[key]["label"]}
    return out


def sensitivity(evaluation, creatives, next_test, total, currency="PKR", scenario="balanced", factors=(0.5, 0.75, 1.0, 1.25, 1.5), **kw) -> list:
    """How the allocation changes when the budget changes (reserve share kept constant if it was a percentage)."""
    rows = []
    kw = dict(kw)
    amt = kw.pop("reserve_amount", None)
    pct = kw.pop("reserve_pct", None)
    if amt is not None and pct is None and total:
        pct = amt / total * 100
    for f in factors:
        try:
            a = allocate(evaluation, creatives, next_test, total * f, currency, scenario=scenario, reserve_pct=pct, **kw)
            rows.append({"factor": f, "budget": a["total"], "amounts": {l["name"]: l["amount"] for l in a["lines"]}})
        except BudgetError as e:
            rows.append({"factor": f, "budget": round(total * f, 2), "error": str(e)})
    return rows


def exploratory_plan(concepts: list, total: float, currency: str = "PKR", test_share_pct=None, sample_note: str = "") -> dict:
    """Testing plan for someone with no measured results.

    * The test pool is split EQUALLY across the concepts being tested. With no evidence there is no fair basis for unequal
      shares, and unequal budgets would bias the comparison.
    * The rest is held back until the test shows which concept deserves more money.
    No CPC, CPA, conversion or return figure is estimated, because none has been observed.
    """
    if total is None or total <= 0:
        raise BudgetError("Enter a total budget greater than zero.")
    names = [c.get("title") or c.get("approach") or c["id"] for c in concepts]
    if not names:
        raise BudgetError("Select at least one concept to test.")
    share = 40.0 if test_share_pct is None else float(test_share_pct)
    if not (0 < share <= 100):
        raise BudgetError("The share of budget used for the first test must be between 0 and 100 percent.")
    pool = total * share / 100.0
    parts = _round_cents([pool / len(names)] * len(names), round(pool, 2))
    held = round(total - sum(parts), 2)
    lines = [{"name": n, "concept_id": c["id"], "role": "test", "amount": a, "percent": round(a / total * 100, 1),
              "reasons": ["Equal share of the test pool. With no measured results there is no fair basis for unequal shares, and unequal budgets would bias the comparison."]}
             for n, c, a in zip(names, concepts, parts)]
    if held > 0.005:
        lines.append({"name": "Held until the test has results", "concept_id": None, "role": "held", "amount": held, "percent": round(held / total * 100, 1),
                      "reasons": ["Kept back so you can move money to the concept the test supports, or stop. Do not spend it before then."]})
    return {"mode": "exploratory_plan", "currency": currency, "total": round(total, 2), "test_share_pct": share, "lines": lines,
            "reconciles": abs(sum(l["amount"] for l in lines) - total) < 0.011,
            "notes": ["This is a provisional testing plan, not a forecast. No click cost, conversion or return has been estimated because none has been observed.",
                      "After the first few days of real data, compare each concept's cost per click and cost per conversion, then decide how to use the held amount.",
                      sample_note or "Each concept needs a minimum number of clicks or conversions before results can be read; see the experiment plan."],
            "disclaimer": "A budget plan is a recommendation, not a promise of sales or any return."}
