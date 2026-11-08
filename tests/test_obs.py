"""Observability yang aman untuk data pribadi: redaksi, log terstruktur, ID permintaan, peristiwa keamanan, 500 yang rapi, dan Sentry."""
import json
import logging
import sys
from contextlib import contextmanager

import httpx
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import llm, mailer, obs, ratelimit
from app.config import settings
from app.main import app, startup_warnings
from tests.conftest import bearer
from tests.test_app import BODY

EMAIL, PW, PW2 = "mhs.rahasia@kampus.ac.id", "sandi-rahasia-123", "sandi-baru-98765"
SECRET_TEXT = "motivasi-belajar-rahasia-xyz"  # sengaja < 32 karakter: tidak boleh bergantung pada pola "string acak panjang"


@contextmanager
def temp_route(path, fn, methods=("GET", "POST")):
    """Daftarkan rute sementara di depan mount statis '/' (yang akan menangkap semuanya)."""
    route = APIRoute(path, fn, methods=list(methods))
    app.router.routes.insert(0, route)
    try:
        yield
    finally:
        app.router.routes.remove(route)


def evs(caplog, name=None):
    out = [(r.event, getattr(r, "data", {}), r) for r in caplog.records if getattr(r, "event", None)]
    return [x for x in out if name is None or x[0] == name]


@pytest.fixture(autouse=True)
def _clean(caplog):
    caplog.set_level(logging.INFO)
    obs._last.clear()
    yield


# ---------- redaksi ----------
def test_redact_removes_personal_data_but_keeps_normal_text():
    s = f"gagal untuk {EMAIL} dengan Bearer abcdefgh12345678 dan eyJhbGciOiJI.eyJzdWIiOiIx.c2lnbmF0dXJl serta #t=AbCdEfGhIjKlMnOpQrStUv dan {'Ab1' * 14}"
    r = obs.redact(s)
    assert EMAIL not in r and "abcdefgh12345678" not in r and "eyJhbGci" not in r and "AbCdEfGhIjKlMnOpQrStUv" not in r and "Ab1" * 14 not in r
    assert "[email]" in r and "[jwt]" in r and "Bearer [token]" in r and "#t=[token]" in r and "[token]" in r
    assert obs.redact("Peneliti menulis catatan lapangan setiap hari di sekolah.") == "Peneliti menulis catatan lapangan setiap hari di sekolah."
    assert obs.redact(None) == "" and obs.redact(42) == "42"
    assert obs.redact("/api/sidang/{id}/answer status=200 ms=15") == "/api/sidang/{id}/answer status=200 ms=15"  # jalur & angka tidak ikut tersaring


def test_long_traceback_keeps_head_and_tail_and_dash_rules_survive():
    assert obs.redact("+" + "-" * 40) == "+" + "-" * 40 and obs.redact("Ab1" * 14) == "[token]"  # garis pemisah aman, string acak disensor
    assert obs.redact("constraint drafts_owner_doc_type_chapter_key_key gagal") == "constraint drafts_owner_doc_type_chapter_key_key gagal"  # nama identifier tetap terbaca untuk diagnosis
    assert obs.redact("hash " + "f3a9" * 12) == "hash [token]"  # hex/hash panjang tetap disensor
    try:
        raise ValueError(f"galat akhir untuk {EMAIL}")
    except ValueError:
        import sys as _s
        ex = _s.exc_info()
    r = _with("x", ex, {})
    r.exc_info = (ex[0], ex[1], ex[2])
    long_tb = "\n".join(f"  File \"modul_{i}.py\", line {i}, in fungsi_{i}" for i in range(400))
    monkey = obs.redact  # traceback sintetis panjang: pastikan kepala & ekor selamat, tengah dipotong, panjang terbatas
    import traceback as _tb
    orig = _tb.format_exception
    _tb.format_exception = lambda *a, **k: [long_tb + "\nValueError: galat akhir untuk " + EMAIL]
    try:
        out = obs._exc(r)
    finally:
        _tb.format_exception = orig
    assert out.startswith("  File \"modul_0.py\"") and out.rstrip().endswith("galat akhir untuk [email]") and "…[dipotong]…" in out
    assert len(out) <= obs.EXC_HEAD + obs.EXC_TAIL + 30 and EMAIL not in out


