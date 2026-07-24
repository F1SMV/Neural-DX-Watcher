# ⚡ Neural DX Watcher — v11.2

**DX Cluster Dashboard & Advanced Radio Analysis Engine**

Application web locale de surveillance DX et d'analyse radio destinée aux radioamateurs exigeants.  
Conçue pour **observer**, **comprendre** et **prendre du recul** — pas pour faire du bruit visuel.

---

## 🧭 Présentation générale

**Neural DX Watcher** est une application web locale qui :

- se connecte à un ou plusieurs **DX Clusters (Telnet)**
- affiche les **spots en temps réel** (HF / VHF / UHF)
- intègre les **indices solaires** (SFI, A, Kp…)
- conserve une **mémoire exploitable** de l'activité
- propose **plusieurs niveaux de lecture**, du live à l'analyse stratégique
- **prédit** les ouvertures probables selon ton activité et tes DXCC manquants, avec une **fiabilité mesurée** (pas affichée arbitrairement)

> L'objectif n'est pas de voir beaucoup,  
> mais de **voir juste**.

---

## 🖥️ Pages principales

### 1️⃣ Page **Index** — Temps réel & suivi opérateur

Page d'observation immédiate. Elle affiche :
- le flux de spots en direct
- les bandes actives
- les DX recherchés (*wanted*)
- les indices solaires
- les signaux de **surge** d'activité (HF, 6m et 2m)

👉 **Objectif : savoir ce qui se passe maintenant.**

---

### 📡 Pavé **WATCHLIST · Tracking**

Fonction introduite pour répondre à un besoin simple :
> *« Je n'étais pas devant l'écran : qu'ai-je raté ? »*

- basé sur la watchlist
- exploite un historique en mémoire
- affiche les derniers spots par indicatif

Philosophie :
- ❌ pas un log brut
- ❌ pas un dump massif
- ✅ un outil de rattrapage
- ✅ pensé pour l'opérateur humain

---

### 📶 Pavé **MY SIGNAL** — Self-monitoring PSK Reporter *(v10.5)*

> *« Qui m'entend, où, avec quel SNR ? »* — sans jamais quitter l'application.

- Source : API PSK Reporter, interrogée en JSONP
- Toutes bandes HF/VHF/UHF, tous modes digitaux (FT8/FT4/WSPR/JT65/JS8/MSK144)
- Indicatif receveur, mode, fréquence, distance, âge du rapport, SNR coloré
- Intégré dans les **3 modes** (CLASSIC, SMART, COCKPIT)

👉 **Test d'antenne instantané, vérification avant de lancer un appel dans un pileup.**

---

### 2️⃣ Page **Map** — Carte d'observation (micro-lecture)

Carte classique des **spots individuels** :
- chaque point = **une station**
- représentation géographique immédiate
- vision instantanée

👉 **Objectif : voir où ça se passe.** La page Map est un **outil d'exécution**.

---

### 3️⃣ Page **AI Insight** — Analyse & META ANALYSE différée *(anciennement "Analyse", renommée v10.2)*

Outil volontairement **non temps réel**, basé sur l'analyse du log applicatif. Accessible via `/ai-insight`.

👉 **Outil de recul**, pas un gadget.

---

### 4️⃣ Page **World** — Forecast & Anomalies

La page **World** est **fondamentalement différente** de la page Map.

| Page  | Nature              | Question                                       |
| ----- | ------------------- | ----------------------------------------------- |
| Map   | Observation brute   | Qui est actif maintenant ?                     |
| World | Analyse interprétée | Où la propagation est anormalement favorable ? |

- affichage de **zones**, pas de stations
- clustering spatio-temporel
- filtrage du bruit
- rafraîchissement contrôlé

👉 **World décide, Map exécute.**

---

### 5️⃣ Page **Briefing**

Se met à jour toutes les 12 heures, reprenant les infos DX essentielles. Possibilité d'ajouter automatiquement les calls dans la watchlist de la page Index. Vous ne raterez aucune expédition : dès qu'un call est spotté, il s'affiche en jaune dans le pavé DX spots.

---

### 6️⃣ Page **Satellites**

