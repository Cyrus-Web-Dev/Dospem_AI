# Roadmap Pengembangan Dospem

Dokumen ini merangkum arah pengembangan Dospem agar semakin membantu dosen pembimbing (manusia) tanpa menggantikan perannya, sekaligus meningkatkan pengalaman mahasiswa.

**Prinsip utama:** AI memberi komentar, pertanyaan, dan checklist — **bukan menulis isi, bukan menilai lulus/tidak formal, bukan mewakili dosen**.

**Patokan status (Tahap 12 — observability yang aman untuk data pribadi):**
- **Selesai** — sudah ada di kode & bisa dipakai
- **Sebagian** — ada fondasi, belum lengkap sesuai niat roadmap
- **Belum** — belum diimplementasi

---

## Status Saat Ini (Tahap 12)

| Fitur | Status tahap 12 |
|-------|----------------|
| Roadmap bab skripsi / TA | Selesai |
| Roadmap jurnal | Selesai |
| Roadmap **Laporan PKL** (`laporan_pkl`) | Selesai |
| Roadmap **Proposal / Sempro** (`proposal`) | Selesai |
| Cek EYD V (aturan, tanpa kuota) | Selesai |
| Komentar dospem via LLM (kuota harian) | Selesai |
| Analisis logika bab (Premium) | Selesai |
| Contoh rujukan (OpenAlex, Crossref, DOAJ, OAI, dll.) | Selesai |
| Daftar pustaka + cek sitasi ↔ pustaka | Selesai |
| Export DOCX (sampul, daftar isi, pustaka) | Selesai |
| Kampus, dosen, kode undangan + consent | Selesai |
| Gaya selingkung per kampus/jurusan | Selesai |
| Analitik admin & dosen (dasar) | Selesai |
| Pembayaran premium (Midtrans/Xendit) | Selesai |
| **Mode Sidang** PKL / Sempro / Skripsi + persona | Selesai |
| Dark mode (sistem + preferensi) | Selesai |
| Frontend HTML/JS murni | Selesai (terbatas untuk scaling) |
| Checklist “layak kirim ke dosen” | Selesai |
| Catatan dosen → mahasiswa + lembar bimbingan (ekspor DOCX) | Selesai |
| Ringkasan perubahan antar revisi + riwayat versi & pulihkan | Selesai |
| Bank pertanyaan penguji per kampus/jurusan | Selesai |
| Preset feedback dosen (bawaan + kustom per dosen) | Selesai |
| Dashboard dosen “perlu perhatian” | Selesai (notifikasi belum) |
| Wizard onboarding jenis tugas | Selesai |
| Mode fokus menulis | Selesai |
| Status progres manusiawi (Draft → … → Siap sidang) | Selesai |
| Flag gaya generik / AI-like | Belum |
| Migrasi frontend modern (React/Vite/dll.) | Belum |

**Kesimpulan tahap 12:** Prioritas 1–7 dan paket pra-rilis (hak data UU PDP, kunci akun, reset sandi lewat email, syarat & privasi, batas etika AI) selesai dan teruji (208 tes: 201 jalan di SQLite dan seluruhnya lulus di PostgreSQL 16, + uji UI di DOM). Sebelum rilis publik masih wajib: melengkapi dan meninjau secara hukum `static/legal.html`, `REQUIRE_TERMS_CONSENT=true`, mengisi kredensial Gmail API dan mencoba email sungguhan, serta uji di PostgreSQL. Kontrol biaya LLM (batas jawaban, pencatatan token, cache, pagar harian, dasbor admin) juga selesai; set `LLM_DAILY_TOKEN_BUDGET` sebelum rilis. CI dan backup terjadwal juga selesai (jadwalkan cron-nya dan latih pemulihan ke server lain sebelum rilis). Observability juga selesai (pasang `SENTRY_DSN` dan peringatan sebelum rilis). Fokus berikutnya: 2FA admin/dosen, lalu prioritas 8–9 (flag gaya generik, migrasi frontend bertahap) dan poles spacing.

---

## Arah Fitur & Checklist Hidup

### Prioritas tinggi