def test_redact_strips_database_row_values():
    pg = 'duplicate key value violates unique constraint "x"\nDETAIL:  Key (owner)=(dev-rahasia-1) already exists.\n'
    assert "dev-rahasia-1" not in obs.redact(pg) and "DETAIL: [disaring]" in obs.redact(pg) and "duplicate key value violates" in obs.redact(pg)
    sa = "(psycopg.errors.NotNullViolation) null value\n[SQL: INSERT INTO drafts (content) VALUES (%(content)s)]\n[parameters: {'content': 'isi-rahasia-pendek'}]\n(Background on this error at: https://sqlalche.me/e/20/gkpj)"
    out = obs.redact(sa)
    assert "isi-rahasia-pendek" not in out and "[SQL: INSERT INTO drafts" in out and "Background on this error" in out  # SQL tetap, nilai hilang


def test_database_errors_never_carry_parameter_values(client):
    """Tanpa hide_parameters, str(IntegrityError) memuat nilai kolom (email, isi tulisan). Ini yang akan masuk ke log & Sentry saat ada error DB."""
    from sqlalchemy.exc import IntegrityError
    from app.db import SessionLocal, engine
    from app.models import Draft
    assert engine.hide_parameters is True
    with SessionLocal() as db:
        db.add(Draft(owner="u-uji-hp", doc_type="skripsi", chapter_key="pendahuluan", content=SECRET_TEXT))
        db.commit()
        db.add(Draft(owner="u-uji-hp", doc_type="skripsi", chapter_key="pendahuluan", content=SECRET_TEXT))
        with pytest.raises(IntegrityError) as e:
            db.commit()
    assert SECRET_TEXT not in str(e.value)  # isi tulisan (parameter) tidak pernah ada di pesan mentah, di database mana pun
    # PostgreSQL tetap menulis nilai kolom KUNCI di baris "DETAIL: Key (...)=(...)" pada pesan mentah; redaksi kitalah yang membuangnya sebelum ke log/Sentry
    assert "u-uji-hp" not in obs.redact(str(e.value)) and SECRET_TEXT not in obs.redact(str(e.value))


def test_no_new_exception_messages_embed_dynamic_text():
    """Pesan exception dari kode kita tidak boleh memuat teks pengguna (bisa masuk log/Sentry). Daftar ini sengaja diperiksa: tambahan baru = tinjau dulu."""
    import pathlib
    import re
    found = set()
    for f in sorted((pathlib.Path(__file__).resolve().parents[1] / "app").glob("*.py")):
        for ln in f.read_text(encoding="utf-8").splitlines():
            if re.search(r"raise [A-Za-z.]+\(f[\"']", ln):
                found.add(f"{f.name}: {re.search(r'raise ([A-Za-z.]+)', ln).group(1)}")
    assert found == {"llm.py: GuardError", "oai.py: ValueError", "style.py: ValueError", "docparse.py: ParseError"}  # batas angka, kode server OAI, kunci aturan dari admin, jumlah halaman PDF vs batas: bukan teks mahasiswa


def test_norm_path_single_source():
    assert obs.norm_path("/api/sidang/17/answer") == "/api/sidang/{id}/answer" == ratelimit.norm_path("/api/sidang/17/answer")


# ---------- format log ----------
def _record(msg="halo", exc=None, **extra):
    return logging.LogRecord("dospem.test", logging.WARNING, __file__, 1, msg, (), exc, extra=None) if not extra else _with(msg, exc, extra)


