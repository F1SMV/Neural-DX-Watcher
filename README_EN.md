# 🛰️ Neural DX Watcher — v12.3

**Personal DX cluster monitoring + VHF/UHF propagation forecasting system on Raspberry Pi**

*Callsign: F1SMV (JN23, La Seyne-sur-Mer, Provence) | GitHub: F1SMV/Neural-DX-Watcher*

---

## 📸 Overview (apercu.png)

The main interface combines **four integrated dashboards** :

### Main Dashboard (Home)
- **"Spots Live" Panel** : Real-time stream from 3 DX clusters (dxfun.com, k0xm.net, nc7j.com), refreshed every 10s. Displays call, frequency, mode, distance, bearing, RST, spotter. Filterable by band.
- **Last 5 Hours History** : Notable callsigns, SPD (Speed) activity, propagation trends.
- **"DXCC Opportunities" Gauge** : LoTW real-time integration — countries never worked detected live on your favorite bands.
- **"MY SIGNAL" Panel** (v12.3) : PSK Reporter reception reports for your callsign (342 reports live). Shows who heard you, location, SNR, distance.

### Weather Module (`/weather`)
- **Local Conditions** (Open-Meteo) : Temperature, pressure, wind, humidity, barometric trend.
- **Blitzortung Lightning** : Leaflet dark map, pulsing markers for strikes <300km (3×3 geohash grid).
- **2m WSPR Confirmation** : Beacons heard <300km (confirms local tropo presence).
- **Tropo/Ducting Index** : Open-Meteo heuristic (850hPa inversion, humidity, CAPE).
- **Quick VOACAP** : MUF/SFI prediction for ONE path to selected zone (8 HF bands, reliability mini-bars).
- **24h Band Activity** : HF/VHF separated, actual observed graph (not prediction).
- **Solar Banners** : SFI/K/A/UTC clock, HF/VHF synthesis, alerts.

### Satellites (`/satellites`)
- **ISS/NORAD Passes** : Next 48h passes, elevation, azimuth, live Doppler frequency.
- **Custom AMSAT Catalog** : 62 active satellites (FO-29, AO-91, AO-109, etc.), per-user managed.
- **Satellite Co-visibility** : Calculates simultaneous visibility with distant correspondent (local sgp4).
- **Updated TLEs** : CelesTrak + SatNOGS fallback, auto-refresh.

### DX Briefing (`/briefing`)
- **ARRL News** (v12.3 FIX) : RSS feed `arrl.rss` real-time (342+ articles/month).
- **DX-World Alerts** : Continuous RSS for major propagation events.
- **NG3K ADXO** : Classic radio amateur newsletter.
- **User Watchlist** : Custom alerts by call/country/band.

---

## ✨ v12.3 Fixes (2026-08-29)

### 🐛 FIX #1 : MY SIGNAL Panel Empty → Restored 342 PSK Reporter Receipts

**Complete diagnostic** : Three cumulative problems resolved.

**Problem 1** — MQTT broker `mqtt.pskreporter.info:1883` accepts connection + SUBACK but pushes zero messages (tested global firehose = silent). Third-party service, no guarantee.

**Problem 2** (MAIN) — HTTP fallback missing `rronly=1` parameter. Without it, PSK Reporter returns `activeReceiver` (receiver list) instead of `receptionReport` (actual reports). Code looks for `receptionReport` → always empty.

✅ **Real verification** : `senderCallsign=F1SMV&rronly=1` returns **342 actual reports** available this instant.

**Problem 3** — Cache TTL 90s too short → rate-limit PSK Reporter (`"too many queries too often"`). Official PSK Reporter rule : max 1 request/5 min.

**Fixes applied** :
- Added `rronly=1` to query parameters (line ~7295)
- Rate-limit message detection + clean cache fallback (line ~7307)
- TTL 90s → 300s official (line 7239)

→ **Result** : Panel displays 342 PSK Reporter reports via reliable HTTP, independent of failing MQTT broker.

### 🐛 FIX #2 : ARRL News (Broken HTML → Working RSS)

**Problem** : dxnews.com unstable (admin unavailable). ARRL `/news` page loads content via JavaScript → inaccessible via curl/BeautifulSoup.

✅ **Solution found** : Official RSS feed `https://www.arrl.org/arrl.rss` (standard RSS2 format) returns articles continuously.

**Change** : ARRL source switches from `type: html` with `/news` to `type: rss` with `arrl.rss`.

