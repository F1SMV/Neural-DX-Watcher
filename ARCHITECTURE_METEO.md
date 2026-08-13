# Neural DX Watcher — Module Météo
## Document d'architecture technique

**Statut :** Proposition — pas encore implémenté
**Auteur :** Claude (Anthropic), pour F1SMV
**Basé sur :** `Neural_DX_Watcher_Module_Meteo.md` (spec fonctionnelle initiale)

---

## 1. Principe directeur

Le module ne cherche pas à être une app météo. Il cherche à répondre à
une seule question opérationnelle :

> *Ce que je vois (ou ne vois pas) sur les bandes s'explique-t-il par
> ce qui se passe dehors ?*

Conséquence architecturale : **on ne stocke pas de météo pour la
météo**. Chaque donnée collectée doit pouvoir être mise en regard d'une
donnée radio existante (spots, bruit, WSPR). Sinon elle n'a rien à
faire dans Neural DX Watcher — un vrai site météo fait déjà mieux.

Deuxième principe : **honnêteté des corrélations**. HF est piloté par
l'ionosphère (donc par l'activité solaire, déjà traité par
`predictor.py`/`solar_worker`). La météo troposphérique influence
surtout VHF/UHF/SHF et le bruit électrique (foudre). Le module doit
présenter des **observations synchronisées dans le temps**, pas des
liens de causalité affirmés qu'on ne peut pas prouver avec les données
dont on dispose.

---

## 2. Découpage en 3 phases

Ne pas tout construire d'un coup. Chaque phase est livrable et utile
seule.

| Phase | Contenu | Effort | Valeur radio |
|-------|---------|--------|---------------|
| **1 — MVP** | Conditions locales + Foudre + encart corrélation bruit/orage | Faible-Moyen | ⭐⭐⭐⭐⭐ |
| **2 — Carte** | Superposition radar pluie sur la carte Leaflet existante | Moyen | ⭐⭐⭐ |
| **3 — Intelligence** | Synthèse IA + historique long terme + corrélations saisonnières | Moyen-Élevé | ⭐⭐⭐⭐ |

Ce document couvre l'architecture complète (les 3 phases), mais
l'implémentation doit suivre cet ordre.

---

## 3. Sources de données retenues

### 3.1 Conditions locales — **Open-Meteo**

- Endpoint : `https://api.open-meteo.com/v1/forecast`
- Gratuit, **sans clé API**, sans limite stricte pour un usage perso
- Paramètres : `temperature_2m, pressure_msl, relative_humidity_2m, wind_speed_10m, wind_direction_10m, precipitation`
- Fréquence de poll recommandée : **10 min** (les conditions locales
  changent lentement — pas besoin de plus)
- Lat/lon : réutiliser `user_lat` / `user_lon` déjà calculés depuis le
  QRA (`qra_to_lat_lon()`), donc **zéro configuration supplémentaire**
  pour l'utilisateur

### 3.2 Foudre — **Blitzortung.org**

- Réseau communautaire, flux temps réel via WebSocket
- Existe un endpoint HTTP de secours moins temps réel (`blitzortung.org`
  ne documente pas d'API publique stable — prévoir un fallback
  dégradé : si le flux échoue, afficher "Foudre : indisponible" plutôt
  que planter le panneau)
- Données par impact : lat, lon, timestamp, (pas d'intensité fiable
  côté gratuit — ne pas en promettre à l'utilisateur)
- Calcul dérivé côté backend : distance à `user_lat/user_lon`
  (réutiliser `geo_distance_km()` existant), direction (bearing)
- **Point de vigilance réseau** : Blitzortung n'est pas dans
  `network_configuration` actuel (domaines autorisés pour bash_tool) —
  à ajouter si le dev se fait dans le container ; sur le Pi de
  production ce n'est pas un problème (accès réseau normal)

### 3.3 Radar précipitations — **RainViewer** *(Phase 2 uniquement)*

- API de tuiles gratuite : `https://api.rainviewer.com/public/weather-maps.json`
- Retourne une liste de tuiles PNG horodatées (radar passé + prévision
  courte) à superposer sur Leaflet comme un layer `TileLayer` classique
- **Ne pas télécharger/stocker les tuiles côté Flask** : le frontend
  charge directement les tuiles RainViewer dans le navigateur (comme un
  layer Leaflet normal). Le backend se contente de relayer l'URL de la
  frame courante. Ça évite de transformer le Pi en proxy d'images.

### 3.4 WSPR / Balises / DX Cluster

**Déjà disponibles** dans l'application (spot_history, wsjtx_worker,
telnet_worker). Le module Météo n'ajoute aucune nouvelle collecte ici
— il **consomme** ce qui existe déjà pour construire la corrélation.

