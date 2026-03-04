from __future__ import annotations

import json
import urllib.request
from typing import Iterable

from django.utils import timezone

from .models import Notification, PushDevice


EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


def _chunked(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def send_push_for_notification(notification: Notification) -> dict:
    """
    Отправляет push (Expo) всем активным устройствам квартиры,
    либо всем устройствам (если квартира не указана).
    Возвращает сводку по отправке.
    """
    q = PushDevice.objects.filter(is_active=True)
    if notification.apartment is not None:
        q = q.filter(apartment=notification.apartment)

    tokens = list(q.values_list("token", flat=True).order_by("id"))
    if not tokens:
        return {"ok": True, "sent": 0, "detail": "no devices"}

    sent = 0
    errors: list[str] = []

    # Expo рекомендует отправлять батчами.
    for batch in _chunked(tokens, 90):
        messages = [
            {
                "to": t,
                "title": notification.title,
                "body": notification.body or "",
                "sound": "default",
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
            for entry in data:
                if isinstance(entry, dict) and entry.get("status") == "ok":
                    sent += 1
                else:
                    errors.append(json.dumps(entry, ensure_ascii=False))

    notification.push_sent_at = timezone.now()
    notification.save(update_fields=["push_sent_at"])

    return {"ok": not errors, "sent": sent, "errors": errors[:20]}
