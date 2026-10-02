# 🛰️ Neural DX Watcher

> Plateforme de monitoring DX en temps réel pour radioamateurs — F1SMV / JN23
> Raspberry Pi 5 · Flask · SQLite · Leaflet.js · WSJT-X · Adaptive AI Insight Engine

---

## 📸 Aperçu

![Aperçu du Dashboard](apercu.png)

---

## Table des matières

- [Présentation](#-présentation)
- [Stack technique](#-stack-technique)
- [Historique des versions](#-historique-des-versions)
  - [v13.0 — Adaptive Insight Engine ← ACTUEL](#v130--adaptive-insight-engine--actuel)
  - [v12.7 — Fixes & Polish](#v127--fixes--polish)
  - [v12.6 — VOACAP HF Propagation](#v126--voacap-hf-propagation)
  - [v12.5 — AI Insight Engine (naissance)](#v125--ai-insight-engine-naissance)
  - [v12.2 — MSK144 & Satellites](#v122--msk144--satellites)
  - [v12.1 — Beacons & Lightning](#v121--beacons--lightning)
  - [v11.x — Données & Infrastructure](#v11x--données--infrastructure)
  - [v9.5 — Fondations & Roadmap](#v95--fondations--roadmap)
- [Page AI Insight — Architecture détaillée](#-page-ai-insight--architecture-détaillée)
- [Déploiement](#-déploiement)
- [APIs disponibles](#-apis-disponibles)

---

## 🎯 Présentation

Neural DX Watcher est une application web personnelle de monitoring DX pour radioamateurs. Elle agrège en temps réel les spots du cluster DX telnet, les décodages WSJT-X en UDP local, les données de propagation solaire (SFI/K/A), la météo espace, les balises VHF/UHF, le suivi satellitaire SGP4 et les corrélations météo/foudre.

Depuis la v12.5, l'application embarque un **moteur d'intelligence artificielle adaptatif** qui prédit les ouvertures de propagation, mesure ses erreurs, et s'auto-optimise chaque nuit — une ambition expérimentale pour un projet solo sur Pi.

---

## 🔧 Stack technique

| Composant | Technologie |
|-----------|-------------|
| Backend | Python 3.11 / Flask |
| Base de données | SQLite (`analytics.sqlite`, `predictor.sqlite`) |
| Frontend | Leaflet.js, SortableJS, Space Grotesk / IBM Plex Mono |
| Données solaires | NOAA SWPC (SFI, K, A) |
| Propagation HF | VOACAP (intégré v12.6) |
| Météo/Tropo | Open-Meteo (850hPa, humidité, CAPE) |
| Foudre | Blitzortung MQTT (grille 3×3 autour du QTH) |
| Signaux reçus | PSK Reporter MQTT + HTTP fallback |
| WSPR | wspr.live |
| Satellites | CelesTrak GP API (TLE), SatNOGS (fréquences), SGP4 |
| Cluster DX | Telnet (dxfun.com:8000, dxc.k0xm.net:7300, dxc.nc7j.com:7373) |
| WSJT-X | UDP local port 2237 (décodages temps réel) |
| Balises VHF | dl0tud.tu-dresden.de (CSV IARU R1, auto-update mensuel) |

---

## 📜 Historique des versions

---

### v13.0 — Adaptive Insight Engine ← ACTUEL

**Date :** 26 septembre – 1er octobre 2026

Version la plus ambitieuse. L'AI Insight Engine devient **adaptatif** : il prédit, mesure ses erreurs, s'optimise automatiquement chaque nuit, et boucle sur lui-même. Développé contre un CDC de 31 sections — 9 sections livrées, 69/69 tests unitaires.

#### Livraisons v13.0

| Section | Module | Lignes | Tests | Status |
|---------|--------|--------|-------|--------|
| §8 | PropagationFSM (7 états × 5 bandes) | 460 | 10/10 | ✅ |
| §12 | Backtester (ECE / Brier / F1) | 200 | 8/8 | ✅ |
| §13 | Optimizer (grid search) | 210 | 8/8 | ✅ |
| §14 | Models (versioning, lifecycle) | 280 | 14/14 | ✅ |
| §14b | Scoring live depuis `active_model.config` | — | — | ✅ |
| §15 | QualityGate (4 checks) | 165 | 14/14 | ✅ |
| §24 | Auto-Test (feedback loop live) | 270 | 5/5 | ✅ |
| §25 | DriftMonitor | 180 | 4/4 | ✅ |
| §32 | NightlyCycle (3h UTC, 7j/14j/30j) | 280 | 6/6 | ✅ |

#### Nouveau mode radio : JTTY

**JTTY** (WSJT-X 3.2.0-rc1) intégré dans le scoring, les filtres et les badges UI. Mode numérique non synchronisé proposé par K1JT, proche du RTTY. Plan de bande préliminaire : 11 fréquences de rendez-vous (1.838–144.160 MHz). Couleur UI : orange `#ff9e2c`.

#### Widget Auto-Test

Nouveau panneau dans la page AI Insight : **🔄 Auto-Test (Feedback Loop)**. Affiche en temps réel les prédictions émises, les validations reçues et le score de fraîcheur. Légende bilingue FR/EN (14px, orange) pour guider la lecture des métriques.

---

### v12.7 — Fixes & Polish

**Date :** Septembre 2026

- Fix des indicatifs WSPR (formats `/P`, `/MM`, etc.)
- Correction de la géolocalisation DX pour certaines entités DXCC après le fix cty.dat v11
- Extension des bandes VOACAP couvertes dans le calcul de propagation
- Stabilisation du drag & drop des panneaux (SortableJS)
- Badge expédition : indicateur visuel pour les préfixes rares actifs

---

### v12.6 — VOACAP HF Propagation

**Date :** Septembre 2026

Intégration de **VOACAP** (Voice of America Coverage Analysis Program), standard de référence pour la prédiction de propagation HF point-à-point :

- Calcul backend Python des probabilités de circuit par bande (80m→10m) pour un chemin QTH → zone cible
- Panneau visuel dans AI Insight avec probabilités par bande et heure UTC
- Note explicative : le calcul couvre **un chemin spécifique**, pas l'activité globale de la bande

---

### v12.5 — AI Insight Engine (naissance)

**Date :** Septembre 2026 — *Version charnière*

C'est ici que Neural DX Watcher change de nature. Jusqu'en v12.2, l'application était un agrégateur temps réel. En v12.5, elle acquiert un **cerveau autonome**.

#### Module analytics.py

Module entièrement autonome avec sa propre base SQLite `data/analytics.sqlite`. Jamais couplé à `predictor.py`. Sources en cascade :
1. `predictor.sqlite` (si disponible et intact)
2. `analytics.sqlite` (source primaire)
3. Buffer in-memory (fallback ultime)

#### Page AI Insight — Version initiale

Refonte complète avec timestamps UTC sur chaque bloc. Panneaux : Propagation par bande, DXCC actifs (2h), Calibration SPD, Solar/Geomag, DX Briefing narratif FR/EN.

#### Bug critique découvert en production

`history_maintenance_worker` wrappait `verify_predictions()` dans `except: logger.debug(...)` — une corruption SQLite (perte de courant SD card) échouait en silence depuis des semaines et gelait le panneau "fiabilité mesurée". Fix : toutes les erreurs de workers de fond loggées au niveau `WARNING` minimum.

---

### v12.2 — MSK144 & Satellites

**Date :** Septembre 2026

- **MSK144** : plage de détection corrigée (144 350–144 370 kHz)
- **PSK Reporter** : flux MQTT "MY SIGNAL" temps réel (qui vous reçoit, sans polling HTTP)
- **Satellites** : panneau de co-visibilité 100% local via sgp4 — deux satellites simultanément visibles depuis le QTH. Aucune dépendance externe contrairement à HamClock (hams.at)
- AO-92 / AO-109 : déorbitées 2024, TLE absents = comportement correct (non un bug)

---

### v12.1 — Beacons & Lightning

**Date :** Septembre 2026

- **Page Beacons** (`weather.html`) : panneau de réception des balises IARU R1, worker d'auto-update mensuel depuis dl0tud.tu-dresden.de
- **Basemap** : migration CARTO → Esri Dark Gray Canvas (CARTO requiert désormais des clés API). Ordre de tuiles `{z}/{y}/{x}`
- **Bug critique restauré** : `get_weather_alerts()` supprimée accidentellement par un `str_replace` mal calibré

---

### v11.x — Données & Infrastructure

**Date :** Août 2026

- **NOAA Kp** : fix du parseur — le endpoint retourne `[{"time_tag":..., "Kp":...}]` (JSON-of-objects). Retournait `None` silencieusement depuis des semaines
- **Blitzortung MQTT** : fix du format de topic (`blitzortung/1.1/s/p/e/#`, slash-separated) — CONNACK=0 mais aucune donnée
- **cty.dat longitude** : conversion systématique `lon = -raw_lon` (West-positive → East standard). Un conditionnel laissait les entités asiatiques en miroir dans l'Atlantique
- **Distances** : filtrage des distances impossibles (FT8 capé ~1 000 km, demi-circonférence = 20 037 km)
- **PSK Reporter MQTT** : topic `pskr/filter/v2/+/+/{MY_CALL}/+/#`, priorité MQTT avec fallback HTTP transparent

---

### v9.5 — Fondations & Roadmap

**Date :** Été 2026

Première version publiée avec un cockpit fonctionnel : carte 6m Leaflet temps réel, DX Feed, pavés de bandes HF/VHF, suivi satellitaire de base. La roadmap v9.5 posait les grandes ambitions qui structurent toutes les versions suivantes :

1. **Moteur prédictif** — scoring probabiliste bande/heure/saison → *réalisé en v13.0*
2. **Alertes push ntfy.sh** — notification mobile spot rare / ouverture 6m → *en cours*
3. **Mode Chasse DXCC** — croisement LoTW temps réel → *en cours*
4. **Timeline replay 24h** — scrubber sporadic-E heure par heure → *planifié*
5. **Stats WSJT-X** — distance max décodée par bande/heure → *planifié*

---

## 🧠 Page AI Insight — Architecture détaillée

La page `/ai-insight` est le cœur expérimental de Neural DX Watcher v13.0.

### Boucle fermée complète

```
Spots temps réel (Cluster DX telnet + WSJT-X UDP)
              │
              ▼
┌─────────────────────────────────────────────────────┐
│  §8 — PropagationFSM                                │
│  7 états × 5 bandes                                 │
│  IDLE→RISING→OPENING→STRONG→PEAK→DECLINING→CLOSED   │
│  Horodate début / pic / fin de chaque ouverture     │
└──────────────────────────┬──────────────────────────┘
                           │ événements
                           ▼
┌─────────────────────────────────────────────────────┐
│  §12 — Backtester                                   │
│  Rejoue l'historique SQLite                         │
│  Calcule ECE / Brier / F1                           │
└──────────────────────────┬──────────────────────────┘
                           │ métriques
                           ▼
┌─────────────────────────────────────────────────────┐
│  §13 — Optimizer                                    │
│  Grid search : distance_bonus, poids FT8, cap SPD   │
│  Sélectionne la config avec le meilleur ECE         │
└──────────────────────────┬──────────────────────────┘
                           │ meilleur candidat
                           ▼
┌─────────────────────────────────────────────────────┐
│  §14 + §15 — Models + QualityGate                   │
│  CANDIDATE → VALIDATED → ACTIVE → DEPRECATED        │
│  4 checks avant promotion :                         │
│    ✓ ECE < 0.20      ✓ F1 > 0.60                   │
│    ✓ N_preds > 10k   ✓ Drift < 5% vs modèle actif  │
│  Echec → candidat rejeté, ancien modèle conservé   │
└──────────────────────────┬──────────────────────────┘
                           │ config promue
                           ▼
┌─────────────────────────────────────────────────────┐
│  §14b — calculate_spd_score() — Scoring live        │
│  Lit dynamiquement active_model.config à chaque     │
│  appel — la config de cette nuit tourne dès 3h01    │
└──────────────────────────┬──────────────────────────┘
                           │
              ┌────────────┤
              ▼            ▼
┌──────────────────┐  ┌────────────────────────────────┐
│ §32 NightlyCycle │  │  §25 — DriftMonitor            │
│ Chaque nuit      │  │  Surveille la dérive ECE        │
│ 03:00 UTC        │  │  Alerte si dégradation          │
│ Teste 7j/14j/30j │  └──────────────┬─────────────────┘
│ → promeut meill. │                 │ signaux
└──────────────────┘                 ▼
                     ┌────────────────────────────────┐
                     │  §24 — Auto-Test               │
                     │  10 prédictions/heure          │
                     │  Valide vs spots réels reçus   │
                     │  score = 1 − âge_min/60        │
                     │  Alimente DriftMonitor en       │
                     │  continu                       │
                     └────────────────────────────────┘
```

### Ce qui est novateur

**1. Auto-calibration nocturne (NightlyCycle)**

Les paramètres de scoring SPD ne sont plus des constantes hardcodées. Chaque nuit à 3h UTC, le système rejoue 7, 14 et 30 jours d'historique, mesure objectivement quelle fenêtre prédit le mieux la propagation du lendemain, puis promeut automatiquement le meilleur modèle si les 4 checks passent.

**2. Versioning immuable avec rollback**

Chaque configuration testée est versionnée de façon permanente en SQLite (`model_versions`). Si une mauvaise promotion est détectée, le rollback est possible. Cycle `CANDIDATE → VALIDATED → ACTIVE → DEPRECATED`.

**3. FSM de propagation 7 états × 5 bandes**

`PropagationFSM` suit indépendamment 5 bandes à travers 7 états, horodate précisément chaque ouverture du début au pic à la fin. Données exploitables pour entraîner les prédictions suivantes.

**4. Auto-Test : feedback live en temps réel**

`adaptive/auto_test.py` émet 10 prédictions probabilistes par heure (1 FT8 par bande), les confronte aux spots réels dès qu'ils arrivent (fenêtre ±1h). Le match_score mesure la fraîcheur : spot à 2 min → score 0.97, spot à 55 min → score 0.08. Purge automatique des prédictions non validées de +24h.

**5. Scoring SPD dynamique (§14 Integration)**

`calculate_spd_score()` lit la config du modèle actif via `ModelRegistry.get_active_model()` à chaque appel. Boucle entièrement fermée : données → apprentissage → scoring → données.

### Panneaux de la page AI Insight

| Panneau | Données | Rafraîchissement |
|---------|---------|-----------------|
| Propagation par bande | Spots 30 min, FSM states | 30s |
| Solar + Geomag | SFI/K/A NOAA | 5 min |
| DX Briefing (FR/EN) | Synthèse narrative automatique | 2 min |
| VOACAP HF | Probabilités circuit par bande/heure | Manuel |
| Calibration SPD | ECE/F1 du modèle actif | 5 min |
| FSM States | État temps réel par bande | 30s |
| Optimizer history | Runs, ECE, promotions | 1 min |
| Model versions | ACTIVE / CANDIDATE / DEPRECATED | 1 min |
| DriftMonitor | ECE glissant, alertes dérive | 1 min |
| 🔄 Auto-Test | Prédictions + validations live | 10s |

### Lire le widget Auto-Test

```
Prédictions : 11
  → 1 pari émis par bande à chaque heure UTC (10 bandes = 10 paris)
  → Purgés après 24h si aucun spot ne les valide

Validées : 5 (45%)
  → 5 bandes prédites ont reçu un vrai spot dans l'heure
  → Les 6 autres : bandes fermées (normal selon propagation du moment)

Score : 0.98
  → Fraîcheur moyenne des confirmations
  → 0.98 = spots arrivés quasi immédiatement après la prédiction
  → Score bas = bande ouverte tardivement dans l'heure (≈60 min)

Chaque validation alimente le DriftMonitor → NightlyCycle à 3h UTC.
```

### Modes radio supportés

| Mode | Fréquences clés | Couleur UI |
|------|-----------------|------------|
| FT8 | 14.074, 7.074, 50.313 MHz… | Violet `#a78bfa` |
| FT4 | 14.080, 7.047 MHz… | Rose `#ff00cc` |
| CW | Segments CW par bande | Jaune `#fbbf24` |
| SSB | Segments SSB par bande | Cyan `#22d3ee` |
| MSK144 | 144.360 MHz ±10 kHz | Cyan foncé |
| PSK31 | 14.070–14.071 MHz | Jaune-vert |
| RTTY | Segments RTTY par bande | Orange `#ff8800` |
| **JTTY** | **11 fréquences : 1.838–144.160 MHz** | **Orange `#ff9e2c`** |
| JT65 | Segments JT65 | Cyan |
| AM / FM | Segments AM/FM | Vert |

---

## 🚀 Déploiement

```bash
git clone https://github.com/F1SMV/Neural-DX-Watcher.git
cd Neural-DX-Watcher
./start.sh
```

> ⚠️ **Toujours utiliser `./start.sh`**, jamais `python3 webapp.py` directement.
> Le script active le venv (`venv/bin/python3`), vérifie les dépendances et nettoie les ports.

| URL | Page |
|-----|------|
| `http://192.168.1.79:8000` | Accueil + Cockpit 6m |
| `http://192.168.1.79:8000/ai-insight` | AI Insight Engine |
| `http://192.168.1.79:8000/satellites` | Suivi satellitaire |
| `http://192.168.1.79:8000/hunt` | Chasse DXCC |
| `http://192.168.1.79:8000/weather` | Météo + Balises + Foudre |

---

## 📡 APIs disponibles

### Spots & DX

| Endpoint | Description |
|----------|-------------|
| `GET /spots.json?band=6m&mode=FT8` | Spots filtrés par bande/mode |
| `GET /api/map/spots.json` | Spots géolocalisés pour carte |
| `GET /api/wsjtx/spots.json` | Décodages WSJT-X temps réel |
| `GET /api/weather/wspr.json` | Confirmation WSPR 2m |
| `GET /api/psk_reporter.json` | Réceptions PSK Reporter |

### Propagation & Solaire

| Endpoint | Description |
|----------|-------------|
| `GET /api/solar.json` | SFI/K/A + statut propagation |
| `GET /api/voacap.json` | Prédictions VOACAP par bande/zone |
| `GET /api/briefing.json?lang=fr` | DX Briefing narratif |

### Adaptive Insight Engine (v13.0)

| Endpoint | Description |
|----------|-------------|
| `GET /api/adaptive/fsm.json` | États FSM temps réel par bande |
| `GET /api/adaptive/events.json` | Historique des ouvertures détectées |
| `GET /api/adaptive/fsm_stats.json` | Statistiques globales FSM |
| `POST /api/adaptive/optimize.json` | Déclenche l'optimizer manuellement |
| `GET /api/adaptive/optimizer_runs.json` | Historique des runs |
| `GET /api/adaptive/models/active.json` | Modèle actif + config en cours |
| `GET /api/adaptive/models/candidates.json` | Candidats en attente de validation |
| `GET /api/adaptive/models/versions.json` | Toutes les versions |
| `GET /api/adaptive/qg/status.json` | QualityGate : seuils + statut |
| `POST /api/adaptive/qg/validate/<id>.json` | Validation manuelle d'un candidat |
| `GET /api/adaptive/nightly/latest.json` | Derniers runs NightlyCycle |
| `POST /api/adaptive/nightly/run.json` | Déclenche NightlyCycle manuellement |
| `GET /api/adaptive/autotest/stats.json` | Stats Auto-Test globales |
| `GET /api/adaptive/autotest/latest.json` | Dernières prédictions + validations |
| `POST /api/adaptive/autotest/predict.json` | Crée une prédiction manuelle |

---

## 📊 État CDC v13.0

**9 / 31 sections livrées · 69 / 69 tests ✅**

| Section | Feature | Status |
|---------|---------|--------|
| §8 | PropagationFSM | ✅ Live |
| §12 | Backtester | ✅ Live |
| §13 | Optimizer | ✅ Live |
| §14 | Models (versioning) | ✅ Live |
| §14b | Scoring dynamique | ✅ Live |
| §15 | QualityGate | ✅ Live |
| §24 | Auto-Test (feedback loop) | ✅ Live |
| §25 | DriftMonitor | ✅ Live |
| §32 | NightlyCycle | ✅ Live |
| §2 | Distribution (GitHub / Docker) | 🔜 |

---

## 🔭 Prochaines étapes

- **Alertes ntfy.sh** — notification mobile spot rare / ouverture 6m
- **Mode Chasse DXCC** — croisement LoTW temps réel, ne montrer que ce qui manque
- **Timeline replay 24h** — scrubber pour revoir une ouverture sporadic-E heure par heure
- **JTTY live** — suivi actif dès WSJT-X 3.2.0 release stable
- **§24b** — prédictions basées SFI + heure UTC

---

*Neural DX Watcher v13.0 — F1SMV — JN23 — La Seyne-sur-Mer, France*
*Développé avec Claude (Anthropic) — Septembre / Octobre 2026*
