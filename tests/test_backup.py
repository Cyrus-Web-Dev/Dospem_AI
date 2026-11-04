"""Backup & uji pemulihan PostgreSQL: retensi (murni), pembangun perintah, dan integrasi nyata (hanya jika PostgreSQL + pg_dump tersedia)."""
import datetime as dt
import os
import random
import shutil
import sys
from pathlib import Path

import pytest

from scripts import dospem_backup as b

N = lambda d, h=2: b.backup_name(dt.datetime(2026, 10, 1, h) + dt.timedelta(days=d))  # noqa: E731  (d hari sejak 1 Okt 2026)


# ---------- retensi (murni) ----------
def test_retention_daily_plus_weekly():
    names = [N(d) for d in range(34)]  # 1 Okt .. 3 Nov 2026 (minggu ISO 40..45)
    keep, drop = b.retention(names, keep_daily=7, keep_weekly=3)
    # 7 terbaru: 3 Nov .. 28 Okt. Mingguan (3 minggu terbaru): minggu 45 -> 3 Nov, minggu 44 -> 1 Nov, minggu 43 -> 25 Okt (satu-satunya tambahan).
    d = lambda s: b.backup_name(dt.datetime.strptime(s, "%Y-%m-%d").replace(hour=2))  # noqa: E731
    assert set(keep) == {d(f"2026-11-0{i}") for i in (1, 2, 3)} | {d("2026-10-31"), d("2026-10-30"), d("2026-10-29"), d("2026-10-28"), d("2026-10-25")}
    assert set(keep) | set(drop) == set(names) and not set(keep) & set(drop)
    assert keep[0] == N(33)  # terbaru di depan


def test_retention_order_independent_and_ignores_foreign_files():
    names = [N(d) for d in range(20)]
    shuffled = names[:]
    random.Random(1).shuffle(shuffled)
    assert b.retention(names, 3, 2) == b.retention(shuffled, 3, 2)
    foreign = ["catatan.txt", "dospem-2026-11-03.dump", "dospem-20261303-020000.dump", "dospem-20261103-020000.dump.sha256", "dospem-20261103-020000.dump.part"]
    keep, drop = b.retention(names + foreign, 3, 2)
    assert not (set(foreign) & (set(keep) | set(drop)))  # berkas lain tidak pernah masuk daftar hapus


def test_retention_never_drops_the_newest():
    names = [N(d) for d in range(5)]
    assert b.retention(names, 0, 0)[0] == [N(4)]
    assert b.retention([], 7, 8) == ([], [])
    assert b.retention([N(0)], 1, 0) == ([N(0)], [])


# ---------- target & perintah ----------
def test_target_from_url_and_env():
    t = b.Target.build("postgresql+psycopg://adm:p%40ss%2Fw@db.host:6543/prod_db", None, env={})
    assert (t.mode, t.user, t.password, t.host, t.port, t.db) == ("url", "adm", "p@ss/w", "db.host", "6543", "prod_db")
    assert b.Target.build(None, None, env={"BACKUP_PG_URL": "postgresql://u:x@h/d"}).db == "d"
    for bad in ("mysql://u@h/d", "postgresql://u@h/", "bukan url"):
        with pytest.raises(b.BackupError) as e:
            b.Target.build(bad, None, env={})
        assert e.value.code == 1


def test_commands_never_put_password_in_argv():
    t = b.Target.build("postgresql://adm:RAHASIA@h:5432/d", None, env={})
    argv, env = t.cmd("pg_dump", "-Fc")
    assert argv == ["pg_dump", "-h", "h", "-p", "5432", "-U", "adm", "-Fc"] and env == {"PGPASSWORD": "RAHASIA"} and "RAHASIA" not in " ".join(argv)
    dk = b.Target.build(None, "compose.yml", "db", env={"POSTGRES_USER": "u1", "POSTGRES_DB": "d1"})
    assert dk.mode == "docker" and (dk.user, dk.db) == ("u1", "d1")
    assert dk.cmd("pg_dump", "-Fc") == (["docker", "compose", "-f", "compose.yml", "exec", "-T", "db", "pg_dump", "-U", "u1", "-Fc"], {})
    assert b.Target.build(None, None, env={}).mode == "docker"  # tanpa URL: memakai docker-compose.prod.yml bawaan repo


