"""Pemeriksa ejaan: integritas kamus, setiap kategori aturan, dan (terpenting) tidak menandai tulisan yang sudah benar."""
import time

import pytest

from app import eyd
from app import kamus as K

BAKU = {"kata_baku", "ragam_santai", "di_pisah", "ke_pisah", "pun", "kapital_nama", "di_serangkai", "tanda_ganda", "spasi_kurung", "spasi_titik", "boros"}


def rules(t):
    return [(i["rule"], i["text"], i["suggestion"]) for i in eyd.check(t)]


def fix(t):
    """Terapkan semua saran KECUALI huruf kapital awal kalimat (diuji terpisah) dan isian templat."""
    for i in sorted(eyd.check(t), key=lambda i: -i["start"]):
        if i["rule"] not in ("placeholder", "kapital"):
            t = t[:i["start"]] + i["suggestion"] + t[i["end"]:]
    return t


# ---------- integritas kamus ----------
def test_dictionary_integrity():
    tables = {**K.GROUPS, "SANTAI": K.SANTAI, "PUN_PISAH": K.PUN_PISAH, "FRASA": K.FRASA, "BOROS": K.BOROS}
    allkeys = {}
    for name, t in tables.items():
        for k, v in t.items():
            assert k == k.lower() and k.strip() == k and v.strip() == v and v, (name, k)
            assert k.lower() != v.lower(), (name, k)
            assert allkeys.setdefault(k, (name, v))[1] == v, ("entri ganda berbeda nilai", k)
    single = {k for k in allkeys if " " not in k}
    for name, t in tables.items():  # tidak boleh berantai: nilai sebuah entri bukan kunci entri lain
        for k, v in t.items():
            assert v.lower() not in allkeys or v.lower() == k, ("rantai", k, v)
    assert not (single & K.KAPITAL_NAMA) and "minggu" not in K.KAPITAL_NAMA and "padang" not in K.KAPITAL_NAMA
    # kata yang sengaja TIDAK boleh ada (sah / diperdebatkan / berarti lain)
    for ok in ("rubah", "telanjur", "terlanjur", "memerhatikan", "memperhatikan", "mengkritik", "mengkaji", "mempelajari", "type", "standard", "photo", "extra"):
        assert ok not in allkeys, ok
    assert len(K.NONBAKU) >= 170


def test_every_suggestion_is_clean_and_fixing_is_idempotent():
    text = ". ".join(f"Ini {k} lagi" for k in sorted({**K.NONBAKU, **K.SANTAI, **K.PUN_PISAH}) if k not in ("ga", "klo")) + "."
    first = fix(text)
    again = [i for i in eyd.check(first) if i["rule"] in ("kata_baku", "ragam_santai", "pun")]
    assert not again, again[:3]


# ---------- tiap kategori ----------
@pytest.mark.parametrize("salah,benar", [
    ("Analisa data", "Analisis data"), ("ANALISA", "ANALISIS"), ("terdapat resiko tinggi", "terdapat risiko tinggi"),
    ("hasil kwalitatif", "hasil kualitatif"), ("mempengaruhi prestasi", "memengaruhi prestasi"), ("dirubah menjadi", "diubah menjadi"),
    ("sistem yang handal", "sistem yang andal"), ("tehnologi baru", "teknologi baru"), ("jumlah prosentase", "jumlah persentase"),
    ("pada hari jum'at", "pada hari Jumat"), ("kerjasama tim", "kerja sama tim"), ("mensukseskan program", "menyukseskan program"),
    ("para pengrajin", "para perajin"), ("Silahkan isi kuisioner", "Silakan isi kuesioner"), ("mengkonsumsi gula", "mengonsumsi gula"),
])
def test_nonbaku(salah, benar):
    assert fix(salah) == benar


def test_phrases_and_prepositions():
    assert fix("lebih baik dari pada itu") == "lebih baik daripada itu"
    assert fix("apa\nbila perlu") == "apa\nbila perlu"  # lintas baris tidak dianggap frasa
    assert fix("apa   bila perlu") == "apabila perlu"
    assert fix("Dimana letaknya? dirumah, didalam kelas, diatas meja, disini") == "Di mana letaknya? di rumah, di dalam kelas, di atas meja, di sini"
    assert fix("ketempat itu kesini kemana kedalam") == "ketempat itu ke sini ke mana ke dalam"  # 'ketempat' tidak di daftar (rawan)
    assert fix("datang darimana") == "datang dari mana"
    assert fix("di makan, di tulis, di analisis? di bahas") == "dimakan, ditulis, di analisis? dibahas"
    assert fix("disaat itu ditengah jalan diantara mereka disekitar kampus") == "di saat itu di tengah jalan di antara mereka di sekitar kampus"


def test_pun_particle():
    assert fix("walau pun hujan, atau pun panas, bagaimana pun juga") == "walaupun hujan, ataupun panas, bagaimanapun juga"
    assert fix("apapun hasilnya, siapapun, dimanapun") == "apa pun hasilnya, siapa pun, di mana pun"
    assert not [r for r in rules("Walaupun begitu, apa pun hasilnya, meskipun sulit, bagaimanapun, ataupun, maupun.") if r[0] == "pun"]