| Item | Status tahap 6 | Catatan / saran |
|------|----------------|-----------------|
| Laporan PKL + Proposal/Sempro (roadmap + checklist) | Selesai | Pertahankan; sesuaikan checklist per kampus lewat gaya selingkung bila perlu |
| Mode Sidang (PKL, Sempro, Skripsi) + persona | Selesai | Pertahankan aturan: AI tidak menuliskan jawaban mahasiswa |
| Checklist **“layak kirim ke dosen”** | Selesai | `POST /api/readiness` + tab Kesiapan. Gabungkan EYD + checklist bab + panjang min + sitasi kasar → flag + daftar kekurangan. Cegah draf mentah masuk inbox dosen |
| **Catatan dosen → mahasiswa** | Selesai | `supervisor_notes` + `/api/notes`. Tabel/API terpisah dari draf; dosen tetap pemegang komunikasi resmi |
| **Ringkasan perubahan antar revisi** | Selesai | `draft_revisions` + `dosen_views`. Snapshot/diff per bab; tampilkan “apa yang berubah sejak review terakhir” |
| **Bank pertanyaan penguji** per kampus/jurusan | Selesai | Kurasi admin/dosen; mode sidang memilih & memparafrase, tidak mengarang tanpa sumber |
| **Preset feedback dosen** | Selesai | Bawaan + kustom per dosen (maks. 30). Frasa sering dipakai (“perjelas gap”, “metode belum dijustifikasi”) tempel cepat |

### Prioritas sedang

| Item | Status tahap 6 | Catatan / saran |
|------|----------------|-----------------|
| Dashboard dosen **“perlu perhatian”** | Selesai | Filter bawaan = stuck / draf baru / siap sidang. Semula: ada progres & tertahan; ubah default ke stuck lama / draf baru / siap sidang — bukan daftar penuh |
| Poles analitik mahasiswa tertahan | Sebagian | Threshold `STUCK_DAYS` sudah ada; perkuat notifikasi non-spam ke dosen |
| Mode “tanya dulu, baru tulis” (Socratic) | Belum | Alur terpisah: AI hanya bertanya sampai kerangka jelas |
| Deteksi sitasi ↔ daftar pustaka | Selesai | Sudah ada; poles UX laporan missing/uncited |
| Flag gaya generik / AI-like (ringan) | Belum | Sinyal untuk dicek manual, bukan vonis plagiarism |
| Status progres manusiawi | Selesai | `GET /api/progress`; “siap” memakai definisi yang sama dengan dasbor dosen |
| Email notifikasi (opsional) | Belum | Catatan baru / stuck — jangan spam harian |

### UI/UX & arsitektur frontend

| Item | Status tahap 6 | Catatan / saran |
|------|----------------|-----------------|
| Dark mode | Selesai | Pertahankan |
| Spacing & hierarki lebih lega | Sebagian | Sudah ada design tokens; kurangi kesan rapat di layar kecil |
| Wizard pilih jenis tugas di awal | Selesai | Muncul sekali pada kunjungan pertama; tombol ? membukanya lagi |
| Mode fokus (sembunyikan sidebar) | Selesai | Tombol Fokus / Esc; keluar otomatis saat minta bimbingan |
| Layout tiga kolom responsif | Sebagian | Roadmap \| Editor \| Panel; di mobile pakai tab |
| Progress visual manusiawi | Selesai | Daftar tahap + penanda status per bab + langkah berikut |
| Dasbor dosen lebih tenang & fokus | Sebagian | Sejalan “perlu perhatian” |
| **Migrasi SPA modern** | Belum | Lihat bagian stack frontend di bawah |
| Editor kaya (TipTap) | Belum | Heading, highlight komentar inline, bukan hanya textarea |
| Mobile-friendly cek feedback | Sebagian | Uji ulang setelah layout lega |

### Lainnya

| Item | Status tahap 6 | Catatan / saran |
|------|----------------|-----------------|
| Login Google / SSO kampus | Belum | Berguna untuk onboarding institusi |
| Email konfirmasi akun | Belum | — |
| Halaman syarat & privasi | Selesai (draf; placeholder `[ISI:]` + tinjauan hukum wajib) | `static/legal.html`, persetujuan tercatat |
| Gaya selingkung fisik (margin, spasi baris, nomor halaman) | Sebagian | Teks polos sudah; format halaman lewat export DOCX |
| Export PDF laporan progres | Belum | Opsional setelah DOCX stabil |
| Queue worker untuk job berat | Belum | Jika analisis batch / panen OAI membesar |

### Yang tidak dilakukan (batas etika — tetap)

