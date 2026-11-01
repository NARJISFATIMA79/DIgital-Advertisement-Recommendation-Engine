"""End-to-end analysis pipeline with two journeys.

MODE "idea":     product idea only -> concept proposals -> competitor references -> text comparison -> test plan -> exploratory budget plan
MODE "existing": ads (+ optional results) -> validation -> metrics -> evaluation -> evidence -> comparison -> next test -> budget

Nothing here fills missing values with invented data. Measured results, creative observations and public video text
are kept in separate result sections.
"""
from __future__ import annotations

from . import budget as B
from . import transparency as TR
from .competitive import analyse_public_video, compare_with_own, competitor_performance, dimension_table
from .concepts import GENERATOR, assess_concept, generate_concepts
from .creative import assess_creative
from .discovery import safe_youtube_url, tokens
from .evaluation import OBJECTIVE_SPECS, evaluate_ads, plan_concept_tests, recommend_next_test, SAMPLE_FIELD, MIN_SAMPLE
from .metrics import ALL_NUMERIC, aggregate_rows
from .strategy import OBJECTIVES, STRATEGIES, strategy_for
from .validation import validate_csv_text

MAX_ADS, MAX_CONCEPTS, MAX_VIDEOS = 20, 8, 15


def _num(x):
    if x in (None, ""):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def _s(x, n=500):
    return x.strip()[:n] if isinstance(x, str) else ("" if x is None else str(x)[:n])


def validate_payload(payload):
    """Shape and size checks. Raises ValueError with a message safe to show to the user."""
    if not isinstance(payload, dict):
        raise ValueError("The request must be a JSON object.")
    for key, typ in (("profile", dict), ("ads", list), ("concepts", list), ("competitor_videos", list), ("competitor_performance", list)):
        if payload.get(key) is not None and not isinstance(payload[key], typ):
            raise ValueError(f"'{key}' has the wrong format.")
    if payload.get("budget") is not None and not isinstance(payload["budget"], dict):
        raise ValueError("'budget' has the wrong format.")
    if len(payload.get("ads") or []) > MAX_ADS:
        raise ValueError(f"Please analyse at most {MAX_ADS} advertisements at a time.")
    if len(payload.get("concepts") or []) > MAX_CONCEPTS:
        raise ValueError(f"Please keep at most {MAX_CONCEPTS} concepts.")
    if len(payload.get("competitor_videos") or []) > MAX_VIDEOS:
        raise ValueError(f"Please compare at most {MAX_VIDEOS} competitor videos at a time.")
    for lst in ("ads", "concepts", "competitor_videos", "competitor_performance"):
        if any(not isinstance(i, dict) for i in (payload.get(lst) or [])):
            raise ValueError(f"Every item in '{lst}' must be an object.")
    if any(isinstance(a.get("performance"), (list, str)) for a in payload.get("ads") or []):
        raise ValueError("Performance figures have the wrong format.")


def _profile(raw):
    p = raw or {}
    industry = p.get("industry") if p.get("industry") in STRATEGIES else "other"
    out = {k: _s(p.get(k), 300) for k in ("brand", "product", "market", "audience", "goal", "benefit", "problem", "initial_hook", "offer", "other_desc", "price")}
    out["audience"] = _s(p.get("audience"), 500)
    out["industry"] = industry
    return out


def run_analysis(payload: dict) -> dict:
    validate_payload(payload)
    profile = _profile(payload.get("profile"))
    objective = payload.get("objective") or (payload.get("profile") or {}).get("objective") or "sales"
    if objective not in OBJECTIVES:
        raise ValueError(f"Unknown objective '{objective}'.")
    ads_in = payload.get("ads") or []
    mode = payload.get("mode") or ("existing" if ads_in else "idea")
    if mode not in ("idea", "existing"):
        raise ValueError("Unknown analysis mode.")
    if mode == "idea" and not profile["product"]:
        raise ValueError("Tell us what you are advertising (the product or service) so concepts and searches can be created.")
    if mode == "existing" and not ads_in:
        raise ValueError("Add at least one advertisement to analyse, or switch to 'I have a product idea'.")
    strategy = strategy_for(profile["industry"], objective)
    ctx = {"objective": objective, "product": profile["product"], "audience": profile["audience"], "industry_label": strategy["label"],
           "approaches": strategy["approaches"], "market": profile["market"], "brand": profile["brand"]}
    run = _run_idea if mode == "idea" else _run_existing
    result = run(payload, profile, objective, strategy, ctx)
    result.update({"mode": mode, "profile": profile, "objective": objective, "objective_label": OBJECTIVES[objective], "strategy": strategy,
                   "is_demo": bool(payload.get("is_demo")),
                   "method_note": "Measured results decide who gets proven budget. Creative checklists and competitor observations only suggest what to test."})
    return result


