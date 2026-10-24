-- The policy engine (PHASE_2.md group 10): what the database guarantees
-- about `policy` rows, so that no code path can switch a rule on by itself.
--
-- 1. The policy learner is an actor (agent:policy). It may INSERT a policy
--    (roles.sql) and nothing else: no role may UPDATE one.
-- 2. A policy is born 'proposed', whatever the INSERT says.
-- 3. Its status follows its POLICY work item (subject_type 'policy',
--    subject_id = policy.id), which moves only through transition() and
--    the hash-chained event stream:
--        item APPROVED                  -> 'approved', and any older approved
--                                          version of the same name -> 'retired'
--        item REJECTED                  -> 'rejected' (the reason is the
--                                          item's reason and the event's)
--        item NEW/PROPOSED/NEEDS_INFO/HELD -> 'proposed' (an approval pulled
--                                          back by a hold switches it off)
--        item POSTED/CLOSED             -> unchanged
--    The item turns APPROVED only if the event it came from
--    (work_item.last_event_seq) is an allowed `approve` of that item by a
--    controller. Anything else, including a raw UPDATE of the item's state,
--    is refused here.
--
-- The trigger fires on UPDATE of state only. Replay re-inserts every item in
-- NEW and re-applies each transition in order, so it rebuilds the same
-- statuses the live history set.

INSERT INTO actor (id, name, role, active)
VALUES ('agent:policy', 'Policy learner', 'agent', true)
ON CONFLICT (id) DO NOTHING;

CREATE FUNCTION policy_born_proposed() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.status := 'proposed';
    RETURN NEW;
END $$;

CREATE TRIGGER policy_insert_proposed
    BEFORE INSERT ON policy
    FOR EACH ROW EXECUTE FUNCTION policy_born_proposed();

CREATE FUNCTION policy_follow_work_item() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    pid bigint;
    pol policy%ROWTYPE;
    ev audit_event%ROWTYPE;
    approver_role text;
BEGIN
    IF NEW.kind <> 'POLICY' OR NEW.subject_type <> 'policy' OR NEW.state = OLD.state THEN
        RETURN NEW;
    END IF;
    IF NEW.subject_id !~ '^[0-9]{1,18}$' THEN
        RAISE EXCEPTION 'POLICY work item % names no policy (subject_id %)', NEW.id, NEW.subject_id;
    END IF;
    pid := NEW.subject_id::bigint;
    SELECT * INTO pol FROM policy WHERE id = pid FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'POLICY work item % names policy %, which does not exist', NEW.id, pid;
    END IF;

    IF NEW.state = 'APPROVED' THEN
        SELECT * INTO ev FROM audit_event WHERE seq = NEW.last_event_seq;
        SELECT role INTO approver_role FROM actor WHERE id = ev.actor_id;
        IF ev.seq IS NULL OR ev.action <> 'approve' OR NOT ev.allowed
           OR ev.subject_type <> 'work_item' OR ev.subject_id <> NEW.id::text
           OR approver_role IS DISTINCT FROM 'controller' THEN
            RAISE EXCEPTION 'policy % may only be approved by a controller''s approve event '
                            '(work item %, event %)', pid, NEW.id, NEW.last_event_seq;
        END IF;
        UPDATE policy SET status = 'retired'
         WHERE name = pol.name AND version < pol.version AND status = 'approved';
        UPDATE policy SET status = 'approved' WHERE id = pid;
    ELSIF NEW.state = 'REJECTED' THEN
        UPDATE policy SET status = 'rejected' WHERE id = pid;
    ELSIF NEW.state IN ('NEW', 'PROPOSED', 'NEEDS_INFO', 'HELD') THEN
        UPDATE policy SET status = 'proposed' WHERE id = pid AND status <> 'retired';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER work_item_policy_status
    AFTER UPDATE OF state ON work_item
    FOR EACH ROW EXECUTE FUNCTION policy_follow_work_item();
