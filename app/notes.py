"""Catatan dosen -> mahasiswa (kanal resmi, terpisah dari draf dan komentar AI) + lembar bimbingan (logbook).
Dosen hanya bisa menulis/membaca catatan untuk mahasiswa yang MASIH memberi izin (supervisi 'approved').
Mahasiswa selalu bisa membaca catatan yang ditujukan kepadanya, juga setelah izin dicabut (itu data miliknya)."""
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import current_user
from .campus import current_dosen
from .db import get_db
from .models import FeedbackPreset, Supervision, SupervisorNote, User
from .quota import today
from .roadmap import ROADMAP

router = APIRouter(prefix="/api")

# Frasa umpan balik yang sering dipakai dosen: tempel cepat lalu sesuaikan. Bukan teks yang ditulis AI untuk mahasiswa.
PRESETS = [
    {"key": "gap", "text": "Perjelas celah penelitiannya: apa yang belum dijawab oleh penelitian terdahulu?"},
    {"key": "metode", "text": "Metode belum dijustifikasi. Jelaskan mengapa pendekatan ini dipilih dibanding alternatifnya."},
    {"key": "rumusan", "text": "Rumusan masalah belum selaras dengan tujuan. Cek apakah setiap tujuan menjawab satu rumusan."},
    {"key": "rujukan", "text": "Klaim ini perlu rujukan yang jelas dan mutakhir."},
    {"key": "data", "text": "Sertakan data pendukung beserta sumbernya."},
    {"key": "alur", "text": "Alur antarparagraf belum runtut. Satu paragraf sebaiknya memuat satu gagasan utama."},
    {"key": "pembahasan", "text": "Pembahasan baru menyebut hasil. Kaitkan dengan teori dan penelitian lain."},
    {"key": "bahasa", "text": "Perbaiki ejaan dan bahasa baku sebelum dikirim ulang."},
    {"key": "revisi", "text": "Silakan revisi sesuai catatan, lalu kirim ulang beserta ringkasan perubahannya."},
    {"key": "lanjut", "text": "Bab ini sudah baik. Lanjutkan ke bab berikutnya."},
]


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    kind: Literal["catatan", "logbook"] = "catatan"
    doc_type: str | None = Field(None, max_length=20)
    chapter_key: str | None = Field(None, max_length=40)
    session_date: date | None = None

    @field_validator("body")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = v.replace("\x00", "").strip()
        if not v:
            raise ValueError("catatan tidak boleh kosong")
        return v

    @model_validator(mode="after")
    def _target(self):
        if self.chapter_key and not self.doc_type:
            raise ValueError("chapter_key butuh doc_type")
        if self.doc_type and self.chapter_key and self.chapter_key not in {c["key"] for c in ROADMAP.get(self.doc_type, [])}:
            raise ValueError("jenis tugas atau bab tidak dikenal")
        if self.doc_type and not self.chapter_key and self.doc_type not in ROADMAP:
            raise ValueError("jenis tugas tidak dikenal")
        return self


def _out(n: SupervisorNote, dosen: str | None = None) -> dict:
    d = {"id": n.id, "kind": n.kind, "doc_type": n.doc_type, "chapter_key": n.chapter_key, "body": n.body,
         "session_date": n.session_date.isoformat() if n.session_date else None,
         "created_at": n.created_at.isoformat(), "read_at": n.read_at.isoformat() if n.read_at else None}
    if dosen is not None:
        d["dosen"] = dosen
    return d


def _approved(db: Session, dosen: User, sid: int) -> Supervision:
    s = db.scalar(select(Supervision).where(Supervision.dosen_id == dosen.id, Supervision.mahasiswa_id == sid, Supervision.status == "approved"))
    if not s:
        raise HTTPException(404, "Mahasiswa tidak ditemukan atau belum memberi izin")
    return s


# ---------- Dosen ----------
MAX_CUSTOM_PRESETS = 30


class PresetIn(BaseModel):
    text: str = Field(min_length=5, max_length=300)

    @field_validator("text")
    @classmethod
    def _t(cls, v: str) -> str:
        v = " ".join(v.replace("\x00", " ").split())
        if len(v) < 5:
            raise ValueError("frasa terlalu pendek")
        return v


@router.get("/dosen/presets")
def presets(u: User = Depends(current_dosen), db: Session = Depends(get_db)):
    """Preset bawaan + frasa kustom milik dosen ini (key 'c<id>', custom=true)."""
    mine = db.scalars(select(FeedbackPreset).where(FeedbackPreset.dosen_id == u.id).order_by(FeedbackPreset.id))
    return [{**p, "custom": False} for p in PRESETS] + [{"key": f"c{p.id}", "text": p.text, "custom": True} for p in mine]


