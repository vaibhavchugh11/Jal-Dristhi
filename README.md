# JalDrishti

Water-quality monitoring and early-warning prototype for an ESP32 buoy (pH, turbidity, TDS, dissolved oxygen,
temperature). English, Hindi and Marathi. Three views of the same data: **Community** (public, fishers),
**Government / Authority** (detail, warnings, when events happened) and **Firms / Compliance** (company limits).

> Prototype. Not validated in the field. Shows **no real readings** until you supply some. The built-in
> "DEMO DATA" is synthetic and always labelled as such. The app never says water is safe or unsafe and never names a pollutant.

## Windows setup (first time)

1. Install Python 3.10 or newer from https://www.python.org/downloads/ (tick **Add python.exe to PATH**).
2. Open this folder in File Explorer, click the address bar, type `cmd`, press Enter. Then run:
   ```
   setup_windows.bat
   ```
   (or by hand: `python -m venv .venv`, `.venv\Scripts\activate`, `pip install -r requirements.txt`)

## Run

```
run_app.bat
```
or `.venv\Scripts\activate` then `streamlit run app.py`. Your browser opens at http://localhost:8501.

With no data yet the app starts on **DEMO DATA**. In the sidebar you can switch the demo scenario
(normal, unusual change, device offline, sensor faults) to see every state.

## Use your own data

* **CSV:** put a file at `data/raw/readings.csv` with the columns
  `received_at,device_id,location_id,timestamp,ph,turbidity_ntu,tds_ppm,do_mg_l,temperature_c`,
  then choose **My data** in the sidebar and press **Refresh data**.
* **ESP32 over MQTT:** see `docs/ESP32_CONNECTION.md` (broker setup, message format, example sketch), then run `run_mqtt.bat`.
* Site names/coordinates: copy `data/sites.example.csv` to `data/sites.csv` and edit. Leave coordinates blank if unknown (no map is shown then).
* Calibration records: `data/calibration.example.csv` -> `data/calibration.csv`.
* Optional settings: copy `.env.example` to `.env`.

## Tests

```
.venv\Scripts\activate
python -m pytest tests -q
```

## Project layout

```
app.py                      Streamlit entry point (header, language, mode, sidebar)
jaldrishti/
  config.py                 all thresholds, limits, WHI weights/curves (assumptions are marked)
  i18n.py, translations/    en.py / hi.py / mr.py text, date and number formatting
  data_store.py             CSV read/write, MQTT message parsing, sites, calibration
  validation.py             raw -> checked values + quality flags
  alerts.py                 baseline, persistence, events, sensor-fault separation, statuses
  whi.py                    provisional Water Health Index
  quality.py, explain.py    completeness/connection summary; plain-language wording
  observations.py, reviews.py   community notes (unverified) and authorised verification
  reports.py, charts.py     Markdown report; Plotly graphs
  demo_data.py              synthetic DEMO data
  mqtt_subscriber.py        optional MQTT -> CSV bridge
  ui/                       community.py, technical.py, components.py, data_access.py, styles.py
assets/                     logo files (made from your artwork by scripts/make_logo_assets.py)
data/                       readings, sites, calibration, observations, reviews (CSV)
docs/                       ESP32_CONNECTION.md, METHODS.md, TRANSLATIONS.md
tests/                      92 automated tests
```

## On a phone

The layout adapts to small screens (sensor cards two across, finger-sized buttons, settings inside the page instead of a hidden sidebar).
To open it on your phone while it runs on your PC: connect both to the same WiFi, double-click `run_app_for_phone.bat`,
and open `http://<the IPv4 address it prints>:8501` in the phone's browser. Allow Python on **private** networks if Windows asks.
The app has no login, so use trusted WiFi only. In the phone browser use "Add to Home screen" to make an app-like shortcut.
To reach it from anywhere you must host it (for example Streamlit Community Cloud, free); keep real data private first.

## The three views

* **Community:** large cards, plain language, cautious next steps, observations from residents.
* **Government / Authority:** all readings, history, data quality, WHI breakdown, anomaly warnings with start/end time and
  duration, a plain "pattern note" for each event (for example "turbidity and TDS rose together... cause not confirmed"),
  reviewer verification, reports.
* **Firms / Compliance:** a company creates a profile and types in **its own limits** (minimum and/or maximum per parameter,
  compared per reading or as a 1 h / 24 h average, with a policy reference). The app then compares the buoy readings with
  those limits: latest status (within / close to limit / outside), % of readings outside, periods outside with start, end,
  duration and peak, whether an unusual change was detected at the same time, insights, suggested next steps, and a downloadable
  report + CSV. Profiles are saved in `data/compliance_profiles.json`. Nothing is pre-filled.
  It is a rule-based screening (no AI model) and **not** a legal compliance decision, and the buoy measures the water where it floats, not the company's outlet.

## What works (tested)

* Three languages across the whole interface, graphs, alerts and downloadable report. Language switch in the header.
* Community view: large cards, plain explanations, status wording that only describes what the system knows,
  cautious next steps, low-data mode, spoken summary (browser voices), community observations (kept separate, always "unverified").
* Technical view: all readings, history graphs with baseline band and event shading, date ranges, data table with quality flags,
  CSV download, completeness and connection status, calibration table, WHI with component breakdown, anomaly flag with
  contributing parameters, event list, reviewer verification (PIN), report download, methods and limits.
* CSV ingestion with validation (missing vs zero vs implausible vs stuck), duplicate removal, raw/processed separation.
* Alert states: no unusual change / unusual change - investigate / verified (reviewer only) / data unavailable, stale or unreliable.
* MQTT subscriber, tested end to end against a local Mosquitto broker including malformed messages and a broker restart.

## What still needs real data or validation

* Real ESP32 readings. The example sketch is **untested on hardware**; sensor read functions are placeholders.
* Field validation, sensor calibration records and reference-meter comparison.
* WHI curves/thresholds are provisional and **not** derived from BIS/CPCB. Tidal/brackish sites need their own curves.
* Alert thresholds are untuned (no field data), and there is no allowance for daily cycles, tides or rain.
* Hindi and Marathi are drafts and must be reviewed by fluent speakers.
* No login/HTTPS: keep it on a trusted network. Optional audio depends on the browser having a Hindi/Marathi voice.
* No machine-learning model is connected (the SINDy/XGBoost work is separate and not validated on field data).

Details: `docs/METHODS.md`.
