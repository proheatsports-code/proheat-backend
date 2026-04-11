<<<<<<< HEAD
from __future__ import annotations

import os
import json
import sqlite3
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, EmailStr

APP_NAME = "ProHeat Sports Backend"
BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = Path(os.getenv("PROHEAT_DATA_DIR", BASE_DIR / "proheat_data"))
STATIC_DIR = Path(os.getenv("PROHEAT_STATIC_DIR", BASE_DIR / "static"))
UPLOADS_DIR = Path(os.getenv("PROHEAT_UPLOADS_DIR", BASE_DIR / "proof_uploads"))
DB_PATH = Path(os.getenv("PROHEAT_DB_PATH", BASE_DIR / "proheat.db"))

DEFAULT_SUPERADMIN_NAME = os.getenv("DEFAULT_SUPERADMIN_NAME", "ProHeat Master Admin")
DEFAULT_SUPERADMIN_EMAIL = os.getenv("DEFAULT_SUPERADMIN_EMAIL", "admin@proheatsports.com")
DEFAULT_SUPERADMIN_PASSWORD = os.getenv("DEFAULT_SUPERADMIN_PASSWORD", "ProHeatAdmin123!")

PASSWORD_ITERATIONS = 120_000

DATA_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
=======
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
>>>>>>> 8939051425474de8539e4f8eb18b1c6c0e78b429
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

<<<<<<< HEAD

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return now_utc().isoformat()


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_ITERATIONS
    ).hex()
    return hashed, salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    calc_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(calc_hash, stored_hash)


def create_token() -> str:
    return secrets.token_urlsafe(48)


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
=======
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
>>>>>>> 8939051425474de8539e4f8eb18b1c6c0e78b429
    conn.row_factory = sqlite3.Row
    return conn


<<<<<<< HEAD
def normalize_membership_status(end_date: Optional[str]) -> str:
    if not end_date:
        return "pending"
    dt = parse_dt(end_date)
    if not dt:
        return "pending"
    return "active" if dt > now_utc() else "expired"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def init_db() -> None:
    ensure_dirs()
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        password_salt TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        status TEXT NOT NULL DEFAULT 'active',
        membership_start TEXT,
        membership_end TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token TEXT UNIQUE NOT NULL,
        user_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS payment_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT UNIQUE NOT NULL,
        user_id TEXT NOT NULL,
        proof_filename TEXT,
        proof_url TEXT,
        notes TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS admin_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_user_id TEXT NOT NULL,
        action TEXT NOT NULL,
        target_user_id TEXT,
        details TEXT,
        created_at TEXT NOT NULL
    )
=======
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
>>>>>>> 8939051425474de8539e4f8eb18b1c6c0e78b429
    """)

    conn.commit()
    conn.close()


<<<<<<< HEAD
def create_default_superadmin() -> None:
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users WHERE email = ?", (DEFAULT_SUPERADMIN_EMAIL,))
    existing = cur.fetchone()
    if existing:
        conn.close()
        return

    hashed, salt = hash_password(DEFAULT_SUPERADMIN_PASSWORD)
    created_at = iso_now()
    user_id = "admin_default_001"

    cur.execute("""
    INSERT INTO users (
        user_id, name, email, password_hash, password_salt,
        role, status, membership_start, membership_end, created_at, updated_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        DEFAULT_SUPERADMIN_NAME,
        DEFAULT_SUPERADMIN_EMAIL,
        hashed,
        salt,
        "superadmin",
        "active",
        created_at,
        (now_utc() + timedelta(days=3650)).isoformat(),
        created_at,
        created_at
    ))

=======
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
>>>>>>> 8939051425474de8539e4f8eb18b1c6c0e78b429
    conn.commit()
    conn.close()


<<<<<<< HEAD
def boot() -> None:
    init_db()
    create_default_superadmin()


boot()


class RegisterIn(BaseModel):
    name: str
    email: EmailStr
    password: str


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class AdminCreateSubadminIn(BaseModel):
    name: str
    email: EmailStr
    password: str


class ApproveMembershipIn(BaseModel):
    user_id: str
    days: int


class DeleteRequestIn(BaseModel):
    request_id: str


class ExtendMembershipIn(BaseModel):
    user_id: str
    days: int


class ExpireMembershipIn(BaseModel):
    user_id: str


class DeleteUserIn(BaseModel):
    user_id: str


def get_token_from_header(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Token requerido.")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Formato de token inválido.")
    return authorization.replace("Bearer ", "", 1).strip()


