from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
import shutil
import requests
import os
import json
from typing import Any

# =========================================================
# CONFIGURACIÓN
# =========================================================
BASE_DIR = Path(__file__).resolve().parent
DB_NAME = BASE_DIR / "proheat.db"
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

PROHEAT_DATA_DIR = BASE_DIR / "proheat_data"
PROHEAT_HISTORY_DIR = PROHEAT_DATA_DIR / "history"
PROHEAT_LATEST_JSON = PROHEAT_DATA_DIR / "latest.json"

PROHEAT_DATA_DIR.mkdir(exist_ok=True)
PROHEAT_HISTORY_DIR.mkdir(exist_ok=True)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

app = FastAPI(title="ProHeat Sports Backend")

print("🚀 Backend ProHeat v2 activo")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://proheatsports.com",
        "https://www.proheatsports.com",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================
# MODELOS
# =========================================================
class UserRegister(BaseModel):
    name: str
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class AdminNote(BaseModel):
    note: str | None = None

class ExtendMembershipRequest(BaseModel):
    days: int = 30


# =========================================================
# DB
# =========================================================
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'none',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_login TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS memberships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payment_proofs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            status TEXT NOT NULL DEFAULT 'submitted',
            admin_note TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


init_db()


# =========================================================
# FUNCIONES AUXILIARES
# =========================================================
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def send_telegram_message(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=10
        )
    except Exception as e:
        print(f"[WARN] No se pudo enviar mensaje a Telegram: {e}")


def send_telegram_document(file_path: str, caption: str = ""):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
    try:
        with open(file_path, "rb") as f:
            requests.post(
                url,
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": caption
                },
                files={
                    "document": f
                },
                timeout=20
            )
    except Exception as e:
        print(f"[WARN] No se pudo enviar archivo a Telegram: {e}")


def user_exists(user_id: int) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None


def log_admin_action(admin_id: int, user_id: int, action: str, details: str = ""):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO admin_actions (admin_id, user_id, action, details)
        VALUES (?, ?, ?, ?)
    """, (admin_id, user_id, action, details))
    conn.commit()
    conn.close()


def get_latest_membership(user_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT *
        FROM memberships
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 1
    """, (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result


def expire_membership_if_needed(user_id: int):
    membership = get_latest_membership(user_id)
    if not membership:
        return

    end_date = membership["end_date"]
    status = membership["status"]

    if not end_date or status != "active":
        return

    try:
        end_dt = datetime.fromisoformat(end_date)
    except ValueError:
        return

    if datetime.now() > end_dt:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE memberships
            SET status = 'expired'
            WHERE id = ?
        """, (membership["id"],))

        cursor.execute("""
            UPDATE users
            SET status = 'expired'
            WHERE id = ?
        """, (user_id,))

        conn.commit()
        conn.close()


def create_or_replace_membership(user_id: int, days: int = 30, plan_name: str = "premium_mensual"):
    start_dt = datetime.now()
    end_dt = start_dt + timedelta(days=days)

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO memberships (user_id, plan_name, status, start_date, end_date)
        VALUES (?, ?, 'active', ?, ?)
    """, (
        user_id,
        plan_name,
        start_dt.isoformat(timespec="seconds"),
        end_dt.isoformat(timespec="seconds")
    ))

    cursor.execute("""
        UPDATE users
        SET status = 'active'
        WHERE id = ?
    """, (user_id,))

    conn.commit()
    conn.close()

    return {
        "start_date": start_dt.isoformat(timespec="seconds"),
        "end_date": end_dt.isoformat(timespec="seconds")
    }


# =========================================================
# FUNCIONES DATOS PROHEAT
# =========================================================
def load_latest_predictions() -> dict[str, Any]:
    if not PROHEAT_LATEST_JSON.exists():
        raise HTTPException(
            status_code=404,
            detail="No se encontró latest.json en proheat_data"
        )

    try:
        with open(PROHEAT_LATEST_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="latest.json está corrupto o no es JSON válido"
        )

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=500,
            detail="latest.json no tiene el formato esperado"
        )

    return data


def get_prediction_section(section: str) -> list[dict[str, Any]]:
    data = load_latest_predictions()

    if section not in data:
        raise HTTPException(
            status_code=404,
            detail=f"No existe la sección '{section}' en latest.json"
        )

    section_data = data[section]

    if not isinstance(section_data, list):
        raise HTTPException(
            status_code=500,
            detail=f"La sección '{section}' no tiene formato de lista"
        )

    return section_data