def _with(msg, exc, extra):
    r = logging.LogRecord("dospem.test", logging.WARNING, __file__, 1, msg, (), exc)
    for k, v in extra.items():
        setattr(r, k, v)
    return r


def test_json_formatter_shape_and_cleaning():
    tok = obs.REQUEST_ID.set("rid-abc-12345")
    try:
        line = obs.JsonFormatter().format(_with(f"kirim ke {EMAIL}", None, {"event": "uji", "data": {"n": 3, "ok": True, "x": None, "s": f"{EMAIL} {'z' * 300}"}}))
    finally:
        obs.REQUEST_ID.reset(tok)
    d = json.loads(line)
    assert d["level"] == "WARNING" and d["logger"] == "dospem.test" and d["request_id"] == "rid-abc-12345" and d["event"] == "uji"
    assert d["msg"] == "kirim ke [email]" and d["n"] == 3 and d["ok"] is True and d["x"] is None
    assert EMAIL not in line and len(d["s"]) <= 200  # nilai dipotong dan disaring
    assert d["ts"].endswith("+00:00")


def test_exception_text_is_redacted():
    try:
        raise ValueError(f"duplicate key (email)=({EMAIL}) already exists")
    except ValueError:
        import sys as _s
        r = _with("gagal", _s.exc_info(), {})
    for fmt in (obs.JsonFormatter(), obs.TextFormatter()):
        out = fmt.format(r)
        assert "ValueError" in out and EMAIL not in out and "[email]" in out


def test_dev_only_logs_are_unredacted_only_outside_production(monkeypatch):
    r = _with(f"tautan #t={'Q' * 30} untuk {EMAIL}", None, {"dev_only": True})
    monkeypatch.setattr(settings, "env", "dev")
    assert EMAIL in obs.JsonFormatter().format(r) and "Q" * 30 in obs.TextFormatter().format(r)  # pengembang perlu melihat tautan reset
    monkeypatch.setattr(settings, "env", "prod")
    assert EMAIL not in obs.JsonFormatter().format(r) and "Q" * 30 not in obs.TextFormatter().format(r)
    plain = _with(f"untuk {EMAIL}", None, {})
    monkeypatch.setattr(settings, "env", "dev")
    assert EMAIL not in obs.JsonFormatter().format(plain)  # tanpa penanda dev_only: selalu disaring


def test_setup_logging_is_idempotent_and_silences_http_libraries():
    root = logging.getLogger()
    obs.setup_logging()
    obs.setup_logging()
    assert sum(1 for h in root.handlers if getattr(h, "_dospem", False)) == 1
    assert logging.getLogger("httpx").level == logging.WARNING and logging.getLogger("uvicorn.access").disabled
    assert logging.getLogger("uvicorn.error").propagate and logging.getLogger("uvicorn.error").handlers == []


def test_python_warnings_go_through_logging(caplog):
    """pytest mengambil alih warnings.showwarning selama tes, jadi jalur logging diuji langsung; di server nyata captureWarnings yang aktif."""
    obs.setup_logging()
    assert logging._warnings_showwarning is not None  # captureWarnings(True) terpasang
    logging._showwarning(UserWarning(f"peringatan uji untuk {EMAIL}"), UserWarning, "x.py", 3)
    rec = [r for r in caplog.records if r.name == "py.warnings"]
    out = obs.JsonFormatter().format(rec[0])
    assert rec and "peringatan uji" in out and EMAIL not in out and json.loads(out)["logger"] == "py.warnings"


def test_outbound_http_urls_with_query_are_never_logged(caplog):
    """httpx mencatat URL lengkap (termasuk query = kata kunci pencarian mahasiswa) pada level INFO bila tidak dijinakkan."""
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={}))) as c:
        c.get(f"https://api.openalex.org/works?search={SECRET_TEXT}")
    assert SECRET_TEXT not in caplog.text and not [r for r in caplog.records if r.name == "httpx"]


