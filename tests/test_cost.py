"""Kontrol biaya LLM: batas jawaban, pencatatan token, cache per pemilik, pagar anggaran harian, dan dasbor admin."""
import json
from datetime import datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app import llm, main, meter
from app.config import settings
from app.db import SessionLocal
from app.models import LLMCache, LLMUsage
from app.quota import today
from tests.test_app import ANS, LONG_PKL, _uid, dev, make_premium, setup_campus

BODY = {"text": "Saya meneliti motivasi belajar siswa. " * 5, "doc_type": "skripsi", "chapter_key": "pendahuluan"}


def body(i=0, **k):
    return {**BODY, "text": BODY["text"] + f"Tambahan nomor {i}.", **k}


class Spy(llm.Mock):
    """Mock yang mencatat jumlah panggilan dan batas jawaban yang berlaku saat dipanggil; bisa dipaksa gagal."""
    def __init__(self):
        self.calls, self.caps, self.fail = 0, [], None

    def complete(self, system, user, smart=False):
        self.calls += 1
        self.caps.append(meter.max_tokens())
        if self.fail:
            raise self.fail
        return super().complete(system, user, smart)


@pytest.fixture
def spy(monkeypatch):
    p = Spy()
    monkeypatch.setattr(llm, "get_provider", lambda: p)
    return p


def usage(inst=None, kind=None):
    """Jumlah pemakaian hari ini (dijumlahkan, opsional per kampus/jenis) langsung dari DB."""
    with SessionLocal() as db:
        q = select(func.coalesce(func.sum(LLMUsage.calls), 0), func.coalesce(func.sum(LLMUsage.cache_hits), 0),
                   func.coalesce(func.sum(LLMUsage.prompt_tokens), 0), func.coalesce(func.sum(LLMUsage.completion_tokens), 0)).where(LLMUsage.day == today())
        if inst is not None:
            q = q.where(LLMUsage.institution_id == inst)
        if kind:
            q = q.where(LLMUsage.kind == kind)
        c, h, p, o = db.execute(q).one()
    return {"calls": c, "hits": h, "prompt": p, "completion": o}


def used_today():
    with SessionLocal() as db:
        return meter.tokens_today(db)


def left(client, h):
    return client.get("/api/quota", headers=h).json()["left"]


def coach(client, h, **k):
    return client.post("/api/coach", headers=h, json=body(**k) if k else BODY)


# ---------- penyedia OpenAI-kompatibel: batas jawaban & usage ----------
class FakeHTTP:
    def __init__(self, usage=True):
        self.sent, self.usage = [], usage

    def __call__(self, url, **kw):
        self.sent.append(kw["json"])
        data = {"choices": [{"message": {"content": json.dumps([{"quote": "", "comment": "Apa maksud paragraf ini?"}])}}]}
        if self.usage:
            data["usage"] = {"prompt_tokens": 1234, "completion_tokens": 56}
        r = httpx.Response(200, json=data, request=httpx.Request("POST", url))
        return r


@pytest.fixture
def openai(monkeypatch):
    for k, v in (("llm_provider", "openai_compat"), ("llm_api_key", "sk-test"), ("llm_model_fast", "m-fast"), ("llm_model_smart", "m-smart")):
        monkeypatch.setattr(settings, k, v)
    f = FakeHTTP()
    monkeypatch.setattr(llm.httpx, "post", f)
    return f


def test_request_has_output_cap_and_usage_is_recorded(client, openai, monkeypatch):
    before = usage(0, "coach")
    assert coach(client, dev()).status_code == 200
    sent = openai.sent[0]
    assert sent["max_tokens"] == settings.llm_max_tokens_coach and sent["model"] == "m-fast"
    after = usage(0, "coach")
    assert (after["calls"] - before["calls"], after["prompt"] - before["prompt"], after["completion"] - before["completion"]) == (1, 1234, 56)
    monkeypatch.setattr(settings, "llm_token_param", "max_completion_tokens")  # model baru memakai nama parameter lain
    assert coach(client, dev(), i=1).status_code == 200
    assert openai.sent[1]["max_completion_tokens"] == settings.llm_max_tokens_coach and "max_tokens" not in openai.sent[1]