def load_history_by_date(date_str: str) -> dict[str, Any]:
    file_path = PROHEAT_HISTORY_DIR / f"predictions_{date_str}.json"

    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No existe histórico para la fecha {date_str}"
        )

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail=f"El archivo histórico {file_path.name} no es JSON válido"
        )

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=500,
            detail=f"El histórico {file_path.name} no tiene el formato esperado"
        )

    return data


# =========================================================
# ENDPOINTS BÁSICOS
# =========================================================
@app.get("/")
def root():
    return {"message": "ProHeat backend activo"}


@app.get("/debug/db")
def debug_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    tables = [row["name"] for row in cursor.fetchall()]

    conn.close()

    return {
        "db_path": str(DB_NAME),
        "db_exists": DB_NAME.exists(),
        "tables": tables
    }


@app.get("/debug/data")
def debug_data():
    return {
        "data_dir": str(PROHEAT_DATA_DIR),
        "history_dir": str(PROHEAT_HISTORY_DIR),
        "latest_json": str(PROHEAT_LATEST_JSON),
        "latest_exists": PROHEAT_LATEST_JSON.exists()
    }


# =========================================================
# REGISTRO
# =========================================================
@app.post("/register")
def register(user: UserRegister):
    conn = get_db()
    cursor = conn.cursor()

    password_hash = hash_password(user.password)

    try:
        cursor.execute("""
            INSERT INTO users (name, email, password_hash, status)
            VALUES (?, ?, ?, 'none')
        """, (
            user.name.strip(),
            user.email.strip().lower(),
            password_hash
        ))

        conn.commit()
        new_user_id = cursor.lastrowid

        send_telegram_message(
            f"🆕 Nuevo usuario registrado en ProHeat Sports\n"
            f"ID: {new_user_id}\n"
            f"Nombre: {user.name.strip()}\n"
            f"Correo: {user.email.strip().lower()}\n"
            f"Estado: none"
        )

        return {
            "message": "Usuario creado correctamente",
            "user_id": new_user_id
        }

    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="El correo ya existe")
    finally:
        conn.close()


# =========================================================
# LOGIN
# =========================================================
@app.post("/login")
def login(user: UserLogin):
    conn = get_db()
    cursor = conn.cursor()

    password_hash = hash_password(user.password)

    cursor.execute("""
        SELECT id, name, status
        FROM users
        WHERE email = ? AND password_hash = ?
    """, (user.email.strip().lower(), password_hash))

    result = cursor.fetchone()

    if not result:
        conn.close()
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")

    user_id = result["id"]
    expire_membership_if_needed(user_id)

    cursor.execute("""
        SELECT id, name, status
        FROM users
        WHERE id = ?
    """, (user_id,))
    updated_user = cursor.fetchone()

    cursor.execute("""
        UPDATE users
        SET last_login = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (user_id,))

    conn.commit()
    conn.close()

    return {
        "message": "Login correcto",
        "user_id": updated_user["id"],
        "name": updated_user["name"],
        "status": updated_user["status"]
    }


# =========================================================
# MEMBRESÍA
# =========================================================
@app.get("/membership/{user_id}")
def membership(user_id: int):
    if not user_exists(user_id):
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    expire_membership_if_needed(user_id)
    current_membership = get_latest_membership(user_id)

    if not current_membership:
        return {"membership": "none"}

    return {
        "membership": current_membership["status"],
        "plan_name": current_membership["plan_name"],
        "start_date": current_membership["start_date"],
        "end_date": current_membership["end_date"]
    }


# =========================================================
# SUBIR COMPROBANTE
# =========================================================
@app.post("/upload-proof/{user_id}")
async def upload_proof(user_id: int, file: UploadFile = File(...)):
    if not user_exists(user_id):
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    original_name = Path(file.filename).name
    safe_name = f"user_{user_id}_{timestamp}_{original_name}"
    file_path = UPLOADS_DIR / safe_name

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO payment_proofs (user_id, file_path, status)
        VALUES (?, ?, 'submitted')
    """, (user_id, str(file_path)))

    cursor.execute("""
        UPDATE users
        SET status = 'pending'
        WHERE id = ?
    """, (user_id,))

    conn.commit()
    conn.close()

    caption = (
        f"📩 Nuevo comprobante recibido\n"
        f"Usuario ID: {user_id}\n"
        f"Archivo: {safe_name}\n"
        f"Estado: pending\n"
        f"La aprobación puede tardar hasta 24 horas."
    )

    send_telegram_message(
        f"📩 Nuevo comprobante recibido\n"
        f"Usuario ID: {user_id}\n"
        f"Archivo: {safe_name}\n"
        f"Ruta: {file_path}\n"
        f"Estado: pending\n"
        f"La aprobación puede tardar hasta 24 horas."
    )

    send_telegram_document(str(file_path), caption)

    return {
        "message": "Comprobante subido correctamente. La aprobación puede tardar hasta 24 horas.",
        "file_path": str(file_path)
    }