# ------------------------------------------------------------------------------------------------ shared pieces
def _budget_inputs(payload):
    b = payload.get("budget") or {}
    total = _num(b.get("total"))
    return b, total, (b.get("currency") or "PKR")[:6]


def _competitive(payload, profile, own_items, warnings):
    """Analyse selected public videos; compare each own item (concept or ad) via an evidence-tagged dimension table."""
    vids = payload.get("competitor_videos") or []
    perf = competitor_performance(payload.get("competitor_performance"))
    if not vids and not perf["available"]:
        return None
    aud = set(tokens(profile["audience"]))
    analyses = []
    seen = set()
    for v in vids:
        vid = v.get("video_id") or v.get("url") or v.get("title")
        if vid in seen:
            warnings.append(f"'{_s(v.get('title'), 80)}' was selected more than once; it was counted once.")
            continue
        seen.add(vid)
        v = {**v, "description": _s(v.get("description"), 6000), "title": _s(v.get("title"), 300) or "Untitled video"}
        url = safe_youtube_url(v.get("url") or "") if v.get("url") else None
        v["url"] = url
        a = analyse_public_video(v, _s(v.get("script_text"), 60000), aud)
        a["status"] = v.get("status") or "Relevant Public Video"
        a["verification_note"] = v.get("verification_note")
        a["verification"] = TR.sanitize_verification(v.get("verification"))
        vt = a["verification"]
        a["verification_basis"] = ("transparency_exact" if vt and vt["state"] == "verified_exact" and (vt["record"] or {}).get("matched_video_id") == v.get("video_id")
                                   else "user_confirmed" if a["status"] == "Verified Paid Ad" else "none")
        a["public_stats"] = {k: v.get(k) for k in ("public_views", "public_likes", "public_comments")} if a["origin"] == "youtube_api" else None
        a["retrieved_at"] = v.get("retrieved_at")
        a["channel"] = v.get("channel_title")
        analyses.append(a)
    block = {"analyses": analyses, "performance": perf, "comparisons": [], "depth_summary": {}, "verification_summary": TR.summarise(analyses)}
    for a in analyses:
        block["depth_summary"][a["depth"]] = block["depth_summary"].get(a["depth"], 0) + 1
    if analyses:
        for own in own_items[:4]:
            block["comparisons"].append({"for": own["name"], "kind": own["kind"], "dimensions": dimension_table(own["fields"], analyses, aud),
                                         "summary": compare_with_own(own["fields"], own.get("creative"), analyses)})
    return block


def _evidence_map(mode, measured, observed, unknown, hypotheses):
    return {"measured": measured, "observed": observed, "hypotheses": hypotheses, "unknown": unknown}


def _unknowns(competitive, measured_available):
    u = []
    if not measured_available:
        u.append("How real customers respond to these ads: no campaign results have been supplied.")
        u.append("Cost per click, cost per conversion and return: none has been observed, so none is estimated.")
    if competitive:
        u.append("Whether any selected video is or was a paid YouTube ad, unless it has an exact Transparency Center video-ID match or you recorded a source yourself.")
        u.append("How well any competitor video performed commercially. Public views and likes are not advertising results.")
        if any(a["depth"] != "transcript" for a in competitive["analyses"]):
            u.append("What is said in videos without a transcript, and the visuals, audio and editing of every video.")
    else:
        u.append("What competitors are doing: no reference videos were compared.")
    return u


