"""Format isi draf yang kaya: tabel dan gambar hidup di dalam teks draf sebagai penanda sederhana, sehingga tetap dapat diedit,
dibaca AI, diperiksa, dan diekspor.

  Tabel   : baris yang diawali `|` (gaya Markdown). Baris kedua boleh berupa pemisah `| --- | --- |` (menandai baris judul kolom).
            Pindah baris dalam sel ditulis `<br>`; tanda `|` di dalam sel ditulis `\\|`.
  Gambar  : satu baris `![keterangan](asset:ID)`; ID = 16 heksadesimal pertama SHA-256 isi gambar (disimpan di tabel draft_assets).
  Daftar  : `- butir` dan `1. butir` (dua spasi per tingkat).
Modul ini murni fungsi teks (tanpa DB) agar bisa dipakai bersama oleh pengunggah, pemeriksa, tinjauan, ekspor Word, dan sesi tanya-jawab."""
import re

IMG_LINE = re.compile(r"^!\[([^\]\n]{0,200})\]\(asset:([0-9a-f]{12,64})\)\s*$")
ASSET_REF = re.compile(r"\(asset:([0-9a-f]{12,64})\)")
SEP_ROW = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")
CELL_SPLIT = re.compile(r"(?<!\\)\|")
BR = re.compile(r"\s*<br\s*/?>\s*", re.I)
CAPTION = re.compile(r"^\s*(Tabel|Gambar)\s+(\d+(?:\.\d+)*)\b[.:]?\s*(.*)$", re.I)


def is_row(line: str) -> bool:
    return line.lstrip().startswith("|")


def split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in CELL_SPLIT.split(s)]


def cell_text(raw: str) -> str:
    """Isi sel sebagai satu baris teks (pindah baris -> ' / ') untuk AI dan hitungan kata."""
    return BR.sub(" / ", raw).strip()


def make_row(cells: list[str]) -> str:
    return "| " + " | ".join(c.replace("|", "\\|").replace("\n", "<br>") for c in cells) + " |"


def make_table(rows: list[list[str]]) -> str:
    """Daftar baris -> teks tabel (baris pertama = judul kolom). Baris dipadatkan ke jumlah kolom terbanyak."""
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    out = [make_row(rows[0]), "| " + " | ".join(["---"] * n) + " |"]
    out += [make_row(r) for r in rows[1:]]
    return "\n".join(out)


def parse(text: str) -> list[tuple[str, object]]:
    """Teks -> urutan balok: ('table', {'rows': [[sel]], 'header': bool}), ('img', {'alt','hash'}), ('line', str).
    Baris kosong dibuang; baris tabel yang berurutan digabung menjadi satu tabel."""
    out: list[tuple[str, object]] = []
    rows: list[list[str]] = []
    header = False

    def flush():
        nonlocal rows, header
        if rows:
            out.append(("table", {"rows": rows, "header": header}))
        rows, header = [], False

    for line in text.split("\n"):
        s = line.strip()
        if not s:
            flush()
            continue
        if is_row(s):
            if SEP_ROW.match(s):
                header = header or len(rows) == 1
                continue
            rows.append(split_row(s))
            continue
        flush()
        m = IMG_LINE.match(s)
        out.append(("img", {"alt": m.group(1), "hash": m.group(2)}) if m else ("line", s))
    flush()
    return out


def hashes(text: str) -> list[str]:
    """ID gambar yang dirujuk teks, berurutan dan tanpa duplikat."""
    return list(dict.fromkeys(ASSET_REF.findall(text or "")))


def prose(text: str) -> str:
    """Teks tanpa tabel dan gambar: dasar hitungan kata/paragraf/kalimat agar baris tabel tidak menggelembungkan angkanya."""
    return "\n".join(v for k, v in parse(text) if k == "line")  # type: ignore[misc]


def words(text: str) -> int:
    """Jumlah kata prosa (tanpa isi baris tabel dan penanda gambar): satu definisi "kata" untuk progres, kesiapan, riwayat, dan dasbor."""
    if "|" not in text and "![" not in text:
        return len(text.split())
    return len(prose(text).split())


