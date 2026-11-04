"""Hak data pengguna (UU PDP): ekspor data pribadi, penghapusan akun, dan transparansi akses dosen.
Penghapusan = anonimisasi: semua data pribadi dan tulisan dibuang; hanya catatan pembayaran (kewajiban pembukuan) yang
dipertahankan, terhubung ke baris pengguna yang sudah dikosongkan."""
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from . import obs, quota
from .auth import _is_dosen, current_user, is_admin, plan_of, verify_pw
from .config import settings
from .db import get_db
from .models import (AIUsage, Base, LLMCache, BibEntry, Bookmark, Draft, DraftAccess, DraftRevision, ExamQuestion, Example, FeedbackPreset, Institution, Invite,
                     Membership, Payment, SidangSession, SidangTurn, StylePref, StyleTemplate, Supervision, SupervisorNote, User)
from .ratelimit import redis_client

router = APIRouter(prefix="/api")
KEEP_TABLES = {"users", "payments"}  # payments: dipertahankan untuk pembukuan
ACCESS_COLLAPSE = timedelta(minutes=10)


@router.get("/public-config")
def public_config():
    """Info publik non-rahasia untuk halaman legal dan form daftar."""
    return {"contact_email": settings.contact_email, "terms_version": settings.terms_version,
            "require_terms_consent": settings.require_terms_consent, "access_log_days": settings.access_log_days}


# ---------- log akses dosen ----------
def log_access(db: Session, dosen_id: int, mahasiswa_id: int, doc_type: str, chapter_key: str) -> None:
    """Catat dosen membuka draf (tanpa commit). Pembukaan berulang pada bab yang sama dalam 10 menit digabung."""
    now = datetime.utcnow()
    last = db.scalar(select(DraftAccess).where(DraftAccess.dosen_id == dosen_id, DraftAccess.mahasiswa_id == mahasiswa_id, DraftAccess.doc_type == doc_type,
                                               DraftAccess.chapter_key == chapter_key).order_by(DraftAccess.id.desc()).limit(1))
    if last and now - last.at < ACCESS_COLLAPSE:
        last.at = now
    else:
        db.add(DraftAccess(dosen_id=dosen_id, mahasiswa_id=mahasiswa_id, doc_type=doc_type, chapter_key=chapter_key, at=now))
    db.execute(delete(DraftAccess).where(DraftAccess.mahasiswa_id == mahasiswa_id, DraftAccess.at < now - timedelta(days=settings.access_log_days)))


@router.get("/account/access-log")
def access_log(u: User = Depends(current_user), db: Session = Depends(get_db)):
    """Kapan dosen membuka drafmu (100 terbaru)."""
    rows = db.execute(select(DraftAccess, User).join(User, User.id == DraftAccess.dosen_id).where(DraftAccess.mahasiswa_id == u.id)
                      .order_by(DraftAccess.at.desc()).limit(100)).all()
    return [{"dosen": d.name or d.email, "doc_type": a.doc_type, "chapter_key": a.chapter_key, "at": a.at.isoformat()} for a, d in rows]


# ---------- ekspor ----------
def _iso(d):
    return d.isoformat() if d else None


