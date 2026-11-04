"""Pengiriman email transaksional (reset kata sandi).

Provider:
  - `mock`  : development/tes — tidak mengirim apa pun, hanya mencatat ke log dan OUTBOX
  - `gmail` : Gmail API (OAuth2 refresh token)

Kegagalan kirim dicatat tetapi TIDAK dilempar, agar respons API tidak membocorkan
apakah sebuah email terdaftar.
"""
from __future__ import annotations

import base64
import logging
from email.message import EmailMessage

from . import obs
from .config import settings

log = logging.getLogger("dospem.mail")
OUTBOX: list[dict] = []  # hanya diisi provider mock (dibatasi 100 pesan terakhir)

_SCOPES = ("https://www.googleapis.com/auth/gmail.send",)


def send(to: str, subject: str, body: str) -> bool:
    if settings.email_provider != "gmail":
        OUTBOX.append({"to": to, "subject": subject, "body": body})
        del OUTBOX[:-100]
        log.warning(
            "[email mock] kepada=%s subjek=%s\n%s",
            to,
            subject,
            body,
            extra={"dev_only": True},
        )  # tautan reset sengaja terlihat di pengembangan; disaring di produksi
        return True
    try:
        return _send_gmail(to, subject, body)
    except Exception as e:  # jaringan, otentikasi, alamat tak valid, kuota, dll.
        obs.event(
            "email_failed",
            "error",
            domain=to.rsplit("@", 1)[-1],
            exc=type(e).__name__,
            reason=str(e)[:150],
        )  # tanpa alamat lengkap
        return False


def _send_gmail(to: str, subject: str, body: str) -> bool:
    """Kirim lewat Gmail API memakai OAuth2 refresh token."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    # EmailMessage menolak karakter baris baru di header (anti header injection)
    msg = EmailMessage()
    msg["From"] = settings.gmail_sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    creds = Credentials(
        token=None,
        refresh_token=settings.gmail_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.gmail_client_id,
        client_secret=settings.gmail_client_secret,
        scopes=list(_SCOPES),
    )
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return True
