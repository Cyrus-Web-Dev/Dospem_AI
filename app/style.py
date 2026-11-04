"""Fase 4 · tahap 2: gaya selingkung. Aturan per kampus/jurusan disimpan sebagai JSON (divalidasi),
lalu memengaruhi: cek ejaan (check), checklist & target kata (apply_roadmap), dan konteks komentar/analisis AI (llm._ctx)."""
import json
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from . import eyd
from .auth import current_admin, current_user, current_user_opt
from .db import get_db
from .models import Institution, Membership, StylePref, StyleTemplate, User
from .roadmap import ROADMAP

router = APIRouter(prefix="/api")
admin = [Depends(current_admin)]


class ChapterRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    extra_checklist: list[str] = Field(default_factory=list, max_length=8)
    min_words: int | None = Field(None, ge=0, le=50000)
    max_words: int | None = Field(None, ge=0, le=50000)


class Margins(BaseModel):
    model_config = ConfigDict(extra="forbid")
    top: float = Field(4.0, ge=1, le=6)
    left: float = Field(4.0, ge=1, le=6)
    bottom: float = Field(3.0, ge=1, le=6)
    right: float = Field(3.0, ge=1, le=6)


class FormatRules(BaseModel):
    """Format dokumen untuk ekspor Word. Bawaan = pola umum skripsi di Indonesia; WAJIB dicocokkan dengan pedoman kampus."""
    model_config = ConfigDict(extra="forbid")
    font: str = Field("Times New Roman", min_length=2, max_length=60, pattern=r"^[\w .\-]+$")
    size_pt: int = Field(12, ge=8, le=16)
    line_spacing: float = Field(1.5, ge=1.0, le=3.0)
    margin_cm: Margins = Field(default_factory=Margins)
    justify: bool = True
    first_line_indent_cm: float = Field(1.25, ge=0, le=3)
    paper: Literal["a4", "f4", "letter"] = "a4"
    page_number: Literal["bottom_center", "top_right", "none"] = "bottom_center"


class StyleRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: FormatRules = Field(default_factory=FormatRules)
    notes: str = Field("", max_length=600)
    citation_style: Literal["apa", "ieee", "none"] = "none"
    forbid_first_person: bool = False
    max_sentence_words: int | None = Field(None, ge=10, le=200)
    replacements: dict[str, str] = Field(default_factory=dict, max_length=50)
    chapters: dict[str, ChapterRule] = Field(default_factory=dict)

    @field_validator("chapters")
    @classmethod
    def _chapter_keys(cls, v):
        plain = {c["key"] for chs in ROADMAP.values() for c in chs}
        for k in v:
            doc, _, key = k.partition(".")
            if not (k in plain or (key and key in {c["key"] for c in ROADMAP.get(doc, [])})):
                raise ValueError(f"kunci bab tidak dikenal: '{k}'. Pakai nama bab (mis. pendahuluan) atau jenis.bab (mis. laporan_pkl.profil)")
        return v


def parse_rules(raw: dict) -> dict:
    try:
        return StyleRules.model_validate(raw).model_dump()
    except ValidationError as e:
        f = e.errors()[0]
        raise HTTPException(422, f"Aturan tidak valid di '{'.'.join(map(str, f['loc'])) or 'rules'}': {f['msg']}")


def current_rules(u: User | None = Depends(current_user_opt), db: Session = Depends(get_db)) -> dict | None:
    if not u:
        return None
    raw = db.scalar(select(StyleTemplate.rules).join(StylePref, StylePref.template_id == StyleTemplate.id).where(StylePref.user_id == u.id))
    return json.loads(raw) if raw else None


FP = re.compile(r"\b(saya|aku|kami|kita)\b", re.I)
NUM = re.compile(r"\[\d+(?:\s*[,–-]\s*\d+)*\]")
AUTH = re.compile(r"\([A-Z][^()\n]{1,80}?,\s*(?:19|20)\d{2}[a-z]?\)")
SENT = re.compile(r"[^.!?\n]+[.!?]?")


def _issue(text, s, e, sug, msg):
    return {"start": s, "end": e, "text": text[s:e], "suggestion": sug, "rule": "selingkung", "severity": "style", "message": msg}


def check(text: str, rules: dict) -> list[dict]:
    out = []
    if rules.get("forbid_first_person"):
        out += [_issue(text, m.start(), m.end(), "peneliti", "Pedoman kampus meminta bentuk impersonal (mis. 'peneliti', 'penelitian ini').") for m in FP.finditer(text)]
    if (mx := rules.get("max_sentence_words")):
        for m in SENT.finditer(text):
            ws = list(re.finditer(r"\S+", m.group()))
            if len(ws) > mx:
                out.append(_issue(text, m.start() + ws[-3].start(), m.start() + ws[-1].end(), "",
                                  f"Kalimat ini {len(ws)} kata; pedoman kampus menyarankan maksimal {mx}. Bisakah dipecah?"))
    cs = rules.get("citation_style")
    if cs == "apa":
        out += [_issue(text, m.start(), m.end(), "", "Pedoman kampus memakai gaya APA: tulis (Nama, tahun), bukan nomor.") for m in NUM.finditer(text)]
    elif cs == "ieee":
        out += [_issue(text, m.start(), m.end(), "", "Pedoman kampus memakai gaya IEEE: gunakan rujukan bernomor [n].") for m in AUTH.finditer(text)]
    for k, v in rules.get("replacements", {}).items():
        out += [_issue(text, m.start(), m.end(), eyd._case(m.group(), v), "Istilah ini diganti sesuai pedoman kampus.")
                for m in re.finditer(rf"\b{re.escape(k)}\b", text, re.I)]
    return out


