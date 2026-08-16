# ⚡ Neural DX Watcher — v12.1

**DX Cluster Dashboard & Advanced Radio Analysis Engine**

Application web locale de surveillance DX et d'analyse radio destinée aux radioamateurs exigeants.  
Conçue pour **observer**, **comprendre** et **prendre du recul** — pas pour faire du bruit visuel.

---

## ⚙️ Configuration initiale — Définis ton indicatif

Avant de lancer l'application, tu peux **soit** :

### Option 1 : Éditer webapp.py (une seule fois)

Édite `webapp.py` et modifie cette ligne (ligne ~89) :

```python
MY_CALL = "F1SMV"  # ← Remplace par TON indicatif
```

Puis relance Flask. La configuration est maintenant **sauvegardée en local** dans `data/config.json` — elle persiste à chaque redémarrage et mise à jour.

### Option 2 : Éditer data/config.json directement

Une fois lancée, l'app crée automatiquement `data/config.json`. Tu peux l'éditer directement :

```json
{
  "my_call": "F1SMV",
  "user_qra": "JN23",
  "timestamp_utc": "2026-01-01T00:00:00"
}
```

Sauvegarde et relance Flask.

---

## 🧭 Présentation générale

**Neural DX Watcher** est une application web locale qui :

- se connecte à un ou plusieurs **DX Clusters (Telnet)**
- affiche les **spots en temps réel** (HF / VHF / UHF)
- intègre les **indices solaires** (SFI, A, Kp…)
- conserve une **mémoire exploitable** de l'activité
- propose **plusieurs niveaux de lecture**, du live à l'analyse stratégique
- **prédit** les ouvertures probables selon ton activité et tes DXCC manquants
- inclut un **module Météo Radio** complet (propagation, foudre, WSPR, balises)
- accessible via **HTTPS sécurisé** (reverse proxy + Let's Encrypt) pour un usage distant

> L'objectif n'est pas de voir beaucoup,  
> mais de **voir juste**.

---

## 🖥️ Pages principales

### 1️⃣ Page **Index** — Temps réel & suivi opérateur

Page d'observation immédiate. Elle affiche :
- le flux de spots en direct
- les bandes actives
- les DX recherchés (*wanted*)
- les indices solaires (SFI, A-index, K-index)
- les signaux de **surge** d'activité (HF, 6m et 2m)

### 📡 Pavé **WATCHLIST · Tracking**

> *« Je n'étais pas devant l'écran : qu'ai-je raté ? »*

- basé sur la watchlist
- exploite un historique en mémoire
- affiche les derniers spots par indicatif

### 📶 Pavé **MY SIGNAL** — Self-monitoring PSK Reporter

> *« Qui m'entend, où, avec quel SNR ? »* — sans jamais quitter l'application.

- Source : API PSK Reporter (JSONP), cache 5 min (limite serveur officielle)
- Toutes bandes HF/VHF/UHF, tous modes digitaux (FT8/FT4/WSPR/JT65/JS8/MSK144)
- Indicatif receveur, mode, fréquence, distance, âge du rapport, SNR coloré

---

### 2️⃣ Page **Map** — Carte d'observation

Carte classique des **spots individuels** :
- chaque point = **une station**
- **filtre par bande** : n'affiche que la bande sélectionnée
- mode **"QUI M'ENTEND"** : stations qui te reçoivent avec enveloppe grand cercle

---

### 3️⃣ Page **AI Insight** — Analyse différée

Outil volontairement **non temps réel**, basé sur l'analyse du log applicatif.

---

### 4️⃣ Page **World** — Forecast & Anomalies

| Page  | Nature              | Question                                        |
| ----- | ------------------- | ----------------------------------------------- |
| Map   | Observation brute   | Qui est actif maintenant ?                      |
| World | Analyse interprétée | Où la propagation est anormalement favorable ?  |

---

### 5️⃣ Page **Briefing**

Mise à jour automatique toutes les 12 heures. Intégration directe des calls dans la watchlist.

---

### 6️⃣ Page **Satellites**

Suivi temps réel des satellites amateurs. Calcul local via sgp4, prochains passages AOS/TCA/LOS, fréquences uplink/downlink depuis SatNOGS, TLE au format JSON OMM.

---

### 7️⃣ Page **⛈️ Météo Radio** *(v12.0–v12.1)*

Module complet de corrélation météo / propagation. Voir section dédiée ci-dessous.

---

## 🌦️ Module Météo Radio — `/weather`

### Objectif

Répondre à : *« Les conditions météo expliquent-elles ce que j'observe sur les bandes ? »*

### Pavés disponibles

**Synthèse globale** — Jauge HF/VHF heuristique (cadran S-mètre analogique). Affiche `—` si une donnée manque, jamais un chiffre inventé. Indice heuristique, pas une mesure physique calibrée.

**Activité électrique** — Impacts de foudre Blitzortung dans un rayon de 300 km, carte Leaflet centrée sur le QTH, marqueurs dynamiques par âge (rouge pulsant < 5 min, orange < 30 min, gris > 30 min). Abonnement MQTT à 9 cellules geohash (grille 3×3 autour du QTH) pour ne rater aucun impact des cellules voisines.

**Conditions actuelles** — Deux onglets :
- *HF* : température (rouge ≥ 30°C, orange ≥ 25°C), pression (rouge < 1000 hPa), tendance barométrique sur 2h (↓ chute rapide = risque de dégradation), humidité, vent, précipitations
- *VHF/UHF* : indice tropo/ducting (heuristique inversion surface/850hPa + humidité + CAPE), vent à 300hPa, CAPE, confirmation WSPR 2m dans 300 km

**Bruit / QRN** — Corrélation bruit/foudre avec vocabulaire radioamateur (QRN, équivalence points S). Jauge 4 niveaux : Calme / Élevé / Perturbé / Orageux. **Source prioritaire : spots WSPR captés par des stations proches du QTH** (wspr.live, 24/7, sans dépendance à WSJT-X). Repli automatique sur SNR WSJT-X si zone pauvre en balises. WSPR HF et VHF séparés (dynamiques différentes).

**VOACAP Rapide** — Prédiction MUF/LUF pour un trajet précis (sélecteur de zone : Europe, Amériques, Asie, Océanie, Afrique). Mini-barres de fiabilité par bande HF colorées. Note explicite : cette prédiction concerne un trajet unique et peut légitimement différer de l'activité globale observée.

**Activité par bande (24h)** — Comptage réel depuis le flux cluster, HF et VHF séparés, barres colorées par bande.

**Balises VHF/UHF/SHF reçues** — Balises spotées par des stations à moins de 300 km du QTH sur les 3 dernières heures, issues du flux DX cluster. Mise à jour automatique mensuelle de la liste de référence depuis [dl0tud.tu-dresden.de/beacons](https://dl0tud.tu-dresden.de/beacons) (DJ5CW, Fabian Kurz, TU Dresden). Les balises connues sont marquées ★. En cas d'échec de la MAJ, le fichier local est conservé et un message d'avertissement est affiché.

### Sources de données

| Source | Usage | Coût |
|--------|-------|------|
| [Open-Meteo](https://open-meteo.com) | Conditions locales (temp, pression, CAPE, vent 300hPa…) | Gratuit, sans clé |
| Blitzortung MQTT | Foudre temps réel | Gratuit, communautaire |
| [wspr.live](https://wspr.live) | Activité WSPR HF/VHF (ClickHouse SQL) | Gratuit, sans clé |
| VOACAP Online | Prédiction de propagation HF | Gratuit |
| dl0tud.tu-dresden.de | Liste de référence balises VHF/UHF/SHF | Gratuit |

### Dépendance supplémentaire

```bash
pip install paho-mqtt --break-system-packages
```

Sans `paho-mqtt`, l'application démarre normalement — le module foudre se désactive proprement (log d'avertissement).

### Points d'honnêteté importants

- L'indice tropo/ducting est une **heuristique simplifiée** (pas un modèle physique complet)
- La jauge Synthèse est un **repère visuel**, pas une mesure calibrée
- Si 0 spot WSPR et WSJT-X non connecté → affiche `—`, jamais un chiffre inventé
- Si 0 impact de foudre → **peut signifier une zone sans orage ou un broker MQTT temporairement indisponible** (Blitzortung est un service communautaire non-officiel)
- Si 0 balise reçue dans le pavé Balises → **pas d'opérateur proche ayant spotté une balise, ne signifie pas absence d'ouverture**

---

## 🚀 Installation

```bash
git clone https://github.com/F1SMV/Neural-DX-Watcher.git
cd Neural-DX-Watcher
chmod +x start.sh
./start.sh
```

L'application sera accessible sur `http://localhost:8000`

> 💡 Un **Raspberry Pi** est recommandé pour la faible consommation électrique.

---

## 🔐 Installation HTTPS sécurisée (accès distant)

### 1. Obtenir un domaine DDNS
Va sur [duckdns.org](https://www.duckdns.org), crée un sous-domaine gratuit, récupère ton token.

### 2. Installer acme.sh
```bash
curl https://get.acme.sh | sh -s email=ton@email.com
source ~/.bashrc
```

### 3. Générer un certificat Let's Encrypt (challenge DNS)
```bash
export DuckDNS_Token="TON_TOKEN"
~/.acme.sh/acme.sh --issue --dns dns_duckdns -d f1smv-dxwatcher.duckdns.org
```

### 4. Configurer nginx (reverse proxy)
```bash
sudo apt install nginx apache2-utils
sudo mkdir -p /etc/nginx/ssl
~/.acme.sh/acme.sh --install-cert -d f1smv-dxwatcher.duckdns.org \
  --key-file       /etc/nginx/ssl/dxwatcher.key \
  --fullchain-file /etc/nginx/ssl/dxwatcher.crt \
  --reloadcmd      "sudo systemctl reload nginx"

sudo htpasswd -c /etc/nginx/.htpasswd f1smv
```

Forward du port externe **8443** vers `192.168.1.81:8443` (TCP).  
**Accès distant :** `https://f1smv-dxwatcher.duckdns.org:8443`

---

## ⚙️ Architecture technique

- Backend : Python / Flask
- Frontend : HTML / CSS / JavaScript (SortableJS, Leaflet, IBM Plex Mono, Space Grotesk)
- Cluster : Telnet DX Cluster
- Analyse : `predictor.py`, `dxcc_resolver.py`
- Stockage : mémoire + JSON locaux + SQLite
- Sécurité : token API local + reverse proxy nginx
- MQTT : paho-mqtt (foudre Blitzortung)

Aucune dépendance cloud.

---

## 🗂️ Historique des versions

### v12.1 — Module Météo : corrections critiques et balises VHF/UHF/SHF

#### 🌩️ Fix critique : Topic MQTT Blitzortung (2026-08-14)

Le broker Blitzortung a changé son format de topic MQTT en production — les cellules geohash sont maintenant séparées par des slashes (`blitzortung/1.1/s/p/e/#`) au lieu d'être concaténées (`blitzortung/1.1/spe/#`). Le broker acceptait la connexion et renvoyait CONNACK=0 mais ne publiait **rien** sur les anciens topics — illusion de fonctionnement, zéro donnée reçue. Fix : `"/".join(gh)` dans `_lightning_on_connect()`.

#### 🌩️ Fix géohash voisins (cellules adjacentes)

Une cellule geohash de précision 3 couvre ~156×156 km. S'abonner à une seule cellule laissait passer tout impact tombant dans une cellule voisine, même à 60 km du QTH. Fix : abonnement à une grille 3×3 (QTH + 8 cellules voisines, 9 topics MQTT au total).

#### 🛰️ Pavé Balises VHF/UHF/SHF

Nouveau pavé dans la page Météo affichant les balises **réellement spotées** par des stations à moins de 300 km du QTH :

- **Données temps réel** : issues du flux DX cluster déjà connecté. Fix associé : `spot_history` hardcodait `"de": None` — capture maintenant le callsign du spotter (`de_call`) et sa distance au QTH (`de_dist_km`) depuis la ligne cluster `DX de <SPOTTER>:`
- **Liste de référence** : mise à jour automatique mensuelle depuis [dl0tud.tu-dresden.de/beacons](https://dl0tud.tu-dresden.de/beacons) (CSV de DJ5CW / Fabian Kurz, TU Dresden). Parsing `;`-séparé, déduplication par call, filtre QRT. En cas d'échec, le fichier local est conservé et un message d'erreur s'affiche dans l'interface
- Les balises connues (dans la liste de référence) sont marquées ★ dans l'affichage

#### 🧭 Fix `spot_history` spotter

La colonne `"de"` de `spot_history` était hardcodée à `None` depuis l'origine, alors que le callsign du spotter est disponible dans la ligne brute du cluster. Fix complet : extraction de `de_call` et calcul de `de_dist_km` (distance spotter ↔ QTH). Améliore non seulement le pavé Balises mais toute analyse future nécessitant la géolocalisation du spotter.

#### 🎨 Refonte visuelle weather.html

Direction "Instrument Panel" : fond graphite + bicolore ambre/teal (au lieu du cyan unique), polices Space Grotesk + IBM Plex Mono, panneaux façon bezel d'instrument (ligne de lumière haute, rivets). Jauge Synthèse Globale transformée en cadran S-mètre analogique (arc 180°, zones colorées, aiguille animée).

#### 🔗 Navigation

Lien `⛈️ Météo` ajouté dans les pages `ai_insight.html`, `briefing.html`, `map.html`, `world.html`, `satellites.html`. Au passage, correction du lien `/briefing.html` → `/briefing` dans `map.html` et `world.html`.

#### 🔢 Fix version index.html

Un second endroit hardcodé `V11.3` dans le header visible de `index.html` (différent du `<title>` déjà corrigé en v12.0) — corrigé pour suivre `{{ version }}`.

---

### v12.0 — Module Météo Phase 1, configuration persistante, WSPR

- **Module Météo** (page `/weather`) : conditions locales Open-Meteo, foudre Blitzortung MQTT, corrélation bruit/QRN WSPR, VOACAP Rapide, activité par bande 24h
- **WSPR source prioritaire** : spots captés par des stations proches du QTH via wspr.live (24/7, sans WSJT-X). HF et VHF séparés. Repli automatique sur SNR WSJT-X
- **Configuration persistante** : MY_CALL et user_qra dans `data/config.json`
- **Fix titre** : `<title>` hardcodé en `v11.3` corrigé

### v11.3 — HTTPS · K-index · PSK Reporter · Filtres bande

- Reverse proxy nginx + DuckDNS + Let's Encrypt (port 8443)
- Fix parsing K-index NOAA (format dict vs tableaux)
- Cache PSK Reporter 300s (limite officielle)
- Filtre par bande sur les cartes Map/World
- Token API local `X-API-Token`

### v11.0–v11.2 — Sécurité, corrections critiques

- Refonte `predictor.py` et `dxcc_resolver.py`
- Token API local, reverse proxy nginx
- Fix META ANALYSE (script manquant)
- Fix AI Insight (popups natifs)
- Indicateur de chargement Satellites

### v10.0–v10.5 — Versions antérieures

Consulter l'historique complet : 👉 https://github.com/F1SMV/Neural-DX-Watcher/commits/main

---

## 👤 Auteur

Développé par **F1SMV – Eric**  
avec l'assistance de Claude (Anthropic)  
au service de la communauté radioamateur.  
Contact : @f1smv sur X
