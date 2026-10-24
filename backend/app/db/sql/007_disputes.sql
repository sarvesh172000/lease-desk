-- Disputes and obligations (PHASE_2.md groups 11 and 12).
--
-- dispute     the dispute register: one row per upheld hold that disputes
--             money with a landlord. The letter, its status (drafted, sent,
--             acknowledged, credited, partially_credited, refused), the
--             credit memos matched to it and the journal entries that
--             recognised, cleared or wrote off the landlord receivable.
--             Every change to a row is also an audit_event with
--             subject_type 'dispute', which is the status history.
-- obligation  the lease's critical dates: renewal notice deadlines, CAM
--             audit windows, deposit returns, expirations, each with the
--             clause that sets it.
--
-- Who writes what (roles.sql): the disputes agent drafts (INSERT), the API
-- records landlord replies (status, credits), the gateway records what it
-- sent and posted (outbox and journal ids). The obligations agent keeps the
-- obligation table. Nobody deletes.
--
-- The work-item keys are DEFERRABLE INITIALLY DEFERRED for the same reason
-- journal_entry's is (004_work.sql): replay deletes and re-inserts work
-- items with the same ids inside one transaction.

CREATE TABLE dispute (
    id                   text PRIMARY KEY,          -- DSP-<charge check item id>
    work_item_id         bigint NOT NULL UNIQUE
                         REFERENCES work_item (id) DEFERRABLE INITIALLY DEFERRED,
    charge_item_id       bigint NOT NULL UNIQUE
                         REFERENCES work_item (id) DEFERRABLE INITIALLY DEFERRED,
    charge_id            text NOT NULL REFERENCES landlord_charge (id),
    landlord_id          text NOT NULL REFERENCES landlord (id),
    lease_id             text NOT NULL REFERENCES lease (id),
    clinic_id            text NOT NULL REFERENCES clinic (id),
    entity_id            text NOT NULL REFERENCES entity (id),
    region_id            text REFERENCES region (id),
    period               date NOT NULL CHECK (extract(day FROM period) = 1),
    charge_type          text NOT NULL,
    billed               numeric(14, 2) NOT NULL,
    supported            numeric(14, 2) NOT NULL,
    amount               numeric(14, 2) NOT NULL CHECK (amount > 0),   -- disputed
    status               text NOT NULL DEFAULT 'drafted'
                         CHECK (status IN ('drafted', 'sent', 'acknowledged', 'credited',
                                           'partially_credited', 'refused')),
    notice_to            jsonb NOT NULL,            -- name, attn, address, email
    letter               text NOT NULL,
    facts                jsonb NOT NULL,
    letter_outbox_id     bigint REFERENCES outbox (id),
    sent_at              timestamptz,
    credited_amount      numeric(14, 2) NOT NULL DEFAULT 0 CHECK (credited_amount >= 0),
    credits              jsonb NOT NULL DEFAULT '[]',   -- [{credit_memo_ref, amount, received_on}]
    credit_memo_ref      text,                      -- the latest one
    refusal_reason       text,
    receivable_entry_id  bigint REFERENCES journal_entry (id),
    writeoff_entry_id    bigint REFERENCES journal_entry (id),
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    CHECK (credited_amount <= amount),
    CHECK (billed = supported + amount)
);
CREATE INDEX dispute_status ON dispute (status, region_id);

CREATE TABLE obligation (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lease_id          text NOT NULL REFERENCES lease (id),
    clinic_id         text NOT NULL REFERENCES clinic (id),
    entity_id         text NOT NULL REFERENCES entity (id),
    region_id         text REFERENCES region (id),
    kind              text NOT NULL CHECK (kind IN ('renewal_notice', 'cam_audit_window',
                                                    'deposit_return', 'expiration')),
    key               text NOT NULL,                -- renewal_notice, cam_audit_window:2026, ...
    due_date          date NOT NULL,
    action            text NOT NULL,                -- what someone has to do by due_date
    citation          jsonb NOT NULL,               -- section, page, quote, document, field(s)
    source            text NOT NULL CHECK (source IN ('lease_term', 'generator')),
    lease_version_id  bigint REFERENCES lease_version (id),
    details           jsonb NOT NULL DEFAULT '{}',
    computed_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (lease_id, key)
);
CREATE INDEX obligation_due ON obligation (due_date);

-- The two agents that act here. Like system:gateway (004_work.sql), they are
-- actors so every event they write names a real row.
INSERT INTO actor (id, name, role, active) VALUES
    ('agent:disputes', 'Disputes agent', 'agent', true),
    ('agent:obligations', 'Obligations agent', 'agent', true)
ON CONFLICT (id) DO NOTHING;