def get_session_user_by_token(token: str) -> dict[str, Any]:
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
    SELECT s.token, s.expires_at, u.*
    FROM sessions s
    JOIN users u ON u.user_id = s.user_id
    WHERE s.token = ?
    """, (token,))
    row = cur.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=401, detail="Sesión inválida.")

    expires_at = parse_dt(row["expires_at"])
    if not expires_at or expires_at <= now_utc():
        raise HTTPException(status_code=401, detail="Sesión expirada.")

    return dict(row)


def require_logged_user(authorization: Optional[str] = Header(None)) -> dict[str, Any]:
    token = get_token_from_header(authorization)
    return get_session_user_by_token(token)


def require_admin(authorization: Optional[str] = Header(None)) -> dict[str, Any]:
    user = require_logged_user(authorization)
    role = user.get("role", "")
    if role not in {"superadmin", "subadmin"}:
        raise HTTPException(status_code=403, detail="Permisos insuficientes.")
    return user


def require_superadmin(authorization: Optional[str] = Header(None)) -> dict[str, Any]:
    user = require_logged_user(authorization)
    if user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Solo el superadministrador puede hacer esta acción.")
    return user


def write_admin_log(admin_user_id: str, action: str, target_user_id: Optional[str] = None, details: Optional[str] = None) -> None:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO admin_logs (admin_user_id, action, target_user_id, details, created_at)
    VALUES (?, ?, ?, ?, ?)
    """, (admin_user_id, action, target_user_id, details, iso_now()))
    conn.commit()
    conn.close()


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if UPLOADS_DIR.exists():
    app.mount("/proofs", StaticFiles(directory=str(UPLOADS_DIR)), name="proofs")


@app.get("/", response_model=None)
def root():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse({"message": "Backend ProHeat activo."})


@app.get("/admin", response_model=None)
def admin_page():
    admin_path = STATIC_DIR / "admin.html"
    if admin_path.exists():
        return FileResponse(admin_path)
    return JSONResponse({"message": "Sube admin.html a la carpeta static."})


@app.post("/register")
def register_user(payload: RegisterIn):
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("SELECT 1 FROM users WHERE email = ?", (payload.email.lower(),))
    if cur.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Ese correo ya está registrado.")

    user_id = f"user_{secrets.token_hex(6)}"
    password_hash, password_salt = hash_password(payload.password)
    now_str = iso_now()

    cur.execute("""
    INSERT INTO users (
        user_id, name, email, password_hash, password_salt,
        role, status, membership_start, membership_end, created_at, updated_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        payload.name.strip(),
        payload.email.lower(),
        password_hash,
        password_salt,
        "user",
        "active",
        None,
        None,
        now_str,
        now_str
    ))

    conn.commit()
    conn.close()

    return {
        "message": "Cuenta creada correctamente.",
        "user_id": user_id
    }


@app.post("/login")
def login_user(payload: LoginIn):
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users WHERE email = ?", (payload.email.lower(),))
    user = cur.fetchone()

    if not user:
        conn.close()
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos.")

    if user["role"] not in {"user", "subadmin", "superadmin"}:
        conn.close()
        raise HTTPException(status_code=403, detail="Usuario inválido.")

    if not verify_password(payload.password, user["password_hash"], user["password_salt"]):
        conn.close()
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos.")

    token = create_token()
    created_at = iso_now()
    expires_at = (now_utc() + timedelta(days=30)).isoformat()

    cur.execute("""
    INSERT INTO sessions (token, user_id, created_at, expires_at)
    VALUES (?, ?, ?, ?)
    """, (token, user["user_id"], created_at, expires_at))

    conn.commit()
    conn.close()

    membership_status = normalize_membership_status(user["membership_end"])

    return {
        "message": "Login correcto.",
        "token": token,
        "user_id": user["user_id"],
        "name": user["name"],
        "email": user["email"],
        "role": user["role"],
        "status": membership_status
    }


@app.get("/membership/{user_id}")
def get_membership(user_id: str):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cur.fetchone()
    conn.close()

    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    membership = normalize_membership_status(user["membership_end"])
    if not user["membership_end"]:
        membership = "pending"

    return {
        "user_id": user["user_id"],
        "membership": membership,
        "start_date": user["membership_start"],
        "end_date": user["membership_end"]
    }


@app.post("/upload-proof/{user_id}")
async def upload_proof(user_id: str, file: UploadFile = File(...)):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cur.fetchone()

    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    suffix = Path(file.filename or "proof.bin").suffix or ".bin"
    stored_name = f"{user_id}_{secrets.token_hex(8)}{suffix}"
    save_path = UPLOADS_DIR / stored_name

    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)

    request_id = f"req_{secrets.token_hex(6)}"
    proof_url = f"/proofs/{stored_name}"
    now_str = iso_now()

    cur.execute("""
    INSERT INTO payment_requests (
        request_id, user_id, proof_filename, proof_url, notes, status, created_at, updated_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        request_id,
        user_id,
        file.filename or stored_name,
        proof_url,
        "Comprobante subido desde la web.",
        "pending",
        now_str,
        now_str
    ))

    conn.commit()
    conn.close()

    return {
        "message": "Comprobante enviado correctamente. Quedó pendiente de revisión.",
        "request_id": request_id,
        "proof_url": proof_url
    }


