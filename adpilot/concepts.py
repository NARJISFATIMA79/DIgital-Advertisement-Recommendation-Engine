"""Rule-based advertising concept generator for people who have no advertisement yet.

HONEST LABEL: this is NOT an AI model. It fills editable templates with the words the user supplied and with the
industry framework in strategy.py. Output is a set of creative PROPOSALS to test. Nothing here predicts results,
and no performance numbers are produced. Where a fact is needed (a result, a proof point, an offer) the template
leaves a [bracket] for the user to fill with something they can substantiate.
"""
from __future__ import annotations
import re

from .creative import assess_creative
from .strategy import OBJECTIVES, strategy_for

GENERATOR = {"type": "rule_based_templates", "ai_model_used": False,
             "note": "Concepts are built from editable templates and the information you entered. No AI model was used and nothing was tested."}

# order of archetypes per objective (first three are pre-selected)
ORDER = {
    "sales": ["problem_solution", "demonstration", "customer_story", "offer_led", "explainer"],
    "leads": ["problem_solution", "explainer", "customer_story", "offer_led", "demonstration"],
    "traffic": ["problem_solution", "explainer", "offer_led", "demonstration", "customer_story"],
    "awareness": ["customer_story", "demonstration", "problem_solution", "explainer", "offer_led"],
    "reach": ["customer_story", "demonstration", "problem_solution", "explainer", "offer_led"],
    "engagement": ["demonstration", "customer_story", "explainer", "problem_solution", "offer_led"],
    "consideration": ["explainer", "demonstration", "customer_story", "problem_solution", "offer_led"],
}
# words used to match an archetype to this industry's own approach names (strategy.py)
APPROACH_KEYS = {
    "problem_solution": ["problem"], "demonstration": ["demonstration", "showcase", "walkthrough", "preparation", "tutorial", "unboxing", "routine", "sample lesson"],
    "customer_story": ["testimonial", "customer", "student", "case study", "creator"],
    "offer_led": ["offer", "promotion", "free-trial", "booking", "seasonal"], "explainer": ["explanation", "explainer", "instructor", "agent", "features", "comparison", "menu"],
}
TITLES = {"problem_solution": "Problem and solution", "demonstration": "Product demonstration", "customer_story": "Customer story",
          "offer_led": "Offer-led", "explainer": "Expert explainer"}
FORMAT = {"problem_solution": ("skippable", 30), "demonstration": ("skippable", 45), "customer_story": ("skippable", 60), "offer_led": ("non_skippable", 20), "explainer": ("skippable", 60)}

CTA = {
    "sales": {"default": "Shop now", "food": "Order now", "real_estate": "Book a viewing", "software": "Start your free trial", "education": "Enrol today"},
    "leads": {"default": "Get in touch", "education": "Try a free lesson", "real_estate": "Book a viewing", "software": "Book a demo", "food": "Book a table"},
    "traffic": {"default": "Learn more"}, "awareness": {"default": "Watch more"}, "reach": {"default": "Watch more"},
    "engagement": {"default": "Subscribe for more"}, "consideration": {"default": "See how it works"},
}


def _cap(s):
    s = (s or "").strip()
    return s[0].upper() + s[1:] if s else s


def _lc(s):
    s = (s or "").strip()
    return s[0].lower() + s[1:] if s else s


def _clean(s, n=300):
    return re.sub(r"\s+", " ", (s or "")).strip()[:n]


def _approach_name(archetype, strategy):
    for a in strategy["approaches"]:
        if any(k in a.lower() for k in APPROACH_KEYS[archetype]):
            return a
    return TITLES[archetype]


def _cta(objective, industry):
    d = CTA.get(objective, CTA["sales"])
    return d.get(industry, d["default"])


