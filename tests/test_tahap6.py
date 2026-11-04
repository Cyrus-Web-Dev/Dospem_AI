"""Tahap 6: checklist layak kirim, riwayat revisi, catatan dosen/logbook, dan dasbor 'perlu perhatian'."""
from app.config import settings
from tests.test_app import BIB_A, dev, setup_campus

LONG = ("Penelitian ini membahas motivasi belajar siswa di sekolah menengah pertama negeri. " * 20).strip()
GOOD_URL = "/api/drafts/skripsi/pendahuluan"


def join(client, hs, code):
    assert client.post("/api/supervision/join", headers=hs, json={"code": code, "consent": True}).status_code == 200


def sid_of(client, hd):
    return client.get("/api/dosen/students", headers=hd).json()[0]["student"]["id"]


# ---------- readiness ----------
def test_readiness_empty_short_and_ready(client):
    d = dev()
    body = {"doc_type": "skripsi", "chapter_key": "pendahuluan"}
    r = client.post("/api/readiness", headers=d, json=body).json()  # draf belum ada
    assert r["ready"] is False and r["gaps"][0]["kind"] == "kosong" and r["stats"]["words"] == 0
    r = client.post("/api/readiness", headers=d, json={**body, "text": "Terlalu pendek."}).json()
    assert r["ready"] is False and r["gaps"][0]["kind"] == "pendek" and r["gaps"][0]["need"] == settings.ready_min_words
    r = client.post("/api/readiness", headers=d, json={**body, "text": LONG}).json()
    assert r["ready"] is True and r["gaps"] == [] and len(r["manual"]) == 4
    client.put(GOOD_URL, headers=d, json={"content": LONG})  # tanpa `text`: memakai draf tersimpan
    assert client.post("/api/readiness", headers=d, json=body).json()["ready"] is True


def test_readiness_placeholder_spelling_manual_and_validation(client):
    d, body = dev(), {"doc_type": "skripsi", "chapter_key": "pendahuluan"}
    r = client.post("/api/readiness", headers=d, json={**body, "text": LONG + " [isi latar belakang masalah]"}).json()
    assert r["ready"] is False and [g["kind"] for g in r["gaps"]] == ["placeholder"]
    messy = "Saya tinggal dirumah ,analisa ini banget. " * 40
    kinds = [g["kind"] for g in client.post("/api/readiness", headers=d, json={**body, "text": messy}).json()["gaps"]]
    assert "ejaan" in kinds
    r = client.post("/api/readiness", headers=d, json={**body, "text": LONG, "checked": [0, 1]}).json()
    manual = [g for g in r["gaps"] if g["kind"] == "manual"]
    assert r["ready"] is True and manual[0]["count"] == 2  # manual hanya peringatan, bukan penghalang
    assert client.post("/api/readiness", headers=d, json={**body, "text": LONG, "checked": [-1]}).status_code == 422
    assert client.post("/api/readiness", headers=d, json={"doc_type": "skripsi", "chapter_key": "ngawur"}).status_code == 404
    assert client.post("/api/readiness", json=body).status_code == 400  # tanpa identitas


def test_readiness_uses_campus_min_words_and_bibliography(client, admin, reg):
    h, _ = reg()
    body = {"doc_type": "skripsi", "chapter_key": "pendahuluan", "text": LONG + " Menurut (Wijaya, 2020) hal ini penting."}
    assert client.post("/api/refs", headers=h, json=BIB_A).status_code == 200
    r = client.post("/api/readiness", headers=h, json=body).json()
    assert [g for g in r["gaps"] if g["kind"] == "sitasi"][0]["examples"] == ["(Wijaya, 2020)"]
    assert r["ready"] is True  # sitasi hanya peringatan
    # tanpa pustaka tersimpan: tidak menuduh sitasi hilang
    h2, _ = reg()
    assert "sitasi" not in [g["kind"] for g in client.post("/api/readiness", headers=h2, json=body).json()["gaps"]]
    tid = client.post("/api/admin/style", headers=admin, json={"name": "Ketat", "rules": {"chapters": {"pendahuluan": {"min_words": 5000}}}}).json()["id"]
    assert client.put("/api/style/me", headers=h2, json={"template_id": tid}).status_code == 200
    g = client.post("/api/readiness", headers=h2, json=body).json()["gaps"]
    assert g[0]["kind"] == "pendek" and g[0]["need"] == 5000


