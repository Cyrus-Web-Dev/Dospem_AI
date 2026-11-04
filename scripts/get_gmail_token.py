#!/usr/bin/env python3
"""Skrip sekali-pakai untuk mendapatkan GMAIL_REFRESH_TOKEN.

Langkah:
1. Buka https://console.cloud.google.com/
2. Buat project (atau pilih yang sudah ada) → aktifkan "Gmail API"
3. Credentials → Create Credentials → OAuth client ID
   - Application type: Desktop app
   - Unduh JSON, simpan sebagai credentials.json di folder ini
4. Jalankan:  python scripts/get_gmail_token.py
5. Browser akan terbuka → login dengan akun Gmail yang akan dipakai mengirim email
6. Salin nilai yang dicetak ke .env (GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN)
7. Hapus credentials.json setelah selesai (jangan commit ke git)

Catatan:
- Scope yang diminta hanya gmail.send (tidak bisa baca kotak masuk).
- Refresh token berlaku selama tidak dicabut di https://myaccount.google.com/permissions
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("Instal dulu:  pip install google-auth-oauthlib google-api-python-client")
    sys.exit(1)

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
HERE = Path(__file__).resolve().parent
CREDS_FILE = HERE / "credentials.json"


def main() -> None:
    if not CREDS_FILE.exists():
        print(f"File tidak ditemukan: {CREDS_FILE}")
        print("Unduh OAuth client (Desktop app) dari Google Cloud Console dan simpan sebagai credentials.json")
        sys.exit(1)

    data = json.loads(CREDS_FILE.read_text(encoding="utf-8"))
    # Support both "installed" (Desktop) and "web" formats
    client = data.get("installed") or data.get("web")
    if not client:
        print("Format credentials.json tidak dikenali (harus berisi key 'installed' atau 'web')")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    if not creds.refresh_token:
        print(
            "Tidak mendapatkan refresh_token.\n"
            "Coba cabut akses aplikasi di https://myaccount.google.com/permissions lalu jalankan lagi."
        )
        sys.exit(1)

    print("\n=== Salin ke file .env ===\n")
    print(f"EMAIL_PROVIDER=gmail")
    print(f"GMAIL_CLIENT_ID={client['client_id']}")
    print(f"GMAIL_CLIENT_SECRET={client['client_secret']}")
    print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
    print(f"GMAIL_SENDER=Dospem <alamat-gmail-anda@gmail.com>")
    print("\nSetelah disalin, hapus credentials.json (jangan di-commit).")


if __name__ == "__main__":
    main()
