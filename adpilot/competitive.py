"""Creative comparison between the customer's ad and selected public videos.

Only legitimately accessible text is analysed: the public title, description, and any script or
transcript the user pastes/uploads. The system never claims to have watched a video.
Competitor performance is NEVER inferred from views, likes or comments.
"""
from __future__ import annotations
import re

from .creative import ACTION_VERBS, BENEFIT_WORDS, PROBLEM_WORDS, _has_any, _words
from .metrics import compute_metrics

OFFER_RE = re.compile(r"(\d+\s?%|\bfree\b|\bdiscount\b|\bsale\b|\boff\b|\bbundle\b|\btrial\b|\blimited\b|\bgift\b)", re.I)
PROOF_WORDS = ["review", "rated", "dermatolog", "certified", "award", "customers", "trusted", "clinically", "tested", "guarantee", "years"]
STRUCTURE_CUES = {
    "problem-solution": PROBLEM_WORDS,
    "demonstration": ["how to", "watch", "demo", "step", "apply", "use", "try"],
    "testimonial": ["i love", "my favourite", "my favorite", "customer", "review", "told me", "changed my"],
    "offer-led": ["% off", "sale", "discount", "free", "limited time", "bundle"],
    "storytelling": ["story", "journey", "imagine", "once", "meet", "behind"],
}


def _first_sentence(text, max_words=25):
    s = re.split(r"(?<=[.!?])\s+", (text or "").strip())[0] if text else ""
    return " ".join(s.split()[:max_words])


def _hasw(text, terms):
    """Whole-word/phrase matches only (so 'use' does not match 'because')."""
    t = (text or "").lower()
    out = []
    for w in terms:
        pat = (r"\b" if w[:1].isalnum() else "") + re.escape(w) + (r"\b" if w[-1:].isalnum() else "")
        if re.search(pat, t):
            out.append(w)
    return out


STRUCTURE_CUES["demonstration"] = ["how to", "demo", "demonstration", "step by step", "watch how", "in action", "apply", "tutorial", "unboxing"]
FEATURES = {
    "problem_solution": lambda t: bool(_hasw(t, PROBLEM_WORDS)),
    "demonstration": lambda t: bool(_hasw(t, STRUCTURE_CUES["demonstration"])),
    "storytelling": lambda t: bool(_hasw(t, STRUCTURE_CUES["storytelling"] + STRUCTURE_CUES["testimonial"])),
    "offer": lambda t: bool(OFFER_RE.search(t)),
    "cta": lambda t: bool(_hasw(t, ACTION_VERBS)),
    "proof": lambda t: bool(_hasw(t, PROOF_WORDS)),
    "benefit": lambda t: bool(_hasw(t, BENEFIT_WORDS)),
}


def analyse_public_video(video: dict, script_text: str = "", audience_terms=None) -> dict:
    """Extract creative signals from the text that is actually available, tagging WHERE each signal was seen.

    Depth levels (never higher than the inputs support):
      limited      - only a title, or a very short description
      text_based   - a usable description (>= 20 words)
      transcript   - a transcript or script the user supplied (>= 20 words)
    Visuals, audio and editing are never analysed.
    """
    script = (script_text or "").strip()
    desc = (video.get("description") or "").strip()
    title = (video.get("title") or "").strip()
    have_script = len(script.split()) >= 20
    have_desc = len(desc.split()) >= 20
    depth = "transcript" if have_script else ("text_based" if have_desc else "limited")
    sources = {"title": title, "description": desc, "transcript": script if have_script else ""}
    seen = {k: [src for src, txt in sources.items() if txt and fn(txt.lower())] for k, fn in FEATURES.items()}
    low = " ".join(sources.values()).lower()
    structures = [k for k, cues in STRUCTURE_CUES.items() if _hasw(low, cues)]
    offers = sorted({m.group(0).strip().lower() for m in OFFER_RE.finditer(" ".join(sources.values()))})
    aud_hit = sorted(set(audience_terms or []) & set(_words(low)))
    missing = []
    if not have_script:
        missing.append("A transcript or script (paste it or upload a .txt/.srt/.vtt file). The YouTube Data API does not provide transcripts for other people's videos.")
    missing.append("Visuals, audio, music and editing are not analysed by AdPilot; only text is.")
    label = {"transcript": "Transcript-based analysis", "text_based": "Text-based analysis (title and description)", "limited": "Limited Analysis (title only)"}[depth]
    return {
        "video_id": video.get("video_id"), "title": title, "url": video.get("url"),
        "depth": depth, "analysis_level": label, "limited": depth == "limited",
        "missing_inputs": missing, "not_analysed": ["visuals", "audio", "editing"],
        "signals": {
            "hook": ({"text": _first_sentence(script), "source": "transcript", "note": "First sentence of the transcript you supplied."} if have_script else
                     {"text": title, "source": "title", "note": "Only the public title is available. This is the headline, not necessarily the opening of the video."}),
            "structures": structures, "offers": offers, "call_to_action_terms": _hasw(low, ACTION_VERBS)[:5], "proof_terms": _hasw(low, PROOF_WORDS)[:5],
            "benefit_terms": _hasw(low, BENEFIT_WORDS)[:6], "audience_terms": aud_hit[:6], "seen_in": seen,
            "duration_seconds": video.get("duration_seconds"),
        },
        "evidence_quality": "Moderate" if depth == "transcript" else "Limited",
        "origin": video.get("source") or ("youtube_api" if video.get("retrieved_at") else "manual"),
        "note": "Creative observation only. It says nothing about how well this video performed commercially.",
    }


