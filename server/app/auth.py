import hashlib
import hmac
import time
from collections import deque
from pathlib import Path

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, TimestampSigner

COOKIE = "remix_session"
MAX_AGE = 30 * 24 * 3600
FAIL_LIMIT, FAIL_WINDOW = 5, 60


class Auth:
    def __init__(self, password: str | None, data_dir: Path, clock=time.monotonic):
        self.password = password
        self.clock = clock
        key = hmac.new((data_dir / "secret.key").read_bytes(), b"session", hashlib.sha256).digest()
        self.signer = TimestampSigner(key)
        self.fails: dict[str, deque[float]] = {}  # shortcut: never pruned for idle IPs, fine for a single-user app

    def token(self) -> str:
        return self.signer.sign("ok").decode()

    def valid(self, token: str | None) -> bool:
        if not token:
            return False
        try:
            self.signer.unsign(token, max_age=MAX_AGE)
        except BadSignature:
            return False
        return True

    def blocked(self, ip: str) -> bool:
        q = self.fails.setdefault(ip, deque())
        while q and self.clock() - q[0] >= FAIL_WINDOW:
            q.popleft()
        return len(q) >= FAIL_LIMIT

    def fail(self, ip: str) -> None:
        self.fails.setdefault(ip, deque()).append(self.clock())


def require_auth(request: Request) -> None:
    auth: Auth = request.app.state.auth
    if auth.password and not auth.valid(request.cookies.get(COOKIE)):
        raise HTTPException(401, "Not signed in")
