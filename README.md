# 📡 Neural DX Watcher — v10.0


**DX Cluster Dashboard & Advanced Radio Analysis Engine**

Application web locale de surveillance DX et d'analyse radio destinée aux radioamateurs exigeants.  
Conçue pour **observer**, **comprendre** et **prendre du recul** — pas pour faire du bruit visuel.

---

## 🧭 Présentation générale

**Neural DX Watcher ** est une application web locale qui :

- se connecte à un ou plusieurs **DX Clusters (Telnet)**
- affiche les **spots en temps réel** (HF / VHF / UHF)
- intègre les **indices solaires** (SFI, A, Kp…)
- conserve une **mémoire exploitable** de l'activité
- propose **plusieurs niveaux de lecture**, du live à l'analyse stratégique
- **prédit** les ouvertures probables selon ton activité et tes DXCC manquants

> L'objectif n'est pas de voir beaucoup,  
> mais de **voir juste**.

---

## 🖥️ Pages principales

### 1️⃣ Page **Index** — Temps réel & suivi opérateur

Page d'observation immédiate.

Elle affiche :
- le flux de spots en direct
- les bandes actives
- les DX recherchés (*wanted*)
- les indices solaires
- les signaux de **surge** d'activité

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

### 2️⃣ Page **Map** — Carte d'observation (micro-lecture)

Carte classique des **spots individuels** :

- chaque point = **une station**
- représentation géographique immédiate
- vision instantanée

👉 **Objectif : voir où ça se passe.**

La page **Map** est un **outil d'exécution**.

---

### 3️⃣ Page **Analyse** — META ANALYSE différée

Outil volontairement **non temps réel**, basé sur l'analyse du log applicatif.

👉 **Outil de recul**, pas un gadget.

---

### 4️⃣ Page **World** — Forecast & Anomalies

La page **World** est **fondamentalement différente** de la page Map.

| Page | Nature | Question |
|---|---|---|
| Map | Observation brute | Qui est actif maintenant ? |
| World | Analyse interprétée | Où la propagation est anormalement favorable ? |

- affichage de **zones**, pas de stations
- clustering spatio-temporel
- filtrage du bruit
- rafraîchissement contrôlé

👉 **World décide, Map exécute.**

### 5️⃣ Page **Briefing**

Se met à jour toutes les 12 heures, reprenant les infos DX essentielles. Possibilité d'ajouter automatiquement les calls dans la watchlist de la page Index. Vous ne raterez aucune expédition : dès qu'un call est spotté, il s'affiche en jaune dans le pavé DX spots.

---

📸 Aperçu

![Apercu du Dashboard](apercu.png)


## 🚀 Installation

```bash
git clone https://github.com/f1smv/spot-watcher-dx.git
cd spot-watcher-dx
chmod +x start.sh
./start.sh
```

L'application sera accessible sur `http://localhost:8000`

---

## ⚙️ Architecture technique

- Backend : Python / Flask
- Frontend : HTML / CSS / JavaScript
- Cluster : Telnet DX Cluster
- Analyse : scripts Python dédiés
- Stockage : mémoire + JSON locaux + **SQLite** (v10.0)

Aucune dépendance cloud.

---

## 🗂️ Historique des versions

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
- Boost directionnel : certains paths Es sont historiquement plus fréquents (EU→EU fort, EU→JA modéré…)
- Facteur bande : 6m = indépendant du SFI (Es), HF = pondéré par SFI et Kp
- Bonus historique local : les événements déjà enregistrés en base renforcent le score des mêmes créneaux
- Croisement DXCC manquants : seules les ouvertures vers des entités encore à faire sont proposées

**Brique 3 — Prédictions affichées dans le COCKPIT**
- Nouveau pavé **🔮 PRÉDICTIONS PERSONNALISÉES** en colonne 1 du mode COCKPIT
- TOP 5 fenêtres les plus probables sur les 24 prochaines heures
- Chaque prédiction : heure UTC, bande, DXCC cible, score en %, barre visuelle colorée, tip explicatif
- Cache 10 min, recalcul automatique à chaque switch vers le mode cockpit
- Exemple : *"Probabilité forte (68%) d'ouverture 6m vers JT1 entre 14h et 17z — JT1 te manque en FT8"*