# ---------- middleware permintaan ----------
def test_request_id_and_access_event(client, caplog):
    r = client.get("/api/doctypes", headers={"X-Request-ID": "abc-123-def-456"})
    assert r.headers["X-Request-ID"] == "abc-123-def-456"
    for bad in ("x" * 100, "bad id!!", "pendek", ""):
        rid = client.get("/api/doctypes", headers={"X-Request-ID": bad}).headers["X-Request-ID"]
        assert rid != bad and len(rid) == 16
    ev = [d for n, d, _ in evs(caplog, "request") if d["path"] == "/api/doctypes"]
    assert ev[0] == {"method": "GET", "path": "/api/doctypes", "status": 200, "ms": ev[0]["ms"]} and isinstance(ev[0]["ms"], int)
    assert evs(caplog, "request")[0][2].levelno == logging.INFO


def test_access_log_normalizes_ids_and_never_logs_query_or_credentials(client, caplog):
    client.get(f"/api/sidang/17/answer?token={SECRET_TEXT}", headers={"Authorization": "Bearer abcdefgh12345678", "X-Device-Id": "dev-rahasia-0001"})
    paths = [d["path"] for _, d, _ in evs(caplog, "request")]
    assert "/api/sidang/{id}/answer" in paths
    assert SECRET_TEXT not in caplog.text and "abcdefgh12345678" not in caplog.text and "dev-rahasia-0001" not in caplog.text


def test_healthz_success_is_quiet_but_slow_and_5xx_are_loud(client, caplog, monkeypatch):
    client.get("/healthz")
    assert not [d for _, d, _ in evs(caplog, "request") if d["path"] == "/healthz"]
    monkeypatch.setattr(settings, "slow_request_ms", 0)
    client.get("/api/doctypes")
    assert evs(caplog, "request")[-1][2].levelno == logging.WARNING  # lambat
    caplog.clear()

    def five():
        from fastapi import HTTPException
        raise HTTPException(503, "x")
    with temp_route("/__five", five):
        client.get("/__five")
    assert [r.levelno for _, d, r in evs(caplog, "request") if d["path"] == "/__five"] == [logging.ERROR]


def test_unhandled_exception_is_clean_for_user_and_complete_in_log(caplog):
    def boom():
        raise ValueError(f"duplicate key (email)=({EMAIL}) already exists")
    c = TestClient(app)
    with temp_route("/__boom", boom):
        r = c.get("/__boom?x=1")
    assert r.status_code == 500 and r.headers["X-Request-ID"] == r.json()["request_id"]
    assert set(r.json()) == {"detail", "request_id"} and "Traceback" not in r.text and "ValueError" not in r.text and EMAIL not in r.text  # tanpa bocoran internal
    (name, data, rec), = evs(caplog, "unhandled_exception")
    assert data == {"method": "GET", "path": "/__boom", "exc": "ValueError"} and rec.exc_info
    out = obs.JsonFormatter().format(rec)
    assert "ValueError" in out and EMAIL not in out and "[email]" in out  # traceback ada untuk admin, tetapi tersaring
    assert "ExceptionGroup" not in out and "[email]) already exists" in out  # dibuka dari ExceptionGroup; baris galat sebenarnya tidak terpotong
    req_ev = [rr for n, d, rr in evs(caplog, "request") if d["path"] == "/__boom"]
    assert req_ev and req_ev[0].levelno == logging.ERROR and json.loads(obs.JsonFormatter().format(req_ev[0]))["status"] == 500


