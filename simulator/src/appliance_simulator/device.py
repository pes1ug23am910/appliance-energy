from __future__ import annotations

import json
import logging
import ssl
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

from .state import DeviceState

LOG = logging.getLogger(__name__)


class Device:
    def __init__(self, device_id: str, password: str, host: str, port: int,
                 ca: Path, state_dir: Path, interval: float = 10, drop_reports: bool = False):
        self.state = DeviceState(state_dir / f"{device_id}.sqlite", device_id)
        self.device_id = device_id
        self.interval = interval
        self.drop_reports = drop_reports
        self.sent_at = {}
        self.first_sent_at = {}
        self.receipt_seconds = []
        self.delivery_lock = threading.Lock()
        self.connected = threading.Event()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"sim-{device_id}", clean_session=False)
        self.client.username_pw_set(device_id, password)
        self.client.tls_set(ca_certs=str(ca), tls_version=ssl.PROTOCOL_TLS_CLIENT)
        self.client.max_queued_messages_set(1000)
        self.client.reconnect_delay_set(1, 30)
        self.client.on_connect = self._connect
        self.client.on_disconnect = lambda *_: self.connected.clear()
        self.client.on_message = self._message
        self.host, self.port = host, port

    def _connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            LOG.error("MQTT rejected device %s: %s", self.device_id, reason_code)
            return
        self.connected.set()
        client.subscribe([(f"devices/{self.device_id}/desired", 1), (f"devices/{self.device_id}/receipt", 1)])
        self.publish("sync", {"device_id": self.device_id, "boot_id": self.state.boot_id})
        self.report()

    def publish(self, kind: str, payload: dict):
        return self.client.publish(f"devices/{self.device_id}/{kind}", json.dumps(payload), qos=1, retain=False)

    def report(self):
        if not self.drop_reports:
            self.publish("reported", self.state.report())

    def _message(self, client, userdata, message):
        try:
            payload = json.loads(message.payload)
            if message.topic.endswith("/receipt"):
                if payload.get("status") == "accepted":
                    self.state.acknowledge(payload["event_id"])
                    with self.delivery_lock:
                        self.sent_at.pop(payload["event_id"], None)
                        started = self.first_sent_at.pop(payload["event_id"], None)
                        if started is not None:
                            self.receipt_seconds.append(time.monotonic() - started)
                            if len(self.receipt_seconds) > 10000:
                                del self.receipt_seconds[:1000]
            elif message.topic.endswith("/desired"):
                outcome = self.state.apply(payload)
                LOG.info("device=%s command=%s outcome=%s", self.device_id, payload.get("command_id"), outcome)
                if outcome in ("applied", "duplicate", "stale"):
                    self.report()
        except (ValueError, TypeError, KeyError):
            LOG.warning("Invalid message on %s", message.topic)

    def start(self):
        self.client.connect_async(self.host, self.port, keepalive=30)
        self.client.loop_start()

    def tick(self, elapsed: float):
        self.state.sample(elapsed)
        if self.connected.is_set():
            for event in self.state.pending():
                now = time.monotonic()
                with self.delivery_lock:
                    send = now - self.sent_at.get(event["event_id"], float("-inf")) >= 10
                    if send:
                        self.sent_at[event["event_id"]] = now
                        self.first_sent_at.setdefault(event["event_id"], now)
                if send:
                    self.publish("telemetry", event)
            self.report()

    def stop(self):
        self.client.disconnect()
        self.client.loop_stop()
        self.state.close()