# ---------- revisi ----------
def test_revisions_snapshot_diff_and_ownership(client):
    d = dev()
    assert client.get(GOOD_URL + "/revisions", headers=d).status_code == 404  # belum ada draf
    client.put(GOOD_URL, headers=d, json={"content": "Paragraf satu.\n\nParagraf dua."})
    client.put(GOOD_URL, headers=d, json={"content": "Paragraf satu.\n\nParagraf dua."})  # sama: tidak ada versi baru
    client.put(GOOD_URL, headers=d, json={"content": "Paragraf satu diubah.\n\nParagraf dua.\n\nParagraf tiga."})
    revs = client.get(GOOD_URL + "/revisions", headers=d).json()
    assert len(revs) == 2 and revs[0]["id"] > revs[1]["id"]
    old = revs[1]["id"]
    assert client.get(f"{GOOD_URL}/revisions/{old}", headers=d).json()["content"].startswith("Paragraf satu.")
    df = client.get(f"{GOOD_URL}/revisions/{old}/diff", headers=d).json()
    assert (df["changed"], df["added"], df["removed"], df["same"]) == (1, 1, 0, False) and df["words_delta"] > 0
    assert {i["type"] for i in df["items"]} == {"diubah", "ditambah"}
    other = dev()
    client.put(GOOD_URL, headers=other, json={"content": "Milik lain."})
    assert client.get(f"{GOOD_URL}/revisions/{old}", headers=other).status_code == 404  # tidak bisa mengintip versi orang lain
    assert client.get("/api/drafts/skripsi/ngawur/revisions", headers=d).status_code == 404


def test_revisions_throttle_and_prune(client, monkeypatch):
    d = dev()
    monkeypatch.setattr(settings, "revision_min_minutes", 60)
    for i in range(3):
        client.put(GOOD_URL, headers=d, json={"content": f"isi {i}"})
    assert len(client.get(GOOD_URL + "/revisions", headers=d).json()) == 1  # ditahan jeda minimal
    monkeypatch.setattr(settings, "revision_min_minutes", 0)
    monkeypatch.setattr(settings, "revision_keep", 3)
    for i in range(10, 16):
        client.put(GOOD_URL, headers=d, json={"content": f"isi {i}"})
    revs = client.get(GOOD_URL + "/revisions", headers=d).json()
    assert len(revs) == 3
    assert client.get(f"{GOOD_URL}/revisions/{revs[0]['id']}", headers=d).json()["content"] == "isi 15"


# ---------- catatan dosen & logbook ----------
def test_notes_flow_and_authorization(client, admin, reg):
    hd, hs, iid, code = setup_campus(client, admin, reg, LONG)
    join(client, hs, code)
    sid = sid_of(client, hd)
    hx, _ = reg()
    url = f"/api/dosen/students/{sid}/notes"
    assert client.get("/api/dosen/presets", headers=hs).status_code == 403
    assert len(client.get("/api/dosen/presets", headers=hd).json()) >= 5
    assert client.post(url, headers=hs, json={"body": "x"}).status_code == 403  # mahasiswa tidak boleh menulis
    assert client.post(url, headers=hx, json={"body": "x"}).status_code == 403
    assert client.post(url, headers=hd, json={"body": "   "}).status_code == 422
    assert client.post(url, headers=hd, json={"body": "ok", "chapter_key": "pendahuluan"}).status_code == 422  # chapter butuh doc_type
    assert client.post(url, headers=hd, json={"body": "ok", "doc_type": "skripsi", "chapter_key": "ngawur"}).status_code == 422
    n = client.post(url, headers=hd, json={"body": "Perjelas rumusan masalah.", "doc_type": "skripsi", "chapter_key": "pendahuluan"}).json()
    lg = client.post(url, headers=hd, json={"body": "Bimbingan 1: bahas Bab 1.", "kind": "logbook"}).json()
    assert n["kind"] == "catatan" and n["session_date"] is None and lg["session_date"]  # logbook otomatis bertanggal
    mine = client.get("/api/notes", headers=hs).json()
    assert mine["unread"] == 2 and {x["dosen"] for x in mine["notes"]} == {"Bu Rina"}
    assert [x["id"] for x in client.get("/api/notes?kind=logbook", headers=hs).json()["notes"]] == [lg["id"]]
    assert [x["id"] for x in client.get("/api/notes?doc_type=skripsi&chapter_key=pendahuluan", headers=hs).json()["notes"]] == [n["id"]]
    assert client.post(f"/api/notes/{n['id']}/read", headers=hx).status_code == 404  # bukan miliknya
    assert client.post(f"/api/notes/{n['id']}/read", headers=hs).status_code == 200
    assert client.get("/api/notes", headers=hs).json()["unread"] == 1
    assert client.post("/api/notes/read-all", headers=hs).status_code == 200
    assert client.get("/api/notes", headers=hs).json()["unread"] == 0
    assert client.get("/api/notes", headers=hx).json() == {"notes": [], "unread": 0}  # pihak lain tidak melihat
    assert len(client.get(url, headers=hd).json()) == 2
    assert client.delete(f"/api/dosen/notes/{n['id']}", headers=hx).status_code == 403
    assert client.delete(f"/api/dosen/notes/{n['id']}", headers=hd).status_code == 200
    assert client.delete(f"/api/dosen/notes/{n['id']}", headers=hd).status_code == 404
    assert client.get("/api/notes").status_code == 401


