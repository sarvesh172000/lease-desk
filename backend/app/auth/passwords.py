"""Password hashes: argon2id, and a dev-only way to give seeded people one.

    python -m app.auth.passwords set-dev-passwords      (or `make dev-passwords`)

Argon2id with argon2-cffi's defaults (RFC 9106 low-memory profile). The
parameters live inside each hash, so raising them later only needs
`needs_rehash()`: old hashes keep verifying, and are replaced when we next
know the plain password.

`verify_password()` never raises on a bad hash: a corrupt or foreign value in
`actor.password_hash` means "cannot log in", not a 500.

The dev setter gives every seeded *person* the password `demo`. Agents keep a
null hash, which login refuses on its own, and the auth routes refuse role
`agent` regardless. It writes as `lease_gateway`, the only role allowed to
UPDATE actor, and refuses to run with demo mode off: a known password in a
shared environment is a breach, not a convenience.
"""

import sys
from functools import lru_cache
from typing import List, Optional

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import text
from sqlalchemy.engine import Connection

DEV_PASSWORD = "demo"

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: Optional[str], password: str) -> bool:
    """True only for a well-formed hash that matches. Null, empty, corrupt
    or non-argon2 hashes are a plain False."""
    if not stored_hash:
        return False
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    """True when the hash was made with weaker parameters than today's."""
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except (InvalidHashError, ValueError):
        return True


@lru_cache(maxsize=1)
def dummy_hash() -> str:
    """A hash nobody's password matches. Login verifies against it when the
    email is unknown, so an unknown user costs the same argon2 work as a
    wrong password and response time does not reveal who has an account."""
    import secrets

    return hash_password(secrets.token_urlsafe(32))


# ----------------------------------------------------------- dev passwords

_PEOPLE = text("""
    SELECT id, password_hash FROM actor
    WHERE role <> 'agent' AND email IS NOT NULL
    ORDER BY id
""")
_SET = text("UPDATE actor SET password_hash = :h WHERE id = :id AND role <> 'agent'")


class DevPasswordsRefused(RuntimeError):
    pass


def set_dev_passwords(conn: Connection, demo_mode: bool,
                      password: str = DEV_PASSWORD) -> List[str]:
    """Give every seeded person `password`. Returns the ids whose hash
    changed; someone whose hash already verifies and is current is left
    alone, so a second run is a no-op. `conn` must be lease_gateway."""
    if not demo_mode:
        raise DevPasswordsRefused(
            "refusing to set dev passwords with LEASEDESK_DEMO_MODE off")
    changed = []
    for actor_id, current in conn.execute(_PEOPLE).all():
        if verify_password(current, password) and not needs_rehash(current):
            continue
        conn.execute(_SET, {"h": hash_password(password), "id": actor_id})
        changed.append(actor_id)
    return changed


def main(argv: List[str]) -> int:
    if argv != ["set-dev-passwords"]:
        print("usage: python -m app.auth.passwords set-dev-passwords", file=sys.stderr)
        return 2
    from ..db.engine import engine
    from ..settings import get_settings

    try:
        with engine("lease_gateway").begin() as conn:
            changed = set_dev_passwords(conn, get_settings().demo_mode)
    except DevPasswordsRefused as exc:
        print(exc, file=sys.stderr)
        return 1
    print("dev passwords: %d %s set to %r%s" % (
        len(changed), "person" if len(changed) == 1 else "people", DEV_PASSWORD,
        "" if changed else " (already current)"))
    for actor_id in changed:
        print("  %s" % actor_id)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
