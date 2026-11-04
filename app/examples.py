import json
import re

from sqlalchemy.exc import IntegrityError

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import scholar
from .auth import current_user, current_user_opt
from .db import get_db
from .models import Bookmark, Example, User

router = APIRouter(prefix="/api")
FIELDS = ("source", "external_id", "doi", "title", "year", "venue", "url", "license")


def upsert(db: Session, it: dict, update: bool = False) -> tuple[Example | None, bool]:
    """Simpan/ambil Example. Aman terhadap dua permintaan serentak (savepoint). Mengembalikan (objek, baru?)."""
    it = scholar.clip(it)
    find = select(Example).where(Example.source == it["source"], Example.external_id == it["external_id"])
    ex = db.scalar(find)
    if ex:
        if update:
            for k in FIELDS[2:]:
                setattr(ex, k, it[k])
            ex.authors, ex.abstract = json.dumps(it["authors"]), it["abstract"]
        return ex, False
    try:
        with db.begin_nested():
            ex = Example(**{k: it[k] for k in FIELDS}, authors=json.dumps(it["authors"]), abstract=it["abstract"])
            db.add(ex)
            db.flush()
        return ex, True
    except IntegrityError:
        return db.scalar(find), False


def _like(t: str) -> str:
    return t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def local_search(db: Session, q: str, limit: int = 8) -> list[Example]:
    """Cari di hasil panen OAI (jurnal OJS Indonesia): semua kata harus ada di judul."""
    toks = [t for t in re.split(r"\s+", q) if len(t) >= 3][:5]
    if not toks:
        return []
    stmt = (select(Example).where(Example.source == "oai", *[Example.title.ilike(f"%{_like(t)}%", escape="\\") for t in toks])
            .order_by(Example.year.desc().nullslast(), Example.id.desc()).limit(limit))
    return list(db.scalars(stmt))


def _dump(ex: Example, marked: set) -> dict:
    op = scholar.is_open(ex.license)
    return {"id": ex.id, "source": ex.source, "title": ex.title, "authors": json.loads(ex.authors), "year": ex.year,
            "venue": ex.venue, "doi": ex.doi, "url": ex.url, "license": ex.license, "is_open": op,
            "abstract": ex.abstract if op else None, "annotation": ex.annotation, "bookmarked": ex.id in marked}


def _marked(db: Session, u: User | None) -> set:
    return set(db.scalars(select(Bookmark.example_id).where(Bookmark.user_id == u.id))) if u else set()


@router.get("/examples/curated")
def curated(db: Session = Depends(get_db), u: User | None = Depends(current_user_opt)):
    rows = db.scalars(select(Example).where(Example.annotation.is_not(None)).order_by(Example.id.desc()).limit(30))
    marked = _marked(db, u)
    return {"results": [_dump(e, marked) for e in rows]}


@router.get("/examples/sources")
def list_sources():
    return [{"key": k, "label": l} for k, l, _ in scholar.sources()] + [{"key": "oai", "label": "Jurnal OJS Indonesia (hasil panen)"}]


@router.get("/examples/links")
def link_outs(q: str = Query(min_length=3, max_length=200)):
    return {"links": scholar.links(q)}


@router.get("/examples/search")
def search(q: str = Query(min_length=3, max_length=200), source: str = "all", lang: str = "", oa_only: bool = True,
          db: Session = Depends(get_db), u: User | None = Depends(current_user_opt)):
    if source not in {"all", "oai", *(k for k, _, _ in scholar.sources())}:
        raise HTTPException(422, "Sumber tidak dikenal")
    items, warn = scholar.search(q, source, lang, oa_only) if source != "oai" else ([], [])
    out, dois = [], set()
    if source in ("all", "oai"):
        for ex in local_search(db, q):
            out.append(ex)
            dois.add(ex.doi)
    for it in items:
        if it["doi"] and it["doi"] in dois:
            continue
        ex, _ = upsert(db, it)
        if ex:
            out.append(ex)
    db.commit()
    marked = _marked(db, u)
    return {"results": [_dump(e, marked) for e in out], "warnings": warn}


@router.get("/bookmarks")
def bookmarks(db: Session = Depends(get_db), u: User = Depends(current_user)):
    rows = db.scalars(select(Example).join(Bookmark, Bookmark.example_id == Example.id)
                      .where(Bookmark.user_id == u.id).order_by(Bookmark.id.desc()))
    marked = _marked(db, u)
    return {"results": [_dump(e, marked) for e in rows]}


@router.post("/bookmarks/{eid}")
def add_bookmark(eid: int, db: Session = Depends(get_db), u: User = Depends(current_user)):
    if not db.get(Example, eid):
        raise HTTPException(404, "Contoh tidak ditemukan")
    if not db.scalar(select(Bookmark).where(Bookmark.user_id == u.id, Bookmark.example_id == eid)):
        db.add(Bookmark(user_id=u.id, example_id=eid))
        db.commit()
    return {"ok": True}


@router.delete("/bookmarks/{eid}")
def del_bookmark(eid: int, db: Session = Depends(get_db), u: User = Depends(current_user)):
    b = db.scalar(select(Bookmark).where(Bookmark.user_id == u.id, Bookmark.example_id == eid))
    if b:
        db.delete(b)
        db.commit()
    return {"ok": True}
