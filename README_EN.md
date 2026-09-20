# Neural DX Watcher v12.7

**A smart DXCC hunting web app for the modern radio amateur**, built on Flask + SQLite, running on Raspberry Pi 5 at `192.168.1.81:8000`.

User: **F1SMV** (QTH: JN23, La Seyne-sur-Mer, 43.076°N 5.873°E)  
Repository: [F1SMV/Neural-DX-Watcher](https://github.com/F1SMV/Neural-DX-Watcher)

---

## 📸 Overview
![Dashboard Overview](apercu.png)

---

## 🎯 Main Features

### DXCC Hunt Mode (v12.4) ✨
Dedicated **`/hunt`** route — full-screen interface optimized for real-time hunting:
- **Target #1 hero card**: large country presentation, flag 🇵🇬, capital, population, UTC offset (live via REST Countries API, 30-day cache)
- **Leaflet world map** (320px, cockpit 6m pattern): QTH + DX station + dashed link, secondary markers weighted by SPD
- **Clickable secondary list**: top 15 targets sorted by SPD, click = zoom on map
- **🏴 EXPÉ badge** (v12.7): highlights active DX expeditions in orange in the DX Wanted table, auto-crossed with ng3k briefing
- **Real-time band filter**, 15s refresh
- **localStorage tracking**: follow interesting calls

### AI Insight (v12.5) ✨
Dedicated **`/ai_insight`** route — behavioral analysis dashboard, fully bilingual FR/EN:
- **Recent Activity**: hour-by-hour sparkline (24h), peak and current hour highlighted
- **Next Hours**: past activity frequency on upcoming slots — bilingual explanations, low-sample slots flagged in orange
- **When It Opens**: weekday × UTC hour heatmap
- **Band Trends**: recent vs. previous period comparison
- **HF Predictions VOACAP (v12.6)**: **8 bands × 24 hours** grid (v12.7: 12m, 17m, 30m added)
- AJAX refresh every 5 min, maturity bar every minute
- Drag & drop panels (v12.7), order persisted in localStorage

### HF Predictions VOACAP (v12.6) ✨
Fifth panel of the AI Insight page — point-to-point predictions via the **VOACAP** engine (US gov, open source):
- **Free-form input**: callsign (`JA1ABC`), DXCC prefix (`ZS`, `VK`, `EA8`…) or country name — automatic resolution
- **Local DXCC table** (~60 entities, instant) + Nominatim/OSM geocoding fallback
- **Band × hour matrix**: 8 bands (10m→80m) × 24 UTC hours, shaded by REL
- **Current-hour hero**: recommended band right now, REL% and SNR at a glance
- **DX shortcuts**: USA, Japan, Australia, Brazil, South Africa in one click
- **24h cache**: stored in `data/voacap_cache.sqlite`

**VOACAP setup (one time only):**
```bash
bash ~/.claude/skills/voacap/scripts/setup.sh
```

### Propagation & Forecasting
- **VOACAP Rapid**: precise HF path to selected zone (5min)
- **Tropospheric indicators**: 850hPa inversion, humidity, CAPE
- **Blitzortung MQTT**: real-time lightning (3×3 grid around QTH), RF/QRN correlation
- **WSPR global**: spots per band, individual callsigns + real QTH distances (v12.7), 2m radar confirmation

### Satellites & Beacons
- **Co- and counter-aperture visibility**: SGP4, 48h horizon, ≥30s overlap
- **VHF/UHF/SHF beacons**: 62 IARU beacons, monthly auto-update from dl0tud.tu-dresden.de
- **SatNOGS for frequencies**

### LoTW Management & Stats
- **Native LoTW integration**: disk cache 6589 QSOs, periodic sync
- **Dxcc_hunt.py**: scoring engine per band, rarity + distance, internal database
- **ARRL / ng3k Briefing**: recent DX news, active expeditions crossed with spots

### Backend Architecture
- **`webapp.py`**: 7700+ lines, Python 3.13, Flask, SQLite
- **`analytics.py`**: autonomous AI Insight engine, dedicated `data/analytics.sqlite`
- **`voacap_adapter.py`**: VOACAP wrapper + 24h SQLite cache
- **`country_meta.py`**: country enrichment (flag, capital, population, TZ) — 30-day cache
- **`dxcc_hunt.py`**: pure DXCC Hunt logic (injectable, testable, 13/13 tests ✅)
- **`ntfy_alerts.py`**: desktop/email notifications (v10.0, complete)

---

## v12.7 — Detailed Changelog

### New Features
- **🏴 EXPÉ badge in DX Wanted** (`index.html`, `webapp.py`)
  - Automatic cross-check: cluster spots ↔ ng3k briefing — any call active in both sources gets an orange badge in the DX Wanted (Top 10) table
  - Callsigns extracted from ng3k titles (prefix ≥ 4 chars with digit, end date in the future)
  - Exposed via `wanted.json` → `expedition_calls: {call: country}`

- **VOACAP: 8 bands** (up from 5) — 12m (24.9 MHz), 17m (18.1 MHz), 30m (10.1 MHz) added in `ai_insight.html` and default freqs of `/api/voacap/predict`

- **AI Insight drag & drop**: panels rearrangeable by drag (SortableJS), order persisted under `ai_insight_panel_order` localStorage key

- **WSPR 2m confirmation enriched**: individual callsigns and real TX→QTH distances (Haversine) displayed instead of an anonymous count

### Fixes
- **DX geolocation**: fixed KH8→Michigan bug (American Samoa now correctly placed) and 8 Pacific/Caribbean entities (KH0 Mariana, KH1 Baker-Howland, KH2 Guam, KH4 Midway, KH5 Palmyra, KH7K Kure, KH8/s Swains, 5W Samoa)
  - Bug 1: `CALLSIGN_ZONES` had `'AH': USA` mapping all AH* to Missouri
  - Bug 2: step 3 of the resolver (zone digit extraction) wrongly applied to KH*/AH*/KP*
  - Bug 3: post-parsing cty.dat overrides for entries with incorrect longitude signs

### Infrastructure & Cleanup
- `APP_VERSION` → `'12.7'`
- `defaultdict` removed from imports (unused)
- `start.sh`: `paho-mqtt` added to dependency check, `telnetlib3` removed (not in `requirements.txt`)
- Full webapp.py audit: 252 functions, 0 syntax errors, Haversine calculations validated

---

## v12.6 — Detailed Changelog

### New Features
- **HF Predictions VOACAP panel** in AI Insight (`ai_insight.html`)
  - Band × hour matrix (10m→80m / UTC 00-23), shaded by circuit reliability (REL)
  - Current-hour hero: recommended band + REL% + SNR at a glance
  - Unified input: callsign, DXCC prefix or country name → auto-resolution
  - 5 DX shortcuts, 24h SQLite cache, graceful fallback if `voacapl` not installed

- **`voacap_adapter.py`** (new module): wraps `voacap_predict.py` (Reid skill), VOACAP output parser, autonomous SQLite cache
- **Route `POST /api/voacap/predict`**: SSN auto-derived from current NOAA SFI if not provided

### Cleanup
- `APP_VERSION` → `'12.6'`
- Removed orphaned route `@app.route("/ai.html")`
- `requirements.txt` fully rewritten: exact dependencies, VOACAP setup notes

---

## v12.5 — Detailed Changelog

### New Features
- **Redesigned AI Insight page** (`ai_insight.html`, `/ai_insight` route)
  - Fully autonomous `analytics.py` module: dedicated `data/analytics.sqlite`
  - 4 dynamic panels: Recent Activity, Next Hours, When It Opens, Band Trends
  - AJAX refresh every 5 min, maturity bar every minute

### UX Improvements
- **"Next Hours" panel clarity**: bilingual FR/EN subtitles, low-sample slots (< 5 obs.) flagged in orange, callout accents switched to orange

### Fixes
- **`dxcc_hunt.py`**: physically impossible distances filtered out
- **`weather.html`**: CARTO → Esri Dark Gray Canvas migration, fixed `{z}/{y}/{x}` tile ordering
- **`hunt.html`**: Leaflet map stabilization (staggered `invalidateSize`, zero gray borders)

---

## v12.4 — Detailed Changelog

### New Features
- **Complete DXCC Hunt mode** (routes `/hunt`, `/api/hunt/data`)
  - Sort by continuous SPD score (rarity + distance + split + mode)
  - Target #1 enriched (flag, capital, population, UTC offset)
  - Multi-target secondary markers on map, weighted by SPD
  - Clickable navigation: click secondary target → zoom map

- **`country_meta.py`**: DXCC country enrichment (REST Countries API v3.1, 30-day cache, graceful fallback)
- **🎯 HUNT nav link** + blinking indicator (20s animation), localStorage watchlist

### Critical Fixes
- DXCC Hunt sort: replaced boolean `is_rare` with continuous SPD score
- Hunt Leaflet map: `worldCopyJump: true`, `center: QTH`, `zoom: 2`, zero gray borders

### Tests
- 13/13 unit tests `dxcc_hunt.py`
- 16/16 unit tests `country_meta.py`

---

## 🚀 Quick Start

### Requirements
- Python 3.13 + venv
- Raspberry Pi 5 (or Linux x64)
- Network port: 8000 (Flask)

### Deploy on Pi
```bash
cd ~/Spot-Watcher-DX
cp webapp.py country_meta.py dxcc_hunt.py voacap_adapter.py .
cp templates/*.html templates/
pkill -f "python.*webapp.py"
bash start.sh
```

### Verify
```bash
curl http://192.168.1.81:8000/hunt
curl 'http://192.168.1.81:8000/api/hunt/data?band=20m'
curl -s 'http://192.168.1.81:8000/wanted.json' | python3 -m json.tool | grep expedition
```

---

## 📊 Key Modules

| File | Role | Status |
|------|------|--------|
| `webapp.py` | Flask backend | ✅ v12.7 |
| `analytics.py` | AI Insight engine (autonomous, own cache) | ✅ v12.5 |
| `voacap_adapter.py` | VOACAP wrapper + 24h cache | ✅ v12.6 |
| `ai_insight.html` | AI Insight UI + HF Predictions (bilingual FR/EN) | ✅ v12.7 |
| `index.html` | Dashboard + DX Wanted + Expé badge | ✅ v12.7 |
| `dxcc_hunt.py` | Hunt DXCC engine | ✅ 13/13 tests |
| `country_meta.py` | Country enrichment (30d cache) | ✅ 16/16 tests |
| `hunt.html` | Hunt UI (Leaflet, SPD markers) | ✅ Cockpit 6m |
| `start.sh` | Launch + dependency check | ✅ v12.7 |

---

## 🔧 Advanced Config

### DX Clusters
```python
CLUSTERS = [
    'dxfun.com:8000',
    'dxc.k0xm.net:7300',
    'dxc.nc7j.com:7373',
]
```

### LoTW
- Disk cache: `data/lotw_cache.json`
- Test ADIF: `lotw_debug_qsl.adi` (6589 QSOs)

### Beacons
- Source: `dl0tud.tu-dresden.de/beacons`
- Auto-update monthly
- Local ref: `data/beacons_reference.json`

---

## 📡 Public APIs

```
GET  /hunt                        → Hunt HTML page
GET  /api/hunt/data?band=20m      → Hunt JSON
GET  /wanted.json                 → DX Wanted + expedition_calls
POST /api/voacap/predict          → HF VOACAP predictions
GET  /weather                     → Weather + Blitzortung
GET  /satellites                  → Sat visibility
GET  /api/weather/wspr.json       → WSPR snapshot (callsigns + distances)
```

---

## 🧪 Development

### Tests
```bash
python3 test_dxcc_hunt.py      # 13/13
python3 test_country_meta.py   # 16/16
```

### Pre-deployment check
```bash
python3 -m py_compile webapp.py
node --check templates/ai_insight.html
node --check templates/index.html
```

---

## 📝 License & Credits

- **Code**: F1SMV, MIT — built with Claude AI (Anthropic)
- **Data**
  - Esri Imagery (© Esri)
  - IARU-R1 Beacons (DJ5CW, TU Dresden)
  - REST Countries API v3.1
  - LoTW ARRL
  - Blitzortung MQTT
  - VOACAP (US gov, open source)
  - ng3k.com (DX expeditions)

---

**v12.7** — September 2026  
*"Hunt smarter, not harder"*
