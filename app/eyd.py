"""Pemeriksa ejaan berbasis aturan (deterministik, gratis, cepat) — acuan: EYD Edisi V (2022), KBBI Daring.
LLM hanya dipakai untuk hal yang tidak bisa diaturankan (kalimat boros, logika). Kamus ada di kamus.py."""
import re

from . import kamus as K
from .kamus import NONBAKU  # noqa: F401  (kompatibilitas)

WORD = re.compile(r"[A-Za-z]+(?:['’\-][A-Za-z]+)*")
PROTECT = re.compile(r"https?://\S+|www\.\S+|\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+|\b10\.\d{4,9}/\S+|`[^`\n]*`")
EN = frozenset("the and of is are to in that this with for by on was were be as an from or not can".split())


def _case(src: str, sug: str) -> str:
    if len(src) > 1 and src.isupper():
        return sug.upper()
    return sug[:1].upper() + sug[1:] if src[:1].isupper() else sug


def _rx(words: str, flags: int = re.I) -> re.Pattern:
    return re.compile(r"\b(" + words + r")\b", flags)


def _phrase(table: dict) -> re.Pattern:
    keys = sorted(table, key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(r"[ \t]+".join(map(re.escape, k.split())) for k in keys) + r")\b", re.I)


FRASA_RX, BOROS_RX = _phrase(K.FRASA), _phrase(K.BOROS)
_norm = lambda s: " ".join(s.lower().split())


def _token(t: str, s: int, e: int) -> bool:
    """Token yang tampak seperti kode/nama berkas/ID (respon_data, $respon, photo.jpg): jangan diperiksa."""
    p, n = t[s - 1] if s else "", t[e] if e < len(t) else ""
    return bool((p and p in "$_@#/\\") or (n and n in "_(=") or (n == "." and e + 1 < len(t) and t[e + 1].isalpha())  # `"" in "abc"` itu True: wajib dicek tak kosong
                or (p == "." and s >= 2 and t[s - 2].isalnum()))


def _issue(t, s, e, sug, rule, sev, msg):
    return {"start": s, "end": e, "text": t[s:e], "suggestion": sug, "rule": rule, "severity": sev, "message": msg}


def _scan_words(text: str) -> list[dict]:
    """Satu kali lintas kata untuk semua aturan berbasis kamus."""
    out = []
    for m in WORD.finditer(text):
        w, lw = m.group(0), m.group(0).lower()
        s, e = m.span()
        if lw in K.NONBAKU:
            rule, sev, msg, sug = "kata_baku", "error", "Bentuk baku: lihat saran (KBBI)", K.NONBAKU[lw]
        elif lw in K.SANTAI:
            rule, sev, sug = "ragam_santai", "style", K.SANTAI[lw]
            msg = "Ragam santai. Dalam tulisan ilmiah pakai bentuk baku (abaikan jika ini kutipan langsung, mis. hasil wawancara)."
        elif lw in K.PUN_PISAH:
            rule, sev, msg, sug = "pun", "error", "Partikel 'pun' ditulis terpisah (EYD V)", K.PUN_PISAH[lw]
        elif w == lw and lw in K.KAPITAL_NAMA:
            rule, sev, msg, sug = "kapital_nama", "error", "Nama diri (hari, bulan, negara, bahasa, kota) diawali huruf kapital", lw.capitalize()
            if _token(text, s, e):
                continue
            out.append(_issue(text, s, e, sug, rule, sev, msg))
            continue
        else:
            continue
        if not _token(text, s, e):
            out.append(_issue(text, s, e, _case(w, sug), rule, sev, msg))
    return out


def _protected(text: str) -> list[tuple[int, int]]:
    """Bagian yang tidak diperiksa: URL, surel, DOI, kode satu baris, dan baris berbahasa Inggris (mis. abstrak)."""
    spans = [m.span() for m in PROTECT.finditer(text)]
    pos = 0
    for line in text.split("\n"):
        ws = re.findall(r"[A-Za-z']+", line)
        if len(ws) >= 6 and sum(w.lower() in EN for w in ws) / len(ws) >= 0.2:
            spans.append((pos, pos + len(line)))
        pos += len(line) + 1
    return spans


def _mk(rx, rule, sev, msg, fn):
    return rx, rule, sev, msg, fn