def test_request_id_present_on_rate_limited_responses(client, caplog, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    ratelimit._mem.clear()
    codes = [client.post("/api/auth/forgot", json={"email": "siapa@saja.id"}) for _ in range(5)]
    assert [r.status_code for r in codes][:3] == [200, 200, 200] and codes[-1].status_code == 429
    assert codes[-1].headers["X-Request-ID"]  # middleware terluar membungkus pembatas laju
    assert len(evs(caplog, "rate_limited")) == 1  # dibatasi frekuensinya: tidak membanjiri log
    ratelimit._mem.clear()


def test_redis_outage_is_visible_not_silent(client, caplog, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)

    def down(*a, **k):
        raise ConnectionError("redis mati")
    monkeypatch.setattr(ratelimit, "hit", down)
    assert client.post("/api/auth/forgot", json={"email": "siapa@saja.id"}).status_code == 200  # layanan tetap jalan (fail-open)
    client.post("/api/auth/forgot", json={"email": "siapa@saja.id"})
    ev = evs(caplog, "redis_unavailable")
    assert len(ev) == 1 and ev[0][1] == {"where": "ratelimit"} and ev[0][2].levelno == logging.ERROR


# ---------- peristiwa keamanan ----------
def test_security_events_cover_the_account_lifecycle(client, caplog, monkeypatch):
    monkeypatch.setattr(settings, "login_max_failures", 2)
    mailer.OUTBOX.clear()
    h = bearer(client.post("/api/auth/register", json={"email": EMAIL, "password": PW}).json()["token"])
    for _ in range(2):
        client.post("/api/auth/login", json={"email": EMAIL, "password": "salah-salah"})
    client.post("/api/auth/login", json={"email": EMAIL, "password": PW})  # terkunci
    names = [n for n, _, _ in evs(caplog) if n != "request"]
    assert names == ["user_registered", "login_failed", "account_locked", "login_failed", "login_blocked_locked"]
    assert evs(caplog, "account_locked")[0][1] == {"minutes": settings.login_lock_minutes}
    caplog.clear()
    client.post("/api/auth/forgot", json={"email": EMAIL})
    import re
    tok = re.search(r"#t=([\w-]+)", mailer.OUTBOX[-1]["body"]).group(1)
    client.post("/api/auth/reset", json={"token": tok, "new_password": PW2})
    h2 = bearer(client.post("/api/auth/login", json={"email": EMAIL, "password": PW2}).json()["token"])
    client.post("/api/auth/password", headers=h2, json={"old_password": PW2, "new_password": PW})
    h3 = bearer(client.post("/api/auth/login", json={"email": EMAIL, "password": PW}).json()["token"])
    client.post("/api/account/delete", headers=h3, json={"password": PW})
    assert [n for n, _, _ in evs(caplog) if n != "request"] == ["password_reset_requested", "password_reset_done", "password_changed", "account_deleted"]


def test_llm_errors_are_logged_without_content(client, caplog, monkeypatch):
    class Bad(llm.Mock):
        def complete(self, system, user, smart=False):
            raise httpx.HTTPStatusError(f"401 untuk {SECRET_TEXT}", request=httpx.Request("POST", f"https://llm/x?q={SECRET_TEXT}"), response=httpx.Response(401))
    monkeypatch.setattr(llm, "get_provider", lambda: Bad())
    assert client.post("/api/coach", headers={"X-Device-Id": "perangkat-uji-001"}, json=BODY).status_code == 502
    (n, d, r), = evs(caplog, "llm_error")
    assert d == {"kind": "coach", "exc": "HTTPStatusError", "status": 401} and r.levelno == logging.WARNING  # 401 = kunci API salah: terlihat jelas oleh admin
    assert SECRET_TEXT not in caplog.text


def test_payment_webhook_anomalies_are_logged(client, caplog, reg):
    from tests.test_app import make_premium
    h, _ = reg()
    make_premium(client, h)
    import hashlib
    oid = client.post("/api/pay/checkout", headers=h, json={"plan": "premium_90"}).json()["order_id"]
    caplog.clear()  # make_premium di atas sudah menghasilkan payment_paid miliknya sendiri

    def hook(amt, sig=None):
        s = sig or hashlib.sha512(f"{oid}200{amt}sk".encode()).hexdigest()
        return client.post("/api/pay/webhook/midtrans", json={"order_id": oid, "status_code": "200", "gross_amount": amt, "transaction_status": "settlement", "signature_key": s}).status_code
    assert hook("69000.00", "salah") == 403 and hook("1000.00") == 400 and hook("69000.00") == 200
    got = [n for n, _, _ in evs(caplog) if n.startswith("payment_")]
    assert got == ["payment_webhook_rejected", "payment_amount_mismatch", "payment_paid"]
    assert evs(caplog, "payment_amount_mismatch")[0][2].levelno == logging.ERROR


# ---------- sapuan privasi: tidak ada data pribadi di SEMUA log ----------
class Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, r):
        self.lines.append(obs.JsonFormatter().format(r))