**Nouvelles routes backend**
- `GET /api/predictions` — prédictions personnalisées (croisées avec LoTW si actif)
- `GET /api/predictor/stats` — stats de collecte (spots loggés, événements Es, sessions)
- `POST /api/presence` — heartbeat opérateur (suspend les alertes push si tu es sur la page)

#### 📊 Sparklines dans le DX Feed

À côté de chaque indicatif dans le **DX Spot Feed** du mode COCKPIT :
- Canvas 40×14 px inline, **6 barres de 10 min** couvrant la dernière heure
- D'un coup d'œil : *"il vient d'arriver"* vs *"il tourne depuis 40 min"*
- Intensité cyan proportionnelle au nombre de spots dans la tranche
- Données issues de `/api/spot_history` — aucune collecte supplémentaire, l'historique RAM existant est exploité
- Injection automatique par MutationObserver : toujours à jour sans recharger la page

#### 🔔 Alertes push intelligentes (optionnel — non activé par défaut)

Infrastructure d'alertes disponible, désactivée tant que `NTFY_URL` n'est pas configuré.

**3 types d'alertes :**
1. **Watchlist spotté** — un call suivi apparaît sur le cluster
2. **NEW DXCC** — une entité manquante en LoTW est active sur une bande à faire
3. **Ouverture 6m** — surge détecté (> N spots / 10 min)

**Anti-spam intégré :**
- Cooldown 15 min par call/type en SQLite
- **Filtre présence** : si tu es sur la page (heartbeat < 45s), aucune alerte n'est envoyée

**Badge PUSH** dans le titre du DX Feed — indique le statut (actif / inactif), cliquable pour voir les détails.

**Configuration ntfy.sh (si souhaité) :**
```bash
# Créer un topic sur ntfy.sh (gratuit, aucun compte requis)
export NTFY_URL="https://ntfy.sh/neuraldx-f1smv-XXXXXX"

# Sur smartphone : installer l'app ntfy.sh, s'abonner au même topic
# Test depuis l'app :
curl -s -X POST http://localhost:8000/api/ntfy/test
```

Self-hosting possible sur le Pi (binaire unique Go, ~20 Mo RAM).

**Nouvelles routes :**
- `GET /api/ntfy/status` — statut, cooldowns, alertes récentes
- `POST /api/ntfy/test` — envoyer une notification de test

#### 🎨 Design système unifié (v9.6 → intégré v10.0)

Le langage visuel du mode COCKPIT est devenu **le design de toute l'application** :
- Fond HUD avec grille 32px et scanlines CRT en couches fixes
- Glassmorphism sur tous les pavés CLASSIC et SMART (`backdrop-filter: blur(18px)`)
- Titres `.panel-header` style ck-title avec pastille lumineuse et bandeau dégradé cyan
- Boutons de mode avec états lumineux distincts (cyan / violet / orange)
- Header : verre dépoli + glow titre, ticker translucide
- Tableaux : en-têtes cyan glow, hover rows
- Scrollbars dégradé cyan→orange
- Correction structurelle : `#header-row2` était rendu hors du header depuis v9.x

#### 🔧 Pavé Propagation HF corrigé

Le pavé **PROPAGATION HF** du mode COCKPIT affichait des données VHF/UHF incorrectes :
- Bandes corrigées : `80m / 40m / 20m / 17m / 15m / 12m / 10m` (au lieu de `50MHz / 70MHz / 144MHz / 432MHz`)
- Axe X : 24 colonnes 00z→23z (au lieu de 6 slots 06z→21z)
- Palette : rouge→vert identique au pavé classique
- Ligne "now" : trait blanc pointillé + triangle ▼
- Légende inline : 0-20 / 20-40 / 40-60 / 60-80 / 80+
- Modèle diurnal : 80m/40m favorisés la nuit, 10m/12m/15m dépendants du SFI

