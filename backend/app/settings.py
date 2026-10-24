"""Runtime configuration, read from the environment in one place.

Every value has a development default that matches `.env.example` and the
Compose file, so a fresh clone runs without a `.env`. Production overrides
them; nothing secret is committed.

The database has one owner (migrations only) and four application roles. Each
process connects as exactly one role, which is the point: the worker connects
as `lease_agent`, so even a bug in an agent cannot write the ledger.
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict

DB_ROLES = ("lease_agent", "lease_gateway", "lease_api", "lease_reader")


@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int
    db_name: str
    db_owner: str
    db_owner_password: str
    role_passwords: Dict[str, str]
    data_dir: str
    demo_mode: bool

    def db_url(self, role: str, database: str = "") -> str:
        """SQLAlchemy URL for one role. `role="owner"` is for migrations."""
        if role == "owner":
            user, password = self.db_owner, self.db_owner_password
        elif role in self.role_passwords:
            user, password = role, self.role_passwords[role]
        else:
            raise ValueError("unknown database role %r" % role)
        return "postgresql+psycopg://%s:%s@%s:%d/%s" % (
            user, password, self.db_host, self.db_port, database or self.db_name)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env = os.environ.get
    return Settings(
        db_host=env("LEASEDESK_DB_HOST", "localhost"),
        db_port=int(env("LEASEDESK_DB_PORT", "5433")),
        db_name=env("LEASEDESK_DB_NAME", "leasedesk"),
        db_owner=env("LEASEDESK_DB_OWNER", "leasedesk"),
        db_owner_password=env("LEASEDESK_DB_OWNER_PASSWORD", "leasedesk"),
        # Dev default: each role's password is its own name. Override in any
        # shared environment.
        role_passwords={
            role: env("LEASEDESK_%s_PASSWORD" % role.upper(), role) for role in DB_ROLES
        },
        data_dir=env("LEASEDESK_DATA_DIR", "data/generated"),
        demo_mode=env("LEASEDESK_DEMO_MODE", "1") == "1",
    )
