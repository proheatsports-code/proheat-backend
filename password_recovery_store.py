"""Almacenamiento SQLite para recuperacion de cuentas ProHeat."""

from datetime import datetime, timedelta, timezone

from password_recovery import (
    CODE_TTL_MINUTES,
    MAX_VERIFY_ATTEMPTS,
    MAX_REQUESTS_PER_WINDOW,
    REQUEST_WINDOW_MINUTES,
    create_reset_code,
    expiration_time,
    hash_reset_code,
    utc_now,
    verify_reset_code,
)


def create_recovery_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            code_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            used INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_password_reset_user
        ON password_reset_codes(user_id)
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_hash TEXT NOT NULL,
            requested_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_password_reset_requests
        ON password_reset_requests(email_hash, requested_at)
    """)

    conn.commit()


def normalize_email(email):
    return str(email).strip().lower()


def email_fingerprint(email, secret):
    return hash_reset_code(normalize_email(email), secret)


def request_allowed(conn, email, secret):
    cutoff = (
        utc_now() - timedelta(minutes=REQUEST_WINDOW_MINUTES)
    ).isoformat()

    fingerprint = email_fingerprint(email, secret)

    count = conn.execute(
        """
        SELECT COUNT(*)
        FROM password_reset_requests
        WHERE email_hash = ?
          AND requested_at >= ?
        """,
        (fingerprint, cutoff),
    ).fetchone()[0]

    return count < MAX_REQUESTS_PER_WINDOW


def record_request(conn, email, secret):
    conn.execute(
        """
        INSERT INTO password_reset_requests (
            email_hash, requested_at
        )
        VALUES (?, ?)
        """,
        (
            email_fingerprint(email, secret),
            utc_now().isoformat(),
        ),
    )
    conn.commit()


def create_recovery_code(conn, user_id, secret):
    code = create_reset_code()

    conn.execute(
        """
        UPDATE password_reset_codes
        SET used = 1
        WHERE user_id = ?
          AND used = 0
        """,
        (user_id,),
    )

    conn.execute(
        """
        INSERT INTO password_reset_codes (
            user_id,
            code_hash,
            created_at,
            expires_at,
            attempts,
            used
        )
        VALUES (?, ?, ?, ?, 0, 0)
        """,
        (
            user_id,
            hash_reset_code(code, secret),
            utc_now().isoformat(),
            expiration_time().isoformat(),
        ),
    )

    conn.commit()
    return code


def check_recovery_code(conn, user_id, code, secret):
    row = conn.execute(
        """
        SELECT *
        FROM password_reset_codes
        WHERE user_id = ?
          AND used = 0
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()

    if not row:
        return False

    if row["attempts"] >= MAX_VERIFY_ATTEMPTS:
        return False

    expires_at = datetime.fromisoformat(row["expires_at"])

    if utc_now() >= expires_at:
        return False

    valid = verify_reset_code(
        code,
        row["code_hash"],
        secret,
    )

    if not valid:
        conn.execute(
            """
            UPDATE password_reset_codes
            SET attempts = attempts + 1
            WHERE id = ?
            """,
            (row["id"],),
        )
        conn.commit()

    return valid


def consume_recovery_code(conn, user_id):
    conn.execute(
        """
        UPDATE password_reset_codes
        SET used = 1
        WHERE user_id = ?
          AND used = 0
        """,
        (user_id,),
    )
    conn.commit()


def apply_password_reset(conn, user_id, code, secret, new_password):
    """
    Valida el codigo, actualiza la contrasena central
    e invalida todas las sesiones del usuario en una
    unica transaccion SQLite.

    La conexion debe estar configurada con row_factory
    sqlite3.Row y hash_password debe ser la funcion
    oficial del backend central.
    """
    from backend import hash_password
    from password_recovery import validate_new_password

    if not validate_new_password(new_password):
        raise ValueError(
            "La contrasena debe tener entre 12 y 128 caracteres."
        )

    if not isinstance(code, str) or len(code) != 6 or not code.isdigit():
        return False

    # El bloqueo de escritura evita que dos operaciones
    # consuman simultaneamente el mismo codigo.
    conn.execute("BEGIN IMMEDIATE")

    try:
        row = conn.execute(
            """
            SELECT *
            FROM password_reset_codes
            WHERE user_id = ?
              AND used = 0
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

        if row is None:
            conn.rollback()
            return False

        if row["attempts"] >= MAX_VERIFY_ATTEMPTS:
            conn.rollback()
            return False

        expires_at = datetime.fromisoformat(row["expires_at"])

        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if utc_now() >= expires_at:
            conn.rollback()
            return False

        if not verify_reset_code(code, row["code_hash"], secret):
            conn.execute(
                """
                UPDATE password_reset_codes
                SET attempts = attempts + 1
                WHERE id = ?
                """,
                (row["id"],),
            )
            conn.commit()
            return False

        new_hash, new_salt = hash_password(new_password)

        result = conn.execute(
            """
            UPDATE users
            SET password_hash = ?,
                password_salt = ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (
                new_hash,
                new_salt,
                utc_now().isoformat(),
                user_id,
            ),
        )

        if result.rowcount != 1:
            conn.rollback()
            return False

        conn.execute(
            """
            UPDATE password_reset_codes
            SET used = 1
            WHERE user_id = ?
              AND used = 0
            """,
            (user_id,),
        )

        conn.execute(
            """
            DELETE FROM sessions
            WHERE user_id = ?
            """,
            (user_id,),
        )

        conn.commit()
        return True

    except Exception:
        conn.rollback()
        raise


