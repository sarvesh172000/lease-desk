-- The four database roles: the second line of defence behind can().
--
-- This file is the desired state, not a diff. Every migration re-applies it:
-- revoke everything, then grant exactly what the architecture allows. A grant
-- that is not written here does not exist, and backend/tests/platform/
-- test_roles.py asserts the full matrix so an extra one fails the suite.
--
--   lease_agent    the worker. Reads records; writes ingestion, events and
--                  work. Cannot touch the ledger, the outbox or golden tables.
--   lease_gateway  the only writer back to records: golden tables, the
--                  journal, the outbox, period status.
--   lease_api      serves the UI. Writes events and work through transition().
--   lease_reader   the auditor. Read-only on everything.
--
-- Nobody, including the gateway, may UPDATE or DELETE audit_event: no grant
-- exists, and a trigger rejects it even for the owner.

DO $$
DECLARE r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['lease_agent', 'lease_gateway', 'lease_api', 'lease_reader'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('CREATE ROLE %I LOGIN', r);
        END IF;
    END LOOP;
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA public
    FROM lease_agent, lease_gateway, lease_api, lease_reader;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public
    FROM lease_agent, lease_gateway, lease_api, lease_reader;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO lease_agent, lease_gateway, lease_api, lease_reader;

-- Everyone may verify the chain; that is the point of having one.
GRANT EXECUTE ON FUNCTION audit_verify_chain() TO
    lease_agent, lease_gateway, lease_api, lease_reader;

-- ------------------------------------------------------------ reader
GRANT SELECT ON ALL TABLES IN SCHEMA public TO lease_reader;

-- ------------------------------------------------------------- agent
GRANT SELECT ON
    source_document, raw_row, sync_cursor,
    entity, region, landlord, center, clinic, lease, landlord_charge, payment,
    lease_version, lease_term,
    work_item, question, policy, agent_run, tool_call, job,
    account, period,
    audit_event
TO lease_agent;
GRANT INSERT ON source_document, raw_row TO lease_agent;           -- ingestion
GRANT INSERT, UPDATE ON sync_cursor TO lease_agent;
GRANT INSERT ON lease_version, lease_term TO lease_agent;          -- drafts; a person confirms
GRANT INSERT, UPDATE ON work_item, question, agent_run, tool_call, job TO lease_agent;
-- The policy learner proposes policies. Nobody updates one: its status follows
-- its POLICY work item, by trigger (sql/006_policies.sql).
DO $$
BEGIN
    IF to_regprocedure('policy_follow_work_item()') IS NOT NULL THEN
        GRANT INSERT ON policy TO lease_agent;
    END IF;
END $$;
GRANT INSERT ON audit_event TO lease_agent;

-- --------------------------------------------------------------- api
GRANT SELECT ON ALL TABLES IN SCHEMA public TO lease_api;
GRANT INSERT, UPDATE ON work_item, question TO lease_api;
GRANT UPDATE (confirmed_by, confirmed_at) ON lease_version TO lease_api;
GRANT INSERT ON job TO lease_api;                                  -- "run checks now"
GRANT INSERT ON audit_event TO lease_api;

-- ----------------------------------------------------------- gateway
GRANT SELECT ON ALL TABLES IN SCHEMA public TO lease_gateway;
GRANT INSERT, UPDATE ON
    entity, region, landlord, center, clinic, lease, landlord_charge, payment
TO lease_gateway;
GRANT INSERT ON account, period TO lease_gateway;
GRANT UPDATE (status, closed_at, closed_by) ON period TO lease_gateway;
GRANT INSERT ON journal_entry, journal_line, outbox TO lease_gateway;
GRANT UPDATE (status, attempts, sent_at) ON outbox TO lease_gateway;
GRANT UPDATE (state, updated_at, last_event_seq) ON work_item TO lease_gateway;
GRANT INSERT ON audit_event TO lease_gateway;

-- ------------------------------------------------------------- actor
-- Everyone sees who can act; only the API (login) and the gateway (seeding)
-- see password hashes. ALL TABLES above granted reader the whole row.
DO $$
BEGIN
    IF to_regclass('public.actor') IS NOT NULL THEN
        REVOKE SELECT ON actor FROM lease_reader;
        GRANT SELECT (id, name, role, email, region_id, entity_id, active) ON actor
            TO lease_agent, lease_reader;
        GRANT INSERT, UPDATE ON actor TO lease_gateway;
    END IF;
END $$;

-- Sequences behind serial columns. Identity columns need no grant for a
-- plain INSERT.
GRANT USAGE ON SEQUENCE audit_event_seq_seq TO lease_agent, lease_gateway, lease_api;

-- Except where the id must exist before the row does: work/transitions.py
-- draws a work item's (and a question's) id first, so the event that creates
-- it can carry the id and replay can recreate the row with the same one. Only
-- agents create items and ask questions.
GRANT USAGE ON SEQUENCE work_item_id_seq, question_id_seq TO lease_agent;

-- Migration bookkeeping is nobody's business but the owner's. ALL TABLES
-- above sweeps it in, so take it back out.
DO $$
BEGIN
    IF to_regclass('public.alembic_version') IS NOT NULL THEN
        REVOKE ALL ON alembic_version FROM lease_agent, lease_gateway, lease_api, lease_reader;
    END IF;
END $$;
