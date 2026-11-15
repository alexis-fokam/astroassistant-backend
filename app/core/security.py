"""Sécurité des profils locaux (§7) : hachage des PIN et jetons de session signés.

Bibliothèque standard uniquement. Les PIN sont hachés en PBKDF2-SHA256. Après connexion,
l'API émet un jeton sans état ``<id du membre>.<expiration>.<HMAC-SHA256>`` signé avec
``AV_SECRET_KEY``.
"""

import base64
import hashlib
import hmac
import secrets
import time

_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 200_000


def hash_pin(pin: str) -> str:
    """Renvoie ``pbkdf2_sha256$<itérations>$<sel hex>$<empreinte hex>``."""
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
    """Id du membre porté par un jeton valide et non expiré ; None sinon."""
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