DIMENSIONS = [
    ("hook", "Opening-hook approach", "transcript"), ("problem_solution", "Problem-and-solution framing", "any"),
    ("demonstration", "Product demonstration", "any"), ("storytelling", "Storytelling or customer voice", "any"),
    ("benefit", "Benefits communicated", "any"), ("offer", "Offers and promotions", "any"),
    ("cta", "Calls to action", "any"), ("proof", "Credibility and proof points", "any"),
    ("audience", "Audience positioning", "any"),
]


def _own_has(own: dict, key: str, audience_terms):
    text = " ".join([own.get("hook", ""), own.get("main_message", ""), own.get("offer", ""), own.get("cta", ""), own.get("outline", "")]).lower()
    if key == "hook":
        return bool(own.get("hook", "").strip())
    if key == "offer":
        return bool((own.get("offer") or "").strip()) or bool(OFFER_RE.search(text))
    if key == "cta":
        return bool((own.get("cta") or "").strip())
    if key == "audience":
        return bool(set(audience_terms or []) & set(_words(text)))
    return FEATURES[key](text)


def dimension_table(own: dict, analyses: list, audience_terms=None) -> list:
    """Per dimension: what was OBSERVED in the references (with evidence), what the concept contains, an interpretation and a
    hypothesis. Dimensions that the available evidence cannot support are marked not assessable instead of guessed."""
    rows = []
    for key, label, need in DIMENSIONS:
        # a dimension is judged only from videos with enough text; title-only videos are counted but never used to claim absence
        usable = [a for a in analyses if a["depth"] == "transcript"] if need == "transcript" else [a for a in analyses if a["depth"] != "limited"]
        n_total = len(analyses)
        mine = _own_has(own, key, audience_terms)
        title_only = sum(1 for a in analyses if a["depth"] == "limited")
        row = {"key": key, "dimension": label, "videos_assessed": len(usable), "videos_selected": n_total, "yours": "yes" if mine else "no", "title_only_skipped": title_only}
        if key == "hook" and not usable:
            row.update(observed="Not assessable: no transcripts were supplied, so opening hooks cannot be observed.", assessable=False, interpretation="", hypothesis="")
            rows.append(row); continue
        if not usable:
            row.update(observed="Not assessable: the selected videos have no usable text.", assessable=False, interpretation="", hypothesis=""); rows.append(row); continue
        if key == "audience":
            hits = [a for a in usable if a["signals"]["audience_terms"]]
        elif key == "hook":
            hits = [a for a in usable if a["signals"]["hook"]["text"]]
        else:
            hits = [a for a in usable if a["signals"]["seen_in"].get(key)]
        where = sorted({s for a in hits for s in (a["signals"]["seen_in"].get(key, []) if key in a["signals"]["seen_in"] else ["transcript"])})
        row["observed"] = (f"{len(hits)} of {len(usable)} assessable video(s) show this in their {'/'.join(where) or 'text'}." + (f" For example: {hits[0]['title'][:70]}." if hits else "")
                           + (f" {title_only} title-only video(s) were not used." if title_only and need != "transcript" else ""))
        row["assessable"] = True; row["share"] = len(hits) / len(usable)
        if key == "hook":
            row["interpretation"] = "Hooks can only be compared qualitatively from transcripts."; row["hypothesis"] = ""
        elif hits and not mine:
            row["interpretation"] = f"{len(hits)} of {len(usable)} references use this and your concept does not (yet)."
            row["hypothesis"] = f"A variation that adds {label.lower()} might change results. This is a hypothesis to test; the references' own results are unknown."
        elif hits and mine:
            row["interpretation"] = "Your concept and the references both use this, so it is unlikely to differentiate you on its own."; row["hypothesis"] = ""
        elif not hits and mine:
            row["interpretation"] = "Your concept uses this and none of the assessable references show it. It may differentiate you, or the references may simply not mention it in text."
            row["hypothesis"] = "Test whether emphasising it helps."
        else:
            row["interpretation"] = "Neither your concept nor the references show this in the available text."; row["hypothesis"] = ""
        rows.append(row)
    return rows


