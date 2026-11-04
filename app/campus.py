"""Fase 4 · tahap 1: kampus, dosen, dan dasbor pemantauan. Dosen hanya melihat mahasiswa yang
SECARA EKSPLISIT menyetujui (lewat kode undangan + persetujuan), dan persetujuan bisa dicabut kapan saja."""
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import account, readiness, revisions, style
from .auth import current_admin, current_user
from .config import settings
from .db import get_db
from .models import Draft, DraftRevision, DosenView, Institution, Invite, Membership, Supervision, User
from .roadmap import ROADMAP

router = APIRouter(prefix="/api")
ALPHA = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
admin = [Depends(current_admin)]


# ---------- Admin: kampus & dosen ----------
class InstIn(BaseModel):
    name: str = Field(min_length=3, max_length=160)


class DosenIn(BaseModel):
    email: str = Field(max_length=255)


@router.post("/admin/institutions", dependencies=admin)
def add_institution(b: InstIn, db: Session = Depends(get_db)):
    i = Institution(name=b.name.strip())
    db.add(i)
    db.commit()
    return {"id": i.id}


@router.get("/admin/institutions", dependencies=admin)
def list_institutions(db: Session = Depends(get_db)):
    out = []
    for i in db.scalars(select(Institution).order_by(Institution.id.desc())):
        d = db.execute(select(User.email, User.name).join(Membership, Membership.user_id == User.id)
                       .where(Membership.institution_id == i.id, Membership.role == "dosen"))
        out.append({"id": i.id, "name": i.name, "dosen": [{"email": e, "name": n} for e, n in d]})
    return out


@router.post("/admin/institutions/{iid}/dosen", dependencies=admin)
def add_dosen(iid: int, b: DosenIn, db: Session = Depends(get_db)):
    if not db.get(Institution, iid):
        raise HTTPException(404, "Kampus tidak ditemukan")
    u = db.scalar(select(User).where(User.email == b.email.strip().lower()))
    if not u:
        raise HTTPException(404, "Pengguna belum mendaftar di Dospem")
    if not db.scalar(select(Membership).where(Membership.institution_id == iid, Membership.user_id == u.id, Membership.role == "dosen")):
        db.add(Membership(institution_id=iid, user_id=u.id, role="dosen"))
        db.commit()
    return {"ok": True}