# ------------------------------------------------------------------------------------------------ MODE: idea
def _run_idea(payload, profile, objective, strategy, ctx):
    warnings = []
    given = payload.get("concepts") or []
    if given:
        concepts = []
        for i, c in enumerate(given):
            c = {k: v for k, v in c.items() if k not in ("creative",)}
            c["id"] = _s(c.get("id"), 12) or f"c{i + 1}"
            for f in ("hook", "main_message", "offer", "cta", "title", "approach", "outline", "why_it_may_appeal", "landing_note", "audience", "archetype"):
                c[f] = _s(c.get(f), 600)
            c["audience"] = c["audience"] or profile["audience"]
            c["assumptions"] = [_s(x, 300) for x in (c.get("assumptions") or [])][:8] if isinstance(c.get("assumptions"), list) else []
            c["duration_seconds"] = _num(c.get("duration_seconds"))
            c["format"] = _s(c.get("format"), 20)
            c["label"] = "Creative proposal, not a tested ad"
            c["selected"] = bool(c.get("selected", True))
            c["creative"] = assess_concept(c, profile, objective)
            concepts.append(c)
    else:
        concepts = generate_concepts(profile, objective)
    selected = [c for c in concepts if c["selected"]]
    if not selected:
        raise ValueError("Select at least one concept to analyse.")
    own_url = payload.get("own_url")
    if own_url:
        safe = safe_youtube_url(own_url)
        if safe:
            profile["own_video_url"] = safe
        else:
            warnings.append("The link you entered for your own video is not a valid YouTube link, so it was ignored. It is optional.")
    competitive = _competitive(payload, profile, [{"name": c["title"], "kind": "concept", "fields": c, "creative": c["creative"]} for c in selected], warnings)
    b, total, currency = _budget_inputs(payload)
    plan = None
    plan_error = None
    sample = SAMPLE_FIELD.get(objective, "clicks")
    if total:
        try:
            plan = B.exploratory_plan(selected, total, currency, _num(b.get("test_share_pct")),
                                      f"Working minimum before comparing: about {MIN_SAMPLE[sample]:,} {sample} per concept.")
        except B.BudgetError as e:
            plan_error = str(e)
    test_budget = next((l["amount"] for l in (plan or {}).get("lines", []) if l["role"] == "test"), None)
    experiments = plan_concept_tests(selected, objective, strategy, test_budget, currency)
    if plan:
        experiments["test_budget"] = sum(l["amount"] for l in plan["lines"] if l["role"] == "test")
        experiments["test_budget_note"] = f"{currency} {experiments['test_budget']:,.0f} total, split equally across the concepts."
    observed = []
    if competitive and competitive["analyses"]:
        for comp in competitive["comparisons"][:1]:
            observed = [f"{d['dimension']}: {d['observed']}" for d in comp["dimensions"] if d.get("assessable")]
    actions = _actions_idea(selected, competitive, experiments, plan, total, profile)
    return {
        "ads": [], "evaluation": {"status": "not_applicable", "reasons": ["No advertisements or performance data were supplied, so no measured comparison exists."], "ranking": [], "metrics_used": [],
                                  "objective_label": OBJECTIVES[objective], "why_these_metrics": OBJECT_WHY(objective)},
        "best_performer": None, "provisional_leader": None, "next_test": experiments, "experiments": experiments,
        "concepts": concepts, "selected_concepts": [c["id"] for c in selected], "concept_generator": GENERATOR,
        "budget": None, "budget_plan": plan, "budget_error": plan_error, "competitive": competitive,
        "data_quality": {"validation": None, "warnings": warnings, "ads_without_data": []},
        "comparison_basis": {"measured": False, "creative_text": True, "public_video_text": bool(competitive and competitive["analyses"]),
                             "text": "This analysis uses your inputs and, where selected, the text of public videos. There is no measured campaign performance, so no concept is ranked as a proven winner."},
        "evidence_map": _evidence_map("idea", "None. No campaign results exist for these concepts.", observed, _unknowns(competitive, False),
                                      [f"{c['title']}: {c['why_it_may_appeal']}" for c in selected[:3]]),
        "next_actions": actions,
        "explanations": _explain_idea(selected, competitive, experiments, plan, strategy),
        "improve_with": ["A real product benefit and the problem it solves, in your customers' words.", "Competitor transcripts or scripts for deeper comparison.",
                         "Measured results from a small test, then re-run AdPilot in 'I already have advertisements' mode."],
    }


def OBJECT_WHY(objective):
    return OBJECTIVE_SPECS[objective]["why"]


