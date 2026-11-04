from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

import httpx

from . import eyd, llm, meter, obs, quota, revisions, style
from .config import settings
from .db import get_db
from .auth import limit, owner
from .models import AIUsage, Draft
from .roadmap import DOC_TYPES, ROADMAP

router = APIRouter(prefix="/api")


def _usage(db: Session, who: str) -> AIUsage:
    u = db.scalar(select(AIUsage).where(AIUsage.owner == who, AIUsage.day == date.today()))
    if not u:
        u = AIUsage(owner=who, day=date.today(), count=0)
        db.add(u)
        db.flush()
    return u


class TextIn(BaseModel):
    text: str = Field(max_length=20000)


class CoachIn(TextIn):
    doc_type: str = "skripsi"
    chapter_key: str = ""


class DraftIn(BaseModel):
    content: str = Field(max_length=200000)

    @field_validator("content")
    @classmethod
    def _no_nul(cls, v: str) -> str:
        return v.replace("\x00", "")  # PostgreSQL menolak karakter NUL di kolom teks


def _valid_chapter(doc_type: str, chapter_key: str) -> None:
    if chapter_key not in {c["key"] for c in ROADMAP.get(doc_type, [])}:
        raise HTTPException(404, "Jenis tugas atau bab tidak dikenal")


@router.get("/doctypes")
def doctypes():
    return [{"key": d["key"], "label": d["label"]} for d in DOC_TYPES]


@router.get("/roadmap/{doc_type}")
def roadmap(doc_type: str, rules: dict | None = Depends(style.current_rules)):
    if doc_type not in ROADMAP:
        raise HTTPException(404, "Jenis tugas tidak dikenal")
    return style.apply_roadmap(ROADMAP[doc_type], rules, doc_type)


@router.post("/check")
def check(body: TextIn, rules: dict | None = Depends(style.current_rules)):
    """Gratis & tanpa kuota: aturan ejaan + gaya selingkung (bila mahasiswa memilih)."""
    return {"issues": eyd.check(body.text, style.check(body.text, rules) if rules else None)}


@router.get("/quota")
def get_quota(who: str = Depends(owner), db: Session = Depends(get_db)):
    used = quota.used(db, who)
    return {"limit": limit(who), "used": used, "left": max(0, limit(who) - used)}


@router.post("/coach")
def coach(body: CoachIn, who: str = Depends(owner), db: Session = Depends(get_db), rules: dict | None = Depends(style.current_rules)):
    key = meter.cache_key("coach", body.doc_type, body.chapter_key, body.text, rules)
    hit = meter.cache_get(db, who, key)
    if hit is not None:  # teks sama persis: tanpa memanggil LLM dan tanpa memotong kuota
        meter.record_hit(db, who, "coach")
        return {"comments": hit, "left": limit(who) - quota.used(db, who), "cached": True}
    meter.check_budget(db)
    n = quota.take(db, who, limit(who))
    if n is None:
        raise HTTPException(429, "Kuota bimbingan hari ini habis. Kembali besok atau upgrade.")
    try:
        with meter.call("coach") as acc:
            comments = llm.coach(body.text, body.doc_type, body.chapter_key, rules)
    except llm.GuardError as e:
        quota.refund(db, who)
        raise HTTPException(422, str(e))
    except (httpx.HTTPError, llm.ProviderError) as e:
        obs.llm_error("coach", e)
        quota.refund(db, who)
        raise HTTPException(502, "Layanan AI sedang sibuk. Kuotamu tidak terpakai.")
    meter.record(db, who, "coach", acc)
    meter.cache_put(db, who, "coach", key, comments)
    return {"comments": comments, "left": limit(who) - n}


@router.get("/drafts/{doc_type}/{chapter_key}")
def get_draft(doc_type: str, chapter_key: str, who: str = Depends(owner), db: Session = Depends(get_db)):
    _valid_chapter(doc_type, chapter_key)
    d = db.scalar(select(Draft).where(Draft.owner == who, Draft.doc_type == doc_type, Draft.chapter_key == chapter_key))
    return {"content": d.content if d else ""}


@router.put("/drafts/{doc_type}/{chapter_key}")
def put_draft(doc_type: str, chapter_key: str, body: DraftIn, who: str = Depends(owner), db: Session = Depends(get_db)):
    _valid_chapter(doc_type, chapter_key)
    d = db.scalar(select(Draft).where(Draft.owner == who, Draft.doc_type == doc_type, Draft.chapter_key == chapter_key))
    if d:
        d.content = body.content
    else:
        d = Draft(owner=who, doc_type=doc_type, chapter_key=chapter_key, content=body.content)
        db.add(d)
    db.flush()
    revisions.snapshot(db, d)  # riwayat versi (ikut transaksi yang sama dengan simpan draf)
    db.commit()
    return {"ok": True}
