"""Tabel dan gambar: impor dari .docx, penyimpanan gambar, pratinjau (API), pemeriksaan, tinjauan, dan ekspor Word."""
import io
import struct
import uuid
import zipfile
import zlib

import pytest

from app import assets, docparse, eyd, review, richtext
from app.config import settings
from tests.test_app import make_premium
from tests.test_upload_review import dev, up


def png(w=40, h=30, rgb=(200, 30, 30)):
    """PNG sah minimal (tanpa Pillow)."""
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)  # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def rich_docx(images=(), merged=False):
    from docx import Document
    d = Document()
    d.add_paragraph("3.1 Analisis Kebutuhan", style="Heading 1")
    d.add_paragraph("Daftar kebutuhan ditunjukkan pada Tabel 3.1 dan alur pada Gambar 3.1.")
    d.add_paragraph("Tabel 3.1. Kebutuhan Fungsional")
    t = d.add_table(rows=3, cols=3)
    for r, row in enumerate([["Kode", "Nama", "Catatan"], ["KF-01", "Login | 2FA", "Langkah 1\nLangkah 2"], ["KF-02", "Registrasi", ""]]):
        for c, v in enumerate(row):
            t.cell(r, c).text = v
    if merged:
        t.cell(2, 1).merge(t.cell(2, 2))
    for i, im in enumerate(images):
        d.add_picture(io.BytesIO(im), width=None)
        d.add_paragraph(f"Gambar 3.{i + 1}. Diagram ke-{i + 1}")
    d.add_paragraph("Butir pertama", style="List Bullet")
    d.add_paragraph("Butir kedua", style="List Bullet")
    d.add_paragraph("Langkah satu", style="List Number")
    d.add_paragraph("Langkah dua", style="List Number")
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


# ---------- richtext ----------
def test_richtext_parse_roundtrip_and_helpers():
    rows = [["Kode", "Isi"], ["A|B", "baris 1\nbaris 2"], ["", "x"]]
    t = richtext.make_table(rows)
    assert t.splitlines()[1] == "| --- | --- |" and "A\\|B" in t and "baris 1<br>baris 2" in t
    k, v = richtext.parse("Teks.\n\n" + t + "\n\n![ket](asset:0123456789abcdef)\nAkhir.")[1]
    assert k == "table" and v["header"] and v["rows"][1] == ["A|B", "baris 1<br>baris 2"]
    text = "Dua kata.\n" + t + "\n![x](asset:0123456789abcdef)"
    assert richtext.words(text) == 2 and richtext.words("tanpa tabel di sini") == 4
    assert richtext.hashes(text + "![y](asset:0123456789abcdef)") == ["0123456789abcdef"]
    assert "[gambar: x]" in richtext.for_llm(text) and "| --- |" not in richtext.for_llm(text) and "baris 1 / baris 2" in richtext.for_llm(text)
    assert richtext.digest(text).count("[tabel, kolom: Kode | Isi; 2 baris") == 1


# ---------- impor .docx ----------
def test_docx_import_table_image_lists_and_alt():
    r = docparse.extract(rich_docx([png()]), "b.docx")
    t = r["text"]
    assert r["tables"] == 1 and len(r["images"]) == 1 and r["image_count"] == 1
    assert "| Kode | Nama | Catatan |\n| --- | --- | --- |" in t
    assert "Login \\| 2FA" in t and "Langkah 1<br>Langkah 2" in t  # pipa dan pindah baris di sel aman
    sha = richtext.hashes(t)[0]
    assert r["images"][sha]["mime"] == "image/png" and f"![](asset:{sha})" in t
    assert "- Butir pertama\n- Butir kedua" in t and "1. Langkah satu\n2. Langkah dua" in t
    order = [t.index(x) for x in ("Tabel 3.1. Kebutuhan", "| Kode |", f"asset:{sha}", "Gambar 3.1. Diagram")]
    assert order == sorted(order)  # urutan dokumen dipertahankan


def test_docx_merged_cells_warn_and_unsupported_images_are_skipped():
    r = docparse.extract(rich_docx(merged=True), "b.docx")
    assert any("sel tabel yang digabung" in w for w in r["warnings"])
    # hanya PNG/JPEG/GIF/WebP berdasarkan ISI; SVG ditolak
    assert docparse.sniff_image(b"<svg xmlns='http://www.w3.org/2000/svg'/>") is None and docparse.sniff_image(b"RIFF\0\0\0\0WEBPVP8 ") == "image/webp"
    assert docparse.image_dims(png(40, 30), "image/png") == (40, 30)