def _actions_idea(selected, comp, exp, plan, total, profile):
    acts = []
    if any("[" in (c["hook"] + c["main_message"] + c["offer"]) for c in selected):
        acts.append({"action": "Fill in the [bracketed] parts of your chosen concepts with facts you can prove.", "why": "Templates cannot know your real results, offers or customer stories.", "basis": "Your inputs"})
    if not comp or not comp["analyses"]:
        acts.append({"action": "Add a few competitor reference videos (automatic search or a pasted link).", "why": "Without references, AdPilot cannot say how your concepts differ from what the audience already sees.", "basis": "Missing evidence"})
    else:
        gaps = []
        for d in comp["comparisons"][0]["dimensions"] if comp["comparisons"] else []:
            if d.get("assessable") and d.get("share", 0) >= 0.5 and d["yours"] == "no" and d["key"] != "hook":
                gaps.append(d)
        for d in gaps[:2]:
            acts.append({"action": f"Create a variation of your leading concept that adds {d['dimension'].lower()}, and test it against the original.",
                         "why": d["observed"] + " This is a hypothesis to test; the references' results are unknown.", "basis": "Public video text (observed) plus a hypothesis"})
        if any(a["depth"] != "transcript" for a in comp["analyses"]):
            acts.append({"action": "Paste transcripts for the most relevant references.", "why": "Hooks and spoken calls to action cannot be compared without them. The YouTube Data API does not supply transcripts for other people's videos.", "basis": "Analysis limitation"})
        vs = comp.get("verification_summary") or {}
        if vs.get("reference_only"):
            acts.append({"action": f"Treat the {vs['reference_only']} unverified reference(s) as public reference content, not as competitor ads.", "why": "They were not matched to a Transparency Center creative by exact video ID and not confirmed by you. They show creative patterns in public videos, not what competitors pay to run. Run the Transparency Center check or add a source to upgrade them.", "basis": "Verification limit"})
        elif any(a["status"] == "Potential Advertising Creative" for a in comp["analyses"]):
            acts.append({"action": "Check the references you rely on in the Google Ads Transparency Center before calling them competitor ads.", "why": "AdPilot cannot confirm paid-ad status from public data.", "basis": "Verification limit"})
    acts.append({"action": f"Run the concept test: {exp['headline'].lower()}.", "why": exp["hypothesis"], "basis": "Experiment design (hypothesis)"})
    if plan:
        held = next((l for l in plan["lines"] if l["role"] == "held"), None)
        if held:
            acts.append({"action": "Hold the remaining budget until the test shows which concept deserves it.", "why": "No concept has evidence yet, so spending everything now would be a guess.", "basis": "Exploratory plan"})
    else:
        acts.append({"action": "Set a budget to see an exploratory testing plan.", "why": "The plan splits a first test pool equally and holds the rest back.", "basis": "Missing input"})
    acts.append({"action": "After the test, enter the real results and re-run AdPilot in 'I already have advertisements' mode.", "why": "That is when AdPilot can compare measured performance and allocate budget on evidence.", "basis": "Next stage"})
    return acts


def _explain_idea(selected, comp, exp, plan, strategy):
    out = [{"title": "Concept proposals", "recommendation": "Compare " + ", ".join(c["title"] for c in selected) + ".",
            "why": "Each proposal uses a different approach from this industry's framework so the test teaches you something.", "basis": "Your inputs and industry hypotheses (rule-based templates, no AI model)",
            "data": "Product, audience, benefit, objective and the industry framework.", "assumptions": ["Claims must be substantiated by you.", "Checklist scores are heuristics, not predictions."],
            "to_improve": "Add the real problem, benefit, offer and proof points."}]
    out.append({"title": "Test plan", "recommendation": exp["headline"] + ".", "why": exp["hypothesis"], "basis": "Experiment design (hypothesis)",
                "data": exp["evidence_basis"], "assumptions": [exp["minimum_sample"]], "to_improve": "Real campaign results after the first test."})
    if plan:
        out.append({"title": "Budget plan", "recommendation": f"Use {plan['test_share_pct']:g}% for an equal-split test and hold the rest.", "why": plan["lines"][0]["reasons"][0],
                    "basis": "Exploratory assumption (no measured data)", "data": "Total budget and number of concepts only.", "assumptions": plan["notes"][:1], "to_improve": "Measured cost per click and conversion after the test."})
    return out


