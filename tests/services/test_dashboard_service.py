"""Unit tests for dashboard period-bounds math (pure function, no DB).

Weekly/monthly are fixed-length rolling windows ending today, not
calendar-boundary windows (Monday-start week, 1st-of-month) -- a partial
calendar period (e.g. viewing "Monthly" on the 3rd) must not produce an
artificially short window or a mismatched-length previous period.
"""

from datetime import date

from app.services.dashboard_service import _period_bounds


def test_this_week_is_a_7_day_rolling_window_ending_today():
    today = date(2026, 8, 18)  # a Tuesday
    start, end, prev_start, prev_end = _period_bounds("this_week", today)
    assert (start, end) == (date(2026, 8, 12), date(2026, 8, 18))
    assert (prev_start, prev_end) == (date(2026, 8, 5), date(2026, 8, 11))


def test_this_month_is_a_30_day_rolling_window_ending_today():
    today = date(2026, 8, 3)  # early in the month -- must not truncate the window
    start, end, prev_start, prev_end = _period_bounds("this_month", today)
    assert (start, end) == (date(2026, 7, 5), date(2026, 8, 3))
    assert (prev_start, prev_end) == (date(2026, 6, 5), date(2026, 7, 4))