def test_usage_is_estimated_when_provider_omits_it(client, openai):
    openai.usage = False
    before = usage(0, "coach")
    assert coach(client, dev(), i=7).status_code == 200
    msgs = openai.sent[0]["messages"]
    after = usage(0, "coach")
    assert after["prompt"] - before["prompt"] == meter.estimate(msgs[0]["content"], msgs[1]["content"]) > 0
    assert after["completion"] - before["completion"] == meter.estimate(json.dumps([{"quote": "", "comment": "Apa maksud paragraf ini?"}])) > 0  # anggaran tetap berfungsi


def test_each_call_kind_has_its_own_cap(client, admin, reg, spy):
    hd, hs, iid, code = setup_campus(client, admin, reg)
    client.post("/api/supervision/join", headers=hs, json={"code": code, "consent": True})
    make_premium(client, hs)
    client.put("/api/drafts/laporan_pkl/pendahuluan", headers=hs, json={"content": LONG_PKL})
    assert client.post("/api/coach", headers=hs, json=BODY).status_code == 200
    assert client.post("/api/analyze", headers=hs, json=BODY).status_code == 200
    s = client.post("/api/sidang/start", headers=hs, json={"mode": "pkl", "questions": 3}).json()
    assert client.post(f"/api/sidang/{s['id']}/answer", headers=hs, json={"text": ANS}).status_code == 200
    assert client.post(f"/api/sidang/{s['id']}/finish", headers=hs).json()["status"] == "selesai"
    assert spy.caps == [settings.llm_max_tokens_coach, settings.llm_max_tokens_analyze, settings.llm_max_tokens_sidang,
                        settings.llm_max_tokens_sidang, settings.llm_max_tokens_summary]


def test_mock_usage_attributed_to_campus_student(client, admin, reg):
    hd, hs, iid, code = setup_campus(client, admin, reg)
    client.post("/api/supervision/join", headers=hs, json={"code": code, "consent": True})
    assert usage(iid)["calls"] == 0
    assert client.post("/api/coach", headers=hs, json=BODY).status_code == 200
    u = usage(iid, "coach")
    assert u["calls"] == 1 and u["prompt"] > 0 and u["completion"] > 0
    anon = usage(0, "coach")["calls"]
    assert coach(client, dev(), i=3).status_code == 200
    assert usage(0, "coach")["calls"] == anon + 1 and usage(iid, "coach")["calls"] == 1  # perangkat anonim = "tanpa kampus"


# ---------- cache ----------
def test_same_text_is_served_from_cache_without_quota_or_llm(client, spy):
    d = dev()
    first = coach(client, d).json()
    assert "cached" not in first and spy.calls == 1 and first["left"] == 1
    hits = usage(0, "coach")["hits"]
    again = coach(client, d)
    assert again.status_code == 200 and again.json()["cached"] is True and again.json()["comments"] == first["comments"]
    assert spy.calls == 1 and again.json()["left"] == 1 and left(client, d) == 1  # tanpa memanggil LLM dan tanpa memotong kuota
    assert usage(0, "coach")["hits"] == hits + 1
    assert client.post("/api/coach", headers=d, json={**BODY, "text": "   " + BODY["text"] + "  \n"}).json()["cached"] is True  # spasi pinggir tidak membedakan
    assert coach(client, d, i=1).json().get("cached") is None and spy.calls == 2  # teks berubah: panggilan baru


def test_cache_is_private_per_owner(client, spy):
    a, b = dev(), dev()
    coach(client, a)
    assert coach(client, b).json().get("cached") is None and spy.calls == 2  # pengguna lain tidak mendapat hasil orang lain