def test_docx_with_content_control_keeps_text():
    from docx import Document
    from docx.oxml import OxmlElement
    d = Document()
    d.add_paragraph("Sebelum kontrol.")
    p = d.add_paragraph("Isi di dalam kontrol konten.")
    sdt, content = OxmlElement("w:sdt"), OxmlElement("w:sdtContent")
    p._p.addprevious(sdt)
    sdt.append(content)
    content.append(p._p)
    b = io.BytesIO()
    d.save(b)
    assert "Isi di dalam kontrol konten." in docparse.extract(b.getvalue(), "k.docx")["text"]


def test_docx_shapes_and_notes_are_reported():
    z = io.BytesIO(rich_docx())
    out = io.BytesIO()
    with zipfile.ZipFile(z) as zi, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in zi.namelist():
            data = zi.read(n)
            if n == "word/document.xml":
                data = data.replace(b"</w:body>", b'<w:p><w:r><w:pict><v:shape xmlns:v="urn:schemas-microsoft-com:vml"/></w:pict></w:r></w:p></w:body>')
            zo.writestr(n, data)
    r = docparse.extract(out.getvalue(), "s.docx")
    assert any("objek gambar Word" in w for w in r["warnings"])


def test_txt_md_keep_tables_and_images_markup():
    md = "Pengantar.\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n- butir\n- butir dua\n"
    r = docparse.extract(md.encode(), "t.md")
    assert "| A | B |\n| --- | --- |\n| 1 | 2 |" in r["text"] and "- butir\n- butir dua" in r["text"] and r["tables"] == 1
    r = docparse.extract(b"Baris satu\n| X | Y |\n| --- | --- |\n| 1 | 2 |\nBaris dua", "t.txt")
    assert r["text"] == "Baris satu\n\n| X | Y |\n| --- | --- |\n| 1 | 2 |\n\nBaris dua"


# ---------- endpoint: unggah + gambar ----------
def test_upload_stores_images_and_serves_only_to_owner(client):
    h = dev()
    r = up(client, h, rich_docx([png(), png(20, 20, (0, 0, 200))]), "b.docx")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["tables"] == 1 and j["images"] == 2 and "| Kode |" in j["content"]
    shas = richtext.hashes(j["content"])
    a = client.get(f"/api/assets/skripsi/pendahuluan/{shas[0]}", headers=h)
    assert a.status_code == 200 and a.headers["content-type"] == "image/png" and a.content.startswith(b"\x89PNG") and "immutable" in a.headers["cache-control"]
    assert a.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"/api/assets/skripsi/pendahuluan/{shas[0]}", headers=dev()).status_code == 404  # bukan milik pemilik lain
    assert client.get(f"/api/assets/skripsi/metode/{shas[0]}", headers=h).status_code == 404          # bab lain
    assert client.get("/api/assets/skripsi/pendahuluan/zzzz", headers=h).status_code == 404
    assert client.get(f"/api/assets/skripsi/pendahuluan/{shas[0]}").status_code == 400               # tanpa identitas
    assert "img-src 'self' data: blob:" in client.get("/").headers["content-security-policy"]


def test_upload_gc_keeps_assets_of_previous_versions_but_drops_unreferenced(client):
    h = dev()
    sha_a = richtext.hashes(up(client, h, rich_docx([png(30, 30, (1, 2, 3))]), "a.docx").json()["content"])[0]
    r2 = up(client, h, rich_docx([png(31, 31, (9, 9, 9))]), "b.docx").json()
    sha_b = richtext.hashes(r2["content"])[0]
    assert client.get(f"/api/assets/skripsi/pendahuluan/{sha_b}", headers=h).status_code == 200
    # versi lama masih ada di riwayat: gambarnya tetap ada agar 'pulihkan' tidak menampilkan gambar rusak
    assert client.get(f"/api/assets/skripsi/pendahuluan/{sha_a}", headers=h).status_code == 200
    # unggahan teks biasa: gambar yang tidak dirujuk draf maupun riwayat dibersihkan
    from app.db import SessionLocal
    from app.models import DraftRevision
    with SessionLocal() as db:
        db.query(DraftRevision).delete()
        db.commit()
    up(client, h, "Teks saja tanpa gambar.".encode(), "c.txt")
    assert client.get(f"/api/assets/skripsi/pendahuluan/{sha_a}", headers=h).status_code == 404


