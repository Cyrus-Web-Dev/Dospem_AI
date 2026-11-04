"""Reset kata sandi lewat email: tidak membocorkan email terdaftar, token sekali pakai & berumur pendek, dan provider Gmail API."""
import hashlib
import re
import time
from datetime import datetime, timedelta

import jwt
import pytest
from sqlalchemy import select

from app import mailer
from app.config import settings
from app.db import SessionLocal
from app.models import PasswordReset, User
from tests.conftest import bearer
from tests.test_app import _uid

OLD, NEW = "rahasia123", "sandi-baru-987"


@pytest.fixture(autouse=True)
def _outbox():
    mailer.OUTBOX.clear()


def forgot(client, email):
    return client.post("/api/auth/forgot", json={"email": email})


def last_token():
    return re.search(r"#t=([\w-]+)", mailer.OUTBOX[-1]["body"]).group(1)


def reset(client, token, pw=NEW):
    return client.post("/api/auth/reset", json={"token": token, "new_password": pw})


def login(client, email, pw):
    return client.post("/api/auth/login", json={"email": email, "password": pw}).status_code


def test_forgot_is_uniform_and_token_is_hashed(client, reg):
    h, e = reg()
    a, b = forgot(client, "tidak-terdaftar@test.id"), forgot(client, e)
    assert a.status_code == b.status_code == 200 and a.json() == b.json()  # tak bisa dipakai menebak email terdaftar
    assert len(mailer.OUTBOX) == 1 and mailer.OUTBOX[0]["to"] == e
    raw = last_token()
    assert mailer.OUTBOX[0]["body"].count(f"{settings.base_url.rstrip('/')}/reset.html#t={raw}") == 1
    with SessionLocal() as db:
        rows = db.scalars(select(PasswordReset).where(PasswordReset.user_id == _uid(h))).all()
    assert len(rows) == 1 and rows[0].token_hash == hashlib.sha256(raw.encode()).hexdigest() and raw not in rows[0].token_hash  # hanya hash di DB
    assert 0 < (rows[0].expires_at - datetime.utcnow()).total_seconds() <= settings.reset_token_minutes * 60
    assert client.post("/api/auth/forgot", json={"email": "bukan-email"}).status_code == 422


def test_reset_flow_single_use_and_revokes_sessions(client, reg):
    h, e = reg()
    uid, now = _uid(h), int(time.time())
    old_jwt = bearer(jwt.encode({"sub": str(uid), "iat": now - 100, "exp": now + 3600}, settings.secret_key, algorithm="HS256"))
    forgot(client, e)
    t = last_token()
    assert reset(client, t, "pendek").status_code == 422
    assert reset(client, "x" * 30).status_code == 400 and reset(client, "pendek").status_code == 422
    assert reset(client, t).json() == {"ok": True}
    assert login(client, e, OLD) == 401 and login(client, e, NEW) == 200
    assert client.get("/api/auth/me", headers=old_jwt).status_code == 401  # sesi lama (mis. perangkat yang dicuri) mati
    assert reset(client, t, "lain-lagi-123").status_code == 400  # sekali pakai
    assert login(client, e, NEW) == 200


def test_expired_token_and_newer_request_supersedes(client, reg):
    h, e = reg()
    forgot(client, e)
    t1 = last_token()
    with SessionLocal() as db:
        db.scalars(select(PasswordReset).where(PasswordReset.user_id == _uid(h))).first().expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    assert reset(client, t1).status_code == 400 and login(client, e, OLD) == 200  # kedaluwarsa: tak ada yang berubah
    forgot(client, e)
    forgot(client, e)
    t2, t3 = mailer.OUTBOX[-2]["body"], mailer.OUTBOX[-1]["body"]
    tok2, tok3 = (re.search(r"#t=([\w-]+)", x).group(1) for x in (t2, t3))
    assert reset(client, tok3).status_code == 200
    assert reset(client, tok2).status_code == 400  # token lain milik akun itu ikut hangus setelah reset berhasil


def test_reset_unlocks_account(client, reg, monkeypatch):
    monkeypatch.setattr(settings, "login_max_failures", 2)
    h, e = reg()
    assert [login(client, e, "salah-salah") for _ in range(2)] == [401, 401]
    assert login(client, e, OLD) == 429
    forgot(client, e)
    assert reset(client, last_token()).status_code == 200
    assert login(client, e, NEW) == 200


def test_forgot_rate_cap_per_account(client, reg):
    h, e = reg()
    for _ in range(6):
        assert forgot(client, e).status_code == 200
    assert len(mailer.OUTBOX) == settings.reset_max_per_hour  # sisanya diam-diam diabaikan, balasan tetap sama


