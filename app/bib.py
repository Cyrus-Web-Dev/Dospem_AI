"""Daftar pustaka pribadi: simpan, ambil metadata dari DOI (Crossref), format APA/IEEE, dan periksa sitasi."""
import html
import json
import re
from typing import Literal
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import refs, scholar
from .auth import current_user
from .config import settings
from .db import get_db
from .models import BibEntry, Draft, Example, User
from .roadmap import ROADMAP

router = APIRouter(prefix="/api")
MAX_ENTRIES = 500
FIELDS = ("kind", "year", "title", "venue", "volume", "issue", "pages", "publisher", "doi", "url")
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")


def norm_doi(s: str | None) -> str | None:
    s = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", (s or "").strip(), flags=re.I).lower()
    return s or None


class BibIn(BaseModel):
    kind: Literal["jurnal", "buku", "web", "lain"] = "jurnal"
    authors: list[str] = Field(default_factory=list, max_length=40)
    year: int | None = Field(None, ge=1000, le=2100)
    title: str = Field(min_length=2, max_length=500)
    venue: str | None = Field(None, max_length=300)
    volume: str | None = Field(None, max_length=20)
    issue: str | None = Field(None, max_length=20)
    pages: str | None = Field(None, max_length=30)
    publisher: str | None = Field(None, max_length=200)
    doi: str | None = Field(None, max_length=200)
    url: str | None = Field(None, max_length=500)

    @field_validator("authors")
    @classmethod
    def _authors(cls, v):
        v = [" ".join(a.split()) for a in v if a and a.strip()]
        if any(len(a) > 120 for a in v):
            raise ValueError("nama penulis terlalu panjang")
        return v

    @field_validator("doi")
    @classmethod
    def _doi(cls, v):
        v = norm_doi(v)
        if v and not DOI_RE.match(v):
            raise ValueError("format DOI tidak dikenal (contoh: 10.1234/abcd)")
        return v

    @field_validator("url")
    @classmethod
    def _url(cls, v):
        if v and not re.match(r"^https?://", v.strip(), re.I):
            raise ValueError("URL harus diawali http:// atau https://")
        return v.strip() if v else None

    @field_validator("title", "venue", "volume", "issue", "pages", "publisher")
    @classmethod
    def _clean(cls, v):
        return re.sub(r"[\x00-\x1f]", " ", v).strip() if isinstance(v, str) else v


def _dict(e: BibEntry) -> dict:
    return {"id": e.id, "authors": json.loads(e.authors or "[]"), **{k: getattr(e, k) for k in FIELDS}}


def _out(e: BibEntry) -> dict:
    d = _dict(e)
    return {**d, "apa": refs.apa(d), "ieee": refs.ieee(d)}


def _mine(db: Session, u: User, rid: int) -> BibEntry:
    e = db.get(BibEntry, rid)
    if not e or e.user_id != u.id:
        raise HTTPException(404, "Pustaka tidak ditemukan")
    return e


@router.get("/refs")
def list_refs(u: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"items": [_out(e) for e in db.scalars(select(BibEntry).where(BibEntry.user_id == u.id).order_by(BibEntry.id))]}