# ------------------------------------------------------------------------------------------------ MODE: existing
def _run_existing(payload, profile, objective, strategy, ctx):
    ads_in = list(payload.get("ads") or [])
    names = [_s(a.get("name"), 120) for a in ads_in]
    if any(not n for n in names):
        raise ValueError("Every advertisement needs a name.")
    if len(set(n.lower() for n in names)) != len(names):
        raise ValueError("Advertisement names must be unique so results can be matched to the right ad.")
    validation, csv_by_ad = None, {}
    if payload.get("csv_text"):
        validation = validate_csv_text(_s(payload["csv_text"], 8_000_000))
        if validation["errors"]:
            validation["clean_rows"] = []
        for r in validation["clean_rows"]:
            csv_by_ad.setdefault(r["ad_name"].strip().lower(), []).append(r)
    warnings = list((validation or {}).get("warnings", []))
    manual = {n.lower() for n in names}
    for key, rows in csv_by_ad.items():
        if key not in manual:
            ads_in.append({"name": rows[0]["ad_name"], "_from_csv": True})
            warnings.append(f"'{rows[0]['ad_name']}' appears in the uploaded data but was not added as an advertisement; it was added automatically without creative details.")

    ads, creatives, eval_input = [], {}, []
    for i, a in enumerate(ads_in):
        ad_id = f"ad{i + 1}"
        name = _s(a.get("name"), 120)
        perf = a.get("performance") if isinstance(a.get("performance"), dict) else {}
        bad = [f for f in ALL_NUMERIC if perf.get(f) not in (None, "") and _num(perf.get(f)) is None]
        if bad:
            warnings.append(f"'{name}': {', '.join(bad)} could not be read as numbers and were treated as unknown (not zero).")
        rows = csv_by_ad.get(name.strip().lower())
        totals, source = None, None
        if rows:
            totals = aggregate_rows(rows); source = f"uploaded CSV ({len(rows)} records)"
            if any(_num(perf.get(f)) is not None for f in ALL_NUMERIC):
                warnings.append(f"'{name}': both typed totals and uploaded rows were supplied; the uploaded rows were used.")
        elif any(_num(perf.get(f)) is not None for f in ALL_NUMERIC):
            t = {f: _num(perf.get(f)) for f in ALL_NUMERIC}
            if t.get("clicks") is not None and t.get("impressions") is not None and t["clicks"] > t["impressions"]:
                warnings.append(f"'{name}': clicks exceed impressions in the typed totals; these figures were excluded from analysis.")
            elif any(v is not None and v < 0 for v in t.values()):
                warnings.append(f"'{name}': negative values in the typed totals; these figures were excluded from analysis.")
            else:
                totals = {**t, "_coverage": {f: [1 if t[f] is not None else 0, 1] for f in ALL_NUMERIC}, "row_count": 1}
                source = "typed totals"
        creative = None
        url = None
        if a.get("url"):
            url = safe_youtube_url(a["url"])
            if not url:
                warnings.append(f"'{name}': the video link is not a valid YouTube link, so it was ignored. The link is optional.")
        if not a.get("_from_csv"):
            creative = assess_creative({"hook": _s(a.get("hook")), "main_message": _s(a.get("main_message")), "offer": _s(a.get("offer")), "cta": _s(a.get("cta")),
                                        "creative_approach": _s(a.get("creative_approach")), "landing_note": _s(a.get("landing_note")),
                                        "duration_seconds": _num(a.get("duration_seconds")), "format": _s(a.get("format"), 20), "audience": _s(a.get("audience"))}, ctx)
            creatives[ad_id] = creative
        eval_input.append({"id": ad_id, "name": name, "totals": totals})
        ads.append({"id": ad_id, "name": name, "url": url, "data_source": source, "creative": creative,
                    "fields": {"hook": _s(a.get("hook")), "main_message": _s(a.get("main_message")), "offer": _s(a.get("offer")), "cta": _s(a.get("cta"))}})

    evaluation = evaluate_ads(eval_input, objective)
    spec = OBJECTIVE_SPECS[objective]
    b, total, currency = _budget_inputs(payload)
    reserve_amount, reserve_pct = _num(b.get("reserve_amount")), _num(b.get("reserve_pct"))
    if reserve_amount is not None:
        reserve_pct = None
    res_for_test = reserve_amount if reserve_amount is not None else ((total or 0) * reserve_pct / 100 if reserve_pct is not None and total else None)
    next_test = recommend_next_test(evaluation, creatives, strategy, objective, total or 0, res_for_test, currency)
    budget_out, budget_error = None, None
    if total:
        kw = {"min_alloc": _num(b.get("min_per_ad")), "max_alloc": _num(b.get("max_per_ad")), "reserve_amount": reserve_amount, "reserve_pct": reserve_pct}
        scen = B.scenarios(evaluation, creatives, next_test, total, currency, **kw)
        chosen = b.get("scenario") if b.get("scenario") in B.SCENARIOS else "balanced"
        budget_out = {"scenarios": scen, "selected": chosen, "sensitivity": B.sensitivity(evaluation, creatives, next_test, total, currency, scenario=chosen, **kw)}
        errs = [s["error"] for s in scen.values() if "error" in s]
        if errs and len(errs) == len(scen):
            budget_error = errs[0]
    if budget_out and next_test.get("status") == "ok" and next_test.get("test_budget") is None:
        sel = budget_out["scenarios"].get(budget_out["selected"], {})
        if "lines" in sel:
            next_test["test_budget"] = sel["reserve"]
            next_test["test_budget_note"] = f"{currency} {sel['reserve']:,.0f} comes from the {sel['scenario_label']} scenario's default reserve (you did not set one)."

    own_items = [{"name": a["name"], "kind": "ad", "fields": a["fields"], "creative": a["creative"]} for a in ads if a["creative"]]
    competitive = _competitive(payload, profile, own_items, warnings)
    by_id = {r["id"]: r for r in evaluation["ads"]}
    for a in ads:
        r = by_id[a["id"]]
        a["metrics"], a["missing_metrics"], a["evidence"] = r["metrics"], r["missing"], r["evidence"]
        a["totals"] = {k: v for k, v in (r["totals"] or {}).items() if not k.startswith("_")} if r["totals"] else None
        a["objective_score"] = r.get("objective_score")
        a.pop("fields", None)
    n_data = sum(1 for a in ads if a["totals"])
    basis = {"measured": n_data >= 2, "creative_text": bool(creatives), "public_video_text": bool(competitive and competitive["analyses"])}
    parts = []
    if n_data >= 2: parts.append(f"measured campaign results from {n_data} ads (these decide the ranking)")
    elif n_data == 1: parts.append("measured results for only one ad (nothing to rank it against)")
    if creatives: parts.append("the creative text you entered (checklist only; it never changes the measured ranking)")
    if basis["public_video_text"]: parts.append("public competitor video text")
    basis["text"] = "This comparison is based on " + (", ".join(parts) if parts else "the limited inputs supplied") + "."
    best = evaluation.get("best_performer")
    quality = {"validation": None if not validation else {"summary": validation["summary"], "errors": validation["errors"], "excluded": validation["excluded"][:200]},
               "warnings": warnings, "ads_without_data": [a["name"] for a in ads if not a["data_source"]]}
    observed = []
    if competitive and competitive["comparisons"]:
        observed = [f"{d['dimension']}: {d['observed']}" for d in competitive["comparisons"][0]["dimensions"] if d.get("assessable")]
    measured_txt = (f"Best performer: {best['name']}." if best else "No reliable winner; evidence inconclusive.") if n_data >= 2 else "Not enough ads with measured data to compare."
    return {
        "ads": ads, "evaluation": {k: v for k, v in evaluation.items() if k != "ads"}, "best_performer": best, "provisional_leader": evaluation.get("provisional_leader"),
        "next_test": next_test, "budget": budget_out, "budget_error": budget_error, "budget_plan": None, "competitive": competitive, "data_quality": quality,
        "comparison_basis": basis, "concepts": [], "experiments": None,
        "evidence_map": _evidence_map("existing", measured_txt, observed, _unknowns(competitive, n_data > 0), [next_test.get("hypothesis")] if next_test.get("status") == "ok" else []),
        "next_actions": _actions_existing(evaluation, best, next_test, quality, competitive, n_data),
        "explanations": _explain_existing(evaluation, next_test, budget_out, strategy),
        "improve_with": ["Results for every ad over the same dates and audience.", "More conversions or clicks per ad (see the evidence notes).", "Transcripts for competitor references."],
    }


