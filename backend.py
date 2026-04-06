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

# =========================================================
# CONFIGURACIÓN
# =========================================================
BASE_DIR = Path(__file__).resolve().parent
DB_NAME = BASE_DIR / "proheat.db"
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

app = FastAPI(title="ProHeat Sports Backend")

print("🚀 Backend ProHeat v2 activo")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 🔥 ABIERTO PARA PRUEBA
    allow_credentials=False,  # ⚠️ IMPORTANTE cuando usas "*"
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
# FUNCIONES AUXILIARES
# =========================================================
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def send_telegram_message(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    if TELEGRAM_TOKEN == "AQUI_TU_TOKEN_DE_BOT" or TELEGRAM_CHAT_ID == "AQUI_TU_CHAT_ID":
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

    if TELEGRAM_TOKEN == "AQUI_TU_TOKEN_DE_BOT" or TELEGRAM_CHAT_ID == "AQUI_TU_CHAT_ID":
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
            INSERT INTO users (name, email, password_hash)
            VALUES (?, ?, ?)
        """, (user.name.strip(), user.email.strip().lower(), password_hash))

        conn.commit()
        new_user_id = cursor.lastrowid

        send_telegram_message(
            f"🆕 Nuevo usuario registrado en ProHeat Sports\n"
            f"ID: {new_user_id}\n"
            f"Nombre: {user.name.strip()}\n"
            f"Correo: {user.email.strip().lower()}\n"
            f"Estado: pending"
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
# ESTADO MEMBRESÍA
# =========================================================
@app.get("/membership/{user_id}")
def membership(user_id: int):
    if not user_exists(user_id):
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    expire_membership_if_needed(user_id)
    membership = get_latest_membership(user_id)

    if not membership:
        return {"membership": "none"}

    return {
        "membership": membership["status"],
        "plan_name": membership["plan_name"],
        "start_date": membership["start_date"],
        "end_date": membership["end_date"]
    }

# =========================================================
# SUBIR COMPROBANTE
# =========================================================
@app.post("/upload-proof/{user_id}")
async def upload_proof(user_id: int, file: UploadFile = File(...)):
    if not user_exists(user_id):
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"user_{user_id}_{timestamp}_{file.filename}"
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
# VER COMPROBANTES
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
# APROBAR USUARIO
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
# RECHAZAR USUARIO
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
# SUSPENDER USUARIO
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
# ELIMINAR USUARIO (LÓGICO)
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

    log_admin_action(admin_id=1, user_id=user_id, action="extend_membership", details=f"Extendida {payload.days} días")

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
# LISTAR USUARIOS
# =========================================================
@app.get("/users")
def list_users():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name, email, role, status, created_at, last_login
        FROM users
        ORDER BY id DESC
    """)

    results = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return results
# =========================================================
# TEST TELEGRAM
# =========================================================
@app.get("/test-telegram")
def test_telegram():
    send_telegram_message("✅ Prueba de Telegram desde ProHeat Sports")
    return {"message": "Mensaje de prueba enviado"}