def test_upload_image_limits_drop_markers_and_warn(client, monkeypatch):
    h = dev()
    monkeypatch.setattr(settings, "asset_max_per_chapter", 1)
    r = up(client, h, rich_docx([png(30, 30, (1, 1, 1)), png(31, 31, (2, 2, 2))]), "b.docx").json()
    assert len(richtext.hashes(r["content"])) == 1 and any("batas penyimpanan gambar" in w for w in r["warnings"])
    monkeypatch.setattr(settings, "asset_max_per_chapter", 60)
    monkeypatch.setattr(settings, "asset_max_mb", 0)  # semua gambar dianggap terlalu besar
    r = up(client, dev(), rich_docx([png()]), "b.docx").json()
    assert richtext.hashes(r["content"]) == [] and any("gambar dilewati" in w for w in r["warnings"])


def test_assets_store_rejects_over_user_quota(client, monkeypatch):
    from app.db import SessionLocal
    monkeypatch.setattr(settings, "asset_user_quota_mb", 0)
    with SessionLocal() as db:
        kept, refused = assets.store(db, "dev-q", "skripsi", "pendahuluan", {"a" * 16: {"data": png(), "mime": "image/png"}})
    assert kept == set() and refused == 1


# ---------- pemeriksaan EYD pada tabel ----------
def test_eyd_ignores_table_notation_and_identifiers():
    t = "| Entitas 1 | Relasi | Kardinalitas |\n| --- | --- | --- |\n| User | memiliki | 1 : N |\n| merk | VARCHAR | Merk kendaraan |\n![d](asset:0123456789abcdef)\n\nKalimat merk biasa ,salah."
    got = [(i["rule"], i["text"]) for i in eyd.check(t)]
    assert ("kata_baku", "Merk") in got and ("kata_baku", "merk") in got            # kalimat biasa dan sel berkalimat tetap diperiksa
    assert not any(r == "spasi_tanda" and tx == " :" for r, tx in got)             # '1 : N' adalah notasi
    cells = [i for i in eyd.check(t) if i["rule"] == "kata_baku" and t[i["start"]:i["end"]] == "merk" and i["start"] < t.index("\n\nKalimat")]
    assert cells == []                                                              # nama kolom basis data (satu token) tidak dikoreksi
    assert ("spasi_tanda", " ,") in got                                            # tanda baca di kalimat biasa tetap diperiksa


# ---------- tinjauan ----------
def test_review_prose_stats_exclude_tables_and_crossrefs():
    text = ("3.1 Analisis\n\nKebutuhan ditunjukkan pada Tabel 3.1 sampai Tabel 3.3 dan Gambar 3.9.\n\nTabel 3.1. Satu\n| A | B |\n| --- | --- |\n| x y z | q |\n\n"
            "Tabel 3.2. Dua\nTabel 3.3. Tiga\nTabel 3.3. Ganda\nTabel 3.5. Lima\n\nGambar 3.1. Diagram\n\nKalimat uraian kedua yang cukup panjang.")
    r = review.report(text)
    assert r["stats"]["tables"] == 1 and r["stats"]["words"] < 40 and r["stats"]["paragraphs"] == 2  # baris tabel dan judul tak dihitung sebagai uraian
    msgs = [i["message"] for i in r["issues"] if i["group"] == "rujukan"]
    assert any("Tabel 3.3 bernomor sama" in m for m in msgs) and any("Nomor Tabel 3.4 terlewat" in m for m in msgs)
    assert any("Tabel 3.5 belum dirujuk" in m for m in msgs) and any("Gambar 3.1 belum dirujuk" in m for m in msgs)
    assert any("Gambar 3.9 dirujuk tetapi tidak ada keterangannya" in m for m in msgs)
    assert not any("Tabel 3.2 belum dirujuk" in m for m in msgs)  # rujukan rentang 'Tabel 3.1 sampai Tabel 3.3' sah
    for i in r["issues"]:
        if i["group"] == "rujukan":
            assert text[i["start"]:i["end"]] == i["text"]


