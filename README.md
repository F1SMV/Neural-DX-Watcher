# Neural DX Watcher v12.5

**Une application web de chasse DXCC intelligente pour le radioamateur moderne**, basée sur Flask + SQLite, tournant sur Raspberry Pi 5 à `192.168.1.81:8000`.

Utilisateur : **F1SMV** (QTH : JN23, La Seyne-sur-Mer, 43.076°N 5.873°E)  
Dépôt : [F1SMV/Neural-DX-Watcher](https://github.com/F1SMV/Neural-DX-Watcher)

---

## 📸 Aperçu
![Aperçu du Dashboard](apercu.png)

---

## 🎯 Fonctionnalités Principales

### Analyse IA / AI Insight (v12.5) ✨
Route **`/ai_insight`** — tableau de bord d'analyse comportementale, entièrement bilingue FR/EN :
- **Activité récente** : sparkline heure par heure (24h), pic et heure courante mis en évidence
- **Prochaines heures** : fréquence d'activité observée par le passé sur les créneaux à venir (même heure, ou même jour+heure dès 14j d'historique) — **explications bilingues intégrées** précisant qu'il s'agit d'une fréquence constatée (« au moins un spot »), pas d'une prévision de propagation ni d'une mesure de force d'ouverture
- **Fiabilité affichée** : créneaux avec moins de 5 observations signalés en **orange** avec info-bulle, pour éviter de lire un 100% comme un signal fort en tout début de collecte
- **Quand ça ouvre** : heatmap jour de semaine × heure UTC, moyenne par occurrence (pas de cumul)
- **Tendances par bande** : comparaison période récente vs précédente, triée 160 m → 23 cm
- **Rafraîchissement automatique** : nouvel appel `/api/analytics` toutes les 5 min (fetch, sans recharger la page), barre de maturité recalculée chaque minute
- **Module `analytics.py`** entièrement autonome : base dédiée `data/analytics.sqlite`, chaîne de repli multi-source (`predictor.sqlite` → spots en mémoire) si `predictor.py` n'est pas actif

### Mode Chasse DXCC (v12.4) ✨
Route dédiée **`/hunt`** — interface full-screen optimisée pour le hunt en direct :
- **Cible n°1 en hero** : présentation large du pays cible, drapeau 🇵🇬, capitale, population, décalage horaire (données en temps réel via REST Countries API, cache 30j)
- **Carte Leaflet monde** (320px, pattern cockpit 6m) : QTH + station DX + liaison pointillée, marqueurs secondaires pondérés par SPD (rareté + distance + split + mode)
- **Liste secondaire cliquable** : top 15 cibles triées par SPD, clic = zoom sur la carte, classe `.active` sur le lien nav 🎯 HUNT
- **Filtre bande en temps réel**, rafraîchissement 15s
- **localStorage tracking** : suivi des appels intéressants

### Propagation & Prédictions
- **VOACAP Rapide** : chemin HF précis vers la zone sélectionnée (5min)
- **Indicateurs troposphériques** : inversion 850hPa, humidité, CAPE
- **Blitzortung MQTT** : foudre temps réel (grid 3×3 autour QTH), correlation RF/QRN
- **WSPR global** : spots par bande, localisation bruitée, confirmation 2m radar

### Satellites & Beacons
- **Visibilité co- et contres-empreintes** : SGP4, horizon 48h, ≥30s overlap
- **Beacons VHF/UHF/SHF** : 62 balises IARU, mise à jour mensuelle dl0tud.tu-dresden.de
- **SatNOGS pour les fréquences**

### Gestion LoTW & Statistiques
- **Intégration LoTW native** : cache disque 6589 QSOs, synchronisation périodique
- **Dxcc_hunt.py** : moteur de scoring par bande, rareté + distance, log interne en base
- **Briefing ARRL** : actualités récentes remplaçant dxnews.com (HTML scraping)

### Architecture Backend
- **`webapp.py`** : 7500+ lignes, Python 3.13, Flask, SQLite
- **`country_meta.py`** : enrichissement pays (drapeau, capitale, population, TZ) — cache 30j, 0 appel réseau si répété
- **`dxcc_hunt.py`** : logique pure DXCC Hunt (injectable, testable, 13/13 tests ✅)
- **`ntfy_alerts.py`** : notifications desktop/mail (v10.0, complet)
- **`test_dxcc_hunt.py`, `test_country_meta.py`** : suites unitaires complètes

---

## v12.5 — Changelog Détaillé

### Nouvelles Fonctionnalités
- **Page Analyse IA refondue** (`ai_insight.html`, route `/ai_insight`)
  - Nouveau module `analytics.py` totalement autonome : base dédiée `data/analytics.sqlite`, ne dépend jamais d'un `predictor.py` qui tournerait ou non (repli silencieux sinon)
  - 4 panneaux dynamiques : Activité récente, Prochaines heures, Quand ça ouvre, Tendances par bande
  - Rafraîchissement AJAX toutes les 5 min, barre de maturité (niveau de collecte) qui avance chaque minute sans appel API

