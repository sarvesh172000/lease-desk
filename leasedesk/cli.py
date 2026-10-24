"""The demo: a rent payment stops matching, and the system goes looking for why.

    python -m leasedesk.cli

Runs offline against the stored amendment. With ANTHROPIC_API_KEY set and
--live, the amendment is instead recovered from the raw inbox by Claude.
"""

import argparse
import glob
import sys
from datetime import date

from .models import load_lease
from .reconcile import check, first_break, load_payments
from .remeasure import remeasure
from .schedule import build

LEASE = "data/leases/store-14.json"
PAYMENTS = "data/payments.csv"
INBOX = "data/inbox/*.eml"
BOOKS_CLOSED_THROUGH = date(2026, 9, 1)


def rule(title):
    print("\n" + title)
    print("-" * len(title))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Lease desk demo")
    parser.add_argument("--live", action="store_true", help="use Claude to find the amendment")
    args = parser.parse_args(argv)

    original = load_lease(LEASE)
    known = original.as_of(date(2026, 6, 30))  # what the books believe today

    rule("1. The schedule the books are running on")
    sched = build(known)
    print("{} — {}".format(known.lease_id, known.location))
    print("Term {} to {}, IBR {:.1%}".format(known.commencement, known.end, known.discount_rate))
    print("Opening liability ${:,.2f}, opening ROU ${:,.2f}".format(
        sched.opening_liability, sched.opening_rou))

    rule("2. Reconciling cash against the schedule")
    variances = check(sched, load_payments(PAYMENTS))
    if not variances:
        print("Every payment ties. Nothing to do.")
        return 0
    for v in variances:
        print("  ! " + v.describe())

    break_at = first_break(variances)
    rule("3. Going looking for why")
    if args.live:
        found = _live_search(break_at)
        if not found or not found.explains_variance:
            print("No document in the mailbox explains this. Routing to the lease accountant.")
            return 1
        print("Found: {}".format(found.summary))
        print("Quote: \"{}\"".format((found.quote or "").strip()))
        print("Confidence: {:.0%}".format(found.confidence))
        effective = date.fromisoformat(found.effective)
    else:
        amendment = original.amendments[0]
        print("Found: {}".format(amendment.source))
        print(amendment.summary)
        effective = amendment.effective

    rule("4. Remeasuring the lease")
    r = remeasure(original, effective=effective, through=BOOKS_CLOSED_THROUGH)
    print("Liability  ${:>12,.2f}  ->  ${:>12,.2f}   ({:+,.2f})".format(
        r.liability_before, r.liability_after, r.liability_delta))
    print("ROU asset  ${:>12,.2f}  ->  ${:>12,.2f}   ({:+,.2f})".format(
        r.rou_before, r.rou_after, r.rou_delta))
    print("New term runs through {}".format(r.new.periods[-1].period))
    print("Rent expense catch-up for Jul–Sep: ${:,.2f}".format(r.expense_catchup))

    rule("5. Proposed adjusting entries — awaiting controller sign-off")
    print("  {:<24} {:>14} {:>14}".format("Account", "Debit", "Credit"))
    for line in r.entries:
        print("  {:<24} {:>14} {:>14}".format(
            line.account,
            "{:,.2f}".format(line.debit) if line.debit else "",
            "{:,.2f}".format(line.credit) if line.credit else "",
        ))
    debits = sum(e.debit for e in r.entries)
    credits = sum(e.credit for e in r.entries)
    print("  {:<24} {:>14,.2f} {:>14,.2f}".format("", debits, credits))
    print("\nBalanced." if abs(debits - credits) < 0.01 else "\nOUT OF BALANCE")
    return 0


def _live_search(variance):
    from . import extract

    if not extract.available():
        print("ANTHROPIC_API_KEY is not set; rerun without --live.", file=sys.stderr)
        return None
    messages = []
    for path in sorted(glob.glob(INBOX)):
        with open(path) as fh:
            messages.append("Source: {}\n{}".format(path, fh.read()))
    return extract.find_amendment(variance.describe(), messages)


if __name__ == "__main__":
    raise SystemExit(main())
