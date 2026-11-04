"""Sumber contoh: OpenAlex, Crossref, DOAJ (selalu aktif); Semantic Scholar & CORE (opsional, lihat config).
Hanya metadata + tautan; abstrak ditampilkan jika lisensinya terbuka (CC-BY/CC0). Sumber dipanggil paralel dan hasilnya
di-cache beberapa jam (Redis bila ada, selain itu memori proses)."""
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import httpx

from .config import settings
from .ratelimit import redis_client

HEADERS = {"User-Agent": f"Dospem/0.3 (mailto:{settings.contact_email})"}
OPEN_LIC = re.compile(r"cc[-_ ]?by|cc0|creativecommons\.org/(licenses/by|publicdomain)", re.I)
NC_ND = re.compile(r"(?:^|[-_/ ])(?:nc|nd)(?:[-_/. ]|$)|by[-_ ]?(?:nc|nd)", re.I)  # CC-BY-NC/ND tetap dianggap tertutup untuk abstrak
LIMITS = {"source": 20, "external_id": 200, "doi": 200, "venue": 300, "url": 500, "license": 200}  # = panjang kolom models.Example
CACHE_TTL = 6 * 3600
_mem: dict = {}


def is_open(lic: str | None) -> bool:
    return bool(lic and OPEN_LIC.search(lic) and not NC_ND.search(lic.split("creativecommons.org")[-1]))


def clip(it: dict) -> dict:
    """Potong ke batas kolom & buang NUL (PostgreSQL menolaknya)."""
    return {k: (v.replace("\x00", "")[:LIMITS[k]] if isinstance(v, str) and k in LIMITS else v) for k, v in it.items()}


def _doi(d: str | None) -> str | None:
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", d.strip(), flags=re.I).lower() or None if d else None


def _year(v) -> int | None:
    try:
        return int(str(v)[:4])
    except (TypeError, ValueError):
        return None


def _abstract(inv: dict | None) -> str | None:
    if not inv:
        return None
    pos = {p: w for w, ps in inv.items() for p in ps}
    return " ".join(pos[i] for i in sorted(pos))


# ---------- OpenAlex ----------
def norm_openalex(w: dict) -> dict:
    loc = w.get("primary_location") or {}
    return {"source": "openalex", "external_id": w["id"].rsplit("/", 1)[-1], "doi": _doi(w.get("doi")),
            "title": w.get("title") or "(tanpa judul)",
            "authors": [a["author"]["display_name"] for a in w.get("authorships", []) if (a.get("author") or {}).get("display_name")][:6],
            "year": w.get("publication_year"), "venue": (loc.get("source") or {}).get("display_name"),
            "url": (w.get("open_access") or {}).get("oa_url") or loc.get("landing_page_url") or w.get("doi"),
            "license": loc.get("license"), "abstract": _abstract(w.get("abstract_inverted_index"))}


