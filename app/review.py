"""Tinjauan seluruh bab ala dosen pembimbing, tanpa batas "beberapa kalimat".

1) POST /api/review  : laporan DETERMINISTIK atas draf tersimpan (gratis, tanpa kuota): ejaan EYD V, kata tidak baku, pleonasme dan
   pemborosan kata, tanda baca, kalimat/paragraf terlalu panjang, pedoman kampus. Hasilnya juga memuat daftar BAGIAN bab untuk tahap AI.
2) POST /api/review/section : pembacaan AI atas SATU bagian (±2.800 karakter). Klien memanggilnya berurutan sehingga bab sepanjang
   puluhan halaman bisa dibaca tanpa satu permintaan yang lama. Tiap bagian: cache per isi (bagian yang tak berubah gratis), kuota
   harian terpisah ("review"), kuota dikembalikan bila AI gagal, dan pagar anggaran harian berlaku.
AI hanya memberi komentar dan pertanyaan; temuan yang menulis ulang kalimat atau menunjuk kutipan yang tidak ada di teks dibuang.
"""
import hashlib
import re
from bisect import bisect_right
from collections import Counter

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import eyd, llm, meter, obs, quota, richtext, style
from .auth import owner
from .config import settings
from .db import get_db
from .models import Draft
from .roadmap import ROADMAP

router = APIRouter(prefix="/api/review")
KIND = "review"
MAX_ISSUES = 200
LONG_SENTENCE = 40
LONG_PARAGRAPH = 250
SENT = re.compile(r"[^.!?\n]+[.!?]?")
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
GROUP_OF = {"rujukan_silang": "rujukan", 
    "kata_baku": "baku", "ragam_santai": "santai", "di_pisah": "ejaan", "ke_pisah": "ejaan", "di_serangkai": "ejaan", "pun": "ejaan",
    "kapital_nama": "ejaan", "kapital": "ejaan", "boros": "boros", "pleonasme": "boros", "kata_ulang": "boros",
    "spasi": "tanda", "spasi_tanda": "tanda", "spasi_setelah": "tanda", "spasi_titik": "tanda", "spasi_kurung": "tanda", "tanda_ganda": "tanda",
    "placeholder": "templat", "selingkung": "kampus",
}
GROUP_LABEL = {"rujukan": "Rujukan tabel dan gambar", "boros": "Pleonasme dan pemborosan kata", "baku": "Kata tidak baku (KBBI)", "ejaan": "Ejaan dan huruf kapital (EYD V)",
               "tanda": "Tanda baca dan spasi", "santai": "Ragam santai", "templat": "Isian templat belum diganti", "kampus": "Pedoman kampus"}
GROUP_ORDER = ["boros", "rujukan", "baku", "ejaan", "tanda", "santai", "templat", "kampus"]


class ChapterIn(BaseModel):
    doc_type: str = Field(max_length=20)
    chapter_key: str = Field(max_length=40)


class SectionIn(ChapterIn):
    index: int = Field(ge=0, le=500)
    h: str = Field(min_length=6, max_length=16)


def review_limit(who) -> int:
    return settings.premium_review_quota if getattr(who, "plan", "free") == "premium" else settings.free_review_quota


def _draft(db: Session, who: str, doc_type: str, chapter_key: str) -> Draft:
    if chapter_key not in {c["key"] for c in ROADMAP.get(doc_type, [])}:
        raise HTTPException(404, "Jenis tugas atau bab tidak dikenal")
    d = db.scalar(select(Draft).where(Draft.owner == who, Draft.doc_type == doc_type, Draft.chapter_key == chapter_key))
    if not d or not (d.content or "").strip():
        raise HTTPException(400, "Bab ini masih kosong. Unggah file atau tulis dulu isinya.")
    return d