Suivi temps réel des satellites amateurs (AO-73, AO-91, AO-92, ISS, RS-44, SO-50, FO-29, PO-101…). Calcul local via **sgp4**, prochains passages (AOS/TCA/LOS), **fréquences uplink/downlink** depuis SatNOGS *(v10.1)*, type de satellite auto-détecté *(v10.1)*, calcul d'azimut corrigé *(v10.1)*, TLE au format JSON OMM compatible post-2026 *(v10.2)*.

---

📸 Aperçu

![Apercu du Dashboard](apercu.png)

---

## 🚀 Installation

```bash
git clone https://github.com/F1SMV/Neural-DX-Watcher.git
cd Neural-DX-Watcher
chmod +x start.sh
./start.sh
```

L'application sera accessible sur `http://localhost:8000`

> 💡 Un **Raspberry Pi** est recommandé pour la faible consommation électrique, mais le programme fonctionne sur n'importe quel PC sous Linux.

---

## ⚙️ Architecture technique

- Backend : Python / Flask
- Frontend : HTML / CSS / JavaScript
- Cluster : Telnet DX Cluster
- Analyse : scripts Python dédiés (`predictor.py`, `dxcc_resolver.py`)
- Stockage : mémoire + JSON locaux + **SQLite**

Aucune dépendance cloud.

---

## 🗂️ Historique des versions

### v11.2 — Corrections critiques : META ANALYSE, AI Insight, Satellites

#### 🐛 Erreur 500 sur META ANALYSE — script analyseur manquant

Le dossier `tools/` et le script `tools/log_meta_analyzer.py` n'existaient pas sur le serveur — la route `POST /api/meta/run` échouait systématiquement. Écriture complète du script manquant :

- Parse les lignes `SPOT: CALL (band, mode) -> SPD: X pts (Dist: Ykm)` du log applicatif
- Déduplique par indicatif (garde le meilleur score SPD), trie les top spots
- Génère `data/meta/summary.json` au format exact attendu par la page AI Insight
- Conçu pour ne jamais planter : log absent ou vide → résumé valide vide, jamais d'erreur

En complément, le backend renvoie désormais le **détail réel de l'erreur** (`stderr` du script) au lieu d'un simple code retour opaque — les erreurs futures seront immédiatement diagnostiquables au lieu de nécessiter une investigation à l'aveugle.

#### 🔧 Page AI Insight — `confirm()`/`alert()` natifs enfin remplacés

Le renommage `analysis.html` → `ai_insight.html` (v10.2) avait repris une version antérieure aux corrections de dialogue faites en cours de route — les popups navigateur natifs (`confirm()`, `alert()`) étaient toujours présents en production. Corrigé : dialog HTML inline pour la confirmation de relance, message d'erreur détaillé (incluant le `stderr` du backend) affiché directement dans la page.

#### ⏳ Page Satellites — indicateur de chargement

Le premier appel de calcul de position (TLE + sgp4) peut prendre jusqu'à 45 secondes après un démarrage serveur. Ajout d'un indicateur de chargement explicite (sablier animé + message) sur la carte, retiré automatiquement dès que les positions arrivent.

#### 📡 Page Index — message d'attente clarifié

