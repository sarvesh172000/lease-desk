-- Who can act. can() reads role, region and entity from here; login reads
-- the password hash. Agents are actors too ("agent:checker"), so every event
-- names a real row and an agent can be refused like anyone else.

CREATE TABLE actor (
    id             text PRIMARY KEY,           -- PER-RM-BAY, agent:checker
    name           text NOT NULL,
    role           text NOT NULL CHECK (role IN ('regional_manager', 'ap_clerk', 'controller',
                                                 'auditor', 'agent')),
    email          text UNIQUE,
    region_id      text REFERENCES region (id),   -- regional managers are scoped to one
    entity_id      text REFERENCES entity (id),   -- null means every entity
    password_hash  text,                          -- argon2; null cannot log in
    active         boolean NOT NULL DEFAULT true,
    CHECK (role <> 'regional_manager' OR region_id IS NOT NULL)
);
