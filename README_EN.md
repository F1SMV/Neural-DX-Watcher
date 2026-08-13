# ⚡ Neural DX Watcher — v12.0

**DX Cluster Dashboard & Advanced Radio Analysis Engine**

A local web application for DX monitoring and radio analysis, designed for the demanding amateur radio operator.  
Built to **observe**, **understand** and **step back** — not to generate visual noise.

---

## ⚙️ Initial Setup — Set Your Callsign

Before launching the application, you can **either**:

### Option 1: Edit webapp.py (one time only)

Edit `webapp.py` and modify this line (around line ~89):

```python
MY_CALL = "F1SMV"  # ← Replace with YOUR callsign
```

Then restart Flask. Your configuration is now **saved locally** in `data/config.json` — it persists across restarts and updates.

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
- maintains a **usable memory** of activity
- offers **multiple reading levels**, from live monitoring to strategic analysis
- **predicts** probable openings based on your activity and missing DXCCs, with **measured reliability** (not an arbitrary display)
- accessible via **secure HTTPS** (reverse proxy + Let's Encrypt) for remote use

> The goal is not to see a lot,  
> but to **see clearly**.

---

## 🖥️ Main Pages

### 1️⃣ **Index** — Real-time & Operator Tracking

Immediate observation page. It displays:
- the live spot stream
- active bands
- wanted DX
- solar indices (SFI, A-index, K-index)
- **surge** activity signals (HF, 6m and 2m)

👉 **Goal: know what's happening right now.**

---

### 📡 **WATCHLIST · Tracking** Panel

Built to answer a simple need:
> *"I wasn't at my desk — what did I miss?"*

- based on the watchlist
- uses in-memory history
- shows the latest spots per callsign

Philosophy:
- ❌ not a raw log
- ❌ not a massive dump
- ✅ a catch-up tool
- ✅ designed for the human operator

---

### 📶 **MY SIGNAL** Panel — PSK Reporter Self-monitoring *(v10.5)*

> *"Who's hearing me, where, with what SNR?"* — without ever leaving the app.

- Source: PSK Reporter API, queried via JSONP
- All bands HF/VHF/UHF, all digital modes (FT8/FT4/WSPR/JT65/JS8/MSK144)
- Receiver callsign, mode, frequency, distance, report age, color-coded SNR
- **Data freshness display**: "PSK update Xs ago · next possible in Ys" *(v11.3)*
- Integrated in **all 3 modes** (CLASSIC, SMART, COCKPIT)

**⏱️ Délai temps réel :** Après un QSO, ton call apparaît typiquement en **2-3 minutes** (limité par l'agrégation PSK Reporter elle-même, pas par Neural DX Watcher). Le backend interroge PSK Reporter toutes les 90 secondes.

👉 **Instant antenna testing, verification before calling into a pileup.**

---

### 2️⃣ **Map** — Observation Map (micro-reading)

Classic map of individual spots:
- each point = **one station**
- immediate geographic representation
- instant vision
- **band filter**: displays only selected band *(v11.3)*
- **"WHO HEARS ME"** mode: stations receiving you with great-circle envelope

👉 **Goal: see where it's happening.** The Map page is an **execution tool**.

---

### 3️⃣ **AI Insight** — Analysis & Deferred META ANALYSIS *(formerly "Analysis", renamed in v10.2)*

A deliberately **non-real-time** tool, based on application log analysis. Available at `/ai-insight`.

👉 **A tool for stepping back**, not a gimmick.

---

### 4️⃣ **World** — Forecast & Anomalies

The **World** page is **fundamentally different** from the Map page.

| Page  | Nature                | Question                                        |
| ----- | --------------------- | ------------------------------------------------ |
| Map   | Raw observation       | Who is active right now?                        |
| World | Interpreted analysis  | Where is propagation abnormally favorable?      |

- displays **zones**, not stations
- spatio-temporal clustering
- noise filtering
- controlled refresh

👉 **World decides, Map executes.**

---

### 5️⃣ **Briefing**

Updated every 12 hours with essential DX information. Callsigns can be added to the watchlist automatically. You won't miss any expedition: as soon as a call is spotted, it appears in yellow in the DX spots panel.

---

### 6️⃣ **Satellites**

Real-time tracking of amateur satellites (AO-73, AO-91, AO-92, ISS, RS-44, SO-50, FO-29, PO-101…). Local computation via **sgp4**, next passes (AOS/TCA/LOS), **uplink/downlink frequencies** from SatNOGS *(v10.1)*, auto-detected satellite type *(v10.1)*, fixed azimuth calculation *(v10.1)*, JSON OMM TLE format compatible with post-2026 catalog *(v10.2)*, **latitude clipping 70°N/S** on MY SIGNAL envelope *(v11.3)*.

---

📸 Preview

![Dashboard Preview](apercu.png)

---

## 🚀 Installation

```bash
git clone https://github.com/F1SMV/Neural-DX-Watcher.git
cd Neural-DX-Watcher
chmod +x start.sh
./start.sh
```

Available at `http://localhost:8000`

> 💡 A **Raspberry Pi** is recommended for its low power consumption, but the program runs on any Linux PC.

---

## 🔐 Secure HTTPS Installation (Remote Access) — *v11.3*

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

sudo htpasswd -c /etc/nginx/.htpasswd f1smv   # personal password
```

Create `/etc/nginx/sites-available/neuraldx` with reverse proxy configuration on port **8443** (no conflict with your NAS on 443).

### 5. Router
Forward external port **8443** to `192.168.1.81:8443` (TCP).

**Remote access:** `https://f1smv-dxwatcher.duckdns.org:8443` — valid TLS, Nginx Basic Auth + app-level API token.

---

## ⚙️ Technical Architecture

- Backend: Python / Flask
- Frontend: HTML / CSS / JavaScript
- Cluster: Telnet DX Cluster
- Analysis: dedicated Python scripts (`predictor.py`, `dxcc_resolver.py`)
- Storage: memory + local JSON + **SQLite**
- Security: local API token + nginx reverse proxy (v11.3)

No cloud dependency.

---

## 🗂️ Version History

### v12.0 — Major overhaul: enriched history, Weather module, persistent config

- **HISTORY panel redesigned**: switched from "30min/12h" to **"last 5 hours"**, now showing **standout calls by SPD score** (top 5 per hour slot, sorted by rarity), larger characters and orange theme for better readability
- **Persistent configuration**: MY_CALL and user_qra saved to `data/config.json`, automatically restored on every restart — no more re-entering
- **DXCC Opportunities**: automatic polling every 30 min (LoTW active + panel visible)
- **Browser tab title fix**: the page `<title>` was hardcoded to "v11.3" for several versions, never following `APP_VERSION` — fixed to display the current version dynamically

#### 🌦️ New: Weather Module (Phase 1)

New **⛈️ WEATHER** tab — first phase of the module described in
`ARCHITECTURE_METEO.md`. Goal: answer "do weather conditions explain
what I'm observing on the bands?"

- **Local conditions** (Open-Meteo, free, no API key): temperature, pressure, humidity, wind, precipitation — QTH position reused automatically, zero extra setup
- **Electrical activity** (community Blitzortung MQTT bridge): lightning strikes within a 300 km radius, distance and direction (bearing + compass point), 1h history
- **Bilingual FR/EN noise/weather correlation**: factual and explanatory summary of ambient radio activity, crossed with recent electrical activity — **always shows the source and reference band** used (a 12dB SNR doesn't mean the same thing on 40m as on 10m) — phrased as observations, never as unproven causal claims
  - **Priority source: WSPR spots** received by stations near the QTH (via [wspr.live](https://wspr.live), free, no API key) — works **24/7**, no dependency on WSJT-X being open
  - **Automatic fallback: WSJT-X SNR** (new `snr_buffer`, fed by *all* received FT8/FT4 decodes, not just the ones shown in the DX Feed) if no WSPR beacons are received in the area
- New API routes: `/api/weather/local.json`, `/api/weather/lightning.json`, `/api/weather/wspr.json`, `/api/weather/correlation.json`
- New page: `/weather`

**⚠️ New Python dependency**: `paho-mqtt` (for the lightning feed)
```bash
pip install paho-mqtt --break-system-packages
```
Without this dependency the app still starts normally — the lightning module disables itself cleanly (warning logged) without affecting the rest of the app.

**⚠️ Lightning feed reliability**: the community Blitzortung bridge has no official service guarantee. If no strikes appear despite a visible storm elsewhere, see the troubleshooting notes in the `lightning_worker()` comments (webapp.py).

Phase 2 (rain radar on map) and Phase 3 (AI synthesis, long-term history) not included — see `ARCHITECTURE_METEO.md`.

### v11.5 — Persistent Configuration · MY_CALL & QRA in data/config.json

- **Config persistence** : MY_CALL and user_qra are now saved to `data/config.json` (persists across restarts)
- No need to re-enter your callsign or locator on every restart or redeploy
- File auto-created on first launch with defaults
- Two configuration methods: edit `webapp.py` OR edit `data/config.json` directly
- New API route `/api/update_mycall` for changing callsign via API (future: integrate in UI)

### v11.4 — DXCC Opportunities · Automatic Polling

- Added automatic polling every 30 minutes for the "DXCC Opportunities" panel (when LoTW active + panel visible)
- Previously frozen without user action; now detects new expeditions automatically

---

### v11.3 — HTTPS Infrastructure · K-index Fixed · Map Filtering · PSK Freshness

#### 🔐 Nginx Reverse Proxy + DuckDNS + Let's Encrypt (Security v11.3)

- Complete reverse proxy configuration on port **8443** (no conflict with NAS 443)
- DNS challenge acme.sh: no port 80/443 required
- Nginx Basic Auth + app-level API token (dual layer)
- Flask remains local 127.0.0.1:8000 (unreachable from Internet)
- Secure remote HTTPS access: `https://f1smv-dxwatcher.duckdns.org:8443`

#### 🗺️ Band Filter on Maps (v11.3)

When you select a band in the **DX SPOTS HF/VHF** panel, the map displays **only that band** (not all bands) → better clarity at a glance.

#### 📶 MY SIGNAL Freshness Display (v11.3)

- Explicit text: *"PSK update Xs ago · next possible in Ys"*
- Makes transparent the 5-min delay that seemed "frozen"
- Displayed in the MY SIGNAL panel and near "WHO HEARS ME" buttons

#### 🔮 K-index Finally Visible (v11.3)

**Root bug:** NOAA parsing expected `[ ["time_tag","Kp",...], [...], ... ]` (table arrays), but NOAA sends `[ {"time_tag":"...","Kp":3.67,...}, ... ]` (dict objects). Result: Kp returned `None` silently, K-index stayed "N/A" indefinitely.

**Complete fix:**
- NOAA parsing now accepts both formats (dict AND arrays)
- A-index fallback if Kp NOAA unavailable: Kp ≈ A/3
- Improved logging to trace fetch failures

#### 📊 PSK Reporter Cache Adjusted (v11.3)

- TTL: 90s → **300s** (5 min = official NOAA policy)
- 90s = 3.3× over-solicitation → silent throttling after weeks
- Frontend polling: 90s → 20s (queries local backend cache, not PSK Reporter directly)
- Dynamic `age_s` recalculation: even in fallback, report age increments correctly

#### 📍 MY SIGNAL Envelope Latitude Clipping (v11.3)

- Great-circle envelope clipped at **70°N/S**
- Eliminates "web effect" over Greenland in Mercator projection

#### 🎨 Interface Corrections (v11.3)

- Label "Analyse" → "AI Insight" in `briefing.html` (consistency)
- Favicon added to `briefing.html`
- API token interception fixed on `briefing.html` (was silently breaking watchlist POSTs)
- Setup ⚙ complete: 31 tiles listed flat (FR labels), backend persistence shared

---

### v11.2 — Critical Fixes: META ANALYSIS, AI Insight, Satellites

#### 🐛 500 Error on META ANALYSIS — Missing Analyzer Script

The `tools/` directory and `tools/log_meta_analyzer.py` script simply didn't exist on the server — the `POST /api/meta/run` route was failing systematically. Complete rewrite of the missing script.

#### 🔧 AI Insight Page — Native `confirm()`/`alert()` Finally Replaced

Native browser popups (`confirm()`, `alert()`) were still present in production. Fixed: inline HTML dialog.

#### ⏳ Satellites Page — Loading Indicator

The first position computation call (TLE + sgp4) can take up to 45 seconds after a server restart. Added an explicit loading indicator.

---

### v11.1 — Security Level 2

- Local API token (`X-API-Token`), generated in `data/api_token.txt` (chmod 600)
- Global `fetch()` interceptor on frontend

### v11.0 — Predictor.py Refactor, dxcc_resolver.py, Security Hardening

### v10.5 → v10.0 — Previous Versions

Earlier versions are not documented here to avoid cluttering the documentation.  
See the full commit history on GitHub: 👉 https://github.com/F1SMV/Neural-DX-Watcher/commits/main

---

## 👤 Author

Developed by **F1SMV – Eric**  
with the assistance of Claude (Anthropic)  
for the amateur radio community.  
Contact: @f1smv on X