def test_notes_blocked_after_consent_revoked(client, admin, reg):
    hd, hs, iid, code = setup_campus(client, admin, reg, LONG)
    join(client, hs, code)
    sid = sid_of(client, hd)
    url = f"/api/dosen/students/{sid}/notes"
    nid = client.post(url, headers=hd, json={"body": "Catatan awal."}).json()["id"]
    client.delete(f"/api/supervision/{client.get('/api/supervision/mine', headers=hs).json()[0]['id']}", headers=hs)
    assert client.post(url, headers=hd, json={"body": "lagi"}).status_code == 404
    assert client.get(url, headers=hd).status_code == 404
    assert client.delete(f"/api/dosen/notes/{nid}", headers=hd).status_code == 404
    assert [x["id"] for x in client.get("/api/notes", headers=hs).json()["notes"]] == [nid]  # mahasiswa tetap bisa membaca miliknya


# ---------- dosen: perubahan sejak review & perlu perhatian ----------
def test_dosen_changes_since_last_view_and_attention(client, admin, reg):
    hd, hs, iid, code = setup_campus(client, admin, reg, LONG)
    join(client, hs, code)
    st = client.get("/api/dosen/students", headers=hd).json()[0]
    assert st["attention"] == ["draf_baru"] and st["unseen"] == 1
    sid = st["student"]["id"]
    url = f"/api/dosen/students/{sid}/drafts/skripsi/pendahuluan"
    first = client.get(url, headers=hd).json()
    assert first["changes"] is None and first["last_seen"] is None and first["readiness"]["ready"] is True
    assert "manual" not in first["readiness"]
    again = client.get(url, headers=hd).json()
    assert again["changes"]["same"] is True and again["last_seen"]
    assert client.get("/api/dosen/students", headers=hd).json()[0]["attention"] == []  # sudah dibaca semua
    assert client.get("/api/dosen/students?focus=true", headers=hd).json() == []
    client.put(GOOD_URL, headers=hs, json={"content": LONG + "\n\nParagraf baru hasil revisi."})
    st = client.get("/api/dosen/students?focus=true", headers=hd).json()
    assert len(st) == 1 and st[0]["attention"] == ["draf_baru"]
    ch = client.get(url, headers=hd).json()["changes"]
    assert ch["same"] is False and ch["added"] == 1 and ch["items"][0]["after"] == "Paragraf baru hasil revisi."
    assert client.get(url, headers=hd).json()["changes"]["same"] is True  # pembacaan terbaru jadi pembanding berikutnya


def test_dosen_read_missing_draft_and_other_dosen_has_own_view(client, admin, reg):
    hd, hs, iid, code = setup_campus(client, admin, reg, LONG)
    join(client, hs, code)
    sid = sid_of(client, hd)
    empty = client.get(f"/api/dosen/students/{sid}/drafts/skripsi/metode", headers=hd).json()
    assert empty == {"content": "", "updated_at": None, "changes": None, "last_seen": None, "readiness": None}
    client.get(f"/api/dosen/students/{sid}/drafts/skripsi/pendahuluan", headers=hd)
    hd2, ed2 = reg(name="Pak Dua")
    assert client.post(f"/api/admin/institutions/{iid}/dosen", headers=admin, json={"email": ed2}).status_code == 200
    code2 = client.post("/api/dosen/invite", headers=hd2, json={"institution_id": iid}).json()["code"]
    join(client, hs, code2)
    assert client.get("/api/dosen/students", headers=hd2).json()[0]["unseen"] == 1  # jejak baca per dosen


