"""The Lease Desk HTTP API, as the Fetch.ai agents see it.

The agents never touch the database. Everything they know and everything
they do is one of these calls, made with the paired person's scoped token
(`Authorization: Bearer ldp_...` + `X-LeaseDesk-Chat-User`), so the API runs
`current_actor`, `can()`, the gateway and the audit stream exactly as it does
for the web app.

    client = LeaseDeskClient("http://localhost:8000")
    claimed = client.claim("K7QM-9XDA", chat_user="agent1q...")       # no session needed
    me = client.paired(claimed["token"], "agent1q...")
    me.items(); me.act(42, "approve", reason="...")
    for frame in me.investigate(42): ...        # the investigation's SSE frames, as they arrive

Any non-2xx is an ApiError with the status and the API's `detail`. Tests hand
in FastAPI's TestClient (an httpx.Client) as `http`, so the agents are
exercised against the real app and a real database with no server running.
"""

import json
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import quote

import httpx

CHAT_USER_HEADER = "X-LeaseDesk-Chat-User"      # = app.auth.pairing.CHAT_USER_HEADER
CLIENT_KEY_HEADER = "X-Pairing-Client-Key"
INVESTIGATION_READ_S = 600.0


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__("%s: %s" % (status, detail))
        self.status = status
        self.detail = detail

    @property
    def refused(self) -> bool:      # can() said no (or the scope did)
        return self.status == 403

    @property
    def unpaired(self) -> bool:     # token unknown, expired or revoked
        return self.status == 401


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300] or response.reason_phrase
    detail = body.get("detail") if isinstance(body, dict) else body
    if isinstance(detail, list):      # FastAPI validation errors
        return "; ".join(str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail)
    return str(detail)


class LeaseDeskClient:
    def __init__(self, base_url: str = "http://localhost:8000", *,
                 http: Optional[httpx.Client] = None, timeout: float = 30.0,
                 client_key: Optional[str] = None):
        self.http = http if http is not None else httpx.Client(base_url=base_url, timeout=timeout)
        self.client_key = client_key

    def _request(self, method: str, path: str, *, headers: Optional[Dict[str, str]] = None,
                 **kwargs: Any) -> Any:
        response = self.http.request(method, path, headers=headers, **kwargs)
        # The agents act only through the bearer token; a cookie the transport
        # might have picked up must never ride along on a later call.
        self.http.cookies.clear()
        if response.status_code >= 400:
            raise ApiError(response.status_code, _detail(response))
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def claim(self, code: str, chat_user: str) -> Dict[str, Any]:
        headers = {CLIENT_KEY_HEADER: self.client_key} if self.client_key else None
        return self._request("POST", "/api/pairing/claim", headers=headers,
                             json={"code": code, "chat_user": chat_user})

    def paired(self, token: str, chat_user: str) -> "PairedClient":
        return PairedClient(self, token, chat_user)


class PairedClient:
    """Calls made as one paired person. Holds a token, never a password."""

    def __init__(self, base: LeaseDeskClient, token: str, chat_user: str):
        self._base = base
        self._headers = {"Authorization": "Bearer %s" % token, CHAT_USER_HEADER: chat_user}

    def _get(self, path: str, **params: Any) -> Any:
        params = {k: v for k, v in params.items() if v is not None}
        return self._base._request("GET", path, headers=self._headers, params=params or None)

    def _post(self, path: str, body: Optional[dict] = None) -> Any:
        return self._base._request("POST", path, headers=self._headers, json=body)

    # who
    def me(self) -> Dict[str, Any]:
        return self._get("/api/auth/me")

    def pairing(self) -> Dict[str, Any]:
        return self._get("/api/pairing/me")

    def unpair(self) -> None:
        self._post("/api/pairing/me/revoke")

    # the queue
    def items(self, state: Optional[str] = None, limit: int = 200) -> Dict[str, Any]:
        return self._get("/api/items", state=state, limit=limit)

    def item(self, item_id: int) -> Dict[str, Any]:
        return self._get("/api/items/%d" % item_id)

    def act(self, item_id: int, action: str, reason: Optional[str] = None) -> Dict[str, Any]:
        return self._post("/api/items/%d/actions/%s" % (item_id, action),
                          {"reason": reason} if reason else {})

    def why(self, item_id: int, question: Optional[str] = None) -> Dict[str, Any]:
        return self._post("/api/items/%d/why" % item_id,
                          {"question": question} if question else None)

    def investigate(self, item_id: int) -> Iterator[Dict[str, Any]]:
        """POST /api/exceptions/exc_<id>/investigate: the investigation's
        `data: {...}` frames (stage searching | found | not_found | remeasured
        | complete | error), yielded as the API streams them. An investigation
        may run a model over the mailbox, so the read timeout is long."""
        http = self._base.http
        try:
            with http.stream("POST", "/api/exceptions/exc_%d/investigate" % item_id, headers=self._headers,
                             timeout=httpx.Timeout(30.0, read=INVESTIGATION_READ_S)) as response:
                if response.status_code >= 400:
                    response.read()
                    raise ApiError(response.status_code, _detail(response))
                for line in response.iter_lines():
                    if line.startswith("data:"):
                        try:
                            frame = json.loads(line[len("data:"):].strip())
                        except ValueError:
                            continue
                        if isinstance(frame, dict):
                            yield frame
        finally:
            http.cookies.clear()

    # the rulebook
    def leases(self) -> List[Dict[str, Any]]:
        return self._get("/api/leases")

    def lease_versions(self, lease_id: str) -> List[Dict[str, Any]]:
        return self._get("/api/leases/%s/versions" % quote(lease_id, safe=""))

    # the record
    def audit(self, subject_type: str, subject_id: str, limit: int = 50) -> Dict[str, Any]:
        return self._get("/api/audit", subject_type=subject_type, subject_id=subject_id, limit=limit)
