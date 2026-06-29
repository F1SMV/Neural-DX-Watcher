# ⚡ Neural DX Watcher — v10.3

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
- **prédit** les ouvertures probables selon ton activité et tes DXCC manquants

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
- les signaux de **surge** d'activité

👉 **Objectif : savoir ce qui se passe maintenant.**

---

### 📡 Pavé **WATCHLIST · Tracking**

> *« Je n'étais pas devant l'écran : qu'ai-je raté ? »*

- basé sur la watchlist
- exploite un historique en mémoire
- affiche les derniers spots par indicatif
- ✅ outil de rattrapage pensé pour l'opérateur humain

---

### 2️⃣ Page **Map** — Carte d'observation

Carte classique des spots individuels — chaque point = une station.  
👉 **Objectif : voir où ça se passe.** La page Map est un **outil d'exécution**.

---

### 3️⃣ Page **AI Insight** — Analyse & META ANALYSE différée

Outil d'analyse non temps réel. Accès via `/ai-insight`.  
👉 **Outil de recul**, pas un gadget.

---

### 4️⃣ Page **World** — Forecast & Anomalies

| Page | Nature | Question |
|---|---|---|
| Map | Observation brute | Qui est actif maintenant ? |
| World | Analyse interprétée | Où la propagation est anormalement favorable ? |

- affichage de **zones**, pas de stations
- clustering spatio-temporel, filtrage du bruit

👉 **World décide, Map exécute.**

---

### 5️⃣ Page **Briefing**

Se met à jour toutes les 12 heures, reprenant les infos DX essentielles. Possibilité d'ajouter automatiquement les calls dans la watchlist.

---

### 6️⃣ Page **Satellites**

Suivi temps réel des satellites amateurs (AO-91, RS-44, SO-50, ISS…). Calcul local via sgp4, prochains passages (AOS/TCA/LOS), fréquences uplink/downlink depuis SatNOGS.

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
- Analyse : scripts Python dédiés
- Stockage : mémoire + JSON locaux + **SQLite**

Aucune dépendance cloud.

---

## 🗂️ Historique des versions

### v10.3 — Détection surge 2m · Navigation AI Insight · Corrections

#### 📡 Détection surge étendue au 2m

- Le 2m était **exclu** de la détection de surge (faux positifs redoutés)
- Désormais inclus avec **double seuil** : taux × 2.0 et minimum 8 spots récents
- Les vraies ouvertures Es sur 2m déclenchent l'alerte · l'activité locale ordinaire ne la déclenche pas

#### 🔗 Navigation corrigée

- Tous les liens "AI Insight" pointaient encore vers `/analysis` → corrigés vers `/ai-insight`
- `map-v11.html` supprimé (page de test obsolète, intégrée au cockpit)

---

### v10.2 — Migration TLE format JSON OMM · Favicon · AI Insight · Corrections

#### 🛰️ Migration TLE JSON OMM (CelesTrak)

CelesTrak épuisera les numéros de catalogue à 5 chiffres (limite à 69999) autour du **12 juillet 2026**. Migration préventive vers le format JSON OMM.

**Nouvelle architecture de chargement TLE — 3 couches :**

1. **Sources JSON OMM (priorité)** — CelesTrak GP API :
   - `gp.php?GROUP=amateur&FORMAT=json` → tous les satellites amateurs
   - `gp.php?GROUP=stations&FORMAT=json` → ISS, CSS Tiangong, etc.
   - `NORAD_CAT_ID` entier natif illimité, `TLE_LINE1`/`TLE_LINE2` compatibles sgp4 sans modification
2. **Fallback texte (AMSAT nasa.all)** — complémente le JSON pour les satellites manquants
3. **Log consolidé** — nombre de satellites chargés par source au démarrage

#### ⚡ Favicon

- Icône ⚡ éclair cyan sur fond sombre, SVG inline base64 dans tous les templates
- Aucun fichier supplémentaire requis

#### 🧠 Page renommée : Analysis → AI Insight

- Template renommé `ai_insight.html`, route `/ai-insight`
- Rétrocompatibilité : `/analysis` et `/analysis.html` redirigent automatiquement

#### 🎨 Améliorations page AI Insight

- Variables CSS manquantes corrigées (`--font-sans`, `--font-display`, `--success`)
- Long Distance enrichi : distance (km), bande, mode, heure
- Calls rares **cliquables** → ajout rapide en watchlist
- Erreur META analyse : `confirm()` remplacé par dialog HTML inline, message d'erreur contextuel (plus de fenêtre popup)
- Indicateur de dernière mise à jour + spinner de refresh
- Toggle langue global FR/EN persisté en localStorage
- Chart.js amélioré : tooltips personnalisés, animation `easeOutQuart`, grille subtile

#### 🔧 Corrections diverses

- Navigation **World** : lien AI Insight ajouté, nom de marque corrigé
- Version affichée mise à jour partout en V10.2

---

### v10.1 — Mode COCKPIT redessiné · Radar sweep · Satellites améliorés · Corrections

#### 🎛 Refonte visuelle du mode COCKPIT

**Pavé PROPAGATION VHF · VOACAP** — tableau HTML 4 bandes (50/70/144/432 MHz) × 6 créneaux, cellules colorées par %

**Effet Radar Sweep** (🆕 bouton toggle ON/OFF)
- Faisceau canvas `requestAnimationFrame`, centré sur le QTH de l'opérateur
- Cercles concentriques, trainée décroissante, point QTH lumineux
- État mémorisé en localStorage

**Légende d'échelle d'activité unifiée** (🆕) — 6 niveaux : FERMÉ → HOT

**Watchlist Tracking cockpit** (🆕) — colonne 3, affichage direct sans filtre, purge configurable

**DX Spot Feed** — calls orange, watchlist jaune, new DXCC rouge, distance en priorité

**Scroll de page** — molette libre sur toute la page cockpit

**Jauge Opening Strength** — 132px → 200px

#### 🛰️ Page Satellites

- Fréquences uplink/downlink depuis SatNOGS (cache 6h, préchargement parallèle au démarrage)
- Type satellite inféré automatiquement (amateur/weather/station)
- **Correction azimut** 🔴 : `atan2(-e, s)` → `atan2(e, -s)` — décalage de 180° corrigé

---

### v10.0 — Moteur prédictif · Sparklines · Alertes push (optionnel)

**Moteur prédictif** (`predictor.py`) : collecte SQLite, scoring Es saisonnier, TOP 5 prédictions 24h  
**Sparklines** DX Feed : canvas 40×14px, 6 barres de 10 min  
**Alertes push** (`ntfy.sh`) : watchlist / NEW DXCC / ouverture 6m, anti-spam 15 min  
**Design** : glassmorphism, HUD scanlines, palette cyan

---

### v9.5 — Géolocalisation fine · Heatmap gaussienne · v9.4 — WSJT-X · v9.2 — Thème Cockpit

### v9.0 — Mode COCKPIT 6 m · v8.x — LoTW · Mode Intelligent · v7.x — Satellites · Briefing · Bandmap

### v6.x — Release stable · World · META ANALYSE

---

## 👤 Auteur

Développé par **F1SMV – Eric**  
avec l'assistance de Claude (Anthropic)  
au service de la communauté radioamateur.  
Contact : @f1smv sur X