def _actions_existing(ev, best, nt, quality, comp, n_data):
    acts = []
    if best:
        acts.append({"action": f"Keep funding '{best['name']}' and check before scaling.", "why": "It has the strongest measured results for this objective with adequate evidence. Check that audience, dates and attribution were comparable.", "basis": "Measured campaign performance"})
    elif n_data >= 2:
        acts.append({"action": "Collect more comparable data before moving budget.", "why": " ".join(ev["reasons"]) or "The difference is too small or the sample too thin.", "basis": "Measured campaign performance (inconclusive)"})
    elif n_data == 1:
        acts.append({"action": "Add results for a second ad (or a new variation) so there is something to compare.", "why": "A single ad cannot be ranked.", "basis": "Missing evidence"})
    else:
        acts.append({"action": "Enter or upload campaign results to unlock measured comparisons.", "why": "Without them AdPilot can only give creative feedback.", "basis": "Missing evidence"})
    if nt.get("status") == "ok":
        acts.append({"action": f"Test: {nt['what_to_change']} on '{nt['ad_name']}'.", "why": nt["why"], "basis": "Creative checklist, uncertainty and industry hypothesis"})
    if quality["validation"] and quality["validation"]["summary"]["excluded_rows"]:
        acts.append({"action": "Fix or confirm the excluded CSV rows.", "why": f"{quality['validation']['summary']['excluded_rows']} rows were left out of the analysis; see Data quality.", "basis": "Data validation"})
    if comp and comp["analyses"]:
        acts.append({"action": "Review the competitor comparison for gaps worth testing.", "why": "Differences in the text of public videos are hypotheses, not evidence that a change will help. They never override your measured results.", "basis": "Public video text"})
    return acts


