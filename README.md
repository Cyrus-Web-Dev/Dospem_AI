# Dospem — dospem digital untuk skripsi, jurnal, dan tugas akhir

Platform bimbingan menulis: AI **memberi komentar dan pertanyaan, bukan menuliskan isi**. Stack: Python + FastAPI, SQLAlchemy 2, Alembic,
PostgreSQL, Redis, frontend HTML/JS murni (disajikan FastAPI).

## Menjalankan (pengembangan)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env               # isi SECRET_KEY dan CONTACT_EMAIL
docker compose up -d db redis      # Postgres di host:5433 (bukan 5432, agar tidak bentrok dengan PostgreSQL lokal)
                                   # atau pakai sqlite: DATABASE_URL=sqlite:///./dospem.db (REDIS_URL boleh kosong)
alembic upgrade head               # buat/migrasi skema
uvicorn app.main:app --reload      # http://127.0.0.1:8000  (docs API: /docs)
pytest                             # 208 tes (201 jalan di SQLite; 7 tes backup butuh PostgreSQL + pg_dump dan dilewati bila tak ada) (SQLite sementara; TEST_DATABASE_URL=postgresql+psycopg://... untuk uji di Postgres)
```
Perubahan model: `alembic revision --autogenerate -m "pesan"` → periksa file → `alembic upgrade head`. `alembic check` memastikan model dan migrasi sinkron.

## Halaman
| URL | Untuk | Isi |
|---|---|---|
| `/` | mahasiswa | roadmap bab, editor, cek EYD V, komentar dospem, contoh rujukan, gaya selingkung, hubungkan dosen, premium |
| `/dosen.html` | dosen | kode undangan, progres per bab, mahasiswa tertahan, baca draf (hanya-baca), analitik kelas |
| `/admin.html` | admin (`ADMIN_EMAILS`) | anotasi contoh, pembayaran, kampus & dosen, gaya selingkung, analitik platform |

## Fitur
- **Cek ejaan** berbasis aturan (EYD V; gratis, tanpa kuota) + **komentar dospem** via LLM (kuota harian: gratis 5, premium 50).
- **Analisis logika bab (Premium)**: rubrik per butir checklist, alur antar paragraf, pertanyaan yang mungkin diajukan dosen. Tidak menulis ulang teks.
- **Contoh rujukan** (tab Rujukan): OpenAlex, Crossref, dan DOAJ aktif otomatis dan dipanggil **paralel** (hasil di-cache 6 jam; Redis bila ada).
  Abstrak tampil hanya bila lisensinya CC-BY/CC0. **Jurnal OJS Indonesia** dipanen admin lewat OAI-PMH (tab Anotasi di `/admin.html`) lalu dicari lokal.
  Tombol "Cari juga di" membuka Google Scholar, Garuda, dan SINTA (tidak ada API publik; tidak di-scrape).
  **Semantic Scholar** dan **CORE** tersedia tetapi NONAKTIF secara default (`SEMANTIC_SCHOLAR_ENABLED`, `CORE_ENABLED` + kunci): ketentuan layanan
  keduanya membatasi pemakaian bawaan ke riset/pendidikan non-komersial, jadi aktifkan hanya setelah memastikan izin untuk produk berbayar.
  Anotasi kurasi di `/admin.html`.
- **Jenis dokumen**: Skripsi, Proposal penelitian (sempro), Laporan PKL, Artikel jurnal, Tugas akhir. Daftarnya satu sumber kebenaran di `roadmap.DOC_TYPES`
  (dropdown, label sampul ekspor, dan tata letak diambil darinya; menambah jenis = menambah entri di `ROADMAP` + `DOC_TYPES`). Struktur bab Laporan PKL
  dan Proposal adalah bawaan umum; sesuaikan dengan pedoman kampus lewat `extra_checklist`/`min_words` pada gaya selingkung. Kunci bab polos
  (`pendahuluan`) berlaku untuk semua jenis dokumen yang punya bab itu; kunci berkualifikasi (`laporan_pkl.pendahuluan`) hanya untuk satu jenis dan diutamakan.
- **Pemeriksa ejaan** (`app/eyd.py` + kamus di `app/kamus.py`): ~175 pasangan kata tidak baku (serapan, imbuhan, ejaan lain), kata depan
  `di/ke/dari` serangkai vs terpisah, partikel `pun`, huruf kapital nama diri, tanda baca ganda, spasi kurung/titik, pleonasme, dan ragam santai
  (sebagai SARAN, karena sah di kutipan wawancara). URL, surel, DOI, kode, token bergaya kode, dan baris berbahasa Inggris tidak diperiksa.
  Aturan menambah kamus ada di docstring `kamus.py`: hanya bentuk yang pasti tidak baku menurut KBBI/EYD V.
- **Mode Sidang** (Premium; tombol "Mode sidang"): AI berperan sebagai dosen penguji untuk **Sidang PKL**, **Seminar proposal (sempro)**, dan **Sidang skripsi**
  (gaya penguji: suportif / standar / kritis; 3-10 pertanyaan). Pertanyaan berpijak pada tulisanmu di jenis dokumen yang sesuai (Laporan PKL / Proposal / Skripsi);
  tiap jawaban dinilai (skor 1-5: materi, kejelasan, argumentasi) disertai petunjuk, lalu ada ringkasan akhir dan tombol "Buka bab" ke bab yang perlu diperkuat.
  Skor akhir = rata-rata skor tiap jawaban (dihitung kode, bukan karangan AI); AI hanya menulis narasi. Penguji bertanya dan menilai, TIDAK menuliskan jawaban.
  Satu sesi aktif per pengguna (dijaga indeks unik parsial di basis data), sesi yang ditinggalkan kedaluwarsa setelah 24 jam, kuota harian terpisah
  (`PREMIUM_SIDANG_QUOTA`, bawaan 40 langkah), kegagalan AI mengembalikan kuota dan jawaban. Jawaban dan skor disimpan per pengguna dan bisa dihapus dari riwayat.
  Tulisan dan jawaban mahasiswa dikirim ke penyedia LLM sebagai DATA (pembatas diberi sanitasi), sama seperti fitur bimbingan lain.
  Catatan: ini latihan, bukan prediksi nilai; kualitas pertanyaan baru terlihat dengan LLM sungguhan (mode `mock` memakai bank pertanyaan tetap).
- **Daftar pustaka** (tab Pustaka, wajib masuk): simpan pustaka pribadi (manual, dari DOI lewat Crossref, atau tombol "+ Pustaka" pada hasil Rujukan),
  tampil dalam **APA 7** atau **IEEE** (nama jurnal miring, APA diurutkan abjad). "Periksa sitasi" mencocokkan `(Nama, 2020)`, `Nama (2020)`, dan `[1]`
  di seluruh draf dengan daftar pustaka: sitasi tanpa pustaka dan pustaka yang belum dikutip. Pemformat tidak mengubah huruf besar/kecil judul dan tidak bisa
  menebak urutan nama orang Indonesia; mahasiswa tetap harus memeriksa hasilnya.
- **Ekspor Word** (tombol "Ekspor Word"): semua bab -> satu `.docx` dengan sampul, daftar isi (bidang Word: klik kanan -> Perbarui Bidang), judul bab/sub-bab
  (`BAB I ...`, `1.1 ...`, `1.1.1 ...` dikenali otomatis), dan daftar pustaka. Formatnya dari aturan `format` pada gaya selingkung kampus
  (font, ukuran, spasi, margin, kertas A4/F4/Letter, posisi nomor halaman). Bawaan (TNR 12, spasi 1,5, margin 4-4-3-3 cm) hanyalah pola umum:
  admin kampus wajib menyesuaikannya dengan pedoman resmi.
- **Kesiapan draf ("layak kirim ke dosen")** (tab Kesiapan): pemeriksaan deterministik gratis (bab kosong/terlalu pendek menurut `min_words` kampus atau
  `READY_MIN_WORDS`, isian templat belum diganti, kepadatan catatan ejaan, sitasi yang belum ada di daftar pustaka, checklist manual yang belum dicentang).
  Hasilnya saran untuk mahasiswa, bukan penilaian akademik. Dosen melihat status yang sama saat membuka draf.
- **Catatan dosen → mahasiswa & lembar bimbingan**: kanal resmi terpisah dari draf dan komentar AI (`/api/dosen/students/{id}/notes`, `/api/notes`), dengan
  lencana belum-dibaca dan frasa cepat (preset) untuk dosen. Hanya untuk mahasiswa yang masih memberi izin.
- **Riwayat versi & ringkasan perubahan**: snapshot draf otomatis (jeda `REVISION_MIN_MINUTES`, maksimal `REVISION_KEEP` terbaru per draf), bandingkan
  dengan isi sekarang, dan pulihkan versi lama (isi sekarang tetap tersimpan sehingga bisa dibatalkan). Dosen melihat "apa yang berubah sejak kamu membaca".
- **Ekspor lembar bimbingan (logbook)**: catatan dosen berjenis `logbook` diunduh mahasiswa sebagai DOCX lanskap (No, tanggal, dosen, bab, uraian, kolom paraf kosong).
- **Bank pertanyaan penguji per kampus**: dosen (kampusnya sendiri) dan admin menyusun pertanyaan per jenis sidang/jurusan. Mode Sidang memilih dari bank
  kampus mahasiswa (diparafrase agar sesuai tulisannya, tidak mengulang); bank kosong = perilaku lama. Jurusan mahasiswa dibaca dari gaya selingkung yang ia pilih.
  Dosen juga bisa menyimpan frasa umpan balik kustom (maks. 30) di samping preset bawaan.
- **Akun & hak data (UU PDP)**: menu *Akun & data* — unduh semua data pribadi (JSON), lihat kapan dosen membuka drafmu, ganti kata sandi (token perangkat lain
  otomatis tidak berlaku), dan hapus akun permanen (konfirmasi sandi). Penghapusan membuang semua tulisan dan data pribadi; hanya catatan pembayaran yang
  tersisa (untuk pembukuan) pada baris pengguna yang sudah dikosongkan. Akun dikunci sementara setelah gagal masuk berulang. Halaman `/legal.html` memuat
  Syarat Layanan & Kebijakan Privasi; centang persetujuan wajib di UI daftar, dan di server bila `REQUIRE_TERMS_CONSENT=true`.
- **Kontrol biaya LLM**: (1) batas panjang jawaban per jenis panggilan; (2) pemakaian token dicatat agregat per hari, jenis, dan kampus (tanpa isi tulisan; bila penyedia
  tidak melaporkan usage, dihitung dari perkiraan panjang teks); (3) komentar/analisis untuk teks yang sama persis dilayani dari cache per pemilik tanpa memanggil LLM dan
  **tanpa memotong kuota** (kunci mencakup gaya selingkung dan model, tidak dibagi antarpengguna, terhapus bersama akun); (4) pagar anggaran harian `LLM_DAILY_TOKEN_BUDGET`:
  bila tercapai fitur AI berhenti (HTTP 503, kuota tidak terpotong) sampai besok, sementara cek EYD, hasil cache, dan penutupan sesi sidang tetap berjalan; (5) tab **Biaya AI**
  di admin: total, per kampus, per jenis, per hari, cache hit rate, status anggaran, dan estimasi biaya dari `LLM_PRICE_*`.
- **Wizard, mode fokus, dan status progres**: pada kunjungan pertama wizard menanyakan jenis tugas (skripsi, TA, proposal, PKL, jurnal, atau latihan sidang) lalu
  menyesuaikan peta bab; tombol **?** membukanya lagi. Tombol **Fokus** (atau Esc untuk keluar) menyembunyikan peta dan panel; mode ini keluar sendiri saat kamu minta
  bimbingan agar hasilnya terlihat. Panel **Progres** menampilkan tahap Draft → Layak bimbingan → Ada catatan dosen → Siap sidang (Siap submit untuk jurnal),
  penanda status tiap bab, dan satu langkah berikutnya (`GET /api/progress`). Status ini penunjuk arah, bukan penilaian: "siap" = semua bab terisi, definisi yang sama
  dengan dasbor dosen.
- **Reset kata sandi lewat email**: "Lupa kata sandi?" di dialog Masuk → tautan sekali pakai (berlaku 30 menit, hanya hash-nya yang disimpan) ke `/reset.html`.
  Balasan selalu sama untuk email terdaftar maupun tidak, maksimal 3 permintaan per akun per jam, dan reset berhasil membuka kunci akun serta
  mencabut semua sesi lama. Email lewat Gmail API (OAuth2); di mode `mock` tautan dicatat di log server untuk pengembangan.
- **Batas etika AI**: teks mahasiswa dibungkus sebagai DATA (pembatas disanitasi), permintaan "tuliskan/susunkan/parafrasekan" pada teks pendek ditolak, dan
  komentar/analisis AI yang berisi kalimat pengganti utuh dibuang dan diganti pesan netral.
- **Dasbor dosen "perlu perhatian"**: bawaannya hanya mahasiswa yang tertahan, punya draf baru sejak terakhir dibaca, atau semua babnya sudah terisi (siap sidang).
- **Kampus & dosen**: admin mendaftarkan dosen; mahasiswa terhubung lewat kode + **persetujuan eksplisit**, dan bisa mencabutnya kapan saja.
- **Gaya selingkung**: aturan JSON per kampus/jurusan (`notes`, `citation_style`, `forbid_first_person`, `max_sentence_words`, `replacements`,
  `chapters.<bab>.{extra_checklist,min_words,max_words}`) memengaruhi cek ejaan, checklist, target kata, dan konteks AI.
- **Analitik**: admin (pengguna, aktivitas, pemakaian AI, pendapatan, bab tersulit, kesalahan paling sering) dan dosen (ringkasan kelas).
  Statistik isi dihitung dari sampel ≤1000 draf terbaru (ejaan: ≤150), hanya agregat, di-cache sampai ada draf berubah.
- **Pembayaran**: `PAYMENT_PROVIDER=mock|midtrans|xendit`. Premium aktif hanya setelah webhook terverifikasi (signature/token + nominal), idempoten.

## Konfigurasi penting (`.env`)
`DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `ENV` (`dev`|`prod`), `BASE_URL`, `ADMIN_EMAILS`, `LLM_PROVIDER` (`mock`|`openai_compat`) +
`LLM_BASE_URL/API_KEY/MODEL_FAST/MODEL_SMART`, `PAYMENT_PROVIDER` + kunci Midtrans/Xendit, `FREE_DAILY_QUOTA`, `PREMIUM_DAILY_QUOTA`,
`PREMIUM_ANALYSIS_QUOTA`, `STUCK_DAYS`, `LLM_DAILY_TOKEN_BUDGET`, `LLM_MAX_TOKENS_*`, `LLM_PRICE_*`, `LLM_CACHE_DAYS`, `EMAIL_PROVIDER`, `GMAIL_*`, `RESET_TOKEN_MINUTES`, `RESET_MAX_PER_HOUR`, `LOGIN_MAX_FAILURES`, `LOGIN_LOCK_MINUTES`, `REQUIRE_TERMS_CONSENT`, `TERMS_VERSION`, `ACCESS_LOG_DAYS`, `READY_MIN_WORDS`, `READY_MAX_ISSUES_PER_100W`, `REVISION_MIN_MINUTES`, `REVISION_KEEP`, `TIMEZONE`, `RATE_LIMIT_ENABLED`. Lihat `.env.example` dan `.env.prod.example`.
Webhook pembayaran: `POST /api/pay/webhook/midtrans` dan `/xendit` (daftarkan URL publik di dashboard).

