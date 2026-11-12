"""Independent verification by an authorised reviewer. Model output can never create a verified finding."""
import csv
import hmac
import os
import uuid
import pandas as pd
from . import config

COLUMNS = ["review_id", "event_key", "site_id", "reviewer_name", "organisation",
           "evidence_type", "evidence_note", "decision", "recorded_at"]
EVIDENCE = ("lab", "field", "record", "other")
DECISIONS = ("verified", "not_confirmed")
MIN_NOTE = 20


def pin_configured():
    return bool(os.getenv("JALDRISHTI_REVIEWER_PIN"))


def load_reviews(path=None):
    path = path or config.REVIEWS_PATH
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(path, dtype=str, keep_default_na=False, on_bad_lines="skip", encoding="utf-8-sig")
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = ""
    return df[COLUMNS]


def verified_keys(site_id=None, path=None):
    """Event keys whose most recent review decision is 'verified'."""
    df = load_reviews(path)
    if site_id is not None:
        df = df[df["site_id"] == site_id]
    if df.empty:
        return set()
    latest = df.sort_values("recorded_at").groupby("event_key").tail(1)
    return set(latest[latest["decision"] == "verified"]["event_key"])


def record_review(event_key, site_id, name, organisation, evidence_type, note, decision, pin, path=None, now=None):
    """Returns a status code: disabled, bad_pin, short_note, invalid or saved."""
    expected = os.getenv("JALDRISHTI_REVIEWER_PIN", "")
    if not expected:
        return "disabled"
    if not hmac.compare_digest(str(pin), expected):
        return "bad_pin"
    note, name = " ".join(str(note).split()), " ".join(str(name).split())
    if len(note) < MIN_NOTE or not name:
        return "short_note"
    if evidence_type not in EVIDENCE or decision not in DECISIONS:
        return "invalid"
    path = path or config.REVIEWS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    from .observations import clean_text
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(COLUMNS)
        w.writerow([uuid.uuid4().hex[:12], event_key, clean_text(site_id, 80), clean_text(name, 120),
                    clean_text(organisation, 120), evidence_type, clean_text(note, 1000), decision,
                    now.strftime("%Y-%m-%dT%H:%M:%SZ")])
    return "saved"