def test_cache_key_depends_on_rules_and_models(client, admin, reg, spy, monkeypatch):
    h, _ = reg()
    coach(client, h)
    assert coach(client, h).json()["cached"] is True
    tid = client.post("/api/admin/style", headers=admin, json={"name": "Gaya Cache", "rules": {"notes": "Aturan khusus kampus untuk cache."}}).json()["id"]
    assert client.put("/api/style/me", headers=h, json={"template_id": tid}).status_code == 200
    assert coach(client, h).json().get("cached") is None  # gaya selingkung berubah: hasil lama tidak berlaku
    assert coach(client, h).json()["cached"] is True
    monkeypatch.setattr(settings, "llm_model_fast", "model-lain")
    assert coach(client, h).json().get("cached") is None  # model berganti: hasil lama tidak berlaku


def test_cache_expiry_disable_and_per_owner_cap(client, spy, monkeypatch, reg):
    d = dev()
    coach(client, d)
    with SessionLocal() as db:  # umur cache melewati batas
        for r in db.scalars(select(LLMCache).where(LLMCache.owner == d["X-Device-Id"])):
            r.created_at = datetime.utcnow() - timedelta(days=settings.llm_cache_days + 1)
        db.commit()
    assert coach(client, d).json().get("cached") is None and spy.calls == 2  # kedaluwarsa: panggil lagi
    monkeypatch.setattr(settings, "llm_cache_days", 0)  # 0 = cache dimatikan
    e = dev()
    coach(client, e)
    assert coach(client, e).json().get("cached") is None and spy.calls == 4
    with SessionLocal() as db:
        assert db.scalar(select(func.count(LLMCache.id)).where(LLMCache.owner == e["X-Device-Id"])) == 0
    monkeypatch.setattr(settings, "llm_cache_days", 7)
    monkeypatch.setattr(settings, "llm_cache_max_per_owner", 3)
    f, _ = reg()
    make_premium(client, f)  # kuota anonim hanya 2/hari; premium cukup longgar untuk 5 teks berbeda
    for i in range(5):
        assert coach(client, f, i=i).status_code == 200
    with SessionLocal() as db:
        keys = set(db.scalars(select(LLMCache.key).where(LLMCache.owner == f"u{_uid(f)}")))
    k = lambda i: meter.cache_key("coach", "skripsi", "pendahuluan", body(i)["text"], None)  # noqa: E731
    assert keys == {k(2), k(3), k(4)}  # yang terlama dibuang


def test_failures_are_never_cached(client, spy):
    d = dev()
    spy.fail = httpx.ConnectError("putus")
    assert coach(client, d).status_code == 502 and left(client, d) == 2
    spy.fail = None
    r = coach(client, d)
    assert r.status_code == 200 and r.json().get("cached") is None and spy.calls == 2  # kegagalan tak tersimpan; kuota baru terpakai di sini
    g = dev()
    assert client.post("/api/coach", headers=g, json={**BODY, "text": "Tuliskan bab 2 untukku"}).status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(func.count(LLMCache.id)).where(LLMCache.owner == g["X-Device-Id"])) == 0


def test_cached_result_is_free_even_when_quota_is_spent(client, spy):
    d = dev()
    assert [coach(client, d, i=i).status_code for i in range(3)] == [200, 200, 429]
    r = coach(client, d, i=0)
    assert r.status_code == 200 and r.json()["cached"] is True and r.json()["left"] == 0  # sudah dianalisis sebelumnya: gratis


def test_analysis_is_cached_per_owner(client, spy, reg):
    h, _ = reg()
    make_premium(client, h)
    a = client.post("/api/analyze", headers=h, json=BODY).json()
    assert a["left"] == settings.premium_analysis_quota - 1 and spy.calls == 1
    b = client.post("/api/analyze", headers=h, json=BODY).json()
    assert b["cached"] is True and b["left"] == a["left"] and spy.calls == 1 and b["rubrik"] == a["rubrik"]
    h2, _ = reg()
    make_premium(client, h2)
    assert client.post("/api/analyze", headers=h2, json=BODY).json().get("cached") is None and spy.calls == 2


