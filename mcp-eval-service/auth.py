"""Shared token mint/verify for the Gate 4 demo (stdlib only).

The token stands in for an OAuth access token. Format:
    base64url(json) "." base64url(hmac-sha256(secret, payload_b64))
Payload: {"scope": <tool name>, "exp": <unix timestamp>}.
The server verifies it on every tool call: present, signature valid,
not expired, scope covers the tool.
"""

import base64
import hashlib
import hmac
import json
import time


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def mint_token(secret: str, scope: str, ttl_seconds: int = 300) -> str:
    payload = {"scope": scope, "exp": int(time.time()) + ttl_seconds}
    payload_b64 = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return payload_b64 + "." + _b64e(sig)


def verify_token(token, secret: str, required_scope: str):
    """Return (ok, reason). ok is True only if all checks pass."""
    if not token:
        return False, "missing credential"
    try:
        payload_b64, sig_b64 = token.split(".")
    except ValueError:
        return False, "malformed credential"
    try:
        payload = json.loads(_b64d(payload_b64))
        expected = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64d(sig_b64)):
            return False, "bad signature"
    except Exception:
        return False, "malformed credential"
    if not isinstance(payload, dict):
        return False, "malformed credential"
    if payload.get("scope") != required_scope:
        return False, "scope does not cover this tool"
    try:
        exp = int(payload.get("exp", 0))
    except (TypeError, ValueError):
        return False, "malformed credential"
    if exp <= int(time.time()):
        return False, "credential expired"
    return True, "ok"
