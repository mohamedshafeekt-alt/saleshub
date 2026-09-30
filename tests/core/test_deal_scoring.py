"""D1–D8 deal scoring: level -> score lookup, total, and the Lead Tracker's
Mode / Proposal SLA thresholds."""

import pytest

from app.core.deal_scoring import (
    SCORING_DESCRIPTIONS,
    SCORING_DIMENSIONS,
    score_summary,
    total_score,
)


def _all_at(score: int) -> dict[str, str]:
    """Pick, for every dimension, the level worth `score`."""
    return {
        dim: next(key for key, (_, s) in spec["levels"].items() if s == score)
        for dim, spec in SCORING_DIMENSIONS.items()
    }


def test_eight_dimensions_each_with_three_described_levels():
    assert list(SCORING_DIMENSIONS) == [f"D{i}" for i in range(1, 9)]
    for dim, spec in SCORING_DIMENSIONS.items():
        assert sorted(s for _, s in spec["levels"].values()) == [1, 2, 3]
        assert SCORING_DESCRIPTIONS[dim].keys() == spec["levels"].keys()


def test_level_labels_carry_no_score_prefix():
    assert SCORING_DIMENSIONS["D1"]["levels"]["mild"] == ("Mild", 1)
    assert SCORING_DIMENSIONS["D2"]["label"] == "Budget (BANT)"
    assert SCORING_DESCRIPTIONS["D2"]["confirmed_above_20l"] == (
        "Budget stated explicitly, approved, and above ₹20L / $25K. Or a defined monthly retainer."
    )


def test_total_score_sums_levels():
    assert total_score(_all_at(1)) == 8
    assert total_score(_all_at(3)) == 24


def test_total_score_is_none_when_unscored():
    assert total_score(None) is None
    assert total_score({}) is None


def test_total_score_ignores_a_dimension_removed_from_the_backend():
    scores = _all_at(2) | {"D99": "gone"}
    assert total_score(scores) == 16


@pytest.mark.parametrize(
    ("total", "mode", "sla"),
    [
        (24, "Mode A — Strike Now", "24 Hours"),
        (20, "Mode A — Strike Now", "24 Hours"),
        (19, "Mode B — Build Case", "48 Hrs + Discovery"),
        (15, "Mode B — Build Case", "48 Hrs + Discovery"),
        (14, "Mode B — Build Case", "48 Hrs + Discovery"),
        (13, "Mode C — Qualify First", "72 Hrs — Qualify Call"),
        (8, "Mode C — Qualify First", "72 Hrs — Qualify Call"),
        (7, "Mode D — Nurture", "No Proposal Yet"),
        (1, "Mode D — Nurture", "No Proposal Yet"),
    ],
)
def test_score_summary_thresholds(total, mode, sla):
    assert score_summary(total) == (mode, sla)


def test_score_summary_is_none_when_unscored():
    assert score_summary(None) == (None, None)