## Deploy produksi (satu VPS)
```bash
cp .env.prod.example .env.prod      # isi semua nilai (ENV=prod, PAYMENT_PROVIDER bukan mock)
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```
Caddy mengurus HTTPS otomatis (arahkan DNS dulu). Service `migrate` menjalankan `alembic upgrade head` sekali sebelum aplikasi naik.
Dengan `ENV=prod`, aplikasi menolak start bila SECRET_KEY lemah, provider `mock`, SQLite, Redis kosong, atau BASE_URL bukan https; `/docs` dimatikan.
Cadangan & pemulihan: lihat bagian **Backup** di bawah.

## Observability
**Log terstruktur** (`app/obs.py`): satu baris JSON per kejadian di produksi (`LOG_FORMAT=json`; teks berwarna-ringan di pengembangan) dengan `ts`, `level`, `logger`, `msg`, `request_id`, dan field peristiwa.
Setiap respons membawa header `X-Request-ID` (juga pada 429 dan 500; ID dari klien dipakai bila bentuknya aman). Pada error 500 pengguna hanya melihat pesan umum + `request_id`; minta kode itu dari
pelapor lalu cari di log. Log akses uvicorn dimatikan (diganti log permintaan sendiri); peringatan Python ikut lewat logging.
| Peristiwa (`event`) | Level | Kapan | Layak dipantau |
|---|---|---|---|
| `request` | INFO/WARNING/ERROR | tiap permintaan: `method`, `path` (id dinormalkan), `status`, `ms` | ERROR = 5xx; WARNING = lebih lambat dari `SLOW_REQUEST_MS` |
| `unhandled_exception` | ERROR | galat tak terduga (traceback tersaring) | **selalu** |
| `llm_error` | WARNING | LLM gagal: `kind`, `exc`, `status` penyedia | `status=401` (kunci salah) / `429` (batas penyedia) |
| `redis_unavailable` | ERROR | Redis mati: **rate limiter berhenti membatasi** | **selalu** |
| `payment_amount_mismatch`, `payment_webhook_rejected` | ERROR/WARNING | webhook dengan nominal/tanda tangan salah | **selalu** |
| `email_failed` | ERROR | Gmail API gagal (hanya `domain`, bukan alamat) | reset sandi tidak terkirim |
| `account_locked`, `login_failed`, `login_blocked_locked` | WARNING | percobaan masuk | lonjakan = serangan |
| `llm_budget_exceeded`, `rate_limited` | WARNING | pagar biaya / batas laju tercapai (dibatasi frekuensinya) | |
| `user_registered`, `password_*`, `account_deleted`, `payment_paid` | INFO | siklus akun & pembayaran (tanpa data pribadi) | |

