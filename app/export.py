"""Ekspor draf ke Word (.docx) sesuai aturan format gaya selingkung kampus (font, spasi, margin, nomor halaman),
lengkap dengan sampul, daftar isi (bidang Word), dan daftar pustaka. Hasil tetap perlu dicek terhadap pedoman kampus."""
import re
from io import BytesIO
from typing import Literal

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH as AL
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from docx.enum.table import WD_TABLE_ALIGNMENT
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import assets as asset_store, docparse, refs, richtext, style
from .auth import current_user
from .db import get_db
from .models import BibEntry, Draft, Supervision, SupervisorNote, User
from .roadmap import DOC_BY_KEY, ROADMAP
from .bib import _dict

router = APIRouter(prefix="/api")
PAPER = {"a4": (21.0, 29.7), "f4": (21.5, 33.0), "letter": (21.59, 27.94)}
ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")  # python-docx menolak karakter kontrol XML
H_BAB = re.compile(r"^\s*BAB\s+[IVXLC\d]+\b", re.I)
H_NUM = re.compile(r"^\s*(\d+(?:\.\d+)+)\s+(\S.*)$")


def clean(s: str) -> str:
    return CTRL.sub("", s or "")


LIST_LINE = re.compile(r"^(\s*)(?:([-*•])|(\d{1,3}[.)]|[a-zA-Z][.)]))\s+(\S.*)$")


