"""Observability yang AMAN untuk data pribadi: log terstruktur (JSON), ID permintaan, peristiwa keamanan, penanganan error tak terduga,
dan integrasi Sentry opsional dengan penyaringan ketat.

Prinsip: log dan laporan error TIDAK PERNAH memuat isi tulisan, isi permintaan, header, query string, alamat IP, email, token, atau variabel lokal.
`redact()` adalah lapisan pengaman terakhir untuk teks yang lolos (mis. pesan galat database yang menyertakan nilai baris)."""
import json
import logging
import re
import sys
import time
import traceback
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi.responses import JSONResponse

from .config import settings

REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)
RID_OK = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}")
BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
RESET = re.compile(r"((?:#|[?&])t=)[A-Za-z0-9_-]{16,}")
DETAIL = re.compile(r"(?im)^(\s*DETAIL:).*$")  # PostgreSQL menyertakan NILAI baris di sini (Key (col)=(nilai), Failing row contains (...))
PARAMS = re.compile(r"(?s)\[parameters: .*?\](?=\n|$)")  # jaring pengaman: SQLAlchemy tanpa hide_parameters mencetak nilai bind
LONG = re.compile(r"(?<![A-Za-z0-9_-])(?=[A-Za-z0-9_-]*[0-9A-Z])[A-Za-z0-9_-]{32,}(?![A-Za-z0-9_-])")  # token acak hampir selalu punya angka/kapital; nama identifier (snake_case huruf kecil) & garis pemisah "-----" tidak disensor
log = logging.getLogger("dospem")
_ID_SEG = re.compile(r"/\d+(?=/|$)")
_last: dict[tuple, float] = {}
_SKIP = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "event", "data", "dev_only"}


def norm_path(p: str) -> str:
    """/api/sidang/17/answer -> /api/sidang/{id}/answer (agar aturan/log tidak tergantung id)."""
    return _ID_SEG.sub("/{id}", p)


def redact(text) -> str:
    """Buang email, JWT, bearer token, token reset, dan string acak panjang dari teks."""
    s = "" if text is None else str(text)
    s = DETAIL.sub(r"\1 [disaring]", s)
    s = PARAMS.sub("[parameters: disaring]", s)
    s = EMAIL.sub("[email]", s)
    s = JWT.sub("[jwt]", s)
    s = BEARER.sub(r"\1 [token]", s)
    s = RESET.sub(r"\1[token]", s)
    return LONG.sub("[token]", s)


def _clean(v, limit=200):
    if v is None or isinstance(v, (bool, int, float)):
        return v
    return redact(v)[:limit]


def _text(r: logging.LogRecord, s: str) -> str:
    # log pengembangan yang SENGAJA memuat tautan (email palsu) tidak disaring, kecuali di produksi
    return s if getattr(r, "dev_only", False) and settings.env != "prod" else redact(s)


def _fields(r: logging.LogRecord) -> dict:
    out = {}
    if getattr(r, "event", None):
        out["event"] = r.event
    out.update({k: _clean(v) for k, v in (getattr(r, "data", None) or {}).items()})
    return out


EXC_HEAD, EXC_TAIL = 1500, 4500


def _exc(r: logging.LogRecord) -> str | None:
    """Traceback tersaring. Dipotong dari TENGAH (awal + akhir dipertahankan): baris galat sebenarnya ada di akhir dan paling dibutuhkan."""
    if not r.exc_info:
        return None
    # pembungkus anyio (ExceptionGroup/EndOfStream) hanya noise: jangan ikuti rantainya bila galat asli dibungkus
    chain = not isinstance(getattr(r.exc_info[1], "__cause__", None), BaseExceptionGroup)
    t = redact("".join(traceback.format_exception(*r.exc_info, chain=chain)))  # saring dulu, baru potong: potongan tak bisa membelah data pribadi
    return t if len(t) <= EXC_HEAD + EXC_TAIL else t[:EXC_HEAD] + "\n…[dipotong]…\n" + t[-EXC_TAIL:]


