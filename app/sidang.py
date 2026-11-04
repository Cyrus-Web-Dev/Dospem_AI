"""Mode Sidang (Premium): AI berperan sebagai dosen penguji. Pertanyaan berpijak pada tulisan mahasiswa; tiap jawaban dinilai
(skor 1-5 pada tiga aspek) dan dibalas pertanyaan berikutnya. Skor akhir dihitung dari nilai tiap jawaban (deterministik),
AI hanya menulis narasi ringkasan. Penguji bertanya dan menilai, TIDAK menuliskan jawaban."""
import json
import re
from datetime import datetime, timedelta
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete as sql_delete
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import bank, llm, meter, obs, quota
from .auth import current_user, plan_of
from .config import settings
from .db import get_db
from .models import Draft, SidangSession, SidangTurn, User
from .roadmap import DOC_BY_KEY, ROADMAP, SIDANG_MODES, SIDANG_PERSONAS

router = APIRouter(prefix="/api/sidang")
EXPIRE = timedelta(hours=24)  # sesi aktif yang ditinggalkan otomatis ditutup agar tidak memblokir sesi baru
CONTEXT_CHARS = 8000
MIN_CONTEXT = 200
KIND = "sidang"
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class StartIn(BaseModel):
    mode: Literal["pkl", "sempro", "skripsi"]
    persona: Literal["suportif", "standar", "kritis"] = "standar"
    questions: int | None = Field(None, ge=3, le=10)


class AnswerIn(BaseModel):
    text: str = Field(min_length=1, max_length=settings.sidang_answer_chars)

    @field_validator("text")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = CTRL.sub("", v).strip()
        if not v:
            raise ValueError("Jawaban tidak boleh kosong")
        return v


# ---------- util ----------
def _turns(db: Session, sid: int) -> list[SidangTurn]:
    return list(db.scalars(select(SidangTurn).where(SidangTurn.session_id == sid).order_by(SidangTurn.idx)))


def _ser(s: SidangSession, turns: list[SidangTurn]) -> dict:
    m = SIDANG_MODES[s.mode]
    return {"id": s.id, "mode": s.mode, "label": m["label"], "persona": s.persona, "persona_label": SIDANG_PERSONAS[s.persona]["label"],
            "doc_type": s.doc_type, "doc_label": DOC_BY_KEY[s.doc_type]["label"], "status": s.status, "max_questions": s.max_questions,
            "created_at": s.created_at.isoformat(), "finished_at": s.finished_at.isoformat() if s.finished_at else None,
            "turns": [{"idx": t.idx, "question": t.question, "answer": t.answer, "feedback": json.loads(t.feedback) if t.feedback else None} for t in turns],
            "summary": json.loads(s.summary) if s.summary else None}


def _mine(db: Session, u: User, sid: int) -> SidangSession:
    s = db.get(SidangSession, sid)
    if not s or s.user_id != u.id:  # sesi orang lain = tidak ada (jangan bocorkan keberadaannya)
        raise HTTPException(404, "Sesi sidang tidak ditemukan")
    return s


def _active(db: Session, u: User) -> SidangSession | None:
    s = db.scalar(select(SidangSession).where(SidangSession.user_id == u.id, SidangSession.status == "aktif"))
    if s and datetime.utcnow() - s.created_at > EXPIRE:
        s.status, s.finished_at = "selesai", datetime.utcnow()
        db.commit()
        return None
    return s


def _need_premium(u: User) -> None:
    if plan_of(u) != "premium":
        raise HTTPException(402, "Mode Sidang adalah fitur Premium.")