def openalex(q, lang, oa_only, limit):
    flt = ",".join(f for f in ["is_oa:true" if oa_only else "", f"language:{lang}" if lang else ""] if f)
    p = {"search": q, "per-page": limit, "mailto": settings.contact_email,
         "select": "id,doi,title,publication_year,authorships,primary_location,open_access,abstract_inverted_index"}
    if flt:
        p["filter"] = flt
    r = httpx.get("https://api.openalex.org/works", params=p, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return [norm_openalex(w) for w in r.json().get("results", [])]


# ---------- Crossref ----------
def norm_crossref(it: dict) -> dict:
    lic = (it.get("license") or [{}])[0].get("URL")
    parts = (it.get("issued") or {}).get("date-parts") or [[None]]
    return {"source": "crossref", "external_id": it["DOI"].lower(), "doi": it["DOI"].lower(),
            "title": (it.get("title") or ["(tanpa judul)"])[0],
            "authors": [" ".join(filter(None, [a.get("given"), a.get("family")])) for a in it.get("author", [])][:6],
            "year": (parts[0] or [None])[0], "venue": (it.get("container-title") or [None])[0],
            "url": it.get("URL"), "license": lic, "abstract": None}


def crossref(q, lang, oa_only, limit):
    p = {"query": q, "rows": limit * 3 if oa_only else limit, "mailto": settings.contact_email,
         "filter": "type:journal-article", "select": "DOI,title,author,issued,container-title,license,URL"}
    r = httpx.get("https://api.crossref.org/works", params=p, headers=HEADERS, timeout=15)
    r.raise_for_status()
    items = [norm_crossref(i) for i in r.json()["message"].get("items", [])]
    return [i for i in items if is_open(i["license"])][:limit] if oa_only else items


# ---------- DOAJ (jurnal akses terbuka; tanpa kunci) ----------
LANGNAME = {"id": "indonesian", "en": "english"}


def norm_doaj(r: dict) -> dict:
    b = r.get("bibjson") or {}
    ids = {i.get("type"): i.get("id") for i in b.get("identifier", []) if isinstance(i, dict)}
    jr = b.get("journal") or {}
    lic = next((l.get("url") or l.get("type") for l in (jr.get("license") or []) if isinstance(l, dict) and (l.get("url") or l.get("type"))), None)
    links = [l for l in b.get("link", []) if isinstance(l, dict) and l.get("url")]
    url = next((l["url"] for l in links if l.get("type") == "fulltext"), None) or (links[0]["url"] if links else None)
    return {"source": "doaj", "external_id": str(r["id"]), "doi": _doi(ids.get("doi")), "title": b.get("title") or "(tanpa judul)",
            "authors": [a["name"] for a in b.get("author", []) if isinstance(a, dict) and a.get("name")][:6], "year": _year(b.get("year")),
            "venue": jr.get("title"), "url": url, "license": lic, "abstract": b.get("abstract"), "lang": jr.get("language") or []}


def doaj(q, lang, oa_only, limit):
    clean = re.sub(r'[+\-=&|><!(){}\[\]^"~*?:\\/]', " ", q).strip()  # karakter khusus Lucene
    if not clean:
        return []
    r = httpx.get("https://doaj.org/api/search/articles/" + quote(clean, safe=""),
                  params={"page": 1, "pageSize": limit * 3 if lang else limit}, headers=HEADERS, timeout=15)
    r.raise_for_status()
    items = [norm_doaj(x) for x in r.json().get("results", [])]
    if lang:
        want = LANGNAME.get(lang, lang).lower()
        items = [i for i in items if any(want in str(x).lower() for x in i["lang"])]
    return items[:limit]


# ---------- Semantic Scholar (opsional) ----------
def norm_s2(p: dict) -> dict:
    oa, ext, base = p.get("openAccessPdf") or {}, p.get("externalIds") or {}, p.get("url") or ""
    return {"source": "semanticscholar", "external_id": p["paperId"], "doi": _doi(ext.get("DOI")), "title": p.get("title") or "(tanpa judul)",
            "authors": [a["name"] for a in p.get("authors", []) if a.get("name")][:6], "year": p.get("year"), "venue": p.get("venue") or None,
            "url": oa.get("url") or (base + "?utm_source=api" if base else None), "license": oa.get("license"), "abstract": None}


def semanticscholar(q, lang, oa_only, limit):
    h = {**HEADERS, **({"x-api-key": settings.semantic_scholar_api_key} if settings.semantic_scholar_api_key else {})}
    p = {"query": q, "limit": limit, "fields": "title,authors,year,venue,externalIds,openAccessPdf,url"}
    if oa_only:
        p["openAccessPdf"] = ""
    r = httpx.get("https://api.semanticscholar.org/graph/v1/paper/search", params=p, headers=h, timeout=15)
    r.raise_for_status()
    items = [norm_s2(x) for x in r.json().get("data", [])]
    return [i for i in items if i["license"] or i["url"]] if not oa_only else [i for i in items if i["url"]]


# ---------- CORE (opsional; butuh kunci) ----------
def norm_core(w: dict) -> dict:
    return {"source": "core", "external_id": str(w["id"]), "doi": _doi(w.get("doi")), "title": w.get("title") or "(tanpa judul)",
            "authors": [a["name"] for a in w.get("authors", []) if isinstance(a, dict) and a.get("name")][:6], "year": w.get("yearPublished"),
            "venue": next((j.get("title") for j in (w.get("journals") or []) if isinstance(j, dict) and j.get("title")), None),
            "url": w.get("downloadUrl") or f"https://core.ac.uk/works/{w['id']}", "license": None, "abstract": None}


def core(q, lang, oa_only, limit):
    r = httpx.get("https://api.core.ac.uk/v3/search/works", params={"q": q, "limit": limit},
                  headers={**HEADERS, "Authorization": "Bearer " + settings.core_api_key}, timeout=15)
    r.raise_for_status()
    return [norm_core(w) for w in r.json().get("results", [])]


def sources() -> list[tuple]:
    """(kunci, label, fungsi) untuk sumber yang aktif. Fungsi dicari saat dipanggil agar mudah di-monkeypatch."""
    out = [("openalex", "OpenAlex", openalex), ("crossref", "Crossref", crossref), ("doaj", "DOAJ (jurnal terbuka)", doaj)]
    if settings.semantic_scholar_enabled:
        out.append(("semanticscholar", "Semantic Scholar", semanticscholar))
    if settings.core_enabled and settings.core_api_key:
        out.append(("core", "CORE", core))
    return out


# ---------- cache ----------
def _cget(key: str):
    try:
        r = redis_client()
        if r:
            v = r.get("sch:" + key)
            return json.loads(v) if v else None
    except Exception:
        pass
    hit = _mem.get(key)
    return hit[1] if hit and hit[0] > time.time() else None


def _cset(key: str, val) -> None:
    try:
        r = redis_client()
        if r:
            r.setex("sch:" + key, CACHE_TTL, json.dumps(val))
            return
    except Exception:
        pass
    if len(_mem) > 300:
        _mem.clear()
    _mem[key] = (time.time() + CACHE_TTL, val)


def _run(label, fn, args):
    try:
        return fn(*args), None
    except httpx.HTTPStatusError as e:
        return [], f"{label} sedang membatasi permintaan; coba lagi sebentar" if e.response.status_code == 429 else f"{label} sedang tidak dapat dihubungi"
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        return [], f"{label} sedang tidak dapat dihubungi"


def search(q, source="all", lang="", oa_only=True, limit=8):
    names = ",".join(k for k, _, _ in sources())
    ck = hashlib.sha1(f"{q.lower().strip()}|{source}|{lang}|{oa_only}|{limit}|{names}".encode()).hexdigest()
    if (hit := _cget(ck)) is not None:
        return hit["items"], hit["warn"]
    chosen = [s for s in sources() if source in ("all", s[0])]
    if not chosen:
        return [], []
    with ThreadPoolExecutor(max_workers=len(chosen)) as ex:  # paralel: total waktu = sumber terlambat, bukan jumlahnya
        futs = [ex.submit(_run, label, fn, (q, lang, oa_only, limit)) for _, label, fn in chosen]
        done = [f.result() for f in futs]
    warn = [w for _, w in done if w]
    lists = [r for r, _ in done]
    items = [lst[i] for i in range(max((len(x) for x in lists), default=0)) for lst in lists if i < len(lst)]  # selang-seling antar sumber
    seen, out = set(), []
    for it in items:
        k = it["doi"] or (it["source"], it["external_id"])
        if k not in seen:
            seen.add(k)
            out.append(it)
    if not warn:
        _cset(ck, {"items": out, "warn": warn})
    return out, warn


def links(q: str) -> list[dict]:
    """Tautan pencarian ke layanan tanpa API publik. Pola URL SINTA/Garuda bisa berubah; basisnya ada di config."""
    qq = quote(q.strip(), safe="")
    return [{"key": "gscholar", "name": "Google Scholar", "url": f"https://scholar.google.com/scholar?q={qq}&hl=id"},
            {"key": "garuda", "name": "Garuda", "url": f"{settings.garuda_base}/documents?q={qq}"},
            {"key": "sinta", "name": "SINTA", "url": f"{settings.sinta_base}/articles?q={qq}"}]