Le tableau de spots affichait un message vide générique sans expliquer que le flux DX Cluster est **temps réel** (pas d'historique à la connexion) — un nouveau spot doit littéralement se produire quelque part après ta connexion pour apparaître. Message remplacé par une explication claire de ce comportement normal.

#### 🎨 Toggle "QUI M'ENTEND" — couleur ajustée

La ligne d'enveloppe de réception passe de vert foncé à **rouge**, nettement plus visible sur le fond satellite Esri des cartes.

---

### v11.1 — Sécurité niveau 2 · Toggle "QUI M'ENTEND" sur les cartes HF & VHF/UHF

#### 🔒 Sécurité niveau 2 — Jeton API local

- Jeton hexadécimal généré automatiquement au premier démarrage, persisté dans `data/api_token.txt` (`chmod 600`)
- Décorateur `@require_api_token` sur les routes qui modifient un état : `/update_qra`, `/spot`, `/api/spot`, `/watchlist.json` (POST/DELETE uniquement — le `GET` reste ouvert, lu en permanence par les 3 modes), `/api/briefing/refresh`, `/api/lotw/login`, `/api/lotw/logout`, `/api/satellites/config`, `/api/satellites/refresh_tle`, `/api/ntfy/test`
- Nouvelle route `GET /api/token` distribue le jeton au frontend
- **Intercepteur `fetch()` global** côté frontend (`index.html`, `satellites.html`, `map.html`, `ai_insight.html`) : toute requête `POST`/`DELETE` reçoit automatiquement l'en-tête `X-API-Token`, sans avoir à patcher chaque appel individuellement
- Bug corrigé : une fonction enregistrée sous deux routes (`/spot` + `/api/spot`) avec `@require_api_token` dupliqué provoquait une `AssertionError` Flask au démarrage — un seul décorateur, positionné juste au-dessus de `def`, résout le conflit d'endpoint

#### 📶 Toggle "QUI M'ENTEND" — Visualisation de la couverture réelle sur les cartes

Nouvelle fonctionnalité exploitant les données déjà collectées par MY SIGNAL : un bouton **`📶 QUI M'ENTEND`** sur chacune des deux cartes (**DX MAP HF** et **DX MAP VHF/UHF**), permettant de visualiser en un coup d'œil qui reçoit réellement le signal, dans quelle direction, et jusqu'où.

**Comportement** :
- Masque les spots DX classiques pendant l'affichage (carte trop chargée sinon)
- Trace une **enveloppe fermée** reliant **toutes** les stations qui te reçoivent, triées par azimut depuis le QTH — un vrai diagramme de réception continu, pas une étoile rayonnant depuis le centre
- Ligne pleine (pas de tirets), vert foncé, bien visible
- Marqueurs triangulaires colorés par SNR (vert ≥-5dB, jaune -15 à -5dB, rouge <-15dB), la station la plus lointaine mise en évidence (🎯)
- Séparation stricte HF / VHF-UHF : un spot 6m ne s'affiche que sur la carte HF, un spot 2m/70cm uniquement sur la carte VHF/UHF (même découpage que `HF_BANDS`/`VHF_BANDS` côté backend) — nouveau champ `band` ajouté à la réponse `/api/my-signal` (via `find_band()`, déjà existant)
- Checkbox **"tout le temps · stations qui me spotent"** — persistée en `localStorage`, restaure l'affichage automatiquement à chaque chargement de page
- Rafraîchissement principal toutes les 3 minutes + vérification légère toutes les 15s qui compare une signature de l'ensemble des stations reçues (call + bande + horodatage) : tout changement (nouvelle station, changement de bande en cours d'opération) déclenche un recalcul immédiat sans attendre le cycle complet

**Bugs corrigés en cours de route** :
- Le rafraîchissement périodique des spots DX classiques (`updateMaps()`) réattachait inconditionnellement les marqueurs à la carte, annulant le masquage demandé — désormais conditionné à l'état du toggle
- Référence à une variable supprimée lors du refactor HF/VHF (`mySignalOn`) provoquant une erreur JS silencieuse à chaque cycle de 90s — nettoyée
- Chevauchement visuel du bouton avec le titre du panneau (`float:right` sur un header non-flex) — corrigé en flexbox `justify-content:space-between`

#### 🎨 Ajustements visuels

- Labels du panel MY SIGNAL agrandis (indicatif, mode/fréquence, distance, badge SNR)
- Distance maximale reportée mise en évidence : taille ×1.35, orange, gras
- Ligne verte de bordure sur les rapports avec SNR > 0dB, nettement renforcée (opacité, épaisseur de bordure)
- Largeur des colonnes du layout classique/smart ajustée : colonne centrale (cartes) élargie de 1cm, colonnes latérales réduites de 0,5cm chacune — meilleure lisibilité des cartes et de leurs nouveaux diagrammes de réception

---

### v11.0 — Moteur prédictif réellement mesuré (refonte complète) · Sécurité renforcée

#### 🧠 Refonte complète de `predictor.py`

Passage d'un système à coefficients manuels non mesurés à un moteur **auto-évalué** :

**Nouveau module `dxcc_resolver.py`** — résolution DXCC unifiée basée sur le fichier `cty.dat` déjà utilisé par le reste de l'application. Gère indifféremment un indicatif (`"DL9XYZ/P"`), un préfixe (`"DL"`), ou un nom d'entité DXCC (`"Germany"`) — corrige un bug sérieux où `_extract_prefix()` découpait aveuglément les 3 premiers caractères de n'importe quelle valeur reçue, y compris un nom de pays provenant de LoTW (`"Germany"` devenait `"GER"` au lieu du préfixe correct `"DL"`), cassant silencieusement les coefficients directionnels du moteur de prédiction.
- Parseur `cty.dat` robuste : gestion des plages de préfixes (`D40-D49`, `D3A-D3Z` par expansion), callsigns exacts en override (`=CALL`), fallback tolérant par recherche de mot-substring pour les variantes de noms courts LoTW vs cty.dat
- Mode dégradé sûr si `cty.dat` est absent — l'application ne plante jamais, elle perd juste la précision directionnelle

