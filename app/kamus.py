"""Kamus pemeriksa ejaan (acuan: EYD Edisi V 2022 dan KBBI Daring, Badan Bahasa).

ATURAN MENAMBAH ENTRI: hanya bentuk yang PASTI tidak baku menurut KBBI/EYD V. Menyuruh mahasiswa mengubah kata yang
sudah benar jauh lebih merugikan daripada melewatkan satu kata. Karena itu sengaja TIDAK dimasukkan:
  - bentuk yang diperdebatkan (mis. telanjur/terlanjur, memerhatikan/memperhatikan, mengkritik/mengritik);
  - kata asing yang sah dipakai apa adanya (mis. type, standard, photo, extra: umum di teks Inggris dan kode program);
  - kata yang punya arti lain (mis. rubah = binatang, minggu = pekan, padang, medan, malang).
Kunci: huruf kecil, satu kata (boleh bertanda hubung/apostrof). Frasa lebih dari satu kata ada di FRASA.
"""

# Ejaan unsur serapan
SERAPAN = {
    "aktifitas": "aktivitas", "aktifis": "aktivis", "efektifitas": "efektivitas", "kreatifitas": "kreativitas",
    "produktifitas": "produktivitas", "objektifitas": "objektivitas", "sensitifitas": "sensitivitas", "intensifitas": "intensitas",
    "motifasi": "motivasi", "analisa": "analisis", "diagnosa": "diagnosis", "hipotesa": "hipotesis", "sintesa": "sintesis",
    "metoda": "metode", "methode": "metode", "resiko": "risiko", "propinsi": "provinsi", "prosentase": "persentase",
    "presentase": "persentase", "prosen": "persen", "praktek": "praktik", "apotik": "apotek", "atlit": "atlet", "azas": "asas",
    "coklat": "cokelat", "cidera": "cedera", "detil": "detail", "ekstrim": "ekstrem", "kongkrit": "konkret", "konkrit": "konkret",
    "komplek": "kompleks", "kordinasi": "koordinasi", "kordinator": "koordinator", "konsekwen": "konsekuen",
    "konsekwensi": "konsekuensi", "kwalitas": "kualitas", "kwantitas": "kuantitas", "kwalitatif": "kualitatif",
    "kwantitatif": "kuantitatif", "frekwensi": "frekuensi", "ekwivalen": "ekuivalen", "kwartal": "kuartal", "kwitansi": "kuitansi",
    "kuisioner": "kuesioner", "kwesioner": "kuesioner", "quesioner": "kuesioner", "hirarki": "hierarki", "karir": "karier",
    "sistim": "sistem", "sistimatis": "sistematis", "tehnik": "teknik", "tehnis": "teknis", "tehnologi": "teknologi",
    "standarisasi": "standardisasi", "survey": "survei", "respon": "respons", "vidio": "video", "pasport": "paspor",
    "obyek": "objek", "obyektif": "objektif", "subyek": "subjek", "subyektif": "subjektif", "projek": "proyek",
    "katagori": "kategori", "orisinil": "orisinal", "profesionil": "profesional", "tradisionil": "tradisional",
    "rasionil": "rasional", "emosionil": "emosional", "realita": "realitas", "efesien": "efisien", "experimen": "eksperimen",
    "kontinyu": "kontinu", "kontinyuitas": "kontinuitas", "ambulan": "ambulans", "disain": "desain", "disainer": "desainer",
    "elit": "elite", "pondasi": "fondasi", "jendral": "jenderal", "kaos": "kaus", "akte": "akta", "adzan": "azan",
    "komplit": "komplet", "lembab": "lembap", "peforma": "performa", "telor": "telur", "handal": "andal",
    "kehandalan": "keandalan", "himbau": "imbau", "himbauan": "imbauan", "menghimbau": "mengimbau", "kharisma": "karisma",
    "trilyun": "triliun", "milyar": "miliar", "milyaran": "miliaran", "antri": "antre", "antrian": "antrean",
}

# Bentukan kata (imbuhan)
AFIKS = {
    "merubah": "mengubah", "dirubah": "diubah", "mempengaruhi": "memengaruhi", "mempesona": "memesona",
    "mengkonsumsi": "mengonsumsi", "menterjemahkan": "menerjemahkan", "penterjemah": "penerjemah", "mentaati": "menaati",
    "mensukseskan": "menyukseskan", "mensosialisasikan": "menyosialisasikan", "mentertibkan": "menertibkan",
    "menyolok": "mencolok", "pengrajin": "perajin", "pengrusakan": "perusakan", "berfikir": "berpikir", "fikiran": "pikiran",
    "memfikirkan": "memikirkan", "ketrampilan": "keterampilan", "ketentraman": "ketenteraman", "berhutang": "berutang",
    "menasehati": "menasihati", "nasehat": "nasihat",
}

# Ejaan lain
LAIN = {
    "ijin": "izin", "ijasah": "ijazah", "jaman": "zaman", "jadual": "jadwal", "jenasah": "jenazah", "jum'at": "Jumat",
    "jum’at": "Jumat", "kuatir": "khawatir", "kemaren": "kemarin", "kerjasama": "kerja sama", "tanggungjawab": "tanggung jawab",
    "tatacara": "tata cara", "lobang": "lubang", "mesjid": "masjid", "merk": "merek", "nafas": "napas", "negri": "negeri",
    "nomer": "nomor", "nopember": "November", "pebruari": "Februari", "pinsil": "pensil", "rapot": "rapor", "rejeki": "rezeki",
    "sekedar": "sekadar", "seksama": "saksama", "silahkan": "silakan", "syah": "sah", "tauladan": "teladan",
    "tentram": "tenteram", "trampil": "terampil", "hutang": "utang", "hakekat": "hakikat", "fikir": "pikir",
    "nampak": "tampak", "bahwasannya": "bahwasanya", "gubug": "gubuk", "dimana-mana": "di mana-mana",
}