RULES = [
    _mk(FRASA_RX, "kata_baku", "error", "Bentuk baku: lihat saran (KBBI)",
        lambda m: (m.start(), m.end(), _case(m.group(0), K.FRASA[_norm(m.group(0))]))),
    _mk(_rx(r"(?:ke(?:" + K.KE_PLACE + r")|dari(?:" + K.DARI_PLACE + r"))"), "ke_pisah", "error",
        "'ke' dan 'dari' sebagai kata depan ditulis terpisah",
        lambda m: (m.start(), m.end(), _case(m.group(0), re.sub(r"^(ke|dari)", r"\1 ", m.group(0), flags=re.I)))),
    _mk(re.compile(r"\bdi(?:" + K.DI_PLACE + r")\b", re.I), "di_pisah", "error", "'di' sebagai kata depan ditulis terpisah",
        lambda m: (m.start(), m.end(), _case(m.group(0), "di " + m.group(0)[2:]))),
    _mk(re.compile(r"\bdi (" + K.DI_VERB + r")(kan|i)?\b", re.I), "di_serangkai", "error",
        "'di-' pada kata kerja pasif ditulis serangkai", lambda m: (m.start(), m.end(), m.group(0).replace(" ", "", 1))),
    _mk(re.compile(r"\b(" + "|".join(K.PUN_GABUNG) + r")[ \t]+pun\b", re.I), "pun", "error",
        "Pada kata ini 'pun' ditulis serangkai (EYD V)", lambda m: (m.start(), m.end(), _case(m.group(0), m.group(1).lower() + "pun"))),
    _mk(BOROS_RX, "boros", "style", "Frasa ini bisa dipersingkat tanpa mengubah makna",
        lambda m: (m.start(), m.end(), _case(m.group(0), K.BOROS[_norm(m.group(0))]))),
    _mk(re.compile(r"\b([^\W\d_]{2,}) \1\b", re.I), "kata_ulang", "style", "Kata terulang tanpa sengaja?",
        lambda m: (m.start(), m.end(), m.group(1))),
    _mk(re.compile(r"[ ]{2,}"), "spasi", "error", "Spasi ganda", lambda m: (m.start(), m.end(), " ")),
    _mk(re.compile(r" +([,;:!?]|\.(?![A-Za-z0-9]))"), "spasi_tanda", "error", "Tidak ada spasi sebelum tanda baca",
        lambda m: (m.start(), m.end(), m.group(1))),
    _mk(re.compile(r"\[(?:isi|sebutkan|tulis|masukkan|nama|tambahkan|jelaskan)\b[^\]]{0,300}\]", re.I), "placeholder", "style",
        "Ini masih isian templat. Lengkapi atau hapus sebelum tulisan dikirim ke dosen.", lambda m: (m.start(), m.end(), "")),
    _mk(re.compile(r"[,;:](?=[A-Za-z])"), "spasi_setelah", "error", "Beri spasi setelah tanda baca",
        lambda m: (m.start(), m.end(), m.group(0) + " ")),
    _mk(re.compile(r"(?<=[a-z]{2})\.(?=[A-Z][a-z])"), "spasi_titik", "error", "Beri spasi setelah titik",
        lambda m: (m.start(), m.end(), ". ")),
    _mk(re.compile(r"(?<!\.)\.\.(?!\.)|,{2,}|;{2,}|:{2,}|[!?]{2,}"), "tanda_ganda", "error", "Tanda baca ganda",
        lambda m: (m.start(), m.end(), m.group(0)[0])),
    _mk(re.compile(r"\([ \t]+"), "spasi_kurung", "error", "Tidak ada spasi setelah kurung buka", lambda m: (m.start(), m.end(), "(")),
    _mk(re.compile(r"[ \t]+\)"), "spasi_kurung", "error", "Tidak ada spasi sebelum kurung tutup", lambda m: (m.start(), m.end(), ")")),
    _mk(re.compile(r"(?:^|[.!?]\s+)([a-z])"), "kapital", "error", "Awal kalimat memakai huruf kapital",
        lambda m: (m.start(1), m.end(1), m.group(1).upper())),
]


def check(text: str, extra: list | None = None) -> list[dict]:
    found = list(extra or [])
    built = _scan_words(text)
    for rx, rule, sev, msg, fn in RULES:
        for m in rx.finditer(text):
            s, e, sug = fn(m)
            if text[s:e] != sug:
                built.append(_issue(text, s, e, sug, rule, sev, msg))
    prot = _protected(text)
    if prot:
        built = [i for i in built if not any(i["start"] < pe and ps < i["end"] for ps, pe in prot)]
    found += built
    found.sort(key=lambda i: (i["start"], -(i["end"] - i["start"])))
    out, last = [], -1
    for i in found:  # buang yang tumpang tindih
        if i["start"] >= last:
            out.append(i)
            last = i["end"]
    return out
