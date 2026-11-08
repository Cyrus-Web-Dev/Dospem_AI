"""Unggah berkas per bab (.docx/.pdf/.txt/.md) -> isi draf bab. Tiap bab (Bab 1 s.d. Bab 5, atau bab jenis tugas lain) punya
berkas sendiri. Isi lama selalu disimpan sebagai versi (Riwayat versi) sebelum diganti, jadi unggahan yang keliru bisa dipulihkan.
Berkas aslinya TIDAK disimpan: hanya teks hasil ekstraksi yang menjadi draf."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from . import assets, docparse, revisions, richtext
from .auth import owner
from .config import settings
from .db import get_db
from .models import Draft
from .roadmap import ROADMAP

router = APIRouter(prefix="/api")
MAX_CHARS = 200000  # sama dengan batas draf pada PUT /api/drafts


@router.post("/upload")
async def upload(request: Request, doc_type: str = Query(max_length=20), chapter_key: str = Query(max_length=40),
                 filename: str = Query("berkas", max_length=200), mode: Literal["replace", "append"] = "replace",
                 who: str = Depends(owner), db: Session = Depends(get_db)):
    """Badan permintaan = isi berkas mentah (Content-Type: application/octet-stream)."""
    if chapter_key not in {c["key"] for c in ROADMAP.get(doc_type, [])}:
        raise HTTPException(404, "Jenis tugas atau bab tidak dikenal")
    cap = settings.upload_max_mb * 1024 * 1024
    cl = request.headers.get("content-length", "")
    if cl.isdigit() and int(cl) > cap + 4096:
        raise HTTPException(413, f"Berkas terlalu besar (maks {settings.upload_max_mb} MB).")
    buf = bytearray()
    async for chunk in request.stream():  # batasi sambil membaca: klien tidak jujur soal Content-Length tak boleh memenuhi memori
        buf += chunk
        if len(buf) > cap + 4096:
            raise HTTPException(413, f"Berkas terlalu besar (maks {settings.upload_max_mb} MB).")
    try:
        res = await run_in_threadpool(docparse.extract, bytes(buf), filename)
    except docparse.ParseError as e:
        raise HTTPException(422, str(e))
    text, warnings = res["text"], list(res["warnings"])
    d = db.scalar(select(Draft).where(Draft.owner == who, Draft.doc_type == doc_type, Draft.chapter_key == chapter_key))
    old = (d.content if d else "") or ""
    new = text if mode == "replace" or not old.strip() else old.rstrip() + "\n\n" + text
    if len(new) > MAX_CHARS:
        raise HTTPException(422, f"Isi bab terlalu panjang ({len(new):,} karakter; maks {MAX_CHARS:,}, sekitar 100 halaman). Unggah per bab atau pecah babnya.".replace(",", "."))
    kept, refused = assets.store(db, who, doc_type, chapter_key, res["images"]) if res["images"] else (set(), 0)
    if refused:
        gone = set(res["images"]) - kept
        text = assets.drop_refs(text, gone)
        new = text if mode == "replace" or not old.strip() else old.rstrip() + "\n\n" + text
        warnings.append(f"{refused} gambar tidak disimpan karena batas penyimpanan gambar tercapai (maks {settings.asset_max_per_chapter} gambar per bab, {settings.asset_user_quota_mb} MB total).")
    if d:
        revisions.snapshot(db, d, force=True)  # versi lama aman di Riwayat versi, apa pun yang terjadi setelah ini
        d.content = new
    else:
        d = Draft(owner=who, doc_type=doc_type, chapter_key=chapter_key, content=new)
        db.add(d)
    db.flush()
    revisions.snapshot(db, d, force=True)
    assets.gc(db, who, doc_type, chapter_key)
    db.commit()
    return {"content": new, "words": len(richtext.prose(new).split()), "prev_words": len(richtext.prose(old).split()), "added_words": len(richtext.prose(text).split()),
            "filename": res["filename"], "kind": res["kind"], "mode": mode if old.strip() else "replace", "warnings": warnings,
            "tables": res["tables"], "images": len(richtext.hashes(text))}
