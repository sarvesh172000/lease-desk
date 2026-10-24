from datetime import date

from leasedesk.models import load_lease
from leasedesk.remeasure import remeasure


def run():
    return remeasure(
        load_lease("data/leases/store-14.json"),
        effective=date(2026, 7, 1),
        through=date(2026, 9, 1),
    )


def test_extension_increases_the_liability():
    r = run()
    assert r.liability_after > r.liability_before


def test_rou_moves_with_the_liability():
    r = run()
    assert abs(r.rou_delta - r.liability_delta) < 0.01


def test_entries_balance():
    r = run()
    debits = round(sum(e.debit for e in r.entries), 2)
    credits = round(sum(e.credit for e in r.entries), 2)
    assert debits == credits


def test_new_schedule_runs_to_the_extended_end_date():
    r = run()
    assert r.new.periods[-1].period == date(2031, 12, 1)


def test_remeasured_liability_still_amortizes_to_zero():
    r = run()
    assert abs(r.new.periods[-1].liability_close) < 0.01
