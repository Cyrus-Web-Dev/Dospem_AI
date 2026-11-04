"""Pembayaran premium. Provider: mock (dev), Midtrans Snap, Xendit Invoice.
Status hanya berubah lewat webhook yang diverifikasi (signature/token + nominal)."""
import hashlib
import hmac
import uuid
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Body, Depends, Header, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from . import obs
from .config import settings
from .db import get_db
from .models import Payment, User

router = APIRouter(prefix="/api")
PLANS = {  # harga/durasi contoh: ubah sesuai strategi
    "premium_30": {"label": "Premium 30 hari", "days": 30, "amount": 29000},
    "premium_90": {"label": "Premium 90 hari", "days": 90, "amount": 69000},
}


def _mock(p: Payment, u: User):
    return f"{settings.base_url}/api/pay/mock/{p.order_id}", None


def _midtrans(p: Payment, u: User):
    host = "app.midtrans.com" if settings.midtrans_production else "app.sandbox.midtrans.com"
    r = httpx.post(f"https://{host}/snap/v1/transactions", auth=(settings.midtrans_server_key, ""), timeout=20, json={
        "transaction_details": {"order_id": p.order_id, "gross_amount": p.amount},
        "customer_details": {"email": u.email, "first_name": u.name or "Mahasiswa"},
        "item_details": [{"id": p.plan_key, "price": p.amount, "quantity": 1, "name": PLANS[p.plan_key]["label"]}],
        "callbacks": {"finish": f"{settings.base_url}/?paid=1"}})
    r.raise_for_status()
    j = r.json()
    return j["redirect_url"], j["token"]


def _xendit(p: Payment, u: User):
    r = httpx.post("https://api.xendit.co/v2/invoices", auth=(settings.xendit_secret_key, ""), timeout=20, json={
        "external_id": p.order_id, "amount": p.amount, "currency": "IDR", "payer_email": u.email,
        "description": PLANS[p.plan_key]["label"], "success_redirect_url": f"{settings.base_url}/?paid=1"})
    r.raise_for_status()
    j = r.json()
    return j["invoice_url"], j["id"]


CREATE = {"mock": _mock, "midtrans": _midtrans, "xendit": _xendit}


def settle(db: Session, p: Payment, status: str) -> None:
    """Idempoten: pembayaran yang sama tidak memperpanjang premium dua kali."""
    if p.status == "paid":
        return
    now = datetime.utcnow()
    if status == "paid":
        u = db.get(User, p.user_id)
        u.premium_until = max(now, u.premium_until or now) + timedelta(days=PLANS[p.plan_key]["days"])
        p.status, p.paid_at = "paid", now
        obs.event("payment_paid", plan=p.plan_key)
    elif status in ("failed", "expired"):
        p.status = status
    db.commit()


def _order(db: Session, order_id: str) -> Payment:
    p = db.scalar(select(Payment).where(Payment.order_id == str(order_id)))
    if not p:
        raise HTTPException(404, "Order tidak ditemukan")
    return p


class Checkout(BaseModel):
    plan: str


@router.get("/plans")
def plans():
    return [{"key": k, **v} for k, v in PLANS.items()]


@router.post("/pay/checkout")
def checkout(b: Checkout, db: Session = Depends(get_db), u: User = Depends(current_user)):
    if b.plan not in PLANS:
        raise HTTPException(404, "Paket tidak dikenal")
    p = Payment(order_id="DSP-" + uuid.uuid4().hex[:16], user_id=u.id, plan_key=b.plan,
                amount=PLANS[b.plan]["amount"], provider=settings.payment_provider)
    db.add(p)
    db.flush()
    try:
        url, ref = CREATE[settings.payment_provider](p, u)
    except (httpx.HTTPError, KeyError):
        db.rollback()
        raise HTTPException(502, "Penyedia pembayaran tidak dapat dihubungi. Coba lagi sebentar.")
    p.provider_ref = ref
    db.commit()
    return {"order_id": p.order_id, "redirect_url": url}


@router.get("/pay/orders/{order_id}")
def order_status(order_id: str, db: Session = Depends(get_db), u: User = Depends(current_user)):
    p = _order(db, order_id)
    if p.user_id != u.id:
        raise HTTPException(404, "Order tidak ditemukan")
    return {"status": p.status}


@router.get("/pay/mock/{order_id}")
def mock_pay(order_id: str, db: Session = Depends(get_db)):
    if settings.payment_provider != "mock":
        raise HTTPException(404)
    settle(db, _order(db, order_id), "paid")
    return RedirectResponse("/?paid=1")


@router.post("/pay/webhook/midtrans")
def hook_midtrans(b: dict = Body(...), db: Session = Depends(get_db)):
    if not settings.midtrans_server_key:
        raise HTTPException(503, "Midtrans belum dikonfigurasi")
    raw = f"{b.get('order_id')}{b.get('status_code')}{b.get('gross_amount')}{settings.midtrans_server_key}"
    if not hmac.compare_digest(hashlib.sha512(raw.encode()).hexdigest(), str(b.get("signature_key", ""))):
        obs.event("payment_webhook_rejected", "warning", provider="midtrans")
        raise HTTPException(403, "Signature tidak valid")
    p = _order(db, b.get("order_id"))
    if int(float(b.get("gross_amount", 0))) != p.amount:
        obs.event("payment_amount_mismatch", "error", provider="midtrans")  # signature sah tetapi nominal beda: layak diselidiki
        raise HTTPException(400, "Nominal tidak cocok")
    ts = b.get("transaction_status")
    if ts == "settlement" or (ts == "capture" and b.get("fraud_status") == "accept"):
        settle(db, p, "paid")
    elif ts in ("deny", "cancel", "failure"):
        settle(db, p, "failed")
    elif ts == "expire":
        settle(db, p, "expired")
    return {"ok": True}


@router.post("/pay/webhook/xendit")
def hook_xendit(b: dict = Body(...), x_callback_token: str | None = Header(None), db: Session = Depends(get_db)):
    if not settings.xendit_callback_token or not hmac.compare_digest(x_callback_token or "", settings.xendit_callback_token):
        obs.event("payment_webhook_rejected", "warning", provider="xendit")
        raise HTTPException(403, "Token callback tidak valid")
    p = _order(db, b.get("external_id"))
    if int(b.get("amount", 0)) != p.amount:
        obs.event("payment_amount_mismatch", "error", provider="xendit")
        raise HTTPException(400, "Nominal tidak cocok")
    st = str(b.get("status", "")).upper()
    settle(db, p, "paid" if st in ("PAID", "SETTLED") else "expired" if st == "EXPIRED" else "ignore")
    return {"ok": True}
