from __future__ import annotations

import os
import json
import sqlite3
import secrets
import hashlib
import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Any

import requests
from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, EmailStr

from test_excel_reader_daily import process_excel_to_json

# =========================
# CONFIG
# =========================

APP_NAME = "ProHeat Sports Backend"
BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = Path(os.getenv("PROHEAT_DATA_DIR", BASE_DIR / "proheat_data"))
STATIC_DIR = Path(os.getenv("PROHEAT_STATIC_DIR", BASE_DIR / "static"))
UPLOADS_DIR = Path(os.getenv("PROHEAT_UPLOADS_DIR", BASE_DIR / "proof_uploads"))
DB_PATH = Path(os.getenv("PROHEAT_DB_PATH", BASE_DIR / "proheat.db"))
TEMP_UPLOADS_DIR = Path(os.getenv("PROHEAT_TEMP_UPLOADS_DIR", BASE_DIR / "temp_uploads"))

DEFAULT_SUPERADMIN_NAME = os.getenv("DEFAULT_SUPERADMIN_NAME", "ProHeat Master Admin")
DEFAULT_SUPERADMIN_EMAIL = os.getenv("DEFAULT_SUPERADMIN_EMAIL", "admin@proheatsports.com")
DEFAULT_SUPERADMIN_PASSWORD = os.getenv("DEFAULT_SUPERADMIN_PASSWORD", "ProHeatAdmin123!")

PASSWORD_ITERATIONS = 120_000

