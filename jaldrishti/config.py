"""Central settings. Anything marked ASSUMPTION is a documented guess to be validated."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("JALDRISHTI_DATA_DIR", ROOT / "data"))
RAW_READINGS_PATH = DATA_DIR / "raw" / "readings.csv"
REJECTED_LOG_PATH = DATA_DIR / "raw" / "rejected_messages.log"
SITES_PATH = DATA_DIR / "sites.csv"
CALIBRATION_PATH = DATA_DIR / "calibration.csv"
OBSERVATIONS_PATH = DATA_DIR / "observations.csv"
REVIEWS_PATH = DATA_DIR / "reviews.csv"
WHI_OVERRIDES_PATH = DATA_DIR / "whi_curves.json"
COMPLIANCE_PATH = DATA_DIR / "compliance_profiles.json"

DISPLAY_TZ = "Asia/Kolkata"
# timestamps without a timezone are read as this zone (set to Asia/Kolkata if your ESP32 sends local time)
NAIVE_TIMESTAMP_TZ = os.getenv("JALDRISHTI_NAIVE_TZ", "UTC")

METHOD_VERSION = "statistical-baseline-v0.1 (no machine-learning model integrated)"

RAW_COLUMNS = ["received_at", "device_id", "location_id", "timestamp",
               "ph", "turbidity_ntu", "tds_ppm", "do_mg_l", "temperature_c"]
PARAMS = ["ph", "turbidity", "tds", "do", "temperature"]
CSV_COLUMN = {"ph": "ph", "turbidity": "turbidity_ntu", "tds": "tds_ppm",
              "do": "do_mg_l", "temperature": "temperature_c"}
UNITS = {"ph": "", "turbidity": "NTU", "tds": "ppm", "do": "mg/L", "temperature": "°C"}
DECIMALS = {"ph": 2, "turbidity": 1, "tds": 0, "do": 2, "temperature": 1}

# ASSUMPTION: physical limits of the sensors/natural waters; check against your datasheets.
# a reading outside these is marked "implausible" (this also catches the DS18B20 error value of -127)
PLAUSIBLE = {"ph": (0, 14), "turbidity": (0, 3000), "tds": (0, 1000),
             "do": (0, 20), "temperature": (-2, 50)}
# identical consecutive readings (count) that suggest a stuck sensor; assumes ~5 min between readings
FLATLINE_N = {"ph": 12, "turbidity": 12, "tds": 12, "do": 12, "temperature": 36}
# smallest spread treated as real, so tiny noise on a very steady sensor doesn't create huge z-scores
MIN_SCALE = {"ph": 0.05, "turbidity": 0.5, "tds": 5.0, "do": 0.1, "temperature": 0.1}

# provisional WHI (weights supplied by the project; temperature is not part of the index)
WHI_WEIGHTS = {"do": 0.395, "ph": 0.256, "turbidity": 0.186, "tds": 0.163}
WHI_BANDS = [(95, "excellent"), (80, "good"), (65, "fair"), (45, "marginal"), (0, "poor")]
# ASSUMPTION: provisional sub-index curves as (value, score 0-100) points, linear in between,
# flat outside the ends. Not derived from a regulation. Freshwater-style limits: tidal or brackish
# sites need their own curves (see data/whi_curves.json in docs/METHODS.md).
WHI_CURVES = {
    "do": [(0, 0), (8, 100)],
    "ph": [(0, 0), (7, 100), (14, 0)],
    "turbidity": [(0, 100), (5, 100), (100, 0)],
    "tds": [(0, 100), (100, 100), (500, 0)],
}

# alert logic (statistical, interpretable)
Z_THRESHOLD = 3.5            # robust z-score beyond which a reading is unusual
PERSIST_N = 3                # consecutive unusual readings (same direction) needed to raise a flag
BASELINE_HOURS = 24          # history used as "normal"
EXCLUSION_HOURS = 1          # most recent hours left out of the baseline so an event can't hide in it
MIN_BASELINE_FRACTION = 0.5  # share of the baseline window that must have data
STALE_AFTER_MINUTES = int(os.getenv("JALDRISHTI_STALE_MIN", "30"))
ANALYSIS_DAYS = 14           # how far back events/baselines are computed
EVENT_MERGE_GAP = 6          # readings; nearby flags are merged into one event
STRENGTH_BANDS = [(10, "high"), (6, "moderate"), (0, "low")]  # by max |z|
UNRELIABLE_IF_FAULTS_AT_LEAST = 3  # sensors with issues that make the whole reading unreliable

LANGUAGES = {"en": "English", "hi": "हिन्दी", "mr": "मराठी"}
# set a language to True once a fluent speaker has reviewed it; the "draft translation" notice then disappears
TRANSLATIONS_REVIEWED = {"en": True, "hi": False, "mr": False}
TTS_LANG = {"en": "en-IN", "hi": "hi-IN", "mr": "mr-IN"}