def test_no_personal_data_in_any_log_line_across_full_flows(client, monkeypatch, reg):
    """Satu skenario panjang (daftar, tulis, bimbingan AI, login gagal, reset, ganti sandi, email gagal, error tak terduga, hapus akun)
    dan SEMUA baris log (format produksi) diperiksa: tak boleh memuat email, kata sandi, token, atau isi tulisan."""
    import re
    import time
    import jwt
    monkeypatch.setattr(settings, "env", "prod")  # produksi: log mock email pun disaring
    cap, root = Capture(), logging.getLogger()
    old = root.level
    root.addHandler(cap)
    root.setLevel(logging.INFO)
    try:
        mailer.OUTBOX.clear()
        reg_r = client.post("/api/auth/register", json={"email": EMAIL, "password": PW}).json()
        h = bearer(reg_r["token"])
        client.put("/api/drafts/skripsi/pendahuluan", headers=h, json={"content": SECRET_TEXT + " dst. " * 40})
        client.post("/api/coach", headers=h, json={**BODY, "text": SECRET_TEXT + " Penelitian ini membahas motivasi belajar siswa."})
        client.post("/api/check", json={"text": SECRET_TEXT + " tinggal dirumah ,analisa"})
        client.get(f"/api/examples?q={SECRET_TEXT}", headers=h)
        client.post("/api/auth/login", json={"email": EMAIL, "password": "pw-salah-rahasia-1"})
        client.post("/api/auth/forgot", json={"email": EMAIL})
        raw_token = re.search(r"#t=([\w-]+)", mailer.OUTBOX[-1]["body"]).group(1)
        client.post("/api/auth/reset", json={"token": raw_token, "new_password": PW2})
        jwt_tok = client.post("/api/auth/login", json={"email": EMAIL, "password": PW2}).json()["token"]
        h2 = bearer(jwt_tok)
        # email gagal terkirim: pesan galat Gmail API bisa memuat alamat penerima
        monkeypatch.setattr(settings, "email_provider", "gmail")
        monkeypatch.setattr(settings, "gmail_client_id", "cid")
        monkeypatch.setattr(settings, "gmail_client_secret", "csec")
        monkeypatch.setattr(settings, "gmail_refresh_token", "rtok")
        monkeypatch.setattr(settings, "gmail_sender", "no-reply@test.id")

        def boom_gmail(*a, **k):
            raise RuntimeError(f"User {EMAIL} not found / rejected")
        monkeypatch.setattr(mailer, "_send_gmail", boom_gmail)
        mailer.send(EMAIL, "S", "B")
        # error tak terduga yang pesannya memuat data
        def boom():
            raise RuntimeError(f"gagal untuk {EMAIL} token {jwt_tok}")
        with temp_route("/__boom2", boom):
            TestClient(app).post(f"/__boom2?token={jwt_tok}", headers=h2, json={"content": SECRET_TEXT})

        def db_error():  # galat DB NYATA yang membawa teks mahasiswa sebagai parameter: tanpa hide_parameters ini bocor ke log
            from app.db import SessionLocal
            from app.models import Draft
            with SessionLocal() as db:
                db.add(Draft(owner="u-uji-dup", doc_type="skripsi", chapter_key="pendahuluan", content=SECRET_TEXT))
                db.commit()
                db.add(Draft(owner="u-uji-dup", doc_type="skripsi", chapter_key="pendahuluan", content=SECRET_TEXT))
                db.commit()
        with temp_route("/__dberr", db_error):
            TestClient(app).get("/__dberr")
        client.post("/api/account/delete", headers=h2, json={"password": PW2})
    finally:
        root.removeHandler(cap)
        root.setLevel(old)
    blob = "\n".join(cap.lines)
    assert len(cap.lines) > 10 and '"event": "unhandled_exception"' in blob and '"event": "email_failed"' in blob
    assert "IntegrityError" in blob  # galat DB benar-benar tercatat (jadi ketiadaan teks di bawah bermakna)
    failed = [json.loads(ln) for ln in cap.lines if '"event": "email_failed"' in ln][0]
    assert failed["domain"] == "kampus.ac.id" and failed["exc"] == "RuntimeError" and failed["level"] == "ERROR"  # domain saja: cukup untuk diagnosis
    for secret in (EMAIL, EMAIL.split("@")[0], PW, PW2, "pw-salah-rahasia-1", raw_token, jwt_tok, reg_r["token"], SECRET_TEXT):
        assert secret not in blob, f"BOCOR di log: {secret[:25]}"
    for line in cap.lines:
        json.loads(line)  # setiap baris JSON valid


