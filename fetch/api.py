"""The Lease Desk API, as the agents use it.

The agent signs in as a person (LEASEDESK_EMAIL / LEASEDESK_PASSWORD) and
acts with that person's role: an approve the role may not make is refused by
the API, on record, exactly as it would be in the web app. Nothing here
decides anything; it only carries requests and answers.
"""

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional

import httpx


class DeskError(RuntimeError):
    """The API refused or failed. `status` is the HTTP status, when there was one."""

    def __init__(self, message: str, status: Optional[int] = None):
        self.status = status
        super().__init__(message)


@dataclass(frozen=True)
class Credentials:
    base_url: str
    email: str
    password: str

    @classmethod
    def from_env(cls) -> "Credentials":
        missing = [k for k in ("LEASEDESK_EMAIL", "LEASEDESK_PASSWORD") if not os.environ.get(k)]
        if missing:
            raise SystemExit("set %s (see fetch/README.md)" % " and ".join(missing))
        return cls(base_url=os.environ.get("LEASEDESK_API_URL", "http://localhost:8000").rstrip("/"),
                   email=os.environ["LEASEDESK_EMAIL"], password=os.environ["LEASEDESK_PASSWORD"])


class LeaseDeskAPI:
    def __init__(self, creds: Credentials, client: Optional[httpx.Client] = None):
        self.creds = creds
        self.http = client or httpx.Client(base_url=creds.base_url, timeout=30.0)
        self.actor: Optional[Dict[str, Any]] = None

    # --- session ---------------------------------------------------------

    def login(self) -> Dict[str, Any]:
        r = self.http.post("/api/auth/login", json={"email": self.creds.email,
                                                    "password": self.creds.password})
        if r.status_code != 200:
            raise DeskError("could not sign in to Lease Desk as %s" % self.creds.email, r.status_code)
        self.actor = r.json()
        return self.actor

    def _request(self, method: str, path: str, **kw) -> Any:
        """One call, signing in first if there is no session, and once more if it expired."""
        if self.actor is None:
            self.login()
        try:
            r = self.http.request(method, path, **kw)
            if r.status_code == 401:
                self.login()
                r = self.http.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise DeskError("Lease Desk is not reachable at %s (%s)" % (self.creds.base_url, exc)) from exc
        if r.status_code >= 400:
            raise DeskError(_detail(r), r.status_code)
        return r.json()

    # --- reads -----------------------------------------------------------

    def exceptions(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/api/exceptions")

    def exception(self, exc_id: str) -> Dict[str, Any]:
        return self._request("GET", "/api/exceptions/%s" % exc_id)

    def leases(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/api/leases")

    # --- actions ---------------------------------------------------------

    def approve(self, exc_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
        return self._request("POST", "/api/exceptions/%s/approve" % exc_id, json={"reason": reason})

    def hold(self, exc_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
        return self._request("POST", "/api/exceptions/%s/hold" % exc_id, json={"reason": reason})

    def investigate(self, exc_id: str) -> Iterator[Dict[str, Any]]:
        """The investigation's frames as they arrive (the API streams them as SSE)."""
        if self.actor is None:
            self.login()
        try:
            with self.http.stream("POST", "/api/exceptions/%s/investigate" % exc_id,
                                  timeout=httpx.Timeout(30.0, read=600.0)) as r:
                if r.status_code >= 400:
                    r.read()
                    raise DeskError(_detail(r), r.status_code)
                for line in r.iter_lines():
                    if line.startswith("data: "):
                        yield json.loads(line[len("data: "):])
        except httpx.HTTPError as exc:
            raise DeskError("the investigation stream broke off (%s)" % exc) from exc


def _detail(r: httpx.Response) -> str:
    try:
        detail = r.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, list):     # FastAPI validation errors
        detail = "; ".join(str(d.get("msg", d)) for d in detail)
    return str(detail or "Lease Desk answered %d" % r.status_code)
