"""Auth email+password (scrypt + JWT). Pengguna anonim tetap bisa mencoba lewat X-Device-Id."""
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, object_session

from . import mailer, obs
from .config import settings
from .db import get_db
from .models import Draft, Membership, PasswordReset, User


DEVICE_RE = re.compile(r"^(?!u\d+$)[A-Za-z0-9._:-]{8,64}$")  # tidak boleh menyerupai owner pengguna ("u123")


def _scrypt(pw: str, salt: bytes) -> str:
    return hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1).hex()


def hash_pw(pw: str) -> str:
    salt = os.urandom(16)
    return salt.hex() + "$" + _scrypt(pw, salt)


def verify_pw(pw: str, stored: str | None) -> bool:
    if not stored:
        return False
    salt, h = stored.split("$")
    return hmac.compare_digest(_scrypt(pw, bytes.fromhex(salt)), h)


def make_token(uid: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(uid), "iat": int(now.timestamp()), "exp": now + timedelta(days=settings.jwt_days)}, settings.secret_key, algorithm="HS256")


def current_user_opt(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> User | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        payload = jwt.decode(authorization[7:], settings.secret_key, algorithms=["HS256"])
        u = db.get(User, int(payload["sub"]))
        iat = int(payload.get("iat", 0))
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        return None
    if not u or u.deleted_at:
        return None
    if u.pw_changed_at and iat < int(u.pw_changed_at.replace(tzinfo=timezone.utc).timestamp()):
        return None  # token terbit sebelum kata sandi diganti
    return u


def current_user(u: User | None = Depends(current_user_opt)) -> User:
    if not u:
        raise HTTPException(401, "Masuk dulu untuk memakai fitur ini")
    return u


def plan_of(u: User) -> str:
    return "premium" if u.premium_until and u.premium_until > datetime.utcnow() else "free"


def is_admin(u: User) -> bool:
    return (u.email or "").lower() in {e.strip().lower() for e in settings.admin_emails.split(",") if e.strip()}


def _is_dosen(u: User) -> bool:
    s = object_session(u)
    return bool(s and s.scalar(select(Membership.id).where(Membership.user_id == u.id, Membership.role == "dosen")))


def _pub(u: User) -> dict:
    return {"email": u.email, "name": u.name, "plan": plan_of(u), "is_admin": is_admin(u), "is_dosen": _is_dosen(u),
            "premium_until": u.premium_until.isoformat() if u.premium_until else None}


class Who(str):
    plan = "free"


def current_admin(u: User = Depends(current_user)) -> User:
    if not is_admin(u):
        raise HTTPException(403, "Khusus admin")
    return u


def owner(x_device_id: str | None = Header(None), u: User | None = Depends(current_user_opt)) -> Who:
    if u:
        w = Who(f"u{u.id}")
        w.plan = plan_of(u)
        return w
    if not x_device_id or not DEVICE_RE.match(x_device_id):
        raise HTTPException(400, "X-Device-Id wajib untuk pengguna belum masuk")
    return Who(x_device_id)


def limit(who: Who) -> int:
    return settings.premium_daily_quota if who.plan == "premium" else settings.free_daily_quota


router = APIRouter(prefix="/api/auth")


class Cred(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)
    password: str = Field(min_length=8, max_length=128)
    name: str | None = Field(None, max_length=120)
    accept_terms: bool = False


def _out(u: User) -> dict:
    return {"token": make_token(u.id), "user": _pub(u)}


@router.post("/register")
def register(b: Cred, x_device_id: str | None = Header(None), db: Session = Depends(get_db)):
    email = b.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Email sudah terdaftar. Coba masuk.")
    if settings.require_terms_consent and not b.accept_terms:
        raise HTTPException(400, "Kamu perlu menyetujui Syarat Layanan dan Kebijakan Privasi untuk mendaftar.")
    u = User(email=email, name=b.name, password_hash=hash_pw(b.password))
    if b.accept_terms:
        u.terms_accepted_at, u.terms_version = datetime.utcnow(), settings.terms_version
    db.add(u)
    db.flush()
    if x_device_id and DEVICE_RE.match(x_device_id):  # draf yang ditulis sebelum daftar ikut terbawa
        db.execute(update(Draft).where(Draft.owner == x_device_id).values(owner=f"u{u.id}"))
    db.commit()
    obs.event("user_registered")
    return _out(u)


@router.post("/login")
def login(b: Cred, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.email == b.email.lower()))
    now = datetime.utcnow()
    if u and u.locked_until and u.locked_until > now:  # tetap terkunci walau kata sandi benar
        mins = int((u.locked_until - now).total_seconds() // 60) + 1
        obs.event("login_blocked_locked", "warning")
        raise HTTPException(429, f"Terlalu banyak percobaan masuk yang gagal. Coba lagi sekitar {mins} menit lagi.")
    if not u or u.deleted_at or not verify_pw(b.password, u.password_hash):
        if u and not u.deleted_at:
            u.failed_logins += 1
            if u.failed_logins >= settings.login_max_failures:
                u.locked_until, u.failed_logins = now + timedelta(minutes=settings.login_lock_minutes), 0
                obs.event("account_locked", "warning", minutes=settings.login_lock_minutes)
            db.commit()
        obs.event("login_failed", "warning")
        raise HTTPException(401, "Email atau kata sandi salah")
    if u.failed_logins or u.locked_until:
        u.failed_logins, u.locked_until = 0, None
        db.commit()
    return _out(u)


FORGOT_REPLY = {"ok": True, "message": "Jika email itu terdaftar, tautan untuk mengatur ulang kata sandi sudah dikirim. Periksa juga folder spam."}


def _th(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class ForgotIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)


@router.post("/forgot")
def forgot(b: ForgotIn, bg: BackgroundTasks, db: Session = Depends(get_db)):
    """Minta tautan reset. Balasan SELALU sama (terdaftar atau tidak) agar email tidak bisa ditebak; email dikirim di latar belakang."""
    now = datetime.utcnow()
    db.execute(delete(PasswordReset).where(PasswordReset.expires_at < now - timedelta(days=1)))  # bersih-bersih token lama
    u = db.scalar(select(User).where(User.email == b.email.lower()))
    if u and not u.deleted_at:
        recent = db.scalar(select(func.count(PasswordReset.id)).where(PasswordReset.user_id == u.id, PasswordReset.created_at > now - timedelta(hours=1))) or 0
        if recent < settings.reset_max_per_hour:
            raw = secrets.token_urlsafe(32)
            db.add(PasswordReset(user_id=u.id, token_hash=_th(raw), expires_at=now + timedelta(minutes=settings.reset_token_minutes)))
            link = f"{settings.base_url.rstrip('/')}/reset.html#t={raw}"  # di fragment (#) agar tidak terkirim ke server/log/referrer
            obs.event("password_reset_requested")
            bg.add_task(mailer.send, u.email, "Atur ulang kata sandi Dospem",
                        f"Halo,\n\nKami menerima permintaan untuk mengatur ulang kata sandi akun Dospem-mu. Buka tautan ini (berlaku {settings.reset_token_minutes} menit, sekali pakai):\n\n{link}\n\n"
                        "Jika bukan kamu yang meminta, abaikan email ini; kata sandimu tidak berubah.\n\nDospem")
    db.commit()
    return FORGOT_REPLY


class ResetIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/reset")
def reset_password(b: ResetIn, db: Session = Depends(get_db)):
    """Pakai token reset: ganti kata sandi, buka kunci akun, cabut semua token sesi lama, dan hanguskan token reset lain."""
    now = datetime.utcnow()
    r = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == _th(b.token)))
    u = db.get(User, r.user_id) if r else None
    if not r or r.used_at or r.expires_at < now or not u or u.deleted_at:
        raise HTTPException(400, "Tautan tidak valid atau sudah kedaluwarsa. Minta tautan baru.")
    u.password_hash, u.pw_changed_at = hash_pw(b.new_password), now.replace(microsecond=0)
    u.failed_logins, u.locked_until = 0, None
    r.used_at = now
    db.execute(delete(PasswordReset).where(PasswordReset.user_id == u.id, PasswordReset.id != r.id))
    db.commit()
    obs.event("password_reset_done")
    return {"ok": True}


class PwIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/password")
def change_password(b: PwIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    """Ganti kata sandi. Semua token lama (perangkat lain) otomatis tidak berlaku; token baru dikembalikan."""
    if not verify_pw(b.old_password, u.password_hash):
        raise HTTPException(403, "Kata sandi lama salah")
    if b.old_password == b.new_password:
        raise HTTPException(400, "Kata sandi baru harus berbeda dari yang lama")
    u.password_hash, u.pw_changed_at = hash_pw(b.new_password), datetime.utcnow().replace(microsecond=0)
    db.commit()
    obs.event("password_changed")
    return _out(u)


@router.get("/me")
def me(u: User = Depends(current_user)):
    return {"user": _pub(u)}