@router.post("/refs")
def add_ref(b: BibIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if db.scalar(select(func.count()).select_from(BibEntry).where(BibEntry.user_id == u.id)) >= MAX_ENTRIES:
        raise HTTPException(409, f"Daftar pustaka penuh (maks. {MAX_ENTRIES}).")
    e = BibEntry(user_id=u.id, authors=json.dumps(b.authors), **{k: getattr(b, k) for k in FIELDS})
    db.add(e)
    db.commit()
    return _out(e)


@router.put("/refs/{rid}")
def edit_ref(rid: int, b: BibIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    e = _mine(db, u, rid)
    e.authors = json.dumps(b.authors)
    for k in FIELDS:
        setattr(e, k, getattr(b, k))
    db.commit()
    return _out(e)


@router.delete("/refs/{rid}")
def del_ref(rid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_mine(db, u, rid))
    db.commit()
    return {"ok": True}


_KIND = {"journal-article": "jurnal", "book": "buku", "monograph": "buku", "edited-book": "buku", "reference-book": "buku"}
_TAG = re.compile(r"<[^>]+>")


def _t(s) -> str | None:
    return " ".join(html.unescape(_TAG.sub("", str(s))).split()) or None if s else None


def norm_crossref_ref(m: dict) -> dict:
    au = [f"{a['family']}, {a['given']}" if a.get("family") and a.get("given") else (a.get("family") or a.get("name") or "") for a in m.get("author", []) if isinstance(a, dict)]
    parts = ((m.get("issued") or m.get("published") or {}).get("date-parts") or [[None]])[0] or [None]
    return {"kind": _KIND.get(m.get("type"), "lain"), "authors": [a for a in au if a][:40], "year": parts[0], "title": _t((m.get("title") or [""])[0]) or "",
            "venue": _t((m.get("container-title") or [None])[0]), "volume": _t(m.get("volume")), "issue": _t(m.get("issue")), "pages": _t(m.get("page")),
            "publisher": _t(m.get("publisher")), "doi": norm_doi(m.get("DOI")), "url": m.get("URL")}


@router.get("/refs/lookup")
def lookup_doi(doi: str = Query(min_length=7, max_length=200), u: User = Depends(current_user)):
    """Ambil metadata dari Crossref (belum disimpan; pengguna memeriksa dulu lalu menyimpan)."""
    d = norm_doi(doi)
    if not d or not DOI_RE.match(d):
        raise HTTPException(422, "Format DOI tidak dikenal (contoh: 10.1234/abcd)")
    try:
        r = httpx.get("https://api.crossref.org/works/" + quote(d, safe="/"), params={"mailto": settings.contact_email}, headers=scholar.HEADERS, timeout=15)
        if r.status_code == 404:
            raise HTTPException(404, "DOI tidak ditemukan di Crossref")
        r.raise_for_status()
        return norm_crossref_ref(r.json()["message"])
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(502, "Crossref sedang tidak dapat dihubungi. Isi manual atau coba lagi nanti.")


@router.post("/refs/from-example/{eid}")
def from_example(eid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    x = db.get(Example, eid)
    if not x:
        raise HTTPException(404, "Contoh tidak ditemukan")
    return add_ref(BibIn(kind="jurnal" if x.venue else "lain", authors=json.loads(x.authors or "[]"), year=x.year, title=x.title, venue=x.venue,
                         doi=x.doi, url=x.url if (x.url or "").lower().startswith("http") else None), u, db)


class CheckIn(BaseModel):
    style: Literal["apa", "ieee"] = "apa"
    doc_type: str = "skripsi"
    text: str | None = Field(None, max_length=200000)


@router.post("/refs/check")
def check_refs(b: CheckIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    """Periksa sitasi di teks yang dikirim (satu bab) atau, tanpa `text`, di SELURUH draf jenis tugas itu."""
    entries = [_dict(e) for e in db.scalars(select(BibEntry).where(BibEntry.user_id == u.id).order_by(BibEntry.id))]
    if b.text is not None:
        text, whole = b.text, False
    else:
        if b.doc_type not in ROADMAP:
            raise HTTPException(404, "Jenis tugas tidak dikenal")
        got = {k: c for k, c in db.execute(select(Draft.chapter_key, Draft.content).where(Draft.owner == f"u{u.id}", Draft.doc_type == b.doc_type))}
        text, whole = "\n".join(got.get(c["key"], "") for c in ROADMAP[b.doc_type]), True
    r = refs.check(text, entries, b.style, whole)
    r["uncited"] = None if r["uncited"] is None else [{"id": i, "text": refs.plain(refs.apa(next(e for e in entries if e["id"] == i)))} for i in r["uncited"]]
    return {**r, "total": len(entries), "scope": "semua draf" if whole else "bab ini"}
