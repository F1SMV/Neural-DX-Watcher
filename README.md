# 🛰️ Neural DX Watcher — v12.3

**Système de monitoring DX cluster personnel + prévision propagation VHF/UHF sur Raspberry Pi**

*Callsign: F1SMV (JN23, La Seyne-sur-Mer, Provence) | GitHub: F1SMV/Neural-DX-Watcher*

---

## 📸 Aperçu apercu.png

L'interface principale combine **quatre dashboards intégrés** :

### Dashboard Principal (Accueil)
- **Pavé "Spots Live"** : flux temps réel depuis 3 clusters DX (dxfun.com, k0xm.net, nc7j.com), actualisé toutes les 10s. Affiche call, fréquence, mode, distance, direction, RST, spotter. Filtrable par bande.
- **Historique dernier 5 heures** : callsigns notable, activité par SPD (Speed), tendances propagation.
- **Jauge Opportunités DXCC** : intégration LoTW en temps réel — pays jamais travaillés détectés en direct sur les bandes où tu opères.
- **Pavé "MY SIGNAL"** (v12.3) : rapports PSK Reporter pour ton indicatif (342 rapports en direct). Affiche qui t'a reçu, localisation, SNR, distance.

### Module Météo (`/weather`)
- **Conditions locales** (Open-Meteo) : température, pression, vent, humidité, tendance barométrique.
- **Foudre Blitzortung** : carte Leaflet dark, marqueurs pulsants pour impacts foudre <300km (3×3 grille geohash).
- **WSPR Confirmation 2m** : balises reçues <300km (confirme présence tropo locale).
- **Indice Tropo/Ducting** : heuristique Open-Meteo (inversion 850hPa, humidité, CAPE).
- **VOACAP Rapide** : prédiction MUF/SFI pour UN trajet vers zone sélectionnée (8 bandes HF, mini-barres fiabilité).
- **Activité par bande 24h** : HF/VHF séparées, graphique réel observé (pas prédiction).
- **Bandeaux solaires** : SFI/K/A/horloge UTC, synthèse HF/VHF, alertes.

### Satellites (`/satellites`)
- **Passages ISS/NORAD** : 48h de prochains passes, élévation, azimut, fréquence Doppler live.
- **Catalogue AMSAT personnalisé** : 62 satellites actifs (FO-29, AO-91, AO-109, etc.), gestion par-utilisateur.
- **Co-visibilité satellite** : calcule simultanéité avec correspondant distant (sgp4 local).
- **TLE à jour** : CelesTrak + fallback SatNOGS, refresh automatique.

### Briefing DX (`/briefing`)
- **Nouvelles ARRL** (v12.3 FIX) : flux RSS `arrl.rss` temps réel (342+ articles/mois).
- **DX-World alerts** : RSS continu pour propagation majeure.
- **NG3K ADXO** : newsletter classique radio amateur.
- **Watchlist utilisateur** : alertes custom par call/pays/band.

---

## ✨ Corrections v12.3 (2026-08-29)

### 🐛 FIX #1 : MY SIGNAL Panel vide → Restauré 342 rapports PSK Reporter

**Diagnostic complet** : Trois problèmes cumulés résolus.

**Problème 1** — Broker MQTT `mqtt.pskreporter.info:1883` accepte connexion + SUBACK mais ne pousse zéro message (testé firehose mondial = silencieux). Service tiers non garanti.

**Problème 2** (MAIN) — Fallback HTTP manquait paramètre `rronly=1`. Sans lui, PSK Reporter retournait `activeReceiver` (liste récepteurs) au lieu de `receptionReport` (vrais rapports). Code cherchait `receptionReport` → toujours vide.

✅ **Vérification réelle** : `senderCallsign=F1SMV&rronly=1` retourne **342 vrais rapports** disponibles cet instant.

**Problème 3** — Cache TTL 90s trop court → rate-limit PSK Reporter (`"too many queries too often"`). Règle officielle PSK Reporter : max 1 requête/5 min.

**Corrections appliquées** :
- Ajout `rronly=1` aux paramètres query (ligne ~7295)
- Détection message rate-limit + fallback cache propre (ligne ~7307)
- TTL 90s → 300s officiel (ligne 7239)

→ **Résultat** : Panneau affiche 342 rapports PSK Reporter via HTTP fiable, indépendant du broker MQTT défaillant.

### 🐛 FIX #2 : ARRL News (HTML cassé → RSS fonctionnel)

**Problème** : dxnews.com instable (administrateur indisponible). ARRL page `/news` charge contenu en JavaScript → inaccessible via curl/BeautifulSoup.

✅ **Solution trouvée** : Flux RSS officiel `https://www.arrl.org/arrl.rss` (format RSS2 standard) retourne articles en continu.

