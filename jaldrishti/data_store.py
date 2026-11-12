"""Reading and writing local CSV files: raw readings, sites, calibration. Also parses MQTT messages."""
import csv
import json
import math
import pandas as pd
from . import config


def ensure_dirs():
    config.RAW_READINGS_PATH.parent.mkdir(parents=True, exist_ok=True)


def empty_raw():
    return pd.DataFrame({c: pd.Series(dtype=str) for c in config.RAW_COLUMNS})


def load_raw(path=None):
    path = path or config.RAW_READINGS_PATH
    if not path.exists() or path.stat().st_size == 0:
        return empty_raw()
    df = pd.read_csv(path, dtype=str, keep_default_na=False, on_bad_lines="skip", encoding="utf-8-sig")
    for c in config.RAW_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    return df


def append_raw_rows(rows, path=None):
    path = path or config.RAW_READINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=config.RAW_COLUMNS, extrasaction="ignore")
        if new_file:
            w.writeheader()
        for r in rows:
            w.writerow(r)


ALIASES = {"turbidity": "turbidity_ntu", "tds": "tds_ppm", "do": "do_mg_l", "dissolved_oxygen": "do_mg_l",
           "temperature": "temperature_c", "temp": "temperature_c", "temp_c": "temperature_c",
           "device": "device_id", "location": "location_id", "site": "location_id", "time": "timestamp"}
SENSOR_FIELDS = ["ph", "turbidity_ntu", "tds_ppm", "do_mg_l", "temperature_c"]


def _clean_value(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return ""
    return str(v)


def parse_message(payload, received_at, default_device="unknown", default_location="unknown"):
    """JSON message -> (raw row dict, None) or (None, reason). A missing timestamp is replaced by the receive time."""
    try:
        text = payload.decode("utf-8") if isinstance(payload, (bytes, bytearray)) else str(payload)
        data = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return None, f"not valid JSON ({e})"
    if not isinstance(data, dict):
        return None, "JSON must be an object"
    data = {ALIASES.get(k, k): v for k, v in data.items()}
    if not any(k in data for k in SENSOR_FIELDS):
        return None, "no sensor fields found"
    row = {c: _clean_value(data.get(c)) for c in config.RAW_COLUMNS}
    row["received_at"] = received_at
    row["timestamp"] = row["timestamp"] or received_at
    row["device_id"] = row["device_id"] or default_device
    row["location_id"] = row["location_id"] or default_location
    return row, None


def valid_coords(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None
    return lat, lon


def load_sites(path=None):
    path = path or config.SITES_PATH
    cols = ["location_id", "name", "latitude", "longitude", "notes"]
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df[cols]


def load_calibration(path=None):
    path = path or config.CALIBRATION_PATH
    cols = ["device_id", "sensor", "last_calibrated", "method", "next_due", "notes"]
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df[cols]


def load_whi_overrides(path=None):
    path = path or config.WHI_OVERRIDES_PATH
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