@app.post("/admin/login")
def admin_login(payload: LoginIn):
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users WHERE email = ?", (payload.email.lower(),))
    user = cur.fetchone()

    if not user:
        conn.close()
        raise HTTPException(status_code=401, detail="Credenciales inválidas.")

    if user["role"] not in {"superadmin", "subadmin"}:
        conn.close()
        raise HTTPException(status_code=403, detail="Este usuario no es administrador.")

    if not verify_password(payload.password, user["password_hash"], user["password_salt"]):
        conn.close()
        raise HTTPException(status_code=401, detail="Credenciales inválidas.")

    token = create_token()
    created_at = iso_now()
    expires_at = (now_utc() + timedelta(days=30)).isoformat()

    cur.execute("""
    INSERT INTO sessions (token, user_id, created_at, expires_at)
    VALUES (?, ?, ?, ?)
    """, (token, user["user_id"], created_at, expires_at))

    conn.commit()
    conn.close()

    return {
        "message": "Login admin correcto.",
        "token": token,
        "user_id": user["user_id"],
        "name": user["name"],
        "email": user["email"],
        "role": user["role"]
    }


@app.post("/admin/create-subadmin")
def create_subadmin(payload: AdminCreateSubadminIn, admin=Depends(require_superadmin)):
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("SELECT 1 FROM users WHERE email = ?", (payload.email.lower(),))
    if cur.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Ese correo ya existe.")

    user_id = f"subadmin_{secrets.token_hex(6)}"
    password_hash, password_salt = hash_password(payload.password)
    now_str = iso_now()

    cur.execute("""
    INSERT INTO users (
        user_id, name, email, password_hash, password_salt,
        role, status, membership_start, membership_end, created_at, updated_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        payload.name.strip(),
        payload.email.lower(),
        password_hash,
        password_salt,
        "subadmin",
        "active",
        now_str,
        (now_utc() + timedelta(days=3650)).isoformat(),
        now_str,
        now_str
    ))

    conn.commit()
    conn.close()

    write_admin_log(
        admin_user_id=admin["user_id"],
        action="create_subadmin",
        target_user_id=user_id,
        details=f"Correo: {payload.email.lower()}"
    )

    return {
        "message": "Subadministrador creado correctamente.",
        "user_id": user_id,
        "email": payload.email.lower(),
        "role": "subadmin"
    }


@app.get("/admin/pending-requests")
def admin_pending_requests(admin=Depends(require_admin)):
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
    SELECT
        pr.request_id,
        pr.user_id,
        u.name,
        u.email,
        pr.proof_filename,
        pr.proof_url,
        pr.notes,
        pr.status,
        pr.created_at,
        pr.updated_at
    FROM payment_requests pr
    JOIN users u ON u.user_id = pr.user_id
    ORDER BY pr.created_at DESC
    """)

    items = [dict(row) for row in cur.fetchall()]
    conn.close()
    return {"items": items}


