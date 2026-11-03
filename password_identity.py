"""Verificacion de contrasenas existentes de ProHeat Sports."""

import hashlib
import secrets


def verify_password(password, stored_hash, salt, iterations):
    calculated = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()

    return secrets.compare_digest(calculated, stored_hash)
