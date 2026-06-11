# 📡 Radio Spot Watcher DX — v9.5

> Désormais badgée **NEURAL DX WATCHER v9.5** dans l'interface.

**DX Cluster Dashboard & Advanced Radio Analysis Engine**

Application web locale de surveillance DX et d'analyse radio destinée aux radioamateurs exigeants.  
Conçue pour **observer**, **comprendre** et **prendre du recul** — pas pour faire du bruit visuel.

---

## 🧭 Présentation générale

**Radio Spot Watcher DX** est une application web locale qui :

- se connecte à un ou plusieurs **DX Clusters (Telnet)**
- affiche les **spots en temps réel** (HF / VHF / UHF)
- intègre les **indices solaires** (SFI, A, Kp…)
- conserve une **mémoire exploitable** de l'activité
- propose **plusieurs niveaux de lecture**, du live à l'analyse stratégique

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
- Stockage : mémoire + JSON locaux

Aucune dépendance cloud.

---

### 🗂️ Historique des versions

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

- Ajout de 14090 kHz (20m) et 18095 kHz (17m) comme fréquences FT8 — maintenant détectées correctement au lieu de SSB
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

**Purge Watchlist corrigée**

- Nouveau fichier `data/wl_activity.json` — persiste la date du dernier spot par call entre redémarrages
- Sauvegarde automatique toutes les 30 minutes
- Les boutons 7j/14j/30j/60j filtrent maintenant correctement les calls vraiment inactifs
- Seuls les calls inactifs depuis X jours apparaissent cochés (logique inversée corrigée)

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

- L'application devient **NEURAL DX WATCHER v9.5** (titre de page et en-tête)

**Nouveau sélecteur de modes (3 modes dans le header)**

Le curseur 🧠 est remplacé par trois boutons exclusifs :

- ⚡ **CLASSIC** — affichage classique (ex-mode BASIC)
- 🧠 **SMART** — analyse intelligente / Top Spots scorés (ex-mode SMART)
- 🎛 **COCKPIT 6 m** — nouveau tableau de bord plein écran dédié à la bande 6 m

Le mode actif est persisté en localStorage.

**Mode COCKPIT 6 m — réécriture complète**

Interface « cockpit radio » dense et sombre (néon cyan/orange), organisée en 3 colonnes, masquant le dashboard classique. Pavés :

- 📌 **SYNTHÈSE 6 m / 24H** — Spots 24h, DXCC uniques, SFI, K-index
- ☀️ **SOLAR & GEOMAGNETIC DATA** — SFI, A-index, K-index
- 📊 **BAND CONDITIONS · HF** — état des bandes
- ⚡ **MAGIC BAND 6 m · HEATMAP ACTIVITÉ DX** — pavé « broadcast » plein cadre :
  - carte monde **E-Layer Hotspots** (Leaflet) avec scan animé et légende HIGH/LOW
  - jauge circulaire **Opening Strength** (CLOSED → OPEN, 0–100 %)
  - liste **E-Layer Hotspots** par zone (Europe, East Coast NA, Japan, Australia)
  - badge 🔴 **OPEN** animé en cas d'ouverture
- 📡 **PROPAGATION HF · VOACAP** — prévision avec sélecteur de zone (EU / NA / AS / OC)
- 🧠 **TOP SPOTS 6 m INTELLIGENTS** — sélection scorée dédiée 6 m
- **DX SPOT FEED · 6 m · 20 MIN** — flux des derniers spots 6 m
- 🎯 **OPPORTUNITÉS DXCC** — croisement LoTW
- 📡 **SPOT MANUEL** — envoi direct au cluster

**Divers**

- Détection 6 m affinée et harmonisation visuelle avec le reste de l'application
- Patches de mise en page cockpit (responsive ≤ 1250 px, lisibilité VOACAP)

### v8.2 — LoTW persistance + Pavé 6m Magic Band + corrections

**LoTW — persistance entre redémarrages**

- Cache LoTW sauvegardé dans `data/lotw_cache.json` après chaque synchronisation
- Rechargement automatique au démarrage — plus besoin de re-synchroniser manuellement
- Opportunités DXCC disponibles immédiatement après un redémarrage
- Déduplication corrigée : un même indicatif (avec ou sans suffixe /P /MM) n'apparaît plus en double

**Pavé ⚡ DX 6M · MAGIC BAND** (Mode SMART uniquement)

