# Neural DX Watcher v12.4

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
- **Target #1 hero card** : large country presentation, flag 🇵🇬, capital, population, UTC offset (live data via REST Countries API, 30-day cache)
- **Leaflet world map** (320px, cockpit 6m pattern) : QTH + DX station + dashed link line, secondary markers weighted by SPD (rarity + distance + split + mode)
- **Clickable secondary list** : top 15 targets sorted by SPD, click = zoom on map, `.active` class on 🎯 HUNT nav link
- **Real-time band filter**, 15s refresh rate
- **localStorage tracking** : follow interesting calls

### Propagation & Forecasting
- **VOACAP Rapid** : precise HF path to selected zone (5min)
- **Tropospheric indicators** : 850hPa inversion, humidity, CAPE
- **Blitzortung MQTT** : real-time lightning (3×3 grid around QTH), RF/QRN correlation
- **WSPR global** : spots per band, fuzzy location, 2m radar confirmation

### Satellites & Beacons
- **Co- and counter-aperture visibility** : SGP4, 48h horizon, ≥30s overlap
- **VHF/UHF/SHF beacons** : 62 IARU beacons, monthly auto-update from dl0tud.tu-dresden.de
- **SatNOGS for frequencies**

### LoTW Management & Stats
- **Native LoTW integration** : disk cache 6589 QSOs, periodic sync
- **Dxcc_hunt.py** : scoring engine per band, rarity + distance, internal database
- **ARRL Briefing** : recent news replacing dxnews.com (HTML scraping)

### Backend Architecture
- **`webapp.py`** : 7500+ lines, Python 3.13, Flask, SQLite
- **`country_meta.py`** : country enrichment (flag, capital, population, TZ) — 30-day cache, zero API calls on repeat
- **`dxcc_hunt.py`** : pure DXCC Hunt logic (injectable, testable, 13/13 tests ✅)
- **`ntfy_alerts.py`** : desktop/email notifications (v10.0, complete)
- **`test_dxcc_hunt.py`, `test_country_meta.py`** : full unit test suites

---

## v12.4 — Detailed Changelog

### New Features
- **Complete DXCC Hunt mode** (routes `/hunt`, `/api/hunt/data`) 
  - Sort by SPD score (signal propagation distance) instead of simple "rare/not rare"
  - Target #1 enriched (flag, capital, population, UTC offset)
  - Multi-target secondary markers on map, weighted by SPD
  - Clickable navigation: click secondary target → zoom map

- **`country_meta.py`** — new DXCC country enrichment module
  - REST Countries API v3.1 requests (free, open)
  - 30-day disk cache (data never changes)
  - Graceful fallback: network failure → cache or `None`
  - Aliases for non-sovereign DXCC entities (Corsica→France, etc.)

- **🎯 HUNT link in complete nav** + blinking indicator (20s animation)
  - localStorage watchlist tracking for interesting calls
  - `/hunt` yellow flash on new opportunity since last visit

### Critical Fixes
- **DXCC Hunt sort** : replaced boolean `is_rare` with continuous SPD score (rarity + distance + split + mode)
- **Hunt Leaflet map** : exact copy of proven cockpit 6m pattern
  - `worldCopyJump: true`, `center: QTH`, `zoom: 2` — **zero gray borders**
  - Staggered invalidateSize `[120, 350, 900]` ms

### Infrastructure & Tests
- **13/13 unit tests** `dxcc_hunt.py`
- **16/16 unit tests** `country_meta.py`
- **Frontend validation** : JS `node --check`, Jinja2 render, Flask `test_client()`

---

## 🚀 Quick Start

### Requirements
- Python 3.13 + venv
- Raspberry Pi 5 (or Linux x64)
- Network port: 8000 (Flask)

### Deploy on Pi
```bash
cd ~/Spot-Watcher-DX

# Copy critical files
cp webapp.py country_meta.py dxcc_hunt.py .
cp hunt.html templates/
cp index.html templates/

# Restart
pkill -f "python.*webapp.py"
bash start.sh
```

### Verify
```bash
curl http://192.168.1.81:8000/hunt
curl 'http://192.168.1.81:8000/api/hunt/data?band=20m'
```

---

## 📊 Key Modules

| File | Role | Status |
|------|------|--------|
| `webapp.py` | Flask backend | ✅ v12.4 |
| `dxcc_hunt.py` | Hunt DXCC engine | ✅ 13/13 tests |
| `country_meta.py` | Country enrichment (30d cache) | ✅ 16/16 tests |
| `hunt.html` | Hunt UI (Leaflet, SPD markers) | ✅ Cockpit 6m |
| `index.html` | Dashboard + 🎯 HUNT nav | ✅ v12.4 |

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
GET /hunt                    → Hunt HTML page
GET /api/hunt/data?band=20m  → Hunt JSON
GET /weather                 → Weather + Blitzortung
GET /satellites              → Sat visibility
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
node --check hunt.html
python3 -m py_compile webapp.py country_meta.py
```

---

## 📝 License & Credits

- **Code** : F1SMV, MIT
- **Data** follow me on X
  - Esri Imagery (© Esri)
  - IARU-R1 Beacons (DJ5CW, TU Dresden)
  - REST Countries API v3.1
  - LoTW ARRL
  - Blitzortung MQTT

---

**v12.4** — September 2026  
*"Hunt smarter, not harder"*
EOFEN
echo "✓ README FR + EN créés"