class JsonFormatter(logging.Formatter):
    def format(self, r: logging.LogRecord) -> str:
        doc = {"ts": datetime.fromtimestamp(r.created, timezone.utc).isoformat(timespec="milliseconds"), "level": r.levelname, "logger": r.name,
               "msg": _text(r, r.getMessage()), "request_id": REQUEST_ID.get(), **_fields(r)}
        if e := _exc(r):
            doc["exc"] = e
        return json.dumps(doc, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def format(self, r: logging.LogRecord) -> str:
        f = _fields(r)
        extra = " ".join(f"{k}={v}" for k, v in f.items() if k != "event")
        head = f"{datetime.fromtimestamp(r.created):%H:%M:%S} {r.levelname:7} [{REQUEST_ID.get() or '-'}] {r.name}: {_text(r, r.getMessage())}"
        return head + (f" {extra}" if extra else "") + (f"\n{_exc(r)}" if r.exc_info else "")


def setup_logging() -> None:
    """Idempoten. Semua log (termasuk uvicorn) lewat satu formatter yang menyaring data pribadi; log akses uvicorn dimatikan (diganti log permintaan sendiri)."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    fmt = (settings.log_format or ("json" if settings.env == "prod" else "text")).lower()
    h = next((x for x in root.handlers if getattr(x, "_dospem", False)), None)
    if h is None:
        h = logging.StreamHandler(sys.stdout)
        h._dospem = True  # type: ignore[attr-defined]
        root.addHandler(h)
    h.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers, lg.propagate = [], True
    acc = logging.getLogger("uvicorn.access")
    acc.handlers, acc.propagate, acc.disabled = [], False, True
    logging.captureWarnings(True)  # warnings.warn(...) ikut lewat formatter (JSON & tersaring), bukan stderr mentah yang mencemari log mesin
    for noisy in ("httpx", "httpcore", "urllib3"):  # httpx mencatat URL LENGKAP (termasuk query: kata kunci pencarian, dll.) pada level INFO
        logging.getLogger(noisy).setLevel(logging.WARNING)


def event(name: str, level: str = "info", **fields) -> None:
    """Peristiwa terstruktur (mis. login_failed). Hanya nilai sederhana; JANGAN kirim email, teks pengguna, atau token (akan disaring, tapi jangan bergantung padanya)."""
    getattr(log, level)(name, extra={"event": name, "data": fields})


def event_throttled(name: str, level: str = "warning", interval: int = 60, key: str = "", **fields) -> None:
    """Seperti event(), tetapi paling sering sekali per `interval` detik per (name, key): untuk kondisi yang bisa terjadi di setiap permintaan."""
    now, k = time.monotonic(), (name, key)
    if now - _last.get(k, -1e9) >= interval:
        _last[k] = now
        event(name, level, **fields)


def llm_error(kind: str, e: BaseException) -> None:
    """Catat kegagalan LLM tanpa isi permintaan: jenis, kelas galat, dan kode HTTP penyedia (mis. 401 kunci salah, 429 batas penyedia)."""
    status = getattr(getattr(e, "response", None), "status_code", None)
    event("llm_error", "warning", kind=kind, exc=type(e).__name__, status=status)


def redis_down(where: str) -> None:
    event_throttled("redis_unavailable", "error", 60, key=where, where=where)


# ---------- middleware permintaan ----------
async def request_context(request, call_next):
    """ID permintaan (X-Request-ID, aman-dipakai), log permintaan (tanpa query/header/IP), dan 500 yang rapi dengan kode rujukan."""
    rid = request.headers.get("x-request-id", "")
    rid = rid if RID_OK.match(rid) else uuid.uuid4().hex[:16]
    tok = REQUEST_ID.set(rid)
    _tag(rid)
    path, t0 = norm_path(request.url.path), time.perf_counter()
    try:
        try:
            resp = await call_next(request)
        except Exception as e:
            e = _leaf(e)  # BaseHTTPMiddleware membungkus galat dalam ExceptionGroup; log & Sentry cukup galat aslinya
            log.error("unhandled_exception", exc_info=(type(e), e, e.__traceback__), extra={"event": "unhandled_exception", "data": {"method": request.method, "path": path, "exc": type(e).__name__}})
            _capture(e)
            resp = JSONResponse({"detail": "Terjadi kesalahan di server. Coba lagi; jika berulang, sebutkan kode ini ke admin.", "request_id": rid}, status_code=500)
        ms = round((time.perf_counter() - t0) * 1000)
        resp.headers["X-Request-ID"] = rid
        level = "error" if resp.status_code >= 500 else "warning" if ms >= settings.slow_request_ms else "info"
        if not (path == "/healthz" and resp.status_code == 200):
            event("request", level, method=request.method, path=path, status=resp.status_code, ms=ms)
        return resp
    finally:
        REQUEST_ID.reset(tok)


def _leaf(e: BaseException) -> BaseException:
    while isinstance(e, BaseExceptionGroup) and len(e.exceptions) == 1:
        e = e.exceptions[0]
    return e


# ---------- Sentry (opsional) ----------
def _strip_url(url: str | None) -> str | None:
    if not url:
        return None
    u = urlsplit(url)
    return f"{u.scheme}://{u.netloc}{norm_path(u.path)}"  # tanpa query & fragment; id numerik dinormalkan


def scrub_breadcrumb(crumb, hint=None):
    crumb.pop("data", None)
    if "message" in crumb:
        crumb["message"] = redact(crumb["message"])
    return crumb


def scrub_event(event_, hint=None):
    """Sebelum dikirim ke Sentry: buang isi permintaan, header, cookie, query, pengguna, variabel lokal, dan data tambahan; saring teks."""
    if req := event_.get("request"):
        event_["request"] = {k: v for k, v in {"method": req.get("method"), "url": _strip_url(req.get("url"))}.items() if v}
    for key in ("user", "extra"):
        event_.pop(key, None)
    for v in (event_.get("exception") or {}).get("values", []):
        v["value"] = redact(v.get("value"))
        for fr in (v.get("stacktrace") or {}).get("frames", []):
            fr.pop("vars", None)
    for key in ("message",):
        if event_.get(key):
            event_[key] = redact(event_[key])
    if le := event_.get("logentry"):
        event_["logentry"] = {k: redact(x) for k, x in le.items() if isinstance(x, str)}
    for b in (event_.get("breadcrumbs") or {}).get("values", []):
        scrub_breadcrumb(b)
    return event_


def init_sentry(**overrides) -> bool:
    if not settings.sentry_dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        log.warning("SENTRY_DSN diisi tetapi paket sentry-sdk tidak terpasang; pelaporan error ke Sentry tidak aktif.")
        return False
    opts = dict(dsn=settings.sentry_dsn, environment=settings.env, release=settings.app_release or None, send_default_pii=False,
                max_request_body_size="never", include_local_variables=False, traces_sample_rate=settings.sentry_traces_sample_rate,
                before_send=scrub_event, before_send_transaction=scrub_event, before_breadcrumb=scrub_breadcrumb,
                integrations=[LoggingIntegration(level=logging.INFO, event_level=None)])  # log hanya jadi jejak (breadcrumb); error dilaporkan eksplisit, tanpa dobel
    sentry_sdk.init(**{**opts, **overrides})
    return True


def _tag(rid: str) -> None:
    """Hubungkan event Sentry dengan baris log lewat request_id."""
    try:
        import sentry_sdk
        if sentry_sdk.get_client().is_active():
            sentry_sdk.set_tag("request_id", rid)
    except Exception:
        pass


def _capture(e: BaseException) -> None:
    try:
        import sentry_sdk
        if sentry_sdk.get_client().is_active():
            sentry_sdk.capture_exception(e)
    except Exception:  # pelaporan tidak boleh mengganggu respons
        pass
