"""Optional MQTT -> CSV bridge. The dashboard works without it.

Run:  python -m jaldrishti.mqtt_subscriber
Settings come from environment variables or a local .env file (see .env.example).
"""
import logging
import os
import sys
from datetime import datetime, timezone

from . import config, data_store

log = logging.getLogger("jaldrishti.mqtt")


def load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(config.ROOT / ".env")
    except ImportError:
        pass


def settings():
    return {
        "host": os.getenv("MQTT_HOST", "localhost"),
        "port": int(os.getenv("MQTT_PORT", "1883")),
        "topic": os.getenv("MQTT_TOPIC", "jaldrishti/+/readings"),
        "username": os.getenv("MQTT_USERNAME", ""),
        "password": os.getenv("MQTT_PASSWORD", ""),
        "tls": os.getenv("MQTT_TLS", "0") == "1",
        "default_location": os.getenv("JALDRISHTI_DEFAULT_LOCATION", "unknown"),
        "client_id": os.getenv("MQTT_CLIENT_ID", "jaldrishti-subscriber"),
    }


def _log_rejected(topic, reason, payload):
    config.REJECTED_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = (payload.decode("utf-8", "replace") if isinstance(payload, (bytes, bytearray)) else str(payload))
    text = " ".join(text.split())[:300]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(config.REJECTED_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{stamp}\t{topic}\t{reason}\t{text}\n")


def handle_payload(payload, topic="", default_location="unknown", received_at=None):
    """Store one message. Returns True if a row was saved, False if it was rejected (and logged)."""
    received_at = received_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parts = topic.split("/")
    device = parts[1] if len(parts) == 3 and parts[1] else "unknown"   # jaldrishti/<device_id>/readings
    row, reason = data_store.parse_message(payload, received_at, default_device=device, default_location=default_location)
    if row is None:
        log.warning("rejected message on %s: %s", topic, reason)
        _log_rejected(topic, reason, payload)
        return False
    data_store.append_raw_rows([row])
    return True


def make_client(client_id):
    import paho.mqtt.client as mqtt
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)   # paho-mqtt 2.x
    except AttributeError:
        return mqtt.Client(client_id=client_id)                                       # paho-mqtt 1.x


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_env()
    s = settings()
    client = make_client(s["client_id"])
    if s["username"]:
        client.username_pw_set(s["username"], s["password"])
    if s["tls"]:
        client.tls_set()

    def on_connect(client, userdata, flags, rc, properties=None):
        failed = getattr(rc, "is_failure", None)
        failed = (rc != 0) if failed is None else failed
        if failed:
            log.error("connection refused: %s", rc)
            return
        log.info("connected to %s:%s, subscribing to %s", s["host"], s["port"], s["topic"])
        client.subscribe(s["topic"])      # re-subscribes automatically after every reconnect

    def on_disconnect(client, userdata, *args):
        log.warning("disconnected from broker, will retry")

    def on_message(client, userdata, msg):
        try:
            ok = handle_payload(msg.payload, msg.topic, s["default_location"])
            if ok:
                log.info("saved reading from %s", msg.topic)
        except Exception:                 # never let one bad message stop the subscriber
            log.exception("could not process message on %s", msg.topic)

    client.on_connect, client.on_disconnect, client.on_message = on_connect, on_disconnect, on_message
    client.reconnect_delay_set(min_delay=1, max_delay=60)
    log.info("writing to %s (Ctrl+C to stop)", config.RAW_READINGS_PATH)
    try:
        client.connect_async(s["host"], s["port"], keepalive=60)
        client.loop_forever(retry_first_connection=True)
    except KeyboardInterrupt:
        log.info("stopped")
        client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