---

## 4. Architecture backend

### 4.1 Nouveaux workers (pattern existant : `threading.Thread(daemon=True)`)

```python
def weather_worker():
    """Poll Open-Meteo toutes les 10 min. Pattern identique à solar_worker()."""
    threading.current_thread().name = 'WeatherWorker'
    logger.info("WeatherWorker démarré (update météo locale toutes les 10 min).")
    fetch_local_weather()  # run once immediately
    while True:
        time.sleep(600)
        fetch_local_weather()

def lightning_worker():
    """Écoute le flux Blitzortung en continu (WebSocket), alimente lightning_buffer."""
    threading.current_thread().name = 'LightningWorker'
    logger.info("LightningWorker démarré.")
    while True:
        try:
            _lightning_listen_loop()  # boucle WebSocket avec reconnexion
        except Exception as e:
            logger.warning(f"LightningWorker: connexion perdue ({e}), retry dans 30s")
            time.sleep(30)
```

Démarrage (dans le bloc `if __name__ == "__main__":`, à la suite des
threads existants) :

```python
threading.Thread(target=weather_worker, daemon=True).start()
threading.Thread(target=lightning_worker, daemon=True).start()
```

### 4.2 Structures de données en mémoire

Suivre le pattern déjà en place pour `spot_history` (deque + lock
dédié) :

```python
weather_cache = {"data": None, "ts": 0}  # dernier snapshot Open-Meteo
WEATHER_CACHE_TTL = 600  # 10 min, aligné sur le poll

lightning_buffer = deque(maxlen=500)   # impacts récents
lightning_lock = threading.Lock()
LIGHTNING_RETENTION_S = 3600  # on ne garde que la dernière heure en mémoire
```

### 4.3 Nouvelles routes Flask

Convention de nommage alignée sur l'existant
(`/api/...json` pour les endpoints de données, pas de préfixe
`/weather/` séparé — cohérence avec `/history.json`, `/live_bands.json`) :

| Route | Méthode | Rôle |
|-------|---------|------|
| `/api/weather/local.json` | GET | Snapshot conditions locales (température, pression, humidité, vent, pluie) |
| `/api/weather/lightning.json` | GET | Impacts de foudre de la dernière heure (lat, lon, dist_km, bearing, ts) |
| `/api/weather/radar_frame.json` | GET | *(Phase 2)* URL de la tuile RainViewer courante |
| `/api/weather/correlation.json` | GET | *(Phase 3)* Synthèse texte + indicateurs de corrélation |
| `/weather` | GET | Page HTML du nouvel onglet (`render_template('weather.html', ...)`) |

Chaque route lit uniquement le cache en mémoire (jamais d'appel réseau
synchrone dans une requête HTTP entrante) — c'est déjà le pattern
utilisé pour `solar_worker`/`fetch_solar_from_wwv_txt`, on le reproduit
à l'identique pour rester cohérent et ne jamais bloquer le thread Flask
principal sur un appel externe lent.

### 4.4 Corrélation bruit / orage (cœur de la Phase 1)

**Vérification effectuée (2026-08-03) — résultat détaillé :**

Le SNR est bien parsé de bout en bout dans le pipeline WSJT-X actuel :
`_wsjtx_parse_decode()` extrait `snr` (int32) → propagé dans
`spot_obj["snr"]` → stocké dans `wsjtx_spots` → exposé via
`/api/wsjtx/spots`.

