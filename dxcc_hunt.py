"""
dxcc_hunt.py — Mode Chasse DXCC — NEURAL DX WATCHER v12.4
============================================================
Inverse la logique du dashboard : au lieu d'afficher tous les spots actifs,
ne montre que ce qui MANQUE réellement (via LoTW), classé par priorité et
par facilité de pointage (distance/bearing).

Trois statuts de priorité (vocabulaire aligné sur /api/lotw/opportunities
pour rester cohérent avec le reste de l'app) :
  1. "new"                → DXCC jamais travaillé, toutes bandes confondues
  2. "worked_unconfirmed" → DXCC travaillé mais aucune QSL LoTW reçue
  3. "band_missing"       → DXCC confirmé ailleurs, mais pas sur CETTE bande

Un DXCC totalement confirmé sur la bande où il est spotté n'est PAS une
opportunité de chasse — il est simplement absent du résultat.

Module pur : ne dépend d'aucun état global de webapp.py. Les fonctions
utilitaires (bearing, rareté) sont injectées en paramètre pour rester
testable en isolation et éviter tout import circulaire avec webapp.py.

Usage (depuis webapp.py) :
    from dxcc_hunt import compute_hunt_list

    hunt_list, total_found = compute_hunt_list(
        spots=active_spots,
        confirmed_dxcc=confirmed_dxcc_set,
        worked_dxcc=worked_dxcc_set,
        dxcc_by_band=dxcc_by_band_dict,
        user_lat=user_lat, user_lon=user_lon,
        calculate_bearing_fn=calculate_bearing,
        bearing_to_compass_fn=bearing_to_compass,
        is_rare_fn=is_rare_prefix,
        band_filter=None,
        limit=15,
    )
"""

import time
from typing import Callable, Optional


# Libellés FR affichés côté frontend (clé = status interne)
STATUS_LABELS = {
    "new":                 "Jamais travaillé",
    "worked_unconfirmed":  "Travaillé — non confirmé",
    "band_missing":        "Manque sur cette bande",
}

# Priorité numérique (plus bas = plus urgent / plus rare)
STATUS_PRIORITY = {
    "new": 1,
    "worked_unconfirmed": 2,
    "band_missing": 3,
}


def _classify(country: str, band: str, confirmed_dxcc: set,
              worked_dxcc: set, dxcc_by_band: dict) -> Optional[str]:
    """
    Détermine le statut de chasse d'un (country, band).
    Retourne None si ce DXCC est déjà pleinement confirmé sur cette bande
    (= pas une opportunité, à exclure du résultat).
    """
    if not country or country == "Unknown":
        return None
    if country not in worked_dxcc:
        return "new"
    if country not in confirmed_dxcc:
        return "worked_unconfirmed"
    confirmed_on_band = dxcc_by_band.get(band, set())
    if country not in confirmed_on_band:
        return "band_missing"
    return None  # déjà tout bon sur cette bande — pas une cible de chasse


def compute_hunt_list(
    spots: list,
    confirmed_dxcc: set,
    worked_dxcc: set,
    dxcc_by_band: dict,
    user_lat: float,
    user_lon: float,
    calculate_bearing_fn: Callable[[float, float, float, float], float],
    bearing_to_compass_fn: Callable[[Optional[float]], str],
    is_rare_fn: Callable[[str], bool],
    band_filter: Optional[str] = None,
    limit: int = 15,
    now: Optional[float] = None,
) -> tuple:
    """
    Construit la liste de chasse DXCC à partir des spots actuellement actifs.

    spots : liste de spot_obj (dicts) — typiquement issus de spots_buffer déjà
            filtrés sur la fenêtre de vie (SPOT_LIFETIME).
    confirmed_dxcc / worked_dxcc : sets de noms de pays (lotw_data).
    dxcc_by_band : {band: set(pays confirmés sur cette bande)} (lotw_data).
    band_filter : si fourni, ne considère que les spots de cette bande.
    limit : nombre max d'entrées retournées (les meilleures en premier).

    Retourne (hunt_list, total_found) où total_found est le nombre total
    d'opportunités distinctes AVANT troncature par `limit` (pour affichage
    "23 opportunités, top 15 affichées").
    """
    if now is None:
        now = time.time()

    if band_filter:
        candidate_spots = [s for s in spots if s.get("band") == band_filter]
    else:
        candidate_spots = spots

    # Dédup par (country, band) : on garde le spot le plus récent pour
    # chaque paire, l'app affiche "ce qui est sur l'air maintenant", pas
    # un historique complet des passages.
    best_by_key = {}

    for s in candidate_spots:
        country = s.get("country", "")
        band = s.get("band", "")
        status = _classify(country, band, confirmed_dxcc, worked_dxcc, dxcc_by_band)
        if status is None:
            continue

        key = (country, band)
        ts = s.get("timestamp", 0)
        existing = best_by_key.get(key)
        if existing is None or ts > existing["_ts"]:
            best_by_key[key] = {
                "_ts": ts,
                "_status": status,
                "_spot": s,
            }

    total_found = len(best_by_key)

    # Construction des entrées finales
    entries = []
    for (country, band), rec in best_by_key.items():
        s = rec["_spot"]
        status = rec["_status"]
        dx_call = s.get("dx_call", "")
        lat = s.get("lat") or 0.0
        lon = s.get("lon") or 0.0

        bearing_deg = None
        compass = None
        if lat and lon and (lat != 0.0 or lon != 0.0):
            try:
                bearing_deg = calculate_bearing_fn(user_lat, user_lon, lat, lon)
                compass = bearing_to_compass_fn(bearing_deg)
            except Exception:
                bearing_deg = None
                compass = None

        is_rare = False
        try:
            is_rare = bool(is_rare_fn(dx_call))
        except Exception:
            is_rare = False

        spd_score = s.get("score", 0) or 0
        is_wanted = bool(s.get("is_wanted", False))

        entries.append({
            "dx_call":        dx_call,
            "country":        country,
            "band":           band,
            "mode":           s.get("mode", ""),
            "freq":           s.get("freq", ""),
            "status":         status,
            "status_label":   STATUS_LABELS.get(status, status),
            "priority":       STATUS_PRIORITY.get(status, 99),
            "distance_km":    s.get("distance_km"),
            "bearing_deg":    round(bearing_deg, 0) if bearing_deg is not None else None,
            "compass":        compass,
            "lat":            lat if (lat and (lat != 0.0 or lon != 0.0)) else None,
            "lon":            lon if (lat and (lat != 0.0 or lon != 0.0)) else None,
            "is_rare":        is_rare,
            "spd_score":      spd_score,
            "is_wanted":      is_wanted,
            "timestamp":      s.get("timestamp", 0),
            "age_s":          max(0, int(now - s.get("timestamp", now))),
        })

    # Tri : priorité croissante (new avant band_missing), puis score SPD
    # décroissant (rareté + distance + split + mode — signal plus fin que
    # le simple booléen "rare"), puis le plus récent en premier.
    entries.sort(key=lambda e: (e["priority"], -e["spd_score"], -e["timestamp"]))

    return entries[:limit], total_found
