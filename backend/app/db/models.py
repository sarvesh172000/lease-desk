"""The schema as SQLAlchemy Core tables, for building queries in Python.

The source of truth is the SQL in `sql/`. This module mirrors its tables
and columns so application code gets names it can autocomplete and a typo
fails at import, not at runtime. `tests/platform/test_schema.py` compares the
two after migrating and fails on any drift.

Constraints, triggers and grants are not repeated here; the database owns
them.
"""

from sqlalchemy import (
    ARRAY, BigInteger, Boolean, Column, Date, Float, Integer, MetaData, Numeric,
    Table, Text, TIMESTAMP,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

Money = Numeric(14, 2)
Timestamp = TIMESTAMP(timezone=True)


def _id():
    return Column("id", BigInteger, primary_key=True)


def _text_id():
    return Column("id", Text, primary_key=True)


# ----------------------------------------------------------------- records

source_document = Table(
    "source_document", metadata, _text_id(),
    Column("sha256", Text), Column("source", Text), Column("kind", Text),
    Column("mime", Text), Column("pages", Integer), Column("storage_key", Text),
    Column("received_at", Timestamp),
)

raw_row = Table(
    "raw_row", metadata, _text_id(),
    Column("source", Text), Column("source_id", Text), Column("payload", JSONB),
)

sync_cursor = Table(
    "sync_cursor", metadata,
    Column("source", Text, primary_key=True), Column("cursor", Text), Column("at", Timestamp),
)

# ------------------------------------------------------------------ golden

entity = Table("entity", metadata, _text_id(), Column("name", Text), Column("state", Text))

region = Table("region", metadata, _text_id(), Column("name", Text), Column("manager_id", Text))

landlord = Table(
    "landlord", metadata, _text_id(),
    Column("name", Text), Column("notice_address", Text),
    Column("authorized_rep", Text), Column("authorized_rep_email", Text),
    Column("property_manager", Text), Column("property_manager_email", Text),
)

center = Table(
    "center", metadata, _text_id(),
    Column("name", Text), Column("address", Text), Column("landlord_id", Text),
    Column("total_rsf", Integer),
)

clinic = Table(
    "clinic", metadata, _text_id(),
    Column("name", Text), Column("entity_id", Text), Column("region_id", Text),
    Column("center_id", Text), Column("suite", Text), Column("rsf", Integer),
)

lease = Table(
    "lease", metadata, _text_id(),
    Column("clinic_id", Text), Column("landlord_id", Text), Column("status", Text),
)

landlord_charge = Table(
    "landlord_charge", metadata, _text_id(),
    Column("lease_id", Text), Column("clinic_id", Text), Column("invoice_id", Text),
    Column("suite", Text), Column("period", Date), Column("charge_type", Text),
    Column("description", Text), Column("amount", Money), Column("document_id", Text),
    Column("page", Integer), Column("raw_ref", Text),
)

payment = Table(
    "payment", metadata, _text_id(),
    Column("lease_id", Text), Column("clinic_id", Text), Column("invoice_id", Text),
    Column("period", Date), Column("charge_type", Text), Column("amount", Money),
    Column("paid_on", Date), Column("reference", Text), Column("counterparty", Text),
    Column("raw_ref", Text),
)

# ---------------------------------------------------------------- rulebook

lease_version = Table(
    "lease_version", metadata, _id(),
    Column("lease_id", Text), Column("version", Integer), Column("effective_from", Date),
    Column("confirmed_by", Text), Column("confirmed_at", Timestamp),
)

lease_term = Table(
    "lease_term", metadata, _id(),
    Column("lease_version_id", BigInteger), Column("field", Text), Column("value", JSONB),
    Column("document_id", Text), Column("page", Integer), Column("bbox", ARRAY(Float)),
    Column("quote", Text), Column("confidence", Numeric(4, 3)),
    Column("extracted_by_run", BigInteger),
)

# -------------------------------------------------------------------- work

agent_run = Table(
    "agent_run", metadata, _id(),
    Column("agent", Text), Column("prompt_id", Text), Column("prompt_version", Text),
    Column("model", Text), Column("status", Text), Column("input_tokens", Integer),
    Column("output_tokens", Integer), Column("cost_usd", Numeric(12, 6)),
    Column("cache_hit", Boolean), Column("started_at", Timestamp),
    Column("finished_at", Timestamp),
)

tool_call = Table(
    "tool_call", metadata, _id(),
    Column("agent_run_id", BigInteger), Column("tool", Text), Column("args", JSONB),
    Column("result", JSONB), Column("allowed", Boolean), Column("at", Timestamp),
)

work_item = Table(
    "work_item", metadata, _id(),
    Column("kind", Text), Column("state", Text), Column("subject_type", Text),
    Column("subject_id", Text), Column("entity_id", Text), Column("region_id", Text),
    Column("clinic_id", Text), Column("period", Date), Column("title", Text),
    Column("amount", Money), Column("proposal", Text), Column("reason", Text),
    Column("evidence", JSONB), Column("proposed_by", Text), Column("created_at", Timestamp),
    Column("updated_at", Timestamp), Column("last_event_seq", BigInteger),
)

question = Table(
    "question", metadata, _id(),
    Column("work_item_id", BigInteger), Column("asked_to", Text), Column("asked_by", Text),
    Column("body", Text), Column("answer", Text), Column("answered_by", Text),
    Column("asked_at", Timestamp), Column("answered_at", Timestamp), Column("due_at", Timestamp),
)

policy = Table(
    "policy", metadata, _id(),
    Column("name", Text), Column("version", Integer), Column("status", Text),
    Column("rule", JSONB), Column("effective_from", Date), Column("effective_to", Date),
    Column("created_at", Timestamp),
)

job = Table(
    "job", metadata, _id(),
    Column("kind", Text), Column("payload", JSONB), Column("status", Text),
    Column("attempts", Integer), Column("run_after", Timestamp), Column("locked_by", Text),
    Column("locked_at", Timestamp), Column("depends_on", ARRAY(BigInteger)),
    Column("idempotency_key", Text), Column("last_error", Text), Column("created_at", Timestamp),
)

# ------------------------------------------------------------------ ledger

account = Table(
    "account", metadata, _id(),
    Column("entity_id", Text), Column("code", Text), Column("name", Text), Column("type", Text),
)

period = Table(
    "period", metadata,
    Column("entity_id", Text, primary_key=True), Column("period", Date, primary_key=True),
    Column("status", Text), Column("closed_at", Timestamp), Column("closed_by", Text),
)

journal_entry = Table(
    "journal_entry", metadata, _id(),
    Column("entity_id", Text), Column("date", Date), Column("period", Date),
    Column("memo", Text), Column("entry_type", Text), Column("idempotency_key", Text),
    Column("work_item_id", BigInteger), Column("created_at", Timestamp),
)

journal_line = Table(
    "journal_line", metadata, _id(),
    Column("journal_entry_id", BigInteger), Column("account_id", BigInteger),
    Column("debit", Money), Column("credit", Money), Column("clinic_id", Text),
)

# ------------------------------------------------------------ outbox, audit

outbox = Table(
    "outbox", metadata, _id(),
    Column("kind", Text), Column("payload", JSONB), Column("idempotency_key", Text),
    Column("status", Text), Column("attempts", Integer), Column("created_at", Timestamp),
    Column("sent_at", Timestamp),
)

audit_event = Table(
    "audit_event", metadata,
    Column("seq", BigInteger, primary_key=True), Column("at", Timestamp),
    Column("actor_id", Text), Column("action", Text), Column("subject_type", Text),
    Column("subject_id", Text), Column("allowed", Boolean), Column("reason", Text),
    Column("diff", JSONB), Column("evidence", JSONB), Column("policy_ref", Text),
    Column("model_ref", Text), Column("prev_hash", Text), Column("hash", Text),
)

actor = Table(
    "actor", metadata, _text_id(),
    Column("name", Text), Column("role", Text), Column("email", Text),
    Column("region_id", Text), Column("entity_id", Text), Column("password_hash", Text),
    Column("active", Boolean),
)

# 'system' is the gateway (system:gateway, migration 0003): the only actor
# that may post.
ACTOR_ROLES = ("regional_manager", "ap_clerk", "controller", "auditor", "agent", "system")

# The eight work states, frozen. work/transitions.py owns the transitions.
WORK_STATES = (
    "NEW", "PROPOSED", "NEEDS_INFO", "HELD", "APPROVED", "REJECTED", "POSTED", "CLOSED",
)