**Mais** — restriction importante — `_wsjtx_inject_spot()` ne conserve
que les décodages qui sont soit un **CQ**, soit un appel **direct à
MY_CALL** (`is_cq or is_calling_me`, ligne ~3636). Tous les autres
décodages FT8/FT4 reçus (la majorité du trafic — QSO entre tiers,
rapports, 73...) sont traités par `wsjtx_worker()` au moment de leur
réception mais **ne sont jamais accumulés** dans une structure
exploitable pour une moyenne glissante. Seul le dernier décodage brut
est gardé (`wsjtx_state["last_decode"]`), écrasé à chaque nouveau
message.

Conséquence : `wsjtx_spots` ne peut **pas** servir de proxy fiable pour
"le bruit ambiant reçu en ce moment" — c'est un flux **filtré** pour
la watchlist/DX, pas un échantillon représentatif du SNR moyen de la
bande.

**Prérequis à ajouter avant Phase 1** (mineur, non-intrusif) :

```python
snr_buffer = deque(maxlen=200)   # (timestamp, snr, band) — TOUS les décodages
snr_buffer_lock = threading.Lock()
```

Dans `wsjtx_worker()`, branche `elif msg_type == MSG_DECODE:`, ajouter
l'alimentation de `snr_buffer` **avant** l'appel existant à
`_wsjtx_inject_spot()` (qui reste inchangé et continue de filtrer pour
son propre usage) :

```python
elif msg_type == MSG_DECODE:
    dec = _wsjtx_parse_decode(data, offset)
    with wsjtx_lock:
        wsjtx_state["last_decode"] = dec
        dial_freq = wsjtx_state["dial_freq"]
        wsjtx_mode = wsjtx_state["mode"]

    # NOUVEAU — accumuler TOUS les décodages pour la moyenne glissante SNR,
    # indépendamment du filtre CQ/calling_me appliqué par _wsjtx_inject_spot()
    with snr_buffer_lock:
        snr_buffer.append((time.time(), dec.get("snr", 0), wsjtx_mode))

    _wsjtx_inject_spot(dec, dial_freq, wsjtx_mode)
```

Une fonction `get_snr_rolling_average(window_s=1200)` (20 min glissant)
lit ensuite `snr_buffer` pour produire la valeur exploitée par
`compute_noise_correlation()`. Aucune régression sur le comportement
existant (`_wsjtx_inject_spot`, `spots_buffer`, watchlist) — c'est un
ajout parallèle, pas une modification du chemin actuel.

---

Logique de calcul, dans une fonction dédiée `compute_noise_correlation()` :

1. Lire `get_snr_rolling_average()` sur les 20 dernières minutes (voir
   ci-dessus — remplace le proxy "taux de spots basses bandes" envisagé
   initialement, maintenant que le SNR réel est accessible)
2. Comparer à la moyenne glissante d'il y a 1h (même fonction, fenêtre
   décalée) pour détecter une tendance à la baisse
3. Croiser avec `lightning_buffer` : y a-t-il eu des impacts dans un
   rayon de 50 km durant la même fenêtre ?
4. Générer une phrase factuelle, jamais causale à tort :
   > *"SNR FT8 moyen en baisse de 4 dB depuis 20 min · 8 impacts de
   > foudre détectés à moins de 30 km (NE)"*

   plutôt que :
   > ~~"L'orage dégrade la propagation"~~ (affirmation non prouvée par
   les données disponibles)

---

## 5. Architecture frontend

### 5.1 Nouvel onglet

Ajout dans la barre de navigation existante, pattern identique aux
onglets actuels (`index.html`, `map.html`, `ai.html`, `world.html`,
`briefing.html`, `satellites.html`) :

```
Accueil | Live | Analyse | Heatmap | Watchlist | Météo
```

Nouveau template `templates/weather.html`, même ossature Jinja2 que les
pages existantes (`version=APP_VERSION, my_call=MY_CALL, ...`).

### 5.2 Disposition (Phase 1)

Réutiliser le système de panels drag & drop existant
(`data-panel-id`, `dd-handle`, persistance via `data/ui_config.json`)
— **pas de nouveau système de layout**, cohérence totale avec Setup ⚙.