# ---------- Dosen ----------
def current_dosen(u: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
    if not db.scalar(select(Membership.id).where(Membership.user_id == u.id, Membership.role == "dosen")):
        raise HTTPException(403, "Khusus dosen yang didaftarkan admin")
    return u


@router.get("/dosen/me")
def dosen_me(u: User = Depends(current_dosen), db: Session = Depends(get_db)):
    out = []
    for i in db.scalars(select(Institution).join(Membership, Membership.institution_id == Institution.id)
                        .where(Membership.user_id == u.id, Membership.role == "dosen")):
        code = db.scalar(select(Invite.code).where(Invite.dosen_id == u.id, Invite.institution_id == i.id, Invite.active.is_(True)))
        out.append({"institution_id": i.id, "name": i.name, "code": code})
    return out


class InviteIn(BaseModel):
    institution_id: int


@router.post("/dosen/invite")
def new_invite(b: InviteIn, u: User = Depends(current_dosen), db: Session = Depends(get_db)):
    if not db.scalar(select(Membership.id).where(Membership.user_id == u.id, Membership.institution_id == b.institution_id, Membership.role == "dosen")):
        raise HTTPException(403, "Kamu bukan dosen di kampus ini")
    for old in db.scalars(select(Invite).where(Invite.dosen_id == u.id, Invite.institution_id == b.institution_id, Invite.active.is_(True))):
        old.active = False
    code = "".join(secrets.choice(ALPHA) for _ in range(8))
    db.add(Invite(code=code, dosen_id=u.id, institution_id=b.institution_id))
    db.commit()
    return {"code": code}


def _state(words: int) -> str:
    return "belum" if words == 0 else "draf" if words < 200 else "terisi"  # ambang sederhana; bisa dikonfigurasi nanti


@router.get("/dosen/students")
def students(focus: bool = False, u: User = Depends(current_dosen), db: Session = Depends(get_db)):
    """Daftar mahasiswa berizin. `attention` = alasan perlu perhatian (stuck | draf_baru | siap_sidang);
    `focus=true` hanya menampilkan yang punya alasan itu (tampilan dasbor yang tenang)."""
    rows = db.execute(select(Supervision, User).join(User, User.id == Supervision.mahasiswa_id)
                      .where(Supervision.dosen_id == u.id, Supervision.status == "approved")).all()
    drafts: dict[str, list[Draft]] = {}
    if rows:
        for d in db.scalars(select(Draft).where(Draft.owner.in_([f"u{s.mahasiswa_id}" for s, _ in rows]))):
            drafts.setdefault(d.owner, []).append(d)
    seen: dict[tuple, datetime] = {}
    if rows:
        for v in db.scalars(select(DosenView).where(DosenView.dosen_id == u.id, DosenView.mahasiswa_id.in_([m.id for _, m in rows]))):
            seen[(v.mahasiswa_id, v.doc_type, v.chapter_key)] = v.seen_at
    now, out = datetime.utcnow(), []
    for s, m in rows:
        ds = drafts.get(f"u{m.id}", [])
        words = {(d.doc_type, d.chapter_key): (len(d.content.split()), d.updated_at) for d in ds}
        types = [t for t in ROADMAP if any(k[0] == t and w[0] > 0 for k, w in words.items())] or ["skripsi"]
        docs = {t: [{"key": c["key"], "title": c["title"], "words": words.get((t, c["key"]), (0, None))[0],
                     "state": _state(words.get((t, c["key"]), (0, None))[0])} for c in ROADMAP[t]] for t in types}
        active = [w[1] for w in words.values() if w[0] > 0]
        last = max(active) if active else None
        stuck = (now - (last or s.approved_at or s.created_at)) > timedelta(days=settings.stuck_days)
        unseen = sum(1 for (dt, ck), (w, upd) in words.items() if w > 0 and ((m.id, dt, ck) not in seen or upd > seen[(m.id, dt, ck)]))
        ready_sidang = any(all(c["state"] == "terisi" for c in cs) for cs in docs.values())
        attention = (["stuck"] if stuck else []) + (["draf_baru"] if unseen else []) + (["siap_sidang"] if ready_sidang else [])
        out.append({"supervision_id": s.id, "student": {"id": m.id, "name": m.name, "email": m.email},
                    "last_active": last.isoformat() if last else None, "stuck": stuck, "unseen": unseen, "attention": attention,
                    "total_words": sum(w[0] for w in words.values()), "docs": docs})
    if focus:
        out = [x for x in out if x["attention"]]
    out.sort(key=lambda x: (not x["attention"], not x["stuck"], (x["student"]["name"] or x["student"]["email"]).lower()))
    return out


@router.get("/dosen/students/{sid}/drafts/{doc_type}/{chapter_key}")
def read_student_draft(sid: int, doc_type: str, chapter_key: str, u: User = Depends(current_dosen), db: Session = Depends(get_db)):
    """Baca draf (hanya-baca). Efek samping disengaja: mencatat versi yang terakhir dibaca dosen, sehingga pembacaan berikutnya
    menampilkan `changes` = apa yang berubah sejak pembacaan ini. `changes` null bila ini pembacaan pertama."""
    if not db.scalar(select(Supervision.id).where(Supervision.dosen_id == u.id, Supervision.mahasiswa_id == sid, Supervision.status == "approved")):
        raise HTTPException(404, "Mahasiswa tidak ditemukan atau belum memberi izin")
    d = db.scalar(select(Draft).where(Draft.owner == f"u{sid}", Draft.doc_type == doc_type, Draft.chapter_key == chapter_key))
    if not d:
        return {"content": "", "updated_at": None, "changes": None, "last_seen": None, "readiness": None}
    content, updated = d.content, d.updated_at.isoformat()
    view = db.scalar(select(DosenView).where(DosenView.dosen_id == u.id, DosenView.mahasiswa_id == sid,
                                             DosenView.doc_type == doc_type, DosenView.chapter_key == chapter_key))
    prev = db.get(DraftRevision, view.revision_id) if view and view.revision_id else None
    changes = revisions.diff(prev.content, content) if prev else None
    last_seen = view.seen_at.isoformat() if view else None
    rev = revisions.snapshot(db, d, force=True)
    now = datetime.utcnow()
    account.log_access(db, u.id, sid, doc_type, chapter_key)
    try:
        if view:
            view.revision_id, view.seen_at = (rev.id if rev else None), now
        else:
            db.add(DosenView(dosen_id=u.id, mahasiswa_id=sid, doc_type=doc_type, chapter_key=chapter_key, revision_id=rev.id if rev else None, seen_at=now))
        db.commit()
    except IntegrityError:  # dua tab dosen membaca bersamaan; pembacaan tetap berhasil
        db.rollback()
    try:
        student = db.get(User, sid)
        ready = readiness.evaluate(content, doc_type, chapter_key, style.current_rules(u=student, db=db))
        ready = {"ready": ready["ready"], "gaps": ready["gaps"], "stats": ready["stats"]}
    except HTTPException:
        ready = None
    return {"content": content, "updated_at": updated, "changes": changes, "last_seen": last_seen, "readiness": ready}


# ---------- Mahasiswa ----------
def _invite(db: Session, code: str) -> Invite:
    inv = db.scalar(select(Invite).where(Invite.code == code.strip().upper(), Invite.active.is_(True)))
    if not inv:
        raise HTTPException(404, "Kode tidak valid atau sudah tidak aktif")
    return inv


@router.get("/supervision/preview")
def preview(code: str, u: User = Depends(current_user), db: Session = Depends(get_db)):
    inv = _invite(db, code)
    d = db.get(User, inv.dosen_id)
    return {"dosen": d.name or d.email, "institution": db.get(Institution, inv.institution_id).name}


class Join(BaseModel):
    code: str = Field(max_length=12)
    consent: bool


@router.post("/supervision/join")
def join(b: Join, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if not b.consent:
        raise HTTPException(400, "Kamu perlu menyetujui berbagi progres dan draf dengan dosen ini")
    inv = _invite(db, b.code)
    if inv.dosen_id == u.id:
        raise HTTPException(400, "Kamu tidak bisa membimbing dirimu sendiri")
    now = datetime.utcnow()
    s = db.scalar(select(Supervision).where(Supervision.dosen_id == inv.dosen_id, Supervision.mahasiswa_id == u.id))
    if s:
        s.status, s.approved_at = "approved", now
    else:
        db.add(Supervision(dosen_id=inv.dosen_id, mahasiswa_id=u.id, institution_id=inv.institution_id, status="approved", approved_at=now))
    if not db.scalar(select(Membership.id).where(Membership.institution_id == inv.institution_id, Membership.user_id == u.id, Membership.role == "mahasiswa")):
        db.add(Membership(institution_id=inv.institution_id, user_id=u.id, role="mahasiswa"))
    db.commit()
    return {"ok": True}


@router.get("/supervision/mine")
def mine(u: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Supervision, User, Institution).join(User, User.id == Supervision.dosen_id)
                      .join(Institution, Institution.id == Supervision.institution_id)
                      .where(Supervision.mahasiswa_id == u.id, Supervision.status == "approved"))
    return [{"id": s.id, "dosen": d.name or d.email, "institution": i.name} for s, d, i in rows]


@router.delete("/supervision/{sid}")
def revoke(sid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    s = db.scalar(select(Supervision).where(Supervision.id == sid, Supervision.mahasiswa_id == u.id))
    if not s:
        raise HTTPException(404, "Tidak ditemukan")
    s.status = "revoked"
    db.commit()
    return {"ok": True}
