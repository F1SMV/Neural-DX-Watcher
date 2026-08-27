# Neural DX Watcher v12.2

**Web Application for DX Spot Monitoring • Propagation Forecasting • Satellite Tracking**

Raspberry Pi 5 • Flask + SQLite • Amateur Radio  
F1SMV (JN23) • https://github.com/F1SMV/Neural-DX-Watcher

---

## 📋 Overview

Neural DX Watcher aggregates **3 real-time DX clusters** (Telnet), displays propagation via **machine learning** and **VOACAP predictions**, tracks **amateur radio satellites** in real-time, and provides a **cockpit dashboard** for VHF/UHF/HF radio operators.

- ✅ **7200+ lines** Flask/Python + 209 functions
- ✅ **Persistent SQLite** (spots, history, config, LoTW cache)
- ✅ **Real-time MQTT PSK Reporter** + HTTP fallback
- ✅ **Blitzortung** live lightning (3×3 geohash grid)
- ✅ **Satellites**: TLE/passes/covisibility (sgp4)
- ✅ **VHF/UHF Beacons**: official IARU reference + spot history

---

## 🚀 Quick Start

### Requirements
```bash
Python 3.9+
pip install paho-mqtt requests pytz sgp4
```

### Installation
```bash
git clone https://github.com/F1SMV/Neural-DX-Watcher.git
cd Neural-DX-Watcher
bash start.sh
```

**URL**: `http://192.168.1.81:8000`  
**Logs**: stdout (Flask with debug=False)

---

## 🎮 User Interface

### Main Pages

| Page | Function |
|------|----------|
| **Cockpit** (index.html) | 6m radar, DX feed, AZ/EL, real-time spot markers |
| **Weather** (weather.html) | Propagation (VOACAP), Leaflet lightning, beacons, WSPR correlation |
| **Satellites** (satellites.html) | CelesTrak TLE, passes az/el, covisibility, NORAD ID lookup |
| **Briefing** (briefing.html) | DX News (ARRL + NG3K), watchlist tracker, AI Insight link |
| **AI Insight** (ai_insight.html) | Spectral analysis, propagation patterns |

### Cockpit Panels (31 configurable)
- DX Cluster spots (cluster1, cluster2, cluster3)
- 6m radar sweep
- Leaflet map az/el
- Watchlist + tracker
- VOACAP rapid + band activity
- MY SIGNAL (PSK Reporter real-time MQTT)
- Surge detector (6m)
- Theory vs Reality
- LoTW status
- Predictions
- 24h band activity indicator
- Setup ⚙ panel (dynamic enable/disable + intervals)

---

## 📡 Data Sources

### Real-time
| Source | Protocol | Interval | Fallback |
|--------|----------|----------|----------|
| **DX Clusters** | Telnet | 10s (3x rotation) | TCP retry |
| **PSK Reporter** | MQTT | < 2s | HTTP polling 5min TTL |
| **Blitzortung** | MQTT | < 1s | Skip if absent |
| **Satellites** | REST API | 6h (CelesTrak GP) | Local TLE cache |

### Forecasts & Analysis
- **VOACAP RAPIDE** (theoretical propagation MUF/SFI single path)
- **Band Activity** (observed spots 24h by band)
- **WSPR** (wspr.live, 2m/6m tropo confirmation)
- **NOAA** (Kp, SFI, A-index JSON)
- **Local Weather** (Open-Meteo: wind, pressure, temp, humidity)
- **Beacons** (dl0tud CSV auto-update monthly, 62 IARU beacons)

---

## ⚙️ Configuration

### data/config.json
```json
{
  "MY_CALL": "F1SMV",
  "user_qra": "JN23",
  "clusters": [
    {"host": "dxfun.com", "port": 8000},
    {"host": "dxc.k0xm.net", "port": 7300},
    {"host": "dxc.nc7j.com", "port": 7373}
  ]
}
```

