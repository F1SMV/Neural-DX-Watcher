# Neural DX Watcher v12.7

**Une application web de chasse DXCC intelligente pour le radioamateur moderne**, basée sur Flask + SQLite, tournant sur Raspberry Pi 5 à `192.168.1.81:8000`.

Utilisateur : **F1SMV** (QTH : JN23, La Seyne-sur-Mer, 43.076°N 5.873°E)  
Dépôt : [F1SMV/Neural-DX-Watcher](https://github.com/F1SMV/Neural-DX-Watcher)

---

## 📸 Aperçu
![Aperçu du Dashboard](apercu.png)

---

## 🎯 Fonctionnalités Principales

### Mode Chasse DXCC (v12.4) ✨
Route dédiée **`/hunt`** — interface full-screen optimisée pour le hunt en direct :
- **Cible n°1 en hero** : présentation large du pays cible, drapeau 🇵🇬, capitale, population, décalage horaire (données en temps réel via REST Countries API, cache 30j)
- **Carte Leaflet monde** (320px, pattern cockpit 6m) : QTH + station DX + liaison pointillée, marqueurs secondaires pondérés par SPD (rareté + distance + split + mode)
- **Liste secondaire cliquable** : top 15 cibles triées par SPD, clic = zoom sur la carte
- **Badge 🏴 EXPÉ** (v12.7) : signale en orange les expéditions DX actives dans le tableau DX Wanted, croisées automatiquement avec le briefing ng3k
- **Filtre bande en temps réel**, rafraîchissement 15s
- **localStorage tracking** : suivi des appels intéressants

### Analyse IA / AI Insight (v12.5) ✨
Route **`/ai_insight`** — tableau de bord d'analyse comportementale, entièrement bilingue FR/EN :
- **Activité récente** : sparkline heure par heure (24h), pic et heure courante mis en évidence
- **Prochaines heures** : fréquence d'activité observée par le passé sur les créneaux à venir — explications bilingues, créneaux à faible échantillon signalés en orange
- **Quand ça ouvre** : heatmap jour de semaine × heure UTC
- **Tendances par bande** : comparaison période récente vs précédente
- **Prédictions HF VOACAP (v12.6)** : grille **8 bandes × 24 heures** (v12.7 : 12m, 17m, 30m ajoutés)
- Rafraîchissement AJAX toutes les 5 min, barre de maturité chaque minute
- Drag & drop des panneaux (v12.7), ordre persisté en localStorage

### Prédictions HF VOACAP (v12.6) ✨
Cinquième panneau de la page AI Insight — prédictions point-à-point via le moteur **VOACAP** (US gov, open source) :
- **Saisie libre** : indicatif (`JA1ABC`), préfixe DXCC (`ZS`, `VK`, `EA8`…) ou nom de pays (`Brésil`, `Australie`) — résolution automatique
- **Table DXCC locale** (~60 entités, réponse instantanée) + fallback géocodage Nominatim/OSM
- **Grille bandes × heures** : 8 bandes (10m→80m) × 24 heures UTC, teintées selon la fiabilité REL
- **Hero heure courante** : bande recommandée maintenant, REL% et SNR en grand
- **Raccourcis DX** : USA, Japon, Australie, Brésil, Afrique du Sud en un clic
- **Cache 24h** : calcul coûteux sur Pi → `data/voacap_cache.sqlite`

**Setup VOACAP (une seule fois) :**
```bash
bash ~/.claude/skills/voacap/scripts/setup.sh
```

### Propagation & Prédictions
- **VOACAP Rapide** : chemin HF précis vers la zone sélectionnée (5min)
- **Indicateurs troposphériques** : inversion 850hPa, humidité, CAPE
- **Blitzortung MQTT** : foudre temps réel (grid 3×3 autour QTH), correlation RF/QRN
- **WSPR global** : spots par bande, callsigns individuels + distances réelles QTH (v12.7), confirmation 2m radar

### Satellites & Beacons
- **Visibilité co- et contres-empreintes** : SGP4, horizon 48h, ≥30s overlap
- **Beacons VHF/UHF/SHF** : 62 balises IARU, mise à jour mensuelle dl0tud.tu-dresden.de
- **SatNOGS pour les fréquences**

### Gestion LoTW & Statistiques
- **Intégration LoTW native** : cache disque 6589 QSOs, synchronisation périodique
- **Dxcc_hunt.py** : moteur de scoring par bande, rareté + distance, log interne en base
- **Briefing ARRL / ng3k** : actualités DX récentes, expéditions actives croisées avec les spots

### Architecture Backend
- **`webapp.py`** : 7700+ lignes, Python 3.13, Flask, SQLite
- **`analytics.py`** : moteur Analyse IA autonome, base dédiée `data/analytics.sqlite`
- **`voacap_adapter.py`** : enveloppe VOACAP + cache 24h SQLite
- **`country_meta.py`** : enrichissement pays (drapeau, capitale, population, TZ) — cache 30j
- **`dxcc_hunt.py`** : logique pure DXCC Hunt (injectable, testable, 13/13 tests ✅)
- **`ntfy_alerts.py`** : notifications desktop/mail (v10.0, complet)

---

## v12.7 — Changelog Détaillé

### Nouvelles Fonctionnalités
- **Badge 🏴 EXPÉ dans DX Wanted** (`index.html`, `webapp.py`)
  - Croisement automatique spots cluster ↔ briefing ng3k : tout call actif dans les deux sources reçoit un badge orange visible dans le tableau DX Wanted (Top 10)
  - Extraction des callsigns d'expéditions depuis les titres ng3k (préfixe ≥ 4 chars avec chiffre, date de fin dans le futur)
  - Exposé via `wanted.json` → champ `expedition_calls: {call: country}`

- **VOACAP : 8 bandes** (au lieu de 5) — 12m (24.9 MHz), 17m (18.1 MHz), 30m (10.1 MHz) ajoutés dans `ai_insight.html` et les fréquences par défaut de `/api/voacap/predict`

- **Drag & drop AI Insight** : panneaux réorganisables par glisser-déposer (SortableJS), ordre persisté en `localStorage` clé `ai_insight_panel_order`

- **WSPR 2m confirmation enrichie** : callsigns individuels et distances réelles TX→QTH (Haversine) affichés, au lieu d'un simple comptage anonyme

### Correctifs
- **Géolocalisation DX** : correction du bug KH8→Michigan (American Samoa correctement placée aux Samoa) et de 8 entités Pacifique/Caraïbes (KH0 Mariannes, KH1 Baker-Howland, KH2 Guam, KH4 Midway, KH5 Palmyra, KH7K Kure, KH8/s Swains, 5W Samoa indépendantes)
  - Bug 1 : `CALLSIGN_ZONES` contenait `'AH': USA` → mappait tous les AH* sur le Missouri
  - Bug 2 : l'étape 3 du résolveur (extraction du chiffre de zone) s'appliquait à tort aux KH*/AH*/KP*
  - Bug 3 : overrides post-parsing cty.dat pour les longitudes à signe erroné

### Infrastructure & Nettoyage
- `APP_VERSION` → `'12.7'`
- `defaultdict` retiré des imports (non utilisé)
- `start.sh` : `paho-mqtt` ajouté au check de dépendances, `telnetlib3` retiré (non listé dans `requirements.txt`)
- Route GET/POST `/api/ui-config` : clarification (deux fonctions distinctes, pas un doublon)
- Audit complet webapp.py : 252 fonctions, 0 erreur syntaxique, calculs Haversine validés

---

## v12.6 — Changelog Détaillé

### Nouvelles Fonctionnalités
- **Panneau Prédictions HF VOACAP** dans AI Insight (`ai_insight.html`)
  - Grille bandes × heures (10m→80m / UTC 00-23), teintée par fiabilité REL
  - Hero heure courante : bande recommandée + REL% + SNR en un coup d'œil
  - Saisie unifiée : indicatif, préfixe DXCC ou nom de pays → résolution automatique
  - 5 raccourcis DX, cache SQLite 24h, fallback gracieux si `voacapl` non installé

- **`voacap_adapter.py`** (nouveau module) : enveloppe `voacap_predict.py` (skill Reid), parseur de sortie VOACAP, cache SQLite autonome
- **Route `POST /api/voacap/predict`** : SSN auto-dérivé du SFI NOAA courant si non fourni

### Nettoyage
- `APP_VERSION` → `'12.6'`
- Suppression route orpheline `@app.route("/ai.html")`
- `requirements.txt` entièrement réécrit : dépendances exactes, notes setup VOACAP

---

## v12.5 — Changelog Détaillé

### Nouvelles Fonctionnalités
- **Page Analyse IA refondue** (`ai_insight.html`, route `/ai_insight`)
  - Module `analytics.py` totalement autonome : base dédiée `data/analytics.sqlite`
  - 4 panneaux dynamiques : Activité récente, Prochaines heures, Quand ça ouvre, Tendances par bande
  - Rafraîchissement AJAX toutes les 5 min, barre de maturité chaque minute

### Améliorations UX
- **Clarté du panneau « Prochaines heures »** : sous-titres bilingues FR/EN, créneaux à faible échantillon (< 5 obs.) signalés en orange, encadrés de synthèse repassés en accent orange

### Correctifs
- **`dxcc_hunt.py`** : validation des distances physiquement impossibles
- **`weather.html`** : migration CARTO → Esri Dark Gray Canvas, correction tuiles `{z}/{y}/{x}`
- **`hunt.html`** : stabilisation carte Leaflet (invalidateSize étagé, zéro bord gris)

---

## v12.4 — Changelog Détaillé

### Nouvelles Fonctionnalités
- **Mode Hunt DXCC complet** (routes `/hunt`, `/api/hunt/data`)
  - Tri par score SPD continu (rareté + distance + split + mode)
  - Cible n°1 enrichie (drapeau, capitale, population, décalage horaire)
  - Marqueurs secondaires multi-cibles sur la carte, pondérés par SPD
  - Navigation cliquable : clic sur une cible secondaire zoom la carte dessus

- **`country_meta.py`** : enrichissement pays DXCC (REST Countries API v3.1, cache 30j, fallback gracieux)
- **Lien 🎯 HUNT dans la nav** + indicateur clignotant (animation 20s), localStorage watchlist

### Correctifs Critiques
- Tri DXCC Hunt : remplacé booléen `is_rare` par score SPD continu
- Leaflet carte hunt : `worldCopyJump: true`, `center: QTH`, `zoom: 2`, zéro bord gris

### Tests
- 13/13 tests unitaires `dxcc_hunt.py`
- 16/16 tests unitaires `country_meta.py`

---

## 🚀 Installation Rapide

### Prérequis
- Python 3.13 + venv
- Raspberry Pi 5 (ou Linux x64)
- Ports réseau : 8000 (Flask)

### Déploiement sur Pi
```bash
cd ~/Spot-Watcher-DX
cp webapp.py country_meta.py dxcc_hunt.py voacap_adapter.py .
cp templates/*.html templates/
pkill -f "python.*webapp.py"
bash start.sh
```

### Vérification
```bash
curl http://192.168.1.81:8000/hunt
curl 'http://192.168.1.81:8000/api/hunt/data?band=20m'
curl -s 'http://192.168.1.81:8000/wanted.json' | python3 -m json.tool | grep expedition
```

---

## 📊 Modules Importants

| Fichier | Rôle | État |
|---------|------|------|
| `webapp.py` | Backend Flask principal | ✅ v12.7 |
| `analytics.py` | Moteur Analyse IA (autonome, cache dédié) | ✅ v12.5 |
| `voacap_adapter.py` | Enveloppe VOACAP + cache 24h | ✅ v12.6 |
| `ai_insight.html` | UI Analyse IA + Prédictions HF (bilingue FR/EN) | ✅ v12.7 |
| `index.html` | Dashboard + DX Wanted + badge Expé | ✅ v12.7 |
| `dxcc_hunt.py` | Moteur scoring Hunt DXCC | ✅ 13/13 tests |
| `country_meta.py` | Enrichissement pays (cache 30j) | ✅ 16/16 tests |
| `hunt.html` | UI Mode Hunt (Leaflet, markers SPD) | ✅ Cockpit 6m |
| `start.sh` | Lancement + vérification dépendances | ✅ v12.7 |

---

## 🔧 Configuration Avancée

### DX Clusters
```python
CLUSTERS = [
    'dxfun.com:8000',
    'dxc.k0xm.net:7300',
    'dxc.nc7j.com:7373',
]
```

### LoTW
- Cache disque : `data/lotw_cache.json`
- Test ADIF : `lotw_debug_qsl.adi` (6589 QSOs)

### Beacons
- Source : `dl0tud.tu-dresden.de/beacons`
- Auto-update mensuel
- Ref locale : `data/beacons_reference.json`

---

## 📡 API Publiques

```
GET  /hunt                        → Mode Hunt HTML
GET  /api/hunt/data?band=20m      → JSON Hunt
GET  /wanted.json                 → DX Wanted + expedition_calls
POST /api/voacap/predict          → Prédictions HF VOACAP
GET  /weather                     → Météo + Blitzortung
GET  /satellites                  → Visibilité sats
GET  /api/weather/wspr.json       → Snapshot WSPR (callsigns + distances)
```

---

## 🧪 Développement

### Tests
```bash
python3 test_dxcc_hunt.py      # 13/13
python3 test_country_meta.py   # 16/16
```

### Validation pré-déploiement
```bash
python3 -m py_compile webapp.py
node --check templates/ai_insight.html
node --check templates/index.html
```

---

## 📝 Licence & Crédits

- **Code** : F1SMV, MIT — codé avec Claude AI (Anthropic)
- **Données**
  - Esri Imagery (© Esri)
  - Beacons IARU-R1 (DJ5CW, TU Dresden)
  - REST Countries API v3.1
  - LoTW ARRL
  - Blitzortung MQTT
  - VOACAP (US gov, open source)
  - ng3k.com (expéditions DX)

---

**v12.7** — Septembre 2026  
*"Hunt smarter, not harder"*