**Yang TIDAK pernah dicatat** (diuji dengan skenario panjang yang memeriksa semua baris log): isi tulisan, isi permintaan, header, query string, alamat IP, email, kata sandi, token/JWT, dan nilai parameter SQL.
Lapisannya: kode tidak memasukkan teks pengguna ke pesan exception (tes menjaga daftar `raise ...(f"...")`), `hide_parameters=True` pada engine SQLAlchemy (tanpa ini pesan galat DB memuat **nilai** kolom),
dan `redact()` yang membuang email, JWT, bearer, token reset, string acak panjang, serta baris `DETAIL:` PostgreSQL. **Redaksi berbasis pola adalah jaring pengaman terakhir, bukan jaminan**: teks bebas yang
kebetulan masuk ke pesan exception tidak bisa dikenali pola. Karena itu jangan pernah menulis `raise X(f"... {teks_pengguna}")`.
**Sentry (opsional)**: isi `SENTRY_DSN` (paket `sentry-sdk` sudah di `requirements.txt`). Event disaring ketat: tanpa isi permintaan, header, cookie, query, data pengguna, dan variabel lokal; URL dinormalkan;
tag `request_id` menghubungkan event ke baris log; `traces_sample_rate` 0 (tanpa pelacakan performa) kecuali kamu ubah. Teruji dengan SDK Sentry asli, termasuk uji kontrol yang membuktikan data memang akan bocor tanpa penyaringan ini.
Batasan: tidak ada metrik/dasbor (Prometheus dsb.) dan tidak ada konfigurasi pengiriman log; pembatasan frekuensi peristiwa berlaku per proses (2 worker = sampai 2 baris per interval).