---

### v9.5 — Géolocalisation fine + Heatmap gaussienne + Envoi direct

**Géolocalisation fine des spots (Option A+B)**

- Table `CALLSIGN_ZONES` : 100+ zones d'appel précises (USA W0-W9/K/N par chiffre de zone, Canada VE1-7, Japon JA0-9, Russie UA0-9, Australie VK1-7, Allemagne DL1-9, Espagne EA1-8, France, Italie)
- `_callsign_jitter()` : offset déterministe ±1.5° basé sur MD5 du callsign — même call = même position à chaque redémarrage, deux calls dans la même zone → positions légèrement différentes
- `get_precise_latlon()` : 4 niveaux — préfixe 3ch → 2ch → chiffre de zone US (KF6I → 6 → Californie) → centroïde pays + jitter
- Résout le bug où tous les USA s'affichaient au même point (37.6, -91.87)

**Heatmap gaussienne 6m (Magic Band cockpit)**

- Remplacement des cercles colorés par distance par une **nappe de chaleur continue** type radar météo
- Chaque spot émet une gaussienne de ~600km (rayon adaptatif via projection Leaflet)
- Accumulation dans un buffer Float32, **normalisation relative** par le max mesuré — la zone la plus dense est toujours rouge, quelle que soit la densité absolue
- Correction gamma 0.65 pour étirer les zones moyennes
- Palette `CK6M_PALETTE` : bleu → cyan → vert → jaune → orange → rouge
- Petits points blancs cliquables (popup call/freq/mode/distance) par-dessus la nappe
- Redessine automatiquement au pan/zoom et sur événement `load` Leaflet (correction carte vide au reload)

**Envoi de spot direct au click**

- Click sur n'importe quelle ligne dans le tableau HF/VHF → spot envoyé immédiatement via `POST /api/spot`
- Toast de confirmation en bas à droite (vert ✅ ou rouge ❌), format agrandi

**Fréquences FT8 expéditions DX**

- Ajout de 14090 kHz (20m) et 18095 kHz (17m) comme fréquences FT8
- Liste complète : 3573, 5357, 7074, 10136, 14074, 14090, 18100, 18095, 21074, 24915, 28074

**Purge Watchlist v2**

- Nouveau fichier `data/wl_activity.json` — persiste `{last_spot, end_date, added}` par call
- `_parse_end_date_from_title()` : parse les titres NG3K (`5Z4 · Kenya · → 16 Jun 2026` → `2026-06-16`)
- Endpoint `/api/watchlist/stale` : inclut uniquement les calls expirés depuis X jours, avec `pre_checked`, `reason`, `end_date`
- Modal purge : lignes rouges pré-cochées (expéditions terminées), date de fin en orange, raison en grisé

**Corrections diverses**

- Endpoint mort `/api/cockpit6/heatmap` (404) supprimé du JS
- Déduplication WSJT-X : 120s → 30s, fenêtre 20 → 50 spots
- Extraction callsign FT8 réécrite : gère `CQ DX`, `CQ EU`, locators, modificateurs

> v9.3 était une version de travail non publiée.

### v9.4 — Intégration WSJT-X + Clustering 6m + corrections

**Intégration WSJT-X UDP**

- Réception du flux UDP WSJT-X en temps réel (port 2237)
- Parser binaire complet du protocole Qt : Heartbeat, Status, Decode, QSOLog
- Filtrage : CQ uniquement + stations appelant directement MY_CALL
- Extraction du **locator Maidenhead** depuis le message FT8 (`CQ W6GY DM04` → coordonnées précises)
- Conversion Maidenhead → lat/lon pour positionnement exact sur la carte (précision ±1°)
- Déduplication 30s (2 périodes FT8) sur 50 spots — évite les doublons sans perdre les CQ répétés
- Spots WSJT-X identifiés par `source: WSJTX`, badge orange `WSJT` + SNR dans les tableaux
- Toggle global `📡 WSJT-X ●` dans le header — active/désactive dans tous les tableaux simultanément
- Persisté en localStorage
- Endpoints `/api/wsjtx/status` et `/api/wsjtx/spots`
- Compatible Log4OM : WSJT-X → Pi (2237) pour décodages + Log4OM local (127.0.0.1:2237) pour QSOs