**4 modèles de propagation distincts** selon la bande, au lieu d'un seul modèle générique :
- Modèle **Es** (6m) : patterns saisonniers/horaires + boost directionnel par préfixe + dégradation Kp
- Modèle **HF** : ionosphérique, dépendance SFI/Kp par bande + préférence diurne/nocturne
- Modèle **tropo** (2m/4m/70cm/23cm) : bonus crépusculaire + saisonnier été
- Boost **TEP** (trans-équatorial) superposable aux bandes éligibles (6m/10m/15m) en soirée proche des équinoxes

**Auto-vérification des prédictions** : chaque prédiction émise est journalisée dans une nouvelle table `prediction_log` (dédupliquée par bande/préfixe/créneau horaire), puis automatiquement comparée aux spots réellement reçus une fois sa fenêtre échue (nouvelle méthode `verify_predictions()`, appelée toutes les 30 minutes depuis le worker de maintenance existant).

**Fiabilité mesurée affichée** : le panel cockpit "🔮 PRÉDICTIONS PERSONNALISÉES" affiche désormais un bandeau `📊 Fiabilité mesurée : 72% sur 30 jours — 18 observations` (coloré vert/orange/rouge selon le taux), avec détail disponible par modèle (Es/HF/tropo). Tant que l'historique est insuffisant, affiche explicitement "pas encore assez d'historique" plutôt qu'un chiffre fantaisiste. Badge modèle par prédiction (Es cyan / HF orange / Tropo violet).

**Lissage empirique bayésien** : la probabilité finale mélange le score théorique du modèle avec le taux réellement observé dans l'historique pour un bin comparable (même bande, heure UTC ±1h, mois ±1, direction/préfixe) — plus l'historique disponible est riche, plus le score se rapproche de la réalité mesurée. Une table `solar_log` et une méthode `record_solar_sample()` sont préparées (non branchées automatiquement) pour une future v12 qui pourra affiner ce lissage avec un historique SFI/Kp réel.

**Migration de base sécurisée** : les bases `predictor.sqlite` v10 existantes (sans la colonne `prefix`) sont migrées automatiquement au démarrage sans perte de données.

#### 🔒 Sécurité et hygiène