### Améliorations UX
- **Clarté du panneau « Prochaines heures »** : sous-titres et info-bulles bilingues FR/EN ajoutés sur les 4 panneaux, y compris les états « pas encore assez de données »
  - Le % affiché est désormais explicitement présenté comme une fréquence d'activité passée (« au moins un spot reçu »), et non une prévision de propagation — évite la confusion quand tous les créneaux affichent 100% en tout début de collecte
  - Créneaux à faible échantillon (< 5 observations) signalés en **orange** avec info-bulle explicative, plutôt qu'un pourcentage nu non qualifié
  - Encadrés de synthèse (« meilleur créneau ») repassés en accent orange pour plus de lisibilité, et affichent désormais le nombre d'observations (n=X)

### Correctifs
- **`dxcc_hunt.py`** : validation des distances — les distances physiquement impossibles sont désormais filtrées (FT8 plafonné à ~1 000 km ; toute distance approchant le demi-tour de la Terre, 20 037 km, est rejetée), ce qui fiabilise le scoring de la liste Hunt
- **`weather.html`** : migration du fond de carte CARTO → Esri Dark Gray Canvas (CARTO exige désormais une clé API) ; correction de l'ordre des tuiles `{z}/{y}/{x}`
- **`hunt.html`** : stabilisation supplémentaire de la carte Leaflet (alignement fin sur le pattern cockpit 6m éprouvé — `invalidateSize` étagé, zéro bord gris)

### Infrastructure & Tests
- **Validation front-end** : rendu simulé en Node (`node --check` + exécution des fonctions de rendu avec données réalistes et cas limites — échantillon faible, probabilité à 0, panneaux verrouillés) avant déploiement

---

## v12.4 — Changelog Détaillé

### Nouvelles Fonctionnalités
- **Mode Hunt DXCC complet** (routes `/hunt`, `/api/hunt/data`) 
  - Tri par score SPD (signal propagation distance) plutôt que simple "rare/pas rare"
  - Cible n°1 enrichie (drapeau, capitale, population, décalage horaire)
  - Marqueurs secondaires multi-cibles sur la carte, pondérés par SPD
  - Navigation cliquable : clic sur une cible secondaire zoom la carte dessus

- **`country_meta.py`** — nouvel module richesse de pays DXCC
  - Requêtes API REST Countries v3.1 (gratuit, open)
  - Cache disque 30 jours (ces données ne changent pas)
  - Fallback gracieux : panne réseau → cache sinon `None`
  - Aliases pour entités DXCC non-souveraines (Corsica→France, etc.)

- **Lien 🎯 HUNT dans la nav** complète + indicateur clignotant (animation 20s)
  - localStorage tracking watchlist de calls intéressants
  - `/hunt` clignotement jaune si nouvelle opportunité depuis visite précédente

### Correctifs Critiques
- **Tri DXCC Hunt** : remplacé booléen `is_rare` par score SPD continu (rareté + distance + split + mode)
- **Leaflet carte hunt** : copie exacte du pattern cockpit 6m éprouvé
  - `worldCopyJump: true`, `center: QTH`, `zoom: 2` — **zéro bord gris**
  - invalidateSize étagé `[120, 350, 900]` ms

### Infrastructure & Tests
- **13/13 tests unitaires** `dxcc_hunt.py`
- **16/16 tests unitaires** `country_meta.py`
- **Validation frontend** : JS `node --check`, Jinja2 render, Flask `test_client()`

---

## 🚀 Installation Rapide

### Prérequis
- Python 3.13 + venv
- Raspberry Pi 5 (ou Linux x64)
- Ports réseau : 8000 (Flask)

### Déploiement sur Pi
```bash
cd ~/Spot-Watcher-DX

# Fichiers critiques à copier
cp webapp.py country_meta.py dxcc_hunt.py .
cp hunt.html templates/
cp index.html templates/

# Redémarrer
pkill -f "python.*webapp.py"
bash start.sh
```

### Vérification
```bash
curl http://192.168.1.81:8000/hunt
curl 'http://192.168.1.81:8000/api/hunt/data?band=20m'
```

---

## 📊 Modules Importants

| Fichier | Rôle | État |
|---------|------|------|
| `webapp.py` | Backend Flask principal | ✅ v12.5 |
| `analytics.py` | Moteur Analyse IA (autonome, cache dédié) | ✅ v12.5 |
| `ai_insight.html` | UI Analyse IA (bilingue FR/EN) | ✅ v12.5 |
| `dxcc_hunt.py` | Moteur scoring Hunt DXCC | ✅ 13/13 tests + validation distances |
| `country_meta.py` | Enrichissement pays (cache 30j) | ✅ 16/16 tests |
| `hunt.html` | UI Mode Hunt (Leaflet, markers SPD) | ✅ Cockpit 6m |
| `index.html` | Dashboard + nav 🎯 HUNT | ✅ v12.4 |

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
GET /hunt                    → Mode Hunt HTML
GET /api/hunt/data?band=20m  → JSON Hunt
GET /weather                 → Météo + Blitzortung
GET /satellites              → Visibilité sats
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
node --check hunt.html
python3 -m py_compile webapp.py country_meta.py
```

---

## 📝 Licence & Crédits

- **Code** : F1SMV, MIT
- **Données** suivez moi sur X 
  - Esri Imagery (© Esri)
  - Beacons IARU-R1 (DJ5CW, TU Dresden)
  - REST Countries API v3.1
  - LoTW ARRL
  - Blitzortung MQTT

---

**v12.5** — Septembre 2026  
*"Hunt smarter, not harder"*
