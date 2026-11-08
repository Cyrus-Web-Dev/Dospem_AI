"""Pembaca berkas unggahan (.docx, .pdf, .txt, .md) -> teks polos per bab. Deterministik, tanpa AI, tanpa kuota.

Berkas dari pengguna tidak dipercaya: ukuran, jumlah halaman, dan ukuran hasil unzip dibatasi (bom zip/PDF), jenis berkas
dikenali dari isinya (bukan hanya ekstensi), dan kegagalan parsing selalu menjadi ParseError berpesan ramah (tanpa isi
berkas di pesan galat). Yang TIDAK ikut dibaca (dan dilaporkan lewat `warnings`): tabel, gambar, catatan kaki, dan PDF hasil pindai.
"""
import hashlib
import io
import re
import struct
import zipfile
from collections import Counter

from . import richtext
from .config import settings

ALLOWED = (".docx", ".pdf", ".txt", ".md")
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
TOC_LINE = re.compile(r"^.{3,}?(?:\.{5,}|(?:\. ){5,}|…{3,})\s*[0-9ivxIVX]+\s*$")  # baris daftar isi: "1.1 Latar Belakang ..... 3"
PAGE_NO = re.compile(r"^(?:halaman\s+)?(?:\d{1,4}|[ivxlcIVXLC]{1,6}|-\s*\d{1,4}\s*-)$", re.I)
STRUCT = re.compile(r"^(?:\||!\[|[-*•]\s|\d{1,3}[.)]\s)")  # baris terstruktur (tabel, gambar, butir daftar): tidak boleh disambung ke paragraf
MAX_ZIP_ENTRIES = 3000
MAX_ZIP_UNPACKED = 80 * 1024 * 1024
MAX_IMAGES = 80
MAX_PIXELS = 80_000_000
NS_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NS_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
NS_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
NS_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
NS_SHAPE = ("{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}wsp", "{http://schemas.microsoft.com/office/word/2010/wordprocessingGroup}wgp")


class ParseError(ValueError):
    """Berkas tidak bisa dibaca; pesannya aman ditampilkan ke pengguna."""


def clean_name(name: str) -> str:
    n = CTRL.sub("", (name or "").replace("\\", "/").rsplit("/", 1)[-1]).strip()
    return n[:120] or "berkas"


def _ext(name: str) -> str:
    n = name.lower()
    return next((e for e in ALLOWED if n.endswith(e)), "")


def _clean_line(ln: str) -> str:
    return re.sub(r"[ \t]+", " ", CTRL.sub("", ln.replace("\u00a0", " ").replace("\u200b", ""))).strip()


def _kind(ln: str) -> str:
    return "t" if ln.startswith("|") else "i" if ln.startswith("![") else "l"


