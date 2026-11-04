"""Roadmap per jenis tugas. Isi di sini buatan sendiri (bukan salinan karya orang lain);
contoh nyata dari sumber terbuka ditautkan lewat `refs` di Fase 2."""

ROADMAP = {
    "skripsi": [
        {"key": "pendahuluan", "title": "Bab 1 · Pendahuluan",
         "goal": "Meyakinkan pembaca bahwa masalahmu nyata, penting, dan bisa diteliti.",
         "checklist": ["Latar belakang bergerak dari umum ke khusus", "Ada data/fakta pendukung berikut rujukannya",
                       "Rumusan masalah terukur dan berupa pertanyaan", "Tujuan menjawab tiap rumusan masalah"],
         "tips": "Tulis rumusan masalah lebih dulu, lalu susun latar belakang sebagai jalan menuju ke sana.",
         "example": "Contoh pola: 'Penggunaan X meningkat (BPS, 2023), tetapi Y masih rendah. Hal ini menimbulkan pertanyaan: seberapa besar pengaruh X terhadap Y?'"},
        {"key": "tinjauan", "title": "Bab 2 · Tinjauan Pustaka",
         "goal": "Menunjukkan teori dan penelitian terdahulu yang menjadi pijakanmu.",
         "checklist": ["Teori dibahas sesuai variabel penelitian", "Penelitian terdahulu dibandingkan, bukan sekadar disebut",
                       "Kerangka berpikir menghubungkan teori dan hipotesis"],
         "tips": "Satu paragraf, satu gagasan, satu atau dua rujukan utama.", "example": ""},
        {"key": "metode", "title": "Bab 3 · Metode Penelitian",
         "goal": "Menjelaskan cara kerja penelitianmu sehingga orang lain bisa mengulanginya.",
         "checklist": ["Pendekatan dan desain dijustifikasi", "Populasi, sampel, dan teknik sampling jelas",
                       "Instrumen dan uji validitas/reliabilitas", "Teknik analisis data sesuai tujuan"],
         "tips": "Tiap pilihan metode butuh alasan, bukan hanya nama.", "example": ""},
        {"key": "hasil", "title": "Bab 4 · Hasil dan Pembahasan",
         "goal": "Menyajikan temuan, lalu menafsirkannya.",
         "checklist": ["Hasil disajikan sebelum ditafsirkan", "Tabel/gambar dirujuk di teks", "Temuan dibandingkan dengan teori dan penelitian lain"],
         "tips": "Pisahkan 'apa yang ditemukan' dan 'apa artinya'.", "example": ""},
        {"key": "penutup", "title": "Bab 5 · Penutup",
         "goal": "Menjawab rumusan masalah dan memberi arah lanjutan.",
         "checklist": ["Kesimpulan menjawab tiap rumusan masalah", "Saran spesifik dan dapat ditindaklanjuti", "Keterbatasan penelitian diakui"],
         "tips": "Jangan memunculkan temuan baru di bab ini.", "example": ""},
    ],
    "jurnal": [
        {"key": "abstrak", "title": "Abstrak", "goal": "Ringkasan mandiri: tujuan, metode, hasil, simpulan.",
         "checklist": ["150–250 kata", "Tanpa rujukan dan singkatan asing", "Ada hasil utama"], "tips": "Tulis terakhir.", "example": ""},
        {"key": "pendahuluan", "title": "Pendahuluan", "goal": "Celah penelitian dan kontribusimu.",
         "checklist": ["Ada research gap", "Tujuan eksplisit", "Kebaruan dinyatakan"], "tips": "Satu gap, satu kontribusi.", "example": ""},
        {"key": "metode", "title": "Metode", "goal": "Bisa direplikasi.",
         "checklist": ["Desain dan data jelas", "Teknik analisis disebut"], "tips": "Ringkas namun lengkap.", "example": ""},
        {"key": "hasil", "title": "Hasil dan Pembahasan", "goal": "Temuan dan maknanya.",
         "checklist": ["Hasil utama di depan", "Dibandingkan dengan literatur"], "tips": "Mulai dari temuan terpenting.", "example": ""},
        {"key": "simpulan", "title": "Simpulan", "goal": "Menjawab tujuan.",
         "checklist": ["Selaras dengan tujuan", "Implikasi dan keterbatasan"], "tips": "Maksimal satu halaman.", "example": ""},
    ],
}
ROADMAP["laporan_pkl"] = [
    {"key": "pendahuluan", "title": "Bab 1 · Pendahuluan",
     "goal": "Menjelaskan mengapa kamu melaksanakan PKL di tempat ini dan apa yang ingin dicapai.",
     "checklist": ["Latar belakang menghubungkan kebutuhan kompetensi dengan tempat PKL", "Tujuan dan manfaat PKL dirumuskan (bagi mahasiswa, kampus, dan instansi)",
                   "Lokasi, waktu, dan ruang lingkup kegiatan jelas", "Ada sistematika penulisan laporan"],
     "tips": "Tulis tujuan PKL sebagai kompetensi yang ingin kamu kuasai, bukan sekadar 'memenuhi syarat kuliah'.", "example": ""},
    {"key": "profil", "title": "Bab 2 · Profil Instansi",
     "goal": "Memberi gambaran instansi tempat PKL secukupnya agar pembaca memahami konteks kerjamu.",
     "checklist": ["Sejarah singkat dan bidang usaha atau layanan instansi", "Visi, misi, dan struktur organisasi (bagan disertai penjelasan)",
                   "Unit tempat kamu ditempatkan beserta tugas unit itu", "Sumber data profil disebutkan (dokumen internal, situs resmi)"],
     "tips": "Fokuskan pada unit tempatmu bekerja; profil instansi tidak perlu lebih panjang daripada uraian kegiatanmu.", "example": ""},
    {"key": "pelaksanaan", "title": "Bab 3 · Pelaksanaan Kegiatan",
     "goal": "Menguraikan apa yang kamu kerjakan selama PKL secara runtut dan dapat diverifikasi.",
     "checklist": ["Jadwal atau kronologi kegiatan per periode (mis. per minggu)", "Uraian tiap kegiatan: apa yang dikerjakan, bagaimana, dengan alat atau metode apa",
                   "Peran pembimbing lapangan dan bentuk bimbingan yang diterima", "Kegiatan dikaitkan dengan kompetensi yang ditargetkan di Bab 1"],
     "tips": "Satu kegiatan, satu paragraf: tujuan, langkah, hasil. Tabel jadwal membantu pembaca.", "example": ""},
    {"key": "hasil", "title": "Bab 4 · Hasil dan Pembahasan",
     "goal": "Menyajikan hasil kerjamu, lalu membahas kesesuaian teori dengan praktik di lapangan.",
     "checklist": ["Hasil kerja, produk, atau temuan disajikan dengan bukti (tabel, gambar, tangkapan layar)", "Teori dari perkuliahan dikaitkan dengan praktik, bukan hanya dikutip",
                   "Kendala yang dihadapi dan cara mengatasinya diuraikan", "Ada refleksi: apa yang dipelajari dan apa yang akan dilakukan berbeda"],
     "tips": "Pisahkan 'apa yang kamu kerjakan' (Bab 3) dari 'apa artinya' (Bab 4).", "example": ""},
    {"key": "penutup", "title": "Bab 5 · Penutup",
     "goal": "Menyimpulkan capaian PKL dan memberi masukan yang berguna.",
     "checklist": ["Kesimpulan menjawab tujuan PKL di Bab 1", "Saran untuk instansi spesifik dan realistis",
                   "Saran untuk kampus atau program studi (mis. kesiapan kompetensi)", "Tidak ada informasi baru yang muncul di bab ini"],
     "tips": "Cocokkan tiap kesimpulan dengan satu tujuan di Bab 1.", "example": ""},
]
ROADMAP["proposal"] = [
    {"key": "pendahuluan", "title": "Bab 1 · Pendahuluan",
     "goal": "Meyakinkan penguji bahwa masalahmu nyata, penting, dan layak diteliti dalam waktu yang tersedia.",
     "checklist": ["Latar belakang bergerak dari umum ke khusus dengan data dan rujukan", "Celah penelitian atau masalah nyata dinyatakan eksplisit",
                   "Rumusan masalah terukur, berupa pertanyaan, dan selaras dengan tujuan", "Manfaat dan batasan penelitian jelas"],
     "tips": "Di seminar proposal, kelayakan adalah yang pertama diuji: pastikan rumusan masalahmu bisa dijawab dengan data yang benar-benar dapat kamu peroleh.", "example": ""},
    {"key": "tinjauan", "title": "Bab 2 · Tinjauan Pustaka",
     "goal": "Menunjukkan landasan teori dan penelitian terdahulu yang membuat penelitianmu masuk akal.",
     "checklist": ["Teori dibatasi pada variabel atau konsep penelitian", "Penelitian terdahulu dibandingkan (apa temuannya, apa bedanya dengan penelitianmu)",
                   "Kerangka berpikir menghubungkan teori, masalah, dan hipotesis (bila ada)", "Rujukan mutakhir dan berasal dari sumber yang kredibel"],
     "tips": "Susun per konsep, bukan per penulis.", "example": ""},
    {"key": "metode", "title": "Bab 3 · Metode Penelitian",
     "goal": "Merancang cara kerja yang konkret agar penguji yakin penelitianmu dapat dilaksanakan.",
     "checklist": ["Pendekatan dan desain penelitian dijustifikasi", "Populasi, sampel, atau subjek dan teknik pengambilannya jelas",
                   "Instrumen, sumber data, dan rencana uji validitas atau reliabilitas", "Teknik analisis data sesuai dengan rumusan masalah", "Pertimbangan etika dan keterbatasan disebutkan"],
     "tips": "Tiap rumusan masalah harus punya teknik analisis yang menjawabnya.", "example": ""},
    {"key": "jadwal", "title": "Jadwal dan Rencana Penelitian",
     "goal": "Menunjukkan bahwa penelitianmu bisa selesai tepat waktu dengan sumber daya yang ada.",
     "checklist": ["Tahapan penelitian berurutan dengan perkiraan waktu", "Risiko utama (mis. akses data, izin) dan rencana cadangannya", "Rencana biaya atau sumber daya bila dipersyaratkan kampus"],
     "tips": "Tabel jadwal per bulan lebih mudah diperiksa penguji.", "example": ""},
]
ROADMAP["ta"] = ROADMAP["skripsi"]