def chapter_rule(rules: dict | None, doc_type: str | None, key: str) -> dict:
    """Aturan bab untuk satu jenis dokumen. Kunci 'laporan_pkl.pendahuluan' lebih diutamakan daripada 'pendahuluan'
    (yang berlaku untuk semua jenis dokumen yang memiliki bab bernama sama)."""
    ch = (rules or {}).get("chapters", {})
    return ch.get(f"{doc_type}.{key}") or ch.get(key) or {}


def apply_roadmap(chapters: list[dict], rules: dict | None, doc_type: str | None = None) -> list[dict]:
    if not rules:
        return chapters
    out = []
    for c in chapters:
        r = chapter_rule(rules, doc_type, c["key"])
        extra = r.get("extra_checklist", [])
        out.append({**c, "checklist": c["checklist"] + extra, "extra": extra, "min_words": r.get("min_words"),
                    "max_words": r.get("max_words"), "notes": rules.get("notes", "")})
    return out


# ---------- Mahasiswa ----------
def _available(db: Session, u: User):
    inst = select(Membership.institution_id).where(Membership.user_id == u.id)
    return db.execute(select(StyleTemplate, Institution.name).outerjoin(Institution, Institution.id == StyleTemplate.institution_id)
                      .where(or_(StyleTemplate.institution_id.is_(None), StyleTemplate.institution_id.in_(inst)))
                      .order_by(StyleTemplate.name)).all()


@router.get("/style/templates")
def templates(u: User = Depends(current_user), db: Session = Depends(get_db)):
    pref = db.get(StylePref, u.id)
    return {"current": pref.template_id if pref else None,
            "templates": [{"id": t.id, "name": t.name, "institution": n, "major": t.major, "notes": json.loads(t.rules).get("notes", "")} for t, n in _available(db, u)]}


class PrefIn(BaseModel):
    template_id: int | None = None


@router.put("/style/me")
def choose(b: PrefIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if b.template_id is None:
        db.execute(delete(StylePref).where(StylePref.user_id == u.id))
    else:
        if b.template_id not in {t.id for t, _ in _available(db, u)}:
            raise HTTPException(404, "Gaya tidak tersedia untukmu")
        pref = db.get(StylePref, u.id)
        if pref:
            pref.template_id = b.template_id
        else:
            db.add(StylePref(user_id=u.id, template_id=b.template_id))
    db.commit()
    return {"ok": True}


# ---------- Admin ----------
class StyleIn(BaseModel):
    name: str = Field(min_length=3, max_length=160)
    institution_id: int | None = None
    major: str | None = Field(None, max_length=160)
    rules: dict


class TestIn(BaseModel):
    rules: dict
    text: str = Field(max_length=5000)


def _save(t: StyleTemplate, b: StyleIn, db: Session):
    if b.institution_id and not db.get(Institution, b.institution_id):
        raise HTTPException(404, "Kampus tidak ditemukan")
    t.name, t.institution_id, t.major = b.name.strip(), b.institution_id, b.major
    t.rules = json.dumps(parse_rules(b.rules), ensure_ascii=False)
    db.add(t)
    db.commit()
    return {"id": t.id}


@router.get("/admin/style", dependencies=admin)
def admin_list(db: Session = Depends(get_db)):
    rows = db.execute(select(StyleTemplate, Institution.name).outerjoin(Institution, Institution.id == StyleTemplate.institution_id).order_by(StyleTemplate.id.desc()))
    return [{"id": t.id, "name": t.name, "institution_id": t.institution_id, "institution": n, "major": t.major, "rules": json.loads(t.rules)} for t, n in rows]


@router.post("/admin/style", dependencies=admin)
def admin_create(b: StyleIn, db: Session = Depends(get_db)):
    return _save(StyleTemplate(), b, db)


@router.put("/admin/style/{tid}", dependencies=admin)
def admin_update(tid: int, b: StyleIn, db: Session = Depends(get_db)):
    t = db.get(StyleTemplate, tid)
    if not t:
        raise HTTPException(404, "Gaya tidak ditemukan")
    return _save(t, b, db)


@router.delete("/admin/style/{tid}", dependencies=admin)
def admin_delete(tid: int, db: Session = Depends(get_db)):
    db.execute(delete(StylePref).where(StylePref.template_id == tid))
    db.execute(delete(StyleTemplate).where(StyleTemplate.id == tid))
    db.commit()
    return {"ok": True}


@router.post("/admin/style/test", dependencies=admin)
def admin_test(b: TestIn):
    return {"issues": eyd.check(b.text, check(b.text, parse_rules(b.rules)))}
