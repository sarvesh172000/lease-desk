"""The source trust ranking. Rules from the lease, not from the model."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.agents.trust import (
    AUTHORIZED_REP, EXECUTED_AMENDMENT, PROPERTY_MANAGER, classify_email, decide,
)

REP = "dana.reyes@serramonteretail.example"
DOMAIN = "serramonteretail.example"


def rank(sender, body="", attachment=False, source_id="s1", claim="c"):
    return classify_email(source_id, sender, body, REP, DOMAIN, attachment,
                          date(2026, 6, 18), claim=claim, quote="q")


def test_authorized_rep_with_an_executed_instrument_is_rank_one():
    s = rank(REP, "Attaching the countersigned Second Amendment.", attachment=True)
    assert s.rank == EXECUTED_AMENDMENT


def test_authorized_rep_without_an_instrument_is_rank_three():
    s = rank(REP, "Confirming we agreed to reduce the rent.")
    assert s.rank == AUTHORIZED_REP


def test_an_attachment_alone_is_not_an_executed_instrument():
    s = rank(REP, "Attaching the July statement.", attachment=True)
    assert s.rank == AUTHORIZED_REP


def test_property_management_is_rank_four():
    s = rank("ktran@crestpointpm.example", "Rent is being adjusted.")
    assert s.rank == PROPERTY_MANAGER
    assert "informational only" in s.reason


def test_the_reps_name_on_another_domain_is_suspect():
    s = rank("dana.reyes@serramonte-retail-billing.example", "Our banking has changed.")
    assert s.is_suspect
    assert "not the landlord's domain" in s.reason


def test_a_suspect_source_cannot_settle_anything():
    s = rank("dana.reyes@elsewhere.example", "Pay here instead.")
    d = decide([s])
    assert not d.settled
    assert "No source survived verification" in d.reason


def test_higher_authority_governs():
    top = rank(REP, "countersigned amendment", attachment=True,
               source_id="amend", claim="rent is 17400")
    low = rank("ktran@crestpointpm.example", "adjusting rent",
               source_id="pm", claim="rent is 10400")
    d = decide([low, top])
    assert d.settled
    assert d.trusted.source_id == "amend"
    assert d.conflicting[0].source_id == "pm"


def test_equal_authority_that_disagrees_settles_nothing():
    a = rank(REP, "countersigned", attachment=True, source_id="a", claim="17400")
    b = rank(REP, "countersigned", attachment=True, source_id="b", claim="18900")
    d = decide([a, b])
    assert not d.settled
    assert "disagree" in d.reason


def test_equal_authority_that_agrees_is_fine():
    a = rank(REP, "countersigned", attachment=True, source_id="a", claim="17400")
    b = rank(REP, "countersigned", attachment=True, source_id="b", claim="17400")
    assert decide([a, b]).settled


def test_a_lone_low_ranked_source_cannot_modify_the_lease():
    d = decide([rank("ktran@crestpointpm.example", "rent is now lower")])
    assert not d.settled
    assert "does not treat as capable of modifying" in d.reason


def test_no_sources_at_all():
    d = decide([])
    assert not d.settled
    assert "No source was found" in d.reason
