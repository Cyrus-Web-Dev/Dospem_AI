"""Analisis logika bab (Premium): rubrik per butir checklist + alur antar paragraf + pertanyaan dosen. Tidak menulis ulang."""
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import llm, meter, obs, quota, richtext, style
from .auth import owner
from .config import settings
from .db import get_db

router = APIRouter(prefix="/api")


class In(BaseModel):
    text: str = Field(max_length=200000)  # sepanjang draf; bab panjang dicuplik di server (lihat analyze)
    doc_type: str = "skripsi"
    chapter_key: str


@router.post("/analyze")
def analyze(b: In, who=Depends(owner), db: Session = Depends(get_db), rules: dict | None = Depends(style.current_rules)):
    if who.plan != "premium":
        raise HTTPException(402, "Analisis logika bab adalah fitur Premium.")
    text = richtext.prose(b.text.replace("\x00", ""))  # tabel dan gambar bukan teks uraian
    if not text.strip():
        raise HTTPException(422, "Tidak ada teks uraian untuk dianalisis (hanya tabel atau gambar).")
    budget, note = settings.max_chars_per_request * 2, None
    if len(text) > budget:  # bab panjang: cuplikan merata sepanjang bab (bagian yang dilewati ditandai […]) alih-alih ditolak
        note = {"condensed": True, "chars": len(text), "used": budget - 300}
        text = richtext.condense(text, budget - 300)
    key = meter.cache_key("analyze", b.doc_type, b.chapter_key, text, rules)
    hit = meter.cache_get(db, who, key)
    if hit is not None:  # teks sama persis: gratis dan tidak memotong kuota analisis
        meter.record_hit(db, who, "analyze")
        return {**hit, "left": settings.premium_analysis_quota - quota.used(db, who, "analisis"), "cached": True}
    meter.check_budget(db)
    n = quota.take(db, who, settings.premium_analysis_quota, "analisis")
    if n is None:
        raise HTTPException(429, "Batas analisis bab hari ini tercapai. Coba lagi besok.")
    try:
        with meter.call("analyze") as acc:
            res = llm.analyze(text, b.doc_type, b.chapter_key, rules)
    except llm.GuardError as e:
        quota.refund(db, who, "analisis")
        raise HTTPException(422, str(e))
    except (httpx.HTTPError, llm.ProviderError) as e:
        obs.llm_error("analyze", e)
        quota.refund(db, who, "analisis")
        raise HTTPException(502, "Layanan AI sedang sibuk. Kuotamu tidak terpakai.")
    res["note"] = note
    meter.record(db, who, "analyze", acc)
    meter.cache_put(db, who, "analyze", key, res)
    return {**res, "left": settings.premium_analysis_quota - n}
