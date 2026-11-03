import sqlite3


def create_identity_links_table(conn: sqlite3.Connection) -> None:
    """Prepara la tabla de vinculación de identidades."""

    conn.execute("""
        CREATE TABLE IF NOT EXISTS identity_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proheat_user_id TEXT NOT NULL UNIQUE,
            quinielas_user_id INTEGER NOT NULL UNIQUE,
            verified_email TEXT NOT NULL,
            verification_method TEXT NOT NULL,
            linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (proheat_user_id)
                REFERENCES users(user_id)
        )
    """)

    conn.commit()


def create_identity_link_attempts_table(conn):
    """
    Registra intentos fallidos de vinculacion sin guardar
    contrasenas ni tokens.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS identity_link_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            central_user_id INTEGER NOT NULL,
            target_email TEXT NOT NULL,
            attempted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_identity_link_attempts
        ON identity_link_attempts (
            central_user_id,
            target_email,
            attempted_at
        )
    """)

    conn.commit()