- `debug=False` dans `app.run()` — le débogueur Werkzeug interactif en mode debug exposait une exécution de code arbitraire sur le réseau local en cas d'exception non gérée, une vulnérabilité critique même en usage domestique
- Fichiers d'export LoTW (contenant l'intégralité du journal de contacts) déplacés du dossier `/tmp` (lisible par tous les utilisateurs du système) vers `data/` (privé, déjà exclu de Git), avec permissions restreintes `chmod 600`
- `start.sh` réécrit : arrêt propre par `SIGTERM` (délai d'attente 5s) avant `kill -9` en dernier recours seulement ; installation des dépendances désormais **conditionnelle** — un test rapide vérifie si tout est déjà disponible avant de lancer `pip install`, utilisant `requirements.txt` s'il existe, évitant un appel réseau systématique à chaque démarrage

---

### v10.5 — Theory vs Reality · MY SIGNAL (PSK Reporter self-monitoring)

#### 🔬 Theory vs Reality — Croisement VOACAP × spots réels

Le tableau VOACAP du cockpit propose désormais un **toggle 3 vues** dans son header :

- **THEORY** : prédiction VOACAP théorique calculée depuis SFI/Kp/zone (comportement d'origine)
- **REAL** : intensité des spots réellement observés sur les dernières 24h, agrégés par bande × créneau 3h × zone continentale (EU/NA/AS/OC/AF/SA détectée via préfixe DXCC)
- **Δ DELTA** : écart réel − théorique. Vert = ouverture non prédite (Es/TEP/aurore) ; rouge = bande morte malgré prédiction favorable

Nouvelle route backend : `GET /api/reality-check/<zone>` — interroge la table `spot_log` SQLite du predictor, normalise en intensité relative (0-100%) sur le max toutes bandes/créneaux confondus. Légende bilingue FR/EN orange sous le tableau.

#### 📶 MY SIGNAL — PSK Reporter Self-monitoring

Nouveau panel **"📶 MY SIGNAL"** — qui m'entend, où, avec quel SNR, sans jamais quitter l'application.

- Nouvelle route backend `GET /api/my-signal` : interroge l'API PSK Reporter (`retrieve.pskreporter.info/query`) en **JSONP** (paramètre `callback=cb` — `format=json` ne fonctionne PAS avec cette API, retourne une erreur silencieuse), extraction du JSON en retirant le wrapper `cb(...)` via regex
- Cache serveur 90 secondes (respecte la politique d'usage de PSK Reporter, qui recommande de ne pas interroger plus d'1x/minute)
- Toutes bandes HF/VHF/UHF, tous modes digitaux (FT8/FT4/WSPR/JT65/JS8/MSK144)
- Affichage : indicatif receveur, mode, fréquence, distance calculée (via cty.dat/Maidenhead), âge du rapport, SNR coloré (vert ≥-5dB / jaune -15 à -5dB / rouge <-15dB), résumé en tête de panel
- Intégré dans les **3 modes** de l'application : CLASSIC et SMART (colonne 3) et COCKPIT (colonne 3) — une seule fonction JS peuple les deux emplacements en un seul fetch
- Limité à 20 stations affichées

#### 🔧 Corrections WSJT-X

Le filtre d'injection des spots (CQ uniquement + stations qui m'appellent directement) a été testé sans filtre (tout injecter) mais s'est révélé inutilisable en pratique, le filtre original a été restauré avec une garde anti-self-spot supplémentaire.

> v10.4 était une version de travail interne, jamais publiée — ses fonctionnalités ont été absorbées dans la v10.5.

---

### v10.3 — Détection surge 2m · Navigation AI Insight · Corrections

- **Bug détection surge** : le 2m était explicitement exclu de `analyze_surges()` → aucune alerte même lors de fortes ouvertures Es visibles à l'écran. Corrigé : 2m réintégré avec seuil adaptatif ×2.0 et minimum 8 spots (au lieu de 3) pour éviter les faux positifs sur l'activité 2m locale/EME permanente
- Log `Cluster … a fermé la connexion (EOFError)` rétrogradé de WARNING à INFO — c'est un failover normal entre plusieurs clusters DX, pas une anomalie
- Liens "AI Insight" corrigés dans `index.html`, `satellites.html` — pointaient encore vers `/analysis.html` suite au renommage v10.2
- Page `map-v11.html` (prototype de carte unifiée devenu obsolète après intégration dans le cockpit) supprimée du projet
- Clusters DX Cluster mis à jour : retrait de `cluster.dx.de:7300` (timeout systématique) et `telnet.wxc.kr:23` (DNS mort), ajout de `dxc.k0xm.net:7300` et `dxc.nc7j.com:7373` (fiables), conservation de `dxfun.com:8000`

---

### v10.2 — Migration TLE format JSON OMM (CelesTrak) · Favicon · Page renommée AI Insight

#### 🛰️ Compatibilité catalogues satellites post-juillet 2026

CelesTrak épuisera les numéros de catalogue à 5 chiffres (limite 69999) autour du **12 juillet 2026** — migration préventive.

- `TLE_JSON_SOURCES` : CelesTrak GP API `gp.php?GROUP=amateur&FORMAT=json` + `GROUP=stations&FORMAT=json`
- `_fetch_all_tles()` retourne `(json_tles, fallback_text)` au lieu d'un simple texte
- `_load_tle_cache()` fusionne JSON en priorité + texte AMSAT `nasa.all` en fallback pour satellites manquants
- `NORAD_CAT_ID` entier natif illimité, `TLE_LINE1`/`TLE_LINE2` compatibles `sgp4.twoline2rv()` sans changement du reste du code

#### ⚡ Favicon

Favicon ⚡ SVG inline base64 dans tous les templates (aucun fichier supplémentaire) — bug corrigé : un ancien favicon 📡 avait été concaténé au lieu de remplacé, laissant des fragments SVG orphelins visibles en haut de page.

#### 🧠 Page renommée : Analyse → AI Insight

Template `analysis.html` → `ai_insight.html`, nouvelle route `/ai-insight` (+ alias `/ai_insight`), anciennes routes `/analysis` et `/analysis.html` conservées en redirect automatique.

#### 🎨 Améliorations page AI Insight

Variables CSS manquantes corrigées (`--font-sans`, `--font-display`, `--success`), `fillList()` enrichi pour Long Distance (distance km + bande + mode + heure), calls rares désormais cliquables (ajout rapide à la watchlist), `confirm()` natif remplacé par une dialog HTML inline pour la META analyse (message d'erreur contextuel en cas de 500), indicateur de dernière mise à jour + spinner de refresh, toggle langue globale FR/EN persisté localStorage, Chart.js amélioré (tooltips personnalisés, animation `easeOutQuart`, hauteur adaptative 220px).

---

### v10.1 — Mode COCKPIT redessiné · Radar sweep · Satellites améliorés · Corrections

#### 🎛 Refonte visuelle du mode COCKPIT

**Pavé PROPAGATION VHF · VOACAP** — tableau HTML simplifié 4 bandes (50/70/144/432 MHz) × 6 créneaux horaires, cellules colorées par pourcentage (rouge→orange→jaune→vert→bleu).

**Effet Radar Sweep** (bouton toggle ON/OFF) — faisceau animé par canvas `requestAnimationFrame`, centré sur le QTH de l'opérateur via projection Leaflet, cercles concentriques + trainée décroissante + point QTH lumineux. État mémorisé en localStorage.

**Légende d'échelle d'activité unifiée** — 6 niveaux (FERMÉ → FAIBLE → CORRECT → OUVERTURE → FORTE → HOT), cohérente avec la heatmap.

**Watchlist Tracking cockpit** — clone du panel Watchlist en colonne 3, affichage direct de toute la watchlist triée par dernier spot sans filtre préalable, sélecteur de purge configurable (15/30/60 min).

**DX Spot Feed amélioré** — calls en orange (lisibilité renforcée), watchlist en jaune, new DXCC en rouge, distance en priorité dans la colonne INFO.

**Scroll de page libéré** — la molette scrolle librement toute la page cockpit (plus de scroll interne piégé par colonne).

**Jauge Opening Strength agrandie** — 132px → 200px.

#### 🛰️ Page Satellites — Fréquences uplink/downlink

- Popup carte enrichi avec les fréquences radio de chaque satellite, source SatNOGS DB (`db.satnogs.org/api/transmitters`), cache serveur 6h, preload au démarrage et côté frontend
- Type de satellite auto-détecté (amateur/météo/station) via reconnaissance de préfixes
- **Correction azimut critique** 🔴 : l'azimut était décalé systématiquement (jusqu'à 180°) — formule SEZ finale corrigée en `atan2(e, -s)`

---

### v10.0 — Moteur prédictif · Sparklines · Alertes push (optionnel)

#### 🔮 Moteur prédictif personnel (`predictor.py`)

Nouvelle brique d'intelligence personnelle : l'application apprend de ton activité et anticipe les ouvertures qui te concernent.

**Brique 1 — Collecte SQLite** (`data/predictor.sqlite`)
- Table `spot_log` : chaque spot reçu est enregistré (call, DXCC, bande, mode, score SPD, horodatage)
- Table `es_events` : chaque spot 6m génère un événement sporadic-E (mois, heure UTC, préfixe de direction)
- Table `sessions` : les sessions opérateur sont tracées via heartbeat depuis le navigateur
- Table `missing_dxcc` : DXCC manquants synchronisés depuis le cache LoTW
- Purge automatique des données > 90 jours

**Brique 2 — Scoring probabiliste**
- Patterns Es saisonniers/horaires : probabilités de base par mois × heure UTC (peak mai-juillet, 07z-18z)
- Boost directionnel : certains paths Es sont historiquement plus fréquents
- Facteur bande : 6m = indépendant du SFI (Es), HF = pondéré par SFI et Kp
- Bonus historique local et croisement DXCC manquants

**Brique 3 — Prédictions affichées dans le COCKPIT**
- Pavé **🔮 PRÉDICTIONS PERSONNALISÉES**, TOP 5 fenêtres les plus probables sur 24h
- Routes : `GET /api/predictions`, `GET /api/predictor/stats`, `POST /api/presence`

#### 📊 Sparklines dans le DX Feed

Canvas 40×14px inline, 6 barres de 10 min couvrant la dernière heure, injection automatique par MutationObserver.

#### 🔔 Alertes push intelligentes (optionnel, `ntfy.sh`)

3 types (watchlist spotté / NEW DXCC / ouverture 6m), anti-spam cooldown 15 min SQLite, filtre présence opérateur. Routes : `GET /api/ntfy/status`, `POST /api/ntfy/test`.

#### 🎨 Design système unifié

Le langage visuel du mode COCKPIT devient le design de toute l'application (glassmorphism, HUD scanlines, palette cyan).

#### 🔧 Pavé Propagation HF corrigé

Bandes corrigées (80m→10m au lieu de VHF/UHF), axe X 24 colonnes 00z→23z, palette rouge→vert, ligne "now", légende inline.

---

### v9.5 — Géolocalisation fine + Heatmap gaussienne + Envoi direct

- Table `CALLSIGN_ZONES` : 100+ zones d'appel précises (USA W0-W9, Canada VE1-7, Japon JA0-9, Russie UA0-9, Australie VK1-7, Allemagne DL1-9, Espagne EA1-8…)
- `_callsign_jitter()` : offset déterministe ±1.5° basé sur MD5 du callsign
- Heatmap gaussienne 6m style radar météo, normalisation relative par le max mesuré, palette bleu→rouge
- Envoi de spot direct au click sur le tableau HF/VHF via `POST /api/spot`
- Purge Watchlist v2 avec parsing automatique des dates de fin d'expédition NG3K

> v9.3 était une version de travail non publiée.

### v9.4 — Intégration WSJT-X + Clustering 6m + corrections

- Réception UDP WSJT-X temps réel (port 2237), parser binaire complet du protocole Qt
- Extraction du locator Maidenhead depuis le message FT8 pour positionnement précis
- Clustering géographique 6m (rayon 400km, 5 niveaux de couleur)
- Compatible Log4OM (WSJT-X → Pi pour décodages + Log4OM local pour QSOs)

### v9.2 — Thème Cockpit unifié

Le thème Cockpit devient le thème unique de toute l'application (suppression du sélecteur light/dark/matrix/softtech).

### v9.0 — NEURAL DX & Mode COCKPIT 6 m

Rebranding en NEURAL DX WATCHER. Sélecteur 3 modes (⚡ CLASSIC / 🧠 SMART / 🎛 COCKPIT 6m). Interface cockpit dense 3 colonnes avec jauge Opening Strength, VOACAP, heatmap E-Layer.

### v8.2 — LoTW persistance + Pavé 6m Magic Band + corrections

Cache LoTW persisté entre redémarrages, mini-carte Magic Band en mode SMART.

### v8.1 — Mode Intelligent amélioré + World relooké

Colonne Rareté (TRÈS RARE/RECHERCHÉ/TRACKING/EXOTIC DX), page World plein écran avec HUD flottant et greyline intégrée.

### v8.0 — Mode Intelligent 🧠

Score composite : Nouveau DXCC (+40), Watchlist (+30), Bande manquante confirmée (+10), SFI favorable (+20), Score SPD natif (+30), Distance >10 000km (+15).

### v7.7 — Responsive · v7.6 — Greyline · v7.5 — Purge Watchlist · v7.4 — Landing page corrigée · v7.3 — Correction analysis.html

### v7.2 — Satellite Tracker

Suivi temps réel (AO-73, AO-91, ISS, RS-44, SO-50, FO-29, PO-101…), calcul local sgp4, passages AOS/TCA/LOS.

### v7.1 — LoTW Opportunités DXCC

Croisement automatique du log LoTW avec les expéditions DX à venir (horizon 21 jours), page Briefing refaite.

### v7.0 — Intégration LoTW & améliorations bandmap

Connexion sécurisée, statistiques DXCC par bande, badges NEW/✓ LoTW, bandmap zoom 100×.

### v6.9 — VOACAP local · v6.5 — Brief vocal IA · v6.4 — Bandmap

### v6.0 — Release stable · v5.6 — World (expérimental) + Watchlist Tracking · v5.2 — META ANALYSE

---

## 👤 Auteur

Développé par **F1SMV – Eric**  
avec l'assistance de Claude (Anthropic)  
au service de la communauté radioamateur.  
Contact : @f1smv sur X
