from __future__ import annotations

import os
import json
import sqlite3
import secrets
import hashlib
import base64
import shutil
import re
import unicodedata
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Any

import requests
from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Header, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
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
VIDEO_UPLOADS_DIR = Path(os.getenv("PROHEAT_VIDEO_UPLOADS_DIR", BASE_DIR / "video_uploads"))

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

# Telegram Bot Premium
BOT_PREMIUM_PRICE_MXN = os.getenv("BOT_PREMIUM_PRICE_MXN", "160.00")
BOT_PREMIUM_DAYS = int(os.getenv("BOT_PREMIUM_DAYS", "30"))
BOT_PAYMENT_CLABE = os.getenv("BOT_PAYMENT_CLABE", "CONFIGURA_BOT_PAYMENT_CLABE_EN_RAILWAY")
BOT_PAYMENT_BANK = os.getenv("BOT_PAYMENT_BANK", "Banco por configurar")
BOT_PAYMENT_ACCOUNT_NAME = os.getenv("BOT_PAYMENT_ACCOUNT_NAME", "ProHeat Sports")
BOT_RETURN_URL_BASE = os.getenv("BOT_RETURN_URL_BASE", "").strip().rstrip("/")

# Telegram bot notifications
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", os.getenv("TELEGRAM_TOKEN", "")).strip()

# API-Football / API-Sports
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", os.getenv("FOOTBALL_API_KEY", os.getenv("API_SPORTS_KEY", ""))).strip()
API_FOOTBALL_BASE = os.getenv("API_FOOTBALL_BASE", "https://v3.football.api-sports.io").strip().rstrip("/")

DATA_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
TEMP_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

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
    VIDEO_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS telegram_memberships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id TEXT UNIQUE NOT NULL,
        status TEXT NOT NULL DEFAULT 'inactive',
        start_date TEXT,
        end_date TEXT,
        source TEXT,
        notes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS telegram_payment_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT UNIQUE NOT NULL,
        telegram_id TEXT NOT NULL,
        proof_filename TEXT,
        proof_url TEXT,
        notes TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS telegram_paypal_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payment_id TEXT UNIQUE NOT NULL,
        telegram_id TEXT NOT NULL,
        paypal_order_id TEXT UNIQUE,
        paypal_capture_id TEXT,
        amount TEXT NOT NULL,
        currency TEXT NOT NULL DEFAULT 'MXN',
        status TEXT NOT NULL,
        raw_payload TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS video_picks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        video_filename TEXT NOT NULL,
        video_url TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_by TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS free_picks_videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        video_filename TEXT NOT NULL,
        video_url TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_by TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
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

class TelegramMembershipIn(BaseModel):
    telegram_id: str
    days: int = 30
    notes: Optional[str] = None

class TelegramExpireIn(BaseModel):
    telegram_id: str

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

def notify_telegram_user(telegram_id: str, text: str) -> bool:
    """Envía notificación al usuario del bot sin romper el flujo si Telegram falla."""
    if not TELEGRAM_BOT_TOKEN:
        return False

    clean_id = str(telegram_id).strip()
    if not clean_id:
        return False

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": clean_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        if response.status_code not in (200, 201):
            print(f"Telegram notify failed for {clean_id}: {response.text}")
            return False
        return True
    except Exception as e:
        print(f"Telegram notify exception for {clean_id}: {e}")
        return False

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

def normalize_telegram_membership_status(end_date: Optional[str], status: str = "inactive") -> str:
    if status != "active":
        return status or "inactive"
    dt = parse_dt(end_date)
    if not dt:
        return "inactive"
    return "active" if dt > now_utc() else "expired"

def activate_telegram_membership(
    telegram_id: str,
    days: int = PREMIUM_DAYS,
    source: str = "admin",
    notes: str = ""
) -> dict[str, Any]:
    clean_id = str(telegram_id).strip()
    if not clean_id:
        raise HTTPException(status_code=400, detail="telegram_id requerido.")
    if days <= 0:
        raise HTTPException(status_code=400, detail="days debe ser mayor a 0.")

    conn = db_connect()
    cur = conn.cursor()

    cur.execute("SELECT * FROM telegram_memberships WHERE telegram_id = ?", (clean_id,))
    row = cur.fetchone()

    base_dt = now_utc()
    if row:
        current_end = parse_dt(row["end_date"])
        if current_end and current_end > base_dt:
            base_dt = current_end

    start_date = row["start_date"] if row and row["start_date"] else iso_now()
    end_date = (base_dt + timedelta(days=days)).isoformat()
    now_str = iso_now()

    if row:
        cur.execute("""
        UPDATE telegram_memberships
        SET status = 'active',
            start_date = ?,
            end_date = ?,
            source = ?,
            notes = ?,
            updated_at = ?
        WHERE telegram_id = ?
        """, (start_date, end_date, source, notes, now_str, clean_id))
    else:
        cur.execute("""
        INSERT INTO telegram_memberships (
            telegram_id, status, start_date, end_date, source, notes, created_at, updated_at
        )
        VALUES (?, 'active', ?, ?, ?, ?, ?, ?)
        """, (clean_id, start_date, end_date, source, notes, now_str, now_str))

    conn.commit()
    conn.close()

    return {
        "telegram_id": clean_id,
        "status": "active",
        "start_date": start_date,
        "end_date": end_date,
        "days": days,
        "source": source,
        "notes": notes,
    }

def expire_telegram_membership(telegram_id: str, source: str = "admin") -> dict[str, Any]:
    clean_id = str(telegram_id).strip()
    if not clean_id:
        raise HTTPException(status_code=400, detail="telegram_id requerido.")

    now_str = iso_now()
    expired_dt = (now_utc() - timedelta(minutes=1)).isoformat()

    conn = db_connect()
    cur = conn.cursor()

    cur.execute("SELECT * FROM telegram_memberships WHERE telegram_id = ?", (clean_id,))
    row = cur.fetchone()

    if row:
        cur.execute("""
        UPDATE telegram_memberships
        SET status = 'expired',
            end_date = ?,
            source = ?,
            updated_at = ?
        WHERE telegram_id = ?
        """, (expired_dt, source, now_str, clean_id))
    else:
        cur.execute("""
        INSERT INTO telegram_memberships (
            telegram_id, status, start_date, end_date, source, notes, created_at, updated_at
        )
        VALUES (?, 'expired', ?, ?, ?, ?, ?, ?)
        """, (clean_id, None, expired_dt, source, "Expirada manualmente", now_str, now_str))

    conn.commit()
    conn.close()

    return {
        "telegram_id": clean_id,
        "status": "expired",
        "end_date": expired_dt,
        "source": source,
    }

def get_telegram_membership_record(telegram_id: str) -> dict[str, Any]:
    clean_id = str(telegram_id).strip()
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM telegram_memberships WHERE telegram_id = ?", (clean_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return {
            "telegram_id": clean_id,
            "status": "inactive",
            "membership": "inactive",
            "start_date": None,
            "end_date": None,
        }

    item = dict(row)
    membership = normalize_telegram_membership_status(item.get("end_date"), item.get("status", "inactive"))
    return {
        "telegram_id": item["telegram_id"],
        "status": membership,
        "membership": membership,
        "start_date": item.get("start_date"),
        "end_date": item.get("end_date"),
        "source": item.get("source"),
        "notes": item.get("notes"),
    }


def get_public_base_url(request: Request) -> str:
    if BOT_RETURN_URL_BASE:
        return BOT_RETURN_URL_BASE
    return str(request.base_url).rstrip("/")