- Pavé dédié à la bande 6m, visible uniquement en mode intelligent
- Mini-carte Leaflet 320px avec markers colorés selon distance (vert >8000 km, jaune >3000 km)
- Tableau 25 spots max, triés par distance décroissante
- Badge 🔴 OPEN animé quand ≥ 5 spots actifs (détection d'ouverture automatique)
- Indicateur watchlist et beacon sur chaque spot
- Drag & drop activé

**Détection modes 6m améliorée**

- 50.313 MHz → FT8 (au lieu de SSB)
- 50.318 MHz → FT4 (au lieu de SSB)

**Corrections diverses**

- Alignement du pavé Opportunités DXCC avec grille CSS 4 colonnes
- Bandes manquantes affichées sur une ligne dédiée (↳ manque: ...)
- Police et couleurs du tableau 6m harmonisées avec le pavé DX WANTED

### v8.1 — Mode Intelligent amélioré + World relooké

**Pavé TOP SPOTS — améliorations**

- Drag & drop activé sur le pavé Mode Intelligent
- Légende des badges bilingue (FR/EN) affichée sous le titre du pavé
- Nouvelle colonne **Rareté** avec 4 niveaux :
  - 🔴 **TRÈS RARE** — Nouveau DXCC + distance > 10 000 km
  - 🟡 **RECHERCHÉ** — Watchlist ou DXCC manquant + distance > 8 000 km
  - 🔵 **TRACKING** — Call dans la watchlist
  - ⚡ **EXOTIC DX** — Distance > 10 000 km hors watchlist (badge orange animé)

**Page World entièrement relookée**

- Carte plein écran — plus de sidebar fixe
- HUD flottant semi-transparent avec backdrop-filter
- Stats temps réel : zones totales / confirmées / suspectes
- Greyline intégrée directement dans World
- Tooltips sur les cercles de propagation (bande, spots, heure UTC)
- Topbar cohérente avec le reste de l'application
- Section "Comment lire" rétractable

### v8.0 — Mode Intelligent 🧠

**Mode BASIC / SMART switchable depuis le header**

- Curseur 🧠 dans le header — bascule entre mode BASIC (affichage classique) et mode SMART (analyse intelligente)
- Nouveau thème visuel dédié : fond `#070B1A`, surfaces `#10172A`, accents cyan `#22D3EE` et violet `#8B5CF6`
- État persisté en localStorage — le mode est mémorisé entre les sessions

**Pavé "TOP SPOTS · MODE INTELLIGENT"**

En mode SMART, le tableau HF est remplacé par une sélection des **15 meilleurs spots** classés par score composite :

- 🔴 **+40 pts** — Nouveau DXCC jamais travaillé (croisement LoTW)
- 🟣 **+30 pts** — Call dans la watchlist
- 🟢 **+10 pts** — DXCC confirmé LoTW, bande manquante
- 🔵 **+20 pts** — Propagation favorable (SFI > 70)
- ⚡ **+30 pts** — Score SPD natif (fiabilité du spot)
- 📡 **+15 pts** — Distance > 10 000 km (DX lointain)

Chaque spot affiche : indicatif, badges colorés, fréquence / bande / mode / heure / distance, barre de score visuelle.

### v7.7 responsive

- v7.7 — améliorations mobiles :

 -Header : titre réduit à 0.82em, indicateurs plus compacts, flex-wrap sur tout
 -Nav links : boutons plus petits, sans margin inutile
 -Voice controls : masqués par défaut sur mobile, bouton 🔊 Voice ▾ pour les afficher/masquer
 -Tableaux spots : colonnes SPD et km masquées sur mobile (gain de place)
 -Bandmap : canvas réduit à 80px de hauteur
 -Cartes HF/VHF : hauteur 180px
 -Dashboard grid : 2 colonnes au lieu de auto-fill
 -Purge modal : 96vw sur mobile
 -Passages satellites : timeline réduite à 90px

### v7.6 greyline 

- ajout de la greyline dans la page map

### v7.5 purge pavé "watching list"

- vous allez pouvoir enlever facilement les calls des expeditions dx rajoutées dans le pavé 

### v7.4 landing page est corrigée

- devient responsive, correction de la page satellite, plus fonctionnelle

### v7.3 - correction 

-  bug page analysis.html

### v7.2 — Satellite Tracker

- Nouvelle page **Satellite Tracker** : suivi temps réel de satellites amateur (AO-73, AO-91, ISS, RS-44, SO-50, FO-29, PO-101…)
- Positions calculées localement via **sgp4** depuis les TLE AMSAT
- Carte **Leaflet** avec footprint de couverture par satellite
- Tableau élévation / azimut / altitude en temps réel
- Pavé **Prochains passages** (24h UTC) : AOS, TCA, LOS, durée, élévation max
- Sélection multi-satellite indépendante pour les passages
- Mise à jour manuelle des keps depuis CelesTrak
- Gestion du catalogue AMSAT : ajout/suppression de satellites suivis

### v7.1

**LoTW — Opportunités DXCC**

- Croisement automatique du log LoTW avec les expéditions DX à venir (horizon 21 jours)
- Section **🎯 OPPORTUNITÉS DXCC — 21 JOURS** dans le pavé LoTW, classée par priorité :
  - 🔴 NOUVEAU DXCC — pays jamais travaillé
  - 🟡 NON CONFIRMÉ — travaillé mais pas de QSL LoTW
  - 🔵 BANDE MANQUANTE — confirmé mais des bandes restent à faire
- Compte à rebours J-X avant la fin de chaque expédition
- Résolution automatique des dates depuis le texte du briefing

**Page Briefing entièrement refaite**

- Un seul rendu unifié pour toutes les sources (fini les trois sections redondantes)
- Pavés **drag & drop** : réorganisables librement, ordre mémorisé en localStorage
- Parser NG3K réécrit pour le format texte structuré — filtre automatique des expéditions terminées
- Titre structuré : `Callsign · DXCC · → date de fin`
- Callsigns surlignés en cyan dans tous les résumés
- Horodatage relatif (il y a 2h, il y a 3j…)
- Correction du warning `datetime.utcnow()` Python 3.12

### v7.0 — Intégration LoTW & améliorations bandmap

**Intégration LoTW (Logbook of the World)**

- Connexion sécurisée depuis l'interface web — identifiants jamais stockés sur le disque
- Import complet de votre log : tous les QSOs uploadés + QSLs confirmées
- Résolution DXCC via `cty.dat` (pas de dépendance au champ ADIF optionnel)
- Statistiques : QSOs totaux, QSLs confirmées, DXCC confirmés par bande (barres visuelles)
- **Dans les spots HF et VHF** : fond rouge + badge NEW = DXCC jamais travaillé / fond vert + ✓ = DXCC déjà confirmé
- **Bouton ★ NEW DXCC** dans les pavés HF et VHF pour filtrer uniquement les nouveaux DXCC
- **Dans la watchlist** : badge NEW DXCC ou ✓ LoTW sur chaque call
- Spinner de chargement pendant la synchronisation (30–60s pour un gros log)

**Bandmap**

- Zoom porté à 100× pour les bandes chargées (ex. 20m)
- Couleur des étiquettes par mode : CW (vert), SSB (bleu), FT8 (violet), FT4 (rose), FT2 (mauve), RTTY (orange), PSK31 (jaune), JT65 (cyan)
- Légende des modes affichée dans les contrôles
- Axe des fréquences : uniquement les vraies limites de bandes radioamateur
- Pan à la souris (clic + glisser) même à zoom 1×
- Persistance de tous les réglages via localStorage

### v6.9

- Pavé VOACAP : prédiction de propagation HF locale (sans dépendance cloud)
- Endpoint `/api/voacap?zone=EU` — calcul MUF/LUF/REL depuis SFI et Kp
- Zones : EU / NA / SA / AS / OC / AF
- Grille colorée bandes × heures UTC style VOACAP
- Zone préférée sauvegardée en localStorage

### v6.8

- Palette de couleurs pour le fond de la bandmap (8 thèmes, persisté)
- Zoom jusqu'à 100× sur la bandmap
- Couleur des pins selon le mode spotté

### v6.7

- Vérification des mises à jour GitHub toutes les 24h (anti rate-limiting)
- Bouton WL pour n'afficher que les stations de la watchlist dans la bandmap
- Filtres HF / VHF 2m / UHF 70cm / QO-100 dans la bandmap
- Correction bug affichage page Analyse

### v6.6

- Bandmap : curseurs zoom et filtre densité SPD
- Recentrage automatique sur le call sélectionné

### v6.5

- Remplacement de `telnetlib` par `telnetlib3` (suggestion F5UGQ)
- Brief vocal IA via bouton dans le pavé Solar Indices (API Perplexity, ~0.01€/appel)

### v6.4

- Ajout de la bandmap sur la page d'accueil, sélection par bande et mode

### v6.3

- Tri par fréquences dans les pavés DX HF et VHF
- Bandeau de notification de mise à jour

### v6.2

- Ajout optionnel des calls dans la watchlist
- Support du mode FT2

### v6.1

- Nouvelle page Briefing DXpéditions
- Modification des cartes de la page Index

### v6.0 — Release stable

- Finalisation de la page World
- Séparation claire Map / World
- Clustering stabilisé
- Rafraîchissement automatique
- UX clarifiée
- Sauvegarde état utilisateur

> Passage de v5.7 à v6.0 dû à plusieurs versions d'essai non publiées.

### v5.7 — Versions de travail

- Prototypes World
- Ajustements de scoring
- Corrections structurelles

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
