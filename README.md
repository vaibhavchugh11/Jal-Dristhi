# JalDrishti

JalDrishti is a water-quality monitoring project built around an ESP32-based buoy. It uses five sensors to measure pH, turbidity, TDS, dissolved oxygen and temperature.

We built a dashboard to make this data useful to different people:

- **Community:** A simple view for residents and fishing communities.
- **Government:** Detailed readings, trends and alerts about unusual changes in water quality.
- **Firms:** A way for companies to enter their own water-quality limits and compare them with the readings.

The dashboard supports English, Hindi and Marathi.

## Running the project

You'll need Python 3.10 or newer.

1. Install Python from https://www.python.org/downloads/.
2. Open the project folder in File Explorer.
3. Click the address bar, type cmd and press Enter.
4. Run setup_windows.bat.

Once setup is complete, double-click run_app.bat in the project folder to start the dashboard.

Alternatively, open Command Prompt in the project folder and run .venv\Scripts\activate followed by streamlit run app.py.

It should open at http://localhost:8501.

## Adding data

The dashboard currently includes synthetic demo data so that its different features can be explored without a connected buoy.

To use actual readings, you can add a CSV file at data/raw/readings.csv.

The required columns are received_at, device_id, location_id, timestamp, ph, turbidity_ntu, tds_ppm, do_mg_l and temperature_c.

The project also supports receiving data from an ESP32 through MQTT. More details are in docs/ESP32_CONNECTION.md.

## Project structure

- app.py – Main dashboard
- jaldrishti/ – Dashboard logic, calculations and translations
- assets/ – Logo and other visual assets
- data/ – Data and configuration files
- docs/ – Project documentation
- tests/ – Automated tests

## A note about the prototype

JalDrishti is still under development and has not been validated through field testing. Demo readings are synthetic and are clearly labelled.
The company compliance feature compares readings against limits entered by the company itself. It is a screening tool, not a legal compliance assessment.