| Hindari | Alasan |
|---------|--------|
| AI menulis paragraf / bab | Menggantikan kerja mahasiswa & dospem |
| AI memberi keputusan lulus/tidak formal | Peran dosen & penguji |
| Auto-kirim draf ke dosen tanpa consent | Privasi & etika |
| Meniru gaya tulisan dosen tertentu | Menyesatkan |
| Janji “lulus sidang dengan Dospem” | Overpromise |

Tagline yang jujur:  
**“Persiapkan draf dan jawabanmu — dosen tetap yang membimbing dan menguji.”**

---

## Prioritas Pengembangan (urutan kerja disarankan)

| Urutan | Item | Status tahap 6 | Alasan |
|--------|------|----------------|--------|
| 1 | Checklist layak kirim ke dosen | Selesai | Langsung mengurangi beban inbox dospem |
| 2 | Catatan dosen → mahasiswa | Selesai | Menutup gap komunikasi resmi |
| 3 | Ringkasan perubahan revisi | Selesai | Hemat waktu baca ulang |
| 4 | Dasbor dosen “perlu perhatian” | Selesai | Fokus energi dosen |
| 5 | Bank pertanyaan kampus + preset feedback | Selesai | Kualitas sidang + efisiensi dosen |
| 6 | Wizard jenis tugas + mode fokus + spacing | Selesai (spacing: sebagian) | Mengatasi UI “standar & rapat” |
| 7 | Status progres manusiawi | Selesai | Kejelasan alur bagi mahasiswa |
| 8 | Flag AI-like ringan | Belum | Integritas (sinyal, bukan vonis) |
| 9 | Migrasi frontend modern (bertahap) | Belum | `index.html` sudah sangat besar; scaling fitur |
| 10 | SSO / syarat-privasi / email | Belum | Kematangan produk publik |

---

## Tambahan hasil peninjauan (belum dikerjakan kecuali ditandai)

**Pra-rilis publik (sebaiknya sebelum scale, bukan di urutan terakhir):**

| Item | Status | Catatan |
|------|--------|---------|
| Hak data pengguna (UU PDP): ekspor & hapus akun beserta draf, kebijakan retensi | Selesai | `/api/account/export`, `/api/account/delete` (anonimisasi, pembayaran dipertahankan) |
| Audit log akses dosen ke draf | Selesai | `draft_accesses`, terlihat oleh mahasiswa di Akun & data |
| Kunci akun setelah gagal login berulang + ganti sandi (token lama dicabut) | Selesai | |
| Reset password lewat email | Selesai | `/api/auth/forgot` + `/reset.html`; Gmail API (OAuth2), tanpa antrean/retry |
| 2FA admin/dosen | Belum | |
| Tes otomatis batas etika AI (draf mahasiswa = data, bukan instruksi; AI tidak menulis paragraf) | Selesai | Sidang, komentar, dan analisis; filter keluaran terhadap kalimat pengganti |
| Kontrol biaya LLM: cache hasil untuk teks tak berubah, batas token, dasbor biaya per kampus | Selesai | `app/meter.py`, tab Biaya AI. Anggaran masih global (belum per kampus/pengguna) |
| Pembayaran: rekonsiliasi, refund/kedaluwarsa, invoice | Belum | Webhook sudah idempoten |
| CI: tes SQLite + PostgreSQL, migrasi naik/turun, build Docker, audit dependensi | Selesai | `.github/workflows/ci.yml` (divalidasi actionlint; belum dijalankan di GitHub) |
| Backup PostgreSQL terjadwal + verifikasi + uji pemulihan + retensi | Selesai | `scripts/dospem_backup.py`; jalur URL diuji di PostgreSQL, mode Docker belum dijalankan di Docker nyata |
| Observability: log terstruktur (JSON), ID permintaan, peristiwa keamanan, Sentry opsional dengan penyaringan | Selesai | `app/obs.py`; tanpa metrik/dasbor |

**Fitur tambahan yang relevan untuk kampus Indonesia:**

