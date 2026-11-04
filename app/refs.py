"""Daftar pustaka: pemformat APA 7 / IEEE dan pengecek sitasi. Murni deterministik (tanpa AI, tanpa kuota).
Penting: judul dan nama ditulis APA SEPERTI DIMASUKKAN pengguna. Pemformat tidak mengubah huruf besar/kecil judul
dan tidak bisa mengetahui urutan nama orang Indonesia; mahasiswa tetap harus memeriksa hasilnya terhadap pedoman kampus."""
import re
import unicodedata
from typing import Iterable

Seg = tuple[str, bool]  # (teks, miring?)


# ---------- nama ----------
def split_name(s: str) -> tuple[str, str]:
    """'Nama Belakang, Nama Depan' -> (belakang, depan); tanpa koma: kata terakhir dianggap nama belakang."""
    s = " ".join((s or "").split())
    if "," in s:
        fam, giv = (x.strip() for x in s.split(",", 1))
        return fam, giv
    parts = s.split(" ")
    return parts[-1], " ".join(parts[:-1])


def initials(giv: str) -> str:
    return " ".join(t[0].upper() + "." for t in re.split(r"[\s\-]+", giv.strip()) if t and t[0].isalpha())


def _apa_name(s: str) -> str:
    fam, giv = split_name(s)
    ini = initials(giv)
    return f"{fam}, {ini}" if ini else fam


def _ieee_name(s: str) -> str:
    fam, giv = split_name(s)
    ini = initials(giv)
    return f"{ini} {fam}" if ini else fam


def _apa_authors(a: list[str]) -> str:
    n = [_apa_name(x) for x in a if x.strip()]
    if len(n) > 20:
        n = n[:19] + ["…", n[-1]]
        return ", ".join(n[:-2]) + ", … " + n[-1]
    if len(n) <= 1:
        return n[0] if n else ""
    return ", ".join(n[:-1]) + (", & " if len(n) > 2 else ", & ") + n[-1]


def _ieee_authors(a: list[str]) -> str:
    n = [_ieee_name(x) for x in a if x.strip()]
    if len(n) > 6:
        return n[0] + " et al."
    if len(n) <= 2:
        return " and ".join(n)
    return ", ".join(n[:-1]) + ", and " + n[-1]


# ---------- penyusun segmen ----------
def _merge(segs: Iterable[Seg]) -> list[Seg]:
    out: list[Seg] = []
    for t, i in segs:
        if not t:
            continue
        if out and out[-1][1] == i:
            out[-1] = (out[-1][0] + t, i)
        else:
            out.append((t, i))
    return out


def plain(segs: list[Seg]) -> str:
    return "".join(t for t, _ in segs)


def _end(s: str) -> str:
    s = s.strip()
    return s if s[-1:] in ".?!" else s + "."


def _link(e: dict) -> str:
    return f"https://doi.org/{e['doi']}" if e.get("doi") else (e.get("url") or "")


def _title(t: str, italic: bool) -> list[Seg]:
    """Judul + pemisah; tanda baca penutup TIDAK ikut dimiringkan."""
    t = t.strip()
    return [(t, italic), (" " if t[-1:] in "?!." else ". ", False)] if t else []


def apa(e: dict) -> list[Seg]:
    kind, title = e.get("kind", "jurnal"), (e.get("title") or "").strip().rstrip(".")
    yr = f"({e['year']})" if e.get("year") else "(t.t.)"
    a = _apa_authors(e.get("authors") or [])
    ital = kind in ("buku", "web")
    segs: list[Seg] = ([(f"{a} {yr}. ", False)] + _title(title, ital)) if a else (_title(title, ital) + [(f"{yr}. ", False)])
    if kind == "jurnal" and e.get("venue"):
        segs += [(e["venue"], True)]
        if e.get("volume"):
            segs += [(", ", False), (e["volume"], True)]
        if e.get("issue"):
            segs += [(f"({e['issue']})", False)]
        if e.get("pages"):
            segs += [(f", {e['pages']}", False)]
        segs += [(". ", False)]
    elif e.get("publisher") or e.get("venue"):
        segs += [(_end(e.get("publisher") or e["venue"]) + " ", False)]
    segs += [(_link(e), False)]
    out = _merge(segs)
    if out:
        out[-1] = (out[-1][0].rstrip(), out[-1][1])
    return [x for x in out if x[0]]


def ieee(e: dict) -> list[Seg]:
    kind, title = e.get("kind", "jurnal"), (e.get("title") or "").strip().rstrip(".")
    a = _ieee_authors(e.get("authors") or [])
    pre = f"{a}, " if a else ""
    yr = str(e["year"]) if e.get("year") else "n.d."
    if kind == "jurnal":
        segs: list[Seg] = [(f"{pre}“{title},” ", False)]
        if e.get("venue"):
            segs += [(e["venue"], True), (", ", False)]
        tail = [f"vol. {e['volume']}" if e.get("volume") else "", f"no. {e['issue']}" if e.get("issue") else "",
                f"pp. {e['pages']}" if e.get("pages") else "", yr]
        segs += [(", ".join(t for t in tail if t), False)]
        segs += [(f", doi: {e['doi']}", False)] if e.get("doi") else []
        segs += [(".", False)]
        if not e.get("doi") and e.get("url"):
            segs += [(f" [Online]. Available: {e['url']}", False)]
    elif kind == "buku":
        segs = [(pre, False), (title, True), (f". {e['publisher']}, " if e.get("publisher") else ". ", False), (yr, False)]
        segs += [(".", False)]
    else:
        segs = [(f"{pre}“{title},” ", False)]
        if e.get("venue") or e.get("publisher"):
            segs += [((e.get("venue") or e.get("publisher")) + ", ", False)]
        segs += [(yr, False), (".", False)]
        if _link(e):
            segs += [(f" [Online]. Available: {_link(e)}", False)]
    out = _merge(segs)
    return [(t.replace("..", "."), i) for t, i in out]  # "n.d." + "." -> satu titik


