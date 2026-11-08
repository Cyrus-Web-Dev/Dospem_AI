import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from . import account, admin, analysis, analytics, auth, bank, bib, campus, examples, export, meter, notes, payments, progress, readiness, assets, revisions, review, sidang, style, upload
from . import obs
from .config import settings
from .db import engine
from .ratelimit import Limiter, redis_client
from .routes import router

PROD = settings.env == "prod"
CSP = ("default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


STATIC = Path(__file__).resolve().parent.parent / "static"


def startup_warnings(prod: bool) -> list[str]:
    """Hal yang tidak menghentikan server tetapi berbahaya dibiarkan di produksi publik."""
    w = []
    if prod and "[ISI:" in (STATIC / "legal.html").read_text(encoding="utf-8"):
        w.append("static/legal.html masih berisi placeholder [ISI: ...]. Lengkapi dan tinjau secara hukum sebelum rilis publik.")
    if prod and not settings.sentry_dsn:
        w.append("SENTRY_DSN kosong: galat produksi hanya terlihat di log. Pasang Sentry (atau pantau log JSON) agar masalah tidak hanya ketahuan dari keluhan pengguna.")
    if prod and settings.sentry_dsn:
        try:
            import sentry_sdk  # noqa: F401
        except ImportError:
            w.append("SENTRY_DSN diisi tetapi paket sentry-sdk tidak terpasang.")
    if prod and settings.llm_daily_token_budget <= 0:
        w.append("LLM_DAILY_TOKEN_BUDGET=0: tidak ada pagar biaya harian untuk LLM. Set angka token per hari agar tagihan tidak bisa membengkak tanpa batas.")
    return w


@asynccontextmanager
async def lifespan(_):
    settings.assert_production_ready()
    for w in startup_warnings(PROD):
        logging.getLogger("uvicorn.error").warning(w)
    yield


obs.setup_logging()
obs.init_sentry()  # sebelum FastAPI dibuat agar integrasinya terpasang
app = FastAPI(title="Dospem", lifespan=lifespan, redoc_url=None,
              docs_url=None if PROD else "/docs", openapi_url=None if PROD else "/openapi.json")
app.add_middleware(Limiter)


@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    resp.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                         "Referrer-Policy": "strict-origin-when-cross-origin", "Content-Security-Policy": CSP})
    if PROD:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp


app.middleware("http")(obs.request_context)  # terakhir didaftarkan = terluar: ID permintaan ada di semua respons, juga 429


@app.get("/healthz")
def healthz():
    try:
        with engine.connect() as c:
            c.execute(text("select 1"))
        if redis_client():
            redis_client().ping()
    except Exception:
        raise HTTPException(503, "tidak sehat")
    return {"ok": True}


for r in (auth.router, account.router, router, examples.router, bib.router, export.router, sidang.router, bank.router, meter.router, notes.router, progress.router, readiness.router, assets.router, revisions.router, review.router, upload.router, payments.router, analysis.router, campus.router, style.router, analytics.router, admin.router):
    app.include_router(r)
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
