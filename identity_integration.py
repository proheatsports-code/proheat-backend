"""Utilidades para la integración de identidad ProHeat Sports / Quinielas."""

from dataclasses import dataclass


def normalize_identity_email(email: str) -> str:
    """Normaliza un correo para búsquedas y comparaciones."""
    return email.strip().lower()


@dataclass(frozen=True)
class LinkedIdentity:
    """Relación entre las identidades de ambas plataformas."""

    quinielas_user_id: int
    proheat_user_id: str
    email: str

    def __post_init__(self):
        if self.quinielas_user_id <= 0:
            raise ValueError("ID de Quinielas inválido")

        if not self.proheat_user_id.strip():
            raise ValueError("ID de ProHeat Sports requerido")

        if not self.email.strip():
            raise ValueError("Correo requerido")

        object.__setattr__(
            self,
            "email",
            normalize_identity_email(self.email),
        )


def find_link_by_proheat_id(conn, proheat_user_id: str):
    """Busca una vinculaci?n existente por ID de ProHeat Sports."""
    row = conn.execute(
        """
        SELECT proheat_user_id, quinielas_user_id,
               verified_email, verification_method, linked_at
        FROM identity_links
        WHERE proheat_user_id = ?
        """,
        (proheat_user_id,),
    ).fetchone()

    return dict(row) if row else None


def find_link_by_quinielas_id(conn, quinielas_user_id: int):
    """Busca una vinculaci?n existente por ID de Quinielas."""
    row = conn.execute(
        """
        SELECT proheat_user_id, quinielas_user_id,
               verified_email, verification_method, linked_at
        FROM identity_links
        WHERE quinielas_user_id = ?
        """,
        (quinielas_user_id,),
    ).fetchone()

    return dict(row) if row else None


def resolve_proheat_user(conn, quinielas_user: dict):
    """
    Recupera el usuario de ProHeat Sports vinculado
    a una identidad previamente verificada de Quinielas.
    """
    quinielas_id = quinielas_user.get("id")

    if type(quinielas_id) is not int or quinielas_id <= 0:
        return None

    link = find_link_by_quinielas_id(conn, quinielas_id)

    if not link:
        return None

    central_email = quinielas_user.get("email")

    if not isinstance(central_email, str):
        return None

    if normalize_identity_email(central_email) != normalize_identity_email(
        link["verified_email"]
    ):
        return None

    conn.row_factory = __import__("sqlite3").Row

    row = conn.execute(
        "SELECT * FROM users WHERE user_id = ?",
        (link["proheat_user_id"],),
    ).fetchone()

    if not row:
        return None

    user = dict(row)

    if user.get("status") != "active":
        return None

    return user


def authenticate_linked_user(conn, quinielas_token: str):
    """
    Valida la identidad central y recupera la cuenta
    previamente vinculada de ProHeat Sports.
    """
    from central_auth_client import (
        validate_quinielas_token,
        CentralAuthError,
    )

    central_user = validate_quinielas_token(quinielas_token)

    proheat_user = resolve_proheat_user(conn, central_user)

    if proheat_user is None:
        raise CentralAuthError(
            "La cuenta central todav?a no est? vinculada con ProHeat Sports."
        )

    return {
        "central_user_id": central_user["id"],
        "proheat_user": proheat_user,
    }


def verify_existing_proheat_account(conn, email: str, password: str):
    """
    Verifica la propiedad de una cuenta existente de ProHeat.
    No crea sesiones ni modifica contrase?as.
    """
    from password_identity import verify_password

    if not isinstance(email, str) or not email.strip():
        return None

    if not isinstance(password, str) or not password:
        return None

    conn.row_factory = __import__("sqlite3").Row

    row = conn.execute(
        """
        SELECT *
        FROM users
        WHERE lower(email) = ?
        """,
        (normalize_identity_email(email),),
    ).fetchone()

    if not row:
        return None

    user = dict(row)

    if user.get("status") != "active":
        return None

    # Los administradores requieren vinculacion separada.
    if user.get("role") != "user":
        return None

    if not verify_password(
        password,
        user["password_hash"],
        user["password_salt"],
        120000,
    ):
        return None

    return user


def link_existing_accounts(conn, central_user: dict, email: str, password: str):
    """
    Vincula dos cuentas despu?s de verificar sus identidades.
    Debe llamarse ?nicamente desde una ruta autenticada y
    protegida contra intentos repetidos.
    """
    import sqlite3

    central_id = central_user.get("id")
    central_email = central_user.get("email")

    if type(central_id) is not int or central_id <= 0:
        raise ValueError("Identidad central invalida.")

    if not isinstance(central_email, str) or not central_email.strip():
        raise ValueError("Correo central invalido.")

    if str(central_user.get("status", "")).lower() != "active":
        raise ValueError("Cuenta central inactiva.")

    from identity_rate_limit import (
        is_link_blocked,
        record_failed_link,
    )

    if not isinstance(email, str) or not email.strip():
        raise ValueError("Correo de ProHeat invalido.")

    normalized_email = normalize_identity_email(email)

    if is_link_blocked(conn, central_id, normalized_email):
        raise ValueError(
            "Demasiados intentos. Intenta nuevamente en 15 minutos."
        )

    user = verify_existing_proheat_account(conn, email, password)

    if user is None:
        record_failed_link(conn, central_id, normalized_email)
        raise ValueError("No fue posible verificar la cuenta ProHeat.")

    if normalize_identity_email(user["email"]) != normalize_identity_email(central_email):
        raise ValueError("Los correos de ambas cuentas no coinciden.")

    if find_link_by_proheat_id(conn, user["user_id"]):
        raise ValueError("La cuenta ProHeat ya esta vinculada.")

    if find_link_by_quinielas_id(conn, central_id):
        raise ValueError("La cuenta Quinielas ya esta vinculada.")

    try:
        conn.execute(
            """
            INSERT INTO identity_links (
                proheat_user_id,
                quinielas_user_id,
                verified_email,
                verification_method
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                user["user_id"],
                central_id,
                normalize_identity_email(central_email),
                "central_session_and_proheat_password",
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise ValueError("Una de las cuentas ya fue vinculada.")

    return {
        "proheat_user_id": user["user_id"],
        "quinielas_user_id": central_id,
        "linked": True,
    }