def build_export(db: Session, u: User) -> dict:
    owner = f"u{u.id}"
    drafts = db.scalars(select(Draft).where(Draft.owner == owner).order_by(Draft.doc_type, Draft.id)).all()
    revs: dict[int, list] = {}
    for r in db.scalars(select(DraftRevision).where(DraftRevision.draft_id.in_([d.id for d in drafts])).order_by(DraftRevision.id)) if drafts else []:
        revs.setdefault(r.draft_id, []).append({"saved_at": _iso(r.created_at), "words": r.words, "content": r.content})
    sups = db.execute(select(Supervision, User, Institution).join(User, User.id == Supervision.dosen_id).join(Institution, Institution.id == Supervision.institution_id)
                      .where(Supervision.mahasiswa_id == u.id)).all()
    notes = db.execute(select(SupervisorNote, User).join(Supervision, Supervision.id == SupervisorNote.supervision_id).join(User, User.id == Supervision.dosen_id)
                       .where(Supervision.mahasiswa_id == u.id).order_by(SupervisorNote.id)).all()
    sessions = db.scalars(select(SidangSession).where(SidangSession.user_id == u.id).order_by(SidangSession.id)).all()
    turns: dict[int, list] = {}
    for t in db.scalars(select(SidangTurn).where(SidangTurn.session_id.in_([s.id for s in sessions])).order_by(SidangTurn.session_id, SidangTurn.idx)) if sessions else []:
        turns.setdefault(t.session_id, []).append({"idx": t.idx, "question": t.question, "answer": t.answer, "feedback": json.loads(t.feedback) if t.feedback else None})
    style = db.scalar(select(StyleTemplate.name).join(StylePref, StylePref.template_id == StyleTemplate.id).where(StylePref.user_id == u.id))
    out = {
        "diekspor_pada": _iso(datetime.utcnow()),
        "catatan": "Salinan data pribadi yang disimpan Dospem untuk akunmu. Riwayat pembayaran tetap disimpan walau akun dihapus (kewajiban pembukuan).",
        "profil": {"email": u.email, "nama": u.name, "paket": plan_of(u), "premium_hingga": _iso(u.premium_until), "terdaftar": _iso(u.created_at),
                   "setuju_syarat": _iso(u.terms_accepted_at), "versi_syarat": u.terms_version, "gaya_selingkung": style},
        "draf": [{"jenis": d.doc_type, "bab": d.chapter_key, "isi": d.content, "diubah": _iso(d.updated_at), "riwayat_versi": revs.get(d.id, [])} for d in drafts],
        "daftar_pustaka": [{"jenis": e.kind, "penulis": json.loads(e.authors or "[]"), "tahun": e.year, "judul": e.title, "sumber": e.venue, "volume": e.volume,
                            "terbitan": e.issue, "halaman": e.pages, "penerbit": e.publisher, "doi": e.doi, "url": e.url}
                           for e in db.scalars(select(BibEntry).where(BibEntry.user_id == u.id).order_by(BibEntry.id))],
        "contoh_tersimpan": [{"judul": t, "doi": doi, "url": url} for t, doi, url in db.execute(
            select(Example.title, Example.doi, Example.url).join(Bookmark, Bookmark.example_id == Example.id).where(Bookmark.user_id == u.id))],
        "dosen_pembimbing": [{"dosen": d.name or d.email, "kampus": i.name, "status": s.status, "disetujui": _iso(s.approved_at)} for s, d, i in sups],
        "catatan_dosen": [{"dosen": d.name or d.email, "jenis": n.kind, "jenis_tugas": n.doc_type, "bab": n.chapter_key, "tanggal_bimbingan": _iso(n.session_date),
                           "isi": n.body, "dikirim": _iso(n.created_at)} for n, d in notes],
        "latihan_sidang": [{"mode": s.mode, "gaya": s.persona, "status": s.status, "dibuat": _iso(s.created_at), "ringkasan": json.loads(s.summary) if s.summary else None,
                            "giliran": turns.get(s.id, [])} for s in sessions],
        "akses_dosen_ke_draf": access_log(u, db),
        "pembayaran": [{"order": p.order_id, "paket": p.plan_key, "jumlah": p.amount, "penyedia": p.provider, "status": p.status, "dibuat": _iso(p.created_at),
                        "dibayar": _iso(p.paid_at)} for p in db.scalars(select(Payment).where(Payment.user_id == u.id).order_by(Payment.id))],
    }
    if _is_dosen(u):
        out["sebagai_dosen"] = {
            "kampus": [i.name for i in db.scalars(select(Institution).join(Membership, Membership.institution_id == Institution.id).where(Membership.user_id == u.id, Membership.role == "dosen"))],
            "frasa_kustom": [p.text for p in db.scalars(select(FeedbackPreset).where(FeedbackPreset.dosen_id == u.id).order_by(FeedbackPreset.id))],
            "pertanyaan_bank_dibuat": [{"pertanyaan": q.question, "mode": q.mode, "jurusan": q.major} for q in db.scalars(select(ExamQuestion).where(ExamQuestion.created_by == u.id))],
            "catatan": "Data mahasiswa bimbinganmu tidak termasuk karena milik mahasiswa masing-masing.",
        }
    return out


@router.get("/account/export")
def export_data(u: User = Depends(current_user), db: Session = Depends(get_db)):
    body = json.dumps(build_export(db, u), ensure_ascii=False, indent=2)
    return Response(body, media_type="application/json", headers={"Content-Disposition": 'attachment; filename="dospem-data-saya.json"'})


# ---------- hapus akun ----------
class DeleteIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


def purge(db: Session, u: User) -> None:
    """Buang semua data pribadi pengguna lalu kosongkan baris pengguna. Pemanggil yang commit."""
    uid, owner = u.id, f"u{u.id}"
    # data tanpa FK ke users (kunci teks) dan anak dari anak, dihapus lebih dulu
    db.execute(delete(DraftRevision).where(DraftRevision.draft_id.in_(select(Draft.id).where(Draft.owner == owner))))
    db.execute(delete(Draft).where(Draft.owner == owner))
    db.execute(delete(SupervisorNote).where(SupervisorNote.supervision_id.in_(select(Supervision.id).where(or_(Supervision.dosen_id == uid, Supervision.mahasiswa_id == uid)))))
    db.execute(delete(SidangTurn).where(SidangTurn.session_id.in_(select(SidangSession.id).where(SidangSession.user_id == uid))))
    keys = [quota._k(owner, k) for k in ("coach", "analisis", "sidang")]
    db.execute(delete(AIUsage).where(AIUsage.owner.in_(keys)))
    db.execute(delete(LLMCache).where(LLMCache.owner == owner))
    r = redis_client()
    if r:
        try:
            r.delete(*[f"q:{k}:{quota.today()}" for k in keys])
        except Exception:  # kuota Redis kedaluwarsa sendiri dalam 2 hari
            obs.redis_down("purge")
    # semua kolom yang merujuk users.id ditelusuri otomatis, jadi tabel baru tidak terlewat
    for t in Base.metadata.sorted_tables:
        if t.name in KEEP_TABLES:
            continue
        for fk in t.foreign_keys:
            if fk.column.table.name == "users" and fk.column.name == "id":
                if fk.ondelete == "SET NULL":
                    db.execute(update(t).where(fk.parent == uid).values({fk.parent.name: None}))
                else:
                    db.execute(delete(t).where(fk.parent == uid))
    u.email = u.name = u.password_hash = u.university = u.major = None
    u.premium_until = u.locked_until = u.pw_changed_at = u.terms_accepted_at = None
    u.terms_version, u.failed_logins, u.deleted_at = None, 0, datetime.utcnow()


@router.post("/account/delete")
def delete_account(b: DeleteIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if is_admin(u):
        raise HTTPException(400, "Akun admin tidak bisa dihapus dari sini. Hapus dulu dari daftar ADMIN_EMAILS.")
    if not verify_pw(b.password, u.password_hash):
        raise HTTPException(403, "Kata sandi salah")
    purge(db, u)
    db.commit()
    obs.event("account_deleted")
    return {"ok": True}