def save_telegram_paypal_payment(
    telegram_id: str,
    order_id: str = "",
    capture_id: str = "",
    amount: str = "160.00",
    currency: str = "MXN",
    status: str = "created",
    raw_payload: dict[str, Any] | None = None,
) -> str:
    conn = db_connect()
    cur = conn.cursor()
    payment_id = f"tpp_{secrets.token_hex(8)}"
    now_str = iso_now()
    cur.execute("""
    INSERT INTO telegram_paypal_payments (
        payment_id, telegram_id, paypal_order_id, paypal_capture_id,
        amount, currency, status, raw_payload, created_at, updated_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        payment_id, str(telegram_id).strip(), order_id, capture_id,
        amount, currency, status, json.dumps(raw_payload or {}, ensure_ascii=False), now_str, now_str
    ))
    conn.commit()
    conn.close()
    return payment_id

def update_telegram_paypal_payment_status(
    order_id: str,
    capture_id: str = "",
    status: str = "completed",
    raw_payload: dict[str, Any] | None = None,
) -> Optional[str]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT telegram_id FROM telegram_paypal_payments WHERE paypal_order_id = ?", (order_id,))
    row = cur.fetchone()
    telegram_id = row["telegram_id"] if row else None
    cur.execute("""
    UPDATE telegram_paypal_payments
    SET paypal_capture_id = COALESCE(?, paypal_capture_id),
        status = ?, raw_payload = ?, updated_at = ?
    WHERE paypal_order_id = ?
    """, (capture_id or None, status, json.dumps(raw_payload or {}, ensure_ascii=False), iso_now(), order_id))
    conn.commit()
    conn.close()
    return telegram_id

def build_bot_payment_page_html(telegram_id: str, base_url: str) -> str:
    safe_tid = str(telegram_id).strip()
    return """<!DOCTYPE html>
<html lang='es'>
<head>
<meta charset='UTF-8' />
<meta name='viewport' content='width=device-width, initial-scale=1.0' />
<title>ProHeat Sports Bot Premium</title>
<style>
body { margin:0; font-family:Arial,Helvetica,sans-serif; background:#000; color:#fff; }
.wrap { max-width:860px; margin:0 auto; padding:28px 18px; }
.card { background:rgba(255,255,255,.04); border:1px solid rgba(255,140,0,.25); border-radius:22px; padding:22px; margin:16px 0; }
h1,h2 { color:orange; margin-top:0; }
.price { font-size:34px; font-weight:900; color:orange; }
.muted { color:#cfcfcf; line-height:1.5; }
.field { background:#111; border:1px solid rgba(255,255,255,.08); border-radius:14px; padding:12px; margin:8px 0; word-break:break-word; }
button { background:orange; color:#000; border:0; border-radius:999px; padding:12px 18px; font-weight:800; cursor:pointer; }
input { width:100%; padding:12px; border-radius:12px; border:1px solid rgba(255,140,0,.25); background:#111; color:#fff; margin:8px 0; }
.msg { margin-top:12px; color:#ffbf66; white-space:pre-wrap; }
</style>
<script src='https://www.paypal.com/sdk/js?client-id=""" + PAYPAL_CLIENT_ID + """&currency=MXN'></script>
</head>
<body>
<div class='wrap'>
<div class='card'><h1>🔥 ProHeat Sports Bot Premium</h1><div class='muted'>Telegram ID: <strong>""" + safe_tid + """</strong></div><div class='price'>$""" + BOT_PREMIUM_PRICE_MXN + """ MXN</div><div class='muted'>Acceso premium por """ + str(BOT_PREMIUM_DAYS) + """ días.</div></div>
<div class='card'><h2>💳 Pagar con PayPal</h2><div id='paypal-button-container'></div><div id='paypalMsg' class='msg'></div></div>
<div class='card'><h2>🏦 Transferencia bancaria</h2><div class='field'><strong>Banco:</strong><br>""" + BOT_PAYMENT_BANK + """</div><div class='field'><strong>Nombre:</strong><br>""" + BOT_PAYMENT_ACCOUNT_NAME + """</div><div class='field'><strong>CLABE:</strong><br>""" + BOT_PAYMENT_CLABE + """</div><div class='field'><strong>Monto:</strong><br>$""" + BOT_PREMIUM_PRICE_MXN + """ MXN</div><p class='muted'>Después de transferir, sube tu comprobante aquí. Un administrador lo validará.</p><form id='proofForm'><input type='file' id='proofFile' accept='image/*,.pdf' required /><button type='submit'>Subir comprobante</button></form><div id='proofMsg' class='msg'></div></div>
</div>
<script>
const telegramId = '""" + safe_tid + """';
const baseUrl = '""" + base_url + """';
if (window.paypal) {
  paypal.Buttons({
    createOrder: async function() {
      const res = await fetch(baseUrl + '/bot/paypal/create-order/' + encodeURIComponent(telegramId), { method: 'POST' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Error creando orden PayPal');
      return data.id;
    },
    onApprove: async function(data) {
      document.getElementById('paypalMsg').textContent = 'Confirmando pago...';
      const res = await fetch(baseUrl + '/bot/paypal/capture-order/' + encodeURIComponent(data.orderID) + '?telegram_id=' + encodeURIComponent(telegramId), { method: 'POST' });
      const payload = await res.json();
      document.getElementById('paypalMsg').textContent = res.ok ? '✅ Pago completado. Tu acceso quedó activado. Regresa al bot y usa /start.' : (payload.detail || 'No se pudo confirmar el pago.');
    },
    onError: function(err) { document.getElementById('paypalMsg').textContent = 'Error PayPal: ' + err; }
  }).render('#paypal-button-container');
} else { document.getElementById('paypalMsg').textContent = 'PayPal no está configurado o no pudo cargar.'; }
document.getElementById('proofForm').addEventListener('submit', async function(e) {
  e.preventDefault();
  const file = document.getElementById('proofFile').files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  document.getElementById('proofMsg').textContent = 'Subiendo comprobante...';
  const res = await fetch(baseUrl + '/bot/upload-proof/' + encodeURIComponent(telegramId), { method: 'POST', body: fd });
  const data = await res.json();
  document.getElementById('proofMsg').textContent = res.ok ? '✅ Comprobante enviado. Queda pendiente de revisión.' : (data.detail || 'Error subiendo comprobante.');
});
</script>
</body></html>"""

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

if VIDEO_UPLOADS_DIR.exists():
    app.mount("/videos", StaticFiles(directory=str(VIDEO_UPLOADS_DIR)), name="videos")

@app.get("/", response_model=None)
def root():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse({"message": "Backend ProHeat activo."})

@app.get("/premium", response_model=None)
def premium_page():
    premium_path = STATIC_DIR / "premium.html"
    if premium_path.exists():
        return FileResponse(premium_path)
    return JSONResponse({"message": "Sube premium.html a la carpeta static."})

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
# TELEGRAM BOT MEMBERSHIPS
# =========================

@app.get("/bot/membership/{telegram_id}")
def bot_get_membership(telegram_id: str):
    return get_telegram_membership_record(telegram_id)

@app.post("/admin/bot/activate-membership")
def admin_activate_bot_membership(payload: TelegramMembershipIn, admin=Depends(require_admin)):
    if payload.days not in {7, 15, 30, 60, 90}:
        raise HTTPException(status_code=400, detail="Solo se permiten 7, 15, 30, 60 o 90 días.")

    membership = activate_telegram_membership(
        telegram_id=payload.telegram_id,
        days=payload.days,
        source=f"admin:{admin['user_id']}",
        notes=payload.notes or "Activación manual desde admin/backend"
    )

    write_admin_log(
        admin_user_id=admin["user_id"],
        action="activate_telegram_membership",
        target_user_id=payload.telegram_id,
        details=f"{payload.days} días"
    )

    notified = notify_telegram_user(
        payload.telegram_id,
        (
            "✅ <b>ProHeat Sports Premium activado</b>\n\n"
            f"Tu acceso al bot fue activado por {payload.days} días.\n"
            f"Vigencia hasta: {membership.get('end_date', 'N/A')}\n\n"
            "Escribe /start para entrar al menú premium."
        )
    )

    return {
        "status": "ok",
        "message": "Membresía Telegram activada correctamente.",
        "membership": membership,
        "telegram_notified": notified,
    }

@app.post("/admin/bot/expire-membership")
def admin_expire_bot_membership(payload: TelegramExpireIn, admin=Depends(require_admin)):
    membership = expire_telegram_membership(
        telegram_id=payload.telegram_id,
        source=f"admin:{admin['user_id']}"
    )

    write_admin_log(
        admin_user_id=admin["user_id"],
        action="expire_telegram_membership",
        target_user_id=payload.telegram_id,
        details="Expirada manualmente"
    )

    notified = notify_telegram_user(
        payload.telegram_id,
        (
            "🔒 <b>Acceso ProHeat Sports vencido</b>\n\n"
            "Tu membresía del bot fue marcada como vencida por administración.\n"
            "Si deseas renovar, abre el enlace de pago desde el bot o envía tu comprobante."
        )
    )

    return {
        "status": "ok",
        "message": "Membresía Telegram expirada correctamente.",
        "membership": membership,
        "telegram_notified": notified,
    }

@app.get("/admin/bot/memberships")
def admin_list_bot_memberships(admin=Depends(require_admin)):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
    SELECT telegram_id, status, start_date, end_date, source, notes, created_at, updated_at
    FROM telegram_memberships
    ORDER BY datetime(updated_at) DESC
    """)
    rows = []
    for row in cur.fetchall():
        item = dict(row)
        item["membership_status"] = normalize_telegram_membership_status(item.get("end_date"), item.get("status", "inactive"))
        rows.append(item)
    conn.close()
    return {"items": rows}


# =========================
# TELEGRAM BOT PAYMENTS
# =========================

@app.get("/bot/pay", response_class=HTMLResponse)
def bot_payment_page(request: Request, telegram_id: str):
    clean_id = str(telegram_id).strip()
    if not clean_id:
        raise HTTPException(status_code=400, detail="telegram_id requerido.")
    base_url = get_public_base_url(request)
    return HTMLResponse(build_bot_payment_page_html(clean_id, base_url))

@app.post("/bot/paypal/create-order/{telegram_id}")
def bot_paypal_create_order(telegram_id: str, request: Request):
    clean_id = str(telegram_id).strip()
    if not clean_id:
        raise HTTPException(status_code=400, detail="telegram_id requerido.")
    access_token = paypal_get_access_token()
    base_url = get_public_base_url(request)
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": f"telegram:{clean_id}",
            "custom_id": f"telegram:{clean_id}",
            "description": f"ProHeat Sports Bot Premium {BOT_PREMIUM_DAYS} días",
            "amount": {"currency_code": "MXN", "value": BOT_PREMIUM_PRICE_MXN}
        }],
        "application_context": {
            "brand_name": "ProHeat Sports",
            "user_action": "PAY_NOW",
            "shipping_preference": "NO_SHIPPING",
            "return_url": f"{base_url}/bot/pay/success?telegram_id={clean_id}",
            "cancel_url": f"{base_url}/bot/pay?telegram_id={clean_id}"
        }
    }
    response = requests.post(
        f"{PAYPAL_API_BASE}/v2/checkout/orders",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    if response.status_code not in (200, 201):
        raise HTTPException(status_code=500, detail=f"Error creando orden PayPal Bot: {response.text}")
    data = response.json()
    order_id = data.get("id", "")
    save_telegram_paypal_payment(clean_id, order_id, amount=BOT_PREMIUM_PRICE_MXN, currency="MXN", status="created", raw_payload=data)
    return data

@app.post("/bot/paypal/capture-order/{order_id}")
def bot_paypal_capture_order(order_id: str, telegram_id: str):
    clean_id = str(telegram_id).strip()
    if not clean_id:
        raise HTTPException(status_code=400, detail="telegram_id requerido.")
    access_token = paypal_get_access_token()
    response = requests.post(
        f"{PAYPAL_API_BASE}/v2/checkout/orders/{order_id}/capture",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        timeout=30,
    )
    if response.status_code not in (200, 201):
        raise HTTPException(status_code=500, detail=f"Error capturando orden PayPal Bot: {response.text}")
    data = response.json()
    status = data.get("status", "")
    capture_id = ""
    purchase_units = data.get("purchase_units", [])
    if purchase_units:
        captures = purchase_units[0].get("payments", {}).get("captures", [])
        if captures:
            capture_id = captures[0].get("id", "")
    stored_telegram_id = update_telegram_paypal_payment_status(order_id, capture_id, status=(status.lower() or "completed"), raw_payload=data)
    if stored_telegram_id and stored_telegram_id != clean_id:
        raise HTTPException(status_code=400, detail="La orden no corresponde a este Telegram ID.")
    if status == "COMPLETED":
        membership = activate_telegram_membership(clean_id, BOT_PREMIUM_DAYS, "paypal_bot", f"PayPal bot order {order_id} capture {capture_id}")
        write_admin_log("paypal_bot_auto", "paypal_bot_auto_approve", clean_id, f"order_id={order_id} capture_id={capture_id} amount={BOT_PREMIUM_PRICE_MXN} MXN")
        notified = notify_telegram_user(
            clean_id,
            (
                "✅ <b>Pago recibido</b>\n\n"
                f"Tu acceso ProHeat Sports Bot Premium quedó activado por {BOT_PREMIUM_DAYS} días.\n"
                f"Vigencia hasta: {membership.get('end_date', 'N/A')}\n\n"
                "Escribe /start para entrar al menú premium."
            )
        )
        return {"status": "ok", "message": "Pago completado y membresía Telegram activada automáticamente.", "paypal_status": status, "order_id": order_id, "capture_id": capture_id, "membership": membership, "telegram_notified": notified}
    return {"status": "pending", "message": "La orden fue capturada pero no quedó completada.", "paypal_status": status, "order_id": order_id, "capture_id": capture_id}

@app.get("/bot/pay/success", response_class=HTMLResponse)
def bot_pay_success(telegram_id: str):
    return HTMLResponse(f"<html><body style='background:#000;color:#fff;font-family:Arial;padding:30px;'><h1 style='color:orange;'>✅ Pago recibido</h1><p>Telegram ID: <strong>{telegram_id}</strong></p><p>Regresa al bot de ProHeat Sports y escribe <strong>/start</strong>.</p></body></html>")

@app.post("/bot/upload-proof/{telegram_id}")
async def bot_upload_proof(telegram_id: str, file: UploadFile = File(...)):
    clean_id = str(telegram_id).strip()
    if not clean_id:
        raise HTTPException(status_code=400, detail="telegram_id requerido.")
    suffix = Path(file.filename or "proof.bin").suffix or ".bin"
    stored_name = f"telegram_{clean_id}_{secrets.token_hex(8)}{suffix}"
    save_path = UPLOADS_DIR / stored_name
    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)
    request_id = f"treq_{secrets.token_hex(6)}"
    proof_url = f"/proofs/{stored_name}"
    now_str = iso_now()
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO telegram_payment_requests (request_id, telegram_id, proof_filename, proof_url, notes, status, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (request_id, clean_id, file.filename or stored_name, proof_url, f"Comprobante Telegram Bot por ${BOT_PREMIUM_PRICE_MXN} MXN", "pending", now_str, now_str))
    conn.commit()
    conn.close()
    return {"message": "Comprobante del bot enviado correctamente. Quedó pendiente de revisión.", "request_id": request_id, "telegram_id": clean_id, "proof_url": proof_url}

@app.get("/admin/bot/payment-requests")
def admin_bot_payment_requests(admin=Depends(require_admin)):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
    SELECT request_id, telegram_id, proof_filename, proof_url, notes, status, created_at, updated_at
    FROM telegram_payment_requests
    ORDER BY datetime(created_at) DESC
    """)
    items = [dict(row) for row in cur.fetchall()]
    conn.close()
    return {"items": items}

@app.post("/admin/bot/approve-payment-request/{request_id}")
def admin_bot_approve_payment_request(request_id: str, days: int = BOT_PREMIUM_DAYS, admin=Depends(require_admin)):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM telegram_payment_requests WHERE request_id = ?", (request_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Solicitud Telegram no encontrada.")
    now_str = iso_now()
    cur.execute("UPDATE telegram_payment_requests SET status = 'reviewed', updated_at = ? WHERE request_id = ?", (now_str, request_id))
    conn.commit()
    conn.close()
    membership = activate_telegram_membership(row["telegram_id"], days, f"admin_payment:{admin['user_id']}", f"Aprobación manual de comprobante {request_id}")
    write_admin_log(admin["user_id"], "approve_telegram_payment_request", row["telegram_id"], f"request_id={request_id} days={days}")
    notified = notify_telegram_user(
        row["telegram_id"],
        (
            "✅ <b>Comprobante aprobado</b>\n\n"
            f"Tu acceso ProHeat Sports Bot Premium fue activado por {days} días.\n"
            f"Vigencia hasta: {membership.get('end_date', 'N/A')}\n\n"
            "Escribe /start para entrar al menú premium."
        )
    )
    return {"status": "ok", "message": "Comprobante aprobado y acceso Telegram activado.", "membership": membership, "telegram_notified": notified}

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
            else:
                conn = db_connect()
                cur = conn.cursor()
                cur.execute("SELECT * FROM telegram_paypal_payments WHERE paypal_order_id = ?", (order_id,))
                telegram_payment_row = cur.fetchone()
                conn.close()

                if telegram_payment_row and telegram_payment_row["status"] != "completed":
                    update_telegram_paypal_payment_status(
                        order_id=order_id,
                        capture_id=capture_id,
                        status="completed",
                        raw_payload=body,
                    )
                    activate_telegram_membership(
                        telegram_id=telegram_payment_row["telegram_id"],
                        days=BOT_PREMIUM_DAYS,
                        source="paypal_bot_webhook",
                        notes=f"Webhook PayPal Bot order {order_id}"
                    )
                    write_admin_log(
                        admin_user_id="paypal_bot_webhook",
                        action="paypal_bot_webhook_auto_approve",
                        target_user_id=telegram_payment_row["telegram_id"],
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
# ADMIN VIDEO PICKS
# =========================

@app.post("/admin/upload-videopick")
async def admin_upload_videopick(
    title: str = Form(...),
    description: str = Form(...),
    video: UploadFile = File(...),
    admin=Depends(require_admin)
):
    filename = video.filename or ""
    suffix = Path(filename).suffix.lower()

    if suffix not in {".mp4", ".mov", ".webm", ".m4v"}:
        raise HTTPException(status_code=400, detail="Solo se permiten videos .mp4, .mov, .webm o .m4v.")

    safe_name = Path(filename).name
    stored_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}_{safe_name}"
    save_path = VIDEO_UPLOADS_DIR / stored_name

    try:
        content = await video.read()
        with open(save_path, "wb") as f:
            f.write(content)

        video_id = f"vp_{secrets.token_hex(6)}"
        video_url = f"/videos/{stored_name}"
        now_str = iso_now()

        conn = db_connect()
        cur = conn.cursor()
        cur.execute("UPDATE video_picks SET is_active = 0, updated_at = ? WHERE is_active = 1", (now_str,))
        cur.execute("""
        INSERT INTO video_picks (
            video_id, title, description, video_filename, video_url,
            is_active, created_by, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            video_id,
            title.strip(),
            description.strip(),
            safe_name,
            video_url,
            1,
            admin["user_id"],
            now_str,
            now_str
        ))
        conn.commit()
        conn.close()

        write_admin_log(
            admin_user_id=admin["user_id"],
            action="upload_videopick",
            details=f"video_id={video_id} file={stored_name}"
        )

        return {
            "status": "ok",
            "message": "VideoPick subido correctamente.",
            "item": {
                "video_id": video_id,
                "title": title.strip(),
                "description": description.strip(),
                "video_url": video_url,
                "video_filename": safe_name,
                "is_active": True,
                "created_at": now_str
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error subiendo VideoPick: {e}")

@app.get("/admin/video-picks")
def admin_list_video_picks(admin=Depends(require_admin)):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
    SELECT video_id, title, description, video_filename, video_url, is_active, created_by, created_at, updated_at
    FROM video_picks
    ORDER BY datetime(created_at) DESC
    """)
    items = []
    for row in cur.fetchall():
        item = dict(row)
        item["is_active"] = bool(item["is_active"])
        items.append(item)
    conn.close()
    return {"items": items}

@app.post("/admin/video-picks/{video_id}/activate")
def admin_activate_video_pick(video_id: str, admin=Depends(require_admin)):
    now_str = iso_now()
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM video_picks WHERE video_id = ?", (video_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="VideoPick no encontrado.")

    cur.execute("UPDATE video_picks SET is_active = 0, updated_at = ? WHERE is_active = 1", (now_str,))
    cur.execute("UPDATE video_picks SET is_active = 1, updated_at = ? WHERE video_id = ?", (now_str, video_id))
    conn.commit()
    conn.close()

    write_admin_log(
        admin_user_id=admin["user_id"],
        action="activate_videopick",
        details=f"video_id={video_id}"
    )

    return {"status": "ok", "message": "VideoPick activado correctamente.", "video_id": video_id}

@app.delete("/admin/video-picks/{video_id}")
def admin_delete_video_pick(video_id: str, admin=Depends(require_admin)):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM video_picks WHERE video_id = ?", (video_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="VideoPick no encontrado.")

    file_path = VIDEO_UPLOADS_DIR / Path(row["video_url"]).name
    cur.execute("DELETE FROM video_picks WHERE video_id = ?", (video_id,))
    conn.commit()
    conn.close()

    if file_path.exists():
        try:
            file_path.unlink()
        except Exception:
            pass

    write_admin_log(
        admin_user_id=admin["user_id"],
        action="delete_videopick",
        details=f"video_id={video_id}"
    )

    return {"status": "ok", "message": "VideoPick eliminado correctamente.", "video_id": video_id}

# =========================
# ADMIN FREE PICKS SIDE VIDEO
# =========================

@app.post("/admin/upload-free-picks-video")
async def admin_upload_free_picks_video(
    title: str = Form(...),
    video: UploadFile = File(...),
    admin=Depends(require_admin)
):
    filename = video.filename or ""
    suffix = Path(filename).suffix.lower()

    if suffix not in {".mp4", ".mov", ".webm", ".m4v"}:
        raise HTTPException(status_code=400, detail="Solo videos .mp4, .mov, .webm o .m4v.")

    safe_name = Path(filename).name
    stored_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}_{safe_name}"
    save_path = VIDEO_UPLOADS_DIR / stored_name

    try:
        content = await video.read()
        with open(save_path, "wb") as f:
            f.write(content)

        video_id = f"fpv_{secrets.token_hex(6)}"
        video_url = f"/videos/{stored_name}"
        now_str = iso_now()

        conn = db_connect()
        cur = conn.cursor()
        cur.execute("UPDATE free_picks_videos SET is_active = 0, updated_at = ? WHERE is_active = 1", (now_str,))
        cur.execute("""
        INSERT INTO free_picks_videos (
            video_id, title, video_filename, video_url,
            is_active, created_by, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            video_id,
            title.strip(),
            safe_name,
            video_url,
            1,
            admin["user_id"],
            now_str,
            now_str
        ))
        conn.commit()
        conn.close()

        write_admin_log(
            admin_user_id=admin["user_id"],
            action="upload_free_picks_video",
            details=f"video_id={video_id} file={stored_name}"
        )

        return {
            "status": "ok",
            "message": "Video lateral de Picks Gratuitas subido correctamente.",
            "item": {
                "video_id": video_id,
                "title": title.strip(),
                "video_url": video_url,
                "video_filename": safe_name,
                "is_active": True,
                "created_at": now_str
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error subiendo video lateral: {e}")

@app.get("/admin/free-picks-video")
def admin_list_free_picks_video(admin=Depends(require_admin)):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
    SELECT video_id, title, video_filename, video_url, is_active, created_by, created_at, updated_at
    FROM free_picks_videos
    ORDER BY datetime(created_at) DESC
    """)
    items = []
    for row in cur.fetchall():
        item = dict(row)
        item["is_active"] = bool(item["is_active"])
        items.append(item)
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

        # =========================
        # HISTORIAL CON FECHA Y HORA
        # =========================
        # Mantiene latest.json como la tabla activa para web/bot,
        # y guarda copias únicas por carga para auditoría/historial.
        history_dir = DATA_DIR / "history"
        excel_history_dir = history_dir / "excel_uploads"
        json_history_dir = history_dir / "json_snapshots"
        excel_history_dir.mkdir(parents=True, exist_ok=True)
        json_history_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_original_name = Path(filename).name or "upload.xlsx"

        excel_history_path = excel_history_dir / f"{timestamp}_{safe_original_name}"
        shutil.copy(temp_file_path, excel_history_path)

        latest_path = DATA_DIR / "latest.json"
        json_history_path = json_history_dir / f"{timestamp}_{safe_original_name.rsplit('.', 1)[0]}.json"

        if latest_path.exists():
            shutil.copy(latest_path, json_history_path)

        write_admin_log(
            admin_user_id=admin["user_id"],
            action="upload_excel",
            details=(
                f"Archivo: {stored_name} | Fecha: {result.get('date')} | "
                f"Historial Excel: {excel_history_path.name} | "
                f"Historial JSON: {json_history_path.name if latest_path.exists() else 'N/A'}"
            )
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
            "history": {
                "timestamp": timestamp,
                "excel_file": str(excel_history_path),
                "json_snapshot": str(json_history_path) if latest_path.exists() else None,
            },
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

@app.get("/api/data/videopicks")
def api_data_videopicks():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
    SELECT video_id, title, description, video_filename, video_url, created_at
    FROM video_picks
    WHERE is_active = 1
    ORDER BY datetime(created_at) DESC
    LIMIT 1
    """)
    row = cur.fetchone()
    conn.close()

    if not row:
        return {"items": []}

    return {"items": [dict(row)]}

@app.get("/api/data/free-picks-video")
def api_data_free_picks_video():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
    SELECT video_id, title, video_filename, video_url, created_at
    FROM free_picks_videos
    WHERE is_active = 1
    ORDER BY datetime(created_at) DESC
    LIMIT 1
    """)
    row = cur.fetchone()
    conn.close()

    if not row:
        return {"items": []}

    return {"items": [dict(row)]}

# =========================
# HISTORY ENDPOINTS
# =========================

@app.get("/api/history")
def api_history():
    history_dir = DATA_DIR / "history"
    excel_history_dir = history_dir / "excel_uploads"
    json_history_dir = history_dir / "json_snapshots"

    excel_files = []
    json_files = []

    if excel_history_dir.exists():
        excel_files = [
            {
                "filename": f.name,
                "path": str(f),
                "size_bytes": f.stat().st_size,
                "modified_at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
            }
            for f in sorted(excel_history_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
            if f.is_file()
        ]

    if json_history_dir.exists():
        json_files = [
            {
                "filename": f.name,
                "path": str(f),
                "size_bytes": f.stat().st_size,
                "modified_at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
            }
            for f in sorted(json_history_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if f.is_file()
        ]

    return {
        "excel_uploads": excel_files,
        "json_snapshots": json_files,
    }

@app.get("/api/history/json/{filename}")
def api_history_json(filename: str):
    safe_name = Path(filename).name
    json_path = DATA_DIR / "history" / "json_snapshots" / safe_name

    if not json_path.exists() or json_path.suffix.lower() != ".json":
        raise HTTPException(status_code=404, detail="Snapshot no encontrado.")

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo leer el snapshot: {e}")


# =========================
# AUTOMATIC EVALUATIONS / RESULTS DASHBOARD
# =========================

EVALUATION_SECTIONS = {
    "ultra": "Predicciones Ultrafiltradas",
    "public": "Predicciones Simples",
    "combinadas": "Combinadas IA",
    "inferno": "Combinadas Inferno",
}

FINISHED_FIXTURE_STATUSES = {"FT", "AET", "PEN"}

# Alias y normalizaciones para mejorar el emparejamiento contra API-Football.
# La API puede usar nombres oficiales distintos a los que cargamos en Excel.
TEAM_ALIASES = {
    "idv": "independiente del valle",
    "ind del valle": "independiente del valle",
    "independiente dv": "independiente del valle",
    "independiente valle": "independiente del valle",
    "atletico madrid": "atletico madrid",
    "atletico de madrid": "atletico madrid",
    "a madrid": "atletico madrid",
    "arsenal": "arsenal",
    "rosario central": "rosario central",
    "libertad": "libertad asuncion",
    "libertad asuncion": "libertad asuncion",
    "sporting cristal": "sporting cristal",
    "palmeiras": "palmeiras",
    "tigres": "tigres uanl",
    "tigres uanl": "tigres uanl",
    "nashville": "nashville sc",
    "nashville sc": "nashville sc",
    "recoleta": "deportivo recoleta",
    "deportivo recoleta": "deportivo recoleta",
    "santos": "santos",
    "universidad central": "universidad central",
    "ucv": "universidad central",
    "man utd": "manchester united",
    "man united": "manchester united",
    "man city": "manchester city",
    "athletic bilbao": "athletic club",
    "sporting cp": "sporting",
    "psg": "paris saint germain",
    "bayern munich": "bayern munich",
    "bayern munchen": "bayern munich",
    "inter": "inter milan",
    "ac milan": "milan",
    "roma": "as roma",
    "spurs": "tottenham",
}

LEAGUE_ALIASES = {
    "champions": "uefa champions league",
    "champions sf": "uefa champions league",
    "uefa champions": "uefa champions league",
    "uefa champions league": "uefa champions league",
    "libertadores": "conmebol libertadores",
    "copa libertadores": "conmebol libertadores",
    "conmebol libertadores": "conmebol libertadores",
    "sudamericana": "conmebol sudamericana",
    "copa sudamericana": "conmebol sudamericana",
    "conmebol sudamericana": "conmebol sudamericana",
    "concachampions": "concacaf champions cup",
    "concacaf champions": "concacaf champions cup",
    "concacaf champions cup": "concacaf champions cup",
    "concacaf champions league": "concacaf champions cup",
}

def normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("’", "'").replace("`", "'")
    text = re.sub(r"[^a-z0-9+\-.\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def canonical_team_name(name: str) -> str:
    text = normalize_text(name)
    text = re.sub(r"\b(fc|cf|sc|ac|cd|club|deportivo|club de futbol)\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return TEAM_ALIASES.get(text, text)

def canonical_league_name(name: str) -> str:
    text = normalize_text(name)
    text = text.replace("semi finals", "sf").replace("semifinal", "sf")
    return LEAGUE_ALIASES.get(text, text)

def split_match_name(match_name: str) -> tuple[str, str]:
    raw = str(match_name or "")
    patterns = [r"\s+vs\.?\s+", r"\s+v\.?\s+", r"\s+-\s+", r"\s+–\s+"]
    for pat in patterns:
        parts = re.split(pat, raw, flags=re.IGNORECASE)
        if len(parts) >= 2:
            return parts[0].strip(), parts[1].strip()
    return raw.strip(), ""

def string_similarity(a: str, b: str) -> float:
    a_norm = normalize_text(a)
    b_norm = normalize_text(b)
    if not a_norm or not b_norm:
        return 0.0
    if a_norm == b_norm:
        return 1.0
    if a_norm in b_norm or b_norm in a_norm:
        return 0.92
    return SequenceMatcher(None, a_norm, b_norm).ratio()

def token_similarity(a: str, b: str) -> float:
    a_tokens = set(normalize_text(a).split())
    b_tokens = set(normalize_text(b).split())
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / max(len(a_tokens), len(b_tokens))

def team_similarity(a: str, b: str) -> float:
    a_norm = canonical_team_name(a)
    b_norm = canonical_team_name(b)
    if not a_norm or not b_norm:
        return 0.0
    if a_norm == b_norm:
        return 1.0
    if a_norm in b_norm or b_norm in a_norm:
        return 0.95
    seq = string_similarity(a_norm, b_norm)
    tok = token_similarity(a_norm, b_norm)
    # Fuzzy ponderado: tolera nombres incompletos, siglas y pequeñas variaciones.
    return max(seq * 0.72 + tok * 0.28, tok)

def league_similarity(a: str, b: str) -> float:
    a_norm = canonical_league_name(a)
    b_norm = canonical_league_name(b)
    if not a_norm or not b_norm:
        return 0.0
    if a_norm == b_norm:
        return 1.0
    if a_norm in b_norm or b_norm in a_norm:
        return 0.92
    seq = string_similarity(a_norm, b_norm)
    tok = token_similarity(a_norm, b_norm)
    return max(seq * 0.65 + tok * 0.35, tok)

def get_fixture_league_name(fixture: dict[str, Any]) -> str:
    league = fixture.get("league", {}) or {}
    return str(league.get("name") or league.get("round") or "")

def match_fixture_for_pick(match_name: str, fixtures: list[dict[str, Any]], pick_league: str = "") -> Optional[dict[str, Any]]:
    pick_home, pick_away = split_match_name(match_name)
    pick_league_norm = canonical_league_name(pick_league)

    if not pick_home and not pick_away:
        return None

    best_fixture = None
    best_score = 0.0
    best_debug: dict[str, Any] = {}

    for fixture in fixtures:
        teams = fixture.get("teams", {}) or {}
        home = (teams.get("home") or {}).get("name", "")
        away = (teams.get("away") or {}).get("name", "")
        fixture_league = get_fixture_league_name(fixture)
        lsim = league_similarity(pick_league_norm, fixture_league) if pick_league_norm else 0.0

        home_home = team_similarity(pick_home, home) if pick_home else 0.0
        away_away = team_similarity(pick_away, away) if pick_away else 0.0
        home_away = team_similarity(pick_home, away) if pick_home else 0.0
        away_home = team_similarity(pick_away, home) if pick_away else 0.0

        direct = (home_home + away_away) / 2 if pick_home and pick_away else max(home_home, away_away)
        reversed_score = (home_away + away_home) / 2 if pick_home and pick_away else max(home_away, away_home)
        team_score = max(direct, reversed_score * 0.96)
        one_team_score = max(home_home, away_away, home_away, away_home)

        # Score principal: equipos pesan más; liga ayuda a confirmar cuando hay múltiples opciones.
        combined = (team_score * 0.78) + (lsim * 0.22 if pick_league_norm else 0.0)

        # Fallback pedido: si coinciden fecha + liga + un solo equipo, tomar ese partido.
        # Fecha ya está implícita porque fixtures viene filtrado por date_key.
        if lsim >= 0.58 and one_team_score >= 0.68:
            combined = max(combined, 0.72 + (one_team_score * 0.18) + (lsim * 0.10))

        # Fallback adicional: si ambos equipos son bastante parecidos aunque la liga venga distinta.
        if team_score >= 0.62:
            combined = max(combined, team_score)

        if combined > best_score:
            best_score = combined
            best_fixture = fixture
            best_debug = {
                "confidence": round(combined, 3),
                "team_score": round(team_score, 3),
                "one_team_score": round(one_team_score, 3),
                "league_score": round(lsim, 3),
                "pick_home": pick_home,
                "pick_away": pick_away,
                "fixture_home": home,
                "fixture_away": away,
                "pick_league": pick_league,
                "fixture_league": fixture_league,
            }

    if not best_fixture:
        return None

    # Umbrales flexibles:
    # - dos equipos: aceptamos fuzzy medio/alto.
    # - un equipo + liga: aceptamos aunque el segundo nombre no coincida.
    team_ok = best_debug.get("team_score", 0) >= 0.54
    one_team_league_ok = best_debug.get("one_team_score", 0) >= 0.68 and best_debug.get("league_score", 0) >= 0.58
    combined_ok = best_debug.get("confidence", 0) >= 0.60

    if combined_ok and (team_ok or one_team_league_ok):
        try:
            best_fixture["_proheat_match"] = best_debug
        except Exception:
            pass
        return best_fixture

    return None

def football_api_get_fixtures(date_key: str) -> list[dict[str, Any]]:
    if not API_FOOTBALL_KEY:
        raise HTTPException(status_code=500, detail="Falta API_FOOTBALL_KEY en Railway.")

    response = requests.get(
        f"{API_FOOTBALL_BASE}/fixtures",
        headers={"x-apisports-key": API_FOOTBALL_KEY},
        params={"date": date_key},
        timeout=35,
    )
    if response.status_code not in (200, 201):
        raise HTTPException(status_code=500, detail=f"Error consultando API-Football: {response.text}")
    payload = response.json()
    return payload.get("response", []) if isinstance(payload, dict) else []

def fixture_score(fixture: dict[str, Any]) -> Optional[dict[str, Any]]:
    fixture_info = fixture.get("fixture", {}) or {}
    status_short = ((fixture_info.get("status") or {}).get("short") or "").upper()
    if status_short not in FINISHED_FIXTURE_STATUSES:
        return None

    goals = fixture.get("goals", {}) or {}
    home_goals = goals.get("home")
    away_goals = goals.get("away")
    if home_goals is None or away_goals is None:
        return None

    teams = fixture.get("teams", {}) or {}
    return {
        "home_team": (teams.get("home") or {}).get("name", ""),
        "away_team": (teams.get("away") or {}).get("name", ""),
        "home_goals": int(home_goals),
        "away_goals": int(away_goals),
        "total_goals": int(home_goals) + int(away_goals),
        "status": status_short,
    }

def resolve_team_side(prediction_text: str, score: dict[str, Any], pick_home: str = "", pick_away: str = "") -> Optional[str]:
    text = canonical_team_name(prediction_text)
    candidates = [
        ("home", score.get("home_team", "")),
        ("away", score.get("away_team", "")),
        ("home", pick_home),
        ("away", pick_away),
    ]
    best_side = None
    best_score = 0.0
    for side, name in candidates:
        sim = team_similarity(text, name)
        # Also check if team name is embedded in the prediction phrase.
        team_norm = canonical_team_name(name)
        if team_norm and team_norm in text:
            sim = max(sim, 0.95)
        if sim > best_score:
            best_score = sim
            best_side = side
    return best_side if best_score >= 0.45 else None

def first_line_value(text: str) -> Optional[tuple[str, float]]:
    match = re.search(r"([+-])\s*(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    return match.group(1), float(match.group(2))

def evaluate_prediction_text(prediction: str, score: dict[str, Any], match_name: str = "") -> dict[str, Any]:
    original_prediction = str(prediction or "").strip()
    text = normalize_text(original_prediction)
    pick_home, pick_away = split_match_name(match_name)

    if not text:
        return {"status": "unknown", "prediction": original_prediction, "reason": "Predicción vacía"}

    hg = int(score["home_goals"])
    ag = int(score["away_goals"])
    total = hg + ag

    # Ambos anotan / BTTS
    if "ambos" in text and ("anotan" in text or "marcan" in text):
        return {"status": "hit" if (hg > 0 and ag > 0) else "miss", "prediction": original_prediction, "reason": f"Resultado {hg}-{ag}"}

    # Doble oportunidad: Equipo o Empate / gana o empata
    if "empate" in text and ("gana" in text or " o " in text):
        side = resolve_team_side(text, score, pick_home, pick_away)
        if side == "home":
            return {"status": "hit" if hg >= ag else "miss", "prediction": original_prediction, "reason": f"{score['home_team']} {hg}-{ag} {score['away_team']}"}
        if side == "away":
            return {"status": "hit" if ag >= hg else "miss", "prediction": original_prediction, "reason": f"{score['home_team']} {hg}-{ag} {score['away_team']}"}
        if "empate" in text and "gana" not in text:
            return {"status": "hit" if hg == ag else "miss", "prediction": original_prediction, "reason": f"Resultado {hg}-{ag}"}

    # Hándicap simple tipo Equipo +1.5 Hándicap / Handicap -2.5
    if "handicap" in text or "handicap" in normalize_text(original_prediction.replace("á", "a")):
        line = first_line_value(text)
        side = resolve_team_side(text, score, pick_home, pick_away)
        if line and side:
            sign, value = line
            team_goals = hg if side == "home" else ag
            opp_goals = ag if side == "home" else hg
            adjusted = team_goals + value if sign == "+" else team_goals - value
            return {"status": "hit" if adjusted > opp_goals else "miss", "prediction": original_prediction, "reason": f"Marcador {hg}-{ag}, hándicap {sign}{value}"}

    # Totales de goles: Goles +1.5 / -3.5
    if "gol" in text or "total" in text or "marcador global" in text:
        line = first_line_value(text)
        if line:
            sign, value = line
            # Si la predicción menciona un equipo, evalúa goles del equipo. Si no, evalúa total.
            side = resolve_team_side(text, score, pick_home, pick_away)
            metric_value = total
            metric_label = "total"
            if side == "home":
                metric_value = hg
                metric_label = score.get("home_team", "local")
            elif side == "away":
                metric_value = ag
                metric_label = score.get("away_team", "visitante")
            ok = metric_value > value if sign == "+" else metric_value < value
            return {"status": "hit" if ok else "miss", "prediction": original_prediction, "reason": f"{metric_label}: {metric_value}, línea {sign}{value}"}

    # ML directo / gana
    if " ml" in f" {text}" or "gana" in text:
        side = resolve_team_side(text, score, pick_home, pick_away)
        if side == "home":
            return {"status": "hit" if hg > ag else "miss", "prediction": original_prediction, "reason": f"Resultado {hg}-{ag}"}
        if side == "away":
            return {"status": "hit" if ag > hg else "miss", "prediction": original_prediction, "reason": f"Resultado {hg}-{ag}"}

    return {"status": "unknown", "prediction": original_prediction, "reason": "Mercado no soportado todavía"}

def extract_prediction_fields(section: str, row: dict[str, Any]) -> list[dict[str, str]]:
    ignore_keys = {"hora", "liga", "sem", "partido", "fecha", "equipo", "id", "notas", "contexto"}
    preferred_keys = [
        "ml_prob", "ml", "pick", "prediccion", "predicción", "pronostico", "pronóstico",
        "apuesta", "mercado", "seleccion", "selección", "marcador_global", "goles_local", "goles_visitante",
    ]
    fields: list[dict[str, str]] = []
    for key in preferred_keys:
        if key in row and str(row.get(key, "")).strip():
            fields.append({"key": key, "value": str(row.get(key)).strip()})

    # Para combinadas puede haber columnas con nombres no estándar. Toma textos largos útiles.
    if section in {"combinadas", "inferno"}:
        for key, value in row.items():
            key_norm = normalize_text(key)
            if key_norm in ignore_keys or any(f["key"] == key for f in fields):
                continue
            value_text = str(value or "").strip()
            if value_text and len(value_text) >= 3:
                fields.append({"key": str(key), "value": value_text})

    # Evita duplicados exactos conservando orden.
    seen = set()
    unique = []
    for field in fields:
        token = (field["key"], field["value"])
        if token not in seen:
            seen.add(token)
            unique.append(field)
    return unique

def evaluate_row(section: str, row: dict[str, Any], fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    match_name = str(row.get("partido") or row.get("Partido") or "").strip()
    base = {
        "section": section,
        "section_label": EVALUATION_SECTIONS.get(section, section),
        "hora": row.get("hora") or row.get("Hora"),
        "liga": row.get("liga") or row.get("Liga"),
        "partido": match_name,
        "status": "pending",
        "score": None,
        "evaluations": [],
    }

    fixture = match_fixture_for_pick(match_name, fixtures, str(base.get("liga") or ""))
    if not fixture:
        base["status"] = "pending"
        base["reason"] = "Partido no encontrado en API-Football"
        return base

    match_info = fixture.get("_proheat_match") if isinstance(fixture, dict) else None
    if match_info:
        base["match_info"] = match_info

    score = fixture_score(fixture)
    if not score:
        base["status"] = "pending"
        base["reason"] = "Partido encontrado por fuzzy, liga o equipo, pero aún no tiene resultado final"
        return base

    base["score"] = score
    fields = extract_prediction_fields(section, row)
    if not fields:
        base["status"] = "unknown"
        base["reason"] = "No se encontraron columnas de predicción evaluables"
        return base

    evaluations = []
    for field in fields:
        ev = evaluate_prediction_text(field["value"], score, match_name)
        ev["field"] = field["key"]
        evaluations.append(ev)

    base["evaluations"] = evaluations
    known = [ev for ev in evaluations if ev["status"] in {"hit", "miss"}]
    if not known:
        base["status"] = "unknown"
        base["reason"] = "Sin mercados soportados para evaluación automática"
    elif any(ev["status"] == "miss" for ev in known):
        base["status"] = "miss"
        base["reason"] = "Al menos una selección evaluada falló"
    else:
        base["status"] = "hit"
        base["reason"] = "Todas las selecciones evaluadas acertaron"
    return base

def summarize_evaluations(section_rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(section_rows)
    hits = sum(1 for item in section_rows if item.get("status") == "hit")
    misses = sum(1 for item in section_rows if item.get("status") == "miss")
    pending = sum(1 for item in section_rows if item.get("status") == "pending")
    unknown = sum(1 for item in section_rows if item.get("status") == "unknown")
    decided = hits + misses
    pct = round((hits / decided) * 100, 2) if decided else 0.0
    return {
        "total": total,
        "hits": hits,
        "misses": misses,
        "pending": pending,
        "unknown": unknown,
        "decided": decided,
        "effectiveness_pct": pct,
    }

def build_evaluation_payload(snapshot_data: dict[str, Any], date_key: str) -> dict[str, Any]:
    fixtures = football_api_get_fixtures(date_key)
    sections: dict[str, Any] = {}
    for section, label in EVALUATION_SECTIONS.items():
        rows = snapshot_data.get(section, [])
        if not isinstance(rows, list):
            rows = []
        evaluated_rows = [evaluate_row(section, row, fixtures) for row in rows if isinstance(row, dict)]
        sections[section] = {
            "label": label,
            "summary": summarize_evaluations(evaluated_rows),
            "items": evaluated_rows,
        }
    return {
        "date": date_key,
        "generated_at": iso_now(),
        "sections": sections,
    }

def evaluations_dir() -> Path:
    path = DATA_DIR / "evaluations"
    path.mkdir(parents=True, exist_ok=True)
    return path

def load_snapshot_for_evaluation(history_filename: Optional[str] = None) -> tuple[str, dict[str, Any]]:
    if history_filename:
        safe_name = Path(history_filename).name
        snapshot_path = DATA_DIR / "history" / "json_snapshots" / safe_name
    else:
        snapshot_path = DATA_DIR / "latest.json"

    if not snapshot_path.exists():
        raise HTTPException(status_code=404, detail="Snapshot de picks no encontrado.")

    with open(snapshot_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Snapshot inválido.")
    return snapshot_path.name, data

def save_evaluation_payload(payload: dict[str, Any]) -> Path:
    date_key = payload.get("date") or datetime.now().strftime("%Y-%m-%d")
    path = evaluations_dir() / f"{date_key}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path

def load_evaluation_file(path: Path) -> Optional[dict[str, Any]]:
    try:
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None

def latest_evaluation_payload() -> Optional[dict[str, Any]]:
    files = sorted(evaluations_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for file in files:
        data = load_evaluation_file(file)
        if data:
            return data
    return None

def cumulative_evaluations_payload() -> dict[str, Any]:
    totals = {
        section: {
            "label": label,
            "summary": {"total": 0, "hits": 0, "misses": 0, "pending": 0, "unknown": 0, "decided": 0, "effectiveness_pct": 0.0},
            "daily": [],
        }
        for section, label in EVALUATION_SECTIONS.items()
    }
    files = sorted(evaluations_dir().glob("*.json"))
    for file in files:
        data = load_evaluation_file(file)
        if not data:
            continue
        date_key = data.get("date") or file.stem
        for section in EVALUATION_SECTIONS:
            summary = (((data.get("sections") or {}).get(section) or {}).get("summary") or {})
            totals[section]["daily"].append({
                "date": date_key,
                "effectiveness_pct": summary.get("effectiveness_pct", 0),
                "hits": summary.get("hits", 0),
                "misses": summary.get("misses", 0),
                "pending": summary.get("pending", 0),
                "unknown": summary.get("unknown", 0),
            })
            for key in ["total", "hits", "misses", "pending", "unknown", "decided"]:
                totals[section]["summary"][key] += int(summary.get(key, 0) or 0)

    for section in totals:
        s = totals[section]["summary"]
        s["effectiveness_pct"] = round((s["hits"] / s["decided"]) * 100, 2) if s["decided"] else 0.0
    return {"generated_at": iso_now(), "sections": totals}

@app.post("/admin/evaluations/recalculate")
def admin_recalculate_evaluations(
    date: str = Form(...),
    history_filename: Optional[str] = Form(None),
    admin=Depends(require_admin)
):
    # date debe venir como YYYY-MM-DD porque API-Football usa ese formato.
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise HTTPException(status_code=400, detail="date debe tener formato YYYY-MM-DD.")

    snapshot_name, snapshot_data = load_snapshot_for_evaluation(history_filename)
    payload = build_evaluation_payload(snapshot_data, date)
    payload["source_snapshot"] = snapshot_name
    saved_path = save_evaluation_payload(payload)

    write_admin_log(
        admin_user_id=admin["user_id"],
        action="recalculate_evaluations",
        details=f"date={date} snapshot={snapshot_name} saved={saved_path.name}"
    )

    return {
        "status": "ok",
        "message": "Evaluación recalculada correctamente.",
        "date": date,
        "source_snapshot": snapshot_name,
        "saved_path": str(saved_path),
        "payload": payload,
    }

@app.get("/api/evaluations/day/{date_key}")
def api_evaluations_day(date_key: str):
    safe_date = Path(date_key).name
    path = evaluations_dir() / f"{safe_date}.json"
    data = load_evaluation_file(path)
    if not data:
        raise HTTPException(status_code=404, detail="Evaluación no encontrada para esa fecha.")
    return data

@app.get("/api/evaluations/cumulative")
def api_evaluations_cumulative():
    return cumulative_evaluations_payload()

@app.get("/api/evaluations/frontend")
def api_evaluations_frontend():
    latest = latest_evaluation_payload()
    cumulative = cumulative_evaluations_payload()
    return {
        "latest": latest,
        "cumulative": cumulative,
        "sections": EVALUATION_SECTIONS,
    }

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
        "video_uploads_dir": str(VIDEO_UPLOADS_DIR),
        "static_dir": str(STATIC_DIR),
        "paypal_configured": bool(PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET),
        "paypal_client_id_present": bool(PAYPAL_CLIENT_ID),
        "paypal_client_secret_present": bool(PAYPAL_CLIENT_SECRET),
        "paypal_api_base_present": bool(PAYPAL_API_BASE),
        "paypal_client_id_len": len(PAYPAL_CLIENT_ID or ""),
        "paypal_client_secret_len": len(PAYPAL_CLIENT_SECRET or ""),
        "telegram_memberships_enabled": True,
        "bot_premium_price_mxn": BOT_PREMIUM_PRICE_MXN,
        "bot_premium_days": BOT_PREMIUM_DAYS,
        "bot_payment_clabe_configured": bool(BOT_PAYMENT_CLABE and not BOT_PAYMENT_CLABE.startswith("CONFIGURA_")),
        "telegram_bot_notifications_enabled": bool(TELEGRAM_BOT_TOKEN),
        "api_football_configured": bool(API_FOOTBALL_KEY),
        "api_football_base": API_FOOTBALL_BASE,
        "evaluations_dir": str(DATA_DIR / "evaluations"),
    }

# =========================
# RUN LOCAL
# =========================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend:app", host="0.0.0.0", port=8000, reload=True)