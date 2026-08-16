# ⚡ Neural DX Watcher — v12.1

**DX Cluster Dashboard & Advanced Radio Analysis Engine**

A local web application for DX monitoring and radio analysis, built for demanding amateur radio operators.  
Designed to **observe**, **understand**, and **step back** — not to generate visual noise.

---

## ⚙️ Initial Setup — Set Your Callsign

Before launching the application, you can **either** :

### Option 1: Edit webapp.py (once)

Edit `webapp.py` and change this line (~line 89):

```python
MY_CALL = "F1SMV"  # ← Replace with YOUR callsign
```

Then restart Flask. Configuration is now **saved locally** in `data/config.json` — it persists across restarts and updates.

### Option 2: Edit data/config.json directly

Once launched, the app automatically creates `data/config.json`. You can edit it directly:

```json
{
  "my_call": "F1SMV",
  "user_qra": "JN23",
  "timestamp_utc": "2026-01-01T00:00:00"
}
```

Save and restart Flask.

---

## 🧭 Overview

**Neural DX Watcher** is a local web application that:

- connects to one or more **DX Clusters (Telnet)**
- displays **real-time spots** (HF / VHF / UHF)
- integrates **solar indices** (SFI, A, Kp…)
- maintains an **actionable memory** of activity
- offers **multiple reading levels**, from live to strategic analysis
- **predicts** probable openings based on your activity and missing DXCCs
- includes a complete **Weather Radio module** (propagation, lightning, WSPR, beacons)
- accessible via **secure HTTPS** (reverse proxy + Let's Encrypt) for remote use

> The goal is not to see a lot,  
> but to **see accurately**.

---

## 🖥️ Main Pages

### 1️⃣ **Index** — Real-time & operator tracking

Immediate observation page displaying:
- live spot feed
- active bands
- wanted DX
- solar indices (SFI, A-index, K-index)
- activity **surge** signals (HF, 6m and 2m)

### 📡 **WATCHLIST · Tracking**

> *"I wasn't at the screen: what did I miss?"*

- watchlist-based
- uses in-memory history
- displays last spots by callsign

### 📶 **MY SIGNAL** — PSK Reporter self-monitoring

> *"Who hears me, where, with what SNR?"* — without leaving the application.

- Source: PSK Reporter API (JSONP), 5-min cache (official server limit)
- All HF/VHF/UHF bands, all digital modes (FT8/FT4/WSPR/JT65/JS8/MSK144)
- Receiver callsign, mode, frequency, distance, report age, color-coded SNR

---

### 2️⃣ **Map** — Observation map

Classic **individual spot** map:
- each point = **one station**
- **band filter**: shows only the selected band
- **"WHO HEARS ME"** mode: receiving stations with great circle envelope

---

### 3️⃣ **AI Insight** — Deferred analysis

Deliberately **non-real-time** tool, based on log analysis.

---

### 4️⃣ **World** — Forecast & Anomalies

| Page  | Nature                | Question                                          |
| ----- | --------------------- | ------------------------------------------------- |
| Map   | Raw observation       | Who is active right now?                         |
| World | Interpreted analysis  | Where is propagation unusually favorable?        |

---

### 5️⃣ **Briefing**

Automatic update every 12 hours. Direct integration of calls into the watchlist.

---

### 6️⃣ **Satellites**

Real-time amateur satellite tracking. Local calculation via sgp4, next passes AOS/TCA/LOS, uplink/downlink frequencies from SatNOGS, JSON OMM TLE format.

---

### 7️⃣ **⛈️ Weather Radio** *(v12.0–v12.1)*

Full weather / propagation correlation module. See dedicated section below.

---

## 🌦️ Weather Radio Module — `/weather`

### Purpose

Answer: *"Do current weather conditions explain what I'm observing on the bands?"*

### Available Panels

**Global Synthesis** — HF/VHF heuristic gauge (analog S-meter dial). Displays `—` if a data source is missing, never an invented value. Heuristic index, not a calibrated physical measurement.

**Electrical Activity** — Blitzortung lightning strikes within 300 km radius, Leaflet map centered on QTH, dynamic markers by age (pulsing red < 5 min, orange < 30 min, grey > 30 min). MQTT subscription to 9 geohash cells (3×3 grid around QTH) to catch strikes in neighboring cells.

**Current Conditions** — Two tabs:
- *HF*: temperature (red ≥ 30°C, orange ≥ 25°C), pressure (red < 1000 hPa), 2h barometric trend (↓ rapid drop = degradation risk), humidity, wind, precipitation
- *VHF/UHF*: tropo/ducting index (heuristic: surface/850hPa temperature inversion + humidity + CAPE), 300hPa wind, CAPE, WSPR 2m confirmation within 300 km

**Noise / QRN** — Noise/lightning correlation with ham radio vocabulary (QRN, S-point equivalents). 4-level gauge: Calm / Elevated / Disturbed / Stormy. **Priority source: WSPR spots from stations near QTH** (wspr.live, 24/7, no WSJT-X dependency). Automatic fallback to WSJT-X SNR if sparse beacon area. HF and VHF WSPR separated (different dynamics).

**Quick VOACAP** — MUF/LUF prediction for a specific path (zone selector: Europe, Americas, Asia, Oceania, Africa). Color-coded reliability mini-bars by HF band. Explicit note: this prediction concerns a single path and may legitimately differ from observed global activity.

**Band Activity (24h)** — Real count from the cluster feed, HF and VHF separated, color-coded bars by band.

**VHF/UHF/SHF Beacons Received** — Beacons spotted by stations within 300 km of QTH over the last 3 hours, from the DX cluster feed. Monthly automatic update of the reference list from [dl0tud.tu-dresden.de/beacons](https://dl0tud.tu-dresden.de/beacons) (DJ5CW, Fabian Kurz, TU Dresden). Known beacons are marked ★. If the update fails, the local file is preserved and a warning is displayed.

### Data Sources

| Source | Usage | Cost |
|--------|-------|------|
| [Open-Meteo](https://open-meteo.com) | Local conditions (temp, pressure, CAPE, 300hPa wind…) | Free, no key |
| Blitzortung MQTT | Real-time lightning | Free, community |
| [wspr.live](https://wspr.live) | HF/VHF WSPR activity (ClickHouse SQL) | Free, no key |
| VOACAP Online | HF propagation prediction | Free |
| dl0tud.tu-dresden.de | VHF/UHF/SHF beacon reference list | Free |

### Additional Dependency

```bash
pip install paho-mqtt --break-system-packages
```

Without `paho-mqtt`, the application starts normally — the lightning module disables cleanly (warning log).

### Important Honesty Notes

- The tropo/ducting index is a **simplified heuristic** (not a complete physical model)
- The Synthesis gauge is a **visual reference**, not a calibrated measurement
- If 0 WSPR spots and WSJT-X not connected → displays `—`, never an invented value
- If 0 lightning strikes → **may mean no storm in range OR the community MQTT broker temporarily unavailable** (Blitzortung is an unofficial community service)
- If 0 beacons in the Beacons panel → **no nearby operator has spotted a known beacon — does not mean no opening**

---

## 🚀 Installation

```bash
git clone https://github.com/F1SMV/Neural-DX-Watcher.git
cd Neural-DX-Watcher
chmod +x start.sh
./start.sh
```

The application will be accessible at `http://localhost:8000`

> 💡 A **Raspberry Pi** is recommended for low power consumption.

---

## 🔐 Secure HTTPS Installation (remote access)

### 1. Get a DDNS domain
Go to [duckdns.org](https://www.duckdns.org), create a free subdomain, get your token.

### 2. Install acme.sh
```bash
curl https://get.acme.sh | sh -s email=your@email.com
source ~/.bashrc
```

### 3. Generate a Let's Encrypt certificate (DNS challenge)
```bash
export DuckDNS_Token="YOUR_TOKEN"
~/.acme.sh/acme.sh --issue --dns dns_duckdns -d f1smv-dxwatcher.duckdns.org
```

### 4. Configure nginx (reverse proxy)
```bash
sudo apt install nginx apache2-utils
sudo mkdir -p /etc/nginx/ssl
~/.acme.sh/acme.sh --install-cert -d f1smv-dxwatcher.duckdns.org \
  --key-file       /etc/nginx/ssl/dxwatcher.key \
  --fullchain-file /etc/nginx/ssl/dxwatcher.crt \
  --reloadcmd      "sudo systemctl reload nginx"

sudo htpasswd -c /etc/nginx/.htpasswd f1smv
```

Forward external port **8443** to `192.168.1.81:8443` (TCP).  
**Remote access:** `https://f1smv-dxwatcher.duckdns.org:8443`

---

## ⚙️ Technical Architecture

- Backend: Python / Flask
- Frontend: HTML / CSS / JavaScript (SortableJS, Leaflet, IBM Plex Mono, Space Grotesk)
- Cluster: Telnet DX Cluster
- Analysis: `predictor.py`, `dxcc_resolver.py`
- Storage: memory + local JSON + SQLite
- Security: local API token + nginx reverse proxy
- MQTT: paho-mqtt (Blitzortung lightning)

No cloud dependencies.

---

## 🗂️ Version History

### v12.1 — Weather Module: Critical Fixes & VHF/UHF/SHF Beacons

#### 🌩️ Critical Fix: Blitzortung MQTT Topic Format (2026-08-14)

The Blitzortung broker changed its MQTT topic format in production — geohash characters are now slash-separated (`blitzortung/1.1/s/p/e/#`) instead of concatenated (`blitzortung/1.1/spe/#`). The broker accepted the TCP connection and returned CONNACK=0 but published **nothing** on the old topics — silent failure, zero data received. Fix: `"/".join(gh)` in `_lightning_on_connect()`.

#### 🌩️ Fix: Geohash Neighbor Cells

A precision-3 geohash cell covers ~156×156 km. Subscribing to only one cell missed strikes in adjacent cells, even 60 km from QTH. Fix: subscription to a 3×3 grid (QTH + 8 neighboring cells, 9 MQTT topics total).

#### 🛰️ VHF/UHF/SHF Beacons Panel

New panel in the Weather page showing beacons **actually spotted** by stations within 300 km of QTH:

- **Real-time data**: from the already-connected DX cluster feed. Associated fix: `spot_history` was hardcoding `"de": None` — now captures the spotter's callsign (`de_call`) and distance to QTH (`de_dist_km`) from the cluster line `DX de <SPOTTER>:`
- **Reference list**: monthly automatic update from [dl0tud.tu-dresden.de/beacons](https://dl0tud.tu-dresden.de/beacons) (CSV by DJ5CW / Fabian Kurz, TU Dresden). Semicolon-separated parsing, deduplication by call, QRT filtering. On failure, local file is preserved and an error message appears in the interface
- Known beacons (in the reference list) are marked ★

#### 🧭 Fix: `spot_history` Spotter Field

The `"de"` column in `spot_history` had been hardcoded to `None` since the beginning, even though the spotter's callsign is available in the raw cluster line. Full fix: extraction of `de_call` and calculation of `de_dist_km` (spotter ↔ QTH distance). Improves not only the Beacons panel but any future analysis requiring spotter geolocation.

#### 🎨 Weather Page Visual Redesign

"Instrument Panel" direction: graphite background + amber/teal dual accent (replacing the single cyan), Space Grotesk + IBM Plex Mono fonts, instrument-bezel style panels (top highlight line, rivets). Global Synthesis gauge replaced by an analog S-meter dial (180° arc, colored zones, animated needle).

#### 🔗 Navigation

`⛈️ Météo` link added to `ai_insight.html`, `briefing.html`, `map.html`, `world.html`, `satellites.html`. Also fixed `/briefing.html` → `/briefing` route in `map.html` and `world.html`.

#### 🔢 Fix: index.html Version

A second hardcoded `V11.3` in the visible header of `index.html` (different from the `<title>` already fixed in v12.0) — fixed to follow `{{ version }}`.

---

### v12.0 — Weather Module Phase 1, Persistent Config, WSPR

- **Weather Module** (`/weather` page): local Open-Meteo conditions, Blitzortung MQTT lightning, WSPR noise/QRN correlation, Quick VOACAP, 24h band activity
- **WSPR as priority source**: spots from stations near QTH via wspr.live (24/7, no WSJT-X needed). HF and VHF separated. Automatic fallback to WSJT-X SNR
- **Persistent config**: MY_CALL and user_qra in `data/config.json`
- **Title fix**: hardcoded `<title>` as `v11.3` corrected

### v11.3 — HTTPS · K-index · PSK Reporter · Band Filters

- nginx reverse proxy + DuckDNS + Let's Encrypt (port 8443)
- Fix NOAA K-index parsing (dict vs array format)
- PSK Reporter 300s cache (official limit)
- Band filter on Map/World maps
- Local API token `X-API-Token`

### v11.0–v11.2 — Security, Critical Fixes

- Refactored `predictor.py` and `dxcc_resolver.py`
- Local API token, nginx reverse proxy
- Fix META ANALYSE (missing script)
- Fix AI Insight (native popups)
- Satellite loading indicator

### v10.0–v10.5 — Earlier Versions

Full history: 👉 https://github.com/F1SMV/Neural-DX-Watcher/commits/main

---

## 👤 Author

Developed by **F1SMV – Eric**  
with the assistance of Claude (Anthropic)  
in service of the amateur radio community.  
Contact: @f1smv on X