def test_review_aggregates_many_unreferenced_and_keeps_tables_whole_in_sections():
    caps = "\n".join(f"Tabel 4.{n}. Judul {n}\n| A | B |\n| --- | --- |\n| {'isi ' * 30} | {n} |\n" for n in range(1, 9))
    r = review.report("Pengantar tanpa rujukan.\n\n" + caps)
    msgs = [i["message"] for i in r["issues"] if i["group"] == "rujukan"]
    assert len(msgs) == 1 and "8 tabel belum dirujuk di teks: Tabel 4.1–4.8" in msgs[0]
    secs = review.split_sections("\n\n".join(f"| H | I |\n| --- | --- |\n" + "\n".join(f"| {'kata ' * 20} | {j} |" for j in range(12)) for _ in range(6)), 1200)
    assert len(secs) > 1 and all(not ln.strip() or ln.startswith("|") for sec in secs for ln in sec.split("\n"))
    assert all(ln.rstrip().endswith("|") for sec in secs for ln in sec.split("\n") if ln)  # tak ada baris tabel terpotong


def test_review_endpoint_with_uploaded_rich_chapter(client):
    h = dev()
    up(client, h, rich_docx([png()]), "b.docx")
    j = client.post("/api/review", headers=h, json={"doc_type": "skripsi", "chapter_key": "pendahuluan"}).json()
    assert j["stats"]["tables"] == 1 and j["stats"]["images"] == 1
    sec = j["sections"][0]
    out = client.post("/api/review/section", headers=h, json={"doc_type": "skripsi", "chapter_key": "pendahuluan", "index": 0, "h": sec["h"]})
    assert out.status_code == 200, out.text


def test_words_counted_without_table_rows_in_progress(client, reg):
    h, _ = reg()
    table = "\n".join(["| a b c d e | f g h i j |", "| --- | --- |"] + ["| satu dua tiga empat | lima enam tujuh |"] * 100)
    assert richtext.words("Uraian pendek.\n" + table) == 2


# ---------- ekspor Word ----------
def test_export_docx_contains_real_tables_and_images(client, reg):
    from docx import Document
    h, _ = reg()
    assert up(client, h, rich_docx([png(), png(24, 24, (5, 5, 5))]), "b.docx").status_code == 200
    r = client.post("/api/export/docx", headers=h, json={"doc_type": "skripsi", "include_toc": False})
    assert r.status_code == 200, r.text
    d = Document(io.BytesIO(r.content))
    assert len(d.tables) == 1 and len(d.inline_shapes) == 2
    t = d.tables[0]
    assert [c.text for c in t.rows[0].cells] == ["Kode", "Nama", "Catatan"] and t.rows[1].cells[1].text == "Login | 2FA"
    assert [p.text for p in t.rows[1].cells[2].paragraphs] == ["Langkah 1", "Langkah 2"]  # <br> menjadi paragraf dalam sel
    body = "\n".join(p.text for p in d.paragraphs)
    assert "|" not in body and "asset:" not in body and "Butir pertama" in body and "1. Langkah satu" in body


def test_export_missing_or_unsupported_image_becomes_marker():
    from docx import Document
    from app import export, style
    b = export.ExportIn(doc_type="skripsi", include_cover=False, include_toc=False, include_refs=False)
    out = export.build_docx([("Bab 1 · Pendahuluan", "Teks.\n\n![Diagram hilang](asset:0123456789abcdef)\n\nGambar 3.1. Diagram")], [], style.FormatRules(), b, "apa", {})
    d = Document(io.BytesIO(out))
    assert any("[Gambar tidak dapat disisipkan: Diagram hilang]" in p.text for p in d.paragraphs) and len(d.inline_shapes) == 0


# ---------- bimbingan memakai ringkasan tabel ----------
def test_bimbingan_context_digests_tables_instead_of_flooding_with_rows(client, reg):
    from app import sidang
    from app.db import SessionLocal
    from app.models import User
    h, _ = reg()
    make_premium(client, h)
    rows = "\n".join(f"| KF-{n:02d} | Kebutuhan nomor {n} | Deskripsi panjang {n} " + "x" * 80 + " |" for n in range(1, 200))
    text = "Pengantar analisis kebutuhan sistem informasi yang cukup panjang. " * 12 + "\n\n| Kode | Nama | Deskripsi |\n| --- | --- | --- |\n" + rows + "\n\n![d](asset:0123456789abcdef)"
    assert up(client, h, text.encode(), "b.txt").status_code == 200
    with SessionLocal() as db:
        u = db.query(User).order_by(User.id.desc()).first()
        _, ctx, _ = sidang._context_scoped(db, u, "skripsi", ["pendahuluan"], 1)
    assert "[tabel, kolom: Kode | Nama | Deskripsi; 199 baris" in ctx and "[gambar: d]" in ctx and ctx.count("KF-") < 8