def _explain_existing(evaluation, next_test, budget_out, strategy):
    items = []
    best = evaluation.get("best_performer")
    if best:
        items.append({"title": "Best-performing advertisement", "recommendation": f"'{best['name']}' has the strongest measured results for {evaluation['objective_label'].lower()}.",
                      "why": evaluation["why_these_metrics"], "data": f"Metrics compared: {', '.join(evaluation['metrics_used'])}. Gap to runner-up: {evaluation.get('margin')}.",
                      "assumptions": evaluation["reasons"], "to_improve": "More conversions and a longer run time strengthen the call; keep audience and dates comparable.", "basis": "Measured campaign performance"})
    else:
        items.append({"title": "Best-performing advertisement", "recommendation": "No reliable winner can be named yet.", "why": " ".join(evaluation["reasons"]) or "There is not enough comparable data.",
                      "data": "Evidence is inconclusive.", "assumptions": [], "to_improve": "Upload historical results for every ad, using the same date range, or run the suggested test.", "basis": "Measured campaign performance (insufficient)"})
    if next_test.get("status") == "ok":
        items.append({"title": "Best advertisement to test next", "recommendation": f"Test a change to '{next_test['ad_name']}': {next_test['what_to_change']}", "why": next_test["why"], "data": next_test["evidence_basis"],
                      "assumptions": ["The hypothesis is untested; creative checklist scores are heuristics."], "to_improve": "Supply performance data and a transcript to sharpen the test choice.", "basis": "Creative assessment + uncertainty + industry hypothesis"})
    if budget_out:
        sel = budget_out["scenarios"].get(budget_out["selected"], {})
        if "lines" in sel:
            top = max(sel["lines"], key=lambda l: l["amount"])
            items.append({"title": "Budget allocation", "recommendation": f"{sel['scenario_label']} scenario: largest share goes to '{top['name']}' ({top['percent']}%).",
                          "why": "Proven budget follows measured objective score and evidence strength; the reserve funds testing.", "data": f"Mode: {sel['mode']}; reserve {sel['currency']} {sel['reserve']:,.0f}.",
                          "assumptions": sel["notes"], "to_improve": "More historical data per advertisement moves ads from test to established.", "basis": "Measured performance" if sel["mode"] == "evidence-based" else "Exploratory assumptions"})
    items.append({"title": "Category strategy", "recommendation": f"For {strategy['label'].lower()}, compare: " + ", ".join(strategy["approaches"][:4]) + ".", "why": strategy["objective_note"],
                  "data": "Configurable industry hypotheses.", "assumptions": ["Hypotheses, not rules; evidence from your own campaigns overrides them."], "to_improve": strategy["budget_notes"], "basis": "Industry-level hypotheses"})
    return items
