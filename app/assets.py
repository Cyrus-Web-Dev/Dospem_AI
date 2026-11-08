"""Penyimpanan dan penyajian gambar bab (diagram Use Case, DFD, ERD, tangkapan layar, dsb. dari .docx yang diunggah).

Gambar dirujuk dari teks draf lewat `![keterangan](asset:ID)` (lihat richtext.py), disimpan per (pemilik, jenis tugas, bab), dan hanya
dapat dibaca pemiliknya. Hanya PNG/JPEG/GIF/WebP berdasarkan ISI (SVG ditolak karena bisa memuat skrip). Batas: jumlah per bab,
total per pemilik, dan ukuran per gambar. Gambar yang tak lagi dirujuk draf maupun riwayat versinya dibersihkan (gc)."""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import docparse, richtext
from .auth import owner
from .config import settings
from .db import get_db
from .models import Draft, DraftAsset, DraftRevision
from .roadmap import ROADMAP

router = APIRouter(prefix="/api")


def store(db: Session, who: str, doc_type: str, chapter_key: str, images: dict[str, dict]) -> tuple[set[str], int]:
    """Simpan gambar hasil ekstraksi. Mengembalikan (ID yang tersimpan/sudah ada, jumlah yang ditolak karena batas). Tidak commit."""
    have = {a for (a,) in db.execute(select(DraftAsset.sha).where(DraftAsset.owner == who, DraftAsset.doc_type == doc_type, DraftAsset.chapter_key == chapter_key))}
    used = db.scalar(select(func.coalesce(func.sum(DraftAsset.size), 0)).where(DraftAsset.owner == who)) or 0
    kept, refused = set(have & set(images)), 0
    count = len(have)
    for sha, im in images.items():
        if sha in have:
            continue
        size = len(im["data"])
        if count >= settings.asset_max_per_chapter or used + size > settings.asset_user_quota_mb * 1024 * 1024:
            refused += 1
            continue
        db.add(DraftAsset(owner=who, doc_type=doc_type, chapter_key=chapter_key, sha=sha, mime=im["mime"], size=size, alt=im.get("alt", "")[:120], data=im["data"]))
        kept.add(sha)
        count, used = count + 1, used + size
    return kept, refused


def drop_refs(text: str, missing: set[str]) -> str:
    """Hapus baris gambar yang rujukannya tidak berhasil disimpan, agar draf tidak berisi gambar rusak."""
    if not missing:
        return text
    return "\n".join(ln for ln in text.split("\n") if not ((m := richtext.IMG_LINE.match(ln.strip())) and m.group(2) in missing))


def gc(db: Session, who: str, doc_type: str, chapter_key: str) -> int:
    """Hapus gambar bab ini yang tak dirujuk draf saat ini maupun riwayat versinya (agar 'pulihkan versi' tetap menampilkan gambarnya)."""
    d = db.scalar(select(Draft).where(Draft.owner == who, Draft.doc_type == doc_type, Draft.chapter_key == chapter_key))
    if not d:
        return 0
    keep = set(richtext.hashes(d.content))
    for (c,) in db.execute(select(DraftRevision.content).where(DraftRevision.draft_id == d.id)):
        keep |= set(richtext.hashes(c))
    q = delete(DraftAsset).where(DraftAsset.owner == who, DraftAsset.doc_type == doc_type, DraftAsset.chapter_key == chapter_key)
    if keep:
        q = q.where(DraftAsset.sha.notin_(keep))
    return db.execute(q).rowcount or 0


def load(db: Session, who: str, doc_type: str, shas: list[str]) -> dict[str, DraftAsset]:
    """Gambar untuk ekspor: sha -> baris, dari semua bab jenis tugas ini milik `who`."""
    if not shas:
        return {}
    return {a.sha: a for a in db.scalars(select(DraftAsset).where(DraftAsset.owner == who, DraftAsset.doc_type == doc_type, DraftAsset.sha.in_(shas)))}


@router.get("/assets/{doc_type}/{chapter_key}/{sha}")
def get_asset(doc_type: str, chapter_key: str, sha: str, who: str = Depends(owner), db: Session = Depends(get_db)):
    if chapter_key not in {c["key"] for c in ROADMAP.get(doc_type, [])} or not richtext.ASSET_REF.fullmatch(f"(asset:{sha})"):
        raise HTTPException(404, "Gambar tidak ditemukan")
    a = db.scalar(select(DraftAsset).where(DraftAsset.owner == who, DraftAsset.doc_type == doc_type, DraftAsset.chapter_key == chapter_key, DraftAsset.sha == sha))
    if not a or docparse.sniff_image(a.data) != a.mime:  # defensif: jangan sajikan apa pun selain gambar yang dikenali
        raise HTTPException(404, "Gambar tidak ditemukan")
    return Response(a.data, media_type=a.mime, headers={"Cache-Control": "private, max-age=31536000, immutable", "ETag": f'"{sha}"', "Content-Disposition": "inline"})
