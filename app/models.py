from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):  # dipakai penuh saat auth (Clerk/Google) ditambahkan
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    name: Mapped[str | None] = mapped_column(String(120))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    university: Mapped[str | None] = mapped_column(String(160))
    major: Mapped[str | None] = mapped_column(String(160))
    plan: Mapped[str] = mapped_column(String(20), default="free")
    premium_until: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    failed_logins: Mapped[int] = mapped_column(default=0, server_default="0")  # kunci sementara setelah gagal berulang
    locked_until: Mapped[datetime | None]
    pw_changed_at: Mapped[datetime | None]  # token yang terbit sebelum ini tidak berlaku lagi
    terms_accepted_at: Mapped[datetime | None]
    terms_version: Mapped[str | None] = mapped_column(String(20))
    deleted_at: Mapped[datetime | None]  # akun dihapus: data pribadi dibuang, baris tersisa hanya untuk catatan pembayaran


class Draft(Base):
    """Satu draf per (pemilik, jenis tugas, bab). `owner` = device id (sementara) / user id."""
    __tablename__ = "drafts"
    __table_args__ = (UniqueConstraint("owner", "doc_type", "chapter_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    doc_type: Mapped[str] = mapped_column(String(20))
    chapter_key: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AIUsage(Base):
    """Kuota harian. Nanti dipindah ke Redis (INCR + EXPIRE) bila trafik naik."""
    __tablename__ = "ai_usage"
    __table_args__ = (UniqueConstraint("owner", "day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    day: Mapped[date] = mapped_column(Date, default=date.today)
    count: Mapped[int] = mapped_column(default=0)


class Example(Base):
    """Cache metadata dari OpenAlex/Crossref. `annotation` diisi kurasi tim (buatan sendiri)."""
    __tablename__ = "examples"
    __table_args__ = (UniqueConstraint("source", "external_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str] = mapped_column(String(200))
    doi: Mapped[str | None] = mapped_column(String(200), index=True)
    title: Mapped[str] = mapped_column(Text)
    authors: Mapped[str] = mapped_column(Text, default="[]")  # JSON
    year: Mapped[int | None]
    venue: Mapped[str | None] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(String(500))
    license: Mapped[str | None] = mapped_column(String(200))
    abstract: Mapped[str | None] = mapped_column(Text)
    annotation: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Bookmark(Base):
    __tablename__ = "bookmarks"
    __table_args__ = (UniqueConstraint("user_id", "example_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    example_id: Mapped[int] = mapped_column(ForeignKey("examples.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(String(40), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_key: Mapped[str] = mapped_column(String(30))
    amount: Mapped[int]
    provider: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|paid|failed|expired
    provider_ref: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    paid_at: Mapped[datetime | None]


class Institution(Base):
    __tablename__ = "institutions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("institution_id", "user_id", "role"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(12))  # dosen | mahasiswa


class Invite(Base):
    __tablename__ = "invites"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(12), unique=True)
    dosen_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id", ondelete="CASCADE"))
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Supervision(Base):
    """Izin eksplisit mahasiswa agar dosen melihat progres & draf. status: approved | revoked."""
    __tablename__ = "supervisions"
    __table_args__ = (UniqueConstraint("dosen_id", "mahasiswa_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    dosen_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    mahasiswa_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(12), default="approved")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    approved_at: Mapped[datetime | None]


class StyleTemplate(Base):
    """Gaya selingkung: aturan format kampus/jurusan (JSON, divalidasi oleh app/style.py). institution_id NULL = umum."""
    __tablename__ = "style_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id", ondelete="CASCADE"))
    major: Mapped[str | None] = mapped_column(String(160))
    rules: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StylePref(Base):
    __tablename__ = "style_prefs"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("style_templates.id", ondelete="CASCADE"))


class UsageDaily(Base):
    """Pemakaian AI harian (coach/analisis) untuk analitik; independen dari Redis."""
    __tablename__ = "usage_daily"
    __table_args__ = (UniqueConstraint("day", "kind"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(20))
    count: Mapped[int] = mapped_column(default=0)


class BibEntry(Base):
    """Daftar pustaka pribadi mahasiswa (nama tabel bukan `references` karena kata kunci SQL)."""
    __tablename__ = "bib_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(12), default="jurnal")  # jurnal | buku | web | lain
    authors: Mapped[str] = mapped_column(Text, default="[]")  # JSON: ["Nama Belakang, Nama Depan", ...]
    year: Mapped[int | None]
    title: Mapped[str] = mapped_column(Text)
    venue: Mapped[str | None] = mapped_column(String(300))
    volume: Mapped[str | None] = mapped_column(String(20))
    issue: Mapped[str | None] = mapped_column(String(20))
    pages: Mapped[str | None] = mapped_column(String(30))
    publisher: Mapped[str | None] = mapped_column(String(200))
    doi: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SidangSession(Base):
    """Satu sesi Mode Sidang. Paling banyak SATU sesi aktif per pengguna (indeks unik parsial)."""
    __tablename__ = "sidang_sessions"
    __table_args__ = (Index("uq_sidang_active", "user_id", unique=True, sqlite_where=text("status = 'aktif'"), postgresql_where=text("status = 'aktif'")),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(12))  # pkl | sempro | skripsi
    persona: Mapped[str] = mapped_column(String(12))  # suportif | standar | kritis
    doc_type: Mapped[str] = mapped_column(String(20))
    max_questions: Mapped[int]
    status: Mapped[str] = mapped_column(String(10), default="aktif")  # aktif | selesai
    summary: Mapped[str | None] = mapped_column(Text)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None]


class SidangTurn(Base):
    __tablename__ = "sidang_turns"
    __table_args__ = (UniqueConstraint("session_id", "idx"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sidang_sessions.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int]
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    feedback: Mapped[str | None] = mapped_column(Text)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SupervisorNote(Base):
    """Catatan resmi dosen -> mahasiswa (kanal terpisah dari draf & komentar AI). kind: catatan | logbook."""
    __tablename__ = "supervisor_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    supervision_id: Mapped[int] = mapped_column(ForeignKey("supervisions.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10), default="catatan")
    doc_type: Mapped[str | None] = mapped_column(String(20))
    chapter_key: Mapped[str | None] = mapped_column(String(40))
    session_date: Mapped[date | None] = mapped_column(Date)  # tanggal bimbingan (logbook)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    read_at: Mapped[datetime | None]


class DraftRevision(Base):
    """Snapshot isi draf (dibatasi `revision_keep` terbaru per draf) untuk riwayat versi & ringkasan perubahan."""
    __tablename__ = "draft_revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text)
    words: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DosenView(Base):
    """Versi draf yang terakhir dibaca dosen (dasar 'apa yang berubah sejak review terakhir')."""
    __tablename__ = "dosen_views"
    __table_args__ = (UniqueConstraint("dosen_id", "mahasiswa_id", "doc_type", "chapter_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    dosen_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    mahasiswa_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    doc_type: Mapped[str] = mapped_column(String(20))
    chapter_key: Mapped[str] = mapped_column(String(40))
    revision_id: Mapped[int | None] = mapped_column(ForeignKey("draft_revisions.id", ondelete="SET NULL"))
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FeedbackPreset(Base):
    """Frasa umpan balik buatan dosen sendiri (melengkapi preset bawaan)."""
    __tablename__ = "feedback_presets"
    id: Mapped[int] = mapped_column(primary_key=True)
    dosen_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ExamQuestion(Base):
    """Bank pertanyaan penguji hasil kurasi dosen/admin per kampus. mode/major NULL = berlaku untuk semua."""
    __tablename__ = "exam_questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str | None] = mapped_column(String(12))  # pkl | sempro | skripsi
    major: Mapped[str | None] = mapped_column(String(160))
    question: Mapped[str] = mapped_column(String(400))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DraftAccess(Base):
    """Jejak kapan dosen membuka draf mahasiswa (transparansi bagi mahasiswa). Dipangkas setelah `access_log_days`."""
    __tablename__ = "draft_accesses"
    id: Mapped[int] = mapped_column(primary_key=True)
    dosen_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    mahasiswa_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    doc_type: Mapped[str] = mapped_column(String(20))
    chapter_key: Mapped[str] = mapped_column(String(40))
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PasswordReset(Base):
    """Token reset kata sandi sekali pakai. Yang disimpan hanya hash SHA-256; token asli hanya ada di email."""
    __tablename__ = "password_resets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LLMCache(Base):
    """Hasil komentar/analisis AI untuk teks yang sama persis, per pemilik (tidak dibagi antarpengguna). Dihapus bersama akun."""
    __tablename__ = "llm_cache"
    __table_args__ = (UniqueConstraint("owner", "key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    key: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(12))
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class LLMUsage(Base):
    """Agregat pemakaian LLM per hari, jenis panggilan, dan kampus (0 = tanpa kampus). Tanpa isi tulisan."""
    __tablename__ = "llm_usage"
    __table_args__ = (UniqueConstraint("day", "kind", "institution_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(12))
    institution_id: Mapped[int] = mapped_column(default=0)
    calls: Mapped[int] = mapped_column(default=0)
    cache_hits: Mapped[int] = mapped_column(default=0)
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    completion_tokens: Mapped[int] = mapped_column(default=0)
