"""Checklist "layak kirim ke dosen": gabungan pemeriksaan deterministik (tanpa AI, tanpa kuota) agar draf mentah
tidak masuk inbox dosen. Hasilnya SARAN untuk mahasiswa, bukan penilaian akademik dan bukan syarat formal."""
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import eyd, refs, style
from .auth import current_user_opt, owner
from .bib import _dict
from .config import settings
from .db import get_db
from .models import BibEntry, Draft, User
from .roadmap import ROADMAP

router = APIRouter(prefix="/api")
MAX_SHOWN = 5


def _gap(kind: str, severity: str, message: str, **extra) -> dict:
    return {"kind": kind, "severity": severity, "message": message, **extra}


def evaluate(text: str, doc_type: str, chapter_key: str, rules: dict | None = None, entries: list[dict] | None = None,
             cite_style: str = "apa", checked: list[int] | None = None) -> dict:
    """Kembalikan {ready, gaps, stats, manual}. `blocker` = sebaiknya dibereskan sebelum dikirim; `warn` = perlu dicek."""
    chapter = next((c for c in ROADMAP.get(doc_type, []) if c["key"] == chapter_key), None)
    if not chapter:
        raise HTTPException(404, "Jenis tugas atau bab tidak dikenal")
    text = (text or "").replace("\x00", "")
    words = len(text.split())
    gaps: list[dict] = []
    rule = style.chapter_rule(rules, doc_type, chapter_key)

    if words == 0:
        gaps.append(_gap("kosong", "blocker", "Bab ini masih kosong."))
    else:
        min_w = rule.get("min_words") or settings.ready_min_words
        if words < min_w:
            src = "pedoman kampus" if rule.get("min_words") else "ambang umum"
            gaps.append(_gap("pendek", "blocker", f"Baru {words} kata; minimal sekitar {min_w} kata ({src}).", have=words, need=min_w))
        if rule.get("max_words") and words > rule["max_words"]:
            gaps.append(_gap("panjang", "warn", f"{words} kata, melebihi batas {rule['max_words']} kata dari pedoman kampus.", have=words, need=rule["max_words"]))

        issues = eyd.check(text, style.check(text, rules) if rules else None)
        ph = [i for i in issues if i.get("rule") == "placeholder"]
        if ph:
            gaps.append(_gap("placeholder", "blocker", f"{len(ph)} isian templat belum diganti.", count=len(ph), examples=[i["text"][:60] for i in ph[:MAX_SHOWN]]))
        rest = [i for i in issues if i.get("rule") != "placeholder"]
        density = round(len(rest) * 100 / words, 1)
        if density > settings.ready_max_issues_per_100w:
            gaps.append(_gap("ejaan", "warn", f"Masih banyak catatan ejaan/gaya ({density} per 100 kata). Jalankan Cek EYD V dulu.", per_100w=density))

        if entries is not None and cite_style in ("apa", "ieee"):
            miss = refs.check(text, entries, cite_style, False)["missing"]
            if miss:
                gaps.append(_gap("sitasi", "warn", f"{len(miss)} sitasi belum ada di daftar pustaka.", count=len(miss), examples=[m["text"] for m in miss[:MAX_SHOWN]]))
    manual = list(chapter["checklist"]) + list(rule.get("extra_checklist", []))
    if checked is not None:
        todo = [m for i, m in enumerate(manual) if i not in set(checked)]
        if todo:
            gaps.append(_gap("manual", "warn", f"{len(todo)} butir checklist belum kamu centang.", count=len(todo), examples=todo[:MAX_SHOWN]))
    return {"ready": not any(g["severity"] == "blocker" for g in gaps), "gaps": gaps, "manual": manual,
            "stats": {"words": words}, "note": "Saran otomatis untuk membantumu menyiapkan draf; keputusan tetap di dosen pembimbingmu."}


class ReadyIn(BaseModel):
    doc_type: str = "skripsi"
    chapter_key: str
    text: str | None = Field(None, max_length=200000)  # kosong = pakai draf tersimpan
    checked: list[int] | None = Field(None, max_length=40)  # indeks butir checklist manual yang sudah dicentang
    style: Literal["apa", "ieee"] = "apa"

    @field_validator("checked")
    @classmethod
    def _idx(cls, v):
        if v is not None and any(i < 0 or i > 1000 for i in v):
            raise ValueError("indeks checklist tidak valid")
        return v


@router.post("/readiness")
def readiness(b: ReadyIn, who: str = Depends(owner), u: User | None = Depends(current_user_opt),
              rules: dict | None = Depends(style.current_rules), db: Session = Depends(get_db)):
    text = b.text
    if text is None:
        d = db.scalar(select(Draft).where(Draft.owner == who, Draft.doc_type == b.doc_type, Draft.chapter_key == b.chapter_key))
        text = d.content if d else ""
    entries = [_dict(e) for e in db.scalars(select(BibEntry).where(BibEntry.user_id == u.id).order_by(BibEntry.id))] if u else None
    if entries is not None and not entries:
        entries = None  # tanpa daftar pustaka tersimpan, jangan menuduh semua sitasi "hilang"
    cs = b.style
    if rules and rules.get("citation_style") in ("apa", "ieee"):
        cs = rules["citation_style"]
    return evaluate(text, b.doc_type, b.chapter_key, rules, entries, cs, b.checked)