def compare_with_own(own_ad: dict, own_creative: dict, competitor_analyses: list) -> dict:
    """Similarities, differences, opportunities, test ideas. Pure text comparison."""
    own_text = " ".join([own_ad.get("hook", ""), own_ad.get("main_message", ""), own_ad.get("offer", ""), own_ad.get("cta", "")])
    own_low = own_text.lower()
    own_offer = bool(OFFER_RE.search(own_text))
    own_proof = bool(_hasw(own_low, PROOF_WORDS))
    own_problem = bool(_hasw(own_low, PROBLEM_WORDS))
    n = len(competitor_analyses)
    out = {"compared_videos": n, "similarities": [], "differences": [], "opportunities": [], "test_ideas": [], "evidence_quality": "Limited" if n == 0 or all(a["limited"] for a in competitor_analyses) else "Moderate"}
    if n == 0:
        out["note"] = "Select at least one public video to compare."
        return out
    def share(pred): return sum(1 for a in competitor_analyses if pred(a["signals"]))
    off, prf, prob, cta = share(lambda s: s["offers"]), share(lambda s: s["proof_terms"]), share(lambda s: "problem-solution" in s["structures"]), share(lambda s: s["call_to_action_terms"])
    if off and not own_offer:
        out["differences"].append(f"{off} of {n} selected videos mention an offer in their text; your ad does not state one.")
        out["opportunities"].append("Consider testing a version with an explicit offer or reason to act now.")
        out["test_ideas"].append("Offer-led opening vs. your current opening (metric: conversion rate or CPA).")
    elif off and own_offer:
        out["similarities"].append(f"Like {off} of {n} selected videos, your ad states an offer, so an offer alone will not differentiate you.")
    if prf and not own_proof:
        out["differences"].append(f"{prf} of {n} selected videos use proof or credibility language (e.g. reviews, certification); your ad text has none.")
        out["opportunities"].append("Test adding a proof point (customer result, rating, certification) if you can support it truthfully.")
        out["test_ideas"].append("Proof-point version vs. original (metric: CTR for traffic, conversion rate for sales).")
    elif prf and own_proof:
        out["similarities"].append("Your ad and several selected videos use proof language.")
    if prob and not own_problem:
        out["differences"].append(f"{prob} of {n} selected videos lead with a problem-solution structure; your hook does not raise a problem.")
        out["test_ideas"].append("Problem-first hook vs. product-first hook.")
    elif not prob and own_problem:
        out["opportunities"].append("Your problem-led hook is less common in the selected videos, which may help you stand out. Whether it performs better has to be tested.")
    if cta == 0 and own_ad.get("cta"):
        out["opportunities"].append("None of the selected videos' text has a clear call to action; yours does, which is a presentation difference, not proof of better results.")
    if own_creative and own_creative.get("overall") is not None:
        out["own_creative_overall"] = own_creative["overall"]
    if not out["differences"] and not out["similarities"]:
        out["differences"].append("The text of the selected videos shows no clear contrast with your ad. Add transcripts for a deeper comparison.")
    out["note"] = "These are creative observations from accessible text. They are hypotheses for testing, not proof that any approach is commercially superior."
    return out


def competitor_performance(entries: list) -> dict:
    """Customer-provided competitor numbers only. Labelled unverified; never estimated."""
    out = []
    for e in entries or []:
        t = {k: e.get(k) for k in ("impressions", "clicks", "spend", "conversions", "revenue", "views")}
        m = compute_metrics(t)
        out.append({"name": e.get("name", "Competitor"), "source": e.get("source") or "Not stated", "metrics": m["values"], "missing": m["missing"],
                    "label": "Customer-provided competitor data. AdPilot cannot verify it."})
    return {"entries": out, "available": bool(out),
            "message": "" if out else "No competitor performance data was supplied. AdPilot can compare creative characteristics but cannot say which competitor ad performs better commercially."}
