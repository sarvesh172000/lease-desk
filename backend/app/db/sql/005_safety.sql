-- Decisions belong to people and the gateway, whatever the code above says.
--
-- roles.sql lets lease_agent write work_item (it moves its own items) and
-- audit_event (it records its own moves), and lets lease_api write both for
-- the people it serves. Table grants cannot say *which* moves, so with can()
-- bypassed (a bug, or raw SQL on the agent's connection) the agent could
-- record an approve, or simply UPDATE an item to APPROVED, and the gateway
-- would post it. These triggers close that, below every line of Python
-- (backend/tests/platform/test_safety_layers.py):
--
--   lease_agent  may not record an allowed approve, reject, answer, resume,
--                close, post or release_batch event, in anyone's name; may
--                not put a work item into, or edit one in, a decided state
--                (APPROVED, REJECTED, POSTED, CLOSED; pulling an approved
--                item back to HELD is still its move); and may not insert a
--                lease version that arrives already confirmed.
--   lease_api    may not record an allowed post or release_batch event, nor
--                move a work item to POSTED: only the gateway posts.
--
-- Refusals (allowed = false) are never blocked: a refused attempt is history.
-- Each function runs as the caller (no SECURITY DEFINER), so current_user is
-- the role that connected.

CREATE FUNCTION audit_event_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
    IF NEW.allowed AND current_user = 'lease_agent' AND NEW.action IN
            ('approve', 'reject', 'answer', 'resume', 'close', 'post', 'release_batch') THEN
        RAISE EXCEPTION 'lease_agent may not record an allowed % (actor %): that decision is a person''s or the gateway''s',
            NEW.action, NEW.actor_id USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.allowed AND current_user = 'lease_api' AND NEW.action IN ('post', 'release_batch') THEN
        RAISE EXCEPTION 'lease_api may not record an allowed % (actor %): only the gateway posts and releases',
            NEW.action, NEW.actor_id USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END $$;

-- Named to sort before audit_event_hash, so a refused row never draws a seq.
CREATE TRIGGER audit_event_guard
    BEFORE INSERT ON audit_event
    FOR EACH ROW EXECUTE FUNCTION audit_event_guard();

CREATE FUNCTION work_item_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
    IF current_user = 'lease_agent' AND NEW.state IN ('APPROVED', 'REJECTED', 'POSTED', 'CLOSED') THEN
        RAISE EXCEPTION 'lease_agent may not put work item % in %: decided items are moved by people and the gateway',
            NEW.id, NEW.state USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF current_user = 'lease_api' AND NEW.state = 'POSTED'
            AND (TG_OP = 'INSERT' OR OLD.state IS DISTINCT FROM 'POSTED') THEN
        RAISE EXCEPTION 'lease_api may not move work item % to POSTED: only the gateway posts',
            NEW.id USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER work_item_guard
    BEFORE INSERT OR UPDATE ON work_item
    FOR EACH ROW EXECUTE FUNCTION work_item_guard();

CREATE FUNCTION lease_version_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
    IF current_user = 'lease_agent' AND (NEW.confirmed_by IS NOT NULL OR NEW.confirmed_at IS NOT NULL) THEN
        RAISE EXCEPTION 'lease_agent may not confirm lease version % of %: a person confirms by approving its item',
            NEW.version, NEW.lease_id USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER lease_version_guard
    BEFORE INSERT OR UPDATE ON lease_version
    FOR EACH ROW EXECUTE FUNCTION lease_version_guard();

-- roles.sql revokes EXECUTE on every function from PUBLIC; these are new.
-- (A trigger fires whatever the caller's EXECUTE privilege.)
REVOKE ALL ON FUNCTION audit_event_guard(), work_item_guard(), lease_version_guard() FROM PUBLIC;
