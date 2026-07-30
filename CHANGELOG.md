# Changelog — Neural DX Watcher

Toutes les versions notables du projet, de la plus récente à la plus ancienne.

---

## v11.3

### Infrastructure & Sécurité
- **Reverse proxy nginx** : accès HTTPS externe via DuckDNS + Let's Encrypt (challenge DNS, aucun port 80/443 requis)
- Port 8443 pour Neural DX Watcher (n'interfère pas avec le NAS sur 443)
- Basic Auth nginx (couche supplémentaire) + token API applicatif (double couche sécurité)
- Flask continue de tourner sur 127.0.0.1:8000 uniquement (inaccessible depuis Internet directement)

### Cartes & Filtrage
- **Filtre bande sur cartes** : quand tu sélectionnes une bande dans le pavé DX SPOTS, la carte n'affiche que celle-ci (pas toutes les bandes) → meilleure lisibilité
- **Clipping latitude MY SIGNAL** : enveloppe grand cercle coupée à 70°N/S (élimine l'effet "toile" au-dessus du Groenland en projection Mercator)

### PSK Reporter & MY SIGNAL
- **TTL cache** : ajusté de 90s → **300s** (5 min = limite officielle NOAA; 90s = 3.3× sur-sollicitation, provoquait un throttling silencieux après quelques semaines)
- **Affichage fraîcheur** : "MàJ PSK il y a Xs · prochaine possible dans Ys" — rend transparent un délai qui semblait "figé"
- **Récalcul age_s dynamique** : même en fallback cache, l'âge des rapports grandit correctement (évite la "carte figée" quand PSK Reporter timeout)
- **Polling frontend** : resserré de 90s → 20s (interroge le cache backend local, pas PSK Reporter directement) → détection plus fluide des rafraîchissements

### Indices solaires
- **K-index enfin visible** : bug parsing NOAA fixé — le code attendait `[ ["time_tag","Kp",...], [...], ... ]` (tableaux de tableaux), mais NOAA envoie `[ {"time_tag":"...","Kp":3.67,...}, ... ]` (objets dict)
- **Fallback A-index** : si Kp NOAA échoue, calcule approx Kp depuis A-index (~A/3) plutôt que "N/A" indéfiniment
- **Logging amélioré** : traçage explicite des échecs de fetch NOAA (format invalide, timeout, erreur HTTP)

### Interface & Bugs
- `briefing.html` : label "Analyse" → "AI Insight" (cohérence avec `ai_insight.html`)
- `briefing.html` : favicon ajouté
- `briefing.html` : **interception de token API corrigée** (cassait silencieusement les POST watchlist depuis cette page)
- Setup ⚙ : panneau complet avec 31 pavés listés à plat (labels FR), persistance backend partagée entre appareils, coupure d'intervalle pour pavés coûteux quand masqués

---

## v11.2

- Ligne rouge d'enveloppe pour le mode **QUI M'ENTEND**
- Correction des erreurs 500 sur **META ANALYSE** (backend renvoie maintenant le vrai `stderr`)
- `tools/log_meta_analyzer.py` réécrit entièrement (fichier était totalement absent)
- `ai_insight.html` : remplacement des `confirm()`/`alert()` natifs par des modales cohérentes
- Spinner de chargement ajouté sur page satellites
- Message d'attente clarifié sur `index.html`

---

## v11.1

- **Sécurité niveau 2** :
  - Token API local (`X-API-Token`), généré et stocké dans `data/api_token.txt` (chmod 600)
  - Intercepteur `fetch()` global côté frontend pour injecter automatiquement le token
- Toggle **"QUI M'ENTEND"** ajouté sur les cartes HF et VHF/UHF

---

## v11.0

- Refonte complète de `predictor.py`
- Nouveau module `dxcc_resolver.py`
- Durcissement sécurité :
  - `debug=False` (débogueur Werkzeug interactif désactivé)
  - Fichiers LoTW déplacés vers `data/` avec permissions `chmod 600`
  - `start.sh` entièrement réécrit

---

## v10.5

- Toggle **Theory vs Reality** sur les prédictions VOACAP
- Panneau **MY SIGNAL** (PSK Reporter) ajouté

---

## v10.4

- Version interne, non publiée

---

## v10.3

- Détection de surge d'activité étendue au 2m
- Corrections de navigation

---

## v10.2

- Migration TLE satellites vers format JSON OMM (CelesTrak GP API)
- Favicon SVG ajouté
- `analysis.html` renommé en `ai_insight.html`

---

## v10.1

- Mode **COCKPIT** : tableau de bord immersif
- Radar sweep animé sur canvas (carte 6m)
- Page satellites avec calcul azimut/élévation

---

*Neural DX Watcher — F1SMV*
