"""Variasi dan pijakan pertanyaan dosen penguji/pembimbing.

Dosen sungguhan tidak menanyakan hal yang sama pada tiap mahasiswa, dan pertanyaannya selalu berpijak pada naskah yang ia baca. Modul ini
menjaga dua hal itu secara deterministik (tanpa biaya token), lalu menyerahkan pengisian pertanyaannya pada AI:

  plan()     : urutan JENIS pertanyaan untuk satu sesi (pembuka -> beragam -> penutup), diacak oleh `seed` (id sesi) sehingga tiap sesi berbeda
               tetapi dapat direproduksi.
  anchors()  : TITIK BIDIK, yaitu kutipan dari bagian naskah yang berbeda-beda untuk tiap giliran, agar pertanyaan tersebar di seluruh naskah.
  anchored() : memeriksa bahwa pertanyaan benar-benar menunjuk naskah (kutipan `rujukan` ada di naskah).
  similar()  : menolak pertanyaan yang terlalu mirip dengan yang sudah ditanyakan.
  fallback() : pertanyaan cadangan yang pasti berpijak pada naskah bila AI melenceng dua kali."""
import random
import re

TYPES = {
    "pembuka": ("Pembuka", "Minta mahasiswa menjelaskan inti tulisannya dengan kata sendiri, sambil menyentuh satu bagian konkret dari tulisan."),
    "klarifikasi": ("Klarifikasi", "Minta penjelasan istilah, konsep, alur, atau bagian yang tertulis terlalu ringkas atau kurang jelas."),
    "justifikasi": ("Justifikasi pilihan", "Tanyakan alasan memilih metode/alat/teori/rancangan/data tertentu dan bukan alternatifnya."),
    "bukti": ("Dasar dan bukti", "Tanyakan dasar data, rujukan, atau perhitungan di balik klaim, angka, atau hasil yang tertulis."),
    "konsistensi": ("Konsistensi", "Pertemukan dua bagian (atau bab) yang tampak tidak selaras atau perlu dihubungkan: rumusan masalah, tujuan, metode, hasil, simpulan."),
    "pembandingan": ("Pembandingan", "Tanyakan perbedaan, kelebihan, dan kekurangan dibanding penelitian, sistem, atau pendekatan lain yang relevan."),
    "kritik": ("Keterbatasan dan risiko", "Tanyakan kelemahan, asumsi, keterbatasan, atau risiko pekerjaan ini dan dampaknya pada simpulan."),
    "skenario": ("Skenario 'bagaimana jika'", "Ajukan situasi hipotetis yang masuk akal (data, skala, pengguna, atau kondisi berubah) dan tanyakan dampaknya."),
    "validasi": ("Pengujian dan validasi", "Tanyakan bagaimana mahasiswa memastikan hasilnya benar dan andal, termasuk pengujian yang dilakukan atau direncanakan."),
    "kontribusi": ("Kontribusi dan manfaat", "Tanyakan kontribusi nyata, manfaat, atau implikasi bagi pengguna, instansi, atau ilmu pengetahuan."),
    "peran": ("Peran pribadi", "Tanyakan bagian mana yang dikerjakan sendiri oleh mahasiswa, keputusan apa yang ia ambil, dan bagaimana ia dapat membuktikannya."),
    "kendala": ("Kendala dan solusi", "Tanyakan kendala tersulit yang dihadapi, cara mengatasinya, dan pelajarannya."),
    "teori_praktik": ("Teori dan praktik", "Tanyakan teori atau konsep kuliah mana yang dipakai dan di bagian mana tampak pada pekerjaannya."),
    "refleksi": ("Refleksi dan tindak lanjut", "Tanyakan apa yang akan dilakukan berbeda, apa yang belum tuntas, dan rencana tindak lanjut."),
}