## Backup & uji pemulihan
`scripts/dospem_backup.py` (pustaka standar, tanpa dependensi tambahan) menjalankan: dump (`pg_dump -Fc`) → **verifikasi** (`pg_restore --list` + ukuran + ada data tabel) → checksum SHA-256 →
unggah offsite opsional → pemangkasan retensi (7 backup terbaru + 1 per minggu untuk 8 minggu; ubah lewat `--keep-daily/--keep-weekly`). Jaminan yang diuji: backup rusak tidak pernah
tersisa (ditulis ke `.part` dulu), pemangkasan **hanya** berjalan setelah backup baru terverifikasi, backup terbaru tidak pernah terhapus, dan berkas lain di folder tidak disentuh.
```bash
# contoh crontab di VPS (jalankan dari folder project; mode Docker memakai layanan `db` di docker-compose.prod.yml)
0 2 * * *  cd /opt/dospem && python3 scripts/dospem_backup.py run --compose docker-compose.prod.yml --dir /var/backups/dospem \
             --upload-cmd "rclone copyto {file} offsite:dospem/{name}" >> /var/log/dospem-backup.log 2>&1
0 4 * * 0  cd /opt/dospem && python3 scripts/dospem_backup.py restore-check --compose docker-compose.prod.yml --dir /var/backups/dospem >> /var/log/dospem-backup.log 2>&1
```
`restore-check` memulihkan backup terbaru ke database sementara, memastikan versi migrasi dan semua tabel ada, menampilkan jumlah baris, lalu **selalu** membuang database sementaranya.
Kode keluar bukan 0 berarti ada masalah (1 dump, 2 verifikasi, 3 unggah, 4 pemulihan): arahkan ke pemantauan/email cron. Untuk koneksi langsung tanpa Docker: `--url postgresql://user:pass@host:5432/db`.
**Penting:** (1) backup memuat tulisan pengguna, jadi batasi akses folder (`chmod 700`) dan **enkripsi sebelum offsite** (mis. `rclone` crypt remote atau `age`); (2) data yang dihapus pengguna
tetap ada di backup lama sampai terpangkas (maks. ± 8 minggu pada pengaturan bawaan): ini sudah tertulis di kebijakan privasi, sesuaikan angkanya dengan retensimu; (3) **latih pemulihan
sungguhan** ke server lain minimal sekali sebelum rilis. Mode Docker belum dijalankan terhadap Docker nyata di lingkungan pengembangan ini (pembangun perintahnya diuji, jalur URL diuji penuh di PostgreSQL).