@router.post("/dosen/presets")
def add_preset(b: PresetIn, u: User = Depends(current_dosen), db: Session = Depends(get_db)):
    if (db.scalar(select(func.count(FeedbackPreset.id)).where(FeedbackPreset.dosen_id == u.id)) or 0) >= MAX_CUSTOM_PRESETS:
        raise HTTPException(400, f"Maksimal {MAX_CUSTOM_PRESETS} frasa kustom. Hapus yang tidak terpakai dulu.")
    if db.scalar(select(FeedbackPreset.id).where(FeedbackPreset.dosen_id == u.id, func.lower(FeedbackPreset.text) == b.text.lower())):
        raise HTTPException(409, "Frasa yang sama sudah tersimpan.")
    p = FeedbackPreset(dosen_id=u.id, text=b.text)
    db.add(p)
    db.commit()
    return {"key": f"c{p.id}", "text": p.text, "custom": True}


@router.delete("/dosen/presets/{pid}")
def delete_preset(pid: int, u: User = Depends(current_dosen), db: Session = Depends(get_db)):
    p = db.scalar(select(FeedbackPreset).where(FeedbackPreset.id == pid, FeedbackPreset.dosen_id == u.id))
    if not p:
        raise HTTPException(404, "Frasa tidak ditemukan")
    db.delete(p)
    db.commit()
    return {"ok": True}


@router.post("/dosen/students/{sid}/notes")
def add_note(sid: int, b: NoteIn, u: User = Depends(current_dosen), db: Session = Depends(get_db)):
    s = _approved(db, u, sid)
    n = SupervisorNote(supervision_id=s.id, kind=b.kind, doc_type=b.doc_type, chapter_key=b.chapter_key, body=b.body,
                       session_date=(b.session_date or today()) if b.kind == "logbook" else None)
    db.add(n)
    db.commit()
    return _out(n)


@router.get("/dosen/students/{sid}/notes")
def student_notes(sid: int, u: User = Depends(current_dosen), db: Session = Depends(get_db)):
    s = _approved(db, u, sid)
    return [_out(n) for n in db.scalars(select(SupervisorNote).where(SupervisorNote.supervision_id == s.id).order_by(SupervisorNote.id.desc()).limit(200))]


@router.delete("/dosen/notes/{nid}")
def delete_note(nid: int, u: User = Depends(current_dosen), db: Session = Depends(get_db)):
    n = db.scalar(select(SupervisorNote).join(Supervision, Supervision.id == SupervisorNote.supervision_id)
                  .where(SupervisorNote.id == nid, Supervision.dosen_id == u.id, Supervision.status == "approved"))
    if not n:
        raise HTTPException(404, "Catatan tidak ditemukan")
    db.delete(n)
    db.commit()
    return {"ok": True}


# ---------- Mahasiswa ----------
@router.get("/notes")
def my_notes(doc_type: str | None = None, chapter_key: str | None = None, kind: Literal["catatan", "logbook"] | None = None,
             u: User = Depends(current_user), db: Session = Depends(get_db)):
    q = (select(SupervisorNote, User).join(Supervision, Supervision.id == SupervisorNote.supervision_id)
         .join(User, User.id == Supervision.dosen_id).where(Supervision.mahasiswa_id == u.id))
    if doc_type:
        q = q.where(SupervisorNote.doc_type == doc_type)
    if chapter_key:
        q = q.where(SupervisorNote.chapter_key == chapter_key)
    if kind:
        q = q.where(SupervisorNote.kind == kind)
    rows = db.execute(q.order_by(SupervisorNote.id.desc()).limit(200)).all()
    unread = db.scalar(select(func.count(SupervisorNote.id)).join(Supervision, Supervision.id == SupervisorNote.supervision_id)
                       .where(Supervision.mahasiswa_id == u.id, SupervisorNote.read_at.is_(None))) or 0
    return {"notes": [_out(n, d.name or d.email) for n, d in rows], "unread": unread}


@router.post("/notes/read-all")
def read_all(u: User = Depends(current_user), db: Session = Depends(get_db)):
    now = datetime.utcnow()
    for n in db.scalars(select(SupervisorNote).join(Supervision, Supervision.id == SupervisorNote.supervision_id)
                        .where(Supervision.mahasiswa_id == u.id, SupervisorNote.read_at.is_(None))):
        n.read_at = now
    db.commit()
    return {"ok": True}


@router.post("/notes/{nid}/read")
def read_note(nid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    n = db.scalar(select(SupervisorNote).join(Supervision, Supervision.id == SupervisorNote.supervision_id)
                  .where(SupervisorNote.id == nid, Supervision.mahasiswa_id == u.id))
    if not n:
        raise HTTPException(404, "Catatan tidak ditemukan")
    if not n.read_at:
        n.read_at = datetime.utcnow()
        db.commit()
    return {"ok": True}