# Singkatan dan ragam santai yang tetap diperlakukan sebagai kesalahan (kompatibel dengan versi sebelumnya)
SINGKATAN = {
    "yg": "yang", "dgn": "dengan", "utk": "untuk", "tdk": "tidak", "krn": "karena", "sdh": "sudah", "blm": "belum",
    "spt": "seperti", "dlm": "dalam", "dpt": "dapat", "lbh": "lebih", "sbg": "sebagai", "karna": "karena",
    "gak": "tidak", "ga": "tidak", "udah": "sudah", "klo": "kalau",
}

# Ragam santai: ditandai sebagai SARAN (bukan kesalahan) karena bisa sah di kutipan langsung (mis. hasil wawancara)
SANTAI = {
    "gimana": "bagaimana", "kenapa": "mengapa", "bikin": "membuat", "banget": "sekali", "bgt": "sekali", "cuma": "hanya",
    "cuman": "hanya", "kayak": "seperti", "kayaknya": "sepertinya", "emang": "memang", "emangnya": "memangnya",
    "nggak": "tidak", "enggak": "tidak", "gini": "begini", "gitu": "begitu", "pake": "pakai", "tapi": "tetapi",
    "aja": "saja", "doang": "saja", "ntar": "nanti", "makasih": "terima kasih", "soalnya": "sebab", "ngomong": "berbicara",
    "ngerti": "mengerti", "dikasih": "diberi",
}

# Partikel -pun: ditulis terpisah, kecuali 12 kata (adapun, andaipun, ataupun, bagaimanapun, biarpun, kalaupun, kendatipun,
# maupun, meskipun, sekalipun, sungguhpun, walaupun)
PUN_PISAH = {
    "apapun": "apa pun", "siapapun": "siapa pun", "kapanpun": "kapan pun", "manapun": "mana pun", "berapapun": "berapa pun",
    "dimanapun": "di mana pun", "kemanapun": "ke mana pun",
}
PUN_GABUNG = ("walau", "meski", "kendati", "sungguh", "biar", "kalau", "atau", "bagaimana")

# Frasa (dua kata atau lebih) yang seharusnya serangkai
FRASA = {
    "dari pada": "daripada", "apa bila": "apabila", "bila mana": "bilamana", "olah raga": "olahraga",
    "sebagai mana": "sebagaimana",
}

# Frasa boros (pleonasme): saran bersifat gaya
BOROS = {
    "dalam rangka untuk": "untuk", "adalah merupakan": "merupakan", "agar supaya": "agar", "demi untuk": "untuk",
    "naik ke atas": "naik", "turun ke bawah": "turun", "mundur ke belakang": "mundur", "maju ke depan": "maju",
    "kurang lebih sekitar": "sekitar", "sangat sekali": "sekali", "mengulang kembali": "mengulang",
}

# Nama diri yang harus berhuruf kapital (hanya bila ditulis seluruhnya huruf kecil)
KAPITAL_NAMA = frozenset("""
januari februari maret april mei juni juli agustus september oktober november desember
senin selasa rabu kamis jumat sabtu
indonesia inggris arab jepang jerman belanda prancis perancis tiongkok melayu korea amerika eropa asia afrika
jawa sumatera kalimantan sulawesi papua jakarta bandung surabaya yogyakarta semarang makassar palembang
""".split())

# Kata depan yang salah ditulis serangkai
DI_PLACE = ("rumah|sekolah|kampus|kantor|sini|situ|sana|mana|atas|bawah|dalam|luar|depan|belakang|samping|kelas|kota|desa|"
            "daerah|wilayah|tempat|lokasi|dunia|masa|saat|zaman|era|toko|pasar|gedung|ruang|laboratorium|antara|sekitar|"
            "tengah|seberang|hadapan|lapangan|negara")
KE_PLACE = "sini|situ|sana|mana|dalam|atas|bawah|depan|belakang|samping|kanan|kiri|rumah|sekolah|kampus|kantor|kelas|tengah|seberang"
DARI_PLACE = "mana|sini|sana|situ|dalam|luar|atas|bawah"
# kata kerja pasif yang sering salah ditulis "di <kata kerja>"
DI_VERB = ("makan|lakukan|gunakan|buat|tulis|ambil|pakai|anggap|sebut|jelaskan|bahas|teliti|kumpulkan|temukan|peroleh|uji|ukur|"
           "tentukan|sajikan|simpulkan|rancang|bangun|kembangkan|terapkan|tunjukkan|hitung|kaji|amati|pilih|olah|susun|"
           "laksanakan|kerjakan|hasilkan")

GROUPS = {"SERAPAN": SERAPAN, "AFIKS": AFIKS, "LAIN": LAIN, "SINGKATAN": SINGKATAN}
NONBAKU: dict[str, str] = {}
for _g in GROUPS.values():
    for _k, _v in _g.items():
        assert NONBAKU.setdefault(_k, _v) == _v, f"entri ganda dengan nilai berbeda: {_k}"
