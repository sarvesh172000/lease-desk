-- Guarantees the database enforces on its own, so that no application bug,
-- and no process connected as the wrong role, can break them:
--
--   1. audit_event is append-only: UPDATE, DELETE and TRUNCATE are rejected.
--   2. audit_event is hash-chained: hash = sha256(prev_hash || canonical row).
--   3. A journal entry balances (debits = credits, at least two lines) when
--      its transaction commits.
--   4. Nothing is written into a closed period.
--
-- The functions are SECURITY DEFINER so they can read what they check even
-- when the calling role cannot. Each pins search_path so that cannot be
-- abused.

-- ------------------------------------------------------- 1. append-only

CREATE FUNCTION audit_event_reject_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_event is append-only: % rejected', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END $$;

CREATE TRIGGER audit_event_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_event
    FOR EACH ROW EXECUTE FUNCTION audit_event_reject_change();

CREATE TRIGGER audit_event_no_truncate
    BEFORE TRUNCATE ON audit_event
    FOR EACH STATEMENT EXECUTE FUNCTION audit_event_reject_change();

-- --------------------------------------------------------- 2. hash chain

-- The canonical form of a row: every column except the two hashes, as jsonb
-- text (jsonb orders its keys deterministically), with the timestamp pinned
-- to UTC so a session time zone cannot change the hash. verify_chain() in
-- work/events.py and audit_verify_chain() below both use this one function.
CREATE FUNCTION audit_canonical(e audit_event) RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT jsonb_build_object(
        'seq',          e.seq,
        'at',           to_char(e.at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
        'actor_id',     e.actor_id,
        'action',       e.action,
        'subject_type', e.subject_type,
        'subject_id',   e.subject_id,
        'allowed',      e.allowed,
        'reason',       e.reason,
        'diff',         e.diff,
        'evidence',     e.evidence,
        'policy_ref',   e.policy_ref,
        'model_ref',    e.model_ref
    )::text
$$;

CREATE FUNCTION audit_hash(prev_hash text, e audit_event) RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT encode(digest(prev_hash || audit_canonical(e), 'sha256'), 'hex')
$$;

CREATE FUNCTION audit_event_chain() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    last_hash text;
BEGIN
    -- The previous hash must be read after every earlier writer committed.
    -- A snapshot taken at transaction start could miss one and fork the chain.
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'audit_event must be written under READ COMMITTED, not %',
            current_setting('transaction_isolation');
    END IF;

    -- One writer at a time, held until commit. seq is drawn *after* the lock,
    -- so seq order, commit order and chain order are the same order.
    PERFORM pg_advisory_xact_lock(hashtext('lease_desk.audit_event_chain'));
    NEW.seq := nextval(pg_get_serial_sequence('audit_event', 'seq'));

    SELECT hash INTO last_hash FROM audit_event ORDER BY seq DESC LIMIT 1;
    NEW.prev_hash := coalesce(last_hash, repeat('0', 64));
    NEW.hash := audit_hash(NEW.prev_hash, NEW);
    RETURN NEW;
END $$;

CREATE TRIGGER audit_event_hash
    BEFORE INSERT ON audit_event
    FOR EACH ROW EXECUTE FUNCTION audit_event_chain();

-- Walk the chain in order. Returns the first broken link, or no row when the
-- chain is intact. A row whose hash does not match its own contents was
-- edited; a row whose prev_hash does not match its predecessor was inserted,
-- deleted or reordered.
CREATE FUNCTION audit_verify_chain()
RETURNS TABLE (broken_seq bigint, problem text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    e audit_event;
    expected_prev text := repeat('0', 64);
BEGIN
    FOR e IN SELECT * FROM audit_event ORDER BY seq LOOP
        IF e.prev_hash <> expected_prev THEN
            broken_seq := e.seq; problem := 'prev_hash does not match the previous event';
            RETURN NEXT; RETURN;
        END IF;
        IF e.hash <> audit_hash(e.prev_hash, e) THEN
            broken_seq := e.seq; problem := 'hash does not match the event contents';
            RETURN NEXT; RETURN;
        END IF;
        expected_prev := e.hash;
    END LOOP;
END $$;

-- ------------------------------------------------------- 3. balanced books

CREATE FUNCTION journal_check_balanced(entry_id bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    n integer;
    debits numeric;
    credits numeric;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM journal_entry WHERE id = entry_id) THEN
        RETURN;  -- the entry itself was removed in this transaction
    END IF;
    SELECT count(*), coalesce(sum(debit), 0), coalesce(sum(credit), 0)
      INTO n, debits, credits
      FROM journal_line WHERE journal_entry_id = entry_id;
    IF n < 2 THEN
        RAISE EXCEPTION 'journal entry % has % line(s); a balanced entry needs at least 2',
            entry_id, n USING ERRCODE = 'check_violation';
    END IF;
    IF debits <> credits THEN
        RAISE EXCEPTION 'journal entry % is unbalanced: debits % <> credits %',
            entry_id, debits, credits USING ERRCODE = 'check_violation';
    END IF;
END $$;

CREATE FUNCTION journal_line_balanced() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        PERFORM journal_check_balanced(NEW.journal_entry_id);
    END IF;
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        PERFORM journal_check_balanced(OLD.journal_entry_id);
    END IF;
    RETURN NULL;
END $$;

CREATE FUNCTION journal_entry_balanced() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    PERFORM journal_check_balanced(NEW.id);
    RETURN NULL;
END $$;

-- Deferred to commit: lines are inserted one at a time, so the entry is
-- legitimately unbalanced in between.
CREATE CONSTRAINT TRIGGER journal_line_must_balance
    AFTER INSERT OR UPDATE OR DELETE ON journal_line
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION journal_line_balanced();

-- Catches an entry committed with no lines at all, which no line trigger sees.
CREATE CONSTRAINT TRIGGER journal_entry_must_balance
    AFTER INSERT ON journal_entry
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION journal_entry_balanced();

-- ------------------------------------------------------ 4. period lock

CREATE FUNCTION period_check_open(entity text, per date) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM period
               WHERE entity_id = entity AND period.period = per AND status = 'closed') THEN
        RAISE EXCEPTION 'period % for entity % is closed', to_char(per, 'YYYY-MM'), entity
            USING ERRCODE = 'check_violation';
    END IF;
END $$;

CREATE FUNCTION journal_entry_period_open() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        PERFORM period_check_open(OLD.entity_id, OLD.period);
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        PERFORM period_check_open(NEW.entity_id, NEW.period);
        RETURN NEW;
    END IF;
    RETURN OLD;
END $$;

CREATE FUNCTION journal_line_period_open() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    entry_id bigint := CASE WHEN TG_OP = 'DELETE' THEN OLD.journal_entry_id
                            ELSE NEW.journal_entry_id END;
    entity text;
    per date;
BEGIN
    SELECT entity_id, period INTO entity, per FROM journal_entry WHERE id = entry_id;
    IF FOUND THEN
        PERFORM period_check_open(entity, per);
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER journal_entry_period_lock
    BEFORE INSERT OR UPDATE OR DELETE ON journal_entry
    FOR EACH ROW EXECUTE FUNCTION journal_entry_period_open();

CREATE TRIGGER journal_line_period_lock
    BEFORE INSERT OR UPDATE OR DELETE ON journal_line
    FOR EACH ROW EXECUTE FUNCTION journal_line_period_open();
