#!/usr/bin/env python3
"""Backup, retensi, dan uji pemulihan PostgreSQL untuk Dospem. Hanya pustaka standar.

  python scripts/dospem_backup.py run            # dump -> verifikasi -> (unggah) -> pangkas lama
  python scripts/dospem_backup.py restore-check  # pulihkan backup terbaru ke DB sementara lalu periksa
  python scripts/dospem_backup.py prune          # hanya terapkan retensi

Target: `--url postgresql://user:pass@host:5432/db` (atau env BACKUP_PG_URL) untuk koneksi langsung, atau mode Docker
(`--compose docker-compose.prod.yml`, layanan `db`) yang menjalankan perkakas PostgreSQL di dalam kontainer.

Jaminan keselamatan (diuji): berkas ditulis ke `.part` dan baru diberi nama final setelah lolos verifikasi, sehingga backup rusak tidak pernah
tersisa; pemangkasan HANYA berjalan setelah backup baru berhasil dan terverifikasi; backup terbaru tidak pernah dihapus; berkas berpola lain tidak disentuh.
Kode keluar: 0 sukses, 1 dump gagal, 2 verifikasi gagal, 3 unggah gagal (berkas lokal tetap ada), 4 uji pemulihan gagal."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

NAME_RE = re.compile(r"^dospem-(\d{8})-(\d{6})\.dump$")
MIN_BYTES = 1024
ROOT = Path(__file__).resolve().parents[1]


class BackupError(RuntimeError):
    def __init__(self, msg: str, code: int):
        super().__init__(msg)
        self.code = code


# ---------- nama & retensi (murni, mudah diuji) ----------
def backup_name(now: dt.datetime) -> str:
    return f"dospem-{now:%Y%m%d-%H%M%S}.dump"


def parse_name(name: str) -> dt.datetime | None:
    m = NAME_RE.match(name)
    if not m:
        return None
    try:
        return dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def retention(names: list[str], keep_daily: int = 7, keep_weekly: int = 8) -> tuple[list[str], list[str]]:
    """(dipertahankan, dihapus). Pertahankan `keep_daily` backup terbaru, ditambah backup terbaru tiap minggu ISO untuk `keep_weekly` minggu terakhir
    yang punya backup. Backup terbaru SELALU dipertahankan. Nama yang bukan pola backup diabaikan (tidak masuk kedua daftar)."""
    parsed = sorted(((parse_name(n), n) for n in names if parse_name(n)), reverse=True)
    keep: set[str] = {n for _, n in parsed[: max(1, keep_daily)]}
    weeks: dict[tuple[int, int], str] = {}
    for t, n in parsed:  # terbaru dulu: yang pertama dijumpai per minggu = terbaru minggu itu
        weeks.setdefault(tuple(t.isocalendar()[:2]), n)
    for wk in sorted(weeks, reverse=True)[: max(0, keep_weekly)]:
        keep.add(weeks[wk])
    ordered = [n for _, n in parsed]
    return [n for n in ordered if n in keep], [n for n in ordered if n not in keep]


# ---------- target koneksi ----------
@dataclass
class Target:
    mode: str  # url | docker
    user: str = "dospem"
    db: str = "dospem"
    host: str = "localhost"
    port: str = "5432"
    password: str = ""
    compose: str = ""
    service: str = "db"

    @classmethod
    def build(cls, url: str | None, compose: str | None, service: str = "db", env: dict | None = None) -> "Target":
        env = os.environ if env is None else env
        url = url or env.get("BACKUP_PG_URL")
        if url:
            u = urlparse(url.replace("postgresql+psycopg://", "postgresql://"))
            if u.scheme not in ("postgresql", "postgres") or not u.path.strip("/"):
                raise BackupError("URL harus berbentuk postgresql://user:pass@host:port/namadb", 1)
            return cls("url", unquote(u.username or "dospem"), u.path.strip("/"), u.hostname or "localhost", str(u.port or 5432), unquote(u.password or ""))
        compose = compose or ("docker-compose.prod.yml" if (ROOT / "docker-compose.prod.yml").exists() else "")
        if not compose:
            raise BackupError("Tentukan --url / BACKUP_PG_URL, atau --compose untuk mode Docker.", 1)
        return cls("docker", env.get("POSTGRES_USER", "dospem"), env.get("POSTGRES_DB", "dospem"), compose=compose, service=service)

    def cmd(self, tool: str, *args: str) -> tuple[list[str], dict]:
        """(argv, tambahan env). Kata sandi lewat env PGPASSWORD, tidak pernah di argv."""
        if self.mode == "docker":
            return ["docker", "compose", "-f", self.compose, "exec", "-T", self.service, tool, "-U", self.user, *args], {}
        return [tool, "-h", self.host, "-p", self.port, "-U", self.user, *args], ({"PGPASSWORD": self.password} if self.password else {})


def _run(argv: list[str], env_extra: dict, *, stdin=None, stdout=None, check_msg: str, code: int) -> subprocess.CompletedProcess:
    try:
        r = subprocess.run(argv, env={**os.environ, **env_extra}, stdin=stdin, stdout=stdout if stdout else subprocess.PIPE, stderr=subprocess.PIPE, timeout=3600)
    except FileNotFoundError as e:
        raise BackupError(f"{check_msg}: perkakas tidak ditemukan ({e.filename}). Pasang postgresql-client atau pakai mode Docker.", code)
    except subprocess.TimeoutExpired:
        raise BackupError(f"{check_msg}: melewati batas waktu", code)
    if r.returncode != 0:
        raise BackupError(f"{check_msg}: {(r.stderr or b'').decode(errors='replace').strip()[:400] or 'kode ' + str(r.returncode)}", code)
    return r


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------- dump & verifikasi ----------
def verify(t: Target, path: Path, min_bytes: int = MIN_BYTES) -> int:
    """Pastikan berkas utuh: cukup besar dan `pg_restore --list` bisa membacanya serta memuat data tabel. Mengembalikan jumlah entri."""
    if not path.exists() or path.stat().st_size < min_bytes:
        raise BackupError(f"Berkas backup kosong atau terlalu kecil (<{min_bytes} byte)", 2)
    if t.mode == "docker":
        argv, env = t.cmd("pg_restore", "--list")
        with path.open("rb") as f:
            r = _run(argv, env, stdin=f, check_msg="Verifikasi gagal (pg_restore --list)", code=2)
    else:
        r = _run(["pg_restore", "--list", str(path)], {}, check_msg="Verifikasi gagal (pg_restore --list)", code=2)
    out = r.stdout.decode(errors="replace")
    if "TABLE DATA" not in out:
        raise BackupError("Backup terbaca tetapi tidak memuat data tabel", 2)
    return sum(1 for ln in out.splitlines() if ln and not ln.startswith(";"))


def dump(t: Target, out_dir: Path, now: dt.datetime | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    now = now or dt.datetime.now()
    final = out_dir / backup_name(now)
    part = final.with_suffix(".dump.part")
    argv, env = t.cmd("pg_dump", "-Fc", "--no-owner", "--no-privileges", "-d", t.db)
    try:
        with part.open("wb") as f:
            _run(argv, env, stdout=f, check_msg="pg_dump gagal", code=1)
        verify(t, part)
    except BackupError:
        part.unlink(missing_ok=True)  # backup rusak tidak boleh tersisa
        raise
    os.replace(part, final)
    final.with_suffix(".dump.sha256").write_text(f"{sha256_of(final)}  {final.name}\n")
    return final


def upload(path: Path, template: str) -> None:
    """Jalankan perintah unggah milikmu, mis. `rclone copyto {file} remote:dospem/{name}`. Gagal -> kode 3 (berkas lokal tetap ada)."""
    argv = [a.replace("{file}", str(path)).replace("{name}", path.name) for a in shlex.split(template)]
    _run(argv, {}, check_msg="Unggah offsite gagal", code=3)


def prune(out_dir: Path, keep_daily: int, keep_weekly: int) -> list[str]:
    _, drop = retention([p.name for p in out_dir.iterdir() if p.is_file()], keep_daily, keep_weekly)
    for n in drop:
        (out_dir / n).unlink(missing_ok=True)
        (out_dir / n).with_suffix(".dump.sha256").unlink(missing_ok=True)
    return drop


def run_backup(t: Target, out_dir: Path, keep_daily=7, keep_weekly=8, upload_cmd: str | None = None, now: dt.datetime | None = None) -> dict:
    path = dump(t, out_dir, now)  # gagal -> BackupError; TIDAK ada pemangkasan
    entries = verify(t, path)
    uploaded = False
    err = None
    if upload_cmd:
        try:
            upload(path, upload_cmd)
            uploaded = True
        except BackupError as e:
            err = e
    dropped = prune(out_dir, keep_daily, keep_weekly)  # hanya setelah backup baru terverifikasi
    res = {"file": path.name, "bytes": path.stat().st_size, "entries": entries, "sha256": sha256_of(path), "uploaded": uploaded, "pruned": dropped}
    if err:
        raise BackupError(f"{err} (backup lokal {path.name} aman)", 3)
    return res


# ---------- uji pemulihan ----------
def restore_check(t: Target, file: Path, strict_version: bool = False) -> dict:
    """Pulihkan `file` ke database sementara, periksa versi migrasi & tabel yang diharapkan, lalu hapus database sementara (selalu)."""
    expected = _expected_schema()
    scratch = f"dospem_rc_{dt.datetime.now():%Y%m%d%H%M%S}_{secrets.token_hex(2)}"
    admin = lambda sql: _run(*_psql(t, "postgres", sql), check_msg="Perintah SQL gagal", code=4)  # noqa: E731
    admin(f'CREATE DATABASE "{scratch}"')
    try:
        argv, env = t.cmd("pg_restore", "--no-owner", "--no-privileges", "-d", scratch)
        if t.mode == "docker":
            with file.open("rb") as f:
                _run(argv, env, stdin=f, check_msg="pg_restore gagal", code=4)
        else:
            _run([*argv, str(file)], env, check_msg="pg_restore gagal", code=4)
        ver = _scalar(t, scratch, "SELECT version_num FROM alembic_version")
        tables = set(_scalar(t, scratch, "SELECT string_agg(table_name, ',') FROM information_schema.tables WHERE table_schema='public'").split(","))
        counts = {tb: int(_scalar(t, scratch, f'SELECT count(*) FROM "{tb}"')) for tb in ("users", "drafts", "payments") if tb in tables}
    finally:
        try:
            admin(f'DROP DATABASE IF EXISTS "{scratch}"')
        except BackupError:
            print(f"PERINGATAN: gagal menghapus DB sementara {scratch}; hapus manual.", file=sys.stderr)
    missing = sorted(expected["tables"] - tables)
    warnings = []
    if missing:
        raise BackupError(f"Tabel hilang dari hasil pemulihan: {', '.join(missing)}", 4)
    if ver != expected["head"]:
        msg = f"Versi migrasi di backup {ver} != kepala repo {expected['head']} (backup lebih lama dari deploy terakhir?)"
        if strict_version:
            raise BackupError(msg, 4)
        warnings.append(msg)
    return {"file": file.name, "alembic": ver, "tables": len(tables), "rows": counts, "warnings": warnings}


def _psql(t: Target, db: str, sql: str) -> tuple[list[str], dict]:
    argv, env = t.cmd("psql", "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1", "-d", db, "-c", sql)
    return argv, env


def _scalar(t: Target, db: str, sql: str) -> str:
    r = _run(*_psql(t, db, sql), check_msg="Query pemeriksaan gagal", code=4)
    return r.stdout.decode().strip()


def _expected_schema() -> dict:
    """Kepala migrasi dan daftar tabel dari repo ini (sumber kebenaran, bukan dari DB yang dicadangkan)."""
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DATABASE_URL", "sqlite://")
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from app.models import Base
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    return {"head": ScriptDirectory.from_config(cfg).get_current_head(), "tables": set(Base.metadata.tables)}


# ---------- CLI ----------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["run", "prune", "restore-check"])
    ap.add_argument("--url"), ap.add_argument("--compose"), ap.add_argument("--service", default="db")
    ap.add_argument("--dir", default=os.environ.get("BACKUP_DIR", "backups"))
    ap.add_argument("--keep-daily", type=int, default=int(os.environ.get("BACKUP_KEEP_DAILY", 7)))
    ap.add_argument("--keep-weekly", type=int, default=int(os.environ.get("BACKUP_KEEP_WEEKLY", 8)))
    ap.add_argument("--upload-cmd", default=os.environ.get("BACKUP_UPLOAD_CMD"))
    ap.add_argument("--file", help="restore-check: berkas tertentu (bawaan: backup terbaru di --dir)")
    ap.add_argument("--strict-version", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.dir)
    try:
        if a.cmd == "prune":
            print(json.dumps({"pruned": prune(out, a.keep_daily, a.keep_weekly)}))
            return 0
        t = Target.build(a.url, a.compose, a.service)
        if a.cmd == "run":
            print(json.dumps(run_backup(t, out, a.keep_daily, a.keep_weekly, a.upload_cmd), ensure_ascii=False))
        else:
            f = Path(a.file) if a.file else next(iter(sorted((p for p in out.glob("dospem-*.dump") if parse_name(p.name)), reverse=True)), None)
            if not f or not f.exists():
                raise BackupError("Tidak ada berkas backup untuk diperiksa.", 4)
            print(json.dumps(restore_check(t, f, a.strict_version), ensure_ascii=False))
        return 0
    except BackupError as e:
        print(json.dumps({"error": str(e), "code": e.code}, ensure_ascii=False), file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
