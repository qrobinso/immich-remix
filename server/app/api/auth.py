import hmac

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from ..auth import COOKIE, MAX_AGE

router = APIRouter(prefix="/api")


class Login(BaseModel):
    password: str


@router.post("/login", status_code=204)
def login(body: Login, request: Request) -> Response:
    auth = request.app.state.auth
    resp = Response(status_code=204)
    if not auth.password:
        return resp
    ip = request.client.host if request.client else "?"
    if auth.blocked(ip):
        raise HTTPException(429, "Too many attempts")
    if not hmac.compare_digest(body.password.encode(), auth.password.encode()):
        auth.fail(ip)
        raise HTTPException(401, "Wrong password")
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    resp.set_cookie(COOKIE, auth.token(), max_age=MAX_AGE, httponly=True, samesite="lax", secure=secure)
    return resp


@router.post("/logout", status_code=204)
def logout() -> Response:
    resp = Response(status_code=204)
    resp.delete_cookie(COOKIE)
    return resp
