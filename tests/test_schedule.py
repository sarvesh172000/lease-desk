from datetime import date

from leasedesk.models import load_lease
from leasedesk.schedule import build, present_value, month_starts


def lease():
    return load_lease("data/leases/store-14.json").as_of(date(2024, 1, 1))


def test_month_starts_spans_inclusive():
    months = month_starts(date(2024, 1, 1), date(2024, 12, 1))
    assert len(months) == 12
    assert months[0] == date(2024, 1, 1)
    assert months[-1] == date(2024, 12, 1)


def test_present_value_in_advance_does_not_discount_first_payment():
    pv = present_value([100.0], 0.12, in_advance=True)
    assert round(pv, 2) == 100.00


def test_present_value_discounts_later_payments():
    pv = present_value([100.0, 100.0], 0.12, in_advance=True)
    assert round(pv, 2) == round(100 + 100 / 1.01, 2)


def test_schedule_covers_full_term():
    sched = build(lease())
    assert len(sched.periods) == 60
    assert sched.periods[0].period == date(2024, 1, 1)
    assert sched.periods[-1].period == date(2028, 12, 1)


def test_liability_amortizes_to_zero():
    sched = build(lease())
    assert abs(sched.periods[-1].liability_close) < 0.01


def test_rou_asset_amortizes_to_zero():
    sched = build(lease())
    assert abs(sched.periods[-1].rou_close) < 0.01


def test_straight_line_cost_is_constant():
    sched = build(lease())
    costs = {p.straight_line_cost for p in sched.periods}
    assert len(costs) == 1


def test_total_expense_equals_total_cash():
    """Total straight-line expense ties to total cash, within cent rounding.

    `straight_line_cost` is stored rounded to cents, so summing it over the
    term can drift by up to half a cent per period. The liability and ROU
    asset still land exactly on zero (tested above) because those run on the
    unrounded figure.
    """
    sched = build(lease())
    total_cash = sum(p.payment for p in sched.periods)
    total_cost = sum(p.straight_line_cost for p in sched.periods)
    assert abs(total_cash - total_cost) <= 0.005 * len(sched.periods)
