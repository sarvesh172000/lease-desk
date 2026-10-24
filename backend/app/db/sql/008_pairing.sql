-- Chat pairing (PHASE_3.md group 9): a person links an ASI:One chat user to
-- their own actor with a one-time code, and the Fetch.ai front desk agent
-- exchanges that code for a scoped bearer token. The agent never holds a
-- password and never touches the database; it calls the HTTP API with the
-- token, so every action still goes through can(), the gateway and the
-- audit stream.
--
-- Only hashes are stored: sha256 of the code and of the token. A row is one
-- pairing's whole life: minted (code), claimed (token, chat user), revoked.
-- Nothing is ever deleted (no role may DELETE anything); revoking stamps
-- revoked_at, and an expired or revoked row simply stops authenticating.

CREATE TABLE pairing (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_id          text NOT NULL REFERENCES actor (id),
    code_hash         text NOT NULL UNIQUE CHECK (length(code_hash) = 64),
    code_expires_at   timestamptz NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    claimed_at        timestamptz,
    chat_user         text CHECK (chat_user IS NULL OR length(chat_user) BETWEEN 1 AND 200),
    token_hash        text UNIQUE CHECK (token_hash IS NULL OR length(token_hash) = 64),
    token_expires_at  timestamptz,
    revoked_at        timestamptz,
    revoked_by        text,
    -- claimed means all three, or none of them
    CHECK ((claimed_at IS NULL) = (token_hash IS NULL)),
    CHECK ((claimed_at IS NULL) = (chat_user IS NULL)),
    CHECK ((token_hash IS NULL) = (token_expires_at IS NULL)),
    CHECK ((revoked_at IS NULL) = (revoked_by IS NULL))
);
CREATE INDEX pairing_actor ON pairing (actor_id);
CREATE INDEX pairing_chat_user ON pairing (chat_user) WHERE chat_user IS NOT NULL;
