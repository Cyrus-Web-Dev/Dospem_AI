from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./dospem.db"
    llm_provider: str = "mock"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model_fast: str = ""
    llm_model_smart: str = ""
    free_daily_quota: int = 5
    max_chars_per_request: int = 3000
    premium_daily_quota: int = 50
    secret_key: str = "dev-secret-ganti-di-produksi"
    jwt_days: int = 7
    contact_email: str = "dev@example.com"
    admin_emails: str = ""
    base_url: str = "http://127.0.0.1:8000"
    payment_provider: str = "mock"
    midtrans_server_key: str = ""
    midtrans_production: bool = False
    xendit_secret_key: str = ""
    xendit_callback_token: str = ""
    env: str = "dev"  # dev | prod
    redis_url: str = ""
    timezone: str = "Asia/Jakarta"
    premium_analysis_quota: int = 10
    premium_sidang_quota: int = 40  # langkah sidang per hari (mulai + tiap jawaban): ~6 sesi x 6 pertanyaan
    sidang_default_questions: int = 6
    sidang_answer_chars: int = 3000
    stuck_days: int = 14
    login_max_failures: int = 5  # gagal masuk berturut-turut sebelum akun dikunci sementara
    login_lock_minutes: int = 15
    require_terms_consent: bool = False  # produksi publik: wajibkan centang Syarat & Privasi saat daftar
    terms_version: str = "2026-11"
    access_log_days: int = 365
    email_provider: str = "mock"  # mock (dev: dicatat di log/outbox) | gmail
    # Gmail API (OAuth2). Dapatkan refresh token sekali lewat scripts/get_gmail_token.py
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""
    gmail_sender: str = ""  # contoh: Dospem <akun-anda@gmail.com> — harus sama dengan akun yang diotorisasi
    reset_token_minutes: int = 30
    llm_token_param: str = "max_tokens"  # beberapa model baru memakai max_completion_tokens
    llm_max_tokens_coach: int = 900  # batas panjang JAWABAN per jenis panggilan (mencegah respons liar yang mahal)
    llm_max_tokens_analyze: int = 1600
    llm_max_tokens_sidang: int = 800
    llm_max_tokens_summary: int = 1400
    llm_daily_token_budget: int = 0  # total token (masuk+keluar) per hari untuk semua pengguna; 0 = tanpa batas. Tercapai -> fitur AI berhenti sampai besok
    llm_price_in_per_mtok: float = 0.0  # harga per 1 juta token, hanya untuk estimasi biaya di dasbor admin
    llm_price_out_per_mtok: float = 0.0
    llm_cost_currency: str = "USD"
    llm_cache_days: int = 7  # hasil komentar/analisis yang sama persis tidak memanggil LLM lagi selama ini
    llm_cache_max_per_owner: int = 100
    upload_max_mb: int = 5  # ukuran maks berkas unggahan (.docx/.pdf/.txt/.md) per bab
    upload_max_pages: int = 150  # halaman maks PDF yang dibaca
    asset_max_mb: int = 4  # ukuran maks satu gambar hasil unggahan
    asset_max_per_chapter: int = 60  # jumlah gambar maks per bab
    asset_user_quota_mb: int = 80  # total gambar maks per pemilik (semua bab)
    review_section_chars: int = 2800  # panjang target satu bagian yang dibaca AI saat meninjau seluruh bab
    free_review_quota: int = 4  # bagian bab yang boleh dibaca AI per hari (gratis); cache tidak memotong
    premium_review_quota: int = 80
    llm_max_tokens_review: int = 1100
    sidang_bimbingan_chars: int = 14000  # bahan bab yang dikirim ke AI pada sesi "Bimbingan per bab"
    log_level: str = "INFO"
    log_format: str = ""  # json | text; kosong = json di produksi, text di pengembangan
    slow_request_ms: int = 2000  # permintaan lebih lambat dari ini dicatat sebagai WARNING
    sentry_dsn: str = ""  # kosong = Sentry mati
    sentry_traces_sample_rate: float = 0.0
    app_release: str = ""  # mis. git sha, untuk melacak versi yang bermasalah
    reset_max_per_hour: int = 3  # permintaan reset per akun per jam (mencegah spam email)
    ready_min_words: int = 150  # ambang bawaan "layak kirim" bila gaya selingkung tidak menetapkan min_words
    ready_max_issues_per_100w: float = 8.0
    revision_min_minutes: int = 5  # jeda minimal antar snapshot revisi (0 = setiap perubahan)
    revision_keep: int = 15  # jumlah snapshot terbaru per draf yang disimpan
    rate_limit_enabled: bool = True
    # Sumber tambahan (opsional). Semantic Scholar & CORE nonaktif sampai kamu memastikan ketentuan layanan
    # mereka untuk produk berbayar (lisensi komersial) dan mengisi kuncinya.
    semantic_scholar_enabled: bool = False
    semantic_scholar_api_key: str = ""
    core_enabled: bool = False
    core_api_key: str = ""
    sinta_base: str = "https://sinta.kemdiktisaintek.go.id"
    garuda_base: str = "https://garuda.kemdiktisaintek.go.id"

    def assert_production_ready(self) -> None:
        if self.env != "prod":
            return
        p = []
        if len(self.secret_key) < 32 or self.secret_key.startswith("dev-secret"):
            p.append("SECRET_KEY lemah/default")
        if self.payment_provider not in ("midtrans", "xendit"):
            p.append("PAYMENT_PROVIDER harus midtrans/xendit")
        if self.payment_provider == "midtrans" and not self.midtrans_server_key:
            p.append("MIDTRANS_SERVER_KEY kosong")
        if self.payment_provider == "xendit" and not (self.xendit_secret_key and self.xendit_callback_token):
            p.append("XENDIT_SECRET_KEY/XENDIT_CALLBACK_TOKEN kosong")
        if self.llm_provider != "openai_compat":
            p.append("LLM_PROVIDER harus openai_compat")
        elif not (self.llm_api_key and self.llm_model_fast and self.llm_model_smart):
            p.append("LLM_API_KEY/LLM_MODEL_FAST/LLM_MODEL_SMART kosong")
        if self.email_provider != "gmail":
            p.append("EMAIL_PROVIDER harus gmail (reset kata sandi butuh email nyata)")
        elif not (self.gmail_client_id and self.gmail_client_secret
                  and self.gmail_refresh_token and self.gmail_sender):
            p.append("GMAIL_CLIENT_ID/GMAIL_CLIENT_SECRET/GMAIL_REFRESH_TOKEN/GMAIL_SENDER kosong")
        if self.database_url.startswith("sqlite"):
            p.append("DATABASE_URL masih SQLite")
        if not self.redis_url:
            p.append("REDIS_URL kosong")
        if not self.base_url.startswith("https://"):
            p.append("BASE_URL harus https")
        if p:
            raise RuntimeError("Konfigurasi produksi tidak aman: " + "; ".join(p))


settings = Settings()
