"""Riwayat versi draf + ringkasan perubahan. Murni deterministik (difflib), tanpa AI dan tanpa kuota.
Snapshot dibatasi: jeda minimal `revision_min_minutes` dan hanya `revision_keep` terbaru per draf (menjaga ukuran DB)."""
import difflib
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import owner
from .config import settings
from .db import get_db
from .models import Draft, DraftRevision
from .roadmap import ROADMAP

router = APIRouter(prefix="/api")
MAX_ITEMS = 30
CLIP = 300
PARA = re.compile(r"\n\s*\n|\n")


def _words(s: str) -> int:
    return len(s.split())


def _paras(text: str) -> list[str]:
    return [p.strip() for p in PARA.split(text or "") if p.strip()]


def _clip(s: str) -> str:
    return s if len(s) <= CLIP else s[:CLIP].rstrip() + "…"


def last_revision(db: Session, draft_id: int) -> DraftRevision | None:
    return db.scalar(select(DraftRevision).where(DraftRevision.draft_id == draft_id).order_by(DraftRevision.id.desc()).limit(1))


def snapshot(db: Session, draft: Draft, force: bool = False) -> DraftRevision | None:
    """Simpan snapshot isi draf saat ini bila berbeda dari snapshot terakhir dan jeda minimal terpenuhi
    (force=True melewati jeda, mis. saat dosen membaca). Tidak melakukan commit; pemanggil yang commit."""
    if not (draft.content or "").strip():
        return None
    last = last_revision(db, draft.id)
    if last and last.content == draft.content:
        return last
    if last and not force and settings.revision_min_minutes > 0 \
            and datetime.utcnow() - last.created_at < timedelta(minutes=settings.revision_min_minutes):
        return None
    rev = DraftRevision(draft_id=draft.id, content=draft.content, words=_words(draft.content))
    db.add(rev)
    db.flush()
    keep = settings.revision_keep
    if keep > 0:
        ids = db.scalars(select(DraftRevision.id).where(DraftRevision.draft_id == draft.id).order_by(DraftRevision.id.desc()).offset(keep)).all()
        if ids:
            for r in db.scalars(select(DraftRevision).where(DraftRevision.id.in_(ids))):
                db.delete(r)
    return rev


def diff(old: str, new: str) -> dict:
    """Ringkasan perubahan per paragraf: ditambah / dihapus / diubah. Teks dipotong agar respons ringan."""
    a, b = _paras(old), _paras(new)
    items, added, removed, changed = [], 0, 0, 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        before, after = a[i1:i2], b[j1:j2]
        if tag == "replace" and len(before) == len(after):
            changed += len(after)
            items += [{"type": "diubah", "before": _clip(x), "after": _clip(y)} for x, y in zip(before, after)]
        else:
            removed += len(before)
            added += len(after)
            items += [{"type": "dihapus", "before": _clip(x), "after": None} for x in before]
            items += [{"type": "ditambah", "before": None, "after": _clip(y)} for y in after]
    wb, wa = _words(old), _words(new)
    return {"added": added, "removed": removed, "changed": changed, "words_before": wb, "words_after": wa, "words_delta": wa - wb,
            "same": not (added or removed or changed), "items": items[:MAX_ITEMS], "truncated": len(items) > MAX_ITEMS}


def _draft(db: Session, who: str, doc_type: str, chapter_key: str) -> Draft:
    if chapter_key not in {c["key"] for c in ROADMAP.get(doc_type, [])}:
        raise HTTPException(404, "Jenis tugas atau bab tidak dikenal")
    d = db.scalar(select(Draft).where(Draft.owner == who, Draft.doc_type == doc_type, Draft.chapter_key == chapter_key))
    if not d:
        raise HTTPException(404, "Draf belum ada")
    return d


def _rev(db: Session, d: Draft, rid: int) -> DraftRevision:
    r = db.scalar(select(DraftRevision).where(DraftRevision.id == rid, DraftRevision.draft_id == d.id))
    if not r:
        raise HTTPException(404, "Versi tidak ditemukan")
    return r


@router.get("/drafts/{doc_type}/{chapter_key}/revisions")
def list_revisions(doc_type: str, chapter_key: str, who: str = Depends(owner), db: Session = Depends(get_db)):
    d = _draft(db, who, doc_type, chapter_key)
    rows = db.execute(select(DraftRevision.id, DraftRevision.words, DraftRevision.created_at)
                      .where(DraftRevision.draft_id == d.id).order_by(DraftRevision.id.desc())).all()
    return [{"id": i, "words": w, "created_at": c.isoformat()} for i, w, c in rows]


@router.get("/drafts/{doc_type}/{chapter_key}/revisions/{rid}")
def get_revision(doc_type: str, chapter_key: str, rid: int, who: str = Depends(owner), db: Session = Depends(get_db)):
    r = _rev(db, _draft(db, who, doc_type, chapter_key), rid)
    return {"id": r.id, "content": r.content, "words": r.words, "created_at": r.created_at.isoformat()}


@router.get("/drafts/{doc_type}/{chapter_key}/revisions/{rid}/diff")
def diff_revision(doc_type: str, chapter_key: str, rid: int, who: str = Depends(owner), db: Session = Depends(get_db)):
    """Apa yang berubah dari versi `rid` sampai isi draf sekarang."""
    d = _draft(db, who, doc_type, chapter_key)
    return diff(_rev(db, d, rid).content, d.content)


@router.post("/drafts/{doc_type}/{chapter_key}/revisions/{rid}/restore")
def restore_revision(doc_type: str, chapter_key: str, rid: int, who: str = Depends(owner), db: Session = Depends(get_db)):
    """Pulihkan draf ke versi `rid`. Isi sekarang disimpan lebih dulu sebagai versi (tanpa jeda), jadi pemulihan bisa dibatalkan."""
    d = _draft(db, who, doc_type, chapter_key)
    target = _rev(db, d, rid)
    content = target.content  # ambil sebelum pruning menghapus baris
    snapshot(db, d, force=True)
    d.content = content
    db.flush()
    snapshot(db, d, force=True)
    db.commit()
    return {"content": content}
