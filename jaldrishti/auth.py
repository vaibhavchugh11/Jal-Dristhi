import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone

from . import config

ROLES = ["consumer", "government", "firm"]
WATER_PREFS = ["auto", "freshwater", "brackish", "seawater"]
ITERATIONS = 600_000
MIN_PASSWORD = 8
MAX_FAILS = 5
LOCK_SECONDS = 300
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def db_path():
    return config.DATA_DIR / "users.db"


def _connect():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path(), timeout=10)
    con.row_factory = sqlite3.Row
    return con


def init():
    with _connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            org TEXT NOT NULL DEFAULT '',
            water_type TEXT NOT NULL DEFAULT 'auto',
            pw_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            failed_count INTEGER NOT NULL DEFAULT 0,
            locked_until REAL NOT NULL DEFAULT 0)""")


def hash_password(password, salt=None, iterations=ITERATIONS):
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256$%d$%s$%s" % (iterations, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def check_password(password, stored):
    try:
        algo, it, salt, dk = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        new = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt), int(it))
        return hmac.compare_digest(new, base64.b64decode(dk))
    except Exception:
        return False


def clean_email(email):
    return (email or "").strip().lower()


def _public(row):
    return {"email": row["email"], "name": row["name"], "role": row["role"],
            "org": row["org"], "water_type": row["water_type"]}


def gov_code_needed():
    return bool(os.getenv("JALDRISHTI_GOV_CODE", ""))


def create_user(email, name, password, confirm, role, org="", water_type="auto", gov_code=""):
    # returns (user_dict, None) or (None, error_key)
    email = clean_email(email)
    name = (name or "").strip()
    org = (org or "").strip()
    if not name:
        return None, "err_name"
    if not EMAIL_RE.match(email):
        return None, "err_email"
    if len(password or "") < MIN_PASSWORD or password.lower() == email:
        return None, "err_password"
    if password != confirm:
        return None, "err_mismatch"
    if role not in ROLES:
        return None, "err_role"
    if water_type not in WATER_PREFS:
        water_type = "auto"
    if role in ("firm", "government") and not org:
        return None, "err_org"
    need = os.getenv("JALDRISHTI_GOV_CODE", "")
    if role == "government" and need and not hmac.compare_digest((gov_code or "").encode(), need.encode()):
        return None, "err_gov_code"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with _connect() as con:
            con.execute("INSERT INTO users (email,name,role,org,water_type,pw_hash,created_at) VALUES (?,?,?,?,?,?,?)",
                        (email, name, role, org, water_type, hash_password(password), stamp))
            row = con.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    except sqlite3.IntegrityError:
        return None, "err_exists"
    return _public(row), None


def authenticate(email, password, now=None):
    # returns (user_dict, None) or (None, error_key)
    now = time.time() if now is None else now
    email = clean_email(email)
    with _connect() as con:
        row = con.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if row is None:
            hash_password(password or "")          # same work as a real check, so timing does not give the account away
            return None, "err_login"
        if row["locked_until"] > now:
            return None, "err_locked"
        if check_password(password or "", row["pw_hash"]):
            con.execute("UPDATE users SET failed_count=0, locked_until=0 WHERE id=?", (row["id"],))
            return _public(row), None
        fails = row["failed_count"] + 1
        lock = now + LOCK_SECONDS if fails >= MAX_FAILS else 0
        con.execute("UPDATE users SET failed_count=?, locked_until=? WHERE id=?",
                    (0 if lock else fails, lock, row["id"]))
        return None, ("err_locked" if lock else "err_login")


def set_water_type(email, water_type):
    if water_type not in WATER_PREFS:
        return False
    with _connect() as con:
        con.execute("UPDATE users SET water_type=? WHERE email=?", (water_type, clean_email(email)))
    return True


def get_user(email):
    with _connect() as con:
        row = con.execute("SELECT * FROM users WHERE email=?", (clean_email(email),)).fetchone()
    return _public(row) if row else None