## CI
`.github/workflows/ci.yml` (divalidasi dengan `actionlint`) menjalankan pada tiap push/PR: tes di SQLite, **seluruh tes di PostgreSQL 16** (termasuk backup + pemulihan nyata), migrasi naik/turun penuh +
`alembic check`, build image Docker + smoke test, dan audit dependensi (informasi). Dependabot memeriksa pip/Docker/Actions tiap minggu. Menjalankan tes PostgreSQL secara lokal:
`docker compose up -d db` lalu `TEST_DATABASE_URL=postgresql+psycopg://dospem:dospem@localhost:5433/dospem pytest` (buat database baru tiap run karena fixture admin mendaftar sekali).

## Privasi & keamanan
Dosen hanya melihat mahasiswa yang menyetujui dan hanya-baca. Analitik tidak mengembalikan isi tulisan. Kata sandi di-hash scrypt, sesi JWT,
rate limit per IP (Redis), header keamanan + CSP. Mode `mock` pembayaran hanya untuk pengembangan.

## Checklist sebelum rilis publik
1. **Lengkapi `static/legal.html`**: semua bagian bertanda kuning `[ISI: …]` (penyelenggara, penyedia LLM/hosting/pembayaran, refund, retensi, yurisdiksi). Teks itu draf
   untuk membantu; **tinjau dengan penasihat hukum**. Server produksi mencatat peringatan selama placeholder masih ada.
