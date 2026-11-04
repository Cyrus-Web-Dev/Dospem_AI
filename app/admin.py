import json
import uuid
import xml.etree.ElementTree as StdET

import httpx

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import current_admin
from .db import get_db
from . import oai
from .examples import _dump, upsert
from .models import Example, Payment, User

router = APIRouter(prefix="/api/admin", dependencies=[Depends(current_admin)])


@router.get("/examples")
def list_examples(q: str = "", show: str = "none", offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    stmt = select(Example)
    if q:
        stmt = stmt.where(Example.title.ilike(f"%{q}%"))
    if show == "none":
        stmt = stmt.where(Example.annotation.is_(None))
    elif show == "done":
        stmt = stmt.where(Example.annotation.is_not(None))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Example.id.desc()).offset(offset).limit(20))
    return {"total": total, "items": [{**_dump(e, set()), "abstract": None} for e in rows]}


class Ann(BaseModel):
    annotation: str | None = Field(None, max_length=2000)


@router.put("/examples/{eid}")
def annotate(eid: int, b: Ann, db: Session = Depends(get_db)):
    ex = db.get(Example, eid)
    if not ex:
        raise HTTPException(404, "Contoh tidak ditemukan")
    ex.annotation = (b.annotation or "").strip() or None
    db.commit()
    return {"ok": True}


class Manual(Ann):
    title: str = Field(min_length=3, max_length=500)
    authors: list[str] = []
    year: int | None = None
    venue: str | None = Field(None, max_length=300)
    url: str | None = Field(None, max_length=500)
    doi: str | None = Field(None, max_length=200)
    license: str | None = Field(None, max_length=200)


@router.post("/examples")
def add_manual(b: Manual, db: Session = Depends(get_db)):
    ex = Example(source="manual", external_id=uuid.uuid4().hex, title=b.title, authors=json.dumps(b.authors[:10]),
                 year=b.year, venue=b.venue, url=b.url, doi=(b.doi or "").lower() or None, license=b.license,
                 annotation=(b.annotation or "").strip() or None)
    db.add(ex)
    db.commit()
    return {"id": ex.id}


class Harvest(BaseModel):
    url: str = Field(min_length=8, max_length=300)
    max_records: int = Field(200, ge=1, le=500)


@router.post("/oai/harvest")
def oai_harvest(b: Harvest, db: Session = Depends(get_db)):
    """Panen metadata dari endpoint OAI-PMH jurnal OJS, mis. https://jurnal.kampus.ac.id/index.php/abc/oai"""
    try:
        recs = oai.harvest(b.url.strip(), b.max_records)
    except StdET.ParseError:
        raise HTTPException(422, "Respons bukan XML OAI-PMH yang valid. Pastikan URL berakhir dengan /oai")
    except ValueError as e:
        raise HTTPException(422, str(e))
    except httpx.HTTPError:
        raise HTTPException(502, "Server OAI tidak dapat dihubungi atau menolak permintaan (coba URL https:// final)")
    added = 0
    for it in recs:
        _, new = upsert(db, it, update=True)
        added += new
    db.commit()
    return {"found": len(recs), "added": added, "updated": len(recs) - added}


@router.get("/payments")
def payments(db: Session = Depends(get_db)):
    rows = db.execute(select(Payment, User.email).join(User, User.id == Payment.user_id).order_by(Payment.id.desc()).limit(50))
    return [{"order_id": p.order_id, "email": e, "plan": p.plan_key, "amount": p.amount, "provider": p.provider,
             "status": p.status, "created_at": p.created_at.isoformat(), "paid_at": p.paid_at.isoformat() if p.paid_at else None}
            for p, e in rows]