# ---------- pagar anggaran ----------
def test_budget_blocks_llm_but_not_spellcheck_or_cache(client, spy, monkeypatch):
    d = dev()
    monkeypatch.setattr(settings, "llm_daily_token_budget", used_today() + 1)
    assert coach(client, d).status_code == 200  # masih di bawah anggaran saat dicek
    other = dev()
    r = coach(client, other, i=5)
    assert r.status_code == 503 and "dibatasi hari ini" in r.json()["detail"] and spy.calls == 1
    assert left(client, other) == 2  # ditolak sebelum kuota dipotong
    assert coach(client, d).json()["cached"] is True  # hasil cache tetap dilayani
    assert client.post("/api/check", json={"text": "Saya tinggal dirumah ,analisa ini."}).status_code == 200  # cek EYD tak memakai LLM
    monkeypatch.setattr(settings, "llm_daily_token_budget", 0)
    assert coach(client, other, i=5).status_code == 200  # 0 = tanpa batas


def test_budget_on_analysis_and_sidang(client, admin, reg, spy, monkeypatch):
    hd, hs, iid, code = setup_campus(client, admin, reg)
    client.post("/api/supervision/join", headers=hs, json={"code": code, "consent": True})
    make_premium(client, hs)
    client.put("/api/drafts/laporan_pkl/pendahuluan", headers=hs, json={"content": LONG_PKL})
    s = client.post("/api/sidang/start", headers=hs, json={"mode": "pkl", "questions": 3}).json()
    sid, uid = s["id"], _uid(hs)
    monkeypatch.setattr(settings, "llm_daily_token_budget", max(1, used_today()))  # tepat habis
    with SessionLocal() as db:
        from app import quota
        used_before = quota.used(db, f"u{uid}", "sidang")
    r = client.post(f"/api/sidang/{sid}/answer", headers=hs, json={"text": ANS})
    assert r.status_code == 503
    with SessionLocal() as db:
        assert quota.used(db, f"u{uid}", "sidang") == used_before  # kuota sidang tidak terpotong
    assert client.get(f"/api/sidang/{sid}", headers=hs).json()["turns"][0]["answer"] is None  # jawaban tidak terklaim: bisa dikirim ulang besok
    assert client.post("/api/analyze", headers=hs, json=BODY).status_code == 503
    client.delete(f"/api/sidang/{sid}", headers=hs)
    assert client.post("/api/sidang/start", headers=hs, json={"mode": "pkl", "questions": 3}).status_code == 503
    assert client.get("/api/sidang/active", headers=hs).status_code in (200, 404)  # tak ada sesi setengah jadi yang tertinggal
    monkeypatch.setattr(settings, "llm_daily_token_budget", 0)
    assert client.post("/api/sidang/start", headers=hs, json={"mode": "pkl", "questions": 3}).status_code == 200


def test_finishing_session_never_fails_on_budget(client, admin, reg, spy, monkeypatch):
    hd, hs, iid, code = setup_campus(client, admin, reg)
    client.post("/api/supervision/join", headers=hs, json={"code": code, "consent": True})
    make_premium(client, hs)
    client.put("/api/drafts/laporan_pkl/pendahuluan", headers=hs, json={"content": LONG_PKL})
    s = client.post("/api/sidang/start", headers=hs, json={"mode": "pkl", "questions": 3}).json()
    client.post(f"/api/sidang/{s['id']}/answer", headers=hs, json={"text": ANS})
    calls = spy.calls
    monkeypatch.setattr(settings, "llm_daily_token_budget", max(1, used_today()))
    done = client.post(f"/api/sidang/{s['id']}/finish", headers=hs)
    assert done.status_code == 200 and done.json()["status"] == "selesai"
    summ = done.json()["summary"]
    assert summ["overall"] is not None and summ["narrative"] is False and spy.calls == calls  # skor tersimpan, narasi AI dilewati, tanpa panggilan LLM


