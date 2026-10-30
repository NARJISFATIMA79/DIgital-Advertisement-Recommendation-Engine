"""Configurable, category-specific strategy frameworks.

These are starting HYPOTHESES to test, not proven rules. Edit this file to change them.
"""
OBJECTIVES = {
    "awareness": "Brand awareness", "reach": "Reach", "engagement": "Video engagement",
    "traffic": "Website traffic", "leads": "Lead generation", "sales": "Sales and conversions",
    "consideration": "Product consideration",
}

STRATEGIES = {
    "fashion": {
        "label": "Fashion and clothing",
        "approaches": ["Product showcase", "Styling demonstration", "Creator-led presentation", "Customer testimonial", "Seasonal offer"],
        "objectives": ["sales", "traffic", "awareness"],
        "priority_metrics": ["roas", "cpa", "conv_rate", "revenue"],
        "weaknesses": ["Product appears late in the video", "No visible price or offer", "Styling context missing", "Call to action not tied to a collection or landing page"],
        "experiments": ["Open with the finished outfit vs. open with the fabric/fit detail", "Offer-led opening vs. styling-led opening", "Creator-led vs. product-only version"],
        "budget_notes": "Seasonal demand shifts quickly; keep a test reserve so new collections can be compared against the proven creative.",
    },
    "education": {
        "label": "Education and online courses",
        "approaches": ["Sample lesson", "Instructor explanation", "Course demonstration", "Student experience", "Problem-solution presentation"],
        "objectives": ["leads", "sales", "consideration"],
        "priority_metrics": ["cpa", "conv_rate", "ctr"],
        "weaknesses": ["Outcome the learner gets is not stated", "No proof of instructor credibility", "Enrolment step is unclear", "Video too long before the call to action"],
        "experiments": ["Sample-lesson opening vs. outcome-promise opening", "Free-trial/lesson call to action vs. enrol-now call to action", "Instructor on camera vs. screen demonstration"],
        "budget_notes": "Lead quality matters more than lead count; track cost per qualified lead or enrolment, not just form fills.",
    },
    "food": {
        "label": "Food and restaurants",
        "approaches": ["Food preparation", "Finished-dish presentation", "Restaurant experience", "Menu highlight", "Local promotional offer"],
        "objectives": ["sales", "leads", "awareness", "traffic"],
        "priority_metrics": ["cpa", "conv_rate", "cpc"],
        "weaknesses": ["Location or delivery area is unclear", "Offer has no end date", "Dish appears only at the end", "No way to order or book in the call to action"],
        "experiments": ["Preparation-first vs. finished-dish-first opening", "Local offer vs. menu highlight", "Order-now vs. book-a-table call to action"],
        "budget_notes": "Local campaigns have small audiences; confirm the target area is large enough to produce meaningful sample sizes.",
    },
    "software": {
        "label": "Software and SaaS",
        "approaches": ["Product demonstration", "Tutorial", "Problem-solution explanation", "Customer case study", "Free-trial offer"],
        "objectives": ["leads", "sales", "consideration", "traffic"],
        "priority_metrics": ["cpa", "conv_rate", "ctr"],
        "weaknesses": ["Problem is not named in the first seconds", "Product UI shown too briefly", "Trial or demo step is unclear", "Target role or company size is not stated"],
        "experiments": ["Problem-first vs. demo-first opening", "Free-trial vs. book-a-demo call to action", "Case-study vs. feature-walkthrough"],
        "budget_notes": "Sales cycles can be long; a short test window may show leads but not paid subscriptions.",
    },
    "beauty": {
        "label": "Beauty and personal care",
        "approaches": ["Product demonstration", "Tutorial", "Routine-based presentation", "Product comparison", "Customer testimonial"],
        "objectives": ["sales", "consideration", "awareness"],
        "priority_metrics": ["roas", "cpa", "conv_rate"],
        "weaknesses": ["Result or benefit not shown", "Ingredients/skin-type relevance missing", "No social proof", "No offer or reason to buy now"],
        "experiments": ["Before/after demonstration vs. routine tutorial", "Testimonial vs. expert explanation", "Bundle offer vs. single-product offer"],
        "budget_notes": "Repeat purchase value is often higher than first-order value; include it in the success criteria if you track it.",
    },
    "real_estate": {
        "label": "Real estate",
        "approaches": ["Property walkthrough", "Location showcase", "Property features", "Agent explanation", "Viewing-booking invitation"],
        "objectives": ["leads", "consideration", "awareness"],
        "priority_metrics": ["cpa", "conv_rate", "ctr"],
        "weaknesses": ["Price range or location not stated", "No clear next step for booking a viewing", "Agent credibility not shown", "Too many properties in one video"],
        "experiments": ["Walkthrough vs. location-first opening", "Viewing-booking call to action vs. brochure download", "Agent-led vs. property-only"],
        "budget_notes": "Qualified enquiries are rare and expensive; judge on cost per qualified lead, and expect noisy small samples.",
    },
    "ecommerce": {
        "label": "General e-commerce",
        "approaches": ["Product showcase", "Offer-led", "Customer testimonial", "Problem-solution", "Unboxing / demonstration"],
        "objectives": ["sales", "traffic"],
        "priority_metrics": ["roas", "cpa", "conv_rate"],
        "weaknesses": ["Price or offer not visible", "Product benefit unclear", "No urgency or reason to act", "Landing page differs from the video"],
        "experiments": ["Offer-led vs. benefit-led opening", "Testimonial vs. demonstration", "Short vs. long cut"],
        "budget_notes": "Keep a test reserve; scale only creatives with enough conversions to trust their CPA.",
    },
    "other": {
        "label": "Other",
        "approaches": ["Product or service demonstration", "Problem-solution", "Customer story", "Offer-led", "Explainer"],
        "objectives": ["awareness", "traffic", "leads", "sales"],
        "priority_metrics": ["cpa", "conv_rate", "ctr"],
        "weaknesses": ["Value proposition unclear", "Call to action vague", "Audience not addressed", "Offer missing"],
        "experiments": ["Problem-first vs. offer-first opening", "Two different calls to action", "Short vs. long cut"],
        "budget_notes": "General guidance only; describe your business so the strategy can be refined.",
    },
}

CATEGORY_ORDER = ["fashion", "education", "food", "beauty", "software", "real_estate", "ecommerce", "other"]


def get_strategy(industry: str) -> dict:
    return STRATEGIES.get(industry) or STRATEGIES["other"]


def strategy_for(industry: str, objective: str) -> dict:
    s = dict(get_strategy(industry))
    fit = objective in s["objectives"]
    s["objective_fit"] = fit
    s["objective_note"] = (
        f"{OBJECTIVES.get(objective, objective)} is one of the objectives this framework was written for."
        if fit else
        f"{OBJECTIVES.get(objective, objective)} is outside this category's usual objectives; treat the category hints as weaker guidance.")
    return s
