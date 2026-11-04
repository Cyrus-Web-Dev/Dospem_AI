"""Kuota harian: Redis bila REDIS_URL diisi (atomik, cepat), selain itu tabel ai_usage.
Setiap pemakaian juga dicatat di usage_daily untuk analitik (terlepas dari Redis)."""
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .models import AIUsage, UsageDaily
from .ratelimit import redis_client


def today():
    return datetime.now(ZoneInfo(settings.timezone)).date()


def _k(owner: str, kind: str) -> str:
    return owner if kind == "coach" else hashlib.sha1(f"{kind}:{owner}".encode()).hexdigest()[:40]


def _row(db: Session, owner: str, kind: str, create=False):
    row = db.scalar(select(AIUsage).where(AIUsage.owner == _k(owner, kind), AIUsage.day == today()))
    if not row and create:
        row = AIUsage(owner=_k(owner, kind), day=today(), count=0)
        db.add(row)
        db.flush()
    return row


def _bump(db: Session, kind: str, n: int) -> None:
    """Catat pemakaian untuk analitik. Kegagalan di sini tidak boleh mengganggu kuota."""
    try:
        for _ in range(2):
            res = db.execute(update(UsageDaily).where(UsageDaily.day == today(), UsageDaily.kind == kind)
                             .values(count=UsageDaily.count + n))
            if res.rowcount:
                db.commit()
                return
            try:
                db.add(UsageDaily(day=today(), kind=kind, count=max(n, 0)))
                db.commit()
                return
            except IntegrityError:
                db.rollback()
    except Exception:
        db.rollback()


def used(db: Session, owner: str, kind: str = "coach") -> int:
    r = redis_client()
    if r:
        return int(r.get(f"q:{_k(owner, kind)}:{today()}") or 0)
    row = _row(db, owner, kind)
    return row.count if row else 0


def take(db: Session, owner: str, limit: int, kind: str = "coach") -> int | None:
    """Ambil 1 jatah. Mengembalikan hitungan baru, atau None bila kuota habis."""
    r = redis_client()
    if r:
        key = f"q:{_k(owner, kind)}:{today()}"
        n = r.incr(key)
        r.expire(key, 172800)
        if n > limit:
            r.decr(key)
            return None
        _bump(db, kind, 1)
        return n
    row = _row(db, owner, kind, create=True)
    if row.count >= limit:
        db.commit()
        return None
    row.count += 1
    db.commit()
    n = row.count
    _bump(db, kind, 1)
    return n


def refund(db: Session, owner: str, kind: str = "coach") -> None:
    r = redis_client()
    if r:
        r.decr(f"q:{_k(owner, kind)}:{today()}")
    else:
        row = _row(db, owner, kind)
        if row and row.count > 0:
            row.count -= 1
            db.commit()
    _bump(db, kind, -1)
