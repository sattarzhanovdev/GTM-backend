from __future__ import annotations

import json
import urllib.request
from typing import Iterable

from django.utils import timezone

from .fcm import get_fcm_config, send_fcm_notification
from .models import Notification, PushDevice


EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_RECEIPTS_URL = "https://exp.host/--/api/v2/push/getReceipts"


def _chunked(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def send_push_for_notification(notification: Notification) -> dict:
    """
    Отправляет push всем активным устройствам квартиры,
    либо всем устройствам (если квартира не указана).

    Поддерживает:
    - FCM (HTTP v1) для token_type='fcm'
    - Expo Push API для token_type='expo' (в основном для Expo Go/старых сборок)
    Возвращает сводку по отправке.
    """
    q = PushDevice.objects.filter(is_active=True)
    if notification.apartment is not None:
        q = q.filter(apartment=notification.apartment)

    devices = list(q.values("token", "token_type").order_by("id"))
    if not devices:
        return {"ok": True, "sent": 0, "detail": "no devices"}

    sent = 0
    errors: list[str] = []
    ticket_ids: list[str] = []
    ticket_to_token: dict[str, str] = {}

    # 1) FCM (Android standalone)
    fcm_cfg = get_fcm_config()
    fcm_tokens = [d["token"] for d in devices if d.get("token_type") == PushDevice.TokenType.FCM]
    if fcm_tokens and not fcm_cfg:
        errors.append("FCM не настроен: нет FCM_SERVICE_ACCOUNT_JSON/FCM_SERVICE_ACCOUNT_FILE")
    if fcm_cfg:
        for t in fcm_tokens:
            try:
                send_fcm_notification(
                    cfg=fcm_cfg,
                    token=t,
                    title=notification.title,
                    body=notification.body or "",
                    data={"notificationId": notification.id, "apartment": notification.apartment or ""},
                )
                sent += 1
            except Exception as e:
                errors.append(str(e))

    # Expo рекомендует отправлять батчами.
    expo_tokens = [d["token"] for d in devices if d.get("token_type") == PushDevice.TokenType.EXPO]
    for batch in _chunked(expo_tokens, 90):
        messages = [
            {
                "to": t,
                "title": notification.title,
                "body": notification.body or "",
                "sound": "default",
                "channelId": "default",
                "data": {"notificationId": notification.id, "apartment": notification.apartment},
            }
            for t in batch
        ]

        req = urllib.request.Request(
            EXPO_PUSH_URL,
            data=json.dumps(messages).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode("utf-8")
                payload = json.loads(raw) if raw else {}
        except Exception as e:
            errors.append(str(e))
            continue

        # payload example: {"data":[{"status":"ok","id":"..."}, ...]}
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, list):
            for idx, entry in enumerate(data):
                token = batch[idx] if idx < len(batch) else ""
                if isinstance(entry, dict) and entry.get("status") == "ok":
                    sent += 1
                    ticket_id = entry.get("id")
                    if token and ticket_id:
                        ticket_ids.append(str(ticket_id))
                        ticket_to_token[str(ticket_id)] = token
                else:
                    errors.append(json.dumps(entry, ensure_ascii=False))

    # Получаем receipts, чтобы видеть реальные ошибки (например InvalidCredentials).
    for chunk in _chunked(ticket_ids, 300):
        req = urllib.request.Request(
            EXPO_RECEIPTS_URL,
            data=json.dumps({"ids": chunk}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode("utf-8")
                payload = json.loads(raw) if raw else {}
        except Exception as e:
            errors.append(str(e))
            continue

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            continue

        for ticket_id, receipt in data.items():
            if not isinstance(receipt, dict):
                continue
            if receipt.get("status") == "ok":
                continue

            # receipt example:
            # { "status":"error","message":"...","details":{"error":"InvalidCredentials"} }
            errors.append(json.dumps({"ticket": ticket_id, **receipt}, ensure_ascii=False))

            details = receipt.get("details") if isinstance(receipt.get("details"), dict) else {}
            err_code = details.get("error")
            if err_code == "DeviceNotRegistered":
                token = ticket_to_token.get(str(ticket_id))
                if token:
                    PushDevice.objects.filter(token=token).update(is_active=False)

    notification.push_sent_at = timezone.now()
    notification.save(update_fields=["push_sent_at"])

    return {"ok": not errors, "sent": sent, "errors": errors[:20]}
