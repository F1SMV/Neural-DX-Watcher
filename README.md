# Neural DX Watcher v12.2

**Application Web de Monitoring des Spots DX • Prévisions Propagation • Satellites**

Raspberry Pi 5/4/3 • Flask + SQLite • Amateur Radio  
F1SMV (JN23) • https://github.com/F1SMV/Neural-DX-Watcher

---

## 📋 Vue d'ensemble

Neural DX Watcher agrège **3 clusters DX temps réel** (Telnet), affiche les propagations par **machine learning** et **prédictions VOACAP**, suit les **satellites amateurs** en temps réel, et fournit un **dashboard cockpit** pour les opérateurs radio VHF/UHF/HF.

- ✅ **7200+ lignes** Flask/Python + 209 fonctions
- ✅ **SQLite** persistant (spots, historique, config, cache LoTW)
- ✅ **MQTT PSK Reporter** temps réel + fallback HTTP
- ✅ **Blitzortung** foudre en direct (grille 3×3 geohash)
- ✅ **Satellites** : TLE/passes/covisibilité (sgp4)
- ✅ **Balises VHF/UHF** : références officielles IARU + spot history

---

## 🚀 Démarrage rapide

### Prérequis
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
**Logs**: stdout (Flask en debug=False)

---
apercu

![Apercu du Dashboard](apercu.png)



## 🎮 Interface utilisateur

### Pages principales

| Page | Fonction |
|------|----------|
| **Cockpit** (index.html) | Radar 6m, DX feed, AZ/EL, marqueurs spots temps réel |
| **Météo** (weather.html) | Propagation (VOACAP), foudre Leaflet, balises, WSPR correlation |
| **Satellites** (satellites.html) | TLE CelesTrak, passes az/el, covisibilité, lookup NORAD ID |
| **Briefing** (briefing.html) | News DX (ARRL + NG3K), watchlist tracker, AI Insight link |
| **AI Insight** (ai_insight.html) | Analyse spectrale, patterns propagation |

### Panneaux cockpit (31 configurable)
- DX Cluster spots (cluster1, cluster2, cluster3)
- Radar sweep 6m
- Carte Leaflet az/el
- Watchlist + tracker
- VOACAP rapid + band activity
- MY SIGNAL (PSK Reporter real-time MQTT)
- Surge detector (6m)
- Théorie vs Réalité
- LoTW status
- Prédictions
- Indicateur bande active 24h
- Panel Setup ⚙ (activation/désactivation dynamique + intervals)

---

## 📡 Sources de données

### Temps réel
| Source | Protocol | Intervalle | Fallback |
|--------|----------|-----------|----------|
| **DX Clusters** | Telnet | 10s (3x rotation) | Retry TCP |
| **PSK Reporter** | MQTT | < 2s | HTTP polling 5min TTL |
| **Blitzortung** | MQTT | < 1s | Skip si absent |
| **Satellites** | REST API | 6h (CelesTrak GP) | Local TLE cache |

### Prévisions & analyse
- **VOACAP RAPIDE** (propagation théorique MUF/SFI 1 path)
- **Band Activity** (spots observés 24h par bande)
- **WSPR** (wspr.live, confirmation tropo 2m/6m)
- **NOAA** (Kp, SFI, A-index JSON)
- **Météo locale** (Open-Meteo : vent, pression, temp, humidité)
- **Balises** (dl0tud CSV auto-update mensuel, 62 IARU beacons)

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

**Persistance inter-appareils** : changements d'un client reflétés partout (via API).

---

## 🔐 Sécurité

- **debug=False** (production)
- **X-API-Token** (local, stocké data/.token)
- **LoTW files** chmod 600
- **HTTPS** : none (LAN only, auto-trusted)

---

## 🐛 Bugs corrigés (v12.2)

✅ PSK Reporter TTL 300s enforced  
✅ NOAA Kp JSON format support  
✅ Blitzortung MQTT topics slash-separated  
✅ MSK144 range 144350–144370 kHz (not ±10Hz)  
✅ Satellite TLE errors per-satellite (pluralisé)  
✅ Satellite fallback logic (no silent reset on empty list)  
✅ Satellite NORAD ID lookup (nouvelle route /api/satellites/lookup/<id>)  

---

## 📊 Améliorations v12.2 vs v12.1

### Nouvelles fonctionnalités
- **PSK Reporter MQTT** real-time (topic dedup, fallback HTTP)
- **Satellite covisibility** (sgp4 dual-path, interface new)
- **Satellite lookup NORAD ID** (manual catalog add by NORAD)
- **Weather panel drag-drop** (SortableJS, localStorage order)
- **Balises VHF/UHF** (real spotter callsign + distance captured)

### Corrections
- ARRL News (remplace dxnews.com instable)
- Mobile contrast (typography + tap targets < 700px)
- Satellite error messaging (all satellites listed, not first only)
- Band activity bar coloring (display:block + BAND_COLORS)

---

## 📚 Architecture

```
Flask (webapp.py, 7200+ lignes)
├── Routes HTTP (200+ @app.route)
├── Workers async (cluster, MQTT, weather, satellites)
├── Modules :
│   ├── predictor.py (VOACAP + ML patterns)
│   ├── dxcc_resolver.py (LoTW cross-check)
│   └── utils.py (parsing, QRA, bearing)
├── SQLite :
│   ├── spots (call, freq, mode, time, distance, ...)
│   ├── spot_history (timeseries)
│   ├── ui_config (panel state)
│   └── LoTW cache
└── Jinja2 templates (5 pages HTML)

Clients (HTML5/JS/CSS)
├── Leaflet (maps + markers)
├── SortableJS (drag-drop)
├── Chart.js (graphs)
└── WebSocket/SSE (real-time updates)
```

---

## 🛠️ Développement

### Notes disciplinaires
- ⚠️ `@require_api_token` ne pas dupliquer (AssertionError)
- ⚠️ PSK Reporter = JSONP (`callback=cb`), pas JSON
- ⚠️ SQLite : migration PUIS index (pas same script)
- ⚠️ Leaflet popupopen = `once('popupopen')` avant `openPopup()`
- ⚠️ Jinja2 → `| tojson | safe` pour JS embeds

### Workflow contributions
1. Fork GitHub F1SMV/Neural-DX-Watcher
2. Branch feature (`git checkout -b feat/ntfy-alerts`)
3. Code + test local (http://localhost:8000)
4. Push + PR (Eric review/merge)

---

## 📞 Support

- **Issues GitHub**: https://github.com/F1SMV/Neural-DX-Watcher/issues
- **Callsign**: F1SMV
- **QTH**: JN23 (La Seyne-sur-Mer, France)

---

## 📖 Ressources

- [CelesTrak TLE API](https://celestrak.com/groupsets.php)
- [VOACAP](https://www.voacap.com)
- [PSK Reporter](https://pskreporter.info)
- [Blitzortung](https://www.blitzortung.org)
- [WSPR](https://wspr.live)
- [SatNOGS](https://db.satnogs.org)

---

**Neural DX Watcher v12.2**  
*Dernier update: Satellite covisibility + MQTT PSK Reporter real-time*  

Consulter l'historique complet : 👉 https://github.com/F1SMV/Neural-DX-Watcher/commits/main

---

## 👤 Auteur
Développé par F1SMV – Eric
avec l'assistance de Claude (Anthropic)
au service de la communauté radioamateur.
Contact : @f1smv sur X
