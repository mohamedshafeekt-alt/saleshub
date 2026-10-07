"""D1–D8 deal qualification scoring (BANT + MEDDIC + CHAMP), from the Lead
Tracker's "D Scoring Guide" sheet.

The frontend renders the form purely from `GET /deals/scoring-dimensions`, so
adding/removing a dimension or level here is the whole change. Each level's
points are exposed too (the deal page's Qualification card shows them), but
totals, modes and priorities are still only ever computed here.
"""

from datetime import datetime, timedelta

# {dimension_key: {"label": ..., "levels": {level_key: (label, score)}}}
SCORING_DIMENSIONS: dict[str, dict] = {
    "D1": {
        "label": "Pain Intensity (CHAMP)",
        "levels": {"mild": ("Mild", 1), "moderate": ("Moderate", 2), "acute": ("Acute", 3)},
    },
    "D2": {
        "label": "Budget (BANT)",
        "levels": {
            "unknown_below_15l": ("Unknown / below ₹15L", 1),
            "indicative_in_range": ("Indicative / in range", 2),
            "confirmed_above_20l": ("Confirmed above ₹20L", 3),
        },
    },
    "D3": {
        "label": "Urgency / Timeline (BANT)",
        "levels": {
            "no_timeline": ("No timeline stated", 1),
            "start_in_30_90_days": ("Start in 30–90 days", 2),
            "start_within_3_weeks": ("Start within 3 weeks", 3),
        },
    },
    "D4": {
        "label": "Decision Maker (MEDDIC / BANT Authority)",
        "levels": {"gatekeeper": ("Gatekeeper", 1), "champion": ("Champion", 2), "economic_buyer": ("Economic buyer", 3)},
    },
    "D5": {
        "label": "Decision Speed (MEDDIC Decision Process)",
        "levels": {
            "slow": ("Slow (3+ months)", 1),
            "moderate": ("Moderate (3–6 weeks)", 2),
            "fast": ("Fast (1–2 weeks)", 3),
        },
    },
    "D6": {
        "label": "Engagement Fit (InnoBoon Specific)",
        "levels": {"low_fit": ("Low fit", 1), "moderate_fit": ("Moderate fit", 2), "high_fit": ("High fit", 3)},
    },
    "D7": {
        "label": "Reference Strength (InnoBoon Specific)",
        "levels": {"cold": ("Cold", 1), "soft_referral": ("Soft referral", 2), "warm_referral": ("Warm referral", 3)},
    },
    "D8": {
        "label": "Account Ceiling (MEDDIC Strategic Value)",
        "levels": {
            "low_ceiling": ("Low ceiling", 1),
            "mid_ceiling": ("Mid ceiling", 2),
            "high_ceiling": ("High ceiling", 3),
        },
    },
}

# {dimension_key: {level_key: tooltip}} -- the sheet's "What This Score Means".
SCORING_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "D1": {
        "mild": "Buyer is curious or exploring. Problem exists but not urgent. No business impact visible yet.",
        "moderate": "Problem is slowing a team or process. Leadership approved a solution search. Feels the friction.",
        "acute": "Problem is causing measurable revenue loss, compliance risk, or competitive disadvantage. "
        "Must be solved now.",
    },
    "D2": {
        "unknown_below_15l": "Budget not stated or implied to be below InnoBoon floor of ₹15L / $18K. Needs qualifying.",
        "indicative_in_range": "Budget is available and roughly in range (₹15L–₹1Cr / $18K–$120K). "
        "Not formally approved but plausible.",
        "confirmed_above_20l": "Budget stated explicitly, approved, and above ₹20L / $25K. Or a defined monthly retainer.",
    },
    "D3": {
        "no_timeline": "No start date mentioned. 'Sometime this year' or 'when budget is approved.' Low velocity.",
        "start_in_30_90_days": "Has a soft target start date next quarter. In their roadmap. Not an emergency but real.",
        "start_within_3_weeks": "Hard deadline. Regulatory trigger, competitive pressure, board commitment, "
        "or tender deadline.",
    },
    "D4": {
        "gatekeeper": "Talking to a junior IT exec, researcher, or procurement admin. DM not named. No path to DM yet.",
        "champion": "Contact is a strong internal champion who can influence the DM. DM named and meeting can be "
        "arranged.",
        "economic_buyer": "CFO, CTO, CEO, or VP is directly on the call. They have sign-off authority and are asking "
        "questions.",
    },
    "D5": {
        "slow": "Large enterprise procurement process. Multiple sign-offs, legal review, RFP committee, or government.",
        "moderate": "Mid-market company. Defined but manageable process. 1–2 approvals needed. Negotiation expected.",
        "fast": "Founder-led startup or repeat InnoBoon client. Minimal process. Can move quickly.",
    },
    "D6": {
        "low_fit": "Generic web/mobile dev, no AI, or domain with no InnoBoon case study. Low margin potential.",
        "moderate_fit": "Software engineering with an adjacent AI component. InnoBoon has partial relevant experience.",
        "high_fit": "GenAI build, Agentic AI system, LLM integration, AI workflow automation, or AI augmentation. "
        "InnoBoon has a matched case study.",
    },
    "D7": {
        "cold": "Pure outbound, LinkedIn DM, website form. No relationship exists. Starting from zero trust.",
        "soft_referral": "Partner, event, advisor, or mutual connection who knows InnoBoon. Credible introduction but "
        "not a client.",
        "warm_referral": "Directly introduced by an existing InnoBoon client, Murali's personal network, or a named "
        "advisor.",
    },
    "D8": {
        "low_ceiling": "Small company, single project, no follow-on. Lifetime value under ₹25L / $30K.",
        "mid_ceiling": "Mid-market with 2–3 phases likely. Retainer or follow-on possible. ₹25L–₹1.5Cr lifetime.",
        "high_ceiling": "Enterprise brand, global company, ₹1.5Cr+ lifetime. Logo strengthens all future InnoBoon "
        "proposals.",
    },
}