→ **Result** : Briefing displays updated ARRL articles (latest update: ARRL satellite news, etc.).

### ✅ Previous Fixes (v12.2)

- **MSK144 corrected** : Frequency 144.350-144.370 MHz (exact 2m range, not ±10Hz)
- **Beacons panel** : 62 IARU Region 1 VHF/UHF/SHF beacons, dl0tud source updated June 2026
- **Blitzortung topic** : MQTT format changed `spe` → `s/p/e`, 3×3 geohash grid confirmed
- **GPS JN23** : Exact positioning 43.076112°N, 5.873671°E (via config.json)
- **Satellite satellites** : CelesTrak CATNR fallback for new launches, sgp4 co-visibility

---

## 🚀 Installation & Startup

### Requirements
- **Raspberry Pi 5** (or Pi 4, capable)
- **Python 3.9+** (tested 3.13)
- **SQLite** (included)
- **Network Connectivity** (stable Ethernet/WiFi)

### Clone Repository
```bash
cd ~
git clone https://github.com/F1SMV/Neural-DX-Watcher.git
cd Neural-DX-Watcher
```

### Create venv and Install Dependencies
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Initial Configuration
```bash
# 1. Create data/config.json with your callsign and locator
cat > data/config.json << 'EOF'
{
  "my_call": "F1SMV",
  "user_qra": "JN23",
  "user_lat": 43.076112,
  "user_lon": 5.873671
}
EOF

# 2. Create data/ui_config.json (panel visibility)
cat > data/ui_config.json << 'EOF'
{
  "briefing_visible": true,
  "weather_visible": true,
  "satellites_visible": true
}
EOF

# 3. Start
bash start.sh
```

### Web Access
```
http://192.168.1.81:8000/  (or your Pi's IP)
```

---

## 📡 Active DX Clusters

The app connects via rotating telnet (10s interval) to three sources :

| Cluster | Host | Port | Propagation |
|---------|------|------|-------------|
| **DXfun** | dxfun.com | 8000 | Worldwide HF + VHF |
| **K0XM** | dxc.k0xm.net | 7300 | USA-centric |
| **NC7J** | dxc.nc7j.com | 7373 | Active spotters |

Each cluster pushes ~5-20 spots/min. Neural deduplicates and enriches.

---

## 🎯 Data Sources

### Radio (Telnet Clusters)
- **50 MHz (6m)** : Sporadic-E spring/summer, tropo winter
- **144 MHz (2m)** : Quasi-permanent tropo propagation, exceptional Es
- **70 cm / 23 cm** : Rarely spotted, rich data if present

### Weather
- **Open-Meteo** : Local conditions, pressure, humidity, wind, sea temp (refresh 30min)
- **NOAA Kp/SFI** : Solar indices JSON (2024+ format)

### Propagation
- **PSK Reporter MQTT** : Real-time reception reports (broker mqtt.pskreporter.info)
- **PSK Reporter HTTP** : Fallback, 342 reports v12.3 (5min cache, rate-limit observed)
- **Blitzortung MQTT** : Lightning, topic `blitzortung/1.1/s/p/e/#`, geohash 3×3
- **WSPR** : wspr.live API (2m beacons <300km, tropo indicator)

### Satellites
- **CelesTrak GP API** : TLE OMM JSON, updated 2-3/day
- **SatNOGS frequencies** : Doppler frequencies, modes

### Beacons
- **dl0tud CSV** : DJ5CW/Fabian Kurz scan (TU Dresden), 62 active beacons, auto-update 30d

---

## ⚙️ Advanced Configuration

### User Locator (Essential)
Edit `data/config.json` for GPS precision :
```json
{
  "user_lat": 43.076112,  // ← Decimal, North = +, South = -
  "user_lon": 5.873671    // ← Decimal, East = +, West = -
}
```

QRA → lat/lon conversion validated by regex `^[A-R]{2}[0-9]{2}([A-X]{2})?$`.

### LoTW (DXCC Confirmation)
```bash
# Download ADIF from LoTW
# Place in data/lotw_adif.adi
# Restart app → DXCC Opportunities updates
```

### Watchlist (Custom Briefing)
In `data/briefing_sources.json`, add callsign/country alerts :
```json
{
  "id": "watchlist",
  "name": "My watchlist",
  "calls": ["5V7A", "3Y0J"],
  "countries": ["Bouvet Island", "Mauritius"]
}
```

