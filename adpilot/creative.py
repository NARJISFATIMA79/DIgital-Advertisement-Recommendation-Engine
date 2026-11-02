"""Rule-based creative assessment from the information the user supplies.

This is a transparent HEURISTIC checklist. It is not a trained model, it does not watch
video, and a high score is not a prediction of commercial success. Each dimension returns
a score (0-100) or None when there is no evidence, plus the evidence used.
"""
from __future__ import annotations
import re

DIMENSIONS = [
    ("hook", "Opening hook"), ("clarity", "Message clarity"), ("presentation", "Product or service presentation"),
    ("audience", "Audience relevance"), ("value", "Value proposition"), ("cta", "Call-to-action clarity"),
    ("objective", "Alignment with the objective"), ("landing", "Ad-to-landing-page alignment"),
    ("format", "Suitability for the video format"),
]
ACTION_VERBS = ["shop", "buy", "order", "book", "enrol", "enroll", "register", "sign up", "subscribe", "start", "try", "get", "download",
                "learn more", "visit", "call", "claim", "join", "watch", "contact", "reserve", "see"]
OBJECTIVE_CTA = {
    "sales": ["shop", "buy", "order", "get", "claim", "reserve"],
    "leads": ["book", "register", "sign up", "enrol", "enroll", "contact", "call", "download", "reserve", "try"],
    "traffic": ["visit", "learn more", "see", "shop", "try", "download"],
    "awareness": ["watch", "subscribe", "learn more", "see", "visit"],
    "reach": ["watch", "subscribe", "learn more", "see"],
    "engagement": ["watch", "subscribe", "join", "see", "learn more"],
    "consideration": ["learn more", "see", "try", "visit", "watch", "download"],
}
BENEFIT_WORDS = ["save", "free", "faster", "easier", "better", "new", "guarantee", "results", "discount", "off", "%", "only", "limited", "learn", "win", "improve", "fresh", "premium"]
PROBLEM_WORDS = ["tired", "struggling", "problem", "stop", "never", "why", "how", "?", "mistake", "secret", "imagine", "what if"]
# Format duration ranges (seconds) are configurable starting points, not YouTube rules.
FORMAT_RANGES = {"bumper": (1, 6), "shorts": (5, 60), "skippable": (12, 180), "non_skippable": (6, 30), "in_feed": (10, 120), "unknown": None}


def _words(text):
    return re.findall(r"[a-z0-9%']+", (text or "").lower())


def _has_any(text, terms):
    t = (text or "").lower()
    return [w for w in terms if w in t]


def _dim(score, confidence, evidence):
    return {"score": None if score is None else int(max(0, min(100, round(score)))), "confidence": confidence, "evidence": evidence}


