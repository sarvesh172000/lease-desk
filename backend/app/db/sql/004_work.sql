-- What the event-sourced work layer (work/transitions.py, work/replay.py)
-- needs from the schema.
--
-- 1. The gateway is an actor. Every event names a real actor row, and `post`
--    is allowed only to role 'system', so the gateway can be refused like
--    anyone else and no person or agent can ever post.
-- 2. Replay rebuilds work_item from audit_event with the same ids. Journal
--    entries point at work items, so the rebuild deletes and re-inserts
--    those rows inside one transaction. Deferring this one foreign key to
--    commit lets that happen and still proves, at commit, that every entry
--    points at an item the history recreated.

ALTER TABLE actor DROP CONSTRAINT actor_role_check;
ALTER TABLE actor ADD CONSTRAINT actor_role_check
    CHECK (role IN ('regional_manager', 'ap_clerk', 'controller', 'auditor', 'agent', 'system'));

INSERT INTO actor (id, name, role, active)
VALUES ('system:gateway', 'Gateway', 'system', true)
ON CONFLICT (id) DO NOTHING;

ALTER TABLE journal_entry ALTER CONSTRAINT journal_entry_work_item_id_fkey
    DEFERRABLE INITIALLY IMMEDIATE;