---

## 🔍 App Structure

```
.
├── webapp.py                 # Flask backend main (7200+ lines)
├── predictor.py              # MUF/SFI/forecasting calculations
├── dxcc_resolver.py          # Entity/country lookup
├── tools/
│   └── log_meta_analyzer.py # Log analysis (offline)
├── templates/
│   ├── index.html            # Main dashboard
│   ├── weather.html          # Weather module (Blitzortung, WSPR, tropo)
│   ├── satellites.html       # Satellite passes
│   ├── briefing.html         # DX news
│   ├── map.html              # MUF/grayline map
│   ├── world.html            # Real-time global activity
│   └── ...
├── data/
│   ├── config.json           # User configuration
│   ├── beacons_reference.json # IARU R1 beacons (62 entries)
│   ├── radio_spot_watcher.db # Local SQLite
│   └── ...
├── start.sh                  # Startup script + venv
└── requirements.txt          # Python dependencies
```

---

## 📊 Databases

### SQLite Tables
- **spot_history** : Cluster spots (50M history by default)
- **dxcc_contacts** : Parsed LoTW log
- **weather_snapshots** : Time-stamped weather conditions
- **solar_snapshots** : SFI/Kp history
- **propagation_events** : Es/Tropo events (v12.3+)

### Flask API Routes
- `GET /api/dx_briefing.json` → News (ARRL, DX-World, NG3K)
- `GET /api/my_signal.json` → PSK Reporter (v12.3 : 342 reports)
- `GET /api/weather/lightning.json` → Lightning strikes <300km
- `GET /api/satellites/passes/<norad_id>` → Next passes
- `GET /api/voacap` → Quick MUF forecast

---

## 🔐 Security

- **Local API Token** : `X-API-Token` header required
- **Debug = False** : Production-ready
- **LoTW Files** : chmod 600 (private)
- **Logs** : `radio_spot_watcher.log` (auto-rotate)

---

## 🐛 Troubleshooting

### MY SIGNAL Panel Empty
**v12.3** : Verify you waited 5 min after fix (PSK Reporter rate-limit). Then restart : `pkill -f python.*webapp.py ; bash start.sh`.

### No 6m Spots
- Verify DX clusters are reachable : `curl telnet://dxfun.com:8000`
- Check logs : `tail -50 radio_spot_watcher.log | grep -i "6m\|50MHz"`

### Lightning Map Empty
- Geohash 3×3 centered on your QTH. Strikes <300km should appear.
- Check log : `grep -i "lightning\|blitzortung" radio_spot_watcher.log | tail -10`

### ARRL News Broken
- RSS `arrl.org/arrl.rss` must respond. Test : `curl -s https://www.arrl.org/arrl.rss | head -20`

---

## 📈 Roadmap v12.4+

- [ ] **Real-Time Alerts** (ntfy.sh) : Push notifications for watchlist calls + new DXCC
- [ ] **DXCC Hunt Mode** : Prioritize top 5 missing calls + exact bearing
- [ ] **Local Learning Engine** : Es/Tropo detection + predictions (long-term)
- [ ] **Multi-band Activity Correlator** : Visual timeline 10m→6m→4m→2m synchronized

---

## 📝 Logs & Debugging

```bash
# Live logs
tail -f radio_spot_watcher.log | grep -i "my_signal\|arrl\|lightning"

# Search specific errors
grep "ERROR\|WARNING" radio_spot_watcher.log | tail -20

# Check API status
curl http://192.168.1.81:8000/api/dx_briefing.json | jq '.sources' 
```

---

## 🤝 Contribution & Support

**Bug Reports** : GitHub Issues (F1SMV/Neural-DX-Watcher)

**QTH** : JN23 (La Seyne-sur-Mer, Provence)
**Callsign** : F1SMV
**Active on** : 6m (Es), 2m (tropo), 70cm /qo100 /HF

---

## 📄 Licence

MIT. Free for personal/radio club use. 

---

**Version 12.3 — August 2026**
- Fixed: MY SIGNAL PSK Reporter (rronly=1, TTL 300s, rate-limit detection)
- Fixed: ARRL News RSS (dxnews.com → arrl.org/arrl.rss)
- Stable: Production-ready Raspberry Pi 5

**Neural DX Watcher — Your personal DX cluster monitoring + VHF/UHF propagation dashboard.**
