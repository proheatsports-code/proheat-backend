import os
import secrets

from fastapi import HTTPException


def validate_service_key(received_key: str | None) -> None:
    expected_key = os.getenv("PROHEAT_INTERNAL_SERVICE_KEY", "")

    if not expected_key:
        raise HTTPException(
            status_code=503,
            detail="Servicio de identidad no configurado.",
        )

    if not received_key or not secrets.compare_digest(
        received_key, expected_key
    ):
        raise HTTPException(
            status_code=403,
            detail="Acceso no autorizado.",
        )