**Changement** : Source ARRL passe de `type: html` avec `/news` à `type: rss` avec `arrl.rss`.

→ **Résultat** : Briefing affiche articles ARRL actualisés (dernière mise à jour : nouvelles satellites ARRL, etc.).

### ✅ Corrections antérieures (v12.2)

- **MSK144 correct** : Fréquence 144.350-144.370 MHz (plage exacte 2m, pas ±10Hz)
- **Beacons panel** : 62 balises IARU Region 1 VHF/UHF/SHF, source dl0tud actualisée juin 2026
- **Blitzortung topic** : Format MQTT changé `spe` → `s/p/e`, grille 3×3 geohash confirmée
- **GPS JN23** : Positionnement exact 43.076112°N, 5.873671°E (via config.json)
- **Satellite satellites** : Fallback CelesTrak CATNR pour nouveaux lancements, co-visibilité sgp4

---

## 🚀 Installation & Démarrage

### Prérequis
- **Raspberry Pi 5** (ou Pi 4, capable)
- **Python 3.9+** (testé 3.13)
- **SQLite** (inclus)
- **Connectivité réseau** (Ethernet/WiFi stable)

### Cloner le repo
```bash
cd ~
git clone https://github.com/F1SMV/Neural-DX-Watcher.git
cd Neural-DX-Watcher
```

### Créer venv et installer dépendances
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Configuration initiale
```bash
# 1. Créer data/config.json avec ton indicatif et locator
cat > data/config.json << 'EOF'
{
  "my_call": "F1SMV",
  "user_qra": "JN23",
  "user_lat": 43.076112,
  "user_lon": 5.873671
}
EOF

# 2. Créer data/ui_config.json (visibilité panneaux)
cat > data/ui_config.json << 'EOF'
{
  "briefing_visible": true,
  "weather_visible": true,
  "satellites_visible": true
}
EOF

# 3. Démarrer
bash start.sh
```

### Accès web
```
http://192.168.1.81:8000/  (ou IP de ton Pi)
```

---

## 📡 Clusters DX Actifs

L'app se connecte en telnet rotatif (10s d'intervalle) à trois sources :

| Cluster | Host | Port | Propagation |
|---------|------|------|-------------|
| **DXfun** | dxfun.com | 8000 | Worldwide HF + VHF |
| **K0XM** | dxc.k0xm.net | 7300 | USA-centric |
| **NC7J** | dxc.nc7j.com | 7373 | Spotters actifs |

Chaque cluster pousse ~5-20 spots/min. Neural déduplique et enrichit.

---

## 🎯 Données Sources

### Radio (Telnet Clusters)
- **HF ** : HF Bands
- **50 MHz (6m)** : Sporadic-E printemps/été, tropo hivernal
- **144 MHz (2m)** : Propagation tropo quasi-permanente, Es exceptionnel
- **70 cm / 23 cm** : Rarement spotté, données riches si présentes

### Météo
- **Open-Meteo** : Conditions locales, pression, humidité, vent, temp. mer (refresh 30min)
- **NOAA Kp/SFI** : Indices solaires JSON (format 2024+)

### Propagation
- **PSK Reporter MQTT** : Rapports réception temps réel (broker mqtt.pskreporter.info)
- **PSK Reporter HTTP** : Fallback, 342 rapports v12.3 (5min cache, rate-limit observé)
- **Blitzortung MQTT** : Foudre, topic `blitzortung/1.1/s/p/e/#`, geohash 3×3
- **WSPR** : wspr.live API (balises 2m <300km, indicateur tropo)

### Satellites
- **CelesTrak GP API** : TLE OMM JSON, actualisé 2-3/jour
- **SatNOGS frequencies** : Fréquences Doppler, modes

### Balises
- **dl0tud CSV** : Scan DJ5CW/Fabian Kurz (TU Dresden), 62 balises actives, MAJ automatique 30j

---

## ⚙️ Configuration Avancée

### Locator Utilisateur (critère)
Modifie `data/config.json` pour précision GPS :
```json
{
  "user_lat": 43.076112,  // ← Décimal, Nord = +, Sud = -
  "user_lon": 5.873671    // ← Décimal, Est = +, Ouest = -
}
```

La conversion QRA → lat/lon est validée par regex `^[A-R]{2}[0-9]{2}([A-X]{2})?$`.

### LoTW (Confirmation DXCC)
```bash
# Télécharger ADIF depuis LoTW
# Placer dans data/lotw_adif.adi
# Relancer l'app → Opportunités DXCC se mettent à jour
```

### Watchlist (Briefing Custom)
Dans `data/briefing_sources.json`, ajoute des indicatifs/pays alertes :
```json
{
  "id": "watchlist",
  "name": "Ma watchlist",
  "calls": ["5V7A", "3Y0J"],
  "countries": ["Bouvet Island", "Mauritius"]
}
```

