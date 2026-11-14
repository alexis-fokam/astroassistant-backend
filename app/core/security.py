"""Local profile security (spec §7): PIN hashing and signed session tokens.

Standard library only. PINs are hashed with PBKDF2-SHA256. After login the API issues a
stateless token ``<member id>.<expiry>.<HMAC-SHA256>`` signed with ``AV_SECRET_KEY``.
"""

import base64
import hashlib
import hmac
import secrets
import time

_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 200_000


def hash_pin(pin: str) -> str:
    """Return ``pbkdf2_sha256$<iterations>$<hex salt>$<hex digest>``."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, _ITERATIONS)
    return f"{_ALGORITHM}${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_pin(pin: str, pin_hash: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = pin_hash.split("$")
    except ValueError:
        return False
    if algorithm != _ALGORITHM:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt_hex), int(iterations))
    return hmac.compare_digest(digest.hex(), digest_hex)


def _sign(payload: str, secret: str) -> str:
    mac = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode()


def create_token(member_id: int, secret: str, ttl_seconds: int, now: float | None = None) -> str:
    expires = int((now or time.time()) + ttl_seconds)
    payload = f"{member_id}.{expires}"
    return f"{payload}.{_sign(payload, secret)}"


def read_token(token: str, secret: str, now: float | None = None) -> int | None:
    """Member id carried by a valid, unexpired token; None otherwise."""
    try:
        member_id, expires, signature = token.split(".")
        payload = f"{member_id}.{expires}"
        if not hmac.compare_digest(signature, _sign(payload, secret)):
            return None
        if int(expires) < (now or time.time()):
            return None
        return int(member_id)
    except ValueError:
        return None