# PayPal
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "")
PAYPAL_WEBHOOK_ID = os.getenv("PAYPAL_WEBHOOK_ID", "")
PAYPAL_API_BASE = os.getenv("PAYPAL_API_BASE", "https://api-m.paypal.com")
PREMIUM_PRICE_MXN = os.getenv("PREMIUM_PRICE_MXN", "110.00")
PREMIUM_DAYS = int(os.getenv("PREMIUM_DAYS", "30"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
TEMP_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# =========================
# FASTAPI
# =========================

app = FastAPI(title=APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# UTILS
# =========================

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
    conn.row_factory = sqlite3.Row
    return conn

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
    TEMP_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

def row_to_dict(row: Optional[sqlite3.Row]) -> dict[str, Any]:
    return dict(row) if row else {}

# =========================
# DB INIT
# =========================

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
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS paypal_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payment_id TEXT UNIQUE NOT NULL,
        user_id TEXT NOT NULL,
        paypal_order_id TEXT,
        paypal_capture_id TEXT,
        amount TEXT NOT NULL,
        currency TEXT NOT NULL DEFAULT 'MXN',
        status TEXT NOT NULL,
        raw_payload TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )
    """)

    conn.commit()
    conn.close()

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

    conn.commit()
    conn.close()

def boot() -> None:
    init_db()
    create_default_superadmin()

boot()

# =========================
# SCHEMAS
# =========================

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

# =========================
# AUTH HELPERS
# =========================

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

# =========================
# PAYPAL HELPERS
# =========================

def paypal_get_access_token() -> str:
    if not PAYPAL_CLIENT_ID or not PAYPAL_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Faltan credenciales PayPal en variables de entorno.")

    auth = base64.b64encode(f"{PAYPAL_CLIENT_ID}:{PAYPAL_CLIENT_SECRET}".encode()).decode()

    response = requests.post(
        f"{PAYPAL_API_BASE}/v1/oauth2/token",
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "client_credentials"},
        timeout=30,
    )

    if response.status_code not in (200, 201):
        raise HTTPException(status_code=500, detail=f"No se pudo obtener token PayPal: {response.text}")

    data = response.json()
    return data["access_token"]

def activate_membership_for_user(user_id: str, days: int, note: str = "") -> dict[str, Any]:
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cur.fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    base_dt = now_utc()
    current_end = parse_dt(user["membership_end"])
    if current_end and current_end > base_dt:
        base_dt = current_end

    new_start = user["membership_start"] or iso_now()
    new_end = (base_dt + timedelta(days=days)).isoformat()
    updated_at = iso_now()

    cur.execute("""
    UPDATE users
    SET membership_start = ?, membership_end = ?, updated_at = ?
    WHERE user_id = ?
    """, (new_start, new_end, updated_at, user_id))

    conn.commit()
    conn.close()

    return {
        "user_id": user_id,
        "membership_start": new_start,
        "membership_end": new_end,
        "note": note,
    }

def save_paypal_payment(
    user_id: str,
    order_id: str = "",
    capture_id: str = "",
    amount: str = "110.00",
    currency: str = "MXN",
    status: str = "created",
    raw_payload: dict[str, Any] | None = None,
) -> str:
    conn = db_connect()
    cur = conn.cursor()

    payment_id = f"pp_{secrets.token_hex(8)}"
    now_str = iso_now()

    cur.execute("""
    INSERT INTO paypal_payments (
        payment_id, user_id, paypal_order_id, paypal_capture_id,
        amount, currency, status, raw_payload, created_at, updated_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        payment_id,
        user_id,
        order_id,
        capture_id,
        amount,
        currency,
        status,
        json.dumps(raw_payload or {}, ensure_ascii=False),
        now_str,
        now_str,
    ))

    conn.commit()
    conn.close()
    return payment_id

def update_paypal_payment_status(
    order_id: str,
    capture_id: str = "",
    status: str = "completed",
    raw_payload: dict[str, Any] | None = None,
) -> None:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
    UPDATE paypal_payments
    SET paypal_capture_id = COALESCE(?, paypal_capture_id),
        status = ?,
        raw_payload = ?,
        updated_at = ?
    WHERE paypal_order_id = ?
    """, (
        capture_id or None,
        status,
        json.dumps(raw_payload or {}, ensure_ascii=False),
        iso_now(),
        order_id,
    ))
    conn.commit()
    conn.close()

def verify_paypal_webhook(headers: dict[str, str], body: dict[str, Any]) -> bool:
    access_token = paypal_get_access_token()

    verify_payload = {
        "auth_algo": headers.get("paypal-auth-algo", ""),
        "cert_url": headers.get("paypal-cert-url", ""),
        "transmission_id": headers.get("paypal-transmission-id", ""),
        "transmission_sig": headers.get("paypal-transmission-sig", ""),
        "transmission_time": headers.get("paypal-transmission-time", ""),
        "webhook_id": PAYPAL_WEBHOOK_ID,
        "webhook_event": body,
    }

    response = requests.post(
        f"{PAYPAL_API_BASE}/v1/notifications/verify-webhook-signature",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json=verify_payload,
        timeout=30,
    )

    if response.status_code not in (200, 201):
        return False

    data = response.json()
    return data.get("verification_status") == "SUCCESS"

# =========================
# STATIC / FILES
# =========================

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

# =========================
# PUBLIC / USER AUTH
# =========================

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

# =========================
# PAYPAL PUBLIC ENDPOINTS
# =========================

@app.post("/paypal/create-order")
def paypal_create_order(user=Depends(require_logged_user)):
    access_token = paypal_get_access_token()

    payload = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "reference_id": user["user_id"],
                "custom_id": user["user_id"],
                "description": "ProHeat Sports Premium 30 días",
                "amount": {
                    "currency_code": "MXN",
                    "value": PREMIUM_PRICE_MXN
                }
            }
        ],
        "application_context": {
            "brand_name": "ProHeat Sports",
            "user_action": "PAY_NOW",
            "shipping_preference": "NO_SHIPPING"
        }
    }

    response = requests.post(
        f"{PAYPAL_API_BASE}/v2/checkout/orders",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )

    if response.status_code not in (200, 201):
        raise HTTPException(status_code=500, detail=f"Error creando orden PayPal: {response.text}")

    data = response.json()
    order_id = data.get("id", "")

    save_paypal_payment(
        user_id=user["user_id"],
        order_id=order_id,
        amount=PREMIUM_PRICE_MXN,
        currency="MXN",
        status="created",
        raw_payload=data,
    )

    return data

@app.post("/paypal/capture-order/{order_id}")
def paypal_capture_order(order_id: str, user=Depends(require_logged_user)):
    access_token = paypal_get_access_token()

    response = requests.post(
        f"{PAYPAL_API_BASE}/v2/checkout/orders/{order_id}/capture",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )

    if response.status_code not in (200, 201):
        raise HTTPException(status_code=500, detail=f"Error capturando orden PayPal: {response.text}")

    data = response.json()
    status = data.get("status", "")
    capture_id = ""

    purchase_units = data.get("purchase_units", [])
    if purchase_units:
        payments = purchase_units[0].get("payments", {})
        captures = payments.get("captures", [])
        if captures:
            capture_id = captures[0].get("id", "")

    update_paypal_payment_status(
        order_id=order_id,
        capture_id=capture_id,
        status=(status.lower() or "completed"),
        raw_payload=data,
    )

    if status == "COMPLETED":
        membership = activate_membership_for_user(
            user_id=user["user_id"],
            days=PREMIUM_DAYS,
            note=f"PayPal order {order_id}"
        )

        write_admin_log(
            admin_user_id="paypal_auto",
            action="paypal_auto_approve",
            target_user_id=user["user_id"],
            details=f"order_id={order_id} capture_id={capture_id}"
        )

        return {
            "status": "ok",
            "message": "Pago completado y membresía activada automáticamente.",
            "paypal_status": status,
            "order_id": order_id,
            "capture_id": capture_id,
            "membership": membership,
        }

    return {
        "status": "pending",
        "message": "La orden fue capturada pero no quedó completada.",
        "paypal_status": status,
        "order_id": order_id,
        "capture_id": capture_id,
    }

@app.post("/paypal/webhook")
async def paypal_webhook(request: Request):
    body = await request.json()
    headers = {k.lower(): v for k, v in request.headers.items()}

    if not PAYPAL_WEBHOOK_ID:
        raise HTTPException(status_code=500, detail="Falta PAYPAL_WEBHOOK_ID.")

    is_valid = verify_paypal_webhook(headers, body)
    if not is_valid:
        raise HTTPException(status_code=400, detail="Webhook PayPal no válido.")

    event_type = body.get("event_type", "")

    if event_type == "PAYMENT.CAPTURE.COMPLETED":
        resource = body.get("resource", {})
        capture_id = resource.get("id", "")
        amount = resource.get("amount", {}).get("value", PREMIUM_PRICE_MXN)
        currency = resource.get("amount", {}).get("currency_code", "MXN")
        supplementary = resource.get("supplementary_data", {})
        related_ids = supplementary.get("related_ids", {})
        order_id = related_ids.get("order_id", "")

        if order_id:
            conn = db_connect()
            cur = conn.cursor()
            cur.execute("SELECT * FROM paypal_payments WHERE paypal_order_id = ?", (order_id,))
            payment_row = cur.fetchone()
            conn.close()

            if payment_row and payment_row["status"] != "completed":
                update_paypal_payment_status(
                    order_id=order_id,
                    capture_id=capture_id,
                    status="completed",
                    raw_payload=body,
                )

                activate_membership_for_user(
                    user_id=payment_row["user_id"],
                    days=PREMIUM_DAYS,
                    note=f"Webhook PayPal order {order_id}"
                )

                write_admin_log(
                    admin_user_id="paypal_webhook",
                    action="paypal_webhook_auto_approve",
                    target_user_id=payment_row["user_id"],
                    details=f"order_id={order_id} capture_id={capture_id} amount={amount} {currency}"
                )

    return {"status": "ok"}

# =========================
# ADMIN AUTH / DATA
# =========================

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
    cur.execute("DELETE FROM paypal_payments WHERE user_id = ?", (payload.user_id,))
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

# =========================
# ADMIN EXCEL UPLOAD
# =========================

@app.post("/admin/upload-excel")
async def admin_upload_excel(
    file: UploadFile = File(...),
    admin=Depends(require_admin)
):
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()

    if suffix not in {".xlsx", ".xlsm", ".xls"}:
        raise HTTPException(status_code=400, detail="Solo se permiten archivos Excel (.xlsx, .xlsm, .xls).")

    stored_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{Path(filename).name}"
    temp_file_path = TEMP_UPLOADS_DIR / stored_name

    try:
        content = await file.read()
        with open(temp_file_path, "wb") as f:
            f.write(content)

        result = process_excel_to_json(temp_file_path, DATA_DIR)

        write_admin_log(
            admin_user_id=admin["user_id"],
            action="upload_excel",
            details=f"Archivo: {stored_name} | Fecha: {result.get('date')}"
        )

        return {
            "status": "ok",
            "message": "Excel procesado correctamente.",
            "source_file": result.get("source_file"),
            "date": result.get("date"),
            "generated_at": result.get("generated_at"),
            "counts": result.get("counts", {}),
            "latest_path": result.get("latest_path"),
            "daily_path": result.get("daily_path"),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error procesando Excel: {e}")

# =========================
# DATA ENDPOINTS FOR INDEX
# =========================

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
            "alta_confianza": [],
            "inferno": []
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

@app.get("/api/data/public")
def api_data_public():
    return {"items": get_section_items("public")}

@app.get("/api/data/general")
def api_data_general():
    return {"items": get_section_items("general")}

@app.get("/api/data/ultra")
def api_data_ultra():
    return {"items": get_section_items("ultra")}

@app.get("/api/data/stakes")
def api_data_stakes():
    return {"items": get_section_items("stakes")}

@app.get("/api/data/combinadas")
def api_data_combinadas():
    return {"items": get_section_items("combinadas")}

@app.get("/api/data/goles")
def api_data_goles():
    return {"items": get_section_items("goles")}

@app.get("/api/data/top")
def api_data_top():
    return {"items": get_section_items("top")}

@app.get("/api/data/alta-confianza")
def api_data_alta_confianza():
    return {"items": get_section_items("alta_confianza")}

@app.get("/api/data/inferno")
def api_data_inferno():
    return {"items": get_section_items("inferno")}

# =========================
# HEALTH / DEBUG
# =========================

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
        "temp_uploads_dir": str(TEMP_UPLOADS_DIR),
        "static_dir": str(STATIC_DIR),
        "paypal_configured": bool(PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET),
        "paypal_client_id_present": bool(PAYPAL_CLIENT_ID),
        "paypal_client_secret_present": bool(PAYPAL_CLIENT_SECRET),
        "paypal_api_base_present": bool(PAYPAL_API_BASE),
        "paypal_client_id_len": len(PAYPAL_CLIENT_ID or ""),
        "paypal_client_secret_len": len(PAYPAL_CLIENT_SECRET or ""),
    }

# =========================
# RUN LOCAL
# =========================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend:app", host="0.0.0.0", port=8000, reload=True)