def _h(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def _hard_split(s: str, n: int) -> list[str]:
    """Satu "kalimat" tanpa tanda baca yang melebihi n karakter dipotong pada spasi terdekat (tidak di tengah kata)."""
    out = []
    while len(s) > n:
        cut = s.rfind(" ", 0, n)
        cut = cut if cut >= n // 2 else n
        out.append(s[:cut].rstrip())
        s = s[cut:].lstrip()
    return out + [s] if s else out


def _units(text: str, target: int) -> list[str]:
    """Paragraf dan tabel sebagai satuan: tabel tidak dipotong di tengah (kecuali sangat panjang, dipotong per baris)."""
    units, tbl = [], []

    def flush():
        nonlocal tbl
        if not tbl:
            return
        block = "\n".join(tbl)
        if len(block) <= target * 1.15:
            units.append(block)
        else:
            cur = []
            for row in tbl:
                if cur and len("\n".join(cur)) + len(row) > target:
                    units.append("\n".join(cur))
                    cur = []
                cur.append(row)
            if cur:
                units.append("\n".join(cur))
        tbl = []

    for ln in text.split("\n"):
        t = ln.strip()
        if richtext.is_row(t):
            tbl.append(t)
            continue
        flush()
        if t:
            units.append(t)
    flush()
    return units


def split_sections(text: str, target: int | None = None) -> list[str]:
    """Bagi bab menjadi bagian ±`target` karakter pada batas paragraf/tabel (paragraf panjang dipecah pada batas kalimat).
    Deterministik: isi yang sama selalu menghasilkan bagian yang sama, sehingga cache per bagian bekerja."""
    target = target or settings.review_section_chars
    pieces: list[str] = []
    for p in _units(text, target):
        if len(p) <= target * 1.15 or richtext.is_row(p):
            pieces.append(p)
            continue
        cur = ""
        for sent in SENT_SPLIT.split(p):
            for part in _hard_split(sent, int(target * 1.4)):
                if cur and len(cur) + len(part) + 1 > target:
                    pieces.append(cur)
                    cur = part
                else:
                    cur = f"{cur} {part}".strip()
        if cur:
            pieces.append(cur)
    secs, cur, n = [], [], 0
    for pc in pieces:
        if cur and n + len(pc) > target:
            secs.append("\n".join(cur))
            cur, n = [], 0
        cur.append(pc)
        n += len(pc) + 1
    if cur:
        if secs and n < target * 0.25:
            secs[-1] += "\n" + "\n".join(cur)
        else:
            secs.append("\n".join(cur))
    return secs


def _sections(content: str) -> list[str]:
    """Bagian bab untuk dibaca AI: HANYA prosa. Tabel menjadi penanda satu baris dan gambar '[gambar]' (lihat richtext.review_text), sehingga data tabel
    yang panjang tidak ikut dikirim, tidak dinilai sebagai kalimat, dan tidak menghabiskan token."""
    return split_sections(richtext.review_text(content))


def _prose_lines(text: str) -> list[tuple[int, str]]:
    """[(posisi awal, isi)] baris prosa: bukan baris tabel dan bukan penanda gambar. Dasar penomoran paragraf dan hitungan."""
    out, pos = [], 0
    for ln in text.split("\n"):
        t = ln.strip()
        if t and not richtext.is_row(t) and not richtext.IMG_LINE.match(t):
            out.append((pos + (len(ln) - len(ln.lstrip())), t))
        pos += len(ln) + 1
    return out


RANGE = re.compile(r"\b(Tabel|Gambar)\s+((?:\d+\.)+)(\d+)\s*(?:sampai(?:\s+dengan)?|s\.?\s?d\.?|hingga|[-–])\s*(?:(?:Tabel|Gambar)\s+)?(?:(?:\d+\.)+)?(\d+)\b", re.I)


def _ranges(nums: list[str]) -> str:
    """['3.6','3.7','3.8','3.23'] -> '3.6–3.8, 3.23' (nomor berurutan pada awalan yang sama diringkas)."""
    parts = [(tuple(int(x) for x in n.split(".")[:-1]), int(n.split(".")[-1])) for n in nums]
    out, i = [], 0
    while i < len(parts):
        j = i
        while j + 1 < len(parts) and parts[j + 1][0] == parts[i][0] and parts[j + 1][1] == parts[j][1] + 1:
            j += 1
        a, b = ".".join(map(str, parts[i][0] + (parts[i][1],))), ".".join(map(str, parts[j][0] + (parts[j][1],)))
        out.append(a if i == j else f"{a}–{b}")
        i = j + 1
    return ", ".join(out)


HEADING = re.compile(r"^\s*(?:BAB\s+[IVXLC\d]+\b|\d+(?:\.\d+)+\s+\S)", re.I)


def _is_label(t: str) -> bool:
    """Judul bab/subbab atau keterangan tabel/gambar (baris pendek tanpa kalimat uraian)."""
    if richtext.CAPTION.match(t) and t.split(None, 2)[-1][:1].isupper() and len(t) <= 200:
        return True
    return bool(HEADING.match(t)) and len(t) <= 120 and not t.rstrip().endswith((".", ",", ";", ":"))


def _crossrefs(text: str, prose_starts: list[int]) -> list[dict]:
    """Pemeriksaan tabel/gambar: tidak dirujuk di teks, nomor ganda atau melompat, dirujuk tanpa keterangan (hanya bab ini).
    Rujukan rentang ('Tabel 3.6 sampai Tabel 3.18') dihitung sah untuk semua nomor di antaranya."""
    caps = richtext.captions(text)
    if not caps:
        return []
    out = []

    def add(start, end, msg, para):
        out.append({"start": start, "end": end, "text": text[start:end], "suggestion": "", "rule": "rujukan_silang", "severity": "style", "message": msg,
                    "group": "rujukan", "paragraph": para, "before": "", "after": ""})

    cap_lines = [(c["start"], c["end"]) for c in caps]
    mentions = {(m.group(1).capitalize(), m.group(2)) for m in re.finditer(r"\b(Tabel|Gambar)\s+(\d+(?:\.\d+)+)\b", text, re.I) if not any(a <= m.start() < b for a, b in cap_lines)}
    pos_of = {}
    for m in re.finditer(r"\b(Tabel|Gambar)\s+(\d+(?:\.\d+)+)\b", text, re.I):
        if not any(a <= m.start() < b for a, b in cap_lines):
            pos_of.setdefault((m.group(1).capitalize(), m.group(2)), (m.start(), m.end()))
    for m in RANGE.finditer(text):
        if any(a <= m.start() < b for a, b in cap_lines):
            continue
        lo, hi = int(m.group(3)), int(m.group(4))
        if lo <= hi <= lo + 60:
            mentions |= {(m.group(1).capitalize(), f"{m.group(2)}{k}") for k in range(lo, hi + 1)}
    seen: dict[tuple[str, str], dict] = {}
    unref: dict[str, list[dict]] = {"Tabel": [], "Gambar": []}
    for c in caps:
        k = (c["label"], c["number"])
        para = bisect_right(prose_starts, c["start"])
        if k in seen:
            add(c["start"], c["end"], f"{c['label']} {c['number']} bernomor sama dengan keterangan sebelumnya. Nomor tabel/gambar harus unik.", para)
            continue
        seen[k] = c
        if k not in mentions:
            unref[c["label"]].append(c)
    for label, lst in unref.items():
        if not lst:
            continue
        first = lst[0]
        para = bisect_right(prose_starts, first["start"])
        if len(lst) <= 5:
            for c in lst:
                add(c["start"], c["end"], f"{label} {c['number']} belum dirujuk di teks. Sebutkan dan jelaskan {label.lower()} ini di badan tulisan sebelum menampilkannya.", bisect_right(prose_starts, c["start"]))
        else:
            rg = _ranges([c["number"] for c in lst])
            seg = rg.split(", ")[0]
            ex = f"{label} {seg.split('–')[0]} sampai {label} {seg.split('–')[1]}" if "–" in seg else f"{label} {seg}"
            add(first["start"], first["end"], f"{len(lst)} {label.lower()} belum dirujuk di teks: {label} {rg}. Sebutkan tiap {label.lower()} di badan tulisan, boleh dengan rujukan rentang (mis. “{ex}”). Catatan ini menunjuk yang pertama.", para)
    for label in ("Tabel", "Gambar"):
        nums = [tuple(int(x) for x in n.split(".")) for (lb, n) in seen if lb == label]
        by_prefix: dict[tuple, list[int]] = {}
        for n in nums:
            by_prefix.setdefault(n[:-1], []).append(n[-1])
        for pre, seq in by_prefix.items():
            seq.sort()
            miss = [x for x in range(1, seq[-1] + 1) if x not in seq]
            if miss and len(miss) <= 3:
                last = seen[(label, ".".join(map(str, pre + (seq[-1],))))]
                add(last["start"], last["end"], f"Nomor {label} {'.'.join(map(str, pre + (miss[0],)))} terlewat (urutan nomor {label.lower()} tidak berurutan).", bisect_right(prose_starts, last["start"]))
    common = Counter(tuple(int(x) for x in n.split("."))[:-1] for (_, n) in seen).most_common(1)
    if common:
        main = ".".join(map(str, common[0][0]))
        for (lb, nu), (st, en) in pos_of.items():
            if nu.rsplit(".", 1)[0] == main and (lb, nu) not in seen:
                add(st, en, f"{lb} {nu} dirujuk tetapi tidak ada keterangannya di bab ini. Periksa nomornya, atau tambahkan keterangan {lb.lower()} tersebut.", bisect_right(prose_starts, st))
    return out


def report(text: str, rules: dict | None = None) -> dict:
    """Laporan deterministik. Murni fungsi teks -> dict (mudah diuji). Hitungan kata/paragraf/kalimat hanya atas prosa (bukan baris tabel)."""
    text = text.replace("\x00", "")
    issues = eyd.check(text, style.check(text, rules) if rules else None)
    pl = _prose_lines(text)
    starts = [p for p, _ in pl]
    words = len(" ".join(t for _, t in pl).split())
    body = [(p, t) for p, t in pl if not _is_label(t)]  # judul dan keterangan tabel/gambar bukan paragraf uraian: tak ikut hitungan kalimat/paragraf
    paras = [t for _, t in body]
    sents = [(pos + m.start(), m.group().strip()) for pos, t in body for m in SENT.finditer(t) if m.group().strip()]
    lens = [len(s.split()) for _, s in sents]
    long_sents = sorted(((n, i) for i, n in enumerate(lens) if n > LONG_SENTENCE), reverse=True)
    all_issues = issues + _crossrefs(text, starts)
    all_issues.sort(key=lambda i: i["start"])
    tbl_lines, pos = [], 0
    for ln in text.split("\n"):
        if richtext.is_row(ln.strip()):
            tbl_lines.append((pos, pos + len(ln)))
        pos += len(ln) + 1
    tbl_starts = [a for a, _ in tbl_lines]

    def in_table(s: int) -> bool:
        i = bisect_right(tbl_starts, s) - 1
        return i >= 0 and tbl_lines[i][0] <= s < tbl_lines[i][1]

    out_issues = []
    for i in all_issues[:MAX_ISSUES]:
        s, e = i["start"], i["end"]
        if "group" not in i:
            i = {**i, "group": GROUP_OF.get(i["rule"], "ejaan"), "paragraph": bisect_right(starts, s),
                 "before": text[max(0, s - 40):s].rsplit("\n", 1)[-1].lstrip(), "after": text[e:e + 40].split("\n")[0]}
        out_issues.append({**i, "in_table": in_table(s)})
    by_group = Counter(i.get("group") or GROUP_OF.get(i["rule"], "ejaan") for i in all_issues)
    common = Counter((i["text"].lower(), i["suggestion"]) for i in issues if i["rule"] in ("kata_baku", "boros", "pleonasme", "ragam_santai"))
    secs = _sections(text)
    return {
        "stats": {"words": words, "paragraphs": len(paras), "sentences": len(sents),
                  "avg_sentence_words": round(sum(lens) / len(lens), 1) if lens else 0,
                  "long_paragraphs": sum(len(p.split()) > LONG_PARAGRAPH for p in paras),
                  "one_sentence_paragraphs": sum(len(SENT_SPLIT.split(p.strip())) < 2 and len(p.split()) > 5 for p in paras),
                  "first_person": len(re.findall(r"\b(?:saya|aku|kami|kita)\b", " ".join(paras), re.I)),
                  "tables": sum(1 for k, _ in richtext.parse(text) if k == "table"), "images": len(richtext.hashes(text)),
                  "issues_per_100w": round(len(all_issues) * 100 / words, 1) if words else 0},
        "total": len(all_issues), "shown": len(out_issues),
        "groups": [{"group": g, "label": GROUP_LABEL[g], "count": by_group[g]} for g in GROUP_ORDER if by_group[g]],
        "common": [{"text": t, "suggestion": s, "count": c} for (t, s), c in common.most_common(8)],
        "issues": out_issues,
        "long_sentences": [{"words": n, "paragraph": bisect_right(starts, sents[i][0]), "preview": " ".join(sents[i][1].split()[:14]) + "…"} for n, i in long_sents[:10]],
        "long_sentence_total": len(long_sents),
        "sections": [{"index": i, "h": _h(t), "words": len(" ".join(ln for ln in t.split("\n") if not ln.startswith("[")).split()), "preview": " ".join(t.split()[:10]) + "…"} for i, t in enumerate(secs)],
    }


@router.post("")
def review(b: ChapterIn, who=Depends(owner), db: Session = Depends(get_db), rules: dict | None = Depends(style.current_rules)):
    d = _draft(db, who, b.doc_type, b.chapter_key)
    r = report(d.content, rules)
    cached, est = 0, 0
    secs = _sections(d.content)
    ch = next((c for c in ROADMAP[b.doc_type] if c["key"] == b.chapter_key), None)
    ctx = llm._ctx(ch, rules, b.doc_type) if ch else ""
    sysp = llm.review_system(b.doc_type)
    for sec, text in zip(r["sections"], secs):  # tandai bagian yang sudah pernah dibaca AI (gratis diulang)
        sec["cached"] = meter.cache_get(db, who, meter.cache_key("review", b.doc_type, b.chapter_key, text, rules)) is not None
        cached += sec["cached"]
        if not sec["cached"]:  # perkiraan token satu panggilan: prompt (instruksi + konteks + bagian) + keluaran sekitar sepertiga batas
            est += meter.estimate(sysp, ctx, text) + settings.llm_max_tokens_review // 3
    limit = review_limit(who)
    r["ai"] = {"limit": limit, "left": max(0, limit - quota.used(db, who, KIND)), "sections": len(secs), "cached": cached,
               "to_pay": len(secs) - cached, "est_tokens": est, "premium": getattr(who, "plan", "free") == "premium"}
    return r


def _locate(content: str, quote: str) -> tuple[int, int] | None:
    """Posisi kutipan di draf (spasi/baris baru dinormalkan). None bila tidak ketemu."""
    q = " ".join((quote or "").rstrip("…. ").split())
    if len(q) < 3:
        return None
    m = re.search(r"\s+".join(map(re.escape, q.split())), content, re.I)
    return (m.start(), m.end()) if m else None


@router.post("/section")
def review_section(b: SectionIn, who=Depends(owner), db: Session = Depends(get_db), rules: dict | None = Depends(style.current_rules)):
    d = _draft(db, who, b.doc_type, b.chapter_key)
    secs = _sections(d.content)
    if b.index >= len(secs) or _h(secs[b.index]) != b.h:
        raise HTTPException(409, "Isi bab berubah sejak tinjauan dimulai. Mulai tinjauan lagi agar komentar menunjuk bagian yang benar.")
    text, limit = secs[b.index], review_limit(who)
    key = meter.cache_key("review", b.doc_type, b.chapter_key, text, rules)

    def done(findings: list[dict], cached: bool) -> dict:
        seen, out = set(), []
        for f in findings:
            sig = (f["quote"].lower(), f["type"])
            if sig in seen:
                continue
            seen.add(sig)
            loc = _locate(d.content, f["quote"]) if f["quote"] else None
            out.append({**f, "start": loc[0] if loc else None, "end": loc[1] if loc else None, "match": d.content[loc[0]:loc[1]] if loc else None})
        return {"index": b.index, "total": len(secs), "findings": out, "cached": cached, "left": max(0, limit - quota.used(db, who, KIND))}

    hit = meter.cache_get(db, who, key)
    if hit is not None:  # bagian yang sama persis: tanpa memanggil AI dan tanpa memotong kuota
        meter.record_hit(db, who, KIND)
        return done(hit, True)
    meter.check_budget(db)
    if quota.take(db, who, limit, KIND) is None:
        raise HTTPException(429, "Batas pembacaan AI hari ini habis" + ("" if getattr(who, "plan", "free") == "premium" else " (Premium memberi batas lebih besar)")
                            + ". Pemeriksaan ejaan dan pleonasme otomatis tetap gratis; bagian yang sudah dibaca tetap tersimpan.")
    try:
        with meter.call(KIND) as acc:
            findings = llm.review_section(text, b.doc_type, b.chapter_key, rules, b.index + 1, len(secs))
    except llm.GuardError as e:
        quota.refund(db, who, KIND)
        raise HTTPException(422, str(e))
    except (httpx.HTTPError, llm.ProviderError) as e:
        obs.llm_error(KIND, e)
        quota.refund(db, who, KIND)
        raise HTTPException(502, "Layanan AI sedang sibuk. Kuotamu tidak terpakai; coba lagi sebentar lagi.")
    meter.record(db, who, KIND, acc)
    meter.cache_put(db, who, KIND, key, findings)
    return done(findings, False)