def for_llm(text: str) -> str:
    """Teks bab -> teks untuk AI: gambar menjadi penanda singkat (AI tidak melihat gambarnya), pemisah tabel dibuang, `<br>` -> ' / '."""
    out = []
    for kind, v in parse(text):
        if kind == "img":
            out.append(f"[gambar: {v['alt'] or 'tanpa keterangan'}]")  # type: ignore[index]
        elif kind == "table":
            out.append("\n".join("| " + " | ".join(cell_text(c) for c in r) + " |" for r in v["rows"]))  # type: ignore[index]
        else:
            out.append(str(v))
    return "\n".join(out)


def review_text(text: str) -> str:
    """Teks bab untuk dibaca AI saat meninjau/membimbing: HANYA prosa. Tabel diganti penanda satu baris '[tabel: N baris, M kolom]' dan
    gambar '[gambar]' (AI tidak membaca isi sel tabel dan tidak melihat gambar). Hemat token: data tabel panjang tidak ikut dikirim."""
    out = []
    for kind, v in parse(text):
        if kind == "img":
            alt = v["alt"]  # type: ignore[index]
            out.append(f"[gambar: {alt}]" if alt else "[gambar]")
        elif kind == "table":
            rows = v["rows"]  # type: ignore[index]
            out.append(f"[tabel: {max(len(rows) - 1, 0)} baris data, {max(len(r) for r in rows)} kolom]")
        else:
            out.append(str(v))
    return "\n".join(out)


def condense(text: str, budget: int, shift: int = 0) -> str:
    """Teks panjang -> cuplikan merata sepanjang teks (paragraf pertama dan terakhir selalu ada; bagian yang dilewati ditandai '[…]').
    `shift` menggeser paragraf yang dipilih sehingga cuplikan berbeda mencakup bagian yang berbeda."""
    if len(text) <= budget:
        return text
    paras = [p[:700].rstrip() + ("…" if len(p) > 700 else "") for p in text.split("\n") if p.strip()]
    if not paras:
        return text[:budget]
    k = max(2, budget // (sum(len(p) for p in paras) // len(paras) + 2))
    if k >= len(paras):
        pick = list(range(len(paras)))
    else:
        stride = -(-len(paras) // k)
        pick = sorted({0, len(paras) - 1, *range(shift % stride, len(paras), stride)})
    out, prev = [], None
    for i in pick:
        if prev is not None and i != prev + 1:
            out.append("[…]")
        out.append(paras[i])
        prev = i
    return "\n".join(out)[:budget]


def digest(text: str, max_rows: int = 2) -> str:
    """Ringkasan padat per tabel untuk sesi tanya-jawab: judul kolom, jumlah baris, dan beberapa baris contoh. Gambar -> penanda."""
    out = []
    for kind, v in parse(text):
        if kind == "img":
            out.append(f"[gambar: {v['alt'] or 'tanpa keterangan'}]")  # type: ignore[index]
        elif kind == "table":
            rows = v["rows"]  # type: ignore[index]
            cols = " | ".join(cell_text(c) for c in rows[0])
            ex = "; ".join(" | ".join(cell_text(c) for c in r) for r in rows[1:1 + max_rows])
            out.append(f"[tabel, kolom: {cols}; {len(rows) - 1} baris" + (f"; contoh: {ex}" if ex else "") + "]")
        else:
            out.append(str(v))
    return "\n".join(out)


def captions(text: str) -> list[dict]:
    """Keterangan tabel/gambar ('Tabel 3.1. Judul Tabel') beserta posisinya. Kalimat rujukan ('Gambar 3.2 menunjukkan alur ...',
    'Tabel 3.1 berikut memuat ...') bukan keterangan: judul keterangan diawali huruf kapital atau angka, kalimat rujukan diawali kata kerja huruf kecil."""
    out, pos = [], 0
    for line in text.split("\n"):
        m = CAPTION.match(line)
        if m and not is_row(line) and len(line.strip()) <= 200 and m.group(3)[:1].isupper() or (m and m.group(3)[:1].isdigit() and not is_row(line) and len(line.strip()) <= 200):
            out.append({"label": m.group(1).capitalize(), "number": m.group(2), "start": pos + line.index(m.group(1)), "end": pos + len(line.rstrip()), "title": m.group(3).strip()})
        pos += len(line) + 1
    return out
