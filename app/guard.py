"""Device allowlist. Enrolled devices carry a random token cookie; only its hash is stored.

Mode "auto": the guard applies only to requests that came in from the internet — through
Cloudflare (it always sets CF-Connecting-IP / CF-Ray and a client cannot remove them),
over https (X-Forwarded-Proto), or addressed to a public hostname. Plain LAN / Tailscale
requests carry none of these and pass straight through.
"""
import hashlib
import json
import secrets
import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse

from . import config

COOKIE = "gcmv_device"
# Fetched by the browser WITHOUT cookies when deciding whether the site can be installed as an
# app; they hold nothing private (name, colours, the school crest).
PUBLIC_PATHS = {"/manifest.webmanifest", "/static/icon-192.png", "/static/icon-512.png", "/static/favicon.png"}
ONE_YEAR = 365 * 24 * 3600


def _load() -> dict:
    if config.DEVICES.exists():
        return json.loads(config.DEVICES.read_text())
    return {"devices": [], "enroll": []}


def _save(d: dict):
    config.DEVICES.write_text(json.dumps(d, indent=2))


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---- used by manage.py ----------------------------------------------------
def new_enroll_code(name: str, ttl_hours: int = 48) -> str:
    d = _load()
    code = secrets.token_urlsafe(18)
    d["enroll"].append({"code": code, "name": name, "expires": time.time() + ttl_hours * 3600})
    _save(d)
    return code


def remove_device(name: str) -> int:
    d = _load()
    before = len(d["devices"])
    d["devices"] = [x for x in d["devices"] if x["name"] != name]
    d["enroll"] = [x for x in d["enroll"] if x["name"] != name]
    _save(d)
    return before - len(d["devices"])


def list_devices() -> dict:
    return _load()


# ---- used by the app --------------------------------------------------------
def code_valid(code: str) -> bool:
    now = time.time()
    return any(e["code"] == code and e["expires"] > now for e in _load()["enroll"])


def redeem(code: str) -> tuple[str, str] | None:
    """Enroll code → (device name, fresh token). One-time use."""
    d = _load()
    now = time.time()
    hit = next((e for e in d["enroll"] if e["code"] == code and e["expires"] > now), None)
    d["enroll"] = [e for e in d["enroll"] if e is not hit and e["expires"] > now]
    if not hit:
        _save(d)
        return None
    token = secrets.token_urlsafe(32)
    d["devices"] = [x for x in d["devices"] if x["name"] != hit["name"]]
    d["devices"].append({"name": hit["name"], "token_sha256": _hash(token), "created": now})
    _save(d)
    return hit["name"], token


def device_for(request: Request) -> str | None:
    tok = request.cookies.get(COOKIE)
    if not tok:
        return None
    h = _hash(tok)
    return next((x["name"] for x in _load()["devices"] if secrets.compare_digest(x["token_sha256"], h)), None)


def from_internet(request: Request) -> bool:
    h = request.headers
    host = (h.get("host") or "").split(":")[0].lower()
    return bool(
        h.get("cf-connecting-ip") or h.get("cf-ray")
        or h.get("x-forwarded-proto", "").lower() == "https"
        or request.url.scheme == "https"
        or host in config.PUBLIC_HOSTS
    )


def guard_applies(request: Request) -> bool:
    if config.GUARD_MODE == "off":
        return False
    if config.GUARD_MODE == "always":
        return True
    return from_internet(request)


class DeviceGuard(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        p = request.url.path
        if p.startswith("/enroll/") or p in PUBLIC_PATHS or not guard_applies(request):
            return await call_next(request)
        if device_for(request) is None:
            return PlainTextResponse("Not Found", status_code=404)
        return await call_next(request)