# (minimum total, Response Mode, Proposal SLA, SLA hours, Priority), highest
# band first -- the Lead Tracker's TOTAL SCORE -> RESPONSE MODE / PROPOSAL SLA
# formulas. Mode D has no proposal due, so no hours.
_BANDS = [
    (20, "Mode A — Strike Now", "24 Hours", 24, "Very High"),
    (14, "Mode B — Build Case", "48 Hrs + Discovery", 48, "High"),
    (8, "Mode C — Qualify First", "72 Hrs — Qualify Call", 72, "Medium"),
    (1, "Mode D — Nurture", "No Proposal Yet", None, "Low"),
]

MODE_A_MIN = _BANDS[0][0]  # "Very high": Mode A, 20+


def total_score(scores: dict[str, str] | None) -> int | None:
    """Sum of the selected levels. Dimensions/levels no longer defined here
    (removed after the deal was scored) contribute nothing."""
    if not scores:
        return None
    return sum(
        SCORING_DIMENSIONS[dim]["levels"][level][1]
        for dim, level in scores.items()
        if level in SCORING_DIMENSIONS.get(dim, {}).get("levels", {})
    )


def score_summary(total: int | None) -> tuple[str | None, str | None]:
    """(Response Mode, Proposal SLA) for a total score."""
    for minimum, mode, sla, _hours, _priority in _BANDS:
        if total is not None and total >= minimum:
            return mode, sla
    return None, None


def priority(total: int | None) -> str | None:
    """Very High / High / Medium / Low for Mode A / B / C / D; None when unscored."""
    for minimum, _mode, _sla, _hours, label in _BANDS:
        if total is not None and total >= minimum:
            return label
    return None


def proposal_sla_due(received_at: datetime, total: int | None) -> datetime | None:
    """When the proposal is due: received time + the band's SLA hours. None
    when unscored or in Mode D (no proposal owed)."""
    for minimum, _mode, _sla, hours, _priority in _BANDS:
        if total is not None and total >= minimum:
            return received_at + timedelta(hours=hours) if hours else None
    return None


def validate_scores(scores: dict[str, str] | None) -> dict[str, str] | None:
    """All-or-nothing: None, or exactly every current dimension with a valid level."""
    if scores is None:
        return None
    if scores.keys() != SCORING_DIMENSIONS.keys():
        raise ValueError(f"scores must cover exactly these dimensions: {', '.join(SCORING_DIMENSIONS)}")
    for dim, level in scores.items():
        if level not in SCORING_DIMENSIONS[dim]["levels"]:
            raise ValueError(f"invalid level {level!r} for {dim}")
    return scores


def scoring_export_fields(scores: dict[str, str] | None) -> dict[str, str | int | None]:
    """Ordered {column: value} for xlsx exports: each dimension's chosen level
    label, then Total Score / Response Mode / Proposal SLA / Priority. Keys are the same
    for every deal, so they double as the list export's headers."""
    fields: dict[str, str | int | None] = {
        spec["label"]: spec["levels"].get((scores or {}).get(dim), (None, None))[0]
        for dim, spec in SCORING_DIMENSIONS.items()
    }
    total = total_score(scores)
    mode, sla = score_summary(total)
    return fields | {"Total Score": total, "Response Mode": mode, "Proposal SLA": sla, "Priority": priority(total)}
