import os
import pathlib
import tempfile
import uuid

os.environ.update({"DATABASE_URL": os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tempfile.mkdtemp()}/test.db", "ADMIN_EMAILS": "admin@test.id", "FREE_DAILY_QUOTA": "2",
                   "LLM_PROVIDER": "mock", "PAYMENT_PROVIDER": "mock", "MIDTRANS_SERVER_KEY": "sk", "ENV": "dev", "REDIS_URL": "",
                   "RATE_LIMIT_ENABLED": "false", "REVISION_MIN_MINUTES": "0"})
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def client():
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean_rate_memory(monkeypatch):
    from app import ratelimit, scholar
    ratelimit._mem.clear()
    scholar._mem.clear()
    for n in ("openalex", "crossref", "doaj", "semanticscholar", "core"):  # tes tidak boleh menyentuh jaringan
        monkeypatch.setattr(scholar, n, lambda *a: [])


def bearer(token):
    return {"Authorization": "Bearer " + token}


@pytest.fixture
def reg(client):
    def _reg(email=None, name="Tes", headers=None):
        email = email or f"{uuid.uuid4().hex[:10]}@test.id"
        r = client.post("/api/auth/register", json={"email": email, "password": "rahasia123", "name": name}, headers=headers or {})
        assert r.status_code == 200, r.text
        return bearer(r.json()["token"]), email
    return _reg


@pytest.fixture(scope="session")
def admin(client):
    r = client.post("/api/auth/register", json={"email": "admin@test.id", "password": "rahasia123", "name": "Admin"})
    assert r.status_code == 200, r.text
    return bearer(r.json()["token"])