```
┌─────────────────────────────┬─────────────────────────────┐
│  CONDITIONS LOCALES          │  ACTIVITÉ ÉLECTRIQUE         │
│  🌡 Temp · 🔽 Pression        │  ⚡ Nb impacts (1h)          │
│  💧 Humidité · 🌬 Vent        │  📍 Distance min             │
│                               │  🧭 Direction dominante      │
├─────────────────────────────┴─────────────────────────────┤
│  CORRÉLATION BRUIT / MÉTÉO                                  │
│  "SNR FT8 moyen -4dB / 20min · 8 impacts <30km (NE)"        │
└─────────────────────────────────────────────────────────────┘
```

Phase 2 ajoute une carte Leaflet dédiée (radar en overlay) en
réutilisant l'instance Leaflet déjà initialisée pour `map.html` comme
référence de configuration (mêmes tuiles de fond, mêmes couleurs).

### 5.3 Polling frontend

Suivre le pattern déjà en place (`setInterval` + vérification
`isPanelHidden()` avant chaque appel, comme pour les Opportunités
DXCC) :

```javascript
setInterval(() => {
    if (!isPanelHidden('weather-local')) loadLocalWeather();
}, 600000);  // 10 min, aligné sur le TTL backend

setInterval(() => {
    if (!isPanelHidden('weather-lightning')) loadLightningData();
}, 60000);   // 1 min — la foudre est un événement rapide
```

---

## 6. Historique long terme (Phase 3)

Pour les corrélations saisonnières, on ne peut pas se contenter de
mémoire RAM (elle se vide au redémarrage). Suivre le pattern SQLite
déjà utilisé ailleurs dans l'app (cf. migrations `ALTER TABLE` /
`CREATE INDEX` séparés en deux `executescript()`, point de vigilance
déjà documenté) :

```sql
CREATE TABLE IF NOT EXISTS weather_history (
    ts INTEGER NOT NULL,
    temp_c REAL,
    pressure_hpa REAL,
    humidity_pct REAL,
    wind_kmh REAL,
    lightning_count_1h INTEGER,
    lightning_dist_min_km REAL,
    avg_snr_ft8 REAL,
    spot_count_hf INTEGER
);
-- Index créé dans un executescript() séparé, après coup (cf. point de vigilance existant)
```

Une ligne toutes les 10 min = ~4300 lignes/mois = table légère, pas de
souci de volume sur plusieurs mois même sur SD card modeste.

---

## 7. Risques et points de vigilance identifiés

- **Blitzortung n'a pas d'API publique officiellement stable** — le
  flux communautaire peut changer de format sans préavis. Prévoir un
  fallback propre (afficher "indisponible", ne jamais planter le
  panneau ni le worker — try/except large autour de la boucle
  d'écoute, exactement comme `lightning_worker()` esquissé plus haut).
- **Ne pas dupliquer un rate-limit externe** : Open-Meteo est tolérant,
  mais on garde quand même un TTL strict côté backend (10 min) pour
  rester bon citoyen et éviter de reproduire l'incident de rate
  limiting déjà rencontré avec PSK Reporter.
- **Ne jamais bloquer le thread Flask** sur un appel réseau météo —
  tout doit passer par les workers + cache, jamais par un fetch
  synchrone dans une route `/api/weather/*`.
- **SNR WSJT-X** : ✅ vérifié le 2026-08-03 — le SNR est bien parsé
  (`_wsjtx_parse_decode`) mais seul un sous-ensemble filtré
  (CQ/calling_me) est accumulé aujourd'hui via `_wsjtx_inject_spot()`.
  Un ajout mineur et non-intrusif (`snr_buffer`, cf. section 4.4) est
  nécessaire avant la Phase 1 pour disposer d'un échantillon SNR
  représentatif de tous les décodages, pas seulement des spots
  affichés.

---

## 8. Prochaine étape proposée

Si validé, prochaine session : implémenter la **Phase 1 uniquement**,
dans cet ordre :

1. Ajout du `snr_buffer` dans `wsjtx_worker()` (cf. section 4.4) —
   petit changement isolé, testable seul avant de toucher au reste
2. `weather_worker`, `lightning_worker`, 2 routes API
   (`/api/weather/local.json`, `/api/weather/lightning.json`)
3. `compute_noise_correlation()` s'appuyant sur `get_snr_rolling_average()`
4. Template `weather.html` avec 2 panels + encart corrélation

Livrable testable en une session, sans dépendance sur RainViewer ni
sur la synthèse IA.