| Item | Status | Catatan |
|------|--------|---------|
| Logbook/lembar bimbingan: ekspor DOCX/PDF | Selesai (DOCX) | `POST /api/export/logbook`; PDF belum |
| Matriks keselarasan rumusan masalah ↔ tujuan ↔ metode ↔ kesimpulan | Belum | AI hanya menandai ketidakselarasan lewat pertanyaan |
| Target tanggal per bab + pengingat (dasar “stuck” yang lebih adil) | Belum | |
| Notifikasi WhatsApp (opt-in, dibatasi frekuensi) | Belum | |
| Multi-dosen (pembimbing 1/2, penguji) + alur ganti dosen | Belum | Hak akses & consent per orang |
| Impor referensi BibTeX/RIS/Zotero | Belum | |
| Rubrik sidang per kampus | Belum | Untuk persiapan, bukan nilai resmi |
| Autosave dengan penanganan konflik dua tab/perangkat | Belum | Saat ini last-write-wins |
| Komentar dosen inline per paragraf | Belum | Saat ini catatan per bab |
| Pencatatan penggunaan AI yang bisa diunduh mahasiswa | Belum | Bukti transparansi |

---

## Catatan Teknis Backend

- `doc_type` & `ROADMAP` sudah mencakup: `skripsi`, `ta`, `jurnal`, `laporan_pkl`, `proposal`.
- Mode sidang: `SIDANG_MODES` + `SidangSession` / `SidangTurn`; persona suportif/standar/kritis; kuota premium.
- Checklist kesiapan (**selesai**): `app/readiness.py`, `POST /api/readiness` → `{ ready, gaps[{kind,severity,message}], manual, stats }`. `blocker` = kosong/pendek/placeholder; `warn` = ejaan, sitasi, checklist manual. Tanpa AI, tanpa kuota.
- Catatan dosen (**selesai**): `app/notes.py`, tabel `supervisor_notes` (supervision_id, kind catatan|logbook, doc_type, chapter_key, session_date, body, read_at). Dosen hanya untuk supervisi `approved`; mahasiswa tetap bisa membaca catatan miliknya setelah izin dicabut.
- Revisi (**selesai**): `app/revisions.py`, tabel `draft_revisions` (snapshot teks penuh, jeda `REVISION_MIN_MINUTES`, simpan `REVISION_KEEP` terbaru) dan `dosen_views` (versi yang terakhir dibaca tiap dosen). Diff per paragraf dengan `difflib`. Membaca draf oleh dosen sengaja menulis `dosen_views` (efek samping GET).
- Bank pertanyaan (**selesai**): `app/bank.py`, tabel `exam_questions` (institution_id, mode, major, question). `pool_for()` memilih bank kampus mahasiswa (via Membership), jenis sidang, dan jurusan (dari gaya selingkung yang dipilih; `User.major` belum pernah diisi). Prompt sidang menerima blok `BANK` sebagai DATA (disanitasi) dengan aturan “pilih dari bank, boleh diparafrase”. Preset kustom: tabel `feedback_presets`.
- Gaya selingkung tetap sumber aturan checklist & konteks LLM per kampus.

---

## Frontend, Framework & Library

### Kondisi sekarang

- Frontend **HTML + JavaScript murni** (`static/index.html`, `dosen.html`, `admin.html` + `base.css` + `common.js`).
- Sudah ada dark mode, mode sidang (dialog), tab pustaka, export DOCX.
- Keterbatasan: `index.html` monolitik (~47KB+), sulit dites/komponenisasi, editor masih textarea, layout mudah terasa rapat saat fitur bertambah.

### Rekomendasi stack (hasil memuaskan & maksimal jangka menengah)

**Backend tidak diganti** (FastAPI + SQLAlchemy + Alembic + PostgreSQL + Redis).

| Lapisan | Pilihan | Keterangan |
|---------|---------|------------|
| Framework UI | **React 18 + TypeScript** | Cocok dashboard, editor, mode sidang |
| Build | **Vite** | DX cepat |
| Routing | **React Router** | Mahasiswa / dosen / admin / sidang |
| Styling | **Tailwind CSS** + **shadcn/ui** | Spacing lega, konsisten, dark mode |
| Editor | **TipTap** (ProseMirror) | Heading, mark komentar, lebih nyaman dari textarea |
| Data fetching | **TanStack Query** | Cache draf, roadmap, kuota, sesi sidang |
| Form | **React Hook Form** + **Zod** | Wizard, catatan dosen, pustaka |
| Tabel | **TanStack Table** | Daftar mahasiswa, bank pertanyaan, progres |
| Diff revisi | **diff** / **diff-match-patch** + UI sederhana | Ringkasan perubahan |
| Toast | **sonner** | Simpan, kuota, catatan terkirim |
| Icon | **lucide-react** | Ringan |
| Date | **date-fns** | Stuck X hari, jadwal |
| Chart analitik | **Recharts** (opsional) | Bab tersulit, aktivitas |