---

## 🔍 Structure de l'App

```
.
├── webapp.py                 # Flask backend principal (7200+ lignes)
├── predictor.py              # Calculs MUF/SFI/prédictions
├── dxcc_resolver.py          # Lookup entities/pays
├── tools/
│   └── log_meta_analyzer.py # Analyse logs (hors Web)
├── templates/
│   ├── index.html            # Dashboard principal
│   ├── weather.html          # Module Météo (Blitzortung, WSPR, tropo)
│   ├── satellites.html       # Passages satellitaires
│   ├── briefing.html         # Nouvelles DX
│   ├── map.html              # Carte MUF/grayline
│   ├── world.html            # Activité mondiale temps réel
│   └── ...
├── data/
│   ├── config.json           # Config utilisateur
│   ├── beacons_reference.json # Balises IARU R1 (62 entrées)
│   ├── radio_spot_watcher.db # SQLite local
│   └── ...
├── start.sh                  # Script démarrage + venv
└── requirements.txt          # Dépendances Python
```

---

## 📊 Bases de Données

### Tables SQLite
- **spot_history** : Spots clusters (50M historique par défaut)
- **dxcc_contacts** : Log LoTW parsed
- **weather_snapshots** : Conditions météo horodatées
- **solar_snapshots** : SFI/Kp historique
- **propagation_events** : Événements Es/Tropo (v12.3+)

### API Routes (Flask)
- `GET /api/dx_briefing.json` → Nouvelles (ARRL, DX-World, NG3K)
- `GET /api/my_signal.json` → PSK Reporter (v12.3 : 342 rapports)
- `GET /api/weather/lightning.json` → Impacts foudre <300km
- `GET /api/satellites/passes/<norad_id>` → Prochains passages
- `GET /api/voacap` → Prévision MUF rapide

---

## 🔐 Sécurité

- **API Token local** : `X-API-Token` header requis
- **Debug = False** : Production ready
- **LoTW files** : chmod 600 (privé)
- **Logs** : `radio_spot_watcher.log` (rotate auto)

---

## 🐛 Troubleshooting

### MY SIGNAL Panel vide
**v12.3** : Vérifie que tu as attendu 5 min après le fix (rate-limit PSK Reporter). Puis redémarrage : `pkill -f python.*webapp.py ; bash start.sh`.

### Pas de spots 6m
- Vérifie que clusters DX sont joignables : `curl telnet://dxfun.com:8000`
- Checks logs : `tail -50 radio_spot_watcher.log | grep -i "6m\|50MHz"`

### Lightning map vide
- Géohash 3×3 centré sur ton QTH. Impacts <300km devraient apparaître.
- Vérifier log : `grep -i "lightning\|blitzortung" radio_spot_watcher.log | tail -10`

### ARRL News cassée
- RSS `arrl.org/arrl.rss` doit répondre. Test : `curl -s https://www.arrl.org/arrl.rss | head -20`

---

## 📈 Roadmap v12.4+

- [ ] **Real-Time Alerts** (ntfy.sh) : Push notifications call watchlist + new DXCC
- [ ] **DXCC Hunt Mode** : Priorité top 5 calls manquants + bearing exact
- [ ] **Local Learning Engine** : Es/Tropo detection + prédictions (long terme)
- [ ] **Multi-band Activity Correlator** : Timeline visuelle 10m→6m→4m→2m synchrone

---

## 📝 Logs & Debugging

```bash
# Logs en direct
tail -f radio_spot_watcher.log | grep -i "my_signal\|arrl\|lightning"

# Chercher erreurs spécifiques
grep "ERROR\|WARNING" radio_spot_watcher.log | tail -20

# Vérifier status API
curl http://192.168.1.81:8000/api/dx_briefing.json | jq '.sources' 
```

---

## 🤝 Contribution & Support

**Rapport de bug** : GitHub Issues (F1SMV/Neural-DX-Watcher)

**QTH** : JN23 (La Seyne-sur-Mer, Provence)
**Indicatif** : F1SMV
**Actif** : HF/ 6m (Es), 2m (tropo, ES), 70cm / QO100 /satellites
** contact via X @F1SMV
---

## 📄 Licence

MIT. Libre d'usage personnel/club radio. 

---

**Version 12.3 — Août 2026**
- Fixed: MY SIGNAL PSK Reporter (rronly=1, TTL 300s, rate-limit detection)
- Fixed: ARRL News RSS (dxnews.com → arrl.org/arrl.rss)
- Stable: Production-ready Raspberry Pi 5

**Neural DX Watcher — Your personal DX cluster monitoring + VHF/UHF propagation dashboard.**
