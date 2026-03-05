from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from dataclasses import dataclass

from django.conf import settings


FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


@dataclass(frozen=True)
class FcmConfig:
    project_id: str
    client_email: str
    private_key: str


def _load_service_account() -> dict | None:
    raw = os.environ.get("FCM_SERVICE_ACCOUNT_JSON") or getattr(settings, "FCM_SERVICE_ACCOUNT_JSON", "")
    raw = str(raw or "").strip()
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            return None

    path = os.environ.get("FCM_SERVICE_ACCOUNT_FILE") or getattr(settings, "FCM_SERVICE_ACCOUNT_FILE", "")
    path = str(path or "").strip()
    if not path:
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def get_fcm_config() -> FcmConfig | None:
    sa = _load_service_account()
    if not isinstance(sa, dict):
        return None

    project_id = str(sa.get("project_id") or "").strip()
    client_email = str(sa.get("client_email") or "").strip()
    private_key = str(sa.get("private_key") or "").strip()

    if not (project_id and client_email and private_key):
        return None

    return FcmConfig(project_id=project_id, client_email=client_email, private_key=private_key)


def _get_access_token(cfg: FcmConfig) -> str:
    # google-auth is the simplest correct way to mint OAuth2 tokens for FCM HTTP v1.
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request

    creds = service_account.Credentials.from_service_account_info(
        {
            "type": "service_account",
            "project_id": cfg.project_id,
            "client_email": cfg.client_email,
            "private_key": cfg.private_key,
            "token_uri": "https://oauth2.googleapis.com/token",
        },
        scopes=[FCM_SCOPE],
    )
    creds.refresh(Request())
    if not creds.token:
        raise RuntimeError("Не удалось получить access token для FCM")
    return str(creds.token)


def send_fcm_notification(
    *,
    cfg: FcmConfig,
    token: str,
    title: str,
    body: str,
    data: dict | None = None,
) -> dict:
    access_token = _get_access_token(cfg)

    url = f"https://fcm.googleapis.com/v1/projects/{cfg.project_id}/messages:send"
    payload = {
        "message": {
            "token": token,
            "notification": {"title": title, "body": body},
            "data": {k: str(v) for k, v in (data or {}).items()},
            "android": {"priority": "high"},
        }
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {access_token}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")
        except Exception:
            body = ""
        # Try to surface Google error message to the admin UI.
        raise RuntimeError(f"FCM HTTP {e.code}: {body or e.reason}") from e