# ---------- Sentry ----------
import importlib.util  # noqa: E402

needs_sentry = pytest.mark.skipif(importlib.util.find_spec("sentry_sdk") is None, reason="butuh paket sentry-sdk (ada di requirements.txt)")  # hanya tes yang memerlukan SDK dilewati, bukan seluruh modul
LOCAL_SECRET, BODY_SECRET, QUERY_SECRET, HEADER_SECRET = "variabel-lokal-rahasia-1", "isi-body-rahasia-2", "query-rahasia-3", "kunci-header-rahasia-4"
COOKIE_VALUE = "biskuit-rahasia-5"
LONG_TOKEN = "Zq9" * 14  # token acak panjang di pesan galat: pola yang memang disaring


def _run_sentry_scenario(monkeypatch, **overrides):
    """Jalankan aplikasi BARU (dibuat setelah init, seperti produksi) dengan SDK Sentry asli dan transport penangkap; kembalikan event yang 'terkirim'."""
    import sentry_sdk
    from fastapi import FastAPI
    events = []
    monkeypatch.setattr(settings, "sentry_dsn", "https://publickey@o0.ingest.invalid/1")
    assert obs.init_sentry(transport=lambda ev: events.append(ev), **overrides) is True
    fresh = FastAPI()
    fresh.middleware("http")(obs.request_context)

    @fresh.post("/proses/{n}")
    def proses(n: int):
        rahasia_lokal = LOCAL_SECRET  # noqa: F841  (variabel lokal yang akan ikut terkirim jika include_local_variables aktif)
        raise ValueError(f"duplicate key (email)=({EMAIL}) already exists, token {LONG_TOKEN}")
    r = TestClient(fresh).post(f"/proses/42?token={QUERY_SECRET}", json={"isi": BODY_SECRET}, headers={"X-Rahasia": HEADER_SECRET, "Cookie": f"sid={COOKIE_VALUE}"})
    sentry_sdk.flush()
    sentry_sdk.get_client().close()
    sentry_sdk.init()  # reset ke keadaan tanpa DSN untuk tes lain
    return r, events


@needs_sentry
def test_sentry_control_run_proves_leaks_are_real_without_scrubbing(monkeypatch):
    """Kontrol: dengan pengaturan 'bawaan' (tanpa penyaringan kita) data memang bocor. Tanpa ini, tes penyaringan bisa kosong makna."""
    r, events = _run_sentry_scenario(monkeypatch, before_send=None, before_send_transaction=None, include_local_variables=True, max_request_body_size="always", send_default_pii=True)
    blob = json.dumps(events, default=str)
    assert events and LOCAL_SECRET in blob and QUERY_SECRET in blob and EMAIL in blob


