from __future__ import annotations

import logging
import os
import sqlite3
import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from password_recovery import validate_new_password
from password_recovery_store import (
    normalize_email,
    reserve_recovery_request_with_ip,
    create_recovery_code,
    apply_password_reset,
    reserve_reset_verification_attempt,
)
from proheat_mailer import mail_configured, send_password_reset_email


router = APIRouter()
logger = logging.getLogger(__name__)

GENERIC_RESPONSE = {
    "message": (
        "Si el correo esta registrado, recibiras "
        "instrucciones para recuperar tu cuenta."
    )
}


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=12, max_length=128)


def recovery_enabled():
    return os.getenv(
        "PROHEAT_PASSWORD_RECOVERY_ENABLED", "false"
    ).lower() == "true"


def recovery_secret():
    secret = os.getenv("PROHEAT_PASSWORD_RESET_SECRET", "")

    if len(secret) < 48:
        raise HTTPException(
            status_code=503,
            detail="Servicio temporalmente no disponible."
        )

    return secret


def notify_quinielas_password_revoked(central_user_id):
    """Notify Quinielas after a successful central password reset.

    Requires matching PROHEAT_AUTH_SYNC_SECRET in both services and
    PROHEAT_QUINIELAS_API_URL in the central service.
    """
    base_url = os.getenv("PROHEAT_QUINIELAS_API_URL", "").strip().rstrip("/")
    secret = os.getenv("PROHEAT_AUTH_SYNC_SECRET", "")
    if not base_url or len(secret) < 48:
        logger.error("Quinielas revocation notification not configured")
        return False
    parsed = urllib.parse.urlsplit(base_url)
    if not (parsed.scheme == "https" or (
        parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")
    )) or parsed.username or parsed.password or parsed.query or parsed.fragment:
        logger.error("Invalid Quinielas revocation endpoint configuration")
        return False
    body = json.dumps({
        "central_user_id": str(central_user_id),
        "timestamp": int(time.time()),
    }, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        base_url + "/auth/internal/central-password-revoked",
        data=body,
        headers={"Content-Type": "application/json", "X-ProHeat-Signature": signature},
        method="POST",
    )
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=8) as response:
            return response.status == 200
    except Exception:
        logger.exception("Quinielas token revocation notification failed")
        return False


def register_recovery_routes(app, db_connect):
    """
    Registra las rutas con acceso a la conexion
    oficial del backend central.
    """

    @router.post("/auth/forgot-password")
    def forgot_password(payload: ForgotPasswordIn, request: Request):

        if not recovery_enabled():
            raise HTTPException(
                status_code=503,
                detail="Recuperacion temporalmente desactivada."
            )

        secret = recovery_secret()

        if not mail_configured():
            raise HTTPException(
                status_code=503,
                detail="Servicio temporalmente no disponible."
            )

        email = normalize_email(str(payload.email))

        # No confiar en X-Forwarded-For recibido directamente.
        # La IP depende de la configuracion segura del proxy.
        client_ip = (
            request.client.host
            if request.client
            else "unknown"
        )

        conn = db_connect()

        try:
            allowed = reserve_recovery_request_with_ip(
                conn, email, client_ip, secret
            )

            if not allowed:
                return GENERIC_RESPONSE

            user = conn.execute(
                "SELECT user_id FROM users WHERE lower(email) = ?",
                (email,),
            ).fetchone()

            if user is None:
                return GENERIC_RESPONSE

            code = create_recovery_code(
                conn, user["user_id"], secret
            )

            try:
                send_password_reset_email(email, code)
            except Exception:
                logger.exception(
                    "No se pudo enviar correo de recuperacion"
                )

            return GENERIC_RESPONSE

        finally:
            conn.close()

    @router.post("/auth/reset-password")
    def reset_password(payload: ResetPasswordIn, request: Request):

        if not recovery_enabled():
            raise HTTPException(
                status_code=503,
                detail="Recuperacion temporalmente desactivada."
            )

        secret = recovery_secret()

        if not validate_new_password(payload.new_password):
            raise HTTPException(
                status_code=422,
                detail="La contrasena debe tener entre 12 y 128 caracteres."
            )

        email = normalize_email(str(payload.email))

        conn = db_connect()

        try:
            client_ip = (
                request.client.host
                if request.client
                else "unknown"
            )

            allowed = reserve_reset_verification_attempt(
                conn, client_ip, secret
            )

            if not allowed:
                raise HTTPException(
                    status_code=429,
                    detail="Demasiados intentos. Intenta mas tarde."
                )

            user = conn.execute(
                "SELECT user_id FROM users WHERE lower(email) = ?",
                (email,),
            ).fetchone()

            if user is None:
                raise HTTPException(
                    status_code=400,
                    detail="Codigo invalido o expirado."
                )

            success = apply_password_reset(
                conn,
                user["user_id"],
                payload.code,
                secret,
                payload.new_password,
            )

            if not success:
                raise HTTPException(
                    status_code=400,
                    detail="Codigo invalido o expirado."
                )

            # The central password is already updated. Invalidate all linked
            # Quinielas tokens, including resets initiated on the central site.
            notified = notify_quinielas_password_revoked(user["user_id"])
            if not notified:
                logger.error("SECURITY: Quinielas token revocation pending for central user %s", user["user_id"])
            return {
                "message": "Contrasena actualizada correctamente.",
                "quinielas_sessions_revoked": notified,
            }

        finally:
            conn.close()

    app.include_router(router)
