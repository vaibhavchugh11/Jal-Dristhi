"""Community-submitted observations: stored apart from instrument readings and always shown as unverified."""
import csv
import pandas as pd
from . import config

COLUMNS = ["recorded_at", "location_id", "colour", "smell", "dead_fish", "notes"]
COLOURS = ("normal", "brown", "green", "other")
SMELLS = ("none", "unusual")
FISH = ("none", "seen")


def clean_text(text, limit=500):
    s = " ".join(str(text or "").split())[:limit]
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s   # stops spreadsheet formula injection


def add_observation(location_id, colour, smell, dead_fish, notes, path=None, now=None):
    if colour not in COLOURS or smell not in SMELLS or dead_fish not in FISH:
        raise ValueError("invalid observation value")
    path = path or config.OBSERVATIONS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(COLUMNS)
        w.writerow([now.strftime("%Y-%m-%dT%H:%M:%SZ"), clean_text(location_id, 80), colour, smell, dead_fish, clean_text(notes)])


def load_observations(location_id=None, days=None, path=None, now=None):
    path = path or config.OBSERVATIONS_PATH
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(path, dtype=str, keep_default_na=False, on_bad_lines="skip", encoding="utf-8-sig")
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = ""
    df["recorded_at"] = pd.to_datetime(df["recorded_at"], errors="coerce", utc=True)
    if location_id is not None:
        df = df[df["location_id"] == location_id]
    if days is not None:
        now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
        df = df[df["recorded_at"] >= now - pd.Timedelta(days=days)]
    return df.sort_values("recorded_at", ascending=False).reset_index(drop=True)