# Kurikulum jenis pertanyaan per mode: pembuka tetap di awal, penutup di akhir, bagian tengah diacak per sesi.
POOL = {
    "pkl": {"buka": "pembuka", "tutup": "refleksi", "tengah": ["peran", "teori_praktik", "kendala", "bukti", "validasi", "kontribusi", "skenario", "konsistensi", "kritik"]},
    "sempro": {"buka": "pembuka", "tutup": "kritik", "tengah": ["justifikasi", "pembandingan", "konsistensi", "bukti", "skenario", "klarifikasi", "validasi", "kontribusi"]},
    "skripsi": {"buka": "pembuka", "tutup": "kontribusi", "tengah": ["bukti", "validasi", "konsistensi", "pembandingan", "justifikasi", "kritik", "skenario", "klarifikasi"]},
    "bimbingan": {"buka": "klarifikasi", "tutup": "refleksi", "tengah": ["justifikasi", "bukti", "konsistensi", "kritik", "skenario", "validasi", "pembandingan"]},
}

TEMPLATES = {
    "pembuka": ["Sebelum masuk ke detail, ceritakan secara singkat inti {doc}-mu. Misalnya pada bagian “{a}”: apa peran gagasan itu dalam keseluruhan {doc}?",
                "Silakan jelaskan dengan kata-katamu sendiri apa yang kamu kerjakan dalam {doc} ini. Saya tertarik pada bagian “{a}”; mengapa bagian itu penting?"],
    "klarifikasi": ["Kamu menulis “{a}”. Coba jelaskan dengan bahasamu sendiri apa maksudnya dan mengapa itu penting di sini.",
                    "Bagian “{a}” terasa ringkas bagi pembaca yang belum tahu konteksnya. Bagaimana kamu menjelaskannya kepada orang awam?"],
    "justifikasi": ["Pada bagian “{a}”, mengapa kamu memilih cara itu dan bukan alternatif lain? Apa pertimbanganmu?",
                    "Saya melihat keputusan di “{a}”. Alternatif apa yang sempat kamu pertimbangkan, dan apa yang membuatmu menolaknya?"],
    "bukti": ["Kamu menyatakan “{a}”. Apa dasar data atau rujukan yang menopang pernyataan itu?",
              "Soal “{a}”: dari mana angka atau klaim itu berasal, dan bagaimana saya bisa memeriksanya?"],
    "konsistensi": ["Bagian “{a}” harus selaras dengan bagian lain tulisanmu. Bagaimana kamu memastikan konsistensinya dengan rumusan masalah dan simpulan?",
                    "Di satu tempat kamu menulis “{a}”. Di bagian lain, adakah yang tampak berlawanan atau belum terhubung dengannya? Jelaskan hubungannya."],
    "pembandingan": ["Terkait “{a}”, apa bedanya dengan pendekatan yang sudah ada sebelumnya? Apa kelebihan dan kekurangannya?",
                     "Jika pembaca membandingkan “{a}” dengan karya lain yang serupa, apa yang membuat pekerjaanmu berbeda?"],
    "kritik": ["Dari bagian “{a}”, apa kelemahan atau keterbatasan yang paling berpengaruh, dan bagaimana dampaknya pada kesimpulanmu?",
               "Apa asumsi di balik “{a}”, dan apa yang terjadi bila asumsi itu tidak terpenuhi?"],
    "skenario": ["Misalkan kondisi pada “{a}” berubah (data lebih besar, pengguna berbeda, atau asumsi tidak terpenuhi). Apa yang terjadi pada hasilmu dan apa yang kamu lakukan?",
                 "Bagaimana jika “{a}” tidak bisa dilakukan seperti rencana? Apa rencana cadanganmu?"],
    "validasi": ["Bagaimana kamu memastikan “{a}” benar dan dapat diandalkan? Pengujian apa yang sudah kamu lakukan?",
                 "Untuk “{a}”, bukti apa yang menunjukkan hasilnya valid dan bukan kebetulan?"],
    "kontribusi": ["Dari “{a}”, apa manfaat nyata yang dihasilkan, dan bagi siapa?",
                   "Jika {doc}-mu dipakai orang lain, bagian “{a}” memberi kontribusi apa yang tidak ada sebelumnya?"],
    "peran": ["Pada bagian “{a}”, mana yang kamu kerjakan sendiri, dan keputusan apa yang kamu ambil?",
              "Kalau saya menelepon pembimbing lapanganmu, apa yang akan beliau katakan tentang peranmu di “{a}”?"],
    "kendala": ["Terkait “{a}”, apa kendala tersulit yang kamu hadapi dan bagaimana kamu mengatasinya?",
                "Pada “{a}”, apa yang tidak berjalan sesuai rencana, dan apa yang kamu pelajari darinya?"],
    "teori_praktik": ["Teori atau konsep kuliah apa yang kamu pakai pada “{a}”, dan di mana tampaknya dalam pekerjaanmu?",
                      "Pada “{a}”, mata kuliah mana yang paling membantu dan apa yang justru tidak diajarkan di kampus?"],
    "refleksi": ["Setelah mengerjakan “{a}”, apa yang akan kamu lakukan berbeda, dan apa tindak lanjut yang kamu rencanakan?",
                 "Jika diberi kesempatan mengulang bagian “{a}”, apa yang kamu ubah dan mengapa?"],
}
PENDALAMAN = ["Jawabanmu tadi masih umum. Kembali ke bagian “{q}”: coba jawab lagi dengan satu contoh atau angka konkret dari tulisanmu.",
              "Saya belum menangkap jawabanmu soal “{q}”. Tunjukkan bagian tulisanmu yang mendukung jawabanmu."]
