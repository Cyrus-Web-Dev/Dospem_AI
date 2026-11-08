"""Fase 4 · tahap 3: analitik. Hanya agregat — tidak ada isi tulisan mahasiswa yang dikembalikan.
Statistik isi (kemajuan bab, kesalahan umum) dihitung dari sampel draf terbaru dan di-cache sampai ada draf yang berubah."""
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import campus, eyd, richtext
from .auth import current_admin
from .config import settings
from .db import get_db
from .models import Draft, Institution, Payment, Supervision, UsageDaily, User
from .quota import today
from .roadmap import DOC_BY_KEY, ROADMAP

router = APIRouter(prefix="/api")
MIN_N = 3            # minimal sampel agar "bab tersulit" dinyatakan
SAMPLE_DRAFTS = 1000  # draf terbaru yang dihitung kemajuannya
CHECK_DRAFTS = 150    # dari sampel itu, berapa yang diperiksa ejaannya
MAX_CHARS = 20000
LABEL = {"kata_baku": "Kata tidak baku", "di_pisah": "'di' kata depan (harus terpisah)", "di_serangkai": "'di-' kata kerja pasif (harus serangkai)",
         "boros": "Frasa boros", "kata_ulang": "Kata terulang", "spasi": "Spasi ganda", "spasi_tanda": "Spasi sebelum tanda baca",
         "spasi_setelah": "Tanda baca tanpa spasi", "kapital": "Huruf kapital awal kalimat", "placeholder": "Isian templat belum diganti",
         "ke_pisah": "'ke'/'dari' kata depan (harus terpisah)", "pun": "Partikel 'pun'", "ragam_santai": "Ragam santai/tidak formal",
         "kapital_nama": "Nama diri tanpa huruf kapital", "tanda_ganda": "Tanda baca ganda", "spasi_kurung": "Spasi di dalam kurung",
         "spasi_titik": "Titik tanpa spasi sesudahnya"}
_cache: dict = {}


def _content_stats(db: Session, owners: list[str] | None, key: str) -> dict:
    cond = Draft.owner.in_(owners) if owners is not None else None
    q = select(func.count(Draft.id), func.max(Draft.updated_at))
    sig = (tuple(db.execute(q.where(cond) if cond is not None else q).one()), hash(tuple(sorted(owners))) if owners is not None else 0)
    hit = _cache.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    q = select(Draft.doc_type, Draft.chapter_key, func.substr(Draft.content, 1, MAX_CHARS)).order_by(Draft.updated_at.desc()).limit(SAMPLE_DRAFTS)
    rows = db.execute(q.where(cond) if cond is not None else q).all()
    agg = defaultdict(lambda: {"words": [], "done": 0, "issues": 0, "checked_words": 0})
    rules, words, sug, rule_drafts, checked = Counter(), Counter(), {}, Counter(), 0
    for dt, ck, content in rows:
        w = richtext.words(content)
        if w == 0:
            continue
        a = agg[(dt, ck)]
        a["words"].append(w)
        a["done"] += campus._state(w) == "terisi"
        if checked < CHECK_DRAFTS:
            checked += 1
            issues = eyd.check(content)
            a["issues"] += len(issues)
            a["checked_words"] += w
            for r in {i["rule"] for i in issues}:
                rule_drafts[r] += 1
            for i in issues:
                rules[i["rule"]] += 1
                if i["rule"] == "kata_baku":
                    k = i["text"].lower()
                    words[k] += 1
                    sug[k] = i["suggestion"].lower()
    chapters = []
    for dt, chs in ROADMAP.items():
        for c in chs:
            a = agg.get((dt, c["key"]))
            if not a:
                continue
            n = len(a["words"])
            chapters.append({"doc_type": dt, "doc_label": DOC_BY_KEY[dt]["label"], "key": c["key"], "title": c["title"], "students": n, "completed": a["done"],
                             "completion_rate": round(a["done"] / n, 2), "median_words": int(statistics.median(a["words"])),
                             "issues_per_100w": round(a["issues"] * 100 / a["checked_words"], 1) if a["checked_words"] else None})
    ok = [c for c in chapters if c["students"] >= MIN_N]
    pick = lambda c: {k: c[k] for k in ("doc_type", "doc_label", "title", "students", "completion_rate", "issues_per_100w")}
    hardest = pick(min(ok, key=lambda c: (c["completion_rate"], -c["students"]))) if ok else None
    noisy = [c for c in ok if c["issues_per_100w"] is not None]
    out = {"chapters": chapters, "hardest": hardest,
           "noisiest": pick(max(noisy, key=lambda c: c["issues_per_100w"])) if noisy else None,
           "top_issues": [{"rule": r, "label": LABEL.get(r, r), "count": n, "drafts": rule_drafts[r]} for r, n in rules.most_common(8)],
           "top_words": [{"word": k, "suggestion": sug[k], "count": n} for k, n in words.most_common(6)],
           "sampled": {"drafts": len(rows), "checked": checked, "capped": len(rows) >= SAMPLE_DRAFTS}}
    if len(_cache) > 100:
        _cache.clear()
    _cache[key] = (sig, out)
    return out


def _local_date(dt: datetime):
    return dt.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(settings.timezone)).date()


@router.get("/admin/analytics", dependencies=[Depends(current_admin)])
def admin_analytics(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    days = [today() - timedelta(days=i) for i in range(13, -1, -1)]
    new = Counter(_local_date(c) for c in db.scalars(select(User.created_at).where(User.created_at >= now - timedelta(days=16))))
    use = {(d, k): n for d, k, n in db.execute(select(UsageDaily.day, UsageDaily.kind, UsageDaily.count).where(UsageDaily.day >= days[0]))}
    count = lambda col, *w: db.scalar(select(func.count()).select_from(col).where(*w)) or 0
    amount, orders = db.execute(select(func.coalesce(func.sum(Payment.amount), 0), func.count())
                                .where(Payment.status == "paid", Payment.paid_at >= now - timedelta(days=30))).one()
    return {
        "totals": {"users": count(User), "premium_active": count(User, User.premium_until > now), "institutions": count(Institution),
                   "supervisions": count(Supervision, Supervision.status == "approved"), "drafts": count(Draft),
                   "active_7d": db.scalar(select(func.count(func.distinct(Draft.owner))).where(Draft.updated_at >= now - timedelta(days=7))) or 0},
        "series": {"days": [d.isoformat() for d in days], "new_users": [new.get(d, 0) for d in days],
                   "coach": [max(0, use.get((d, "coach"), 0)) for d in days], "analisis": [max(0, use.get((d, "analisis"), 0)) for d in days]},
        "revenue_30d": {"amount": int(amount), "orders": int(orders)},
        **_content_stats(db, None, "admin"),
    }


@router.get("/dosen/analytics")
def dosen_analytics(u: User = Depends(campus.current_dosen), db: Session = Depends(get_db)):
    sts = campus.students(u=u, db=db)
    now = datetime.utcnow()
    recent = lambda s: bool(s["last_active"]) and now - datetime.fromisoformat(s["last_active"]) <= timedelta(days=7)
    totals = {"students": len(sts), "stuck": sum(1 for s in sts if s["stuck"]), "active_7d": sum(1 for s in sts if recent(s)),
              "avg_words": int(sum(s["total_words"] for s in sts) / len(sts)) if sts else 0}
    return {"totals": totals, **_content_stats(db, [f"u{s['student']['id']}" for s in sts], f"dosen{u.id}")}