**Clustering géographique 6m — Option C**

- Algorithme de clustering géo rayon 400km sur toutes les cartes 6m
- 5 niveaux de couleur alignés sur la légende carte :
  - 🔵 Bleu (1 spot) → 🔵 Cyan (2) → 🟡 Jaune (3-4) → 🟠 Orange (5-7) → 🔴 Rouge (8+)
- Halo de zone Leaflet proportionnel (150km à 500km)
- Appliqué sur : heat dots cockpit, carte Leaflet cockpit, carte mode SMART

**Corrections diverses**

- Palette VOACAP corrigée : rouge/orange/jaune/vert/cyan/bleu selon probabilité
- Click sur un call dans le tableau HF → pré-remplit le pavé Spot Manuel
- Extraction callsign FT8 réécrite : gère `CQ DX`, `CQ EU`, locators, modificateurs

> v9.3 était une version de travail non publiée.

### v9.2 — Thème Cockpit unifié

**Thème visuel unique pour tous les modes**

- Le thème **Cockpit** (`#050810`, panneaux dégradés sombres, accents cyan) devient le thème par défaut de toute l'application
- Suppression du sélecteur de thème light/dark/matrix/softtech — l'identité visuelle est désormais unique et cohérente
- Les modes ⚡ CLASSIC et 🧠 SMART adoptent l'habillage Cockpit tout en conservant leur layout respectif

**Harmonisation globale**

- Inputs et selects : style terminal (fond quasi-noir, bordure cyan fine, glow au focus)
- Boutons : bordure cyan subtile, hover coloré
- Tables : séparateurs et hover rows en cyan très léger
- Scrollbars : fines (5px), thumb cyan
- Smart panel : bordures et gradients unifiés avec le mode Cockpit

### v9.0 — NEURAL DX & Mode COCKPIT 6 m

**Rebranding**

- L'application devient **NEURAL DX WATCHER** (titre de page et en-tête)

**Nouveau sélecteur de modes (3 modes dans le header)**

- ⚡ **CLASSIC** — affichage classique (ex-mode BASIC)
- 🧠 **SMART** — analyse intelligente / Top Spots scorés (ex-mode SMART)
- 🎛 **COCKPIT 6 m** — nouveau tableau de bord plein écran dédié à la bande 6 m

**Mode COCKPIT 6 m — réécriture complète**

Interface « cockpit radio » dense et sombre (néon cyan/orange), organisée en 3 colonnes. Pavés :

- 📌 **SYNTHÈSE 6 m / 24H** — Spots 24h, DXCC uniques, SFI, K-index
- ☀️ **SOLAR & GEOMAGNETIC DATA** — SFI, A-index, K-index
- 📊 **BAND CONDITIONS · HF** — état des bandes
- ⚡ **MAGIC BAND 6 m · HEATMAP** — carte E-Layer, jauge Opening Strength, liste hotspots
- 📡 **PROPAGATION HF · VOACAP** — prévision bandes HF avec sélecteur de zone
- 🧠 **TOP SPOTS 6 m INTELLIGENTS** — sélection scorée dédiée 6 m
- **DX SPOT FEED · 6 m · 20 MIN** — flux des derniers spots 6 m
- 🎯 **OPPORTUNITÉS DXCC** — croisement LoTW
- 📡 **SPOT MANUEL** — envoi direct au cluster

### v8.2 — LoTW persistance + Pavé 6m Magic Band + corrections

**LoTW — persistance entre redémarrages**

- Cache LoTW sauvegardé dans `data/lotw_cache.json` après chaque synchronisation
- Rechargement automatique au démarrage — plus besoin de re-synchroniser manuellement
- Opportunités DXCC disponibles immédiatement après un redémarrage
- Déduplication corrigée : un même indicatif (avec ou sans suffixe /P /MM) n'apparaît plus en double