# =========================================================
# LISTAR COMPROBANTES
# =========================================================
@app.get("/payment-proofs")
def list_payment_proofs():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT pp.id, pp.user_id, pp.file_path, pp.submitted_at, pp.status, pp.admin_note,
               u.name, u.email
        FROM payment_proofs pp
        LEFT JOIN users u ON pp.user_id = u.id
        ORDER BY pp.id DESC
    """)

    results = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return results


# =========================================================
# APROBAR
# =========================================================
@app.post("/approve/{user_id}")
def approve_user(user_id: int):
    if not user_exists(user_id):
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    membership_data = create_or_replace_membership(user_id=user_id, days=30)

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE payment_proofs
        SET status = 'approved'
        WHERE user_id = ? AND status IN ('submitted', 'under_review')
    """, (user_id,))

    conn.commit()
    conn.close()

    log_admin_action(admin_id=1, user_id=user_id, action="approve", details="Usuario aprobado manualmente")

    send_telegram_message(
        f"✅ Usuario aprobado\n"
        f"Usuario ID: {user_id}\n"
        f"Inicio: {membership_data['start_date']}\n"
        f"Fin: {membership_data['end_date']}"
    )

    return {
        "message": "Usuario aprobado correctamente",
        "membership_start": membership_data["start_date"],
        "membership_end": membership_data["end_date"]
    }


# =========================================================
# RECHAZAR
# =========================================================
@app.post("/reject/{user_id}")
def reject_user(user_id: int, payload: AdminNote | None = None):
    if not user_exists(user_id):
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    note = payload.note if payload else ""

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE users
        SET status = 'rejected'
        WHERE id = ?
    """, (user_id,))

    cursor.execute("""
        UPDATE payment_proofs
        SET status = 'rejected',
            admin_note = ?
        WHERE user_id = ? AND status IN ('submitted', 'under_review')
    """, (note, user_id))

    conn.commit()
    conn.close()

    log_admin_action(admin_id=1, user_id=user_id, action="reject", details=note or "Comprobante rechazado")

    send_telegram_message(
        f"❌ Usuario rechazado\n"
        f"Usuario ID: {user_id}\n"
        f"Nota: {note or 'Sin nota'}"
    )

    return {"message": "Usuario rechazado correctamente"}


# =========================================================
# SUSPENDER
# =========================================================
@app.post("/suspend/{user_id}")
def suspend_user(user_id: int, payload: AdminNote | None = None):
    if not user_exists(user_id):
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    note = payload.note if payload else ""

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE users
        SET status = 'suspended'
        WHERE id = ?
    """, (user_id,))

    cursor.execute("""
        UPDATE memberships
        SET status = 'cancelled'
        WHERE user_id = ? AND status = 'active'
    """, (user_id,))

    conn.commit()
    conn.close()

    log_admin_action(admin_id=1, user_id=user_id, action="suspend", details=note or "Usuario suspendido manualmente")

    send_telegram_message(
        f"⛔ Usuario suspendido\n"
        f"Usuario ID: {user_id}\n"
        f"Nota: {note or 'Sin nota'}"
    )

    return {"message": "Usuario suspendido correctamente"}