def _context(db: Session, u: User, mode: str) -> tuple[str, str, list[tuple[str, str]]]:
    """(doc_type, teks bahan, [(kunci bab, judul)]). Memilih jenis dokumen yang paling banyak isinya; bab dipotong merata."""
    best = None
    for dt in SIDANG_MODES[mode]["doc_types"]:
        got = {k: c for k, c in db.execute(select(Draft.chapter_key, Draft.content).where(Draft.owner == f"u{u.id}", Draft.doc_type == dt))}
        parts = [(c["key"], c["title"], (got.get(c["key"]) or "").strip()) for c in ROADMAP[dt]]
        total = sum(len(p[2]) for p in parts)
        if best is None or total > best[0]:
            best = (total, dt, parts)
    total, dt, parts = best
    if total < MIN_CONTEXT:
        raise HTTPException(400, f"Tulis dulu bahan untuk {DOC_BY_KEY[dt]['label']} (minimal beberapa paragraf) agar penguji punya bahan untuk bertanya.")
    filled = [p for p in parts if p[2]]
    per = max(1000, CONTEXT_CHARS // len(filled))
    text = "\n\n".join(f"[{t}]\n{CTRL.sub('', c)[:per]}" for _, t, c in filled)[:CONTEXT_CHARS]
    return dt, text, [(k, t) for k, t, _ in parts]


def _summary(db: Session, s: SidangSession, turns: list[SidangTurn], context: str, chapters: list) -> dict:
    done = [(t, json.loads(t.feedback)) for t in turns if t.answer and t.feedback]
    avg = {a: round(sum(f["skor"][a] for _, f in done) / len(done), 1) for a in llm.ASPECTS} if done else {}
    overall = round(sum(avg.values()) / len(avg), 1) if avg else None
    verdict = None if overall is None else ("Siap" if overall >= 4.2 else "Cukup siap" if overall >= 3.2 else "Perlu latihan lagi")
    narr = None
    if done and not meter.over_budget(db):  # anggaran habis: skor tetap disimpan, hanya narasi AI yang dilewati
        try:
            with meter.call("summary") as acc:
                narr = llm.sidang_summary(s.mode, s.persona, s.doc_type, chapters, context, [(t.question, t.answer) for t, _ in done])
            meter.record(db, f"u{s.user_id}", "summary", acc)
        except (httpx.HTTPError, llm.ProviderError) as e:
            obs.llm_error("summary", e)
            narr = None  # skor tetap tersimpan; narasi tidak boleh menggagalkan penutupan sesi
    titles = dict(chapters)
    return {"scores": avg, "overall": overall, "verdict": verdict, "answered": len(done), "total": s.max_questions, "narrative": narr is not None,
            "kekuatan": (narr or {}).get("kekuatan", []), "perbaikan": (narr or {}).get("perbaikan", []), "catatan": (narr or {}).get("catatan", ""),
            "revisi_bab": [{"key": r["bab"], "title": titles[r["bab"]], "alasan": r["alasan"]} for r in (narr or {}).get("revisi_bab", [])],
            "disclaimer": "Latihan ini bukan prediksi nilai: penguji sebenarnya bisa bertanya hal yang berbeda."}


def _close(db: Session, s: SidangSession, summary: dict | None) -> None:
    s.status, s.finished_at = "selesai", datetime.utcnow()
    s.summary = json.dumps(summary) if summary else None
    db.commit()


# ---------- endpoint ----------
@router.get("/modes")
def modes():
    return {"modes": [{"key": k, "label": m["label"], "desc": m["desc"], "doc_type": m["doc_types"][0], "doc_label": DOC_BY_KEY[m["doc_types"][0]]["label"]}
                      for k, m in SIDANG_MODES.items()],
            "personas": [{"key": k, "label": p["label"], "desc": p["desc"]} for k, p in SIDANG_PERSONAS.items()],
            "default_questions": settings.sidang_default_questions}


@router.get("")
def history(u: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(SidangSession).where(SidangSession.user_id == u.id).order_by(SidangSession.id.desc()).limit(20))
    out = []
    for s in rows:
        sm = json.loads(s.summary) if s.summary else None
        out.append({"id": s.id, "label": SIDANG_MODES[s.mode]["label"], "persona_label": SIDANG_PERSONAS[s.persona]["label"], "status": s.status,
                    "created_at": s.created_at.isoformat(), "overall": sm and sm.get("overall"), "verdict": sm and sm.get("verdict")})
    return {"items": out}


@router.get("/active")
def active(u: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _active(db, u)
    return {"session": _ser(s, _turns(db, s.id)) if s else None}


@router.post("/start")
def start(b: StartIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    _need_premium(u)
    meter.check_budget(db)
    if _active(db, u):
        raise HTTPException(409, "Masih ada sidang yang berjalan. Lanjutkan atau akhiri dulu.")
    doc_type, context, chapters = _context(db, u, b.mode)
    pool = bank.pool_for(db, u, b.mode)  # pertanyaan kurasi kampus (bisa kosong)
    total = b.questions or settings.sidang_default_questions
    owner = f"u{u.id}"
    if quota.take(db, owner, settings.premium_sidang_quota, KIND) is None:
        raise HTTPException(429, "Batas langkah sidang hari ini tercapai. Coba lagi besok.")
    s = SidangSession(user_id=u.id, mode=b.mode, persona=b.persona, doc_type=doc_type, max_questions=total)
    try:
        db.add(s)
        db.commit()  # indeks unik parsial menolak sesi aktif ganda walau dua permintaan serentak
    except IntegrityError:
        db.rollback()
        quota.refund(db, owner, KIND)
        raise HTTPException(409, "Masih ada sidang yang berjalan. Lanjutkan atau akhiri dulu.")
    try:
        with meter.call("sidang") as acc:
            r = llm.sidang_next(b.mode, b.persona, doc_type, chapters, context, [], 1, total, bank=pool or None)
    except (httpx.HTTPError, llm.ProviderError) as e:
        obs.llm_error("sidang", e)
        db.delete(s)
        db.commit()
        quota.refund(db, owner, KIND)
        raise HTTPException(502, "Layanan AI sedang sibuk. Kuotamu tidak terpakai.")
    db.add(SidangTurn(session_id=s.id, idx=1, question=r["pertanyaan"]))
    db.commit()
    meter.record(db, owner, "sidang", acc)
    return _ser(s, _turns(db, s.id))


@router.post("/{sid}/answer")
def answer(sid: int, b: AnswerIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    _need_premium(u)
    meter.check_budget(db)  # sebelum klaim jawaban & kuota: bila ditolak, tidak ada yang berubah
    s = _mine(db, u, sid)
    if s.status != "aktif":
        raise HTTPException(409, "Sidang ini sudah selesai.")
    turns = _turns(db, sid)
    cur = turns[-1] if turns else None
    if not cur or cur.answer is not None:
        raise HTTPException(409, "Tidak ada pertanyaan yang menunggu jawaban.")
    owner = f"u{u.id}"
    if quota.take(db, owner, settings.premium_sidang_quota, KIND) is None:
        raise HTTPException(429, "Batas langkah sidang hari ini tercapai. Coba lagi besok.")
    claim = db.execute(update(SidangTurn).where(SidangTurn.id == cur.id, SidangTurn.answer.is_(None)).values(answer=b.text))  # klaim atomik: kirim ganda tidak diproses dua kali
    db.commit()
    if claim.rowcount != 1:
        quota.refund(db, owner, KIND)
        raise HTTPException(409, "Jawaban untuk pertanyaan ini sudah dikirim.")
    db.refresh(cur)
    try:
        dt, context, chapters = _context(db, u, s.mode)
    except HTTPException:  # bahan dihapus di tengah sesi: pakai bahan seadanya agar sesi tetap bisa lanjut
        dt, context, chapters = s.doc_type, "(tulisan tidak tersedia)", [(c["key"], c["title"]) for c in ROADMAP[s.doc_type]]
    history = [(t.question, t.answer) for t in turns[:-1] if t.answer] + [(cur.question, cur.answer)]
    last = cur.idx >= s.max_questions
    try:
        with meter.call("sidang") as acc:
            r = llm.sidang_next(s.mode, s.persona, s.doc_type, chapters, context, history, cur.idx + 1, s.max_questions, bank=bank.pool_for(db, u, s.mode) or None)
    except (httpx.HTTPError, llm.ProviderError) as e:
        obs.llm_error("sidang", e)
        db.execute(update(SidangTurn).where(SidangTurn.id == cur.id).values(answer=None))  # jawaban dikembalikan agar bisa dikirim ulang
        db.commit()
        quota.refund(db, owner, KIND)
        raise HTTPException(502, "Layanan AI sedang sibuk. Jawabanmu tidak hilang dan kuotamu tidak terpakai; kirim ulang sebentar lagi.")
    cur.feedback = json.dumps(r["penilaian"])
    meter.record(db, owner, "sidang", acc)
    if not last:
        db.add(SidangTurn(session_id=sid, idx=cur.idx + 1, question=r["pertanyaan"]))
        db.commit()
    else:
        db.commit()
        _close(db, s, _summary(db, s, _turns(db, sid), context, chapters))
    return _ser(s, _turns(db, sid))


@router.post("/{sid}/finish")
def finish(sid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _mine(db, u, sid)
    if s.status != "aktif":
        raise HTTPException(409, "Sidang ini sudah selesai.")
    turns = _turns(db, sid)
    try:
        dt, context, chapters = _context(db, u, s.mode)
    except HTTPException:
        dt, context, chapters = s.doc_type, "(tulisan tidak tersedia)", [(c["key"], c["title"]) for c in ROADMAP[s.doc_type]]
    _close(db, s, _summary(db, s, turns, context, chapters) if any(t.answer for t in turns) else None)
    return _ser(s, turns)


@router.get("/{sid}")
def detail(sid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _mine(db, u, sid)
    return _ser(s, _turns(db, sid))


@router.delete("/{sid}")
def delete(sid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _mine(db, u, sid)
    db.execute(sql_delete(SidangTurn).where(SidangTurn.session_id == sid))  # anak dulu, eksplisit: FK cascade tak berlaku di SQLite, dan tanpa relationship() urutan hapus ORM tidak terjamin
    db.delete(s)
    db.commit()
    return {"ok": True}