@app.get("/admin/users")
def admin_users(admin=Depends(require_admin)):
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
    SELECT
        user_id,
        name,
        email,
        role,
        status,
        membership_start,
        membership_end,
        created_at
    FROM users
    ORDER BY created_at DESC
    """)

    rows = []
    for row in cur.fetchall():
        item = dict(row)
        item["membership_status"] = normalize_membership_status(item["membership_end"]) if item["role"] == "user" else "active"
        item["start_date"] = item["membership_start"]
        item["end_date"] = item["membership_end"]
        rows.append(item)

    conn.close()
    return {"items": rows}


@app.post("/admin/approve-membership")
def admin_approve_membership(payload: ApproveMembershipIn, admin=Depends(require_admin)):
    if payload.days not in {7, 15, 30}:
        raise HTTPException(status_code=400, detail="Solo se permiten 7, 15 o 30 días.")

    conn = db_connect()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users WHERE user_id = ?", (payload.user_id,))
    user = cur.fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    base_dt = now_utc()
    current_end = parse_dt(user["membership_end"])
    if current_end and current_end > base_dt:
        base_dt = current_end

    new_start = user["membership_start"] or iso_now()
    new_end = (base_dt + timedelta(days=payload.days)).isoformat()
    updated_at = iso_now()

    cur.execute("""
    UPDATE users
    SET membership_start = ?, membership_end = ?, updated_at = ?
    WHERE user_id = ?
    """, (new_start, new_end, updated_at, payload.user_id))

    cur.execute("""
    UPDATE payment_requests
    SET status = 'reviewed', updated_at = ?
    WHERE user_id = ? AND status = 'pending'
    """, (updated_at, payload.user_id))

    conn.commit()
    conn.close()

    write_admin_log(
        admin_user_id=admin["user_id"],
        action="approve_membership",
        target_user_id=payload.user_id,
        details=f"{payload.days} días"
    )

    return {
        "message": "Membresía aprobada correctamente.",
        "user_id": payload.user_id,
        "days": payload.days,
        "end_date": new_end
    }


@app.post("/admin/extend-membership")
def admin_extend_membership(payload: ExtendMembershipIn, admin=Depends(require_admin)):
    if payload.days not in {7, 15, 30}:
        raise HTTPException(status_code=400, detail="Solo se permiten 7, 15 o 30 días.")

    conn = db_connect()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users WHERE user_id = ?", (payload.user_id,))
    user = cur.fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    if user["role"] != "user":
        conn.close()
        raise HTTPException(status_code=400, detail="Solo se puede extender membresía a usuarios normales.")

    base_dt = now_utc()
    current_end = parse_dt(user["membership_end"])
    if current_end and current_end > base_dt:
        base_dt = current_end

    new_start = user["membership_start"] or iso_now()
    new_end = (base_dt + timedelta(days=payload.days)).isoformat()
    updated_at = iso_now()

    cur.execute("""
    UPDATE users
    SET membership_start = ?, membership_end = ?, updated_at = ?
    WHERE user_id = ?
    """, (new_start, new_end, updated_at, payload.user_id))

    conn.commit()
    conn.close()

    write_admin_log(
        admin_user_id=admin["user_id"],
        action="extend_membership",
        target_user_id=payload.user_id,
        details=f"{payload.days} días"
    )

    return {
        "message": "Membresía extendida correctamente.",
        "user_id": payload.user_id,
        "days": payload.days,
        "end_date": new_end
    }


@app.post("/admin/expire-membership")
def admin_expire_membership(payload: ExpireMembershipIn, admin=Depends(require_admin)):
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users WHERE user_id = ?", (payload.user_id,))
    user = cur.fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    if user["role"] != "user":
        conn.close()
        raise HTTPException(status_code=400, detail="Solo se puede vencer membresía a usuarios normales.")

    expired_dt = (now_utc() - timedelta(minutes=1)).isoformat()

    cur.execute("""
    UPDATE users
    SET membership_end = ?, updated_at = ?
    WHERE user_id = ?
    """, (expired_dt, iso_now(), payload.user_id))

    conn.commit()
    conn.close()

    write_admin_log(
        admin_user_id=admin["user_id"],
        action="expire_membership",
        target_user_id=payload.user_id,
        details="Marcada como vencida manualmente"
    )

    return {
        "message": "Membresía marcada como vencida.",
        "user_id": payload.user_id
    }


@app.post("/admin/delete-request")
def admin_delete_request(payload: DeleteRequestIn, admin=Depends(require_admin)):
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("SELECT * FROM payment_requests WHERE request_id = ?", (payload.request_id,))
    req = cur.fetchone()
    if not req:
        conn.close()
        raise HTTPException(status_code=404, detail="Solicitud no encontrada.")

    cur.execute("DELETE FROM payment_requests WHERE request_id = ?", (payload.request_id,))
    conn.commit()
    conn.close()

    write_admin_log(
        admin_user_id=admin["user_id"],
        action="delete_request",
        target_user_id=req["user_id"],
        details=f"request_id={payload.request_id}"
    )

    return {"message": "Solicitud eliminada correctamente."}


@app.post("/admin/delete-user")
def admin_delete_user(payload: DeleteUserIn, admin=Depends(require_admin)):
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users WHERE user_id = ?", (payload.user_id,))
    user = cur.fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    if user["role"] == "superadmin":
        conn.close()
        raise HTTPException(status_code=403, detail="No se puede eliminar al superadministrador por este endpoint.")

    if user["role"] == "subadmin" and admin["role"] != "superadmin":
        conn.close()
        raise HTTPException(status_code=403, detail="Solo el superadministrador puede eliminar subadministradores.")

    cur.execute("DELETE FROM sessions WHERE user_id = ?", (payload.user_id,))
    cur.execute("DELETE FROM payment_requests WHERE user_id = ?", (payload.user_id,))
    cur.execute("DELETE FROM users WHERE user_id = ?", (payload.user_id,))
    conn.commit()
    conn.close()

    write_admin_log(
        admin_user_id=admin["user_id"],
        action="delete_user",
        target_user_id=payload.user_id,
        details=f"role={user['role']}"
    )

    return {"message": "Usuario eliminado correctamente."}


@app.get("/admin/admins")
def list_admins(admin=Depends(require_superadmin)):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
    SELECT user_id, name, email, role, created_at
    FROM users
    WHERE role IN ('superadmin', 'subadmin')
    ORDER BY created_at DESC
    """)
    items = [dict(row) for row in cur.fetchall()]
    conn.close()
    return {"items": items}