# =========================================================
# ELIMINAR
# =========================================================
@app.post("/delete/{user_id}")
def delete_user(user_id: int, payload: AdminNote | None = None):
    if not user_exists(user_id):
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    note = payload.note if payload else ""

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE users
        SET status = 'deleted'
        WHERE id = ?
    """, (user_id,))

    cursor.execute("""
        UPDATE memberships
        SET status = 'cancelled'
        WHERE user_id = ? AND status = 'active'
    """, (user_id,))

    conn.commit()
    conn.close()

    log_admin_action(admin_id=1, user_id=user_id, action="delete", details=note or "Usuario eliminado manualmente")

    send_telegram_message(
        f"🗑️ Usuario eliminado\n"
        f"Usuario ID: {user_id}\n"
        f"Nota: {note or 'Sin nota'}"
    )

    return {"message": "Usuario eliminado correctamente"}


# =========================================================
# EXTENDER MEMBRESÍA
# =========================================================
@app.post("/extend-membership/{user_id}")
def extend_membership(user_id: int, payload: ExtendMembershipRequest):
    if not user_exists(user_id):
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    latest = get_latest_membership(user_id)

    if latest and latest["end_date"]:
        try:
            current_end = datetime.fromisoformat(latest["end_date"])
            if current_end < datetime.now():
                current_end = datetime.now()
        except ValueError:
            current_end = datetime.now()
    else:
        current_end = datetime.now()

    new_end = current_end + timedelta(days=payload.days)

    conn = get_db()
    cursor = conn.cursor()

    if latest:
        cursor.execute("""
            UPDATE memberships
            SET status = 'active',
                end_date = ?
            WHERE id = ?
        """, (new_end.isoformat(timespec="seconds"), latest["id"]))
    else:
        cursor.execute("""
            INSERT INTO memberships (user_id, plan_name, status, start_date, end_date)
            VALUES (?, ?, 'active', ?, ?)
        """, (
            user_id,
            "premium_mensual",
            datetime.now().isoformat(timespec="seconds"),
            new_end.isoformat(timespec="seconds")
        ))

    cursor.execute("""
        UPDATE users
        SET status = 'active'
        WHERE id = ?
    """, (user_id,))

    conn.commit()
    conn.close()

    log_admin_action(
        admin_id=1,
        user_id=user_id,
        action="extend_membership",
        details=f"Extendida {payload.days} días hasta {new_end.isoformat(timespec='seconds')}"
    )

    send_telegram_message(
        f"📅 Membresía extendida\n"
        f"Usuario ID: {user_id}\n"
        f"Días agregados: {payload.days}\n"
        f"Nuevo fin: {new_end.isoformat(timespec='seconds')}"
    )

    return {
        "message": "Membresía extendida correctamente",
        "new_end_date": new_end.isoformat(timespec="seconds")
    }


# =========================================================
# API DE DATOS PROHEAT
# =========================================================
@app.get("/api/data")
def api_data_root():
    data = load_latest_predictions()
    return {
        "message": "API de datos ProHeat activa",
        "date": data.get("date"),
        "source_file": data.get("source_file"),
        "generated_at": data.get("generated_at"),
        "sections": [
            key for key, value in data.items()
            if isinstance(value, list)
        ]
    }


@app.get("/api/data/summary")
def api_data_summary():
    data = load_latest_predictions()

    summary = {}
    for key, value in data.items():
        if isinstance(value, list):
            summary[key] = len(value)

    return {
        "date": data.get("date"),
        "source_file": data.get("source_file"),
        "generated_at": data.get("generated_at"),
        "summary": summary
    }


@app.get("/api/data/public")
def api_data_public():
    rows = get_prediction_section("public")
    return {"count": len(rows), "items": rows}


@app.get("/api/data/general")
def api_data_general():
    rows = get_prediction_section("general")
    return {"count": len(rows), "items": rows}


@app.get("/api/data/ultra")
def api_data_ultra():
    rows = get_prediction_section("ultra")
    return {"count": len(rows), "items": rows}


@app.get("/api/data/stakes")
def api_data_stakes():
    rows = get_prediction_section("stakes")
    return {"count": len(rows), "items": rows}


@app.get("/api/data/combinadas")
def api_data_combinadas():
    rows = get_prediction_section("combinadas")
    return {"count": len(rows), "items": rows}


@app.get("/api/data/goles")
def api_data_goles():
    rows = get_prediction_section("goles")
    return {"count": len(rows), "items": rows}


@app.get("/api/data/top")
def api_data_top():
    rows = get_prediction_section("top")
    return {"count": len(rows), "items": rows}


@app.get("/api/data/alta-confianza")
def api_data_alta_confianza():
    rows = get_prediction_section("alta_confianza")
    return {"count": len(rows), "items": rows}


@app.get("/api/data/history/{date_str}")
def api_data_history(date_str: str):
    """
    Ejemplo:
    /api/data/history/2026-03-30
    """
    data = load_history_by_date(date_str)
    return data