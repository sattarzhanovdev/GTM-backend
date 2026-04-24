from __future__ import annotations

import json
import os
import ssl
from typing import Any

from django.conf import settings

from .models import Profile

try:
    from paho.mqtt import publish as mqtt_publish
except Exception:  # pragma: no cover - optional dependency in dev
    mqtt_publish = None


def _setting(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value not in (None, ""):
        return str(value)
    return str(getattr(settings, name, default) or default)


def mqtt_enabled() -> bool:
    return bool(_setting("MQTT_HOST"))


def _as_bool(value: str | bool | None, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _transport() -> str:
    value = _setting("MQTT_TRANSPORT", "tcp").strip().lower()
    return "websockets" if value in {"ws", "wss", "websocket", "websockets"} else "tcp"


DEVICE_RELAY_MAP: dict[tuple[str, str], tuple[str, str]] = {
    ("gate", "1"): ("block1", "relay1"),
    ("gate", "2"): ("block1", "relay2"),
    ("gate", "3"): ("block1", "relay3"),
    ("gate", "4"): ("block4", "relay1"),
    ("gate", "5"): ("block4", "relay2"),
    ("kalitka", "1"): ("block1", "relay4"),
    ("kalitka", "2"): ("block1", "relay5"),
    ("kalitka", "3"): ("block1", "relay6"),
    ("kalitka", "4"): ("block1", "relay7"),
    ("kalitka", "5"): ("block1", "relay8"),
    ("kalitka", "6"): ("block2", "relay1"),
    ("entrance", "1"): ("block2", "relay2"),
    ("entrance", "2"): ("block2", "relay3"),
    ("entrance", "3"): ("block2", "relay4"),
    ("entrance", "4"): ("block2", "relay5"),
    ("entrance", "5"): ("block2", "relay6"),
    ("lift", "1"): ("block2", "relay7"),
    ("lift", "2"): ("block2", "relay8"),
    ("lift", "3"): ("block3", "relay1"),
    ("lift", "4"): ("block3", "relay2"),
    ("lift", "5"): ("block3", "relay3"),
    ("parking", "1"): ("block3", "relay4"),
}


def resolve_relay_address(device_type: str, device_id: str | int) -> tuple[str, str]:
    key = (str(device_type), str(device_id))
    if key not in DEVICE_RELAY_MAP:
        raise RuntimeError(f"MQTT relay mapping is missing for {device_type}:{device_id}")
    return DEVICE_RELAY_MAP[key]


def build_topic(profile: Profile, device_type: str, device_id: str | int) -> str:
    return build_topic_for_scope(
        complex_slug=profile.complex.slug,
        building_id=profile.building.building_id,
        entrance=profile.entrance,
        apartment=profile.apartment,
        device_type=device_type,
        device_id=device_id,
    )


def build_topic_for_scope(
    *,
    complex_slug: str,
    building_id: str,
    entrance: int | None,
    apartment: int | None,
    device_type: str,
    device_id: str | int,
) -> str:
    block_id, relay_id = resolve_relay_address(device_type, device_id)
    return f"gate/{block_id}/{relay_id}/open"


def publish_device_command(
    profile: Profile,
    *,
    device_type: str,
    device_id: str | int,
    action: str = "open",
    value: bool = True,
    seconds: int = 1,
    extra: dict[str, Any] | None = None,
    target_complex: str | None = None,
    target_building: str | None = None,
) -> dict[str, Any]:
    complex_slug = str(target_complex or profile.complex.slug)
    building_id = str(target_building or profile.building.building_id)
    block_id, relay_id = resolve_relay_address(device_type, device_id)
    topic = build_topic_for_scope(
        complex_slug=complex_slug,
        building_id=building_id,
        entrance=profile.entrance,
        apartment=profile.apartment,
        device_type=device_type,
        device_id=device_id,
    )
    meta_payload: dict[str, Any] = {
        "action": action,
        "value": value,
        "seconds": seconds,
        "duration": int(seconds) * 1000,
        "complex": complex_slug,
        "building": building_id,
        "entrance": profile.entrance,
        "apartment": profile.apartment,
        "blockId": block_id,
        "relayId": relay_id,
        "deviceType": device_type,
        "deviceId": str(device_id),
    }
    if extra:
        meta_payload.update(extra)

    if not mqtt_enabled():
        raise RuntimeError("MQTT is not configured: set MQTT_HOST on the backend.")

    if mqtt_publish is None:
        raise RuntimeError("MQTT dependency is missing. Install paho-mqtt on the backend.")

    auth = None
    username = _setting("MQTT_USERNAME")
    password = _setting("MQTT_PASSWORD")
    if username:
        auth = {"username": username, "password": password}

    tls = None
    if _as_bool(_setting("MQTT_TLS")):
        tls = {"tls_version": ssl.PROTOCOL_TLS_CLIENT}

    proxy_args = None
    ws_path = _setting("MQTT_WS_PATH")
    if _transport() == "websockets" and ws_path:
        proxy_args = {"path": ws_path}

    mqtt_publish.single(
        topic,
        payload="1" if value and action == "open" else "0",
        hostname=_setting("MQTT_HOST"),
        port=int(_setting("MQTT_PORT", "443" if _transport() == "websockets" else "1883")),
        client_id=_setting("MQTT_CLIENT_ID", ""),
        keepalive=int(_setting("MQTT_KEEPALIVE", "30")),
        auth=auth,
        tls=tls,
        qos=int(_setting("MQTT_QOS", "1")),
        retain=_as_bool(_setting("MQTT_RETAIN")),
        transport=_transport(),
        proxy_args=proxy_args,
    )

    return {"published": True, "topic": topic, "payload": "1" if value and action == "open" else "0", "meta": meta_payload}
