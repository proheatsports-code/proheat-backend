import sqlite3


def create_registration_operations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS registration_operations (
            operation_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
        """
    )


def find_registration_operation(
    conn: sqlite3.Connection,
    operation_id: str,
):
    cursor = conn.execute(
        """
        SELECT user_id, email
        FROM registration_operations
        WHERE operation_id = ?
        """,
        (operation_id,),
    )
    return cursor.fetchone()
