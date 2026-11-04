"""Kontrol biaya LLM: batas panjang jawaban, pencatatan token (agregat, tanpa isi tulisan), cache hasil per pemilik,
pagar anggaran harian, dan dasbor admin. Cek EYD tidak memakai LLM sehingga tidak terpengaruh pagar anggaran."""
import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import obs
from .auth import current_admin
from .config import settings
from .db import get_db
from .models import Institution, LLMCache, LLMUsage, Membership
from .quota import today

router = APIRouter(prefix="/api")
PROMPT_VERSION = "2026-11-a"  # naikkan saat prompt/format keluaran berubah agar cache lama tidak dipakai
EST_CHARS_PER_TOKEN = 3  # perkiraan konservatif (Indonesia ~3,5) bila penyedia tidak melaporkan usage


class Acc:
    """Penjumlah pemakaian untuk satu blok `call(...)`."""
    def __init__(self):
        self.calls = self.prompt = self.completion = 0


_CTX: ContextVar[dict | None] = ContextVar("llm_call", default=None)


@contextmanager
def call(kind: str):
    """Tandai blok pemanggilan LLM (coach|analyze|sidang|summary): menentukan batas jawaban dan mengumpulkan pemakaian token."""
    acc = Acc()
    tok = _CTX.set({"kind": kind, "acc": acc})
    try:
        yield acc
    finally:
        _CTX.reset(tok)


def max_tokens() -> int:
    c = _CTX.get()
    caps = {"coach": settings.llm_max_tokens_coach, "analyze": settings.llm_max_tokens_analyze,
            "sidang": settings.llm_max_tokens_sidang, "summary": settings.llm_max_tokens_summary}
    return caps.get(c["kind"] if c else "", settings.llm_max_tokens_analyze)  # tanpa konteks: batas terlonggar, tetap ada batas