def test_upload_template(tmp_path):
    f = tmp_path / "dospem-20261103-020000.dump"
    f.write_bytes(b"x" * 10)
    dest = tmp_path / "offsite"
    dest.mkdir()
    # Cross-platform: python -c shutil.copy (perintah `cp` tidak ada di Windows).
    # Path pakai as_posix() agar backslash Windows tidak dirusak shlex.split (posix=True).
    py = Path(sys.executable).as_posix()
    dest_file = dest / f.name
    b.upload(
        f,
        f'{py} -c "import shutil,sys; shutil.copy(sys.argv[1], sys.argv[2])" {{file}} {dest_file.as_posix()}',
    )
    assert dest_file.read_bytes() == f.read_bytes()
    with pytest.raises(b.BackupError) as e:
        b.upload(f, f'{py} -c "raise SystemExit(1)"')
    assert e.value.code == 3


# ---------- integrasi nyata ----------
URL = (os.environ.get("TEST_DATABASE_URL") or "").replace("postgresql+psycopg://", "postgresql://")
needs_pg = pytest.mark.skipif(not (URL.startswith("postgresql") and shutil.which("pg_dump") and shutil.which("pg_restore") and shutil.which("psql")),
                              reason="butuh TEST_DATABASE_URL PostgreSQL dan pg_dump/pg_restore/psql")


@pytest.fixture
def target():
    return b.Target.build(URL, None, env={})


def scratch_dbs(t):
    return int(b._scalar(t, "postgres", "SELECT count(*) FROM pg_database WHERE datname LIKE 'dospem_rc_%'"))


@needs_pg
def test_run_backup_verify_checksum_and_prune(client, target, tmp_path):
    for d in range(12):  # 12 backup lama palsu + 1 berkas asing
        (tmp_path / N(d, 1)).write_bytes(b"lama")
        (tmp_path / (N(d, 1) + ".sha256")).write_text("x")
    (tmp_path / "catatan-penting.txt").write_text("jangan dihapus")
    res = b.run_backup(target, tmp_path, keep_daily=3, keep_weekly=1, now=dt.datetime(2026, 11, 3, 2))
    f = tmp_path / res["file"]
    assert res["file"] == "dospem-20261103-020000.dump" and res["bytes"] > b.MIN_BYTES and res["entries"] > 50
    assert f.with_suffix(".dump.sha256").read_text().split()[0] == b.sha256_of(f) == res["sha256"]
    assert not list(tmp_path.glob("*.part"))
    left = sorted(p.name for p in tmp_path.glob("dospem-*.dump"))
    assert left == sorted([N(10, 1), N(11, 1), f.name])  # 3 terbaru; pilihan mingguan (minggu terbaru) tumpang tindih dengan yang sudah ada
    assert (tmp_path / "catatan-penting.txt").exists()  # berkas asing tak tersentuh
    assert not (tmp_path / (N(0, 1) + ".sha256")).exists()  # sidecar ikut dihapus bersama backup yang dipangkas


@needs_pg
def test_restore_check_ok_and_cleans_up(client, target, tmp_path, reg):
    h, _ = reg()  # pastikan ada data untuk dihitung walau tes ini dijalankan sendirian
    assert client.put("/api/drafts/skripsi/pendahuluan", headers=h, json={"content": "Isi bab untuk uji backup."}).status_code == 200
    f = b.dump(target, tmp_path)
    before = scratch_dbs(target)
    r = b.restore_check(target, f)
    assert r["alembic"] == b._expected_schema()["head"] and r["tables"] >= len(b._expected_schema()["tables"]) and r["warnings"] == []
    assert r["rows"]["users"] > 0 and r["rows"]["drafts"] > 0  # data benar-benar ikut terpulihkan
    assert scratch_dbs(target) == before  # DB sementara dibuang