TONE = {"suportif": "", "standar": "", "kritis": "Saya ingin memastikan. "}

STOP = frozenset("yang dengan untuk dalam pada dari atau dan itu ini adalah akan telah dapat tidak juga serta oleh karena sebagai antara bagaimana mengapa apakah jelaskan kamu "
                 "anda dalam tersebut sebuah suatu lebih agar bahwa sehingga terhadap".split())
KEY = re.compile(r"\b(karena|sehingga|menggunakan|metode|hasil|menunjukkan|diuji|dirancang|rumusan|tujuan|simpulan|kesimpulan|berdasarkan|dibandingkan|akurasi|responden|sampel|"
                 r"variabel|data|sistem|algoritma|model|rancangan|pengujian|validasi|instansi|tugas|masalah|persen|meningkat|menurun|mengukur)\b", re.I)
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[“”\"'`‹›]", "", s or "").lower().split())


def _toks(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{4,}", _norm(s)) if w not in STOP}


def plan(mode: str, total: int, seed: int) -> list[str]:
    """Urutan jenis pertanyaan untuk `total` giliran: pembuka, bagian tengah teracak (tanpa jenis sama berurutan), lalu penutup."""
    cfg = POOL.get(mode) or POOL["skripsi"]
    rnd = random.Random(f"{mode}:{seed}")
    if total <= 1:
        return [cfg["buka"]]
    mid_n, mid = max(total - 2, 0), []
    while len(mid) < mid_n:
        cyc = list(cfg["tengah"])
        rnd.shuffle(cyc)
        if mid and cyc[0] == mid[-1]:
            cyc.append(cyc.pop(0))
        mid += cyc
    return [cfg["buka"], *mid[:mid_n], cfg["tutup"]]


def jenis_for(mode: str, total: int, seed: int, n: int) -> str:
    p = plan(mode, total, seed)
    return p[min(max(n, 1), len(p)) - 1]


def _clip_words(s: str, n: int = 24) -> str:
    w = s.split()
    return " ".join(w[:n]) + ("…" if len(w) > n else "")


def _score(sent: str) -> int:
    n = len(sent.split())
    return (2 if re.search(r"\d", sent) else 0) + min(3, len(KEY.findall(sent))) + (1 if 10 <= n <= 28 else 0) + (1 if re.search(r"\b[A-Z][a-z]+\b.*\b[A-Z][a-z]+\b", sent) else 0)


def sentences(context: str) -> list[str]:
    """Kalimat uraian dari bahan naskah (tanpa judul bab/penanda tabel-gambar dalam kurung siku, dan tanpa baris tabel)."""
    out = []
    for line in (context or "").split("\n"):
        t = line.strip()
        if not t or t.startswith(("[", "|", "![")):  # judul bab '[Bab 1 · ...]', ringkasan/penanda tabel dan gambar (bisa terpotong), baris tabel: bukan titik bidik
            continue
        t = re.sub(r"^\d+(?:\.\d+)*\s+", "", t)
        # kalimat uraian: berakhir tanda baca akhir kalimat, atau cukup panjang; judul dan keterangan ('Skenario Use Case UC-03 ...') bukan klaim yang bisa ditanyakan
        out += [x.strip() for x in SENT_SPLIT.split(t) if 7 <= len(x.split()) <= 40 and (x.rstrip()[-1:] in ".!?" or len(x.split()) >= 14)]
    return out


def anchors(context: str, n: int, seed: int, k: int = 3, used_text: str = "") -> list[str]:
    """Hingga k kutipan dari bagian naskah yang berbeda untuk giliran ke-n. Naskah dibagi 6 wilayah; wilayah dikunjungi dalam urutan acak per sesi
    (bergeser tiap giliran), dan kalimat yang sudah dipakai pertanyaan sebelumnya dilewati."""
    sents = sentences(context)
    if not sents:
        return []
    used = _norm(used_text)
    r = min(6, len(sents))
    regions = [sents[i * len(sents) // r:(i + 1) * len(sents) // r] for i in range(r)]
    step = max(1, r // max(k, 1))
    order = list(range(r))
    random.Random(f"anchor:{seed}").shuffle(order)  # urutan kunjungan wilayah acak per sesi: tiap putaran r giliran menyentuh SEMUA wilayah naskah
    out = []
    for j in range(k):
        reg = regions[order[(n - 1 + j * step) % r]]
        cand = sorted((s for s in reg if _norm(s)[:50] not in used), key=lambda s: (-_score(s), len(s)))
        if cand and _clip_words(cand[0]) not in out:
            out.append(_clip_words(cand[0]))
    return out


def anchored(question: str, rujukan: str, context: str) -> bool:
    """Benar bila pertanyaan jelas menunjuk naskah: `rujukan` ada di naskah, atau pertanyaan memuat potongan 4 kata berurutan dari naskah."""
    ctx = _norm(context)
    r = _norm(rujukan).rstrip("….")
    if len(r) >= 12 and r in ctx:
        return True
    w = _norm(question).split()
    return any(" ".join(w[i:i + 4]) in ctx for i in range(max(0, len(w) - 3)))


def similar(question: str, previous: list[str], threshold: float = 0.6) -> bool:
    a = _toks(question)
    if len(a) < 3:
        return False
    return any(len(a & b) / max(1, len(a | b)) >= threshold for b in map(_toks, previous) if b)


def fallback(jenis: str, anchor: str, doc_label: str, persona: str, n: int, seed: int) -> str:
    """Pertanyaan cadangan yang pasti berpijak pada naskah (dipakai bila AI dua kali tidak menunjuk naskah atau mengulang)."""
    variants = TEMPLATES.get(jenis) or TEMPLATES["klarifikasi"]
    t = variants[(seed + n) % len(variants)]
    return (TONE.get(persona, "") + t.format(a=anchor or "bagian ini", doc=doc_label.lower())).strip()


def pendalaman(prev_question: str, seed: int, n: int) -> str:
    """Pertanyaan lanjutan atas jawaban lemah. Yang dikutip adalah bagian naskah yang ditanyakan sebelumnya (kutipan di dalam pertanyaan lalu),
    bukan seluruh pertanyaan lalu, agar tidak terbaca janggal (awalan nada dan tanda kutip bersarang)."""
    m = re.search(r"“([^“”]{8,}?)”", prev_question)
    q = _clip_words(m.group(1) if m else prev_question, 14).rstrip("….")
    return PENDALAMAN[(seed + n) % len(PENDALAMAN)].format(q=q)
