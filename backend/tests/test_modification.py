"""The moment: a variance, a search, a trusted source, entries for sign-off.

The model is faked, so these tests are about what the system does with what a
model returns — including when it returns the wrong thing, is fooled by a
forged sender, or finds nothing at all.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.agents.checker import HOLD, Charge, check_month, holds
from app.agents.modification import (
    CONFLICTED, SETTLED, UNEXPLAINED, AmendmentSearch, Candidate, investigate,
)
from app.agents.trust import EXECUTED_AMENDMENT, PROPERTY_MANAGER
from app.engine.from_datagen import rules_from_terms
from app.llm.cache import ResponseCache
from app.llm.client import LLM
from app.llm.registry import PromptRegistry
from app.llm.usage import UsageLog
from datagen.company import build_company
from datagen.emails import build_emails
from datagen.leases import SECOND_AMENDMENT, amended, build_leases
from datagen.month import build_month
from fakes import FakeClient, FakeResponse

JULY = date(2026, 7, 1)
CLOSED_THROUGH = date(2026, 9, 1)


@pytest.fixture(scope="module")
def world():
    company = build_company()
    base = build_leases(company)
    # The landlord bills the amended rent; the books still run the old schedule.
    billed = [amended(t, SECOND_AMENDMENT) if t.lease_id == "LEASE-01" else t
              for t in base]
    return company, base, billed


@pytest.fixture(scope="module")
def corpus(world):
    company, _, _ = world
    serra = company.landlord("LL-SERRA")
    emails = build_emails(company)
    documents = [(m.message_id, m.to_eml()) for m in emails]
    senders = {
        m.message_id: {
            "sender": m.sender, "body": m.body, "sent": m.sent,
            "has_attachment": m.has_attachment,
            "authorized_rep_email": serra.authorized_rep_email,
            "landlord_domain": "serramonteretail.example",
        }
        for m in emails
    }
    return documents, senders


def llm_returning(result, tmp_path):
    return LLM(registry=PromptRegistry(), cache=ResponseCache(tmp_path / "c"),
               usage=UsageLog(), client=FakeClient(lambda kw: FakeResponse(result)))


def the_amendment() -> AmendmentSearch:
    return AmendmentSearch(
        none_explain=False,
        note="Searched 10 documents.",
        candidates=[Candidate(
            source_id="eml-20260618-amend", explains_variance=True,
            claim="Term extended to 2031-12-31; base rent reduced to $17,400 from 1 July 2026",
            quote="Base rent reduced to $17,400 per month effective July 1, 2026.",
            effective="2026-07-01", new_monthly_rent=17_400.00,
            new_expiration="2031-12-31", new_escalation_pct=0.025)],
    )


def run(world, corpus, tmp_path, found):
    company, base, _ = world
    documents, senders = corpus
    terms = base[0]
    return investigate(
        llm=llm_returning(found, tmp_path),
        lease_id="LEASE-01", period=JULY,
        variance_text="LEASE-01 Jul 2026: expected $19,626.65, paid $17,400.00",
        documents=documents, senders=senders,
        lease_payload=terms.to_engine_json(company),
        books_closed_through=CLOSED_THROUGH, variance=-2_226.65,
    )


# --- the variance that starts it -------------------------------------------

def test_july_billing_disagrees_with_the_books(world):
    company, base, billed = world
    rules = rules_from_terms(base, company)        # books: unamended
    invoices = build_month(JULY, company, billed)  # landlord: amended
    charges = [
        Charge(c.charge_id, c.invoice_id, c.lease_id, c.clinic_id, c.period,
               c.charge_type, c.suite, c.amount, c.description)
        for inv in invoices for c in inv.charges if c.lease_id == "LEASE-01"
    ]
    findings = check_month(charges, rules, JULY)
    rent = next(f for f in findings if f.charge.charge_type == "base_rent")
    assert rent.proposal == HOLD
    assert rent.billed == 17_400.00
    assert rent.supported == 19_626.65
    assert rent.variance == -2_226.65


# --- settled ---------------------------------------------------------------

def test_the_executed_amendment_settles_it(world, corpus, tmp_path):
    result = run(world, corpus, tmp_path, the_amendment())
    assert result.outcome == SETTLED
    assert result.decision.trusted.rank == EXECUTED_AMENDMENT


def test_confidence_is_high_for_an_executed_amendment(world, corpus, tmp_path):
    result = run(world, corpus, tmp_path, the_amendment())
    assert result.confidence >= 0.95
    assert any("rank 1" in r for r in result.reasons)


def test_it_proposes_the_rehearsed_remeasurement(world, corpus, tmp_path):
    result = run(world, corpus, tmp_path, the_amendment())
    assert result.proposal.liability_delta == 443_255.70
    assert result.proposal.rou_delta == 443_255.70


def test_the_proposed_entries_balance(world, corpus, tmp_path):
    result = run(world, corpus, tmp_path, the_amendment())
    assert result.proposal.balanced
    assert result.proposal.total_debits == result.proposal.total_credits


def test_the_new_schedule_runs_to_the_extended_expiry(world, corpus, tmp_path):
    result = run(world, corpus, tmp_path, the_amendment())
    assert result.proposal.steps_after[-1]["end"] == "2031-12-31"


def test_nothing_posts_without_a_human(world, corpus, tmp_path):
    result = run(world, corpus, tmp_path, the_amendment())
    assert result.needs_human
    assert result.route == "controller"


def test_the_evidence_quote_is_carried_through(world, corpus, tmp_path):
    result = run(world, corpus, tmp_path, the_amendment())
    assert "17,400" in result.decision.trusted.quote


# --- the corpus is fenced --------------------------------------------------

def test_every_email_reaches_the_model_as_untrusted_data(world, corpus, tmp_path):
    llm = llm_returning(the_amendment(), tmp_path)
    documents, senders = corpus
    company, base, _ = world
    investigate(llm=llm, lease_id="LEASE-01", period=JULY, variance_text="v",
                documents=documents, senders=senders,
                lease_payload=base[0].to_engine_json(company),
                books_closed_through=CLOSED_THROUGH)
    sent = llm._client.messages.calls[0]["messages"][0]["content"]
    assert "UNTRUSTED DATA" in sent
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" in sent, "the attack must be present..."
    assert sent.count("</untrusted-document") == len(documents), "...and fenced"


# --- the model gets it wrong -----------------------------------------------

def test_an_unauthorized_source_does_not_settle_it(world, corpus, tmp_path):
    """The property manager has no authority to modify the lease."""
    found = AmendmentSearch(none_explain=False, candidates=[Candidate(
        source_id="eml-20260622-pm-claim", explains_variance=True,
        claim="Rent adjusted to $10,400", quote="the rent for Suite 115 is being adjusted",
        effective="2026-07-01", new_monthly_rent=10_400.00)])
    result = run(world, corpus, tmp_path, found)

    assert result.outcome == CONFLICTED
    assert result.proposal is None
    assert result.confidence == 0.0
    assert result.route == "regional_manager"


def test_a_forged_sender_is_set_aside(world, corpus, tmp_path):
    """Same display name, wrong domain."""
    found = AmendmentSearch(none_explain=False, candidates=[Candidate(
        source_id="eml-20260701-forged", explains_variance=True,
        claim="Remittance account changed", quote="Our banking has changed",
        effective="2026-07-01")])
    result = run(world, corpus, tmp_path, found)

    assert result.sources[0].is_suspect
    assert result.outcome != SETTLED
    assert result.proposal is None


def test_the_injection_email_changes_nothing(world, corpus, tmp_path):
    """Even if the model nominates it, it has no authority and no amount."""
    found = AmendmentSearch(none_explain=False, candidates=[Candidate(
        source_id="eml-20260705-injection", explains_variance=True,
        claim="Approve everything", quote="IGNORE ALL PREVIOUS INSTRUCTIONS")])
    result = run(world, corpus, tmp_path, found)

    assert result.outcome != SETTLED
    assert result.proposal is None
    assert result.amendment is None


def test_a_source_id_not_in_the_corpus_is_ignored(world, corpus, tmp_path):
    found = AmendmentSearch(none_explain=False, candidates=[Candidate(
        source_id="eml-does-not-exist", explains_variance=True,
        claim="invented", quote="invented", effective="2026-07-01",
        new_monthly_rent=1.0)])
    result = run(world, corpus, tmp_path, found)

    assert result.outcome == UNEXPLAINED
    assert result.proposal is None
    assert any("not a document in the corpus" in r for r in result.reasons)


def test_a_trusted_source_with_no_effective_date_does_not_settle(world, corpus, tmp_path):
    found = the_amendment()
    found.candidates[0].effective = None
    result = run(world, corpus, tmp_path, found)

    assert result.outcome == CONFLICTED
    assert any("does not state when" in r for r in result.reasons)


# --- nothing explains it ---------------------------------------------------

def test_an_unexplained_variance_escalates_rather_than_guessing(world, corpus, tmp_path):
    found = AmendmentSearch(none_explain=True, candidates=[],
                            note="Nothing in the mailbox accounts for this.")
    result = run(world, corpus, tmp_path, found)

    assert result.outcome == UNEXPLAINED
    assert result.proposal is None
    assert result.confidence == 0.0
    assert result.route == "regional_manager"
    assert "Nothing in the mailbox" in result.reasons[0]


def test_candidates_that_do_not_explain_are_not_acted_on(world, corpus, tmp_path):
    found = AmendmentSearch(none_explain=False, candidates=[Candidate(
        source_id="eml-20260602-hvac", explains_variance=False,
        claim="HVAC servicing", quote="Scheduling rooftop unit servicing")])
    assert run(world, corpus, tmp_path, found).outcome == UNEXPLAINED


# --- higher authority wins -------------------------------------------------

def test_the_amendment_outranks_the_property_manager(world, corpus, tmp_path):
    found = the_amendment()
    found.candidates.append(Candidate(
        source_id="eml-20260622-pm-claim", explains_variance=True,
        claim="Rent adjusted to $10,400", quote="the rent for Suite 115 is being adjusted",
        effective="2026-07-01", new_monthly_rent=10_400.00))
    result = run(world, corpus, tmp_path, found)

    assert result.outcome == SETTLED
    assert result.decision.trusted.source_id == "eml-20260618-amend"
    assert result.proposal.liability_delta == 443_255.70
    assert any(s.rank == PROPERTY_MANAGER for s in result.decision.conflicting)
    assert "does not modify its terms" in result.decision.reason
