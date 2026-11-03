"""Control de intentos fallidos de vinculacion de cuentas."""

from datetime import datetime, timedelta, timezone

MAX_ATTEMPTS = 5
WINDOW_MINUTES = 15


def _cutoff():
    return (
        datetime.now(timezone.utc)
        - timedelta(minutes=WINDOW_MINUTES)
    ).strftime("%Y-%m-%d %H:%M:%S")


def is_link_blocked(conn, central_user_id, target_email):
    from identity_integration import normalize_identity_email

    email = normalize_identity_email(target_email)
    cutoff = _cutoff()

    # Limite por cuenta central, independientemente del correo.
    central_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM identity_link_attempts
        WHERE central_user_id = ?
          AND attempted_at >= ?
        """,
        (central_user_id, cutoff),
    ).fetchone()[0]

    # Limite por correo, independientemente de la cuenta central.
    email_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM identity_link_attempts
        WHERE target_email = ?
          AND attempted_at >= ?
        """,
        (email, cutoff),
    ).fetchone()[0]

    return (
        central_count >= MAX_ATTEMPTS
        or email_count >= MAX_ATTEMPTS
    )


def record_failed_link(conn, central_user_id, target_email):
    from identity_integration import normalize_identity_email

    conn.execute(
        """
        INSERT INTO identity_link_attempts (
            central_user_id,
            target_email
        )
        VALUES (?, ?)
        """,
        (
            central_user_id,
            normalize_identity_email(target_email),
        ),
    )

    conn.commit()