# Registri jenis dokumen: satu sumber kebenaran untuk dropdown, label sampul ekspor, dan jenis tata letak.
# kind: "thesis" = tiap bab di halaman baru, sampul, daftar isi; "article" = mengalir seperti artikel.
DOC_TYPES = [
    {"key": "skripsi", "label": "Skripsi", "cover": "SKRIPSI", "kind": "thesis"},
    {"key": "proposal", "label": "Proposal penelitian (sempro)", "cover": "PROPOSAL PENELITIAN", "kind": "thesis"},
    {"key": "laporan_pkl", "label": "Laporan PKL", "cover": "LAPORAN PRAKTIK KERJA LAPANGAN", "kind": "thesis"},
    {"key": "jurnal", "label": "Artikel jurnal", "cover": "ARTIKEL JURNAL", "kind": "article"},
    {"key": "ta", "label": "Tugas akhir", "cover": "TUGAS AKHIR", "kind": "thesis"},
]
DOC_BY_KEY = {d["key"]: d for d in DOC_TYPES}

# Mode Sidang: AI berperan sebagai dosen penguji. doc_types = dokumen yang jadi bahan pertanyaan (dipilih yang paling banyak isinya).
SIDANG_MODES = {
    "pkl": {"label": "Sidang PKL", "doc_types": ["laporan_pkl"],
            "desc": "Penguji menggali pengalaman kerjamu: tugas yang kamu kerjakan sendiri, kontribusi, kendala, dan kaitannya dengan teori kuliah.",
            "fokus": "pengalaman kerja nyata dan peran pribadi mahasiswa, kontribusi bagi instansi, kendala dan solusi, kaitan teori perkuliahan dengan praktik, pelajaran yang diperoleh, etika dan disiplin kerja"},
    "sempro": {"label": "Seminar proposal (sempro)", "doc_types": ["proposal"],
               "desc": "Penguji menguji kelayakan rencanamu: urgensi masalah, rumusan, landasan teori, kecocokan metode, ketersediaan data, dan jadwal.",
               "fokus": "urgensi dan kelayakan masalah, celah penelitian, ketepatan rumusan masalah dan tujuan, landasan teori, kesesuaian metode dengan rumusan masalah, ketersediaan data dan izin, risiko serta jadwal"},
    "skripsi": {"label": "Sidang skripsi", "doc_types": ["skripsi", "ta"],
                "desc": "Penguji menguji hasil penelitianmu: validitas, ketepatan analisis, kesesuaian simpulan, keterbatasan, dan kontribusi.",
                "fokus": "validitas dan reliabilitas, ketepatan analisis dan interpretasi hasil, kesesuaian simpulan dengan rumusan masalah, perbandingan dengan penelitian terdahulu, keterbatasan, implikasi dan saran, orisinalitas kontribusi"},
}
SIDANG_PERSONAS = {
    "suportif": {"label": "Suportif", "desc": "Ramah, pertanyaan terbuka, banyak petunjuk. Cocok untuk pemanasan.",
                 "gaya": "ramah dan menenangkan; pertanyaan terbuka; beri petunjuk arah bila jawaban kurang"},
    "standar": {"label": "Standar", "desc": "Seimbang, seperti kebanyakan penguji.",
                "gaya": "seimbang dan profesional; campur pertanyaan pemahaman dan pertanyaan penggalian"},
    "kritis": {"label": "Kritis", "desc": "Tegas, menuntut dasar data dan rujukan. Tetap sopan.",
               "gaya": "tegas dan kritis; menuntut dasar data, rujukan, dan konsistensi antar bab; menguji celah logika; selalu sopan dan tidak merendahkan"},
}
for _m in SIDANG_MODES.values():
    assert all(d in ROADMAP for d in _m["doc_types"])
assert set(DOC_BY_KEY) == set(ROADMAP) and all(len(k) <= 20 for k in ROADMAP), "DOC_TYPES dan ROADMAP harus sinkron (kolom doc_type maks. 20 karakter)"
