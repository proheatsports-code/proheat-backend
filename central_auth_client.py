"""Cliente de autenticación central de ProHeat Quinielas."""

import os
import requests


QUINIELAS_API_URL = os.getenv(
    "QUINIELAS_API_URL",
    "https://backend-production-3cdc2.up.railway.app",
).rstrip("/")


class CentralAuthError(Exception):
    """Error al validar una identidad central."""


def validate_quinielas_token(token: str) -> dict:
    """
    Consulta Quinielas para comprobar que un token sea válido.

    No crea usuarios, no modifica datos y no registra sesiones.
    """
    if not token or not token.strip():
        raise CentralAuthError("Token requerido.")

    try:
        response = requests.get(
            f"{QUINIELAS_API_URL}/me",
            headers={
                "Authorization": f"Bearer {token.strip()}",
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        raise CentralAuthError(
            "No fue posible conectar con la autenticación central."
        ) from exc

    if response.status_code != 200:
        raise CentralAuthError(
            "No fue posible validar la sesión en Quinielas."
        )

    try:
        user = response.json()
    except ValueError as exc:
        raise CentralAuthError(
            "Respuesta inválida del servidor de autenticación."
        ) from exc

    if not isinstance(user, dict):
        raise CentralAuthError("Respuesta de usuario inv?lida.")

    user_id = user.get("id")
    email = user.get("email")

    if type(user_id) is not int or user_id <= 0:
        raise CentralAuthError("Identificador central inv?lido.")

    if not isinstance(email, str) or not email.strip():
        raise CentralAuthError("Correo central inv?lido.")

    if str(user.get("status", "")).lower() != "active":
        raise CentralAuthError("La cuenta central no est? activa.")

    user["email"] = email.strip().lower()

    return user