def generate_concepts(profile: dict, objective: str, count: int = 4) -> list:
    """Return up to `count` differentiated concept proposals (plus the user's own idea first, if they gave a hook)."""
    prod = _clean(profile.get("product")) or "your product"
    industry = profile.get("industry") or "other"
    st = strategy_for(industry, objective)
    benefit, problem = _clean(profile.get("benefit")), _clean(profile.get("problem"))
    aud = _clean(profile.get("audience"), 120)
    aud_short = " ".join(aud.split()[:6]) if aud else "your audience"
    offer = _clean(profile.get("offer"), 120)
    market = _clean(profile.get("market"), 60)
    ctx = {"objective": objective, "product": prod, "audience": aud, "industry_label": st["label"], "approaches": st["approaches"]}
    BEN = _cap(benefit) if benefit else f"[the main benefit of {prod}]"
    msg = f"{_cap(prod)}: {benefit}." if benefit else f"[State the one main benefit of {prod} in one sentence.]"
    cta = _cta(objective, industry)
    PRO = problem if problem else "[the problem your audience has]"
    T = {  # hook options and rationale per archetype; brackets mark facts only the user can supply
        "problem_solution": dict(
            hooks=[f"Still dealing with {PRO}? Here is a simpler way." if problem else (f"{BEN}. That is what {prod} is for." if benefit else f"Before you pick another {prod}, watch this."),
                   f"Before you pick another {prod}, watch this." if (problem or benefit) else f"What to know before buying {prod}.",
                   f"{_cap(aud_short)}: the one thing to check when choosing {prod}."],
            outline=f"0-5s name the problem in the viewer's words; 5-20s show {prod} addressing it; end with proof you can substantiate and the call to action.",
            why=f"Names a need before the product, so viewers who share it recognise themselves quickly. Hypothesis: relevance in the first seconds helps {aud_short} decide to keep watching."),
        "demonstration": dict(
            hooks=[f"Watch how {prod} works, step by step.", f"Here is {prod} in use, start to finish.", f"See {prod} in action in the first five seconds."],
            outline=f"Open on {prod} being used; show the benefit ({_lc(benefit) if benefit else 'the result you can truthfully show'}) on screen; finish with the call to action.",
            why="Shows rather than tells, which may reduce doubt for products people want to see working. Hypothesis to test, not a known effect."),
        "customer_story": dict(
            hooks=[f"I tried {prod} for [time period]. Here is what happened.", f"Why I switched to {prod}.", f"Three questions people ask about {prod}, answered by someone who uses it."],
            outline=f"A real customer or creator describes the problem, using {prod}, and what changed, in their own words. Only use real, permitted testimonials.",
            why=f"Peer voices can feel more credible than brand voices to {aud_short}. Requires a genuine customer; do not script claims they did not make."),
        "offer_led": dict(
            hooks=[f"{offer} on {prod}. Here is what you get." if offer else f"[Your offer] on {prod}. Here is what you get.",
                   f"{_cap(prod)}: [offer], and why now is a good time to try it.", f"A reason to try {prod} today: [offer]."],
            outline=f"Lead with the offer and its terms, show {prod} briefly, repeat the offer with the call to action. Only run an offer you can honour.",
            why="Gives a concrete reason to act now, which is often tested for conversion-focused goals. May attract discount-driven buyers; compare cost per acquisition, not clicks."),
        "explainer": dict(
            hooks=[f"How to choose {prod}: three things to look for.", f"What most people get wrong about {prod}.", f"{_cap(prod)} explained in under a minute."],
            outline=f"An expert or founder explains how to choose {prod}, builds credibility with facts you can substantiate, then invites the next step.",
            why="Educates before selling, which can suit considered purchases. Hypothesis: clarity and credibility lower hesitation."),
    }
    out, n = [], 0
    own_hook = _clean(profile.get("initial_hook"), 200)
    if own_hook:
        n += 1
        out.append(_build(f"c{n}", "your_idea", "Your own idea", own_hook, [own_hook], msg, offer, cta, "Your own structure. Compare it with the alternatives before you commit.",
                          "You provided this hook. AdPilot will check it against the same checklist and the competitor references.", ctx, st, profile, objective, mine=True))
    for arch in ORDER.get(objective, ORDER["sales"]):
        if len(out) >= count:
            break
        t = T[arch]
        n += 1
        out.append(_build(f"c{n}", arch, _approach_name(arch, st), t["hooks"][0], t["hooks"], msg, offer if arch != "offer_led" or offer else "", cta, t["outline"], t["why"], ctx, st, profile, objective))
    for i, c in enumerate(out):
        c["selected"] = i < 3
    return out


def _build(cid, arch, approach, hook, hooks, msg, offer, cta, outline, why, ctx, st, profile, objective, mine=False, **kw):
    fmt, dur = FORMAT.get(arch, ("skippable", 30))
    assumptions = [
        "Your audience actually has the problem or wants the benefit described (validate with a few real customers or search/comment evidence).",
        "Every claim in the ad can be substantiated and complies with advertising rules in your market.",
        "The landing page repeats the same offer and message the ad promises.",
        f"The suggested {fmt.replace('_', ' ')} format and about {dur} seconds are starting assumptions; check current YouTube format rules.",
    ]
    if "[" in hook or "[" in msg or (offer and "[" in offer):
        assumptions.insert(0, "Fill in the [bracketed] parts with real facts before using this.")
    c = {"id": cid, "archetype": arch, "title": approach, "approach": approach, "hook": hook, "hook_options": hooks, "main_message": msg,
         "offer": offer, "cta": cta, "outline": outline, "why_it_may_appeal": why, "assumptions": assumptions,
         "format": fmt, "duration_seconds": dur, "label": "Creative proposal, not a tested ad", "is_user_idea": mine,
         "audience": profile.get("audience", ""), "creative_approach": approach, "landing_note": ""}
    c["creative"] = assess_creative({"hook": hook, "main_message": msg, "offer": offer, "cta": cta, "creative_approach": approach, "landing_note": "",
                                     "duration_seconds": dur, "format": fmt, "audience": profile.get("audience", "")}, ctx)
    return c


def assess_concept(concept: dict, profile: dict, objective: str) -> dict:
    """Re-run the checklist on a concept after the user edits it."""
    st = strategy_for(profile.get("industry") or "other", objective)
    ctx = {"objective": objective, "product": profile.get("product", ""), "audience": profile.get("audience", ""), "industry_label": st["label"], "approaches": st["approaches"]}
    return assess_creative({"hook": concept.get("hook", ""), "main_message": concept.get("main_message", ""), "offer": concept.get("offer", ""), "cta": concept.get("cta", ""),
                            "creative_approach": concept.get("approach", ""), "landing_note": concept.get("landing_note", ""),
                            "duration_seconds": concept.get("duration_seconds"), "format": concept.get("format"), "audience": concept.get("audience", "")}, ctx)
