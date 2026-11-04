"""Panen metadata jurnal OJS lewat OAI-PMH (protokol resmi, gratis). Dijalankan admin; hasilnya disimpan sebagai
Example(source="oai") lalu dicari secara lokal. Abstrak hanya disimpan bila lisensinya terbuka."""
import ipaddress
import re
import socket
from urllib.parse import parse_qsl, urlparse

import httpx
from defusedxml import ElementTree as ET  # aman dari entity expansion (XML dari server pihak ketiga)

from . import scholar

NS = {"o": "http://www.openarchives.org/OAI/2.0/", "dc": "http://purl.org/dc/elements/1.1/",
      "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/"}
MAX_BYTES = 5_000_000
MAX_PAGES = 10
DOI_RE = re.compile(r"10\.\d{4,9}/\S+")
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def check_url(url: str) -> tuple[str, dict]:
    """Hanya http(s) ke alamat publik (cegah SSRF ke jaringan internal). Mengembalikan (url tanpa query, parameter bawaan)."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("URL OAI harus diawali http:// atau https://")
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValueError("Alamat server tidak ditemukan")
    for i in infos:
        ip = ipaddress.ip_address(i[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ValueError("Alamat internal tidak diizinkan")
    return p._replace(query="", fragment="").geturl(), dict(parse_qsl(p.query))


def _get(url: str, params: dict) -> bytes:
    with httpx.stream("GET", url, params=params, headers=scholar.HEADERS, timeout=20, follow_redirects=False) as r:
        r.raise_for_status()  # 3xx juga dianggap galat: pakai URL final (mis. https://)
        buf = bytearray()
        for chunk in r.iter_bytes():
            buf += chunk
            if len(buf) > MAX_BYTES:
                raise ValueError("Respons terlalu besar")
        return bytes(buf)


def parse(xml: bytes) -> tuple[list[dict], str | None]:
    root = ET.fromstring(xml)
    err = root.find("o:error", NS)
    if err is not None:
        if err.get("code") == "noRecordsMatch":
            return [], None
        raise ValueError(f"Server OAI menolak permintaan ({err.get('code')})")
    lr = root.find("o:ListRecords", NS)
    if lr is None:
        raise ValueError("Respons bukan ListRecords OAI-PMH")
    out = []
    for rec in lr.findall("o:record", NS):
        h, md = rec.find("o:header", NS), rec.find("o:metadata/oai_dc:dc", NS)
        if h is None or md is None or h.get("status") == "deleted":
            continue

        def g(tag):
            return [(e.text or "").strip() for e in md.findall("dc:" + tag, NS) if (e.text or "").strip()]
        title = g("title")[:1]
        if not title:
            continue
        ids = g("identifier")
        doi = next((scholar._doi(m.group(0)) for i in ids if (m := DOI_RE.search(i))), None)
        url = next((i for i in ids if i.startswith("http") and "doi.org" not in i), None) or next((i for i in ids if i.startswith("http")), None)
        rights = g("rights")
        lic = next((r for r in rights if r.startswith("http")), None) or (rights[0] if rights else None)
        y = next((m.group(0) for d in g("date") if (m := YEAR_RE.search(d))), None)
        desc = g("description")[:1]
        oid = (h.findtext("o:identifier", default="", namespaces=NS) or "").strip() or (url or title[0])
        out.append({"source": "oai", "external_id": oid, "doi": doi, "title": title[0], "authors": g("creator")[:6],
                    "year": int(y) if y else None, "venue": (g("source") or [""])[0].split(";")[0].strip() or None,
                    "url": url, "license": lic, "abstract": desc[0] if desc and scholar.is_open(lic) else None})
    tok = lr.find("o:resumptionToken", NS)
    return out, ((tok.text or "").strip() or None) if tok is not None else None


def harvest(base_url: str, max_records: int = 200, getter=None) -> list[dict]:
    getter = getter or _get  # dicari saat dipanggil (bukan saat definisi) agar bisa diganti di tes
    url, base = check_url(base_url)
    params = {**base, "verb": "ListRecords", "metadataPrefix": "oai_dc"}
    out: list[dict] = []
    for _ in range(MAX_PAGES):
        recs, token = parse(getter(url, params))
        out += recs
        if not token or len(out) >= max_records:
            break
        params = {**base, "verb": "ListRecords", "resumptionToken": token}
    return out[:max_records]