def test_attention_siap_sidang_and_stuck(client, admin, reg, monkeypatch):
    hd, hs, iid, code = setup_campus(client, admin, reg)
    join(client, hs, code)
    for c in ("pendahuluan", "tinjauan", "metode", "hasil", "penutup"):
        client.put(f"/api/drafts/skripsi/{c}", headers=hs, json={"content": "kata " * 250})
    sid = sid_of(client, hd)
    for c in ("pendahuluan", "tinjauan", "metode", "hasil", "penutup"):
        client.get(f"/api/dosen/students/{sid}/drafts/skripsi/{c}", headers=hd)
    assert client.get("/api/dosen/students", headers=hd).json()[0]["attention"] == ["siap_sidang"]
    monkeypatch.setattr(settings, "stuck_days", -1)  # semua dianggap tertahan
    st = client.get("/api/dosen/students?focus=true", headers=hd).json()[0]
    assert st["attention"] == ["stuck", "siap_sidang"] and st["stuck"] is True


def test_restore_revision_is_safe_and_undoable(client, monkeypatch):
    d = dev()
    monkeypatch.setattr(settings, "revision_min_minutes", 60)  # jeda aktif: pemulihan harus tetap menyelamatkan teks terbaru
    client.put(GOOD_URL, headers=d, json={"content": "versi awal"})
    client.put(GOOD_URL, headers=d, json={"content": "teks terbaru yang belum sempat jadi versi"})
    first = client.get(GOOD_URL + "/revisions", headers=d).json()[-1]["id"]
    assert client.post(f"{GOOD_URL}/revisions/{first}/restore", headers=d).json() == {"content": "versi awal"}
    assert client.get(GOOD_URL, headers=d).json()["content"] == "versi awal"
    contents = [client.get(f"{GOOD_URL}/revisions/{r['id']}", headers=d).json()["content"] for r in client.get(GOOD_URL + "/revisions", headers=d).json()]
    assert "teks terbaru yang belum sempat jadi versi" in contents  # bisa dibatalkan
    other = dev()
    client.put(GOOD_URL, headers=other, json={"content": "milik lain"})
    assert client.post(f"{GOOD_URL}/revisions/{first}/restore", headers=other).status_code == 404


def test_export_logbook_docx(client, admin, reg):
    import io
    from docx import Document
    hd, hs, iid, code = setup_campus(client, admin, reg, LONG)
    join(client, hs, code)
    sid = sid_of(client, hd)
    assert client.post("/api/export/logbook", headers=hs, json={}).status_code == 400  # belum ada logbook
    client.post(f"/api/dosen/students/{sid}/notes", headers=hd, json={"body": "Catatan biasa tidak ikut."})
    assert client.post("/api/export/logbook", headers=hs, json={}).status_code == 400
    client.post(f"/api/dosen/students/{sid}/notes", headers=hd, json={"body": "Bimbingan 2.", "kind": "logbook", "session_date": "2026-10-20", "doc_type": "skripsi", "chapter_key": "metode"})
    client.post(f"/api/dosen/students/{sid}/notes", headers=hd, json={"body": "Bimbingan 1 \x00ok.", "kind": "logbook", "session_date": "2026-10-10"})
    r = client.post("/api/export/logbook", headers=hs, json={"author": "Budi", "nim": "123", "title": "Judul Uji"})
    assert r.status_code == 200 and "wordprocessingml" in r.headers["content-type"]
    doc = Document(io.BytesIO(r.content))
    t = doc.tables[0]
    assert len(t.rows) == 3 and [c.text for c in t.rows[1].cells][:3] == ["1", "10-10-2026", "Bu Rina"]  # urut tanggal
    assert t.rows[2].cells[3].text == "Bab 3 · Metode Penelitian" and t.rows[2].cells[4].text == "Bimbingan 2."
    assert doc.sections[0].page_width > doc.sections[0].page_height  # lanskap
    assert any("Budi" in p.text for p in doc.paragraphs)
    assert client.post("/api/export/logbook", json={}).status_code == 401
    hx, _ = reg()
    assert client.post("/api/export/logbook", headers=hx, json={}).status_code == 400  # milik orang lain tidak bocor