def assess_creative(ad: dict, ctx: dict) -> dict:
    """ad: dict of creative fields; ctx: business/campaign context (objective, product, audience, industry)."""
    hook, msg, offer, cta = ad.get("hook", ""), ad.get("main_message", ""), ad.get("offer", ""), ad.get("cta", "")
    approach, landing = ad.get("creative_approach", ""), ad.get("landing_note", "")
    duration, fmt = ad.get("duration_seconds"), ad.get("format") or "unknown"
    objective = ctx.get("objective", "sales")
    ctx_terms = set(_words(" ".join([ctx.get("product", ""), ctx.get("audience", ""), ctx.get("industry_label", "")]))) - {"the", "and", "for", "of", "a", "to", "in", "aged", "age"}
    out = {}

    # hook
    if not hook.strip():
        out["hook"] = _dim(None, "none", "No opening hook was described, so this dimension is unavailable.")
    else:
        s, ev = 40, []
        n = len(_words(hook))
        if 4 <= n <= 25:
            s += 20; ev.append(f"Hook is {n} words, short enough to land quickly.")
        else:
            ev.append(f"Hook is {n} words; very short or very long hooks are harder to evaluate.")
        if _has_any(hook, PROBLEM_WORDS):
            s += 20; ev.append("Names a problem or raises a question.")
        if _has_any(hook, BENEFIT_WORDS) or re.search(r"\d", hook):
            s += 20; ev.append("Contains a concrete benefit, number or offer.")
        out["hook"] = _dim(s, "moderate", " ".join(ev))

    # clarity
    if not msg.strip():
        out["clarity"] = _dim(None, "none", "No main message was provided.")
    else:
        n = len(_words(msg)); s = 50; ev = [f"Main message is {n} words."]
        if 5 <= n <= 22:
            s += 30; ev.append("Short enough to be a single idea.")
        elif n > 40:
            s -= 10; ev.append("Long messages often carry more than one idea.")
        if msg.count(",") + msg.count(";") <= 2:
            s += 10
        out["clarity"] = _dim(s, "moderate", " ".join(ev))

    # presentation
    strat_approaches = [a.lower() for a in ctx.get("approaches", [])]
    if not approach.strip():
        out["presentation"] = _dim(None, "none", "No creative approach selected.")
    elif approach.lower() in strat_approaches:
        out["presentation"] = _dim(75, "low", f"'{approach}' is one of the approaches in this category's strategy framework (a hypothesis, not proof).")
    else:
        out["presentation"] = _dim(55, "low", f"'{approach}' is not in this category's framework; it may still work and is worth testing.")

    # audience
    blob = " ".join([hook, msg, offer, ad.get("audience", "")])
    if not blob.strip() or not ctx_terms:
        out["audience"] = _dim(None, "none", "Not enough text or business context to compare against the target audience.")
    else:
        overlap = sorted(ctx_terms & set(_words(blob)))
        s = 40 + min(len(overlap), 4) * 12
        out["audience"] = _dim(s, "low", f"Shares {len(overlap)} term(s) with your product/audience description" + (f": {', '.join(overlap[:5])}." if overlap else ". Consider addressing the audience directly."))

    # value
    vp = " ".join([offer, msg])
    if not vp.strip():
        out["value"] = _dim(None, "none", "No offer or message supplied.")
    else:
        hits = _has_any(vp, BENEFIT_WORDS)
        s = 35 + (25 if offer.strip() else 0) + min(len(hits), 3) * 13
        out["value"] = _dim(s, "moderate", ("Offer stated. " if offer.strip() else "No explicit offer. ") + (f"Benefit terms found: {', '.join(hits[:4])}." if hits else "No benefit terms found."))

    # cta
    if not cta.strip():
        out["cta"] = _dim(None, "none", "No call to action supplied.")
    else:
        verbs = _has_any(cta, ACTION_VERBS); n = len(_words(cta))
        s = 30 + (35 if verbs else 0) + (20 if n <= 6 else 5) + (10 if re.search(r"\b(now|today|free|trial|offer)\b", cta.lower()) else 0)
        out["cta"] = _dim(s, "moderate", (f"Starts with an action ({', '.join(verbs[:2])}). " if verbs else "No clear action verb. ") + f"{n} words.")

    # objective alignment
    if not cta.strip():
        out["objective"] = _dim(None, "none", "Needs a call to action to judge alignment with the objective.")
    else:
        wanted = OBJECTIVE_CTA.get(objective, [])
        m = _has_any(cta, wanted)
        out["objective"] = _dim(80 if m else 40, "low", f"CTA {'matches' if m else 'does not obviously match'} a '{objective}' objective" + (f" (found: {', '.join(m[:2])})." if m else f"; expected actions such as {', '.join(wanted[:3])}."))

    # landing alignment
    if not landing.strip():
        out["landing"] = _dim(None, "none", "No landing-page description supplied.")
    else:
        lt = set(_words(landing)); at = set(_words(" ".join([msg, offer, cta]))) - {"the", "a", "and", "to", "of"}
        ov = sorted(lt & at)
        out["landing"] = _dim(40 + min(len(ov), 4) * 15, "low", f"Landing description shares {len(ov)} key term(s) with the ad" + (f": {', '.join(ov[:5])}." if ov else ". Check that the offer and wording match."))

    # format
    rng = FORMAT_RANGES.get(fmt)
    if duration in (None, "") or not rng:
        out["format"] = _dim(None, "none", "Needs both a format and a duration.")
    else:
        d = float(duration)
        ok = rng[0] <= d <= rng[1]
        out["format"] = _dim(85 if ok else 35, "low", f"{d:g}s is {'inside' if ok else 'outside'} the configured {rng[0]}-{rng[1]}s range for '{fmt}'. Ranges are working assumptions; check current YouTube format rules.")

    avail = {k: v for k, v in out.items() if v["score"] is not None}
    overall = round(sum(v["score"] for v in avail.values()) / len(avail)) if avail else None
    cov = len(avail) / len(DIMENSIONS)
    weakest = sorted(avail.items(), key=lambda kv: kv[1]["score"])[:3]
    strongest = sorted(avail.items(), key=lambda kv: -kv[1]["score"])[:2]
    labels = dict(DIMENSIONS)
    return {
        "overall": overall, "coverage": round(cov, 2),
        "confidence": "limited" if cov < 0.4 else ("moderate" if cov < 0.8 else "good"),
        "dimensions": {k: {"label": labels[k], **out[k]} for k, _ in DIMENSIONS},
        "weakest": [k for k, _ in weakest], "strongest": [k for k, _ in strongest],
        "disclaimer": "Rule-based checklist over the text you supplied. It does not watch the video and is not a validated predictor of results.",
    }