2. Set `REQUIRE_TERMS_CONSENT=true` dan naikkan `TERMS_VERSION` setiap kali isi syarat berubah bermakna.
3. Isi `CONTACT_EMAIL` dengan kotak surat yang benar-benar dipantau (tercantum di halaman legal untuk permintaan data).
4. **Isi `LLM_DAILY_TOKEN_BUDGET`** (pagar biaya harian; server produksi memberi peringatan bila 0) dan harga model di `LLM_PRICE_*` agar tab Biaya AI menampilkan estimasi. Pantau tab itu beberapa hari pertama lalu sesuaikan.
5. **Isi `SENTRY_DSN`** (atau pastikan log JSON dipantau) dan buat peringatan untuk `unhandled_exception`, `redis_unavailable`, dan `payment_amount_mismatch`; sebutkan layanan pemantau & retensi log di `legal.html`.
6. Isi `EMAIL_PROVIDER=gmail` + kredensial `GMAIL_*` (produksi menolak mulai bila masih `mock`). Dapatkan refresh token sekali lewat `python scripts/get_gmail_token.py`, lalu coba alur "Lupa kata sandi?" sampai email benar-benar masuk inbox.
7. **Jadwalkan backup** (cron di atas) dan latih pemulihan ke server lain; jalankan `pytest` dengan `TEST_DATABASE_URL` PostgreSQL (sudah otomatis di CI), dan jalankan `pytest` dengan `TEST_DATABASE_URL` Postgres.