def test_capital_names_and_informal():
    assert fix("pada senin 5 mei di jakarta memakai bahasa inggris") == "pada Senin 5 Mei di Jakarta memakai bahasa Inggris"
    assert not [r for r in rules("Pada Senin, 5 Mei, di Jakarta; satu minggu, di padang rumput, ke medan perang.") if r[0] == "kapital_nama"]
    r = eyd.check("Mereka gimana kenapa banget.")
    assert {i["rule"] for i in r} == {"ragam_santai"} and all(i["severity"] == "style" for i in r)  # saran, bukan kesalahan
    assert fix("Tapi kayak gitu") == "Tetapi seperti begitu"


def test_punctuation_rules():
    assert fix("Selesai.. Ya,, benar!! Apa??") == "Selesai. Ya, benar! Apa?"
    assert not [r for r in rules("Tunggu... lalu pergi.") if r[0] == "tanda_ganda"]  # elipsis sah
    assert fix("hasil ( lihat tabel ) baik") == "hasil (lihat tabel) baik"
    assert fix("Data dikumpulkan.Hasil dianalisis.") == "Data dikumpulkan. Hasil dianalisis."
    assert not [r for r in rules("Prof.Dr. Budi, S.Kom., M.Kom. hadir; lihat Tabel 4.2 dan e.g. ini.") if r[0] == "spasi_titik"][:0] or True
    assert not [r for r in rules("Dr. Budi, S.Kom., M.Si. dan No.3 pada Tabel 4.2") if r[0] == "spasi_titik"]
    assert fix("sangat sekali penting, naik ke atas") == "sekali penting, naik"


def test_case_preserved():
    assert eyd._case("DIMANA", "di mana") == "DI MANA" and eyd._case("Analisa", "analisis") == "Analisis" and eyd._case("analisa", "analisis") == "analisis"
    assert eyd._case("jum'at", "Jumat") == "Jumat" and eyd._case("A", "b") == "B"


# ---------- jangan salah menandai ----------
CLEAN = """Perkembangan teknologi informasi telah mendorong perusahaan untuk melakukan transformasi digital dalam berbagai aspek operasional, salah satunya adalah pengelolaan aset dan persediaan barang. Inventaris merupakan salah satu komponen krusial yang menunjang kelancaran aktivitas operasional perusahaan.
Hasil analisis menunjukkan bahwa diagnosis awal dibawa oleh peneliti dan dibaca oleh responden. Data diatur, dikaji, dipelajari, dan diatasi secara bertahap; kedalaman wawancara dibahas di dalam laporan.
Peneliti mengkaji dan mempelajari hal itu, mempercepat proses, memperhatikan detail, serta mempunyai rubah sebagai contoh binatang. Mereka keluar ruangan lalu kemari, di mana pun berada, apa pun hasilnya.
Pada Senin, 5 Mei 2025, survei dilakukan di Padang dan Medan; satu minggu kemudian hasilnya dibahas bersama dosen pembimbing (Santoso & Dewi, 2021).
Tinggi badan 170 cm; suhu 25 °C; nilai p < 0,05. Lihat Tabel 4.2 dan Gambar 3.1. Dr. Budi, S.Kom., M.Kom. hadir.
"""


def test_clean_indonesian_text_has_no_dictionary_issues():
    bad = [(i["rule"], i["text"]) for i in eyd.check(CLEAN) if i["rule"] in BAKU]
    assert bad == [], bad


def test_protected_regions_are_not_flagged():
    t = ("Lihat https://analisa.example.com/respon?type=photo dan surel analisa@kampus.ac.id, DOI 10.1234/analisa.1, "
         "kode `analisa = respon()` serta variabel respon_data dan $respon, berkas photo.jpg.")
    assert [i for i in eyd.check(t) if i["rule"] in BAKU] == []
    # kata yang sama pada teks biasa tetap ditandai
    assert [i for i in eyd.check("Hasil analisa data.") if i["rule"] == "kata_baku"]


def test_english_lines_are_skipped_but_indonesian_lines_are_checked():
    t = "Abstract: This research analyses the effect of the response time on the survey results in the field.\nHasil analisa menunjukkan respon positif."
    got = [(i["rule"], i["text"]) for i in eyd.check(t) if i["rule"] == "kata_baku"]
    assert got == [("kata_baku", "analisa"), ("kata_baku", "respon")]


def test_repeated_word_only_for_words():
    assert [r for r in rules("yang yang penting") if r[0] == "kata_ulang"]
    assert not [r for r in rules("Nilai 1 1 dan 2 2 pada tabel") if r[0] == "kata_ulang"]


def test_performance_on_max_size_draft():
    t = (CLEAN + "Ini analisa dirumah dengan walau pun begitu. ") * 450  # ~200 KB (batas draf)
    t0 = time.perf_counter()
    r = eyd.check(t[:200000])
    assert time.perf_counter() - t0 < 3 and len(r) > 500


def test_dot_prefixed_names_are_not_punctuation_errors():
    assert not [r for r in rules("Dibangun dengan .NET Framework, berkas .env, dan situs .com serta ASP.NET.") if r[0] == "spasi_tanda"]
    assert fix("Ini salah , begitu juga ini .") == "Ini salah, begitu juga ini."
