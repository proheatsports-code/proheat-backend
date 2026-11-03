"""Recuperacion segura de contrasenas para ProHeat Sports."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

CODE_TTL_MINUTES = 15
MAX_VERIFY_ATTEMPTS = 5
MAX_REQUESTS_PER_WINDOW = 3
REQUEST_WINDOW_MINUTES = 60


def utc_now():
    return datetime.now(timezone.utc)


def create_reset_code():
    """Genera un codigo numerico criptograficamente aleatorio."""
    return f"{secrets.randbelow(1000000):06d}"


def hash_reset_code(code, secret):
    """Genera una huella HMAC para no almacenar codigos en texto claro."""
    return hmac.new(
        secret.encode("utf-8"),
        code.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_reset_code(code, stored_hash, secret):
    """Compara la huella del codigo sin filtrar diferencias temporales."""
    candidate = hash_reset_code(code, secret)
    return hmac.compare_digest(candidate, stored_hash)


def expiration_time():
    return utc_now() + timedelta(minutes=CODE_TTL_MINUTES)


def is_expired(expires_at):
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    return utc_now() >= expires_at


def validate_new_password(password):
    """Validacion minima de seguridad para nuevas contrasenas."""
    return (
        isinstance(password, str)
        and len(password) >= 12
        and len(password) <= 128
    )
