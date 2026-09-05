"""
country_meta.py — Enrichissement pays DXCC — NEURAL DX WATCHER v12.4
========================================================================
Récupère drapeau, capitale, population et décalage horaire pour la Cible
n°1 du Mode Chasse DXCC, via l'API publique REST Countries (v3.1,
restcountries.com — gratuite, sans clé, aucune donnée inventée ici).

Utilisé uniquement pour la cible principale (pas les cibles secondaires)
pour limiter les appels réseau à un seul par refresh.

Cache : ces faits ne changent quasi jamais — cache mémoire + persistance
disque (data/country_meta_cache.json), TTL 30 jours, même pattern que
beacons_reference.json (refresh périodique, jamais de blocage si l'API
est indisponible : on retombe sur le cache existant, sinon None).

Certaines entités DXCC (cty.dat) ne sont pas des états souverains
("Corsica", "European Russia", "Alaska"...) — ALIASES redirige vers le
pays réel pour l'appel API. C'est une approximation assumée (le fuseau
horaire et le drapeau du pays rattaché sont réutilisés), jamais une
invention de chiffres : si aucune correspondance fiable n'existe, le
lookup échoue proprement et retourne None (le frontend masque le bloc).

Usage (depuis webapp.py) :
    from country_meta import get_country_meta
    import requests
    meta = get_country_meta("Papua New Guinea", requests.get, local_utc_offset=2.0)
    # meta = {"flag": "🇵🇬", "capital": "Port Moresby",
    #         "population": 10329931, "tz_diff_hours": 8.0}
"""

import json
import time
import logging
import urllib.parse
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("country_meta")

CACHE_TTL = 30 * 24 * 3600  # 30 jours — ces faits ne changent quasi jamais
CACHE_FILE = Path("data/country_meta_cache.json")
REQUEST_TIMEOUT = 5

# DXCC entities (cty.dat) qui ne correspondent pas à un nom de pays
# souverain interrogeable tel quel sur REST Countries. Liste volontairement
# incrémentale : si une entité manque, le lookup échoue juste proprement
# (pas de crash), on l'ajoute ici au besoin.
ALIASES = {
    "Corsica":                       "France",
    "European Russia":               "Russia",
    "Asiatic Russia":                "Russia",
    "Fed. Rep. of Germany":          "Germany",
    "England":                       "United Kingdom",
    "Scotland":                      "United Kingdom",
    "Wales":                         "United Kingdom",
    "Northern Ireland":              "United Kingdom",
    "Alaska":                        "United States",
    "Hawaii":                        "United States",
    "Balearic Is.":                  "Spain",
    "Canary Is.":                    "Spain",
    "Ceuta & Melilla":               "Spain",
    "Sardinia":                      "Italy",
    "Sicily":                        "Italy",
    "Azores":                        "Portugal",
    "Madeira Is.":                   "Portugal",
    "Franz Josef Land":              "Russia",
    "Kaliningrad":                   "Russia",
    "Svalbard":                      "Norway",
    "Jan Mayen":                     "Norway",
}

_cache: dict = {}
_cache_loaded = False


def _load_cache():
    global _cache, _cache_loaded
    if _cache_loaded:
        return
    _cache_loaded = True
    if CACHE_FILE.exists():
        try:
            _cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"country_meta: cache illisible, on repart de zéro ({e})")
            _cache = {}


def _save_cache():
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(_cache, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.debug(f"country_meta: échec sauvegarde cache (non bloquant): {e}")


def _parse_utc_offset(tz_str: str) -> Optional[float]:
    """'UTC+10:00' -> 10.0 ; 'UTC-03:30' -> -3.5 ; 'UTC' -> 0.0 ; invalide -> None."""
    if not tz_str:
        return None
    tz_str = tz_str.strip()
    if tz_str == "UTC":
        return 0.0
    if len(tz_str) < 5 or not tz_str.startswith("UTC"):
        return None
    try:
        sign = 1 if tz_str[3] == '+' else -1
        rest = tz_str[4:]
        parts = rest.split(':')
        hours = int(parts[0])
        minutes = int(parts[1]) if len(parts) > 1 else 0
        return sign * (hours + minutes / 60.0)
    except Exception:
        return None


def get_country_meta(
    dxcc_name: str,
    http_get_fn: Callable,
    local_utc_offset: float = 0.0,
) -> Optional[dict]:
    """
    Retourne {flag, capital, population, tz_diff_hours} pour un nom
    d'entité DXCC, ou None si aucune correspondance / API indisponible.

    dxcc_name        : nom d'entité DXCC (ex: 'Papua New Guinea', 'Corsica')
    http_get_fn       : fonction (url, timeout=...) -> objet réponse avec
                        .status_code et .json() — injectée pour rester
                        testable sans appel réseau réel (pattern dxcc_hunt.py)
    local_utc_offset  : décalage UTC actuel de la station (ex: 2.0 en été
                        France), pour calculer le décalage RELATIF affiché
    """
    if not dxcc_name:
        return None

    _load_cache()

    query_name = ALIASES.get(dxcc_name, dxcc_name)
    cache_key = query_name.lower()

    cached = _cache.get(cache_key)
    if cached and (time.time() - cached.get("fetched_at", 0)) < CACHE_TTL:
        return _with_tz_diff(cached.get("data"), local_utc_offset)

    try:
        url = (
            "https://restcountries.com/v3.1/name/"
            f"{urllib.parse.quote(query_name)}"
            "?fields=name,capital,population,flag,timezones"
        )
        resp = http_get_fn(url, timeout=REQUEST_TIMEOUT)
        if getattr(resp, "status_code", None) != 200:
            return _with_tz_diff(cached.get("data"), local_utc_offset) if cached else None

        payload = resp.json()
        entry = payload[0] if isinstance(payload, list) and payload else (
            payload if isinstance(payload, dict) else None
        )
        if not entry:
            return None

        capital_list = entry.get("capital") or []
        tz_list = entry.get("timezones") or []

        data = {
            "flag":              entry.get("flag"),
            "capital":           capital_list[0] if capital_list else None,
            "population":        entry.get("population"),
            "country_utc_offset": _parse_utc_offset(tz_list[0]) if tz_list else None,
        }
        _cache[cache_key] = {"data": data, "fetched_at": time.time()}
        _save_cache()
        return _with_tz_diff(data, local_utc_offset)

    except Exception as e:
        logger.debug(f"country_meta: échec lookup '{query_name}': {e}")
        return _with_tz_diff(cached.get("data"), local_utc_offset) if cached else None


def _with_tz_diff(data: Optional[dict], local_utc_offset: float) -> Optional[dict]:
    """Recalcule tz_diff_hours à la volée (local_utc_offset peut varier avec l'heure d'été)."""
    if not data:
        return None
    out = dict(data)
    country_offset = out.pop("country_utc_offset", None)
    out["tz_diff_hours"] = (
        round(country_offset - local_utc_offset, 1) if country_offset is not None else None
    )
    return out
