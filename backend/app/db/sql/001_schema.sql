-- Lease Desk schema. Table names are frozen (docs/phases/PHASE_1.md, group 2).
--
-- Five layers, top to bottom in the architecture:
--   records   what arrived from source systems, untouched
--   golden    the standardized business truth, written only by the gateway
--   rulebook  what each lease says, with the page and box that proves it
--   work      the system of work, projected from audit_event
--   ledger    double-entry books, balanced and period-locked by trigger
-- plus the outbox and audit_event, the append-only, hash-chained history.
--
-- Money is numeric(14,2), never float. Periods are the first day of a month.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------- records

CREATE TABLE source_document (
    id           text PRIMARY KEY,           -- md5(source | source_id): re-sync never duplicates
    sha256       char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    source       text NOT NULL,
    kind         text NOT NULL,              -- lease, invoice, email, ...
    mime         text NOT NULL,
    pages        integer CHECK (pages >= 0),
    storage_key  text NOT NULL,
    received_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX source_document_sha256 ON source_document (sha256);

CREATE TABLE raw_row (
    id         text PRIMARY KEY,             -- md5(source | source_id)
    source     text NOT NULL,
    source_id  text NOT NULL,
    payload    jsonb NOT NULL,
    UNIQUE (source, source_id)
);

CREATE TABLE sync_cursor (
    source  text PRIMARY KEY,
    cursor  text NOT NULL,
    at      timestamptz NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------- golden

CREATE TABLE entity (
    id     text PRIMARY KEY,
    name   text NOT NULL,
    state  char(2) NOT NULL
);

CREATE TABLE region (
    id          text PRIMARY KEY,
    name        text NOT NULL,
    manager_id  text                         -- the regional manager's actor id
);

CREATE TABLE landlord (
    id                      text PRIMARY KEY,
    name                    text NOT NULL,
    notice_address          text,
    authorized_rep          text,            -- named in the lease notices clause
    authorized_rep_email    text,
    property_manager        text,            -- NOT the authorized representative
    property_manager_email  text
);

CREATE TABLE center (
    id           text PRIMARY KEY,
    name         text NOT NULL,
    address      text,
    landlord_id  text NOT NULL REFERENCES landlord (id),
    total_rsf    integer NOT NULL CHECK (total_rsf > 0)
);

CREATE TABLE clinic (
    id         text PRIMARY KEY,
    name       text NOT NULL,
    entity_id  text NOT NULL REFERENCES entity (id),
    region_id  text NOT NULL REFERENCES region (id),
    center_id  text NOT NULL REFERENCES center (id),
    suite      text NOT NULL,
    rsf        integer NOT NULL CHECK (rsf > 0)
);

CREATE TABLE lease (
    id           text PRIMARY KEY,
    clinic_id    text NOT NULL REFERENCES clinic (id),
    landlord_id  text NOT NULL REFERENCES landlord (id),
    status       text NOT NULL DEFAULT 'active'
                 CHECK (status IN ('draft', 'active', 'expired', 'terminated'))
);

CREATE TABLE landlord_charge (
    id           text PRIMARY KEY,           -- md5(source | source_id) of the raw row
    lease_id     text NOT NULL REFERENCES lease (id),
    clinic_id    text NOT NULL REFERENCES clinic (id),
    invoice_id   text NOT NULL,
    suite        text,
    period       date NOT NULL CHECK (extract(day FROM period) = 1),
    charge_type  text NOT NULL,
    description  text,
    amount       numeric(14, 2) NOT NULL,
    document_id  text REFERENCES source_document (id),
    page         integer CHECK (page >= 1),
    raw_ref      text NOT NULL REFERENCES raw_row (id)
);
CREATE INDEX landlord_charge_period ON landlord_charge (period, lease_id);

CREATE TABLE payment (
    id            text PRIMARY KEY,
    lease_id      text NOT NULL REFERENCES lease (id),
    clinic_id     text NOT NULL REFERENCES clinic (id),
    invoice_id    text,
    period        date NOT NULL CHECK (extract(day FROM period) = 1),
    charge_type   text NOT NULL,
    amount        numeric(14, 2) NOT NULL,
    paid_on       date NOT NULL,
    reference     text,
    counterparty  text,
    raw_ref       text NOT NULL REFERENCES raw_row (id)
);
CREATE INDEX payment_period ON payment (period, lease_id);

-- --------------------------------------------------------------- rulebook

CREATE TABLE lease_version (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lease_id        text NOT NULL REFERENCES lease (id),
    version         integer NOT NULL CHECK (version >= 1),
    effective_from  date NOT NULL,
    confirmed_by    text,                    -- null until a regional manager confirms
    confirmed_at    timestamptz,
    UNIQUE (lease_id, version),
    CHECK ((confirmed_by IS NULL) = (confirmed_at IS NULL))
);

-- ------------------------------------------------------------------- work

CREATE TABLE agent_run (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent           text NOT NULL,
    prompt_id       text,
    prompt_version  text,
    model           text,
    status          text NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running', 'succeeded', 'failed')),
    input_tokens    integer NOT NULL DEFAULT 0,
    output_tokens   integer NOT NULL DEFAULT 0,
    cost_usd        numeric(12, 6) NOT NULL DEFAULT 0,
    cache_hit       boolean NOT NULL DEFAULT false,
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz
);

CREATE TABLE lease_term (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lease_version_id  bigint NOT NULL REFERENCES lease_version (id),
    field             text NOT NULL,
    value             jsonb NOT NULL,
    document_id       text REFERENCES source_document (id),
    page              integer CHECK (page >= 1),
    bbox              double precision[] CHECK (bbox IS NULL OR cardinality(bbox) = 4),
    quote             text,
    confidence        numeric(4, 3) CHECK (confidence BETWEEN 0 AND 1),
    extracted_by_run  bigint REFERENCES agent_run (id),
    UNIQUE (lease_version_id, field)
);

CREATE TABLE tool_call (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent_run_id  bigint NOT NULL REFERENCES agent_run (id),
    tool          text NOT NULL,
    args          jsonb NOT NULL DEFAULT '{}',
    result        jsonb,
    allowed       boolean NOT NULL,
    at            timestamptz NOT NULL DEFAULT now()
);

-- The eight states and nine transitions are frozen. The state machine lives
-- in work/transitions.py; this CHECK makes an unknown state impossible to
-- store even if that code is bypassed.
CREATE TABLE work_item (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind            text NOT NULL,           -- CHARGE_CHECK, LEASE_ABSTRACTION, ...
    state           text NOT NULL DEFAULT 'NEW'
                    CHECK (state IN ('NEW', 'PROPOSED', 'NEEDS_INFO', 'HELD',
                                     'APPROVED', 'REJECTED', 'POSTED', 'CLOSED')),
    subject_type    text NOT NULL,
    subject_id      text NOT NULL,
    entity_id       text REFERENCES entity (id),
    region_id       text REFERENCES region (id),
    clinic_id       text REFERENCES clinic (id),
    period          date CHECK (period IS NULL OR extract(day FROM period) = 1),
    title           text NOT NULL,
    amount          numeric(14, 2),
    proposal        text,                    -- what the agent proposed: approve, hold
    reason          text,
    evidence        jsonb NOT NULL DEFAULT '{}',
    proposed_by     text,                    -- separation of duties checks this
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    last_event_seq  bigint,                  -- the audit_event this state came from
    UNIQUE (kind, subject_type, subject_id)  -- running a month twice adds nothing
);
CREATE INDEX work_item_queue ON work_item (state, region_id, period);

CREATE TABLE question (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    work_item_id  bigint NOT NULL REFERENCES work_item (id),
    asked_to      text NOT NULL,
    asked_by      text NOT NULL,
    body          text NOT NULL,
    answer        text,
    answered_by   text,
    asked_at      timestamptz NOT NULL DEFAULT now(),
    answered_at   timestamptz,
    due_at        timestamptz
);

CREATE TABLE policy (                        -- empty until Phase 2
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            text NOT NULL,
    version         integer NOT NULL DEFAULT 1 CHECK (version >= 1),
    status          text NOT NULL DEFAULT 'proposed'
                    CHECK (status IN ('proposed', 'approved', 'rejected', 'retired')),
    rule            jsonb NOT NULL,
    effective_from  date,
    effective_to    date,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (name, version)
);

CREATE TABLE job (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind             text NOT NULL,
    payload          jsonb NOT NULL DEFAULT '{}',
    status           text NOT NULL DEFAULT 'queued'
                     CHECK (status IN ('queued', 'running', 'done', 'failed', 'dead')),
    attempts         integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    run_after        timestamptz NOT NULL DEFAULT now(),
    locked_by        text,
    locked_at        timestamptz,
    depends_on       bigint[] NOT NULL DEFAULT '{}',
    idempotency_key  text UNIQUE,
    last_error       text,
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX job_ready ON job (status, run_after);

-- ----------------------------------------------------------------- ledger

CREATE TABLE account (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_id  text NOT NULL REFERENCES entity (id),
    code       text NOT NULL,
    name       text NOT NULL,
    type       text NOT NULL CHECK (type IN ('asset', 'liability', 'equity', 'revenue', 'expense')),
    UNIQUE (entity_id, code)
);

CREATE TABLE period (
    entity_id  text NOT NULL REFERENCES entity (id),
    period     date NOT NULL CHECK (extract(day FROM period) = 1),
    status     text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    closed_at  timestamptz,
    closed_by  text,
    PRIMARY KEY (entity_id, period)
);

CREATE TABLE journal_entry (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_id        text NOT NULL,
    date             date NOT NULL,
    period           date NOT NULL,
    memo             text NOT NULL,
    entry_type       text NOT NULL DEFAULT 'standard',
    idempotency_key  text NOT NULL UNIQUE,   -- a repeated key posts once
    work_item_id     bigint REFERENCES work_item (id),
    created_at       timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (entity_id, period) REFERENCES period (entity_id, period)
);

CREATE TABLE journal_line (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    journal_entry_id  bigint NOT NULL REFERENCES journal_entry (id),
    account_id        bigint NOT NULL REFERENCES account (id),
    debit             numeric(14, 2) NOT NULL DEFAULT 0 CHECK (debit >= 0),
    credit            numeric(14, 2) NOT NULL DEFAULT 0 CHECK (credit >= 0),
    clinic_id         text REFERENCES clinic (id),
    CHECK ((debit = 0) <> (credit = 0))      -- exactly one side, never both, never neither
);
CREATE INDEX journal_line_entry ON journal_line (journal_entry_id);

-- ----------------------------------------------------------------- outbox

CREATE TABLE outbox (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind             text NOT NULL,          -- ap_batch, email
    payload          jsonb NOT NULL,
    idempotency_key  text NOT NULL UNIQUE,   -- never sends twice
    status           text NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'sent', 'failed')),
    attempts         integer NOT NULL DEFAULT 0,
    created_at       timestamptz NOT NULL DEFAULT now(),
    sent_at          timestamptz
);

-- ------------------------------------------------------------------ audit

-- No foreign keys by design: the history must survive anything it refers to
-- being superseded. prev_hash and hash are computed by trigger; whatever a
-- client sends for them is overwritten.
CREATE TABLE audit_event (
    seq           bigserial PRIMARY KEY,
    at            timestamptz NOT NULL DEFAULT now(),
    actor_id      text NOT NULL,
    action        text NOT NULL,
    subject_type  text NOT NULL,
    subject_id    text NOT NULL,
    allowed       boolean NOT NULL,
    reason        text,
    diff          jsonb,
    evidence      jsonb,
    policy_ref    text,
    model_ref     text,
    prev_hash     char(64) NOT NULL DEFAULT '',
    hash          char(64) NOT NULL DEFAULT ''
);
CREATE INDEX audit_event_subject ON audit_event (subject_type, subject_id);
