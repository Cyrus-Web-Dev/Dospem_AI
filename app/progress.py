"""Status progres yang manusiawi: Draft -> Layak bimbingan -> Ada catatan dosen -> Siap sidang.
Murni deterministik, tanpa AI dan tanpa kuota. Ini penunjuk arah untuk mahasiswa, BUKAN penilaian akademik:
"siap" hanya berarti semua bab terisi (definisi yang sama dengan dasbor dosen), bukan jaminan lulus."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import readiness, style
from .auth import current_user_opt, owner
from .campus import _state
from .db import get_db
from .models import Draft, Supervision, SupervisorNote, User
from .roadmap import DOC_BY_KEY, ROADMAP

router = APIRouter(prefix="/api")
STAGE_KEYS = ("draft", "layak", "catatan", "siap")


def _labels(kind: str) -> dict:
    return {"draft": "Draft", "layak": "Layak bimbingan", "catatan": "Ada catatan dosen", "siap": "Siap submit" if kind == "article" else "Siap sidang"}


def stage_of(chs: list[dict], notes_total: int) -> str | None:
    """Tahap tertinggi yang berlaku (urutan prioritas: siap > catatan > layak > draft); None = belum mulai."""
    if all(c["terisi"] for c in chs):
        return "siap"
    if notes_total:
        return "catatan"
    if any(c["state"] == "layak" for c in chs):
        return "layak"
    if any(c["words"] for c in chs):
        return "draft"
    return None


def _next(stage: str | None, chs: list[dict], unread: int, has_sup: bool, kind: str) -> str:
    first = lambda pred: next((c for c in chs if pred(c)), None)  # noqa: E731
    if stage is None:
        return f"Mulai dari bab “{chs[0]['title']}”. Versi kasar pun tidak apa-apa."
    if stage == "draft":
        c = first(lambda c: c["state"] == "draf") or first(lambda c: c["state"] == "belum")
        return f"Lanjutkan bab “{c['title']}” sampai layak dibaca dosen. Tab Kesiapan menunjukkan apa yang masih kurang."
    if stage == "layak":
        if not has_sup:
            return "Draf sudah ada yang layak dibaca. Hubungkan dosen pembimbingmu lewat menu Dosen pembimbing agar ia bisa membacanya."
        c = first(lambda c: not c["terisi"])
        return f"Dosenmu bisa membuka bab yang sudah layak. Sambil menunggu catatannya, lanjutkan bab “{c['title']}”."
    if stage == "catatan":
        if unread:
            return f"Ada {unread} catatan baru dari dosen. Baca di tab Kesiapan, lalu revisi."
        return "Revisi sesuai catatan dosen, lalu periksa kesiapan sebelum mengirim ulang."
    if kind == "article":
        return "Semua bagian sudah terisi. Periksa kesiapannya lagi dan bicarakan dengan pembimbingmu sebelum submit."
    return "Semua bab sudah terisi. Latihan di Mode Sidang bisa membantu; penilaian resmi tetap oleh dosen penguji."


def compute(db: Session, who: str, u: User | None, rules: dict | None, doc_type: str) -> dict:
    if doc_type not in ROADMAP:
        raise HTTPException(404, "Jenis tugas tidak dikenal")
    kind = DOC_BY_KEY[doc_type]["kind"]
    texts = {d.chapter_key: d.content for d in db.scalars(select(Draft).where(Draft.owner == who, Draft.doc_type == doc_type))}
    chs = []
    for c in ROADMAP[doc_type]:
        text = texts.get(c["key"], "")
        words = len(text.split())
        state = "belum" if not words else "layak" if readiness.evaluate(text, doc_type, c["key"], rules)["ready"] else "draf"
        chs.append({"key": c["key"], "title": c["title"], "words": words, "state": state, "terisi": _state(words) == "terisi"})
    notes_total = unread = 0
    has_sup = False
    if u:
        q = (select(func.count(SupervisorNote.id)).join(Supervision, Supervision.id == SupervisorNote.supervision_id)
             .where(Supervision.mahasiswa_id == u.id, SupervisorNote.kind == "catatan",
                    (SupervisorNote.doc_type == doc_type) | SupervisorNote.doc_type.is_(None)))
        notes_total = db.scalar(q) or 0
        unread = db.scalar(q.where(SupervisorNote.read_at.is_(None))) or 0
        has_sup = bool(db.scalar(select(Supervision.id).where(Supervision.mahasiswa_id == u.id, Supervision.status == "approved").limit(1)))
    st = stage_of(chs, notes_total)
    labels = _labels(kind)
    return {"doc_type": doc_type, "stage": {"key": st, "label": labels[st] if st else "Belum mulai", "index": STAGE_KEYS.index(st) + 1 if st else 0},
            "stages": [{"key": k, "label": labels[k]} for k in STAGE_KEYS],
            "chapters": [{k: c[k] for k in ("key", "title", "words", "state")} for c in chs],
            "next": _next(st, chs, unread, has_sup, kind), "notes_unread": unread, "has_supervisor": has_sup}


@router.get("/progress")
def progress(doc_type: str = "skripsi", who: str = Depends(owner), u: User | None = Depends(current_user_opt),
             rules: dict | None = Depends(style.current_rules), db: Session = Depends(get_db)):
    return compute(db, who, u, rules, doc_type)