def reserve_recovery_request(conn, email, secret):
    """
    Reserva una solicitud de recuperacion de forma atomica.

    Devuelve True si la solicitud fue admitida.
    Devuelve False si se alcanzo el limite.

    No debe llamarse dentro de otra transaccion activa.
    """
    if conn.in_transaction:
        raise RuntimeError(
            "reserve_recovery_request requiere una conexion sin "
            "transaccion activa"
        )

    conn.execute("BEGIN IMMEDIATE")

    try:
        cutoff = (
            utc_now() - timedelta(minutes=REQUEST_WINDOW_MINUTES)
        ).isoformat()

        fingerprint = email_fingerprint(email, secret)

        count = conn.execute(
            """
            SELECT COUNT(*)
            FROM password_reset_requests
            WHERE email_hash = ?
              AND requested_at >= ?
            """,
            (fingerprint, cutoff),
        ).fetchone()[0]

        if count >= MAX_REQUESTS_PER_WINDOW:
            conn.rollback()
            return False

        conn.execute(
            """
            INSERT INTO password_reset_requests (
                email_hash, requested_at
            )
            VALUES (?, ?)
            """,
            (fingerprint, utc_now().isoformat()),
        )

        conn.commit()
        return True

    except Exception:
        conn.rollback()
        raise


IP_REQUEST_LIMIT = 10
IP_REQUEST_WINDOW_MINUTES = 60


def create_recovery_ip_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_ip_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_hash TEXT NOT NULL,
            requested_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_password_reset_ip_requests
        ON password_reset_ip_requests(ip_hash, requested_at)
    """)

    conn.commit()


def reserve_recovery_request_with_ip(conn, email, ip, secret):
    """
    Reserva una solicitud aplicando simultaneamente:
    - Maximo 3 solicitudes por correo en 60 minutos.
    - Maximo 10 solicitudes por IP en 60 minutos.

    La conexion debe estar fuera de una transaccion activa.
    """
    import hmac
    import hashlib

    if conn.in_transaction:
        raise RuntimeError("La conexion ya tiene una transaccion activa")

    ip_hash = hmac.new(
        secret.encode("utf-8"),
        ("ip:" + ip).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    email_hash = email_fingerprint(email, secret)

    cutoff = (
        utc_now() - timedelta(minutes=60)
    ).isoformat()

    conn.execute("BEGIN IMMEDIATE")

    try:
        email_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM password_reset_requests
            WHERE email_hash = ? AND requested_at >= ?
            """,
            (email_hash, cutoff),
        ).fetchone()[0]

        ip_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM password_reset_ip_requests
            WHERE ip_hash = ? AND requested_at >= ?
            """,
            (ip_hash, cutoff),
        ).fetchone()[0]

        if (
            email_count >= MAX_REQUESTS_PER_WINDOW
            or ip_count >= IP_REQUEST_LIMIT
        ):
            conn.rollback()
            return False

        timestamp = utc_now().isoformat()

        conn.execute(
            """
            INSERT INTO password_reset_requests
            (email_hash, requested_at)
            VALUES (?, ?)
            """,
            (email_hash, timestamp),
        )

        conn.execute(
            """
            INSERT INTO password_reset_ip_requests
            (ip_hash, requested_at)
            VALUES (?, ?)
            """,
            (ip_hash, timestamp),
        )

        conn.commit()
        return True

    except Exception:
        conn.rollback()
        raise


def create_reset_attempts_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_verify_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_hash TEXT NOT NULL,
            attempted_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_password_reset_verify_ip
        ON password_reset_verify_attempts(ip_hash, attempted_at)
    """)
    conn.commit()


def reserve_reset_verification_attempt(conn, ip, secret):
    import hashlib
    import hmac
    from datetime import datetime, timedelta, timezone

    ip_hash = hmac.new(
        secret.encode("utf-8"),
        ("verify-ip:" + ip).encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=1)).isoformat()

    conn.execute("BEGIN IMMEDIATE")

    try:
        conn.execute(
            "DELETE FROM password_reset_verify_attempts "
            "WHERE attempted_at < ?",
            (cutoff,)
        )

        count = conn.execute(
            "SELECT COUNT(*) FROM password_reset_verify_attempts "
            "WHERE ip_hash = ? AND attempted_at >= ?",
            (ip_hash, cutoff)
        ).fetchone()[0]

        if count >= 10:
            conn.rollback()
            return False

        conn.execute(
            "INSERT INTO password_reset_verify_attempts "
            "(ip_hash, attempted_at) VALUES (?, ?)",
            (ip_hash, now.isoformat())
        )

        conn.commit()
        return True

    except Exception:
        conn.rollback()
        raise