## Batasan yang diketahui
- Pagar anggaran bersifat **global** (semua pengguna), belum per kampus atau per pengguna; satu pengguna rakus bisa menghabiskan jatah hari itu bagi semua (kuota harian per pengguna tetap membatasinya). Estimasi biaya hanya sebaik harga yang kamu isi.
- Frontend HTML/JS murni (belum Next.js/TipTap); belum ada login Google kampus, email konfirmasi akun, atau 2FA. Email terkirim di latar belakang tanpa antrean/retry (kegagalan Gmail API hanya dicatat di log); bila volume membesar, pindahkan ke worker.
- Gaya selingkung baru mencakup aturan yang bisa diperiksa pada teks polos (belum margin, spasi baris, penomoran halaman → perlu ekspor dokumen).
- Ekspor logbook baru DOCX (belum PDF). Bank pertanyaan dikelola lewat dasbor dosen dan API admin (`/api/admin/questions`); panel admin visual belum ada. Notifikasi (email/WhatsApp) belum ada.
- Snapshot revisi menyimpan teks penuh (maks. `REVISION_KEEP` per draf); pantau ukuran DB bila pengguna banyak. Tahap "bab tersulit" butuh ≥3 mahasiswa pada bab yang sama.
- Panggilan sungguhan ke OpenAlex/Crossref, Midtrans/Xendit, LLM, dan build Docker belum diuji di lingkungan pengembangan ini.