def format_list(entries: list[dict], style: str) -> list[list[Seg]]:
    """APA: urut abjad penulis pertama lalu tahun. IEEE: sesuai urutan daftar (nomor = urutan)."""
    if style == "ieee":
        return [ieee(e) for e in entries]
    key = lambda e: (_norm(split_name((e.get("authors") or [e.get("title", "")])[0])[0]), e.get("year") or 9999, (e.get("title") or "").lower())
    return [apa(e) for e in sorted(entries, key=key)]


# ---------- pengecek sitasi ----------
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s).split())


Y = r"(?:19|20)\d{2}"
CAP = r"[A-ZÀ-Ý][\w'’\-]*"
PAREN = re.compile(r"\(([^()\n]{3,300})\)")
CITE = re.compile(rf"^\s*(?:lihat\s+|see\s+|mis\.\s+|e\.g\.,?\s+)?(?P<names>[A-ZÀ-Ý].*?)[,\s]*\b(?P<year>{Y})[a-z]?\b")
NARR = re.compile(rf"(?P<names>{CAP}(?:\s+{CAP})*)(?:\s+(?:dkk\.?|et\s+al\.?|&|dan|and)\s+(?:{CAP}(?:\s+{CAP})*)?)?\s+\((?P<year>{Y})[a-z]?\)")
NUMCITE = re.compile(r"\[(\d+(?:\s*[,–-]\s*\d+)*)\]")


def _first_author_tokens(names: str) -> list[str]:
    """'Budi & Ani' / 'Budi dkk.' / 'Budi, Ani' -> ['Budi']; 'Van Helheim' -> ['Van','Helheim']."""
    head = re.split(r"\s*(?:&|,|\bdan\b|\band\b|\bdkk\b|\bet\s+al\b)", names, maxsplit=1)[0]
    return head.split()


def _index(refs: list[dict]) -> dict:
    idx: dict = {}
    for r in refs:
        if r.get("authors") and r.get("year"):
            idx.setdefault((_norm(split_name(r["authors"][0])[0]), int(r["year"])), []).append(r["id"])
    return idx


def _lookup(idx: dict, toks: list[str], year: int):
    for k in range(len(toks)):  # coba sufiks terpanjang dulu: 'Menurut Budi' -> 'Budi'
        hit = idx.get((_norm(" ".join(toks[k:])), year))
        if hit:
            return hit[0]
    return None


def check_apa(text: str, refs: list[dict]) -> dict:
    idx, cited, missing = _index(refs), set(), {}
    seen_spans = []
    for m in PAREN.finditer(text):
        inner = m.group(1)
        if not re.search(Y, inner):
            continue
        for part in inner.split(";"):
            c = CITE.match(part)
            if not c:
                continue
            toks = _first_author_tokens(c["names"])
            if not toks or any(not re.fullmatch(r"[\w'’\-\.]+", t) or any(ch.isdigit() for ch in t) for t in toks):
                continue  # mis. "(Tabel 3, 2020)" bukan sitasi
            rid = _lookup(idx, toks, int(c["year"]))
            label = f"({part.strip()})"
            if rid:
                cited.add(rid)
            else:
                missing.setdefault(label, 0)
                missing[label] += 1
        seen_spans.append((m.start(), m.end()))
    for m in NARR.finditer(text):
        if any(s <= m.start() < e for s, e in seen_spans):
            continue
        toks = _first_author_tokens(m["names"])
        rid = _lookup(idx, toks, int(m["year"]))
        if rid:
            cited.add(rid)
        else:
            label = m.group(0).strip()
            missing.setdefault(label, 0)
            missing[label] += 1
    return {"cited": cited, "missing": [{"text": t, "count": n} for t, n in missing.items()]}


def check_ieee(text: str, refs: list[dict]) -> dict:
    cited, missing = set(), {}
    for m in NUMCITE.finditer(text):
        nums: list[int] = []
        for part in re.split(r"\s*,\s*", m.group(1)):
            rng = re.split(r"\s*[–-]\s*", part)
            nums += list(range(int(rng[0]), int(rng[-1]) + 1)) if len(rng) == 2 and int(rng[0]) <= int(rng[-1]) <= int(rng[0]) + 200 else [int(rng[0])]
        for n in nums:
            if 1 <= n <= len(refs):
                cited.add(refs[n - 1]["id"])
            else:
                missing.setdefault(f"[{n}]", 0)
                missing[f"[{n}]"] += 1
    return {"cited": cited, "missing": [{"text": t, "count": n} for t, n in missing.items()]}


def check(text: str, refs: list[dict], style: str, whole: bool) -> dict:
    r = (check_ieee if style == "ieee" else check_apa)(text, refs)
    unused = [x["id"] for x in refs if x["id"] not in r["cited"]] if whole else None
    return {"missing": r["missing"], "uncited": unused, "cited": len(r["cited"])}