def estimate(*texts: str) -> int:
    return max(1, sum(len(t or "") for t in texts) // EST_CHARS_PER_TOKEN)


def add(prompt: int, completion: int) -> None:
    c = _CTX.get()
    if c:
        a = c["acc"]
        a.calls, a.prompt, a.completion = a.calls + 1, a.prompt + max(0, prompt), a.completion + max(0, completion)


# ---------- pencatatan ----------
def institution_of(db: Session, who: str) -> int:
    """Kampus mahasiswa (0 = tanpa kampus / perangkat anonim)."""
    if not (who[:1] == "u" and who[1:].isdigit()):
        return 0
    return db.scalar(select(Membership.institution_id).where(Membership.user_id == int(who[1:]), Membership.role == "mahasiswa").order_by(Membership.id).limit(1)) or 0


def _bump(db: Session, kind: str, inst: int, **inc: int) -> None:
    cond = (LLMUsage.day == today(), LLMUsage.kind == kind, LLMUsage.institution_id == inst)
    if db.scalar(select(LLMUsage.id).where(*cond)) is None:
        try:
            db.add(LLMUsage(day=today(), kind=kind, institution_id=inst))
            db.flush()
        except IntegrityError:  # proses lain membuatnya lebih dulu
            db.rollback()
    db.execute(update(LLMUsage).where(*cond).values({k: getattr(LLMUsage, k) + v for k, v in inc.items()}))  # atomik di sisi DB
    db.commit()


def record(db: Session, who: str, kind: str, acc: Acc) -> None:
    if acc.calls:
        _bump(db, kind, institution_of(db, who), calls=acc.calls, prompt_tokens=acc.prompt, completion_tokens=acc.completion)


def record_hit(db: Session, who: str, kind: str) -> None:
    _bump(db, kind, institution_of(db, who), cache_hits=1)


# ---------- pagar anggaran ----------
def tokens_today(db: Session) -> int:
    return db.scalar(select(func.coalesce(func.sum(LLMUsage.prompt_tokens + LLMUsage.completion_tokens), 0)).where(LLMUsage.day == today())) or 0


def over_budget(db: Session) -> bool:
    b = settings.llm_daily_token_budget
    return b > 0 and tokens_today(db) >= b


def check_budget(db: Session) -> None:
    """Panggil SEBELUM memotong kuota. Anggaran harian habis -> fitur AI berhenti sampai besok; cek EYD dan hasil cache tetap jalan."""
    if over_budget(db):
        obs.event_throttled("llm_budget_exceeded", "warning", 300, budget=settings.llm_daily_token_budget)
        raise HTTPException(503, "Fitur AI sedang dibatasi hari ini karena batas pemakaian harian tercapai. Cek EYD tetap bisa dipakai. Kuotamu tidak terpakai; coba lagi besok.")


# ---------- cache ----------
def cache_key(kind: str, doc_type: str, chapter_key: str, text: str, rules: dict | None) -> str:
    blob = json.dumps([PROMPT_VERSION, settings.llm_provider, settings.llm_model_fast, settings.llm_model_smart, kind, doc_type, chapter_key, rules or {}, (text or "").strip()],
                      ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def cache_get(db: Session, who: str, key: str):
    if settings.llm_cache_days <= 0:
        return None
    row = db.scalar(select(LLMCache).where(LLMCache.owner == who, LLMCache.key == key))
    if row and row.created_at > datetime.utcnow() - timedelta(days=settings.llm_cache_days):
        return json.loads(row.payload)
    return None


def cache_put(db: Session, who: str, kind: str, key: str, payload) -> None:
    if settings.llm_cache_days <= 0:
        return
    now, data = datetime.utcnow(), json.dumps(payload, ensure_ascii=False)
    row = db.scalar(select(LLMCache).where(LLMCache.owner == who, LLMCache.key == key))
    if row:
        row.payload, row.created_at = data, now
    else:
        db.add(LLMCache(owner=str(who), key=key, kind=kind, payload=data, created_at=now))
    try:
        db.flush()
    except IntegrityError:  # dua permintaan sama bersamaan: yang lain sudah menyimpan
        db.rollback()
        return
    db.execute(delete(LLMCache).where(LLMCache.created_at < now - timedelta(days=settings.llm_cache_days)))
    old = db.scalars(select(LLMCache.id).where(LLMCache.owner == who).order_by(LLMCache.created_at.desc(), LLMCache.id.desc()).offset(max(1, settings.llm_cache_max_per_owner))).all()
    if old:
        db.execute(delete(LLMCache).where(LLMCache.id.in_(old)))
    db.commit()


# ---------- dasbor admin ----------
def _cost(prompt: int, completion: int) -> float | None:
    if not (settings.llm_price_in_per_mtok or settings.llm_price_out_per_mtok):
        return None
    return round(prompt / 1e6 * settings.llm_price_in_per_mtok + completion / 1e6 * settings.llm_price_out_per_mtok, 4)


def _agg(rows) -> dict:
    calls, hits = sum(r.calls for r in rows), sum(r.cache_hits for r in rows)
    p, c = sum(r.prompt_tokens for r in rows), sum(r.completion_tokens for r in rows)
    return {"calls": calls, "cache_hits": hits, "prompt_tokens": p, "completion_tokens": c, "total_tokens": p + c, "cost": _cost(p, c)}


@router.get("/admin/llm-usage")
def llm_usage(days: int = Query(30, ge=1, le=365), _=Depends(current_admin), db: Session = Depends(get_db)):
    """Pemakaian LLM agregat (tanpa isi tulisan): total, per hari, per jenis panggilan, per kampus, dan status anggaran harian."""
    since = today() - timedelta(days=days - 1)
    rows = db.scalars(select(LLMUsage).where(LLMUsage.day >= since).order_by(LLMUsage.day)).all()
    names = dict(db.execute(select(Institution.id, Institution.name)).all())
    group = lambda key: {k: [r for r in rows if key(r) == k] for k in sorted({key(r) for r in rows})}  # noqa: E731
    total = _agg(rows)
    served = total["calls"] + total["cache_hits"]
    budget, used = settings.llm_daily_token_budget, tokens_today(db)
    return {"days": days, "currency": settings.llm_cost_currency, "priced": total["cost"] is not None, "totals": total,
            "cache_hit_rate": round(total["cache_hits"] / served, 3) if served else None,
            "by_day": [{"day": d.isoformat(), **_agg(rs)} for d, rs in group(lambda r: r.day).items()],
            "by_kind": {k: _agg(rs) for k, rs in group(lambda r: r.kind).items()},
            "by_institution": [{"institution_id": i, "name": names.get(i) or ("Tanpa kampus" if i == 0 else f"Kampus #{i}"), **_agg(rs)} for i, rs in group(lambda r: r.institution_id).items()],
            "budget": {"daily_tokens": budget, "used_today": used, "pct": round(used * 100 / budget, 1) if budget else None}}