@needs_sentry
def test_sentry_with_our_config_leaks_nothing_and_links_to_logs(monkeypatch):
    r, events = _run_sentry_scenario(monkeypatch)
    assert r.status_code == 500 and len(events) == 1  # tepat satu event (tanpa dobel dari integrasi logging)
    blob = json.dumps(events, default=str)
    for secret in (LOCAL_SECRET, BODY_SECRET, QUERY_SECRET, HEADER_SECRET, COOKIE_VALUE, EMAIL, LONG_TOKEN):  # NILAI-nilainya (baris kode di stack trace boleh ada)
        assert secret not in blob, f"BOCOR ke Sentry: {secret}"
    ev = events[0]
    assert ev["exception"]["values"][0]["type"] == "ValueError" and "[email]" in ev["exception"]["values"][0]["value"]
    assert ev["request"] == {"method": "POST", "url": "http://testserver/proses/{id}"} and "user" not in ev  # tanpa query, header, cookie, pengguna
    assert ev["tags"]["request_id"] == r.json()["request_id"] == r.headers["X-Request-ID"]  # bisa dilacak ke baris log
    assert all("vars" not in f for f in ev["exception"]["values"][0]["stacktrace"]["frames"])


def test_scrub_event_unit():
    ev = {"request": {"url": "https://a.id/api/x/5?token=abc#f", "data": {"x": 1}, "headers": {"A": "b"}, "cookies": {"c": "d"}, "query_string": "token=abc"},
          "user": {"email": EMAIL}, "extra": {"isi": SECRET_TEXT}, "message": f"hai {EMAIL}",
          "logentry": {"message": f"x {EMAIL}", "formatted": f"x {EMAIL}", "params": [1]},
          "exception": {"values": [{"value": f"bad {EMAIL}", "stacktrace": {"frames": [{"vars": {"a": SECRET_TEXT}, "lineno": 3}]}}]},
          "breadcrumbs": {"values": [{"message": f"m {EMAIL}", "data": {"url": f"https://x/?q={SECRET_TEXT}"}}]}}
    out = obs.scrub_event(ev)
    assert SECRET_TEXT not in json.dumps(out) and EMAIL not in json.dumps(out)
    assert out["request"] == {"url": "https://a.id/api/x/{id}"} and "user" not in out and "extra" not in out
    assert out["exception"]["values"][0]["stacktrace"]["frames"] == [{"lineno": 3}]


def test_sentry_off_without_dsn_and_graceful_when_sdk_missing(monkeypatch, caplog):
    monkeypatch.setattr(settings, "sentry_dsn", "")
    assert obs.init_sentry() is False
    monkeypatch.setattr(settings, "sentry_dsn", "https://k@o0.ingest.invalid/1")
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)  # simulasi paket tidak terpasang
    assert obs.init_sentry() is False and "sentry-sdk tidak terpasang" in caplog.text


def test_startup_warnings_for_observability(monkeypatch):
    monkeypatch.setattr(settings, "sentry_dsn", "")
    assert any("SENTRY_DSN kosong" in w for w in startup_warnings(True)) and not any("SENTRY" in w for w in startup_warnings(False))
    monkeypatch.setattr(settings, "sentry_dsn", "https://k@o0.ingest.invalid/1")
    import types
    monkeypatch.setitem(sys.modules, "sentry_sdk", types.ModuleType("sentry_sdk"))  # hermetik: SDK "terpasang" tanpa bergantung pada lingkungan
    assert not any("SENTRY" in w for w in startup_warnings(True))
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)
    assert any("sentry-sdk tidak terpasang" in w for w in startup_warnings(True))