**Pavé ⚡ DX 6M · MAGIC BAND** (Mode SMART uniquement)

- Mini-carte Leaflet 320px avec markers colorés selon distance (vert >8000 km, jaune >3000 km)
- Tableau 25 spots max, triés par distance décroissante
- Badge 🔴 OPEN animé quand ≥ 5 spots actifs
- Drag & drop activé

### v8.1 — Mode Intelligent amélioré + World relooké

**Pavé TOP SPOTS — améliorations**

- Drag & drop activé sur le pavé Mode Intelligent
- Nouvelle colonne **Rareté** avec 4 niveaux :
  - 🔴 **TRÈS RARE** — Nouveau DXCC + distance > 10 000 km
  - 🟡 **RECHERCHÉ** — Watchlist ou DXCC manquant + distance > 8 000 km
  - 🔵 **TRACKING** — Call dans la watchlist
  - ⚡ **EXOTIC DX** — Distance > 10 000 km hors watchlist

**Page World entièrement relookée**

- Carte plein écran — plus de sidebar fixe
- HUD flottant semi-transparent avec backdrop-filter
- Greyline intégrée directement dans World

### v8.0 — Mode Intelligent 🧠

**Mode BASIC / SMART switchable depuis le header**

**Pavé "TOP SPOTS · MODE INTELLIGENT"** — 15 meilleurs spots classés par score composite :

- 🔴 **+40 pts** — Nouveau DXCC jamais travaillé (croisement LoTW)
- 🟣 **+30 pts** — Call dans la watchlist
- 🟢 **+10 pts** — DXCC confirmé LoTW, bande manquante
- 🔵 **+20 pts** — Propagation favorable (SFI > 70)
- ⚡ **+30 pts** — Score SPD natif
- 📡 **+15 pts** — Distance > 10 000 km

### v7.7 responsive

- Header, tableaux, cartes, bandmap, modal purge adaptés au mobile

### v7.6 greyline

- Ajout de la greyline dans la page map

### v7.5 purge pavé "watching list"

- Suppression facile des calls d'expéditions DX terminées

### v7.4 landing page corrigée

- Responsive, correction de la page satellite

### v7.3 correction

- Bug page analysis.html

### v7.2 — Satellite Tracker

- Nouvelle page **Satellite Tracker** : suivi temps réel (AO-73, AO-91, ISS, RS-44, SO-50, FO-29, PO-101…)
- Positions calculées localement via **sgp4** depuis les TLE AMSAT
- Prochains passages (24h UTC) : AOS, TCA, LOS, durée, élévation max

### v7.1 — LoTW Opportunités DXCC

- Croisement automatique du log LoTW avec les expéditions DX à venir (horizon 21 jours)
- Résolution automatique des dates depuis le texte du briefing

**Page Briefing entièrement refaite**

- Pavés drag & drop, parser NG3K réécrit, callsigns surlignés en cyan

### v7.0 — Intégration LoTW & améliorations bandmap

- Connexion sécurisée depuis l'interface web
- Statistiques : QSOs totaux, QSLs confirmées, DXCC confirmés par bande
- Badges NEW / ✓ LoTW dans les spots HF et VHF
- Bandmap : zoom 100×, couleurs par mode, légende

### v6.9

- Pavé VOACAP : prédiction HF locale sans dépendance cloud

### v6.5

- Brief vocal IA via API Perplexity (~0.01€/appel)

### v6.4

- Bandmap ajoutée à la page d'accueil

### v6.0 — Release stable

- Finalisation de la page World, clustering stabilisé, UX clarifiée

### v5.6

- Introduction de World (expérimentale)
- Pavé WATCHLIST · Tracking

### v5.2

- Introduction de la META ANALYSE

---

## 👤 Auteur

Développé par **F1SMV – Eric**  
avec l'assistance de Claude (Anthropic)  
au service de la communauté radioamateur.  
Contact : @f1smv sur X
