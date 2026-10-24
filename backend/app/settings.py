"""Runtime configuration, read from the environment in one place.

Every value has a development default that matches `.env.example` and the
Compose file, so a fresh clone runs without a `.env`. Production overrides
them; nothing secret is committed.

The database has one owner (migrations only) and four application roles. Each
process connects as exactly one role, which is the point: the worker connects
as `lease_agent`, so even a bug in an agent cannot write the ledger.
"""

import os
import warnings
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Tuple

DB_ROLES = ("lease_agent", "lease_gateway", "lease_api", "lease_reader")

# Signs the login cookie (app/auth/sessions.py). Anyone who knows it can mint
# a session for any actor, so it is only acceptable on a laptop.
DEV_SESSION_SECRET = "leasedesk-dev-session-secret-not-for-production"


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
    session_secret: str = DEV_SESSION_SECRET
    cookie_secure: bool = False     # True behind HTTPS; browsers then refuse it over http
    # Browser origins allowed to call the API with the session cookie (CORS).
    cors_origins: Tuple[str, ...] = ("http://localhost:3000",)

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


def parse_origins(raw: str) -> Tuple[str, ...]:
    """Comma-separated origins, blanks dropped. "*" is refused: a wildcard
    cannot be combined with credentials, and the cookie is the whole point."""
    origins = tuple(o.strip().rstrip("/") for o in raw.split(",") if o.strip())
    if "*" in origins:
        raise ValueError("LEASEDESK_CORS_ORIGINS cannot be '*' when cookies are sent; "
                         "list the origins")
    return origins


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env = os.environ.get
    settings = Settings(
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
        session_secret=env("LEASEDESK_SESSION_SECRET", DEV_SESSION_SECRET),
        cookie_secure=env("LEASEDESK_COOKIE_SECURE", "0") == "1",
        cors_origins=parse_origins(env("LEASEDESK_CORS_ORIGINS", "http://localhost:3000")),
    )
    if settings.session_secret == DEV_SESSION_SECRET and not settings.demo_mode:
        warnings.warn(
            "LEASEDESK_SESSION_SECRET is the committed development default while "
            "LEASEDESK_DEMO_MODE is off: anyone who has read the repo can forge a "
            "login. Set a long random LEASEDESK_SESSION_SECRET.",
            RuntimeWarning, stacklevel=2)
    return settings