def test_deleted_accounts_cannot_reset(client, reg):
    h, e = reg()
    forgot(client, e)
    t = last_token()
    assert client.post("/api/account/delete", headers=h, json={"password": OLD}).status_code == 200
    assert reset(client, t).status_code == 400  # token ikut terhapus bersama akun
    mailer.OUTBOX.clear()
    assert forgot(client, e).status_code == 200 and mailer.OUTBOX == []  # email sudah dikosongkan
    with SessionLocal() as db:
        assert db.scalar(select(PasswordReset).where(PasswordReset.user_id == _uid(h))) is None


# ---------- provider SMTP ----------
class FakeGmailService:
    """Mock minimal untuk googleapiclient Gmail service."""
    instances = []
    fail = False
    last_raw = None
    last_to = None
    last_from = None
    last_subject = None
    last_body = None

    def __init__(self):
        FakeGmailService.instances.append(self)

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, userId, body):
        if FakeGmailService.fail:
            raise OSError("gmail api gagal")
        import base64
        from email import message_from_bytes
        raw = body["raw"]
        FakeGmailService.last_raw = raw
        msg = message_from_bytes(base64.urlsafe_b64decode(raw + "=="))
        FakeGmailService.last_to = msg["To"]
        FakeGmailService.last_from = msg["From"]
        FakeGmailService.last_subject = msg["Subject"]
        FakeGmailService.last_body = msg.get_payload()
        return self

    def execute(self):
        return {"id": "fake-msg-id"}


@pytest.fixture
def gmail(monkeypatch):
    FakeGmailService.instances = []
    FakeGmailService.fail = False
    FakeGmailService.last_raw = FakeGmailService.last_to = None
    FakeGmailService.last_from = FakeGmailService.last_subject = FakeGmailService.last_body = None
    for k, v in (
        ("email_provider", "gmail"),
        ("gmail_client_id", "cid"),
        ("gmail_client_secret", "csec"),
        ("gmail_refresh_token", "rtok"),
        ("gmail_sender", "Dospem <no-reply@test.id>"),
    ):
        monkeypatch.setattr(settings, k, v)

    def fake_build(service, version, credentials=None, cache_discovery=False):
        assert service == "gmail" and version == "v1"
        return FakeGmailService()

    # Patch di dalam modul mailer (import lokal di _send_gmail)
    import googleapiclient.discovery
    monkeypatch.setattr(googleapiclient.discovery, "build", fake_build)
    # Juga pastikan Credentials bisa dibuat tanpa jaringan
    from google.oauth2 import credentials as gcreds
    class FakeCreds:
        def __init__(self, *a, **k):
            pass
    monkeypatch.setattr(gcreds, "Credentials", FakeCreds)
    return FakeGmailService


def test_gmail_sends_message(gmail):
    assert mailer.send("mhs@test.id", "Subjek", "Isi pesan") is True
    assert gmail.last_to == "mhs@test.id"
    assert gmail.last_from == "Dospem <no-reply@test.id>"
    assert gmail.last_subject == "Subjek"
    assert "Isi pesan" in (gmail.last_body or "")
    assert mailer.OUTBOX == []  # provider gmail tidak menyimpan pesan di memori


def test_gmail_failures_never_raise(gmail):
    gmail.fail = True
    assert mailer.send("a@test.id", "S", "B") is False  # jaringan/API gagal: dicatat, tidak dilempar
    gmail.fail = False
    # header injection ditolak oleh EmailMessage
    assert mailer.send("a@test.id\nBcc: korban@test.id", "S", "B") is False
    assert gmail.last_to is None or gmail.last_to == "a@test.id"  # tidak pernah mengirim Bcc palsu


def test_forgot_does_not_leak_gmail_failure(client, reg, gmail):
    h, e = reg()
    gmail.fail = True
    a, b = forgot(client, e), forgot(client, "tidak-ada@test.id")
    assert a.status_code == b.status_code == 200 and a.json() == b.json()  # kegagalan kirim tak terlihat dari luar


def test_reset_page_served(client):
    r = client.get("/reset.html")
    assert r.status_code == 200 and "location.hash" in r.text


def test_static_pages_do_not_redeclare_common_js_globals():
    """common.js dimuat lebih dulu; deklarasi ulang nama top-level-nya di skrip halaman = SyntaxError dan halaman mati total
    (pernah terjadi pada reset.html; tak terlihat oleh tes API)."""
    import pathlib
    static = pathlib.Path(__file__).resolve().parents[1] / "static"
    decl = re.compile(r"^(?:const|let|var|function|async function|class)\s+([A-Za-z_$][\w$]*)", re.M)
    common = set(decl.findall((static / "common.js").read_text(encoding="utf-8")))
    assert "$" in common  # sanity: pola benar-benar menemukan deklarasi
    for page in static.glob("*.html"):
        html = page.read_text(encoding="utf-8")
        if "/common.js" not in html:
            continue
        for script in re.findall(r"<script>(.*?)</script>", html, re.S):
            clash = common & set(decl.findall(script))
            assert not clash, f"{page.name} mendeklarasikan ulang {sorted(clash)} dari common.js"
