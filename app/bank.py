"""Bank pertanyaan penguji per kampus/jurusan (kurasi dosen & admin). Mode Sidang memakainya sebagai kumpulan
pilihan: AI memilih yang paling relevan dengan tulisan mahasiswa lalu boleh memparafrasenya; AI tidak mengarang
pertanyaan baru selama bank untuk kampus mahasiswa itu masih berisi. Tanpa bank, Mode Sidang bekerja seperti sebelumnya."""
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .auth import current_admin
from .campus import current_dosen
from .db import get_db
from .models import ExamQuestion, Institution, Membership, StylePref, StyleTemplate, User

router = APIRouter(prefix="/api")
MAX_PER_INSTITUTION = 300
MAX_POOL = 40
CTRL = re.compile(r"[\x00-\x1f\x7f]")


class QIn(BaseModel):
    institution_id: int
    mode: Literal["pkl", "sempro", "skripsi"] | None = None  # kosong = semua jenis sidang
    major: str | None = Field(None, max_length=160)  # kosong = semua jurusan; cocokkan dengan nama jurusan pada gaya selingkung
    question: str = Field(min_length=10, max_length=400)

    @field_validator("question")
    @classmethod
    def _q(cls, v: str) -> str:
        v = " ".join(CTRL.sub(" ", v).split())
        if len(v) < 10:
            raise ValueError("pertanyaan terlalu pendek")
        return v

    @field_validator("major")
    @classmethod
    def _m(cls, v: str | None) -> str | None:
        v = " ".join(CTRL.sub(" ", v or "").split())
        return v or None


def _out(q: ExamQuestion, inst: str | None = None) -> dict:
    return {"id": q.id, "institution_id": q.institution_id, "institution": inst, "mode": q.mode, "major": q.major,
            "question": q.question, "created_at": q.created_at.isoformat()}


def _add(db: Session, b: QIn, by: User) -> ExamQuestion:
    if not db.get(Institution, b.institution_id):
        raise HTTPException(404, "Kampus tidak ditemukan")
    if (db.scalar(select(func.count(ExamQuestion.id)).where(ExamQuestion.institution_id == b.institution_id)) or 0) >= MAX_PER_INSTITUTION:
        raise HTTPException(400, f"Bank pertanyaan kampus ini sudah penuh ({MAX_PER_INSTITUTION}). Hapus yang tidak terpakai dulu.")
    dup = db.scalar(select(ExamQuestion.id).where(ExamQuestion.institution_id == b.institution_id, ExamQuestion.mode.is_(b.mode) if b.mode is None else ExamQuestion.mode == b.mode,
                                                  ExamQuestion.major.is_(None) if b.major is None else ExamQuestion.major == b.major,
                                                  func.lower(ExamQuestion.question) == b.question.lower()))
    if dup:
        raise HTTPException(409, "Pertanyaan yang sama sudah ada di bank.")
    q = ExamQuestion(institution_id=b.institution_id, mode=b.mode, major=b.major, question=b.question, created_by=by.id)
    db.add(q)
    db.commit()
    return q


def student_major(db: Session, u: User) -> str | None:
    """Jurusan mahasiswa = jurusan pada gaya selingkung yang ia pilih (profil jurusan belum ada di aplikasi)."""
    return db.scalar(select(StyleTemplate.major).join(StylePref, StylePref.template_id == StyleTemplate.id).where(StylePref.user_id == u.id))


def pool_for(db: Session, u: User, mode: str) -> list[str]:
    """Pertanyaan bank yang berlaku untuk mahasiswa ini (kampusnya, jenis sidang ini, jurusannya atau umum)."""
    inst = db.scalars(select(Membership.institution_id).where(Membership.user_id == u.id, Membership.role == "mahasiswa")).all()
    if not inst:
        return []
    major = student_major(db, u)
    mj = ExamQuestion.major.is_(None) if not major else or_(ExamQuestion.major.is_(None), func.lower(ExamQuestion.major) == major.lower())
    q = (select(ExamQuestion.question).where(ExamQuestion.institution_id.in_(inst), or_(ExamQuestion.mode.is_(None), ExamQuestion.mode == mode), mj)
         .order_by(ExamQuestion.id).limit(MAX_POOL))
    return list(db.scalars(q))


# ---------- Dosen ----------
def _my_institutions(db: Session, u: User) -> set[int]:
    return set(db.scalars(select(Membership.institution_id).where(Membership.user_id == u.id, Membership.role == "dosen")))


@router.get("/dosen/questions")
def my_questions(u: User = Depends(current_dosen), db: Session = Depends(get_db)):
    ids = _my_institutions(db, u)
    rows = db.execute(select(ExamQuestion, Institution.name).join(Institution, Institution.id == ExamQuestion.institution_id)
                      .where(ExamQuestion.institution_id.in_(ids)).order_by(ExamQuestion.id.desc())).all()
    return [_out(q, n) for q, n in rows]


@router.post("/dosen/questions")
def add_my_question(b: QIn, u: User = Depends(current_dosen), db: Session = Depends(get_db)):
    if b.institution_id not in _my_institutions(db, u):
        raise HTTPException(403, "Kamu bukan dosen di kampus ini")
    return _out(_add(db, b, u))


@router.delete("/dosen/questions/{qid}")
def delete_my_question(qid: int, u: User = Depends(current_dosen), db: Session = Depends(get_db)):
    q = db.get(ExamQuestion, qid)
    if not q or q.institution_id not in _my_institutions(db, u):
        raise HTTPException(404, "Pertanyaan tidak ditemukan")
    db.delete(q)
    db.commit()
    return {"ok": True}


# ---------- Admin ----------
admin = [Depends(current_admin)]


@router.get("/admin/questions", dependencies=admin)
def admin_list(institution_id: int | None = None, db: Session = Depends(get_db)):
    q = select(ExamQuestion, Institution.name).join(Institution, Institution.id == ExamQuestion.institution_id).order_by(ExamQuestion.id.desc()).limit(500)
    if institution_id:
        q = q.where(ExamQuestion.institution_id == institution_id)
    return [_out(x, n) for x, n in db.execute(q)]


@router.post("/admin/questions")
def admin_add(b: QIn, a: User = Depends(current_admin), db: Session = Depends(get_db)):
    return _out(_add(db, b, a))


@router.delete("/admin/questions/{qid}", dependencies=admin)
def admin_delete(qid: int, db: Session = Depends(get_db)):
    q = db.get(ExamQuestion, qid)
    if not q:
        raise HTTPException(404, "Pertanyaan tidak ditemukan")
    db.delete(q)
    db.commit()
    return {"ok": True}