**Alternatif lebih ringan (jika migrasi penuh ditunda):** Vue 3 + Vite + TS, atau HTML + Alpine.js + Tailwind hanya untuk poles spacing dulu.

### Library backend tambahan (opsional)

| Kebutuhan | Saran |
|-----------|--------|
| Diff server-side | `difflib` (stdlib) |
| PDF | `reportlab` atau generate di frontend |
| Email | Gmail API (OAuth2) |
| Job panjang | Redis + worker sederhana |

### Yang tidak wajib

- Jangan pindah ke Next.js hanya demi SSR (app di belakang login).
- Jangan Redux global jika TanStack Query + context cukup.
- Pertahankan abstraksi LLM (`mock` / `openai_compat`) dan alur pembayaran yang sudah ada.

---

## Arah UI/UX (agar tidak “standar & rapat”)

1. **Spacing & hierarki** — padding longgar; bedakan jelas judul bab, body, komentar AI, catatan dosen.
2. **Wizard onboarding** — pilih jenis tugas sekali di awal; roadmap & mode sidang menyesuaikan.
3. **Mode fokus** — sembunyikan roadmap saat menulis.
4. **Tiga zona (desktop)** — Roadmap | Editor | Panel (checklist / coach / sidang); mobile = tab.
5. **Progress manusiawi** — status, bukan hanya persen bab.
6. **Dasbor dosen tenang** — default “perlu perhatian”.
7. **Label tegas** — komentar AI vs catatan dosen vs hasil sidang (warna/ikon berbeda).
8. **Kontras & a11y** — pertahankan `:focus-visible` dan preferensi tema yang sudah ada.

---

## Keamanan & Privasi (pertahankan)

- Consent eksplisit sebelum dosen melihat draf — jangan dilonggarkan.
- Dosen hanya-baca terhadap draf; catatan dosen = kanal terpisah.
- Analitik agregat, tanpa menampilkan isi tulisan di admin.
- Rate limit, hash password (scrypt), JWT, header keamanan + CSP.
- Mode sidang: skor latihan, **bukan** nilai resmi sidang kampus.
- Sebelum scale publik: syarat & privasi, HTTPS wajib (sudah dipaksa di `ENV=prod`).

---

## Rekomendasi Langkah Awal (setelah Tahap 5)

1. Implementasi **checklist layak kirim** (API + indikator di UI mahasiswa + filter di sisi dosen).
2. Model + API **catatan dosen**; tampilkan di panel mahasiswa.
3. **Diff/revisi** sederhana per bab.
4. Rapikan **dasbor dosen** (perlu perhatian).
5. **Wizard + mode fokus** di frontend yang ada, atau mulai skeleton React+Vite untuk halaman mahasiswa.
6. Bank pertanyaan & preset feedback setelah alur bimbingan stabil.

---

## Ringkasan stack target

| Area | Stack |
|------|--------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, Redis |
| AI | Provider kompatibel OpenAI (abstraksi tetap), kuota harian + sidang premium |
| Frontend (target) | React 18, TypeScript, Vite, React Router |
| UI | Tailwind CSS, shadcn/ui, lucide-react |
| Editor | TipTap |
| Data & form | TanStack Query, React Hook Form, Zod |
| Tabel & chart | TanStack Table, Recharts (opsional) |
| Pembayaran | Midtrans / Xendit |
| Deploy | Docker Compose + Caddy |

---

## Cara memakai dokumen ini

- Kolom **Status tahap 6** diubah menjadi **Selesai** saat fitur merge dan lolos tes.
- Setelah rilis berikutnya, ganti label menjadi “Status tahap 6”, dst., atau tambah kolom baru tanpa menghapus sejarah.
- Prioritas boleh digeser, tetapi batas etika (AI tidak menulis isi / tidak menilai formal) tidak digeser.

---

*Diperbarui setelah peninjauan zip tahap 5 (mode sidang). Selaras dengan tujuan: membantu dospem manusia yang punya waktu terbatas, tanpa mengambil alih peran akademik formal.*
