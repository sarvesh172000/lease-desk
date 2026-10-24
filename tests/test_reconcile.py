from datetime import date

from leasedesk.models import load_lease
from leasedesk.reconcile import check, load_payments, first_break
from leasedesk.schedule import build


def test_flags_the_month_rent_changed():
    original = load_lease("data/leases/store-14.json").as_of(date(2026, 6, 30))
    sched = build(original)
    variances = check(sched, load_payments("data/payments.csv"))

    assert variances, "expected the post-amendment payments to break"
    assert first_break(variances).period == date(2026, 7, 1)


def test_clean_months_are_not_flagged():
    original = load_lease("data/leases/store-14.json").as_of(date(2026, 6, 30))
    sched = build(original)
    variances = check(sched, load_payments("data/payments.csv"))
    flagged = {v.period for v in variances}

    assert date(2026, 4, 1) not in flagged
    assert date(2026, 5, 1) not in flagged
    assert date(2026, 6, 1) not in flagged


def test_variance_is_an_underpayment():
    original = load_lease("data/leases/store-14.json").as_of(date(2026, 6, 30))
    sched = build(original)
    v = first_break(check(sched, load_payments("data/payments.csv")))

    assert v.direction == "underpaid"
    assert round(v.delta, 2) == round(17400.00 - 19626.65, 2)