### data/ui_config.json
```json
{
  "panels": {
    "cluster": {"hidden": false, "order": 0, "interval_s": 10},
    "radar": {"hidden": false, "order": 1, "interval_s": 4},
    "voacap": {"hidden": false, "order": 5, "interval_s": 300}
  }
}
```

**Cross-device persistence**: changes from one client reflected everywhere (via API).

---

## 🔐 Security

- **debug=False** (production)
- **X-API-Token** (local, stored in data/.token)
- **LoTW files** chmod 600
- **HTTPS**: none (LAN only, auto-trusted)

---

## 🐛 Known Bugs Fixed (v12.2)

✅ PSK Reporter TTL 300s enforced  
✅ NOAA Kp JSON format support  
✅ Blitzortung MQTT topics slash-separated  
✅ MSK144 range 144350–144370 kHz (not ±10Hz)  
✅ Satellite TLE errors per-satellite (pluralized)  
✅ Satellite fallback logic (no silent reset on empty list)  
✅ Satellite NORAD ID lookup (new route /api/satellites/lookup/<id>)  

---

## 📊 Improvements v12.2 vs v12.1

### New Features
- **PSK Reporter MQTT** real-time (topic dedup, HTTP fallback)
- **Satellite covisibility** (sgp4 dual-path, new interface)
- **Satellite lookup by NORAD ID** (manual catalog add)
- **Weather panel drag-drop** (SortableJS, localStorage order)
- **VHF/UHF Beacons** (real spotter callsign + distance captured)

### Fixes
- ARRL News (replaces unstable dxnews.com)
- Mobile contrast (typography + tap targets < 700px)
- Satellite error messaging (all satellites listed, not first only)
- Band activity bar coloring (display:block + BAND_COLORS)

---

## 📚 Architecture

```
Flask (webapp.py, 7200+ lines)
├── HTTP Routes (200+ @app.route)
├── Async workers (cluster, MQTT, weather, satellites)
├── Modules:
│   ├── predictor.py (VOACAP + ML patterns)
│   ├── dxcc_resolver.py (LoTW cross-check)
│   └── utils.py (parsing, QRA, bearing)
├── SQLite:
│   ├── spots (call, freq, mode, time, distance, ...)
│   ├── spot_history (timeseries)
│   ├── ui_config (panel state)
│   └── LoTW cache
└── Jinja2 templates (5 HTML pages)

Clients (HTML5/JS/CSS)
├── Leaflet (maps + markers)
├── SortableJS (drag-drop)
├── Chart.js (graphs)
└── WebSocket/SSE (real-time updates)
```

---

## 🛠️ Development

### Disciplinary Notes
- ⚠️ Never duplicate `@require_api_token` (AssertionError)
- ⚠️ PSK Reporter requires JSONP (`callback=cb`), not JSON
- ⚠️ SQLite: migration THEN index (not same script)
- ⚠️ Leaflet popupopen = use `once('popupopen')` before `openPopup()`
- ⚠️ Jinja2 → `| tojson | safe` for JS embeds

### Contribution Workflow
1. Fork GitHub F1SMV/Neural-DX-Watcher
2. Feature branch (`git checkout -b feat/ntfy-alerts`)
3. Code + test locally (http://localhost:8000)
4. Push + PR (Eric review/merge)

---

## 📞 Support

- **GitHub Issues**: https://github.com/F1SMV/Neural-DX-Watcher/issues
- **Callsign**: F1SMV
- **QTH**: JN23 (La Seyne-sur-Mer, France)

---

## 📖 Resources

- [CelesTrak TLE API](https://celestrak.com/groupsets.php)
- [VOACAP](https://www.voacap.com)
- [PSK Reporter](https://pskreporter.info)
- [Blitzortung](https://www.blitzortung.org)
- [WSPR](https://wspr.live)
- [SatNOGS](https://db.satnogs.org)

---

**Neural DX Watcher v12.2**  
*Last update: Satellite covisibility + MQTT PSK Reporter real-time*  

## 👤 Author

Developed by **F1SMV – Eric**  
with the assistance of Claude (Anthropic)  
in service of the amateur radio community.  
Contact: @f1smv on X