@needs_pg
def test_failed_dump_leaves_no_file_and_never_prunes(client, tmp_path):
    for d in range(10):
        (tmp_path / N(d)).write_bytes(b"lama")
    bad = b.Target.build(URL.rsplit("/", 1)[0] + "/database_yang_tidak_ada", None, env={})
    with pytest.raises(b.BackupError) as e:
        b.run_backup(bad, tmp_path, keep_daily=2, keep_weekly=0)
    assert e.value.code == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(N(d) for d in range(10))  # tak ada .part, dan TIDAK ADA yang dipangkas


@needs_pg
def test_corrupt_backup_is_rejected(client, target, tmp_path):
    junk = tmp_path / "dospem-20261103-030000.dump"
    junk.write_bytes(os.urandom(4096))
    with pytest.raises(b.BackupError) as e:
        b.verify(target, junk)
    assert e.value.code == 2
    good = b.dump(target, tmp_path)  # dump VALID tetapi di bawah ambang ukuran: harus ditolak oleh pemeriksaan ukuran, bukan oleh pg_restore
    assert b.verify(target, good) > 0
    with pytest.raises(b.BackupError) as e:
        b.verify(target, good, min_bytes=10**9)
    assert e.value.code == 2 and "terlalu kecil" in str(e.value)
    tiny = tmp_path / "kecil.dump"
    tiny.write_bytes(b"x")
    with pytest.raises(b.BackupError) as e:
        b.verify(target, tiny)
    assert e.value.code == 2
    before = scratch_dbs(target)
    with pytest.raises(b.BackupError) as e:
        b.restore_check(target, junk)
    assert e.value.code == 4 and scratch_dbs(target) == before  # gagal pulih pun DB sementara tetap dibuang


@needs_pg
def test_restore_check_detects_schema_drift(client, target, tmp_path, monkeypatch):
    f = b.dump(target, tmp_path)
    real = b._expected_schema()
    monkeypatch.setattr(b, "_expected_schema", lambda: {**real, "head": "9999"})
    r = b.restore_check(target, f)  # bawaan: peringatan (backup bisa lebih tua dari deploy terakhir)
    assert r["warnings"] and "9999" in r["warnings"][0]
    with pytest.raises(b.BackupError) as e:
        b.restore_check(target, f, strict_version=True)
    assert e.value.code == 4
    monkeypatch.setattr(b, "_expected_schema", lambda: {**real, "tables": real["tables"] | {"tabel_gaib"}})
    with pytest.raises(b.BackupError) as e:
        b.restore_check(target, f)
    assert e.value.code == 4 and "tabel_gaib" in str(e.value)


@needs_pg
def test_upload_failure_keeps_local_backup(client, target, tmp_path):
    with pytest.raises(b.BackupError) as e:
        b.run_backup(target, tmp_path, upload_cmd="false", now=dt.datetime(2026, 11, 3, 4))
    assert e.value.code == 3 and (tmp_path / "dospem-20261103-040000.dump").exists()  # backup lokal aman walau unggah gagal


@needs_pg
def test_cli_exit_codes(client, tmp_path, capsys):
    assert b.main(["run", "--url", URL, "--dir", str(tmp_path)]) == 0
    assert '"file": "dospem-' in capsys.readouterr().out
    assert b.main(["restore-check", "--url", URL, "--dir", str(tmp_path)]) == 0
    assert b.main(["run", "--url", "mysql://x/y", "--dir", str(tmp_path)]) == 1
    assert b.main(["restore-check", "--url", URL, "--dir", str(tmp_path / "kosong")]) == 4
    assert b.main(["prune", "--dir", str(tmp_path), "--keep-daily", "1", "--keep-weekly", "0"]) == 0