def load_latest_json() -> dict[str, Any]:
    latest_path = DATA_DIR / "latest.json"
    if not latest_path.exists():
        return {
            "public": [],
            "general": [],
            "ultra": [],
            "stakes": [],
            "combinadas": [],
            "goles": [],
            "top": [],
            "alta_confianza": []
        }

    try:
        with open(latest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def get_section_items(section: str) -> list[dict[str, Any]]:
    data = load_latest_json()
    items = data.get(section, [])
    return items if isinstance(items, list) else []
=======
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
>>>>>>> 8939051425474de8539e4f8eb18b1c6c0e78b429


@app.get("/api/data/public")
def api_data_public():
<<<<<<< HEAD
    return {"items": get_section_items("public")}
=======
    rows = get_prediction_section("public")
    return {"count": len(rows), "items": rows}
>>>>>>> 8939051425474de8539e4f8eb18b1c6c0e78b429


@app.get("/api/data/general")
def api_data_general():
<<<<<<< HEAD
    return {"items": get_section_items("general")}
=======
    rows = get_prediction_section("general")
    return {"count": len(rows), "items": rows}
>>>>>>> 8939051425474de8539e4f8eb18b1c6c0e78b429


@app.get("/api/data/ultra")
def api_data_ultra():
<<<<<<< HEAD
    return {"items": get_section_items("ultra")}
=======
    rows = get_prediction_section("ultra")
    return {"count": len(rows), "items": rows}
>>>>>>> 8939051425474de8539e4f8eb18b1c6c0e78b429


@app.get("/api/data/stakes")
def api_data_stakes():
<<<<<<< HEAD
    return {"items": get_section_items("stakes")}
=======
    rows = get_prediction_section("stakes")
    return {"count": len(rows), "items": rows}
>>>>>>> 8939051425474de8539e4f8eb18b1c6c0e78b429


@app.get("/api/data/combinadas")
def api_data_combinadas():
<<<<<<< HEAD
    return {"items": get_section_items("combinadas")}
=======
    rows = get_prediction_section("combinadas")
    return {"count": len(rows), "items": rows}
>>>>>>> 8939051425474de8539e4f8eb18b1c6c0e78b429


@app.get("/api/data/goles")
def api_data_goles():
<<<<<<< HEAD
    return {"items": get_section_items("goles")}
=======
    rows = get_prediction_section("goles")
    return {"count": len(rows), "items": rows}
>>>>>>> 8939051425474de8539e4f8eb18b1c6c0e78b429


@app.get("/api/data/top")
def api_data_top():
<<<<<<< HEAD
    return {"items": get_section_items("top")}
=======
    rows = get_prediction_section("top")
    return {"count": len(rows), "items": rows}
>>>>>>> 8939051425474de8539e4f8eb18b1c6c0e78b429


@app.get("/api/data/alta-confianza")
def api_data_alta_confianza():
<<<<<<< HEAD
    return {"items": get_section_items("alta_confianza")}


@app.get("/health")
def health():
    latest_path = DATA_DIR / "latest.json"
    return {
        "status": "ok",
        "app": APP_NAME,
        "db_path": str(DB_PATH),
        "data_dir": str(DATA_DIR),
        "latest_json": str(latest_path),
        "latest_exists": latest_path.exists(),
        "uploads_dir": str(UPLOADS_DIR),
        "static_dir": str(STATIC_DIR)
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend:app", host="0.0.0.0", port=8000, reload=True)
=======
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
>>>>>>> 8939051425474de8539e4f8eb18b1c6c0e78b429
