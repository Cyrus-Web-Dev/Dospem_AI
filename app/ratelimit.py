"""Rate limit per IP (jendela tetap) untuk endpoint sensitif. Redis bila ada; fallback memori (1 proses)."""
import re
import time

import redis
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from . import obs
from .config import settings

_r = None
_mem: dict = {}
RULES = {  # (metode, path): (maks permintaan, detik)
    ("POST", "/api/auth/login"): (10, 60),
    ("POST", "/api/auth/register"): (5, 60),
    ("POST", "/api/coach"): (10, 60),
    ("POST", "/api/analyze"): (6, 60),
    ("POST", "/api/upload"): (10, 60),
    ("POST", "/api/review"): (20, 60),
    ("POST", "/api/review/section"): (30, 60),
    ("GET", "/api/examples/search"): (20, 60),
    ("GET", "/api/refs/lookup"): (10, 60),
    ("POST", "/api/export/docx"): (6, 60),
    ("POST", "/api/export/logbook"): (6, 60),
    ("POST", "/api/readiness"): (30, 60),
    ("GET", "/api/progress"): (60, 60),
    ("POST", "/api/auth/password"): (5, 60),
    ("POST", "/api/auth/forgot"): (3, 60),
    ("POST", "/api/auth/reset"): (5, 60),
    ("POST", "/api/account/delete"): (5, 60),
    ("GET", "/api/account/export"): (3, 60),
    ("POST", "/api/dosen/students/{id}/notes"): (30, 60),
    ("POST", "/api/sidang/start"): (5, 60),
    ("POST", "/api/sidang/{id}/answer"): (12, 60),
    ("POST", "/api/sidang/{id}/finish"): (10, 60),
    ("POST", "/api/pay/checkout"): (5, 60),
    ("POST", "/api/supervision/join"): (10, 60),
    ("GET", "/api/supervision/preview"): (20, 60),
}


def redis_client():
    global _r
    if settings.redis_url and _r is None:
        _r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _r


def hit(key: str, window: int) -> int:
    r = redis_client()
    if r:
        p = r.pipeline()
        p.incr(key)
        p.expire(key, window, nx=True)
        return p.execute()[0]
    now = time.time()
    if len(_mem) > 10000:
        for k in [k for k, (_, e) in _mem.items() if e < now]:
            del _mem[k]
    c, exp = _mem.get(key, (0, 0))
    if now > exp:
        c, exp = 0, now + window
    _mem[key] = (c + 1, exp)
    return c + 1


from .obs import norm_path  # noqa: E402,F401  (dipindah ke obs; tetap bisa diimpor dari sini)


class Limiter(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = norm_path(request.url.path)
        rule = RULES.get((request.method, path)) if settings.rate_limit_enabled else None
        if rule:
            ip = request.client.host if request.client else "?"
            try:
                n = await run_in_threadpool(hit, f"rl:{path}:{ip}", rule[1])
            except Exception:  # Redis mati: jangan jatuhkan layanan (tetapi jangan diam: batas laju tidak berlaku selama ini)
                obs.redis_down("ratelimit")
                n = 0
            if n > rule[0]:
                obs.event_throttled("rate_limited", "warning", 30, key=path, path=path)
                return JSONResponse({"detail": "Terlalu banyak permintaan. Tunggu sebentar lalu coba lagi."}, 429,
                                    headers={"Retry-After": str(rule[1])})
        return await call_next(request)