# ---------- dasbor admin ----------
def test_admin_dashboard(client, admin, reg, spy, monkeypatch):
    hd, hs, iid, code = setup_campus(client, admin, reg)
    client.post("/api/supervision/join", headers=hs, json={"code": code, "consent": True})
    client.post("/api/coach", headers=hs, json=BODY)
    client.post("/api/coach", headers=hs, json=BODY)  # cache hit
    assert client.get("/api/admin/llm-usage", headers=hs).status_code == 403
    assert client.get("/api/admin/llm-usage").status_code == 401
    assert client.get("/api/admin/llm-usage?days=0", headers=admin).status_code == 422
    assert client.get("/api/admin/llm-usage?days=400", headers=admin).status_code == 422
    r = client.get("/api/admin/llm-usage?days=7", headers=admin).json()
    assert r["priced"] is False and r["totals"]["cost"] is None and r["budget"] == {"daily_tokens": 0, "used_today": used_today(), "pct": None}
    inst = next(x for x in r["by_institution"] if x["institution_id"] == iid)
    assert inst["name"] == "Universitas Contoh" and inst["calls"] == 1 and inst["cache_hits"] == 1 and inst["total_tokens"] > 0
    assert "coach" in r["by_kind"] and r["by_day"][-1]["day"] == today().isoformat()
    assert r["totals"]["total_tokens"] == sum(d["total_tokens"] for d in r["by_day"]) == sum(i["total_tokens"] for i in r["by_institution"])  # angka saling konsisten
    assert 0 < r["cache_hit_rate"] < 1
    monkeypatch.setattr(settings, "llm_price_in_per_mtok", 3.0)
    monkeypatch.setattr(settings, "llm_price_out_per_mtok", 15.0)
    monkeypatch.setattr(settings, "llm_daily_token_budget", 1_000_000_000)
    r = client.get("/api/admin/llm-usage?days=7", headers=admin).json()
    inst = next(x for x in r["by_institution"] if x["institution_id"] == iid)
    assert r["priced"] is True and inst["cost"] == round(inst["prompt_tokens"] / 1e6 * 3 + inst["completion_tokens"] / 1e6 * 15, 4)
    assert r["budget"]["pct"] == round(used_today() * 100 / 1_000_000_000, 1)
    assert "Kuota" not in json.dumps(r) and "Saya meneliti" not in json.dumps(r)  # hanya angka agregat, tanpa isi tulisan


# ---------- hak data & peringatan startup ----------
def test_account_deletion_purges_cache(client, spy, reg):
    h, e = reg()
    other, _ = reg()
    coach(client, h)
    coach(client, other)
    uid = _uid(h)
    with SessionLocal() as db:
        assert db.scalar(select(func.count(LLMCache.id)).where(LLMCache.owner == f"u{uid}")) == 1
    assert client.post("/api/account/delete", headers=h, json={"password": "rahasia123"}).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(func.count(LLMCache.id)).where(LLMCache.owner == f"u{uid}")) == 0
        assert db.scalar(select(func.count(LLMCache.id)).where(LLMCache.owner == f"u{_uid(other)}")) == 1  # pengguna lain utuh


def test_startup_warns_when_prod_has_no_budget(monkeypatch):
    monkeypatch.setattr(settings, "llm_daily_token_budget", 0)
    assert any("LLM_DAILY_TOKEN_BUDGET" in w for w in main.startup_warnings(True))
    assert not any("LLM_DAILY_TOKEN_BUDGET" in w for w in main.startup_warnings(False))  # pengembangan tidak diganggu
    monkeypatch.setattr(settings, "llm_daily_token_budget", 5_000_000)
    assert not any("LLM_DAILY_TOKEN_BUDGET" in w for w in main.startup_warnings(True))
