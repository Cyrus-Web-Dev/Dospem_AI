"""Pemeriksaan statis frontend (tanpa browser): sintaks JS, ID ganda, dan referensi berkas. Menangkap kelas bug yang lolos dari tes API
(mis. halaman mati total karena SyntaxError)."""
import collections
import pathlib
import re
import shutil
import subprocess

import pytest

STATIC = pathlib.Path(__file__).resolve().parents[1] / "static"
PAGES = sorted(STATIC.glob("*.html"))
# ID ganda yang sudah ada sejak awal: berada di template JS yang dirender bergantian (tidak pernah dua-duanya di DOM). Tambahan baru = gagal.
KNOWN_DUPLICATE_IDS = {"index.html": {"sg-err", "sg-new"}}
SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S)


def test_pages_exist():
    assert {p.name for p in PAGES} >= {"index.html", "dosen.html", "admin.html", "reset.html", "legal.html"}


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_no_new_duplicate_ids(page):
    ids = collections.Counter(re.findall(r'\bid="([^"]+)"', page.read_text(encoding="utf-8")))
    dup = {k for k, v in ids.items() if v > 1}
    assert dup <= KNOWN_DUPLICATE_IDS.get(page.name, set()), f"ID ganda baru di {page.name}: {sorted(dup - KNOWN_DUPLICATE_IDS.get(page.name, set()))}"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_local_references_exist(page):
    html = page.read_text(encoding="utf-8")
    for ref in re.findall(r'(?:src|href)="(/[^"#?]*)', html):
        if ref.startswith("/api") or ref == "/":
            continue
        assert (STATIC / ref.lstrip("/")).exists(), f"{page.name} merujuk {ref} yang tidak ada"


@pytest.mark.skipif(not shutil.which("node"), reason="butuh Node.js")
@pytest.mark.parametrize("page", PAGES + [STATIC / "common.js"], ids=lambda p: p.name)
def test_inline_javascript_is_syntactically_valid(page, tmp_path):
    text = page.read_text(encoding="utf-8")
    blocks = [text] if page.suffix == ".js" else SCRIPT.findall(text)
    for i, code in enumerate(b for b in blocks if b.strip()):
        f = tmp_path / f"{page.stem}_{i}.js"
        f.write_text(code, encoding="utf-8")
        r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
        assert r.returncode == 0, f"{page.name} (skrip #{i}): {r.stderr.strip()[:400]}"