def blocks(text: str) -> list[tuple[str, object]]:
    """Teks draf -> [(jenis, isi)]: 'BAB I ...' = h1, '1.1 Judul' = h2, '1.1.1 Judul' = h3, 'table' = daftar baris sel,
    'img' = (keterangan, id gambar), 'li' = (tingkat, label atau None untuk butir, teks), selain itu paragraf 'p'."""
    out: list[tuple[str, object]] = []
    for kind, v in richtext.parse(clean(text)):
        if kind == "table":
            out.append(("table", (v["rows"], v["header"])))  # type: ignore[index]
            continue
        if kind == "img":
            out.append(("img", (v["alt"], v["hash"])))  # type: ignore[index]
            continue
        s = str(v).strip()
        m = H_NUM.match(s)
        li = LIST_LINE.match(str(v).rstrip())
        if H_BAB.match(s) and len(s) <= 120 and len(s.split()) <= 14 and not s.endswith("."):
            out.append(("h1", s))
        elif m and len(s) <= 110 and not s.endswith((".", ",", ";", ":")) and m.group(2)[0].isupper():
            out.append(("h2" if m.group(1).count(".") == 1 else "h3", s))
        elif li and (li.group(2) or len(li.group(1)) or li.group(3)[:-1].isdigit()):  # butir daftar: '- x', '1. x', atau bersarang
            out.append(("li", (len(li.group(1)) // 2, li.group(3), li.group(4))))
        else:
            out.append(("p", s))
    return out


def chapter_heading(doc_type: str, title: str) -> str:
    thesis = DOC_BY_KEY[doc_type]["kind"] == "thesis"
    m = re.match(r"^Bab\s+(\d+)\s*·\s*(.+)$", title)
    if m and thesis:
        n = int(m.group(1))
        return f"BAB {ROMAN[n] if n < len(ROMAN) else n} {m.group(2).upper()}"
    return title.upper() if thesis else title


def _font(st, name: str, size: int, bold=None, italic=None):
    f = st.font
    f.name, f.size = name, Pt(size)
    f.color.rgb = RGBColor(0, 0, 0)
    if bold is not None:
        f.bold = bold
    if italic is not None:
        f.italic = italic
    rpr = st.element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.insert(0, rf)
    for k in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rf.set(qn(k), name)
    for k in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):  # tema Word menimpa font eksplisit
        rf.attrib.pop(qn(k), None)


def _field(par, instr: str, placeholder: str, dirty: bool = False):
    def fc(t):
        r = par.add_run()
        e = OxmlElement("w:fldChar")
        e.set(qn("w:fldCharType"), t)
        if dirty and t == "begin":
            e.set(qn("w:dirty"), "true")
        r._r.append(e)
    fc("begin")
    r = par.add_run()
    it = OxmlElement("w:instrText")
    it.set(qn("xml:space"), "preserve")
    it.text = instr
    r._r.append(it)
    fc("separate")
    par.add_run(placeholder)
    fc("end")


class ExportIn(BaseModel):
    doc_type: str = "skripsi"
    style: Literal["apa", "ieee"] | None = None
    title: str | None = Field(None, max_length=300)
    author: str | None = Field(None, max_length=120)
    nim: str | None = Field(None, max_length=40)
    program: str | None = Field(None, max_length=150)
    institution: str | None = Field(None, max_length=150)
    year: int | None = Field(None, ge=1990, le=2100)
    include_cover: bool = True
    include_toc: bool = True
    include_refs: bool = True


def _shade(cell, fill: str) -> None:
    pr = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear")
    sh.set(qn("w:color"), "auto")
    sh.set(qn("w:fill"), fill)
    pr.append(sh)


def _add_table(d, rows: list[list[str]], header: bool, fmt: style.FormatRules, text_w: float) -> None:
    """Tabel Word sungguhan: garis tipis, judul kolom tebal dan berulang di tiap halaman, baris tidak terpotong antarhalaman."""
    n = max(len(r) for r in rows)
    t = d.add_table(rows=len(rows), cols=n)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    size = Pt(max(9, fmt.size_pt - 2))
    t.autofit = False
    wts = [min(70, max([len(richtext.cell_text(r[ci])) for r in rows if ci < len(r)] + [6])) for ci in range(n)]  # lebar kolom sebanding dengan isinya
    wts = [max(w, 0.18 * max(wts)) for w in wts]
    widths = [Cm(text_w * w / sum(wts)) for w in wts]
    for ci, col in enumerate(t.columns):
        col.width = widths[ci]  # tblGrid (dibaca LibreOffice/Word) dan lebar sel dijaga sama
    for ri, row in enumerate(rows):
        tr = t.rows[ri]
        trpr = tr._tr.get_or_add_trPr()
        cs = OxmlElement("w:cantSplit")
        trpr.append(cs)
        if ri == 0 and header:
            th = OxmlElement("w:tblHeader")
            trpr.append(th)
        for ci in range(n):
            cell = tr.cells[ci]
            cell.width = widths[ci]
            parts = [x for x in richtext.BR.split(row[ci] if ci < len(row) else "")] or [""]
            for pi, part in enumerate(parts):
                p = cell.paragraphs[0] if pi == 0 else cell.add_paragraph()
                p.paragraph_format.line_spacing, p.paragraph_format.space_after = 1.0, Pt(2)
                p.paragraph_format.first_line_indent = Cm(0)
                r = p.add_run(clean(part))
                r.font.size = size
                if ri == 0 and header:
                    r.bold = True
            if ri == 0 and header:
                _shade(cell, "E7E6E6")
    gap = d.add_paragraph()  # jarak setelah tabel
    gap.paragraph_format.space_after = Pt(4)
    gap.paragraph_format.line_spacing = 1.0


def _add_image(d, alt: str, sha: str, asset, text_w: float) -> None:
    """Sisipkan gambar rata tengah, selebar-lebarnya area tulisan (tidak diperbesar dari ukuran aslinya). Format yang tak bisa disisipkan
    (mis. WebP) atau gambar yang hilang diganti penanda teks agar pembaca tahu ada gambar di sana."""
    from io import BytesIO
    data, mime = asset if asset else (None, None)
    if data is None or mime not in ("image/png", "image/jpeg", "image/gif"):
        p = d.add_paragraph()
        p.alignment = AL.CENTER
        p.add_run(f"[Gambar tidak dapat disisipkan{': ' + alt if alt else ''}]").italic = True
        return
    dims = docparse.image_dims(data, mime)
    width = text_w if not dims else min(text_w, dims[0] / 96 * 2.54)
    if dims and dims[1] / max(dims[0], 1) * width > 21:  # gambar sangat tinggi: batasi agar muat satu halaman
        width = 21 * dims[0] / dims[1]
    p = d.add_paragraph()
    p.alignment = AL.CENTER
    p.paragraph_format.first_line_indent = Cm(0)
    p.paragraph_format.keep_with_next = True  # tetap sehalaman dengan keterangannya di bawah
    p.paragraph_format.line_spacing = 1.0
    p.add_run().add_picture(BytesIO(data), width=Cm(max(1.0, width)))


def build_docx(chapters: list[tuple[str, str]], entries: list[dict], fmt: style.FormatRules, b: ExportIn, cite_style: str, images: dict[str, tuple[bytes, str]] | None = None) -> bytes:
    thesis = DOC_BY_KEY[b.doc_type]["kind"] == "thesis"  # skripsi/proposal/laporan: tiap bab di halaman baru; artikel: mengalir
    d = Document()
    z = d.settings.element.find(qn("w:zoom"))  # templat bawaan python-docx kurang atribut ini (ditolak validator OOXML)
    if z is not None and z.get(qn("w:percent")) is None:
        z.set(qn("w:percent"), "100")
    sec = d.sections[0]
    w, h = PAPER[fmt.paper]
    sec.page_width, sec.page_height = Cm(w), Cm(h)
    m = fmt.margin_cm
    sec.top_margin, sec.bottom_margin, sec.left_margin, sec.right_margin = Cm(m.top), Cm(m.bottom), Cm(m.left), Cm(m.right)
    cover = bool(thesis and b.include_cover and b.title)
    sec.different_first_page_header_footer = cover  # sampul tanpa nomor halaman

    st = d.styles
    _font(st["Normal"], fmt.font, fmt.size_pt)
    pf = st["Normal"].paragraph_format
    pf.space_before = pf.space_after = Pt(0)
    pf.line_spacing = fmt.line_spacing
    for lvl, (sz, it) in {1: (fmt.size_pt, False), 2: (fmt.size_pt, False), 3: (fmt.size_pt, True)}.items():
        hs = st[f"Heading {lvl}"]
        _font(hs, fmt.font, sz, bold=True, italic=it)
        hs.paragraph_format.space_before, hs.paragraph_format.space_after = Pt(12 if lvl == 1 else 8), Pt(6)
        hs.paragraph_format.keep_with_next = True
        hs.paragraph_format.line_spacing = fmt.line_spacing

    def heading(text, lvl, page_break=False):
        p = d.add_heading(clean(text), lvl)
        if lvl == 1:
            p.alignment = AL.CENTER if thesis else AL.LEFT
        if page_break:
            p.paragraph_format.page_break_before = True
        return p

    if cover:
        def cp(text, bold=False, size=None, before=0):
            p = d.add_paragraph()
            p.alignment = AL.CENTER
            p.paragraph_format.space_before, p.paragraph_format.line_spacing = Pt(before), 1.15
            r = p.add_run(clean(text))
            r.bold = bold
            if size:
                r.font.size = Pt(size)
        cp(DOC_BY_KEY[b.doc_type]["cover"], True, fmt.size_pt + 2, 24)
        cp(b.title.upper(), True, fmt.size_pt + 2, 60)
        cp("Disusun oleh:", False, None, 90)
        for t in (b.author, f"NIM {b.nim}" if b.nim else None):
            if t:
                cp(t, bool(t == b.author), None, 6)
        cp(b.program or "", False, None, 90)
        cp((b.institution or "").upper(), True, fmt.size_pt + 1, 6)
        cp(str(b.year or ""), False, None, 6)

    if thesis and b.include_toc:
        t = d.add_paragraph()
        t.alignment = AL.CENTER
        t.paragraph_format.page_break_before = True
        r = t.add_run("DAFTAR ISI")
        r.bold = True
        _field(d.add_paragraph(), 'TOC \\o "1-3" \\h \\z \\u', "Klik kanan di sini, lalu pilih “Perbarui Bidang” untuk menampilkan daftar isi.", dirty=True)

    text_w = max(5.0, w - m.left - m.right)  # lebar area tulisan (cm): batas lebar gambar dan tabel
    for key_title, text in chapters:
        bl = blocks(text)
        first = bl[0][1] if bl else ""
        head = chapter_heading(b.doc_type, key_title)
        if not (H_BAB.match(first) or first.casefold() == key_title.casefold()):
            heading(head, 1, page_break=thesis)
        for i, (kind, s) in enumerate(bl):
            if kind in ("h1", "h2", "h3"):
                heading(s.upper() if kind == "h1" else s, int(kind[1]), page_break=thesis and kind == "h1")
            elif kind == "table":
                _add_table(d, s[0], s[1], fmt, text_w)
            elif kind == "img":
                _add_image(d, s[0], s[1], (images or {}).get(s[1]), text_w)
            elif kind == "li":
                lvl, label, body = s
                if label in ("-", "*", "•"):
                    p = d.add_paragraph(style="List Bullet" if lvl == 0 else "List Bullet 2")
                    p.add_run(body)
                else:
                    p = d.add_paragraph()
                    p.paragraph_format.left_indent, p.paragraph_format.first_line_indent = Cm(0.9 * (lvl + 1)), Cm(-0.6)
                    p.add_run(f"{label} {body}")
                p.alignment = AL.JUSTIFY if fmt.justify else AL.LEFT
            else:
                p = d.add_paragraph()
                cap = richtext.CAPTION.match(s)
                if cap and cap.group(3)[:1].isupper() and len(s) <= 200:  # keterangan tabel/gambar: rata tengah, tanpa indentasi
                    p.alignment = AL.CENTER
                    p.paragraph_format.keep_with_next = cap.group(1).lower() == "tabel"  # keterangan tabel ada di atas tabelnya
                    p.paragraph_format.space_before = Pt(6)
                else:
                    p.alignment = AL.JUSTIFY if fmt.justify else AL.LEFT
                    p.paragraph_format.first_line_indent = Cm(fmt.first_line_indent_cm)
                p.add_run(s)

    if b.include_refs and entries:
        heading("DAFTAR PUSTAKA", 1, page_break=thesis)
        for n, segs in enumerate(refs.format_list(entries, cite_style), 1):
            p = d.add_paragraph()
            p.alignment = AL.LEFT
            ind = Cm(1.0 if cite_style == "ieee" else 1.27)
            p.paragraph_format.left_indent, p.paragraph_format.first_line_indent = ind, -ind
            p.paragraph_format.line_spacing, p.paragraph_format.space_after = 1.0, Pt(8)
            if cite_style == "ieee":
                p.add_run(f"[{n}]\t")
                p.paragraph_format.tab_stops.add_tab_stop(ind)
            for text, it in segs:
                p.add_run(clean(text)).italic = it or None

    if fmt.page_number != "none":
        part = sec.footer if fmt.page_number == "bottom_center" else sec.header
        par = part.paragraphs[0]
        par.alignment = AL.CENTER if fmt.page_number == "bottom_center" else AL.RIGHT
        _field(par, "PAGE", "1")
    cp_ = d.core_properties
    cp_.title, cp_.author, cp_.comments = clean(b.title or ""), clean(b.author or ""), "Dibuat dengan Dospem"
    buf = BytesIO()
    d.save(buf)
    return buf.getvalue()


MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@router.post("/export/docx")
def export_docx(b: ExportIn, u: User = Depends(current_user), db: Session = Depends(get_db), rules: dict | None = Depends(style.current_rules)):
    if b.doc_type not in ROADMAP:
        raise HTTPException(404, "Jenis tugas tidak dikenal")
    drafts = {k: c for k, c in db.execute(select(Draft.chapter_key, Draft.content).where(Draft.owner == f"u{u.id}", Draft.doc_type == b.doc_type))}
    chapters = [(c["title"], drafts[c["key"]]) for c in ROADMAP[b.doc_type] if (drafts.get(c["key"]) or "").strip()]
    if not chapters:
        raise HTTPException(400, "Belum ada tulisan untuk diekspor. Tulis dulu minimal satu bab.")
    raw = rules or {}  # data gaya lama bisa tak lolos validasi terbaru: jangan sampai ekspor gagal karenanya
    try:
        fmt = style.FormatRules.model_validate(raw.get("format") or {})
    except ValidationError:
        fmt = style.FormatRules()
    cite = b.style or (raw.get("citation_style") if raw.get("citation_style") in ("apa", "ieee") else "apa")
    entries = [_dict(e) for e in db.scalars(select(BibEntry).where(BibEntry.user_id == u.id).order_by(BibEntry.id))]
    shas = list(dict.fromkeys(h for _, c in chapters for h in richtext.hashes(c)))
    imgs = {k: (v.data, v.mime) for k, v in asset_store.load(db, f"u{u.id}", b.doc_type, shas).items()}
    data = build_docx(chapters, entries, fmt, b, cite, imgs)
    return Response(data, media_type=MIME, headers={"Content-Disposition": f'attachment; filename="Dospem-{b.doc_type}.docx"'})


class LogbookIn(BaseModel):
    title: str | None = Field(None, max_length=300)
    author: str | None = Field(None, max_length=120)
    nim: str | None = Field(None, max_length=40)
    program: str | None = Field(None, max_length=150)
    institution: str | None = Field(None, max_length=150)


LOGBOOK_MAX = 500
LOGBOOK_COLS = (("No", 1.2), ("Tanggal", 3.0), ("Dosen pembimbing", 4.6), ("Bab / topik", 4.6), ("Uraian bimbingan", 10.2), ("Paraf dosen", 3.0))


def build_logbook_docx(rows: list[dict], fmt: style.FormatRules, b: LogbookIn) -> bytes:
    """Lembar bimbingan: tabel lanskap dari catatan dosen berjenis logbook. Kolom paraf sengaja kosong (diparaf dosen di kertas)."""
    d = Document()
    z = d.settings.element.find(qn("w:zoom"))
    if z is not None and z.get(qn("w:percent")) is None:
        z.set(qn("w:percent"), "100")
    sec = d.sections[0]
    w, h = PAPER[fmt.paper]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = Cm(h), Cm(w)
    sec.top_margin = sec.bottom_margin = Cm(2.0)
    sec.left_margin = sec.right_margin = Cm(2.0)
    _font(d.styles["Normal"], fmt.font, fmt.size_pt)
    pf = d.styles["Normal"].paragraph_format
    pf.space_before = pf.space_after = Pt(0)
    pf.line_spacing = 1.15

    def line(text: str, bold=False, center=False, size=None, after=2):
        p = d.add_paragraph()
        p.alignment = AL.CENTER if center else AL.LEFT
        p.paragraph_format.space_after = Pt(after)
        r = p.add_run(clean(text))
        r.bold = bold
        if size:
            r.font.size = Pt(size)
    line("LEMBAR BIMBINGAN", True, True, fmt.size_pt + 2, 6)
    for label, val in (("Nama", b.author), ("NIM", b.nim), ("Program studi", b.program), ("Institusi", b.institution), ("Judul", b.title)):
        if val:
            line(f"{label}: {val}")
    d.add_paragraph().paragraph_format.space_after = Pt(4)
    t = d.add_table(rows=1, cols=len(LOGBOOK_COLS))
    t.style = "Table Grid"
    t.autofit = False
    small = max(9, fmt.size_pt - 2)

    def fill(cell, text, width, bold=False):
        cell.width = Cm(width)
        p = cell.paragraphs[0]
        p.paragraph_format.line_spacing = 1.0
        r = p.add_run(clean(text))
        r.bold = bold
        r.font.size = Pt(small)
    for c, (name, wd) in zip(t.rows[0].cells, LOGBOOK_COLS):
        fill(c, name, wd, True)
    for n, r in enumerate(rows, 1):
        cells = t.add_row().cells
        for c, (_, wd), val in zip(cells, LOGBOOK_COLS, (str(n), r["date"], r["dosen"], r["topic"], r["body"], "")):
            fill(c, val, wd)
    cp = d.core_properties
    cp.title, cp.author, cp.comments = "Lembar Bimbingan", clean(b.author or ""), "Dibuat dengan Dospem dari catatan dosen"
    buf = BytesIO()
    d.save(buf)
    return buf.getvalue()


@router.post("/export/logbook")
def export_logbook(b: LogbookIn, u: User = Depends(current_user), db: Session = Depends(get_db), rules: dict | None = Depends(style.current_rules)):
    q = (select(SupervisorNote, User).join(Supervision, Supervision.id == SupervisorNote.supervision_id)
         .join(User, User.id == Supervision.dosen_id)
         .where(Supervision.mahasiswa_id == u.id, SupervisorNote.kind == "logbook")
         .order_by(SupervisorNote.session_date, SupervisorNote.id).limit(LOGBOOK_MAX))
    titles = {(dt, c["key"]): c["title"] for dt, chs in ROADMAP.items() for c in chs}
    rows = [{"date": n.session_date.strftime("%d-%m-%Y") if n.session_date else "", "dosen": d.name or d.email or "",
             "topic": titles.get((n.doc_type, n.chapter_key), ""), "body": n.body} for n, d in db.execute(q)]
    if not rows:
        raise HTTPException(400, "Belum ada catatan lembar bimbingan dari dosenmu.")
    try:
        fmt = style.FormatRules.model_validate((rules or {}).get("format") or {})
    except ValidationError:
        fmt = style.FormatRules()
    return Response(build_logbook_docx(rows, fmt, b), media_type=MIME, headers={"Content-Disposition": 'attachment; filename="Dospem-lembar-bimbingan.docx"'})
