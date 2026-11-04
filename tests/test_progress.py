"""Status progres manusiawi: Draft -> Layak bimbingan -> Ada catatan dosen -> Siap sidang."""
from tests.test_app import dev, setup_campus

GOOD = ("Penelitian ini membahas motivasi belajar siswa di sekolah menengah pertama negeri. " * 20).strip()  # ~260 kata, layak & terisi
SHORT = "Baru mulai menulis latar belakang masalah penelitian ini."
CH = ["pendahuluan", "tinjauan", "metode", "hasil", "penutup"]


def prog(client, h, doc="skripsi"):
    r = client.get(f"/api/progress?doc_type={doc}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def put(client, h, ck, text, doc="skripsi"):
    assert client.put(f"/api/drafts/{doc}/{ck}", headers=h, json={"content": text}).status_code == 200


def test_stages_progress_for_anonymous_device(client):
    d = dev()
    p = prog(client, d)
    assert p["stage"] == {"key": None, "label": "Belum mulai", "index": 0} and "Mulai dari bab" in p["next"]
    assert [s["label"] for s in p["stages"]] == ["Draft", "Layak bimbingan", "Ada catatan dosen", "Siap sidang"]
    assert all(c["state"] == "belum" and c["words"] == 0 for c in p["chapters"])
    put(client, d, "pendahuluan", SHORT)
    p = prog(client, d)
    assert p["stage"]["key"] == "draft" and p["stage"]["index"] == 1 and p["chapters"][0]["state"] == "draf"
    assert "Lanjutkan bab" in p["next"]
    put(client, d, "pendahuluan", GOOD)
    p = prog(client, d)
    assert p["stage"]["key"] == "layak" and p["stage"]["index"] == 2 and p["chapters"][0]["state"] == "layak"
    assert "Hubungkan dosen pembimbingmu" in p["next"] and p["has_supervisor"] is False  # belum terhubung: diarahkan menghubungkan dosen
    assert [c["state"] for c in p["chapters"][1:]] == ["belum"] * 4


def test_placeholder_blocks_layak_and_validation(client):
    d = dev()
    put(client, d, "pendahuluan", GOOD + " [isi latar belakang masalah]")
    assert prog(client, d)["chapters"][0]["state"] == "draf"  # isian templat belum diganti: belum layak
    assert client.get("/api/progress?doc_type=ngawur", headers=d).status_code == 404
    assert client.get("/api/progress").status_code == 400  # tanpa identitas


def test_progress_is_per_owner(client):
    a, b = dev(), dev()
    put(client, a, "pendahuluan", GOOD)
    assert prog(client, a)["stage"]["key"] == "layak" and prog(client, b)["stage"]["key"] is None


def test_notes_stage_scoping_and_unread(client, admin, reg):
    hd, hs, iid, code = setup_campus(client, admin, reg, GOOD)
    client.post("/api/supervision/join", headers=hs, json={"code": code, "consent": True})
    sid = client.get("/api/dosen/students", headers=hd).json()[0]["student"]["id"]
    p = prog(client, hs)
    assert p["stage"]["key"] == "layak" and p["has_supervisor"] is True and "Dosenmu bisa membuka" in p["next"]
    url = f"/api/dosen/students/{sid}/notes"
    client.post(url, headers=hd, json={"body": "Catatan untuk proposal.", "doc_type": "proposal"})
    client.post(url, headers=hd, json={"body": "Logbook tidak dihitung.", "kind": "logbook"})
    assert prog(client, hs)["stage"]["key"] == "layak"  # catatan jenis tugas lain & logbook tidak mengubah tahap skripsi
    n = client.post(url, headers=hd, json={"body": "Perjelas rumusan masalah."}).json()  # tanpa doc_type = berlaku umum
    p = prog(client, hs)
    assert p["stage"]["key"] == "catatan" and p["stage"]["index"] == 3 and p["notes_unread"] == 1 and "1 catatan baru" in p["next"]
    assert prog(client, hs, "proposal")["stage"]["key"] == "catatan" and prog(client, hs, "proposal")["notes_unread"] == 2  # umum + khusus proposal
    client.post(f"/api/notes/{n['id']}/read", headers=hs)
    p = prog(client, hs)
    assert p["stage"]["key"] == "catatan" and p["notes_unread"] == 0 and "Revisi sesuai catatan" in p["next"]


def test_siap_sidang_matches_dosen_dashboard(client, admin, reg):
    hd, hs, iid, code = setup_campus(client, admin, reg)
    client.post("/api/supervision/join", headers=hs, json={"code": code, "consent": True})
    for c in CH[:-1]:
        put(client, hs, c, GOOD)
    assert prog(client, hs)["stage"]["key"] == "layak"
    assert "siap_sidang" not in client.get("/api/dosen/students", headers=hd).json()[0]["attention"]
    put(client, hs, CH[-1], GOOD)
    p = prog(client, hs)
    assert p["stage"] == {"key": "siap", "label": "Siap sidang", "index": 4} and "Mode Sidang" in p["next"] and "dosen penguji" in p["next"]
    assert "siap_sidang" in client.get("/api/dosen/students", headers=hd).json()[0]["attention"]  # definisi sama dengan sisi dosen
    sid = client.get("/api/dosen/students", headers=hd).json()[0]["student"]["id"]
    client.post(f"/api/dosen/students/{sid}/notes", headers=hd, json={"body": "Catatan."})
    assert prog(client, hs)["stage"]["key"] == "siap"  # siap tetap mengalahkan catatan


def test_article_labels_and_campus_min_words(client, admin, reg):
    h, _ = reg()
    for c in client.get("/api/roadmap/jurnal", headers=h).json():
        put(client, h, c["key"], GOOD, "jurnal")
    p = prog(client, h, "jurnal")
    assert p["stage"]["label"] == "Siap submit" and p["stages"][3]["label"] == "Siap submit" and "submit" in p["next"] and "Sidang" not in p["next"]
    tid = client.post("/api/admin/style", headers=admin, json={"name": "Ketat", "rules": {"chapters": {"pendahuluan": {"min_words": 5000}}}}).json()["id"]
    h2, _ = reg()
    put(client, h2, "pendahuluan", GOOD)
    assert prog(client, h2)["chapters"][0]["state"] == "layak"
    assert client.put("/api/style/me", headers=h2, json={"template_id": tid}).status_code == 200
    assert prog(client, h2)["chapters"][0]["state"] == "draf"  # ambang kampus ikut menentukan "layak"


def test_layak_is_not_the_same_as_siap_boundary(client, admin, reg):
    """165 kata: lolos 'layak bimbingan' (>=150) tetapi belum 'terisi' (<200). Semua bab segitu = belum siap sidang, di sisi mahasiswa maupun dosen."""
    mid = ("Penelitian ini membahas motivasi belajar siswa di sekolah menengah pertama negeri. " * 15).strip()
    assert 150 <= len(mid.split()) < 200
    hd, hs, iid, code = setup_campus(client, admin, reg)
    client.post("/api/supervision/join", headers=hs, json={"code": code, "consent": True})
    for c in CH:
        put(client, hs, c, mid)
    p = prog(client, hs)
    assert p["stage"]["key"] == "layak" and all(c["state"] == "layak" for c in p["chapters"])
    assert "siap_sidang" not in client.get("/api/dosen/students", headers=hd).json()[0]["attention"]
    put(client, hs, CH[0], GOOD)  # satu bab terisi, empat lainnya belum: tetap belum siap
    assert prog(client, hs)["stage"]["key"] == "layak"
    for c in CH[1:]:
        put(client, hs, c, GOOD)
    assert prog(client, hs)["stage"]["key"] == "siap"


def test_deleting_sidang_session_leaves_no_turns_and_no_orm_warnings(client, admin, reg):
    """Hapus sesi: giliran dihapus lebih dulu secara eksplisit (urutan ORM tanpa relationship() tidak terjamin, dan di PostgreSQL pernah memicu
    'DELETE expected 1 row, 0 matched')."""
    import warnings
    from sqlalchemy import func, select
    from sqlalchemy.exc import SAWarning
    from app.db import SessionLocal
    from app.models import SidangTurn
    from tests.test_app import ANS, LONG_PKL, make_premium
    h, _ = reg()
    make_premium(client, h)
    client.put("/api/drafts/laporan_pkl/pendahuluan", headers=h, json={"content": LONG_PKL})
    s = client.post("/api/sidang/start", headers=h, json={"mode": "pkl", "questions": 3}).json()
    client.post(f"/api/sidang/{s['id']}/answer", headers=h, json={"text": ANS})  # sesi punya 2 giliran
    with SessionLocal() as db:
        assert db.scalar(select(func.count(SidangTurn.id)).where(SidangTurn.session_id == s["id"])) == 2
    with warnings.catch_warnings():
        warnings.simplefilter("error", SAWarning)
        assert client.delete(f"/api/sidang/{s['id']}", headers=h).json() == {"ok": True}
    with SessionLocal() as db:
        assert db.scalar(select(func.count(SidangTurn.id)).where(SidangTurn.session_id == s["id"])) == 0
    assert client.get(f"/api/sidang/{s['id']}", headers=h).status_code == 404