def _tidy(text: str, per_line: bool = False) -> str:
    """Seragamkan: buang karakter kendali, rapikan spasi, satu baris kosong antarparagraf. Baris terstruktur (tabel, gambar, butir
    daftar) dipertahankan per baris; baris prosa yang berurutan disambung menjadi satu paragraf (kecuali per_line)."""
    lines = [_clean_line(ln) for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    blocks: list[str] = []
    prose: list[str] = []
    struct: list[str] = []

    def flush():
        nonlocal prose, struct
        if prose:
            blocks.append(" ".join(prose))
        if struct:
            blocks.append("\n".join(struct))
        prose, struct = [], []

    for ln in lines:
        if not ln:
            flush()
        elif STRUCT.match(ln):
            if prose:
                flush()
            if struct and _kind(struct[-1]) != _kind(ln):
                flush()  # tabel, gambar, dan butir daftar tidak digabung dalam satu balok
            struct.append(ln)
        else:
            if struct:
                flush()
            if per_line:
                blocks.append(ln)
            else:
                prose.append(ln)
    flush()
    return "\n\n".join(blocks)


def _strip_toc(lines: list[str]) -> tuple[list[str], int]:
    kept = [ln for ln in lines if not TOC_LINE.match(ln)]
    return kept, len(lines) - len(kept)


# ---------- gambar ----------
def sniff_image(b: bytes) -> str | None:
    """Jenis gambar dari isinya (bukan ekstensi). SVG sengaja tidak diterima (bisa memuat skrip)."""
    if b.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if b.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    return None


def image_dims(b: bytes, mime: str) -> tuple[int, int] | None:
    """(lebar, tinggi) dari header; None bila tidak terbaca. Dipakai menolak gambar berpiksel raksasa (beban memori peramban)."""
    try:
        if mime == "image/png" and len(b) >= 24:
            return struct.unpack(">II", b[16:24])
        if mime == "image/gif" and len(b) >= 10:
            return struct.unpack("<HH", b[6:10])
        if mime == "image/webp" and b[12:16] == b"VP8X" and len(b) >= 30:
            return 1 + int.from_bytes(b[24:27], "little"), 1 + int.from_bytes(b[27:30], "little")
        if mime == "image/jpeg":
            i = 2
            while i + 9 < len(b):
                if b[i] != 0xFF:
                    i += 1
                    continue
                m = b[i + 1]
                if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
                    i += 2
                    continue
                n = struct.unpack(">H", b[i + 2:i + 4])[0]
                if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
                    h, w = struct.unpack(">HH", b[i + 5:i + 9])
                    return w, h
                i += 2 + n
    except (struct.error, IndexError):
        return None
    return None


def image_id(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


# ---------- .txt / .md ----------
def _plain(data: bytes) -> tuple[str, list[str]]:
    warns = []
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        s = data.decode("utf-16", errors="replace")
    else:
        try:
            s = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            s = data.decode("cp1252", errors="replace")
            warns.append("Penyandian berkas bukan UTF-8; huruf tertentu mungkin tampil salah.")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return _tidy(s, per_line="\n\n" not in s), warns  # tanpa baris kosong sebagai pemisah, tiap baris prosa dianggap satu paragraf


# ---------- .docx ----------
def _body_items(el):
    """Paragraf dan tabel pada tingkat badan dokumen, berurutan; isi kontrol konten (w:sdt) ikut dibaca."""
    for ch in el.iterchildren():
        tag = ch.tag.rsplit("}", 1)[-1]
        if tag in ("p", "tbl"):
            yield tag, ch
        elif tag == "sdt":
            content = ch.find(NS_W + "sdtContent")
            if content is not None:
                yield from _body_items(content)


def _roman(n: int) -> str:
    out = ""
    for v, r in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= v:
            out, n = out + r, n - v
    return out


def _fmt_num(n: int, fmt: str) -> str:
    if fmt == "decimalZero":
        return f"{n:02d}"
    if fmt in ("lowerLetter", "upperLetter"):
        c = chr(97 + (n - 1) % 26)
        return c.upper() if fmt == "upperLetter" else c
    if fmt in ("lowerRoman", "upperRoman"):
        r = _roman(n)
        return r if fmt == "upperRoman" else r.lower()
    return str(n)


class _Lists:
    """Penomoran daftar Word (numbering.xml). Mengembalikan (jenis, label) per paragraf berdaftar: butir -> '-', bernomor -> '1.' dst.
    Penghitung dipisah per numId (Word membuat numId baru untuk tiap daftar yang dimulai ulang)."""

    def __init__(self, doc):
        self.nums, self.abstr, self.counters = {}, {}, {}
        try:
            root = doc.part.numbering_part.element
        except Exception:  # tanpa numbering.xml: tidak ada daftar otomatis
            return
        for a in root.findall(NS_W + "abstractNum"):
            lv = {}
            for l in a.findall(NS_W + "lvl"):
                nf, st, tx = l.find(NS_W + "numFmt"), l.find(NS_W + "start"), l.find(NS_W + "lvlText")
                try:
                    lv[int(l.get(NS_W + "ilvl", 0))] = (nf.get(NS_W + "val") if nf is not None else "decimal", int(st.get(NS_W + "val")) if st is not None else 1, tx.get(NS_W + "val") if tx is not None else "")
                except (TypeError, ValueError):
                    continue
            self.abstr[a.get(NS_W + "abstractNumId")] = lv
        for n in root.findall(NS_W + "num"):
            a = n.find(NS_W + "abstractNumId")
            self.nums[n.get(NS_W + "numId")] = a.get(NS_W + "val") if a is not None else None

    def of(self, p_el, style_el=None):
        """(numId, ilvl) dari paragraf, atau dari gaya paragrafnya bila gaya itu berdaftar; None bila bukan butir daftar."""
        for el in (p_el, style_el):
            ppr = el.find(NS_W + "pPr") if el is not None else None
            num = ppr.find(NS_W + "numPr") if ppr is not None else None
            if num is not None:
                nid, il = num.find(NS_W + "numId"), num.find(NS_W + "ilvl")
                nid = nid.get(NS_W + "val") if nid is not None else None
                if nid and nid != "0":
                    return nid, int(il.get(NS_W + "val")) if il is not None else 0
        return None

    def label(self, nid: str, ilvl: int) -> tuple[str, str]:
        lv = self.abstr.get(self.nums.get(nid), {})
        fmt, start, txt = lv.get(ilvl, ("decimal", 1, ""))
        if fmt in ("bullet", "none"):
            return "bullet", "-"
        c = self.counters.setdefault(nid, {})
        c[ilvl] = start if ilvl not in c else c[ilvl] + 1
        for k in [k for k in c if k > ilvl]:
            del c[k]
        sub = lambda m: _fmt_num(c.get(int(m.group(1)) - 1, lv.get(int(m.group(1)) - 1, ("decimal", 1, ""))[1]), lv.get(int(m.group(1)) - 1, ("decimal",))[0])  # noqa: E731
        return "number", (re.sub(r"%(\d)", sub, txt) if txt else f"{c[ilvl]}.").strip()


def _clean_alt(s: str | None) -> str:
    return re.sub(r"[\[\]()\r\n\t]+", " ", s or "").strip()[:120]


def _docx(data: bytes) -> tuple[str, list[str], dict]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except zipfile.BadZipFile as e:
        raise ParseError("Berkas .docx rusak atau bukan dokumen Word yang valid.") from e
    if len(infos) > MAX_ZIP_ENTRIES or sum(i.file_size for i in infos) > MAX_ZIP_UNPACKED:
        raise ParseError("Isi berkas .docx tidak wajar (terlalu besar setelah dibuka). Simpan ulang dari Word lalu coba lagi.")
    if "word/document.xml" not in zf.namelist():
        raise ParseError("Berkas ini bukan dokumen Word (.docx) yang valid.")
    from docx import Document  # impor lambat: hanya dibutuhkan saat ada unggahan
    from docx.text.paragraph import Paragraph
    images: dict[str, dict] = {}
    st = Counter()
    try:
        doc = Document(io.BytesIO(data))
        lists = _Lists(doc)
        related = doc.part.related_parts

        def style_el(p):
            try:
                s = Paragraph(p, doc).style
                return s.element if s is not None else None
            except Exception:
                return None

        def para(p_el, in_cell=False) -> tuple[str, str]:
            """(jenis, teks): jenis 'p' paragraf, 'h' judul bernomor otomatis, 'li' butir daftar. Teks sudah diberi nomor/penanda daftar."""
            raw = Paragraph(p_el, doc).text.replace("\t", " ")
            # di sel tabel, pindah baris lunak (Shift+Enter) tetap menjadi baris baru (<br>); di paragraf biasa menjadi spasi
            text = "\n".join(x for x in (_clean_line(x) for x in raw.split("\n")) if x) if in_cell else _clean_line(raw.replace("\n", " "))
            sty = style_el(p_el)
            heading = sty is not None and (sty.get(NS_W + "styleId") or "").lower().startswith(("heading", "judul"))
            ref = lists.of(p_el, sty)
            if not text or ref is None:
                return "p", text
            nid, il = ref
            kind, lab = lists.label(nid, il)
            if heading:
                return "h", f"{lab.rstrip('.')} {text}" if kind == "number" and not re.match(r"^\d+(\.\d+)*\s", text) else text
            return "li", "  " * il + f"{lab} {text}"

        def images_of(p_el) -> list[str]:
            out = []
            for dr in p_el.iter(NS_W + "drawing"):
                dp = next(dr.iter(NS_WP + "docPr"), None)
                alt = _clean_alt((dp.get("descr") or dp.get("title")) if dp is not None else "")
                for bl in dr.iter(NS_A + "blip"):
                    rid = bl.get(NS_R + "embed")
                    part = related.get(rid) if rid else None
                    if part is None:
                        st["img_skipped"] += 1
                        continue
                    blob = part.blob
                    mime = sniff_image(blob)
                    dims = image_dims(blob, mime) if mime else None
                    if not mime or len(blob) > settings.asset_max_mb * 1024 * 1024 or (dims and (dims[0] * dims[1] > MAX_PIXELS or max(dims) > 14000)) or len(images) >= MAX_IMAGES and image_id(blob) not in images:
                        st["img_skipped"] += 1
                        continue
                    iid = image_id(blob)
                    images.setdefault(iid, {"data": blob, "mime": mime, "alt": alt})
                    out.append(f"![{alt}](asset:{iid})")
            return out

        def table(tbl) -> str | None:
            rows = []
            for tr in tbl.findall(NS_W + "tr"):
                cells = []
                for tc in tr.findall(NS_W + "tc"):
                    pr = tc.find(NS_W + "tcPr")
                    gs = pr.find(NS_W + "gridSpan") if pr is not None else None
                    vm = pr.find(NS_W + "vMerge") if pr is not None else None
                    span = int(gs.get(NS_W + "val", 1)) if gs is not None else 1
                    if gs is not None or vm is not None:
                        st["merged"] += 1
                    st["nested"] += len(tc.findall(NS_W + "tbl"))
                    st["cell_img"] += len(list(tc.iter(NS_W + "drawing")))
                    txt = [para(p, True)[1] for p in tc.findall(NS_W + "p")]
                    cells.append("\n".join(t for t in txt if t) if not (vm is not None and vm.get(NS_W + "val") != "restart") else "")
                    cells += [""] * (max(span, 1) - 1)
                if cells:
                    rows.append(cells)
            return richtext.make_table(rows) if any(c.strip() for r in rows for c in r) else None

        blocks: list[str] = []
        cur_list: list[str] = []

        def flush_list():
            nonlocal cur_list
            if cur_list:
                blocks.append("\n".join(cur_list))
            cur_list = []

        for tag, el in _body_items(doc.element.body):
            if tag == "tbl":
                flush_list()
                t = table(el)
                if t:
                    blocks.append(t)
                    st["tables"] += 1
                continue
            kind, text = para(el)
            if text and kind == "li":
                cur_list.append(text)
            else:
                flush_list()
                if text and TOC_LINE.match(text):
                    st["toc"] += 1
                elif text:
                    blocks.append(text)
            for line in images_of(el):
                flush_list()
                blocks.append(line)
                st["images"] += 1
        flush_list()
        body = doc.element.body
        st["shapes"] = sum(1 for _ in body.iter(*NS_SHAPE)) + sum(1 for _ in body.iter(NS_W + "pict")) + sum(1 for _ in body.iter(NS_W + "object"))
        st["notes"] = sum(1 for _ in body.iter(NS_W + "footnoteReference", NS_W + "endnoteReference"))
    except ParseError:
        raise
    except Exception as e:  # python-docx melempar beragam galat untuk berkas rusak
        raise ParseError("Berkas .docx tidak bisa dibaca. Simpan ulang dari Word sebagai .docx lalu coba lagi.") from e
    warns = []
    if st["img_skipped"]:
        warns.append(f"{st['img_skipped']} gambar dilewati (format tidak didukung seperti EMF/WMF, resolusi atau ukuran terlalu besar). Simpan ulang gambarnya sebagai PNG lalu sisipkan kembali.")
    if st["shapes"]:
        warns.append(f"{st['shapes']} objek gambar Word (bentuk, kotak teks, SmartArt, atau objek tertanam) tidak bisa diimpor. Jika itu diagram, salin sebagai gambar (PNG) lalu sisipkan kembali di Word dan unggah ulang.")
    if st["nested"]:
        warns.append(f"{st['nested']} tabel di dalam sel tabel lain tidak ikut diimpor.")
    if st["cell_img"]:
        warns.append(f"{st['cell_img']} gambar di dalam sel tabel dilewati.")
    if st["merged"]:
        warns.append("Ada sel tabel yang digabung; isinya ditulis di sel pertama dan sel gabungannya dikosongkan.")
    if st["notes"]:
        warns.append(f"{st['notes']} catatan kaki/akhir tidak diimpor. Pindahkan isinya ke badan teks bila perlu.")
    if st["toc"]:
        warns.append(f"{st['toc']} baris daftar isi dibuang. Daftar isi dibuat otomatis saat Ekspor Word.")
    return "\n\n".join(blocks), warns, {"images": images, "tables": st["tables"], "image_count": st["images"]}


# ---------- .pdf ----------
def _pdf(data: bytes) -> tuple[str, list[str], dict]:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError
    try:
        rd = PdfReader(io.BytesIO(data), strict=False)
        if rd.is_encrypted:
            raise ParseError("PDF ini dikunci dengan kata sandi. Buka kuncinya dulu, atau simpan ulang sebagai .docx.")
        n = len(rd.pages)
        if n > settings.upload_max_pages:
            raise ParseError(f"PDF terlalu panjang ({n} halaman; maks {settings.upload_max_pages}). Unggah per bab, bukan seluruh dokumen.")
        pages = [(p.extract_text() or "") for p in rd.pages]
    except ParseError:
        raise
    except (PyPdfError, ValueError, KeyError, TypeError, AttributeError, OSError, RecursionError, NotImplementedError) as e:
        raise ParseError("PDF tidak bisa dibaca. Coba simpan ulang PDF-nya, atau unggah versi .docx.") from e
    per_page = [[ln.strip() for ln in pg.replace("\r", "\n").split("\n") if ln.strip()] for pg in pages]
    # Header/footer: baris tepi halaman yang sama di >= 3 halaman (angka dinormalkan) dibuang.
    norm = lambda s: re.sub(r"\d+", "#", s.lower())  # noqa: E731
    edges = lambda ls: (ls[:1] + ls[-2:]) if len(ls) >= 6 else []  # noqa: E731  halaman pendek tak dianggap punya kepala/kaki
    edge = Counter(norm(ln) for ls in per_page for ln in set(edges(ls)))
    repeated = {k for k, c in edge.items() if c >= 3}
    lines, dropped = [], 0
    for ls in per_page:
        ends = edges(ls)
        for ln in ls:
            if PAGE_NO.match(ln) or (norm(ln) in repeated and ln in ends):
                dropped += 1
                continue
            lines.append(ln)
        lines.append("")  # batas halaman
    lines, toc = _strip_toc(lines)
    text = _reflow(lines)
    if not text.strip():
        raise ParseError("PDF ini tidak memuat teks yang bisa dibaca (mungkin hasil pindai/foto). Unggah versi .docx, atau ketik/tempel teksnya.")
    warns = []
    if sum(len(p) for p in pages) < 80 * max(1, n):
        warns.append("Teks yang terbaca sangat sedikit untuk jumlah halamannya; sebagian halaman mungkin berupa gambar.")
    if dropped:
        warns.append(f"{dropped} baris nomor halaman/kepala/kaki halaman dibuang.")
    if toc:
        warns.append(f"{toc} baris daftar isi dibuang.")
    warns.append("Dari PDF hanya teks yang terbaca: tabel menjadi teks biasa, dan gambar/diagram tidak ikut. Untuk tabel dan diagram, unggah versi .docx.")
    warns.append("Teks PDF disusun ulang menjadi paragraf secara otomatis: periksa batas paragraf dan persamaan.")
    return text, warns, {"images": {}, "tables": 0, "image_count": 0}


_END = re.compile(r"[.!?:;)”\"]$")
_START_NEW = re.compile(r"^(?:[A-Z0-9(“\"•–-]|bab\b)")
_HEADING = re.compile(r"^(?:BAB\b|\d+(?:\.\d+)*\s)")


def _reflow(lines: list[str]) -> str:
    """PDF memberi satu baris per baris visual. Sambung baris yang melanjutkan kalimat; baris yang berakhir tanda
    akhir kalimat dan diikuti huruf kapital/angka dianggap awal paragraf baru bila baris itu pendek (akhir paragraf)."""
    paras, cur = [], ""
    for ln in lines:
        if not ln:  # batas halaman: kalimat yang belum selesai tetap disambung ke halaman berikutnya
            if cur and _END.search(cur):
                paras.append(cur)
                cur = ""
            continue
        if not cur:
            cur = ln
        elif _END.search(cur) and _START_NEW.match(ln) and (len(cur) < 90 or _HEADING.match(ln)):
            paras.append(cur)
            cur = ln
        elif _HEADING.match(ln) and len(cur) < 90:
            paras.append(cur)
            cur = ln
        else:
            cur = cur + ("" if cur.endswith("-") and ln[:1].islower() else " ") + ln
    if cur:
        paras.append(cur)
    return _tidy("\n\n".join(paras))


# ---------- pintu masuk ----------
def extract(data: bytes, filename: str) -> dict:
    """Kembalikan {text, kind, filename, warnings}. Melempar ParseError bila berkas tidak dapat diterima."""
    name = clean_name(filename)
    ext = _ext(name)
    if not ext:
        if name.lower().endswith(".doc"):
            raise ParseError("Format .doc lama belum didukung. Buka di Word lalu simpan sebagai .docx.")
        raise ParseError("Format berkas tidak didukung. Gunakan .docx, .pdf, .txt, atau .md.")
    if not data:
        raise ParseError("Berkas kosong.")
    if len(data) > settings.upload_max_mb * 1024 * 1024:
        raise ParseError(f"Berkas terlalu besar (maks {settings.upload_max_mb} MB).")
    if ext == ".docx" and not data.startswith(b"PK"):
        raise ParseError("Isi berkas bukan dokumen Word (.docx) yang valid.")
    if ext == ".pdf" and not data[:1024].lstrip().startswith(b"%PDF"):
        raise ParseError("Isi berkas bukan PDF yang valid.")
    if ext in (".txt", ".md") and (data.startswith((b"PK", b"%PDF")) or (b"\x00" in data[:4096] and data[:2] not in (b"\xff\xfe", b"\xfe\xff"))):
        raise ParseError("Isi berkas bukan teks polos. Gunakan ekstensi yang sesuai dengan jenis berkasnya.")
    if ext == ".docx":
        text, warns, extra = _docx(data)
    elif ext == ".pdf":
        text, warns, extra = _pdf(data)
    else:
        text, warns = _plain(data)
        extra = {"images": {}, "tables": sum(1 for k, _ in richtext.parse(text) if k == "table"), "image_count": 0}
    if not text.strip():
        raise ParseError("Tidak ada teks yang bisa dibaca dari berkas ini.")
    return {"text": text, "kind": ext[1:], "filename": name, "warnings": warns, **extra}
