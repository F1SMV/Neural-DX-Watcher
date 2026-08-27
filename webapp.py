import time

# sgp4 — import au niveau module pour éviter les problèmes de PATH Python
try:
    from sgp4.api import Satrec as _Satrec
    SGP4_AVAILABLE = True
except ImportError:
    _Satrec = None
    SGP4_AVAILABLE = False

import socket
import threading
import json
import os
import sqlite3
import urllib.request
import urllib.parse
import urllib.error
import feedparser
import ssl
import math
import re
import logging
import html
import calendar
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from collections import deque, Counter, defaultdict
from flask import Flask, render_template, jsonify, request, abort, redirect, url_for, Response
from pathlib import Path
import subprocess

# ── v10.0 modules ──────────────────────────────────────────────────────────────
try:
    from predictor import Predictor
    _PREDICTOR_OK = True
except ImportError:
    _PREDICTOR_OK = False
    class Predictor:
        def __init__(self, **kw): pass
        def record_spot(self, *a, **kw): pass
        def record_session_heartbeat(self, *a, **kw): pass
        def sync_missing_dxcc(self, *a, **kw): pass
        def get_predictions(self, **kw): return []
        def get_stats(self): return {}
        def cleanup_old_data(self, *a, **kw): pass
        def invalidate_cache(self): pass

try:
    from ntfy_alerts import NtfyAlerter
    _NTFY_OK = True
except ImportError:
    _NTFY_OK = False
    class NtfyAlerter:
        def __init__(self, **kw): pass
        def record_presence(self): pass
        def on_watchlist_spot(self, *a, **kw): pass
        def on_new_dxcc(self, *a, **kw): pass
        def on_6m_surge(self, *a, **kw): pass
        def get_status(self): return {"enabled": False}
        def _send(self, **kw): pass

META_DIR = Path("data/meta")
META_SUMMARY = META_DIR / "summary.json"
LOTW_CACHE_FILE = Path("data/lotw_cache.json")
LOG_PATH_DEFAULT = Path("radio_spot_watcher.log")  # log courant
ANALYZER = Path("tools/log_meta_analyzer.py")

META_RUN_TOKEN = os.getenv("META_RUN_TOKEN", "")  # optionnel

# =============================================================
# CONFIGURATION IA BRIEF VOCAL (optionnel)
# Activer : définir la variable d'environnement PERPLEXITY_API_KEY
# Ex: export PERPLEXITY_API_KEY="pplx-xxxxxxxxxxxx"
# Désactiver : ne pas définir la variable (feature masquée automatiquement)
# =============================================================
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
AI_BRIEF_ENABLED = bool(PERPLEXITY_API_KEY)
AI_BRIEF_MODEL = "sonar-pro"        # modèle chat Perplexity actuel (2025)
AI_BRIEF_CACHE_TTL = 600           # 10 min entre deux appels API
AI_BRIEF_MAX_TOKENS = 300          # brief court = lecture vocale fluide

# --- CLUSTER TX (Spot) ---
tn_lock = threading.Lock()
tn_current = None  # socket.socket when connected
# --- FIN CLUSTER TX ---
# --- CONFIGURATION GENERALE ---
APP_VERSION = '12.2'
MY_CALL = "F1SMV"
WEB_PORT = 8000
KEEP_ALIVE = 60
SPOT_LIFETIME = 900
SPD_THRESHOLD = 70

# --- WSJT-X UDP ---
WSJTX_UDP_PORT = 2237        # Port UDP WSJT-X (défaut)
WSJTX_ENABLED  = True        # Mettre False pour désactiver
WSJTX_SPOT_LIFETIME = 600    # Durée de vie d'un spot WSJT-X (10 min)



# --- LISTE DES PRÉFIXES RARES (pour entités réellement rares) ---
RARE_PREFIXES = [
    'DP0', 'DP1', 'RI1', '8J1', 'VP8', 'KC4',
    '3Y', '3C', 'P5', 'BS7', 'BV9', 'CE0', 'CY9', 'EZ', 'FT5', 'FT8', 'VK0', 'VK7',
    'HV', '1A', '4U', 'E4', 'SV/A', 'T88', '9J', 'XU', '3D2', 'S21', 'H40',
    'KH0', 'KH1', 'KH3', 'KH4', 'KH7', 'KH9', 'KP1', 'KP5', 'T5', 'T31', 'T33', 'YV0',
    'YK', 'VK0', 'VK9', 'VP0', 'V21', 'XF4', 'XZ', 'ZK', 'ZL8', 'ZL7', 'ZL9',
]

TOP_RANKING_LIMIT = 10
DEFAULT_QRA = "JN23"

# --- CONFIGURATION UTILISATEUR (persistent en data/config.json) ---
CONFIG_FILE = Path("data/config.json")

def load_user_config():
    """Charge MY_CALL et user_qra depuis data/config.json (ou defaults si absent)."""
    global MY_CALL, user_qra
    try:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
            MY_CALL = data.get('my_call', MY_CALL).upper().strip()
            user_qra = data.get('user_qra', DEFAULT_QRA).upper().strip()
            logger.info(f"Config chargée : MY_CALL={MY_CALL}, user_qra={user_qra}")
        else:
            logger.info(f"Config.json absent, utilisation defaults : MY_CALL={MY_CALL}, user_qra={DEFAULT_QRA}")
            save_user_config()  # Crée le fichier avec les defaults
    except Exception as e:
        logger.warning(f"Erreur lors du chargement config.json : {e}, utilisation defaults")

def save_user_config():
    """Sauvegarde MY_CALL et user_qra dans data/config.json."""
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            'my_call': MY_CALL,
            'user_qra': user_qra,
            'timestamp_utc': datetime.utcnow().isoformat()
        }
        CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding='utf-8')
        logger.info(f"Config sauvegardée : MY_CALL={MY_CALL}, user_qra={user_qra}")
    except Exception as e:
        logger.warning(f"Erreur lors de la sauvegarde config.json : {e}")

# --- FIN CONFIGURATION UTILISATEUR ---

# --- THEMES/COULEURS RESTAURÉES ---
TEXT_MAIN = "#a0a0a0" # Gris clair
ACCENT = "#00f3ff"    # Cyan vif
ALERT = "#ff003c"     # Rouge
SUCCESS = "#00ff80"   # Vert
WARNING = "#ffcc00"   # Jaune
# --- FIN THEMES/COULEURS RESTAURÉES ---

# --- CONFIGURATION HISTORIQUE ---
HISTORY_BANDS = ['12m', '10m', '6m']
HISTORY_PERIOD_MINUTES = 30  # Granularité de 30 minutes
HISTORY_WINDOW_HOURS = 12    # Fenêtre de 12 heures
HISTORY_SLOTS = (HISTORY_WINDOW_HOURS * 60) // HISTORY_PERIOD_MINUTES  # 24 slots pour 12h/30min

# --- FICHIER DE LOG ---
LOG_FILE = "radio_spot_watcher.log"

# --- CONFIGURATION SURGE ---
SURGE_WINDOW = 900
SURGE_THRESHOLD = 3.0
MIN_SPOTS_FOR_SURGE = 3

# --- CONFIGURATION ASTRO/MÉTEOR SCATTER ---
METEOR_SHOWERS = [
    {"name": "Quadrantides", "start": (1, 1), "end": (1, 7), "peak": (1, 3)},
    {"name": "Lyrides", "start": (4, 16), "end": (4, 25), "peak": (4, 22)},
    {"name": "Êta Aquarides", "start": (4, 20), "end": (5, 30), "peak": (5, 6)},
    {"name": "Perséides", "start": (7, 15), "end": (8, 24), "peak": (8, 12)},
    {"name": "Orionides", "start": (10, 1), "end": (11, 7), "peak": (10, 21)},
    {"name": "Léonides", "start": (11, 10), "end": (11, 23), "peak": (11, 17)},
    {"name": "Géminides", "start": (12, 4), "end": (12, 17), "peak": (12, 14)},
]
MSK144_RANGE_KHZ = (144350, 144370)  # sous-segment MSK144 standard en 2m

# --- DEFINITIONS BANDES ---
HF_BANDS = ['160m', '80m', '60m', '40m', '30m', '20m', '17m', '15m', '12m', '10m', '6m']
VHF_BANDS = ['4m', '2m', '70cm', '23cm', '13cm', 'QO-100']
BAND_COLORS = {
    '160m': '#5c4b51', '80m': '#8e44ad', '60m': '#2c3e50',
    '40m': '#2980b9', '30m': '#16a085', '20m': '#27ae60',
    '17m': '#f1c40f', '15m': '#e67e22', '12m': '#d35400',
    '10m': '#c0392b',
    '6m': '#e84393',
    '4m': '#ff9ff3', '2m': '#f1c40f',
    '70cm': '#c0392b', '23cm': '#8e44ad', '13cm': '#bdc3c7',
    'QO-100': '#00a8ff'
}

# --- DX CLUSTER CONFIGURATION ---
RSS_URLS = ["https://www.dx-world.net/feed/"]
CLUSTERS = [
    ("dxfun.com", 8000),
    ("dxc.k0xm.net", 7300),
    ("dxc.nc7j.com", 7373),
]
CTY_URL = "https://www.country-files.com/cty/cty.dat"
CTY_FILE = "cty.dat"
WATCHLIST_FILE    = "watchlist.json"
WL_ACTIVITY_FILE  = Path("data/wl_activity.json")  # Persistance dernière activité watchlist
SOLAR_URL = "https://services.swpc.noaa.gov/text/wwv.txt"
NOAA_KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
BRIEFING_SOURCES_FILE = Path("data/briefing_sources.json")
BRIEFING_CACHE_TTL = 60 * 60 * 12
BRIEFING_FEED_TIMEOUT = 15
BRIEFING_ITEM_LIMIT = 8
BRIEFING_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
QO100_NEWS_URL = "https://qo100dx.club/news"
QO100_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}
BRIEFING_DEFAULT_SOURCES = [
    {
        "id": "dxworld",
        "name": "DX-World",
        "url": "https://www.dx-world.net/feed/",
        "site": "https://www.dx-world.net/",
        "type": "rss",
    },
    {
        "id": "arrl",
        "name": "ARRL News",
        "url": "https://www.arrl.org/news",
        "site": "https://www.arrl.org/news",
        "type": "html",
    },
    {
        "id": "ng3k",
        "name": "NG3K ADXO",
        "url": "https://www.ng3k.com/Misc/adxoplain.html",
        "site": "https://www.ng3k.com/misc/adxo.html",
        "type": "html",
    },
]

# --- SOLAR (XML) FETCHER ---

def fetch_noaa_kp_latest(timeout=10):
    """Fetch latest NOAA planetary Kp index (table JSON). Returns dict or None.
    
    Formats supportés :
    - Tableau d'objets (format actuel NOAA) : [{"time_tag":"...","Kp":3.67,...}, ...]
    - Tableau de tableaux (format legacy) : [["time_tag","Kp",...], ["2026-...",3.67,...], ...]
    """
    try:
        req = urllib.request.Request(NOAA_KP_URL, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode('utf-8', errors='ignore'))

        if not isinstance(data, list) or len(data) < 1:
            logger = logging.getLogger(__name__)
            logger.warning(f"Kp NOAA format unexpected: not a list or empty")
            return None

        # Format 1 : tableau d'objets (format actuel NOAA depuis 2020+)
        if isinstance(data[0], dict):
            row = data[-1]  # dernière ligne
            time_tag = str(row.get("time_tag", "")).replace(".000", "")
            kp = row.get("Kp")
            a_running = row.get("a_running")
            station_count = row.get("station_count")
            
            if kp is None:
                return None
            
            try:
                kp = float(kp)
                a_running = int(a_running) if a_running else None
                station_count = int(station_count) if station_count else None
            except (ValueError, TypeError):
                return None
            
            return {
                "kp": kp,
                "kp_time_utc": time_tag,
                "kp_a_running": a_running,
                "kp_station_count": station_count,
            }
        
        # Format 2 : tableau de tableaux (format legacy)
        elif isinstance(data[0], list) and len(data) >= 2:
            header = data[0]
            def _h(name, default=None):
                return header.index(name) if name in header else default

            i_time = _h("time_tag", 0)
            i_kp = _h("Kp", 1)
            i_a = _h("a_running", None)
            i_sc = _h("station_count", None)

            row = data[-1]
            time_tag = str(row[i_time]).replace(".000", "")
            kp = float(str(row[i_kp]).replace(",", "."))
            a_running = int(row[i_a]) if i_a is not None and str(row[i_a]).strip() else None
            station_count = int(row[i_sc]) if i_sc is not None and str(row[i_sc]).strip() else None

            return {
                "kp": kp,
                "kp_time_utc": time_tag,
                "kp_a_running": a_running,
                "kp_station_count": station_count,
            }
        
        else:
            logger = logging.getLogger(__name__)
            logger.warning(f"Kp NOAA format not recognized (not dict or list): {type(data[0])}")
            return None
            
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.warning(f"Kp NOAA fetch failed ({NOAA_KP_URL}): {type(e).__name__}: {e}")
        return None

def fetch_solar_from_wwv_txt():
    """
    Fetch solar indices from NOAA SWPC wwv.txt and NOAA planetary Kp (JSON table),
    then update solar_cache + solar_xml_cache.
    Runs hourly in solar_worker().
    """
    global solar_cache, solar_xml_cache
    try:
        req = urllib.request.Request(SOLAR_URL, headers={'User-Agent': 'Mozilla/5.0', 'Accept': '*/*'})
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode('utf-8', errors='ignore')

        # Robust parsing (wwv.txt format varies)
        sfi = a_idx = k_idx = "N/A"

        m_sfi = re.search(r"Solar\s+flux\s*[:=]?\s*([0-9]+)", raw, re.IGNORECASE)
        if m_sfi:
            sfi = m_sfi.group(1)

        m_a = re.search(r"\bA[-\s]?index\s*[:=]?\s*([0-9]+)", raw, re.IGNORECASE)
        if m_a:
            a_idx = m_a.group(1)

        m_k = re.search(r"\bK[-\s]?index\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)", raw, re.IGNORECASE)
        if m_k:
            k_idx = m_k.group(1)

        # Timestamp
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # NOAA Planetary Kp (robust JSON table)
        kp_info = fetch_noaa_kp_latest()
        kp_val = kp_info.get("kp") if kp_info else None
        kp_time_utc = kp_info.get("kp_time_utc") if kp_info else None
        kp_a_running = kp_info.get("kp_a_running") if kp_info else None
        kp_station_count = kp_info.get("kp_station_count") if kp_info else None

        # Backward-compat: keep 'k' field but prefer planetary Kp when available
        # Si Kp NOAA a échoué mais A-index est disponible, on approx Kp depuis A
        # (A ≈ 3 × Kp en moyenne pour conversion rapide)
        if isinstance(kp_val, (int, float)):
            k_display = f"{kp_val:.2f}"
        elif k_idx != "N/A":
            k_display = k_idx
        else:
            # Fallback : calcul approx Kp depuis A-index si dispon
            try:
                a_num = int(a_idx) if isinstance(a_idx, (int, str)) and str(a_idx).isdigit() else None
                if a_num is not None:
                    approx_kp = a_num / 3.0  # A ≈ 3 × Kp
                    k_display = f"{approx_kp:.1f}" if a_num > 0 else "0"
                else:
                    k_display = "N/A"
            except (ValueError, TypeError):
                k_display = "N/A"

        with solar_lock:
            solar_cache = {
                "sfi": sfi,
                "a": a_idx,
                "k": k_display,           # legacy field used by older UIs
                "kp": kp_val,             # numeric
                "kp_time_utc": kp_time_utc,
                "kp_a_running": kp_a_running,
                "kp_station_count": kp_station_count,
                "ts_utc": ts
            }

            solar_xml_cache = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<solar>'
                f'<sfi>{sfi}</sfi>'
                f'<a>{a_idx}</a>'
                f'<k>{k_display}</k>'
                f'<kp>{"" if kp_val is None else kp_val}</kp>'
                f'<kp_time_utc>{"" if kp_time_utc is None else kp_time_utc}</kp_time_utc>'
                f'<updated_utc>{ts}</updated_utc>'
                '</solar>'
            )

        status_msg = f"SFI={sfi} A={a_idx} K={k_display}" + (f" (Kp={kp_val})" if kp_val is not None else " (Kp fetch failed, falling back)")
        logger.info(f"SOLAR updated: {status_msg}")

    except Exception as e:
        logger.error(f"SolarWorker: impossible de récupérer/produire solar.xml: {e}")
def solar_worker():
    threading.current_thread().name = 'SolarWorker'
    logger.info("SolarWorker démarré (update solar.xml toutes les heures).")
    # run once immediately
    fetch_solar_from_wwv_txt()
    while True:
        time.sleep(3600)
        fetch_solar_from_wwv_txt()

def geo_distance_km(a, b):
    return calculate_distance(a["lat"], a["lon"], b["lat"], b["lon"])


# ══════════════════════════════════════════════════════════════════════════
# MODULE MÉTÉO — Phase 1 : conditions locales + foudre + corrélation
# Architecture : cf. ARCHITECTURE_METEO.md
# ══════════════════════════════════════════════════════════════════════════

def calculate_bearing(lat1, lon1, lat2, lon2):
    """Cap (0-360°, 0=Nord) du point 2 vu depuis le point 1."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
    brng = math.degrees(math.atan2(x, y))
    return (brng + 360) % 360

def bearing_to_compass(deg):
    """Convertit un cap en points cardinaux (N, NE, E, SE, S, SW, W, NW)."""
    if deg is None:
        return "?"
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    idx = int((deg + 22.5) // 45) % 8
    return dirs[idx]

# ── Conditions locales (Open-Meteo) ──────────────────────────────────────
weather_cache = {"data": None, "ts": 0}
WEATHER_CACHE_TTL = 1800  # 30 min — suffisant pour des conditions qui évoluent lentement
weather_history = deque(maxlen=20)   # ~3h20 d'historique (20 x 10 min), pour la tendance baromètre
weather_history_lock = threading.Lock()

def _closest_snapshot(history, history_lock, seconds_ago, tolerance_s=1800):
    """Utilitaire générique : snapshot historique le plus proche de 'il y a X secondes'."""
    target = time.time() - seconds_ago
    with history_lock:
        candidates = [(abs(ts - target), snap) for ts, snap in history]
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    best_diff, best_snap = candidates[0]
    return best_snap if best_diff <= tolerance_s else None

def get_pressure_trend():
    """Tendance barométrique sur ~2h (hausse/baisse/stable) — un indicateur
    météorologique réel et bien établi (baisse rapide = risque de dégradation)."""
    current = weather_cache.get("data")
    if not current or current.get("pressure_hpa") is None:
        return None
    ref = _closest_snapshot(weather_history, weather_history_lock, 7200, tolerance_s=1800)
    if not ref or ref.get("pressure_hpa") is None:
        return None
    delta = round(current["pressure_hpa"] - ref["pressure_hpa"], 1)
    if delta <= -2:
        trend = "falling"
    elif delta >= 2:
        trend = "rising"
    else:
        trend = "stable"
    return {"trend": trend, "delta_hpa": delta}

def fetch_local_weather():
    """Interroge Open-Meteo pour la position QTH courante (user_lat/user_lon).
    Gratuit, sans clé API. Échoue proprement (log + cache inchangé) en cas
    de souci réseau — ne doit jamais faire planter le worker.

    Inclut des paramètres d'altitude (CAPE, vent 300hPa, température 850hPa)
    pour une heuristique simplifiée de ducting tropo — cf. compute_tropo_index().
    NOTE : ces paramètres hourly dépendent du schéma Open-Meteo au moment de
    l'écriture ; si absents de la réponse, le ducting/CAPE afficheront '—'
    sans faire planter le reste (dégradation propre, comme pour wspr.live)."""
    global weather_cache
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={user_lat}&longitude={user_lon}"
            "&current=temperature_2m,pressure_msl,relative_humidity_2m,"
            "wind_speed_10m,wind_direction_10m,precipitation,weather_code"
            "&hourly=cape,temperature_850hPa,wind_speed_300hPa,wind_direction_300hPa"
            "&forecast_days=1&timezone=UTC"
        )
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        current = data.get("current", {})
        hourly = data.get("hourly", {})

        # Trouver l'index horaire le plus proche de l'heure courante
        idx = 0
        current_time_str = current.get("time")
        hourly_times = hourly.get("time", [])
        if current_time_str and hourly_times:
            try:
                idx = hourly_times.index(current_time_str)
            except ValueError:
                idx = min(int(time.strftime("%H", time.gmtime())), len(hourly_times) - 1) if hourly_times else 0

        def _hourly_at(key):
            vals = hourly.get(key, [])
            return vals[idx] if idx < len(vals) else None

        cape = _hourly_at("cape")
        temp_850 = _hourly_at("temperature_850hPa")
        wind_300_speed = _hourly_at("wind_speed_300hPa")
        wind_300_dir = _hourly_at("wind_direction_300hPa")
        surface_temp = current.get("temperature_2m")

        tropo = compute_tropo_index(surface_temp, temp_850, current.get("relative_humidity_2m"), cape)

        snapshot = {
            "temp_c": current.get("temperature_2m"),
            "pressure_hpa": current.get("pressure_msl"),
            "humidity_pct": current.get("relative_humidity_2m"),
            "wind_kmh": current.get("wind_speed_10m"),
            "wind_dir_deg": current.get("wind_direction_10m"),
            "wind_dir_compass": bearing_to_compass(current.get("wind_direction_10m")),
            "precipitation_mm": current.get("precipitation"),
            "weather_code": current.get("weather_code"),
            "cape": cape,
            "wind_300hpa_kmh": wind_300_speed,
            "wind_300hpa_compass": bearing_to_compass(wind_300_dir) if wind_300_dir is not None else None,
            "tropo_index": tropo["index"],
            "ducting_risk": tropo["ducting_risk"],
        }
        weather_cache["data"] = snapshot
        weather_cache["ts"] = time.time()
        with weather_history_lock:
            weather_history.append((time.time(), snapshot))
        logger.debug(f"WeatherWorker: MAJ conditions locales — {snapshot}")
    except Exception as e:
        logger.warning(f"WeatherWorker: échec fetch Open-Meteo ({e}) — cache conservé")

def compute_tropo_index(surface_temp, temp_850hpa, humidity_pct, cape):
    """Heuristique SIMPLIFIÉE (pas un modèle physique complet) de risque de
    ducting tropo, basée sur la détection d'inversion de température entre
    la surface et ~1500m (850hPa) : en air normal, la température baisse
    d'environ 8-9°C entre le sol et 850hPa. Une baisse plus faible (ou une
    hausse) indique une inversion — condition classique favorable au ducting
    troposphérique en VHF/UHF. Volontairement présenté comme un indice
    indicatif (0-10), jamais comme une prévision certaine."""
    if surface_temp is None or temp_850hpa is None:
        return {"index": None, "ducting_risk": None}

    expected_normal_drop = 8.5  # °C, atmosphère standard entre surface et ~1500m
    actual_drop = surface_temp - temp_850hpa
    inversion_strength = expected_normal_drop - actual_drop  # positif = inversion

    score = 0
    if inversion_strength >= 6:
        score += 4
    elif inversion_strength >= 3:
        score += 2
    elif inversion_strength >= 0:
        score += 1

    if humidity_pct is not None and humidity_pct >= 80:
        score += 2
    if cape is not None and cape < 100:  # air stable, peu convectif — favorable au ducting
        score += 1

    index = min(score * 10 // 7, 10)
    if index >= 7:
        risk = "élevé"
    elif index >= 4:
        risk = "modéré"
    else:
        risk = "faible"
    return {"index": index, "ducting_risk": risk}

def weather_worker():
    threading.current_thread().name = 'WeatherWorker'
    logger.info("WeatherWorker démarré (update météo locale toutes les 10 min).")
    fetch_local_weather()
    while True:
        time.sleep(WEATHER_CACHE_TTL)
        fetch_local_weather()

# ── Foudre (Blitzortung, via le pont MQTT communautaire) ────────────────
lightning_buffer = deque(maxlen=500)
lightning_lock = threading.Lock()
LIGHTNING_RETENTION_S = 3600  # on ne garde qu'1h en mémoire
LIGHTNING_RADIUS_KM = 300     # rayon d'intérêt autour du QTH

def _lightning_geohash(lat, lon, precision=3):
    """Encodage geohash standard (base32), utilisé pour filtrer le flux MQTT
    par zone géographique plutôt que de recevoir le flux mondial complet."""
    base32 = "0123456789bcdefghjkmnpqrstuvwxyz"
    lat_range = [-90.0, 90.0]
    lon_range = [-180.0, 180.0]
    geohash = []
    bits = [16, 8, 4, 2, 1]
    bit = 0
    ch = 0
    even = True
    while len(geohash) < precision:
        if even:
            mid = (lon_range[0] + lon_range[1]) / 2
            if lon > mid:
                ch |= bits[bit]
                lon_range[0] = mid
            else:
                lon_range[1] = mid
        else:
            mid = (lat_range[0] + lat_range[1]) / 2
            if lat > mid:
                ch |= bits[bit]
                lat_range[0] = mid
            else:
                lat_range[1] = mid
        even = not even
        if bit < 4:
            bit += 1
        else:
            geohash.append(base32[ch])
            bit = 0
            ch = 0
    return "".join(geohash)

def _lightning_geohash_neighbors(lat, lon, precision=3):
    """Retourne le geohash du QTH + ses 8 cellules voisines (grille 3x3).
    INDISPENSABLE : une cellule geohash de précision 3 mesure ~156x156km.
    S'abonner à une seule cellule laisse passer tout impact tombant dans
    une cellule voisine, même à quelques dizaines de km du QTH — Blitzortung
    publie par cellule d'origine du point, pas par distance au QTH."""
    bits_lon = (precision * 5 + 1) // 2
    bits_lat = (precision * 5) // 2
    lat_step = 180.0 / (2 ** bits_lat)
    lon_step = 360.0 / (2 ** bits_lon)
    hashes = set()
    for dlat in (-1, 0, 1):
        for dlon in (-1, 0, 1):
            nlat = max(-90.0, min(90.0, lat + dlat * lat_step))
            nlon = ((lon + dlon * lon_step + 180) % 360) - 180
            hashes.add(_lightning_geohash(nlat, nlon, precision))
    return hashes

def _lightning_on_message(client, userdata, msg):
    """Callback MQTT — un message = un impact de foudre détecté par le réseau
    communautaire Blitzortung. Format JSON : {"time":..., "lat":..., "lon":...}."""
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        lat = payload.get("lat")
        lon = payload.get("lon")
        if lat is None or lon is None:
            return
        dist_km = calculate_distance(user_lat, user_lon, lat, lon)
        if dist_km > LIGHTNING_RADIUS_KM:
            return  # hors zone d'intérêt, on ignore
        bearing = calculate_bearing(user_lat, user_lon, lat, lon)
        with lightning_lock:
            lightning_buffer.append({
                "ts": payload.get("time", time.time() * 1e9) / 1e9 if payload.get("time", 0) > 1e12 else time.time(),
                "lat": lat, "lon": lon,
                "dist_km": round(dist_km, 1),
                "bearing_deg": round(bearing, 0),
                "bearing_compass": bearing_to_compass(bearing),
            })
    except Exception as e:
        logger.debug(f"LightningWorker: message ignoré ({e})")

def _lightning_on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        geohashes = _lightning_geohash_neighbors(user_lat, user_lon, precision=3)
        for gh in sorted(geohashes):
            topic = "blitzortung/1.1/" + "/".join(gh) + "/#"
            client.subscribe(topic)
        logger.info(f"LightningWorker: connecté, abonné à {len(geohashes)} cellules (format /s/p/e/) : {sorted(geohashes)}")
    else:
        logger.warning(f"LightningWorker: échec connexion MQTT (rc={rc})")

def lightning_worker():
    """Écoute le pont MQTT communautaire Blitzortung en continu, reconnexion
    automatique en cas de coupure. Dégrade proprement (log + retry) si le
    service est indisponible — ne doit jamais planter le processus Flask.

    NOTE IMPORTANTE : ce pont communautaire (blitzortung.ha.sed.pl, utilisé
    par l'intégration Home Assistant "blitzortung") n'a pas de garantie de
    service officielle. Si aucun impact n'apparaît après plusieurs heures
    d'orage visible ailleurs, vérifier :
      1. Que les geohash calculés correspondent bien à la bonne zone (logs
         INFO — 9 cellules doivent être listées : QTH + 8 voisines)
      2. Que le port 1883 sortant n'est pas bloqué par le pare-feu/routeur
      3. Envisager d'élargir LIGHTNING_RADIUS_KM ou réduire la précision
         du geohash (2 au lieu de 3) si la zone couverte est trop petite
    """
    threading.current_thread().name = 'LightningWorker'
    logger.info("LightningWorker démarré (pont MQTT Blitzortung communautaire).")
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        logger.warning("LightningWorker: paho-mqtt non installé — module foudre désactivé. "
                        "Installer avec: pip install paho-mqtt --break-system-packages")
        return

    while True:
        try:
            client = mqtt.Client()
            client.on_connect = _lightning_on_connect
            client.on_message = _lightning_on_message
            client.connect("blitzortung.ha.sed.pl", 1883, keepalive=60)
            client.loop_forever()  # bloque ici, reconnexion gérée par la boucle while externe
        except Exception as e:
            logger.warning(f"LightningWorker: connexion perdue ou échouée ({e}), retry dans 30s")
            time.sleep(30)

def _lightning_prune():
    """Retire les impacts trop anciens du buffer (appelé à chaque lecture)."""
    cutoff = time.time() - LIGHTNING_RETENTION_S
    with lightning_lock:
        while lightning_buffer and lightning_buffer[0]["ts"] < cutoff:
            lightning_buffer.popleft()

# ── WSPR (wspr.live) — SOURCE PRIORITAIRE pour l'indicateur d'activité ambiante ──
# Contrairement au SNR WSJT-X (qui exige que WSJT-X soit ouvert et connecté),
# le réseau WSPR tourne en continu 24/7 grâce aux balises d'autres opérateurs.
# On interroge ici les rapports de réception captés par des stations proches
# du QTH (peu importe qui transmet) : ça donne une image de l'activité radio
# ambiante dans la région, disponible même quand l'utilisateur n'est pas au poste.
WSPR_CACHE_TTL = 600       # 10 min — un nouveau cycle WSPR toutes les 2 min, pas besoin de plus
WSPR_RADIUS_KM = 500       # rayon plus large que la foudre : le réseau WSPR est plus épars
WSPR_2M_CONFIRM_RADIUS_KM = 300  # rayon plus serré pour la confirmation tropo 2m (cf. fetch_wspr_2m_confirmation)
wspr_cache = {"data": None, "ts": 0}
wspr_history = deque(maxlen=20)   # ~3h20 d'historique (20 x 10 min) pour les tendances
wspr_history_lock = threading.Lock()

WSPR_BAND_CODES = {
    -1: "2200m", 0: "630m", 1: "160m", 3: "80m", 5: "60m", 7: "40m",
    10: "30m", 14: "20m", 18: "17m", 21: "15m", 24: "12m", 28: "10m",
    50: "6m", 70: "4m", 144: "2m", 432: "70cm", 1296: "23cm",
}

def fetch_wspr_nearby():
    """Interroge wspr.live (base ClickHouse publique, gratuite, sans clé) pour
    les rapports de réception captés par des stations dans WSPR_RADIUS_KM du QTH,
    sur les 30 dernières minutes. Échoue proprement (log + cache conservé) en
    cas de souci réseau ou de schéma de données différent de celui documenté.

    Sépare volontairement HF et VHF+ : les deux ont des dynamiques de bruit
    et de propagation très différentes (ionosphérique/atmosphérique pour HF,
    troposphérique/Es et surtout QRM local pour VHF), donc les mélanger dans
    une seule moyenne masquerait l'information plutôt que de l'éclairer —
    en particulier pour une app qui suit activement le 6m/sporadic-E.

    NOTE : le schéma de table utilisé ici (wspr.rx avec colonnes rx_lat/rx_lon/
    band/snr/time) correspond à la documentation publique de wspr.live au
    moment de l'écriture. Si l'API ne répond pas comme attendu, vérifier le
    schéma actuel sur https://wspr.live et ajuster la requête SQL ci-dessous."""
    global wspr_cache
    try:
        lat_delta = WSPR_RADIUS_KM / 111.0
        lon_delta = WSPR_RADIUS_KM / (111.0 * max(math.cos(math.radians(user_lat)), 0.1))
        lat_min, lat_max = user_lat - lat_delta, user_lat + lat_delta
        lon_min, lon_max = user_lon - lon_delta, user_lon + lon_delta

        sql = (
            "SELECT band, count() AS spot_count, avg(snr) AS avg_snr, avg(distance) AS avg_dist "
            "FROM wspr.rx "
            "WHERE time > now() - INTERVAL 30 MINUTE "
            f"AND rx_lat BETWEEN {lat_min:.4f} AND {lat_max:.4f} "
            f"AND rx_lon BETWEEN {lon_min:.4f} AND {lon_max:.4f} "
            "GROUP BY band ORDER BY spot_count DESC "
            "FORMAT JSON"
        )
        resp = requests.get("https://db1.wspr.live/", params={"query": sql}, timeout=15)
        resp.raise_for_status()
        rows = resp.json().get("data", [])

        total_spots = sum(int(r.get("spot_count", 0)) for r in rows)
        dominant = rows[0] if rows else None
        dominant_band = WSPR_BAND_CODES.get(int(dominant["band"]), f"{dominant['band']}MHz") if dominant else None
        overall_avg_snr = (
            round(sum(float(r.get("avg_snr", 0)) * int(r.get("spot_count", 0)) for r in rows) / total_spots, 1)
            if total_spots > 0 else None
        )

        bands_list = [
            {"band": WSPR_BAND_CODES.get(int(r["band"]), f"{r['band']}MHz"),
             "band_code": int(r["band"]),
             "spot_count": int(r["spot_count"]),
             "avg_snr": round(float(r["avg_snr"]), 1)}
            for r in rows
        ]

        # ── Agrégats séparés HF (≤ 28 : 10m et en-dessous) vs VHF+ (≥ 50 : 6m et au-dessus) ──
        def _aggregate(subset):
            n = sum(b["spot_count"] for b in subset)
            if n == 0:
                return {"total_spots": 0, "dominant_band": None, "avg_snr": None}
            dom = max(subset, key=lambda b: b["spot_count"])
            avg = round(sum(b["avg_snr"] * b["spot_count"] for b in subset) / n, 1)
            return {"total_spots": n, "dominant_band": dom["band"], "avg_snr": avg}

        hf_bands = [b for b in bands_list if b["band_code"] <= 28]
        vhf_bands = [b for b in bands_list if b["band_code"] >= 50]

        snapshot = {
            "total_spots": total_spots,
            "dominant_band": dominant_band,
            "avg_snr": overall_avg_snr,
            "bands": bands_list,
            "hf": _aggregate(hf_bands),
            "vhf": _aggregate(vhf_bands),
        }
        now = time.time()
        with wspr_history_lock:
            wspr_cache["data"] = snapshot
            wspr_cache["ts"] = now
            wspr_history.append((now, snapshot))
        logger.debug(f"WsprWorker: {total_spots} spots WSPR dans {WSPR_RADIUS_KM}km, bande dominante {dominant_band}")
    except Exception as e:
        logger.warning(f"WsprWorker: échec fetch wspr.live ({e}) — cache conservé, repli SNR WSJT-X actif")

    fetch_wspr_2m_confirmation()

def fetch_wspr_2m_confirmation():
    """Confirmation tropo VHF : spots WSPR reçus spécifiquement en 2m (144MHz)
    dans un rayon plus serré (300km). Un spot 2m local est un signal bien plus
    parlant qu'un spot 6m pour confirmer un vrai ducting troposphérique — le 6m
    fonctionne aussi (et surtout) en Sporadic-E sur 1000-2500km, sans rapport
    avec le ducting local, alors que le 2m WSPR à courte distance est presque
    toujours d'origine troposphérique.

    IMPORTANT : dépend qu'un opérateur balise activement en 2m WSPR à proximité.
    Zéro spot ne veut PAS dire 'pas d'ouverture' — juste 'pas de balise
    disponible pour confirmer'. Ne jamais présenter l'absence de donnée comme
    une absence de condition favorable (même principe que partout ailleurs
    dans le module météo : Blitzortung, SNR WSJT-X, etc.)."""
    global wspr_cache
    try:
        lat_delta = WSPR_2M_CONFIRM_RADIUS_KM / 111.0
        lon_delta = WSPR_2M_CONFIRM_RADIUS_KM / (111.0 * max(math.cos(math.radians(user_lat)), 0.1))
        lat_min, lat_max = user_lat - lat_delta, user_lat + lat_delta
        lon_min, lon_max = user_lon - lon_delta, user_lon + lon_delta

        sql = (
            "SELECT count() AS spot_count, avg(snr) AS avg_snr, avg(distance) AS avg_dist "
            "FROM wspr.rx "
            "WHERE band = 144 AND time > now() - INTERVAL 30 MINUTE "
            f"AND rx_lat BETWEEN {lat_min:.4f} AND {lat_max:.4f} "
            f"AND rx_lon BETWEEN {lon_min:.4f} AND {lon_max:.4f} "
            "FORMAT JSON"
        )
        resp = requests.get("https://db1.wspr.live/", params={"query": sql}, timeout=15)
        resp.raise_for_status()
        rows = resp.json().get("data", [])
        row = rows[0] if rows else {}
        spot_count = int(row.get("spot_count", 0) or 0)

        confirmation = {
            "spot_count": spot_count,
            "avg_snr": round(float(row["avg_snr"]), 1) if spot_count > 0 and row.get("avg_snr") is not None else None,
            "avg_dist_km": round(float(row["avg_dist"]), 0) if spot_count > 0 and row.get("avg_dist") is not None else None,
            "radius_km": WSPR_2M_CONFIRM_RADIUS_KM,
            "beacon_available": spot_count > 0,
        }
        if wspr_cache.get("data") is not None:
            wspr_cache["data"]["confirmation_2m"] = confirmation
        logger.debug(f"WsprWorker: confirmation 2m — {spot_count} spot(s) dans {WSPR_2M_CONFIRM_RADIUS_KM}km")
    except Exception as e:
        logger.warning(f"WsprWorker: échec fetch confirmation 2m ({e})")

def wspr_worker():
    threading.current_thread().name = 'WsprWorker'
    logger.info("WsprWorker démarré (update activité WSPR ambiante toutes les 10 min).")
    fetch_wspr_nearby()
    while True:
        time.sleep(WSPR_CACHE_TTL)
        fetch_wspr_nearby()

def get_wspr_snapshot_near(seconds_ago, tolerance_s=900):
    """Retourne le snapshot WSPR historique le plus proche de 'il y a X secondes',
    ou None si aucun snapshot dans la tolérance donnée."""
    target = time.time() - seconds_ago
    with wspr_history_lock:
        candidates = [(abs(ts - target), snap) for ts, snap in wspr_history]
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    best_diff, best_snap = candidates[0]
    return best_snap if best_diff <= tolerance_s else None

def get_ambient_activity():
    """Indicateur d'activité radio ambiante : WSPR en priorité (fonctionne 24/7,
    aucune dépendance à WSJT-X), repli sur le SNR WSJT-X si WSPR est indisponible
    ou vide (zone à faible densité de balises). La source utilisée est toujours
    explicitée pour rester honnête sur l'origine de la donnée affichée.

    Utilise spécifiquement l'agrégat HF (pas le mélange HF+VHF) : le QRN
    atmosphérique/foudre affecte presque exclusivement le HF (bruit ionosphérique
    et atmosphérique), le VHF étant dominé par d'autres facteurs (Es, QRM local).
    Mélanger les deux masquerait le signal plutôt que de l'éclairer."""
    wspr_now = wspr_cache.get("data")
    hf_now = wspr_now.get("hf") if wspr_now else None
    if hf_now and hf_now.get("total_spots", 0) > 0:
        wspr_1h_ago = get_wspr_snapshot_near(3600, tolerance_s=900)
        hf_1h_ago = wspr_1h_ago.get("hf") if wspr_1h_ago else None
        return {
            "source": "wspr",
            "band": hf_now.get("dominant_band"),
            "value_now": hf_now.get("avg_snr"),
            "spot_count_now": hf_now.get("total_spots"),
            "value_1h_ago": hf_1h_ago.get("avg_snr") if hf_1h_ago else None,
            "spot_count_1h_ago": hf_1h_ago.get("total_spots") if hf_1h_ago else None,
        }

    # Repli : SNR WSJT-X (nécessite WSJT-X ouvert et connecté)
    snr_now = get_snr_rolling_average(0, 1200)
    if snr_now is not None:
        return {
            "source": "wsjtx",
            "band": get_snr_reference_band(1200),
            "value_now": snr_now,
            "value_1h_ago": get_snr_rolling_average(3600, 4800),
        }

    return {"source": "none", "band": None, "value_now": None, "value_1h_ago": None}

# ── Corrélation bruit / météo ────────────────────────────────────────────
def _s_unit_hint(delta_db):
    """Convertit un écart en dB en équivalent 'points S' (repère radioamateur
    standard : ~6dB = 1 point S sur la plupart des S-mètres). Purement
    indicatif — ne prétend pas être une mesure calibrée."""
    s_points = round(abs(delta_db) / 6)
    if s_points < 1:
        return None
    return s_points

def compute_noise_correlation():
    """Synthèse factuelle (jamais causale à tort) croisant l'activité radio
    ambiante et le QRN (bruit électrique/atmosphérique, foudre) récent. Cf.
    section 4.4 de ARCHITECTURE_METEO.md. Source prioritaire : spots WSPR
    captés par des stations proches du QTH (fonctionne 24/7, aucune
    dépendance à WSJT-X). Repli : SNR WSJT-X si WSPR indisponible ou zone à
    faible densité de balises. La source utilisée est toujours explicitée.
    Vocabulaire volontairement radioamateur (QRN, points S) pour parler
    directement aux techniciens plutôt qu'en jargon météo générique."""
    _lightning_prune()

    activity = get_ambient_activity()
    source = activity["source"]
    ref_band = activity.get("band")
    value_now = activity.get("value_now")
    value_1h_ago = activity.get("value_1h_ago")

    with lightning_lock:
        recent_strikes = [s for s in lightning_buffer if time.time() - s["ts"] <= 1800]  # 30 min
        strikes_close = [s for s in recent_strikes if s["dist_km"] <= 50]

    # ── Bloc activité radio ambiante (bilingue, séparé du QRN) ──────────
    if source == "wspr":
        spot_count = activity.get("spot_count_now", 0)
        if value_1h_ago is not None and value_now is not None:
            delta = round(value_now - value_1h_ago, 1)
            s_pts = _s_unit_hint(delta)
            s_hint_fr = f" (≈ {s_pts} point{'s' if s_pts > 1 else ''} S)" if s_pts else ""
            s_hint_en = f" (≈ {s_pts} S-point{'s' if s_pts > 1 else ''})" if s_pts else ""
            if abs(delta) >= 2:
                sign_fr = "en baisse" if delta < 0 else "en hausse"
                sign_en = "down" if delta < 0 else "up"
                activity_fr = (
                    f"Sur {ref_band}, le SNR moyen des balises WSPR captées près de ton QTH est {sign_fr} "
                    f"de {abs(delta)} dB en 1h{s_hint_fr} — actuellement {value_now} dB sur {spot_count} rapports."
                )
                activity_en = (
                    f"On {ref_band}, the average SNR of WSPR beacons near your QTH is {sign_en} "
                    f"{abs(delta)} dB over 1h{s_hint_en} — currently {value_now} dB across {spot_count} reports."
                )
            else:
                activity_fr = f"Sur {ref_band}, SNR WSPR stable ({value_now} dB, {spot_count} rapports) — pas de variation notable."
                activity_en = f"On {ref_band}, WSPR SNR stable ({value_now} dB, {spot_count} reports) — no notable change."
        else:
            activity_fr = f"Sur {ref_band}, {spot_count} rapports WSPR, SNR moyen {value_now} dB (historique insuffisant pour une tendance)."
            activity_en = f"On {ref_band}, {spot_count} WSPR reports, average SNR {value_now} dB (not enough history for a trend)."

    elif source == "wsjtx":
        if value_1h_ago is not None and value_now is not None:
            delta = round(value_now - value_1h_ago, 1)
            s_pts = _s_unit_hint(delta)
            s_hint_fr = f" (≈ {s_pts} point{'s' if s_pts > 1 else ''} S)" if s_pts else ""
            s_hint_en = f" (≈ {s_pts} S-point{'s' if s_pts > 1 else ''})" if s_pts else ""
            if abs(delta) >= 2:
                sign_fr = "en baisse" if delta < 0 else "en hausse"
                sign_en = "down" if delta < 0 else "up"
                activity_fr = (
                    f"Pas de balise WSPR à proximité — repli sur ta station : SNR FT8/FT4 sur {ref_band} "
                    f"{sign_fr} de {abs(delta)} dB en 1h{s_hint_fr} (actuellement {value_now} dB)."
                )
                activity_en = (
                    f"No nearby WSPR beacons — falling back to your station: FT8/FT4 SNR on {ref_band} "
                    f"{sign_en} {abs(delta)} dB over 1h{s_hint_en} (currently {value_now} dB)."
                )
            else:
                activity_fr = f"Pas de balise WSPR à proximité — SNR FT8/FT4 stable sur {ref_band} ({value_now} dB)."
                activity_en = f"No nearby WSPR beacons — FT8/FT4 SNR stable on {ref_band} ({value_now} dB)."
        else:
            activity_fr = f"Pas de balise WSPR à proximité — SNR FT8/FT4 actuel sur {ref_band} : {value_now} dB."
            activity_en = f"No nearby WSPR beacons — current FT8/FT4 SNR on {ref_band}: {value_now} dB."
    else:
        activity_fr = "Aucune donnée : pas de balise WSPR captée et WSJT-X non connecté."
        activity_en = "No data: no WSPR beacon received and WSJT-X not connected."

    # ── Bloc VHF/6m (bilingue, distinct du HF — dynamiques différentes) ──
    wspr_snap = wspr_cache.get("data")
    vhf_data = wspr_snap.get("vhf") if wspr_snap else None
    if vhf_data and vhf_data.get("total_spots", 0) > 0:
        vhf_fr = (
            f"En VHF, {vhf_data['total_spots']} rapports WSPR captés sur {vhf_data['dominant_band']} "
            f"(SNR moyen {vhf_data['avg_snr']} dB) — une ouverture Es ou une propagation "
            f"troposphérique est possible, indépendamment du QRN HF ci-dessus."
        )
        vhf_en = (
            f"On VHF, {vhf_data['total_spots']} WSPR reports received on {vhf_data['dominant_band']} "
            f"(average SNR {vhf_data['avg_snr']} dB) — an Es opening or tropospheric propagation "
            f"is possible, independent of the HF QRN above."
        )
    else:
        vhf_fr = "Aucune balise WSPR VHF (6m et au-dessus) captée actuellement dans la zone."
        vhf_en = "No VHF (6m and above) WSPR beacons currently received in the area."

    # Confirmation tropo 2m (300km) : signal plus fiable que le 6m pour le ducting local,
    # mais dépend qu'une balise 2m WSPR soit active à proximité — jamais présenté comme
    # "pas d'ouverture" en son absence, seulement "pas de confirmation disponible".
    confirm_2m = wspr_snap.get("confirmation_2m") if wspr_snap else None
    if confirm_2m and confirm_2m.get("beacon_available"):
        dist_txt = f", à ~{int(confirm_2m['avg_dist_km'])}km" if confirm_2m.get("avg_dist_km") else ""
        dist_txt_en = f", ~{int(confirm_2m['avg_dist_km'])}km away" if confirm_2m.get("avg_dist_km") else ""
        vhf_fr += (
            f" Confirmation 2m (300km) : {confirm_2m['spot_count']} spot"
            f"{'s' if confirm_2m['spot_count'] > 1 else ''} WSPR reçu{'s' if confirm_2m['spot_count'] > 1 else ''}"
            f"{dist_txt} (SNR {confirm_2m['avg_snr']} dB) — signe assez fiable d'un vrai ducting tropo local."
        )
        vhf_en += (
            f" 2m confirmation (300km): {confirm_2m['spot_count']} WSPR spot"
            f"{'s' if confirm_2m['spot_count'] > 1 else ''} received{dist_txt_en} "
            f"(SNR {confirm_2m['avg_snr']} dB) — a fairly reliable sign of real local tropo ducting."
        )
    else:
        vhf_fr += " Confirmation 2m (300km) : aucune balise 2m disponible pour confirmer (pas d'opérateur actif à proximité — ne signifie pas absence d'ouverture)."
        vhf_en += " 2m confirmation (300km): no 2m beacon available to confirm (no active operator nearby — does not mean no opening)."

    # ── Bloc QRN / foudre (bilingue, séparé) ────────────────────────────
    if strikes_close:
        closest = min(strikes_close, key=lambda s: s["dist_km"])
        n = len(strikes_close)
        lightning_fr = (
            f"{n} impact{'s' if n > 1 else ''} < 50 km dans les 30 dernières minutes "
            f"(le plus proche : {closest['dist_km']} km {closest['bearing_compass']}) — "
            f"un QRN élevé sur les bandes basses (80/40m) est probable."
        )
        lightning_en = (
            f"{n} strike{'s' if n > 1 else ''} within 50 km in the last 30 minutes "
            f"(closest: {closest['dist_km']} km {closest['bearing_compass']}) — "
            f"expect elevated QRN on the lower bands (80/40m)."
        )
    elif recent_strikes:
        n = len(recent_strikes)
        lightning_fr = f"{n} impacts dans un rayon de {LIGHTNING_RADIUS_KM} km, mais > 50 km — QRN local probablement peu affecté."
        lightning_en = f"{n} strikes within {LIGHTNING_RADIUS_KM} km, but beyond 50 km — local QRN likely not much affected."
    else:
        lightning_fr = f"Aucun impact détecté dans un rayon de {LIGHTNING_RADIUS_KM} km — pas de QRN orageux attendu."
        lightning_en = f"No strikes detected within {LIGHTNING_RADIUS_KM} km — no storm-related QRN expected."

    summary_fr = f"{activity_fr} {vhf_fr} {lightning_fr}"
    summary_en = f"{activity_en} {vhf_en} {lightning_en}"

    # ── Niveau global (jauge visuelle) ──────────────────────────────────
    # Score heuristique simple, jamais présenté comme une mesure scientifique :
    # sert uniquement à donner un repère visuel rapide (calme → orageux).
    score = 0
    if value_now is not None and value_1h_ago is not None:
        delta = value_now - value_1h_ago
        if delta <= -6:
            score += 3
        elif delta <= -3:
            score += 2
        elif delta <= -1.5:
            score += 1
    if strikes_close:
        score += min(len(strikes_close), 3)
    elif recent_strikes:
        score += 1

    if score >= 5:
        level, level_fr, level_en = "stormy", "Orageux", "Stormy"
    elif score >= 3:
        level, level_fr, level_en = "disturbed", "Perturbé", "Disturbed"
    elif score >= 1:
        level, level_fr, level_en = "elevated", "Élevé", "Elevated"
    else:
        level, level_fr, level_en = "calm", "Calme", "Calm"

    return {
        "summary_fr": summary_fr,
        "summary_en": summary_en,
        "summary": summary_fr,  # rétrocompatibilité : garder une clé simple = FR par défaut
        "activity_fr": activity_fr,
        "activity_en": activity_en,
        "vhf_fr": vhf_fr,
        "vhf_en": vhf_en,
        "vhf_data": vhf_data,
        "lightning_fr": lightning_fr,
        "lightning_en": lightning_en,
        "source": source,
        "reference_band": ref_band,
        "value_now": value_now,
        "value_1h_ago": value_1h_ago,
        "lightning_count_30min": len(recent_strikes),
        "lightning_count_close_50km": len(strikes_close),
        "level": level,
        "level_label_fr": level_fr,
        "level_label_en": level_en,
        "ts": time.time(),
    }

def compute_global_synthesis():
    """Jauge de synthèse HF/VHF — heuristique transparente, PAS une mesure
    physique calibrée. HF dérivé du niveau QRN (compute_noise_correlation).
    VHF dérivé de la présence/qualité des spots WSPR VHF + de l'indice tropo.
    Si une donnée manque, retourne None pour cette composante plutôt que
    d'inventer un chiffre — le frontend doit afficher '—' dans ce cas."""
    correlation = compute_noise_correlation()
    level_to_pct = {"calm": 92, "elevated": 70, "disturbed": 45, "stormy": 20}
    hf_pct = level_to_pct.get(correlation.get("level"))

    vhf_pct = None
    wspr_snap = wspr_cache.get("data")
    vhf_data = wspr_snap.get("vhf") if wspr_snap else None
    weather = weather_cache.get("data") or {}
    tropo_index = weather.get("tropo_index")

    if vhf_data and vhf_data.get("total_spots", 0) > 0:
        snr = vhf_data.get("avg_snr") or -20
        vhf_pct = max(0, min(100, round((snr + 25) * 4)))
        if tropo_index is not None:
            vhf_pct = round(vhf_pct * 0.7 + (tropo_index * 10) * 0.3)
    elif tropo_index is not None:
        vhf_pct = round(tropo_index * 10 * 0.6)

    components = [p for p in (hf_pct, vhf_pct) if p is not None]
    global_pct = round(sum(components) / len(components)) if components else None

    return {
        "global_pct": global_pct,
        "hf_pct": hf_pct,
        "vhf_pct": vhf_pct,
        "hf_level": correlation.get("level"),
        "hf_level_label_fr": correlation.get("level_label_fr"),
        "note": "Indice heuristique, pas une mesure physique calibrée.",
    }

def get_band_activity_24h():
    """Nombre de spots reçus par bande sur 24h, séparés HF/VHF+, depuis
    spot_history. Base l'affichage du pavé 'Activité par bande'."""
    cutoff = time.time() - 86400
    counts = Counter()
    with spot_history_lock:
        for entry in spot_history:
            if entry.get("ts", 0) >= cutoff and entry.get("band"):
                counts[entry["band"]] += 1

    hf_order = ["160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m", "12m", "10m"]
    vhf_order = ["6m", "4m", "2m", "70cm", "23cm"]

    hf = [{"band": b, "count": counts.get(b, 0)} for b in hf_order if counts.get(b, 0) > 0]
    vhf = [{"band": b, "count": counts.get(b, 0)} for b in vhf_order if counts.get(b, 0) > 0]
    return {"hf": hf, "vhf": vhf, "window_h": 24, "truncated": len(spot_history) >= SPOT_HISTORY_MAX}

# ══════════════════════════════════════════════════════════════════════════
# BALISES VHF/UHF/SHF — pavé "Balises" de la page météo
#
# Deux sources volontairement séparées, jamais mélangées :
#
#   A) RÉFÉRENCE AUTO-MISE À JOUR depuis dl0tud.tu-dresden.de (base de
#      rapports de réception, gérée par DJ5CW / Fabian Kurz, TU Dresden).
#      Mise à jour automatique une fois par mois. En cas d'échec, le dernier
#      fichier valide est conservé et un message apparaît dans l'interface.
#
#   B) CONFIRMATION RÉELLE via le flux DX cluster : si le callsign d'une
#      balise de la liste A est spotté par une station proche de ton QTH
#      (<300km), c'est une preuve réelle de propagation locale.
# ══════════════════════════════════════════════════════════════════════════

BEACON_REFERENCE_FILE   = Path("data/beacons_reference.json")
BEACON_REFERENCE_META   = Path("data/beacons_reference.meta.json")
BEACON_SOURCE_URL       = "https://dl0tud.tu-dresden.de/beacons/csv.php"
BEACON_SOURCE_LABEL     = "dl0tud.tu-dresden.de/beacons (DJ5CW, Fabian Kurz, TU Dresden)"
BEACON_UPDATE_INTERVAL  = 30 * 24 * 3600   # 30 jours
VHF_UHF_SHF_BEACON_BANDS = ["6m", "4m", "2m", "70cm", "23cm", "13cm",
                              "9cm", "6cm", "3cm", "12mm", "6mm", "4mm"]
BEACON_MAX_RANGE_KM = {
    "6m": 3000, "4m": 1500, "2m": 800, "70cm": 500,
    "23cm": 300, "13cm": 200, "9cm": 150, "6cm": 100,
    "3cm": 80, "12mm": 50, "6mm": 30, "4mm": 20,
}

beacon_update_status = {
    "last_attempt": None, "last_success": None, "count": 0,
    "source": BEACON_SOURCE_LABEL, "source_url": BEACON_SOURCE_URL,
    "error": None, "meta_file_date": None,
}
beacon_update_lock = threading.Lock()


def _parse_beacon_csv(text):
    """Parse le CSV de dl0tud.tu-dresden.de (séparateur ';').
    Colonnes : QRG;CALL;LOC;RST;RX IN;KM;DEG;RX BY;REM;DATE
    QRG=fréquence MHz, CALL=indicatif balise, LOC=locator balise,
    REM=remarques, DATE=date du dernier rapport reçu.
    Déduplique par CALL (entrée la plus récente), filtre QRT."""
    import csv, io, re as _re
    FREQ_BANDS = [
        (28.0,30.0,"10m"),(50.0,54.0,"6m"),(70.0,71.0,"4m"),
        (144.0,148.0,"2m"),(430.0,440.0,"70cm"),(1240.0,1300.0,"23cm"),
        (2300.0,2450.0,"13cm"),(3300.0,3500.0,"9cm"),(5650.0,5850.0,"6cm"),
        (10000.0,10500.0,"3cm"),(24000.0,24250.0,"12mm"),
        (47000.0,47200.0,"6mm"),(75500.0,81000.0,"4mm"),
    ]
    def freq_to_band(mhz):
        for lo, hi, band in FREQ_BANDS:
            if lo <= mhz <= hi:
                return band
        return None

    QRT_KW = ["qrt","license cancelled","not qrv","dismantled","off air",
               "switched off","permanently off","qrt for ever"]
    def is_qrt(r):
        return any(k in r.lower() for k in QRT_KW)

    reader = csv.reader(io.StringIO(text), delimiter=";")
    header = None
    by_call = {}
    for row in reader:
        if header is None:
            header = [h.strip().lower() for h in row]
            continue
        if len(row) < 3:
            continue
        def cell(n):
            try: return row[header.index(n)].strip()
            except: return ""
        call    = cell("call").upper().replace(" ","")
        qrg_raw = cell("qrg").replace(",",".")
        loc     = cell("loc").strip().upper()
        remark  = cell("rem")
        date_s  = cell("date")
        if not call or not qrg_raw or not loc: continue
        if is_qrt(remark): continue
        try: freq_mhz = float(qrg_raw)
        except: continue
        band = freq_to_band(freq_mhz)
        if band not in VHF_UHF_SHF_BEACON_BANDS: continue
        if not _re.match(r'^[A-R]{2}[0-9]{2}', loc): continue
        entry = {"call": call, "freq_mhz": round(freq_mhz, 4),
                 "band": band, "locator": loc[:6], "last_report": date_s}
        if call not in by_call or date_s > by_call[call]["last_report"]:
            by_call[call] = entry
    return sorted(by_call.values(), key=lambda b: (b["band"], b["freq_mhz"]))
def fetch_beacon_reference():
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with beacon_update_lock:
        beacon_update_status["last_attempt"] = now_iso
        beacon_update_status["error"] = None
    try:
        req = urllib.request.Request(
            BEACON_SOURCE_URL,
            headers={"User-Agent": BRIEFING_USER_AGENT, "Accept": "text/csv,*/*"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8", errors="ignore")
        beacons = _parse_beacon_csv(text)
        if len(beacons) < 10:
            raise ValueError(f"Seulement {len(beacons)} balises parsees — CSV suspect")
        BEACON_REFERENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
        BEACON_REFERENCE_FILE.write_text(
            json.dumps(beacons, ensure_ascii=False, indent=2), encoding="utf-8")
        meta = {"source": BEACON_SOURCE_LABEL, "source_url": BEACON_SOURCE_URL,
                "updated_at": now_iso, "count": len(beacons)}
        BEACON_REFERENCE_META.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        with beacon_update_lock:
            beacon_update_status.update({
                "last_success": now_iso, "count": len(beacons),
                "error": None, "meta_file_date": now_iso,
            })
        logger.info(f"BeaconUpdate: {len(beacons)} balises mises a jour depuis {BEACON_SOURCE_LABEL}")
    except Exception as e:
        msg = str(e)
        with beacon_update_lock:
            beacon_update_status["error"] = msg
        logger.warning(f"BeaconUpdate: echec MAJ balises ({msg}) — fichier local conserve")


def beacon_update_worker():
    threading.current_thread().name = "BeaconUpdateWorker"
    needs_immediate = True
    if BEACON_REFERENCE_META.exists():
        try:
            import datetime as _dt
            meta = json.loads(BEACON_REFERENCE_META.read_text(encoding="utf-8"))
            updated_at = meta.get("updated_at", "")
            if updated_at:
                last = _dt.datetime.strptime(updated_at, "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=_dt.timezone.utc)
                age_s = (_dt.datetime.now(_dt.timezone.utc) - last).total_seconds()
                if age_s < BEACON_UPDATE_INTERVAL:
                    needs_immediate = False
                    logger.info(
                        f"BeaconUpdateWorker: fichier local ok ({int(age_s/3600)}h), "
                        f"prochaine MAJ dans {int((BEACON_UPDATE_INTERVAL-age_s)/3600)}h"
                    )
                    with beacon_update_lock:
                        beacon_update_status["last_success"] = updated_at
                        beacon_update_status["count"] = meta.get("count", 0)
        except Exception:
            pass
    if needs_immediate:
        logger.info("BeaconUpdateWorker: MAJ initiale de la liste des balises")
        fetch_beacon_reference()
    while True:
        time.sleep(BEACON_UPDATE_INTERVAL)
        logger.info("BeaconUpdateWorker: MAJ mensuelle automatique de la liste des balises")
        fetch_beacon_reference()


def load_beacon_reference():
    if not BEACON_REFERENCE_FILE.exists():
        return []
    try:
        data = json.loads(BEACON_REFERENCE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"load_beacon_reference: fichier invalide ({e})")
        return []


def get_beacons_in_range():
    """Approche A : balises de la liste utilisateur théoriquement à portée
    du QTH (distance/direction calculées), triées par distance. Portée
    indicative par bande (BEACON_MAX_RANGE_KM) — large car VHF/UHF/SHF
    peuvent s'ouvrir très au-delà de la portée troposphérique habituelle
    (Es, tropo exceptionnel). Aucune confirmation de réception ici."""
    beacons = load_beacon_reference()
    if not beacons:
        return {"beacons": [], "info": BEACON_REFERENCE_INFO}

    results = []
    for b in beacons:
        try:
            call = b.get("call")
            band = b.get("band")
            locator = b.get("locator")
            if not (call and band and locator):
                continue
            b_lat, b_lon = qra_to_lat_lon(locator)
            if b_lat is None:
                continue
            dist_km = calculate_distance(user_lat, user_lon, b_lat, b_lon)
            bearing = calculate_bearing(user_lat, user_lon, b_lat, b_lon)
            max_range = BEACON_MAX_RANGE_KM.get(band, 1000)
            results.append({
                "call": call, "band": band, "freq_mhz": b.get("freq_mhz"),
                "locator": locator, "dist_km": round(dist_km, 0),
                "bearing_compass": bearing_to_compass(bearing),
                "in_typical_range": dist_km <= max_range,
            })
        except Exception:
            continue
    results.sort(key=lambda r: r["dist_km"])
    return {"beacons": results, "info": None}

def get_beacon_reception_events(window_min=180):
    """Balises VHF/UHF/SHF réellement spotées par des stations dans TON
    locator ou un locator adjacent (rayon effectif ~300km autour du QTH).
    Ne dépend PAS de la liste de référence — remonte tout spot VHF/UHF/SHF
    dont le spotter est proche de toi. Déduplique par callsign (meilleur
    événement = le plus récent)."""
    cutoff = time.time() - window_min * 60
    known_calls = {b.get("call", "").upper() for b in load_beacon_reference() if b.get("call")}
    seen = {}
    with spot_history_lock:
        for entry in spot_history:
            if entry.get("ts", 0) < cutoff:
                continue
            if entry.get("band") not in VHF_UHF_SHF_BEACON_BANDS:
                continue
            de_dist = entry.get("de_dist_km")
            if de_dist is None or de_dist > 300:
                continue
            call = (entry.get("dx") or "").upper()
            if not call:
                continue
            age_min = int((time.time() - entry.get("ts", time.time())) / 60)
            if call not in seen or age_min < seen[call]["age_min"]:
                seen[call] = {
                    "call": call, "band": entry.get("band"),
                    "mode": entry.get("mode"), "spotter": entry.get("de"),
                    "spotter_dist_km": round(de_dist, 0), "age_min": age_min,
                    "in_reference": call in known_calls,
                }
    events = sorted(seen.values(), key=lambda e: e["age_min"])
    info = None if events else "Aucune balise VHF/UHF/SHF spotée par une station à moins de 300km de ton QTH sur les 3 dernières heures."
    return {"events": events, "info": info}

def get_weather_alerts():
    """Alertes dérivées uniquement de données réellement mesurées — jamais
    de conditions fabriquées (pas d'inversion/ducting annoncée sans que
    l'indice tropo calculé ne la confirme réellement)."""
    alerts = []
    now = time.time()

    correlation = compute_noise_correlation()
    if correlation.get("level") in ("disturbed", "stormy"):
        alerts.append({
            "type": "storm", "icon": "⚡",
            "title": "QRN élevé" if correlation["level"] == "disturbed" else "QRN fort",
            "detail": "Impact possible sur le HF (bruit de fond)",
            "ts": now,
        })

    wspr_snap = wspr_cache.get("data")
    vhf_data = wspr_snap.get("vhf") if wspr_snap else None
    if vhf_data and vhf_data.get("total_spots", 0) >= 5:
        alerts.append({
            "type": "opening", "icon": "📡",
            "title": "Activité VHF détectée",
            "detail": f"{vhf_data['total_spots']} spots WSPR sur {vhf_data.get('dominant_band', 'VHF')} — ouverture possible",
            "ts": now,
        })

    weather = weather_cache.get("data") or {}
    if weather.get("ducting_risk") == "élevé":
        alerts.append({
            "type": "ducting", "icon": "🌫️",
            "title": "Ducting tropo probable",
            "detail": "Inversion de température détectée — conditions VHF/UHF potentiellement favorables",
            "ts": now,
        })

    pressure_trend = get_pressure_trend()
    if pressure_trend and pressure_trend.get("trend") == "falling" and pressure_trend.get("delta_hpa", 0) <= -4:
        alerts.append({
            "type": "pressure", "icon": "🔽",
            "title": "Baisse barométrique rapide",
            "detail": f"{pressure_trend['delta_hpa']} hPa/2h — dégradation météo possible",
            "ts": now,
        })

    return alerts

# ══════════════════════════════════════════════════════════════════════════
# FIN MODULE MÉTÉO
# ══════════════════════════════════════════════════════════════════════════




def cluster_spots(spots, max_dist_km=800):
    clusters = []

    for s in spots:
        placed = False
        for c in clusters:
            if geo_distance_km(s, c["center"]) <= max_dist_km:
                c["spots"].append(s)
                # recalcul centre
                c["center"]["lat"] = sum(x["lat"] for x in c["spots"]) / len(c["spots"])
                c["center"]["lon"] = sum(x["lon"] for x in c["spots"]) / len(c["spots"])
                placed = True
                break
        if not placed:
            clusters.append({
                "center": {"lat": s["lat"], "lon": s["lon"]},
                "spots": [s]
            })

    return clusters
# --- END SOLAR (XML) FETCHER ---


# --- CACHES GLOBAUX et INITIALISATION QTH ---
spots_buffer = deque(maxlen=6000)
# --- SPOT HISTORY (Tracking Watchlist) ---
SPOT_HISTORY_MAX = 20000
spot_history = deque(maxlen=SPOT_HISTORY_MAX)
spot_history_lock = threading.Lock()
# --- END SPOT HISTORY ---
band_history = {}
prefix_db = {}
ticker_info = {"text": "SYSTEM INITIALIZATION... (Waiting for RSS/Solar data)"}

# --- SOLAR CACHE (XML/JSON) ---
solar_lock = threading.Lock()
solar_cache = {"sfi": "N/A", "a": "N/A", "k": "N/A", "kp": None, "kp_time_utc": None, "kp_a_running": None, "kp_station_count": None, "ts_utc": None}
solar_xml_cache = "<?xml version=\"1.0\" encoding=\"UTF-8\"?><solar><sfi>N/A</sfi><a>N/A</a><k>N/A</k><kp></kp><kp_time_utc></kp_time_utc><updated_utc></updated_utc></solar>"
# --- END SOLAR CACHE ---
watchlist    = set()

# ── v10.0 : Predictor & NtfyAlerter ────────────────────────────────────────────
# v11 : cty_path branché sur CTY_FILE déjà utilisé par le reste de l'app
# pour la résolution DXCC (corrige l'ancien bug _extract_prefix()).
predictor = Predictor(db_path="data/predictor.sqlite", my_call=MY_CALL, cty_path=CTY_FILE)
alerter   = NtfyAlerter(db_path="data/ntfy_alerts.sqlite")
wl_activity  = {}        # {call_upper: timestamp_float} — dernier spot vu
wl_activity_lock = threading.Lock()
surge_bands = []
history_30min = {band: [0] * HISTORY_SLOTS for band in HISTORY_BANDS}
history_lock = threading.Lock()
surge_lock = threading.Lock()

# --- CONFIGURATION DU LOGGER ---
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
LOG_FORMAT = '%(asctime)s [%(levelname)s] %(threadName)s: %(message)s'
formatter = logging.Formatter(LOG_FORMAT, datefmt='%Y-%m-%d %H:%M:%S')
file_handler = TimedRotatingFileHandler(
    LOG_FILE,
    when='midnight',
    interval=1,
    backupCount=1,
    encoding='utf-8'
)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# --- FLASK APP INITIALIZATION ---
app = Flask(__name__, template_folder="templates")

# ── SÉCURITÉ v11 — Niveau 2 : jeton local sur les routes qui modifient un
# état (spot, watchlist, LoTW, config satellites, ntfy...). Pas un système
# d'auth complet — juste une protection basique puisque tout est ouvert
# sur le LAN sans aucune vérification aujourd'hui.
#
# Le jeton est généré automatiquement au premier démarrage et persisté
# dans data/api_token.txt (déjà gitignored via data/). Le frontend le lit
# une fois au chargement de la page (route /api/token, elle-même ouverte
# uniquement en local — voir garde ci-dessous) et l'envoie ensuite dans
# l'en-tête X-API-Token à chaque requête mutative.
import secrets as _secrets

API_TOKEN_FILE = Path("data/api_token.txt")


def _load_or_create_api_token() -> str:
    API_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    if API_TOKEN_FILE.exists():
        tok = API_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if tok:
            return tok
    tok = _secrets.token_hex(24)
    API_TOKEN_FILE.write_text(tok, encoding="utf-8")
    try:
        os.chmod(API_TOKEN_FILE, 0o600)
    except Exception:
        pass
    logger.info("Sécurité: nouveau jeton API généré (data/api_token.txt)")
    return tok


API_TOKEN = _load_or_create_api_token()


def require_api_token(fn):
    """
    Décorateur : exige l'en-tête X-API-Token sur les routes qui modifient
    un état. Le frontend servi par cette même app le connaît (voir
    /api/token) — seul un tiers extérieur au LAN sans accès à la page
    HTML ne pourra pas forger de requêtes.
    """
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        provided = request.headers.get("X-API-Token", "")
        if not _secrets.compare_digest(provided, API_TOKEN):
            return jsonify({"ok": False, "error": "Jeton API manquant ou invalide"}), 401
        return fn(*args, **kwargs)

    return wrapper


@app.route("/api/token")
def api_token():
    """
    Distribue le jeton au frontend. Ouvert sans jeton (poule/œuf), mais
    n'a de valeur que pour quelqu'un déjà capable de charger la page HTML
    de l'application — donc déjà sur le LAN autorisé.
    """
    return jsonify({"token": API_TOKEN})


# ── v11.3 — Panneau Setup ⚙ : configuration des pavés visibles/masqués ──────
# Persistée côté serveur (partagée entre tous les appareils qui accèdent à
# l'app), pas en localStorage (qui serait par-navigateur uniquement).
UI_CONFIG_FILE = Path("data/ui_config.json")


def _load_ui_config() -> dict:
    if UI_CONFIG_FILE.exists():
        try:
            return json.loads(UI_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


@app.route("/api/ui-config")
def api_ui_config_get():
    """Retourne la config actuelle : {panel_id: false} pour les pavés masqués uniquement."""
    return jsonify(_load_ui_config())


@app.route("/api/ui-config", methods=["POST"])
@require_api_token
def api_ui_config_set():
    """
    Met à jour la config. Corps attendu : {"panel_id": "ck-voacap", "visible": false}
    Un pavé absent du fichier = visible par défaut (pas besoin de tout lister).
    """
    data = request.get_json(silent=True) or {}
    panel_id = (data.get("panel_id") or "").strip()
    visible = data.get("visible", True)
    if not panel_id:
        return jsonify({"ok": False, "error": "panel_id requis"}), 400

    cfg = _load_ui_config()
    if visible:
        cfg.pop(panel_id, None)  # visible = valeur par défaut, pas la peine de stocker
    else:
        cfg[panel_id] = False

    try:
        UI_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        UI_CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({"ok": True, "config": cfg})


# --- PLAGES DE FREQUENCES CW ---
CW_RANGES = [
    ('160m', 1.810, 1.838), ('80m', 3.500, 3.560), ('40m', 7.000, 7.035),
    ('30m', 10.100, 10.134), ('20m', 14.000, 14.069), ('17m', 18.068, 18.095),
    ('15m', 21.000, 21.070), ('12m', 24.890, 24.913), ('10m', 28.000, 28.070),
]

# --- FRÉQUENCES FT4/FT8 (en kHz) ---
FT8_VHF_FREQ_RANGE_KHZ = (144171, 144177)

# --- FRÉQUENCES PSK31 (en kHz) ---
PSK31_HF_FREQ_RANGE_KHZ = (14070, 14071)


# --- SSL BYPASS ---
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

# --- FONCTIONS UTILITAIRES ---
def qra_to_lat_lon(qra):
    try:
        qra = qra.upper().strip()
        if len(qra) < 4:
            return None, None
        lon = -180 + (ord(qra[0]) - ord('A')) * 20
        lat = -90 + (ord(qra[1]) - ord('A')) * 10
        if len(qra) >= 4:
            lon += int(qra[2]) * 2
            lat += int(qra[3]) * 1
        if len(qra) >= 6:
            lon += (ord(qra[4]) - ord('A')) * (2/24) + (1/24)
            lat += (ord(qra[5]) - ord('A')) * (1/24) + (1/48)
        else:
            lon += 1
            lat += 0.5
        return lat, lon
    except Exception:
        return None, None

# Initialisation du QTH utilisateur
initial_lat, initial_lon = qra_to_lat_lon(DEFAULT_QRA)
user_qra = DEFAULT_QRA
user_lat = initial_lat if initial_lat is not None else 43.10
user_lon = initial_lon if initial_lon is not None else 5.88

def is_meteor_shower_active():
    now = time.gmtime(time.time())
    current_month = now.tm_mon
    current_day = now.tm_mday
    for shower in METEOR_SHOWERS:
        start_m, start_d = shower["start"]
        end_m, end_d = shower["end"]
        if start_m > end_m:
            if (current_month == start_m and current_day >= start_d) or \
               (current_month == end_m and current_day <= end_d) or \
               (start_m == 12 and current_month == 1):
                return True, shower["name"]
        else:
            if (start_m == current_month and current_day >= start_d) or \
               (end_m == current_month and current_day <= end_d) or \
               (start_m < current_month < end_m):
                return True, shower["name"]
    return False, None

# --- Watchlist ---
def load_wl_activity():
    """Charge l'historique d'activité de la watchlist depuis le disque.
    Format v2: {call: {last_spot, end_date, added}} ou ancien format {call: float}
    """
    global wl_activity
    try:
        if WL_ACTIVITY_FILE.exists():
            with open(WL_ACTIVITY_FILE, "r") as f:
                data = json.load(f)
            migrated = {}
            for k, v in data.items():
                call = k.upper()
                if isinstance(v, (int, float)):
                    # Ancien format — migrer
                    migrated[call] = {"last_spot": float(v), "end_date": None, "added": float(v)}
                elif isinstance(v, dict):
                    migrated[call] = v
            with wl_activity_lock:
                wl_activity = migrated
            logger.info(f"WL activity chargée: {len(wl_activity)} calls")
    except Exception as e:
        logger.warning(f"Impossible de charger wl_activity: {e}")


def save_wl_activity():
    """Sauvegarde l'historique d'activité de la watchlist sur le disque."""
    try:
        WL_ACTIVITY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with wl_activity_lock:
            data = dict(wl_activity)
        with open(WL_ACTIVITY_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.warning(f"Impossible de sauvegarder wl_activity: {e}")


def load_watchlist():
    global watchlist
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, "r") as f:
                data = json.load(f)
                watchlist = set([c.upper() for c in data if isinstance(c, str)])
            logger.info(f"Watchlist chargée: {len(watchlist)} indicatifs.")
        except Exception as e:
            logger.error(f"Impossible de charger la Watchlist, elle sera réinitialisée: {e}")
            watchlist = set()

def save_watchlist():
    try:
        with open(WATCHLIST_FILE, "w") as f:
            json.dump(sorted(list(watchlist)), f, indent=2)
        logger.info(f"Watchlist sauvegardée avec {len(watchlist)} indicatifs.")
        save_wl_activity()   # sync l'activité avec la nouvelle watchlist
    except Exception as e:
        logger.error(f"Impossible de sauvegarder la Watchlist: {e}")

# --- SURGE & HISTORY ---
def record_surge_data(band):
    if band not in band_history:
        band_history[band] = deque()
    band_history[band].append(time.time())

    if band in HISTORY_BANDS:
        now_utc = time.gmtime(time.time())
        current_slot = ((now_utc.tm_hour * 2) + (now_utc.tm_min // 30)) % HISTORY_SLOTS
        with history_lock:
            history_30min[band][current_slot] += 1

    if band in VHF_BANDS:
        logger.debug(f"VHF Spot recorded for band {band}.")

def analyze_surges():
    global surge_bands
    current_time = time.time()
    active_surges = []

    recent_ms_spots_count = sum(1 for s in spots_buffer
                              if s.get('mode') == 'MSK144' and (current_time - s['timestamp']) < 900)
    is_active, shower_name = is_meteor_shower_active()
    ms_surge_name = f"MSK144: {shower_name}" if is_active else "MSK144: Inactive"

    with surge_lock:
        if is_active and recent_ms_spots_count >= MIN_SPOTS_FOR_SURGE:
            if ms_surge_name not in surge_bands:
                surge_bands.append(ms_surge_name)
            active_surges.append(ms_surge_name)
        elif ms_surge_name in surge_bands:
            surge_bands.remove(ms_surge_name)

        bands_in_surge = [s for s in surge_bands if not s.startswith("MSK144:")]

        for band in HF_BANDS + [b for b in VHF_BANDS if b != 'QO-100']:
            # Seuil adaptatif : 2m nécessite plus de spots pour éviter
            # les faux positifs (activité locale permanente sur 2m).
            # Une vraie ouverture Es génère 15+ spots/min — seuil élevé
            # = seules les vraies ouvertures déclenchent l'alerte.
            band_threshold = SURGE_THRESHOLD * 2.0 if band == '2m' else SURGE_THRESHOLD
            band_min_spots = max(MIN_SPOTS_FOR_SURGE, 8) if band == '2m' else MIN_SPOTS_FOR_SURGE
            timestamps = band_history.get(band, deque())

            while timestamps and timestamps[0] < current_time - SURGE_WINDOW:
                timestamps.popleft()

            count_total = len(timestamps)
            if count_total < MIN_SPOTS_FOR_SURGE:
                continue

            avg_rate = count_total / (SURGE_WINDOW / 60.0)
            recent_count = sum(1 for t in timestamps if t > current_time - 60)

            is_surging = (recent_count > (avg_rate * band_threshold)) and (recent_count >= band_min_spots)

            if is_surging:
                if band not in bands_in_surge:
                    logger.info(f"ALERTE SURGE {band}: Détectée ({recent_count} spots / min)")
                    surge_bands.append(band)
                if band not in active_surges:
                    active_surges.append(band)
                # ── v10.0 : alerte 6m via ntfy ───────────────────────────
                if band == "6m":
                    try:
                        _recent_6m = sum(1 for t in timestamps if t > time.time() - 600)
                        _top_calls = [s.get("dx_call","") for s in list(spots_buffer)[-20:]
                                      if s.get("band") == "6m"][:5]
                        alerter.on_6m_surge(_recent_6m, _top_calls)
                    except Exception:
                        pass
            elif band in bands_in_surge:
                surge_bands.remove(band)
                logger.info(f"FIN ALERTE SURGE {band}: L'activité a diminué.")
    return active_surges

# --- MOTEUR DRSE ---
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def calculate_spd_score(call, band, mode, comment, country, dist_km):
    score = 10
    call = call.upper()
    comment = (comment or "").upper()
    for p in RARE_PREFIXES:
        if call.startswith(p):
            score += 65
            break

    if 'UP' in comment or 'SPLIT' in comment:
        score += 15
    if 'DX' in comment:
        score += 5
    if 'QRZ' in comment:
        score -= 10
    if 'PIRATE' in comment:
        score = 0
    if mode == 'CW':
        score += 10

    if dist_km and dist_km > 1000:
        distance_bonus = min(20, 20 * math.log10(dist_km / 1000))
        score += distance_bonus

    if band == 'QO-100':
        score += 40
    elif band in VHF_BANDS:
        score += 30

    if band in ['10m', '12m', '15m']:
        score += 15

    return min(int(score), 100)

def is_rare_prefix(call: str) -> bool:
    """True si l'indicatif commence par un préfixe explicitement déclaré rare."""
    c = (call or "").upper().strip()
    for p in RARE_PREFIXES:
        if c.startswith(p):
            return True
    return False

def find_band(freq_khz):
    if 1800 <= freq_khz <= 2000:
        return "160m"
    if 3500 <= freq_khz <= 3800:
        return "80m"
    if 5300 <= freq_khz <= 5450:
        return "60m"
    if 7000 <= freq_khz <= 7300:
        return "40m"
    if 10100 <= freq_khz <= 10150:
        return "30m"
    if 14000 <= freq_khz <= 14350:
        return "20m"
    if 18068 <= freq_khz <= 18168:
        return "17m"
    if 21000 <= freq_khz <= 21450:
        return "15m"
    if 24890 <= freq_khz <= 24990:
        return "12m"
    if 28000 <= freq_khz <= 29700:
        return "10m"
    if 50000 <= freq_khz <= 54000:
        return "6m"
    if 70000 <= freq_khz <= 70500:
        return "4m"
    if 144000 <= freq_khz <= 146000:
        return "2m"
    if 430000 <= freq_khz <= 440000:
        return "70cm"
    if 1240000 <= freq_khz <= 1300000:
        return "23cm"
    if 10489000 <= freq_khz <= 10499000:
        return "QO-100"
    return "Unknown"


def get_band_and_mode_smart(freq_float, comment):
    comment = (comment or "").upper()
    f = float(freq_float)

    if f < 1000:
        f = f * 1000.0
    elif f > 20000000:
        f = f / 1000.0

    freq_khz = f

    band = find_band(freq_khz)
    f_mhz = freq_khz / 1000.0

    mode = "SSB"

    # -----------------------------
    # INITIALISATION
    # -----------------------------
    TOLERANCE_KHZ = 0.2

    is_ft2_hf = False
    is_ft4_hf = False
    is_ft4_vhf = False
    is_ft8_vhf = False

    # -----------------------------
    # FT2 HF
    # -----------------------------
    FT2_HF_FREQS_KHZ = [14082]
    is_ft2_hf = any(
        abs(freq_khz - ft2_f) <= TOLERANCE_KHZ
        for ft2_f in FT2_HF_FREQS_KHZ
    )

    # -----------------------------
    # FT4 HF
    # -----------------------------
    FT4_HF_FREQS_KHZ = [7047, 10140, 14080, 18104, 21180, 24919, 28180]

    is_ft4_hf = any(
        abs(freq_khz - ft4_f) <= TOLERANCE_KHZ
        for ft4_f in FT4_HF_FREQS_KHZ
    )

    # FT4 VHF
    FT4_VHF_FREQ_KHZ = 144170
    is_ft4_vhf = (
        band == "2m" and
        abs(freq_khz - FT4_VHF_FREQ_KHZ) <= TOLERANCE_KHZ
    )

    # FT8 VHF
    ft8_vhf_min, ft8_vhf_max = FT8_VHF_FREQ_RANGE_KHZ
    is_ft8_vhf = (
        band == "2m" and
        ft8_vhf_min <= freq_khz <= ft8_vhf_max
    )

    # FT8 6m (50.313 MHz)
    is_ft8_6m = (band == "6m" and abs(freq_khz - 50313) <= 5)

    # FT4 6m (50.318 MHz)
    is_ft4_6m = (band == "6m" and abs(freq_khz - 50318) <= 2)

    # FT8 HF — fréquences standard + expéditions DX (v9.5)
    FT8_HF_FREQS_KHZ = [
        3573, 5357, 7074, 10136,
        14074, 14090,   # 20m standard + expéditions
        18100, 18095,   # 17m standard + expéditions
        21074, 24915, 28074,
    ]
    is_ft8_hf = any(abs(freq_khz - f) <= 1.0 for f in FT8_HF_FREQS_KHZ)

    # PSK31 20m (14.070 MHz — juste au-dessus du segment CW)
    psk31_min, psk31_max = PSK31_HF_FREQ_RANGE_KHZ
    is_psk31 = (band == "20m" and psk31_min <= freq_khz <= psk31_max)

    # PRIORITE
    if is_ft2_hf:
        mode = "FT2"
    elif is_ft4_hf or is_ft4_vhf or is_ft4_6m:
        mode = "FT4"
    elif is_ft8_vhf or is_ft8_6m or is_ft8_hf:
        mode = "FT8"
    elif is_psk31:
        mode = "PSK31"

    # CW
    if mode == "SSB":
        for cw_band, min_mhz, max_mhz in CW_RANGES:
            if cw_band == band and min_mhz <= f_mhz <= max_mhz:
                mode = "CW"
                break

    # MSK144
    if band == "2m" and MSK144_RANGE_KHZ[0] <= freq_khz <= MSK144_RANGE_KHZ[1]:
        mode = "MSK144"

    # OVERRIDE COMMENT
    if "FT2" in comment:
        mode = "FT2"
    elif "FT4" in comment:
        mode = "FT4"
    elif "FT8" in comment:
        mode = "FT8"
    elif "CW" in comment and mode == "SSB":
        mode = "CW"
    elif "FM" in comment:
        mode = "FM"
    elif "RTTY" in comment:
        mode = "RTTY"
    elif "PSK31" in comment or "PSK-31" in comment:
        mode = "PSK31"
    elif "SSTV" in comment or abs(freq_khz - 14230) <= 2:
        mode = "SSTV"

    return band, mode

def load_cty_dat(force_download: bool = False):
    """Charge cty.dat (DXCC/prefixes). Télécharge si absent (ou si force_download=True).
    NOTE: certains miroirs renvoient 406 sans header Accept -> on force Accept: */*.
    """
    global prefix_db

    def download_cty() -> bool:
        try:
            logger.info("Tentative de téléchargement de cty.dat...")
            headers = {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
                "Accept": "*/*",
            }
            req = urllib.request.Request(CTY_URL, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r, open(CTY_FILE, "wb") as f:
                f.write(r.read())
            # petit garde-fou: fichier trop petit = téléchargement foireux
            if os.path.exists(CTY_FILE) and os.path.getsize(CTY_FILE) < 50_000:
                logger.warning("cty.dat téléchargé mais taille suspecte (<50KB).")
            logger.info("Téléchargement de cty.dat réussi.")
            return True
        except Exception as e:
            logger.error(f"Échec du téléchargement de cty.dat. Vérifie l'URL ou la connexion: {e}")
            return False

    # Télécharger si absent, si demandé, ou si fichier vide/suspect
    if force_download or (not os.path.exists(CTY_FILE)) or (os.path.exists(CTY_FILE) and os.path.getsize(CTY_FILE) < 50_000):
        if not download_cty():
            return

    try:
        logger.info("Chargement de la base de données DXCC (cty.dat).")
        prefix_db.clear()
        with open(CTY_FILE, "rb") as f:
            raw = f.read().decode("latin-1", errors="ignore")

        for rec in raw.replace("\r", "").replace("\n", " ").split(";"):
            if ":" in rec:
                p = rec.split(":")
                country = p[0].strip()
                try:
                    lat, lon = float(p[4]), float(p[5]) * -1
                except Exception:
                    lat, lon = 0.0, 0.0
                try:
                    dxcc_num = int(p[2].strip())
                except Exception:
                    dxcc_num = 0

                prefixes = p[7].strip().split(",")
                if len(p) > 8:
                    prefixes += p[8].strip().split(",")

                for px in prefixes:
                    clean = px.split("(")[0].split("[")[0].strip().lstrip("=")
                    if clean:
                        prefix_db[clean] = {"c": country, "lat": lat, "lon": lon, "dxcc_num": dxcc_num}

        if not prefix_db:
            # si parsing vide, on retente un download "propre"
            logger.warning("prefix_db vide après parsing cty.dat -> re-téléchargement et retry.")
            if download_cty():
                return load_cty_dat(force_download=False)

        logger.info(f"Base de données DXCC chargée: {len(prefix_db)} préfixes.")
    except Exception as e:
        logger.error(f"Erreur lors du parsing de cty.dat: {e}")


# ═══════════════════════════════════════════════════════
# GÉOLOCALISATION FINE v9.5
# Résolution par zone d'appel + jitter déterministe
# ═══════════════════════════════════════════════════════

# Zones d'appel précises (Option B)
# Format: préfixe_regex → (lat, lon, description)
CALLSIGN_ZONES = {
    # USA — zones d'appel W/K (1=NE, 2=NY/NJ, 3=Mid-Atl, 4=SE, 5=SC,
    #        6=Calif, 7=NW, 8=Ohio, 9=Midwest, 0=Plains)
    'W1': (42.5, -71.5, 'New England'),
    'K1': (42.5, -71.5, 'New England'),
    'W2': (40.7, -74.0, 'New York/NJ'),
    'K2': (40.7, -74.0, 'New York/NJ'),
    'W3': (39.9, -75.2, 'Mid-Atlantic'),
    'K3': (39.9, -75.2, 'Mid-Atlantic'),
    'W4': (33.5, -84.4, 'Southeast'),
    'K4': (33.5, -84.4, 'Southeast'),
    'W5': (30.3, -97.7, 'South Central'),
    'K5': (30.3, -97.7, 'South Central'),
    'W6': (36.7, -119.8, 'California'),
    'K6': (36.7, -119.8, 'California'),
    'W7': (46.5, -120.5, 'Northwest'),
    'K7': (46.5, -120.5, 'Northwest'),
    'W8': (41.5, -82.5, 'Ohio Valley'),
    'K8': (41.5, -82.5, 'Ohio Valley'),
    'W9': (41.8, -87.6, 'Midwest'),
    'K9': (41.8, -87.6, 'Midwest'),
    'W0': (38.5, -98.0, 'Plains'),
    'K0': (38.5, -98.0, 'Plains'),
    'N1': (42.5, -71.5, 'New England'),
    'N2': (40.7, -74.0, 'New York/NJ'),
    'N3': (39.9, -75.2, 'Mid-Atlantic'),
    'N4': (33.5, -84.4, 'Southeast'),
    'N5': (30.3, -97.7, 'South Central'),
    'N6': (36.7, -119.8, 'California'),
    'N7': (46.5, -120.5, 'Northwest'),
    'N8': (41.5, -82.5, 'Ohio Valley'),
    'N9': (41.8, -87.6, 'Midwest'),
    'N0': (38.5, -98.0, 'Plains'),
    'AA': (37.6, -91.9, 'USA'),   # préfixes AA-AK génériques
    'AB': (37.6, -91.9, 'USA'),
    'AC': (37.6, -91.9, 'USA'),
    'AD': (37.6, -91.9, 'USA'),
    'AE': (37.6, -91.9, 'USA'),
    'AF': (37.6, -91.9, 'USA'),
    'AG': (37.6, -91.9, 'USA'),
    'AH': (37.6, -91.9, 'USA'),
    'AI': (37.6, -91.9, 'USA'),
    'AJ': (37.6, -91.9, 'USA'),
    'AK': (37.6, -91.9, 'USA'),
    # Canada — VE/VA zones
    'VE1': (44.6, -63.6, 'Nova Scotia'),
    'VA1': (44.6, -63.6, 'Nova Scotia'),
    'VE2': (46.8, -71.2, 'Quebec'),
    'VA2': (46.8, -71.2, 'Quebec'),
    'VE3': (43.7, -79.4, 'Ontario'),
    'VA3': (43.7, -79.4, 'Ontario'),
    'VE4': (49.9, -97.1, 'Manitoba'),
    'VA4': (49.9, -97.1, 'Manitoba'),
    'VE5': (52.1, -106.7, 'Saskatchewan'),
    'VA5': (52.1, -106.7, 'Saskatchewan'),
    'VE6': (53.5, -113.5, 'Alberta'),
    'VA6': (53.5, -113.5, 'Alberta'),
    'VE7': (49.3, -123.1, 'British Columbia'),
    'VA7': (49.3, -123.1, 'British Columbia'),
    # Japon — JA districts
    'JA1': (35.7, 139.7, 'Kanto'),
    'JA2': (35.2, 137.0, 'Tokai'),
    'JA3': (34.7, 135.5, 'Kinki'),
    'JA4': (34.4, 132.5, 'Chugoku'),
    'JA5': (33.8, 132.8, 'Shikoku'),
    'JA6': (33.6, 130.4, 'Kyushu'),
    'JA7': (38.3, 140.9, 'Tohoku'),
    'JA8': (43.1, 141.3, 'Hokkaido'),
    'JA9': (36.6, 136.6, 'Hokuriku'),
    'JA0': (37.2, 138.2, 'Shinetsu'),
    # Russie — régions callsign
    'UA1': (59.9, 30.3, 'St Petersburg'),
    'RA1': (59.9, 30.3, 'St Petersburg'),
    'UA3': (55.7, 37.6, 'Moscow'),
    'RA3': (55.7, 37.6, 'Moscow'),
    'UA4': (53.2, 50.2, 'Volga'),
    'UA6': (45.0, 41.0, 'Caucasus'),
    'UA9': (61.0, 68.0, 'Siberia W'),
    'RA9': (61.0, 68.0, 'Siberia W'),
    'UA0': (57.0, 105.0, 'Siberia E'),
    'RA0': (57.0, 105.0, 'Siberia E'),
    # Australie — VK districts
    'VK1': (-35.3, 149.1, 'ACT'),
    'VK2': (-33.9, 151.2, 'NSW'),
    'VK3': (-37.8, 145.0, 'Victoria'),
    'VK4': (-27.5, 153.0, 'Queensland'),
    'VK5': (-34.9, 138.6, 'S Australia'),
    'VK6': (-32.0, 115.9, 'W Australia'),
    'VK7': (-42.9, 147.3, 'Tasmania'),
    # Allemagne — districts DA-DL
    'DL1': (52.5, 13.4, 'Berlin area'),
    'DL2': (48.1, 11.6, 'Bavaria'),
    'DL3': (53.6, 10.0, 'Hamburg'),
    'DL4': (51.0,  7.0, 'NRW'),
    'DL5': (49.5,  8.5, 'Rhineland'),
    'DL6': (50.0, 12.0, 'Saxony'),
    'DL7': (52.5, 13.4, 'Berlin'),
    'DL8': (51.5,  7.5, 'Westphalia'),
    'DL9': (48.5,  9.0, 'Baden-Württemberg'),
    # Espagne
    'EA1': (43.4,  -4.0, 'N Spain'),
    'EA2': (42.8,  -1.6, 'Navarre'),
    'EA3': (41.4,   2.2, 'Catalonia'),
    'EA4': (40.4,  -3.7, 'Madrid'),
    'EA5': (39.5,  -0.4, 'Valencia'),
    'EA6': (39.6,   2.9, 'Balearic'),
    'EA7': (37.4,  -6.0, 'Andalusia'),
    'EA8': (28.1, -15.4, 'Canary Is'),
    # France
    'F1': (46.0, 2.0, 'France'),
    'F4': (46.0, 2.0, 'France'),
    'F5': (46.0, 2.0, 'France'),
    'F6': (46.0, 2.0, 'France'),
    'F8': (46.0, 2.0, 'France'),
    # Italie
    'I1': (44.4,  8.9, 'Liguria'),
    'I2': (45.5,  9.2, 'Lombardy'),
    'I3': (45.4, 12.3, 'Veneto'),
    'I4': (44.5, 11.3, 'Emilia'),
    'I5': (43.8, 11.2, 'Tuscany'),
    'I6': (42.4, 14.2, 'Abruzzo'),
    'I7': (40.8, 17.2, 'Apulia'),
    'I8': (40.8, 14.3, 'Campania'),
    'I9': (38.1, 15.7, 'Calabria'),
    'IK': (44.5, 11.0, 'Italy'),
    'IZ': (44.5, 11.0, 'Italy'),
    'IU': (44.5, 11.0, 'Italy'),
    'IW': (44.5, 11.0, 'Italy'),
}


def _callsign_jitter(call, lat, lon):
    """Ajoute un jitter déterministe basé sur le callsign.
    Même call = même offset. Pays différents dans un même pays = positions légèrement différentes.
    Max ±1.5° (≈ 165km), invisibles sur une vue mondiale mais séparent les clusters.
    """
    import hashlib
    h = int(hashlib.md5(call.upper().encode()).hexdigest()[:8], 16)
    # Deux offsets indépendants dans [-1.5, +1.5]
    dlat = ((h & 0xFFFF) / 65535.0 - 0.5) * 3.0
    dlon = ((h >> 16 & 0xFFFF) / 65535.0 - 0.5) * 3.0
    return round(lat + dlat, 4), round(lon + dlon, 4)


def get_precise_latlon(call):
    """Retourne (lat, lon, precise) pour un callsign.
    precise=True si on a une zone fine, False si centroïde pays avec jitter.
    Ordre de priorité :
      1. Préfixe 3 chars dans CALLSIGN_ZONES (VE3, JA1, DL9…)
      2. Préfixe 2 chars dans CALLSIGN_ZONES (W6, K7, N4…)
      3. Pour les indicatifs US (K/W/N/A + chiffre quelconque) : zone par le chiffre
      4. Centroïde pays + jitter déterministe
    """
    import re as _re
    call = call.upper().strip()
    base = call.split('/')[0]

    # 1 & 2. Chercher par préfixe 3 puis 2 chars
    for length in (3, 2):
        prefix = base[:length]
        if prefix in CALLSIGN_ZONES:
            lat, lon, _ = CALLSIGN_ZONES[prefix]
            lat, lon = _callsign_jitter(call, lat, lon)
            return lat, lon, True

    # 3. Indicatifs USA : extraire le chiffre de zone (ex: KF6I → 6 → W6/K6)
    if base and base[0] in ('K', 'W', 'N', 'A'):
        m = _re.search(r'(\d)', base)
        if m:
            digit = m.group(1)
            for pfx in ('K' + digit, 'W' + digit, 'N' + digit):
                if pfx in CALLSIGN_ZONES:
                    lat, lon, _ = CALLSIGN_ZONES[pfx]
                    lat, lon = _callsign_jitter(call, lat, lon)
                    return lat, lon, True

    # 4. Fallback : centroïde pays + jitter
    info = get_country_info(call)
    lat  = info.get('lat', 0.0)
    lon  = info.get('lon', 0.0)
    if lat or lon:
        lat, lon = _callsign_jitter(call, lat, lon)
    return lat, lon, False


def get_country_info(call):
    call = call.upper()
    best = {'c': 'Unknown', 'lat': 0.0, 'lon': 0.0, 'dxcc_num': 0}
    longest = 0
    candidates = [call]
    if '/' in call:
        candidates.append(call.split('/')[-1])
        candidates.append(call.split('/')[0])
    for c in candidates:
        for i in range(len(c), 0, -1):
            sub = c[:i]
            if sub in prefix_db and len(sub) > longest:
                longest = len(sub)
                best = prefix_db[sub]
    return best

# --- WORKERS ---
def history_maintenance_worker():
    """Tâche de maintenance pour décaler l'historique 30min/12h à chaque période."""
    threading.current_thread().name = 'HistoryWorker'
    logger.info("HistoryWorker démarré (30min/12h).")
    while True:
        now_utc = time.gmtime(time.time())
        current_minute = now_utc.tm_min
        current_hour = now_utc.tm_hour
        minutes_until_next_slot = (30 - (current_minute % 30)) % 30
        seconds_until_next_slot = minutes_until_next_slot * 60 - now_utc.tm_sec

        # Correction : on s'assure que le temps est toujours positif
        if seconds_until_next_slot < 0:
            seconds_until_next_slot = 0

        logger.debug(f"Prochaine rotation dans {seconds_until_next_slot} secondes.")
        time.sleep(seconds_until_next_slot + 5)
        save_wl_activity()   # persister l'activité watchlist toutes les 30 min
        try: predictor.cleanup_old_data(90)
        except Exception: pass
        # v11 : vérifier les prédictions échues contre les spots réels reçus
        # — alimente la fiabilité mesurée affichée dans le panel cockpit.
        try: predictor.verify_predictions()
        except Exception as e: logger.debug(f"predictor.verify_predictions: {e}")

        with history_lock:
            for band in HISTORY_BANDS:
                history_30min[band].pop(0)
                history_30min[band].append(0)
            logger.info(f"HISTORY 30min: Rotation des slots (nouveau slot pour {current_hour:02d}:{current_minute:02d} UTC).")

def ticker_worker():
    """Tâche pour mettre à jour le message défilant avec les infos solaires et RSS."""
    threading.current_thread().name = 'TickerWorker'
    logger.info("TickerWorker démarré.")
    while True:
        msgs = [f"SYSTEM ONLINE - {MY_CALL} ({APP_VERSION})"]

        try:
            req = urllib.request.Request(SOLAR_URL, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as r:
                l = [x for x in r.read().decode('utf-8').split('\n') if x and not x.startswith((':','#'))]
                if l:
                    solar_data = l[-1].split()
                    try:
                        a_index = solar_data.index('A-Index:') + 1
                        k_index = solar_data.index('K-Index:') + 1
                        A = solar_data[a_index] if a_index < len(solar_data) else 'N/A'
                        K = solar_data[k_index] if k_index < len(solar_data) else 'N/A'
                        msgs.append(f"SOLAR: A-Index: {A} | K-Index: {K}")
                    except ValueError:
                        msgs.append(f"SOLAR: {l[-1]}")
                else:
                    msgs.append("SOLAR: Data empty.")
        except Exception as e:
            logger.error(f"Erreur de récupération des données solaires: {e}")
            msgs.append("SOLAR: Data retrieval failed.")

        try:
            feed = feedparser.parse(RSS_URLS[0])
            if feed.entries:
                news = [entry.title for entry in feed.entries[:5]]
                msgs.append("NEWS: " + " | ".join(news))
            else:
                msgs.append("NEWS: RSS feed empty.")
        except Exception as e:
            logger.error(f"Erreur de récupération du flux RSS: {e}")
            msgs.append("NEWS: RSS retrieval failed.")

        ticker_info["text"] = "   +++   ".join(msgs)
        logger.info(f"Ticker mis à jour.")
        time.sleep(1800)

def _socket_readline(sock, timeout=2):
    """Lit une ligne complète depuis un socket TCP, avec timeout. Retourne str ou lève exception."""
    sock.settimeout(timeout)
    buf = b""
    while True:
        chunk = sock.recv(1024)
        if not chunk:
            raise EOFError("Connexion fermée par le cluster")
        buf += chunk
        if b"\n" in buf:
            line, _, _ = buf.partition(b"\n")
            return line.decode('ascii', errors='ignore').strip()


def _socket_send(sock, text):
    """Envoie une ligne texte sur le socket."""
    sock.sendall(text.encode('latin-1', errors='ignore'))


def telnet_worker():
    """Tâche pour se connecter et écouter le DX Cluster (socket TCP brut, sans telnetlib)."""
    threading.current_thread().name = 'TelnetWorker'
    logger.info("TelnetWorker démarré.")
    idx = 0
    while True:
        host, port = CLUSTERS[idx]
        logger.info(f"Tentative de connexion au Cluster: {host}:{port} ({idx + 1}/{len(CLUSTERS)})")
        tn = None
        try:
            tn = socket.create_connection((host, port), timeout=10)
            # Expose current connection for TX (spotting)
            global tn_current
            with tn_lock:
                tn_current = tn

            # Attente prompt login (best-effort, pas bloquant)
            try:
                _socket_readline(tn, timeout=3)
            except Exception:
                pass

            _socket_send(tn, MY_CALL + "\n")
            time.sleep(1)
            _socket_send(tn, "set/dx/filter\n")
            _socket_send(tn, "show/dx 50\n")
            logger.info(f"Connexion établie sur {host}:{port}. Écoute des spots en cours.")
            last_ping = time.time()

            while True:
                try:
                    line = _socket_readline(tn, timeout=2)
                except EOFError:
                    logger.info(f"Cluster {host} a fermé la connexion (EOFError), failover en cours.")
                    break
                except socket.timeout:
                    line = ""
                except Exception as e:
                    logger.warning(f"Erreur de lecture socket: {e}")
                    line = ""

                if not line:
                    if time.time() - last_ping > KEEP_ALIVE:
                        _socket_send(tn, "\n")
                        last_ping = time.time()
                    analyze_surges()
                    continue

                if line.startswith("DX de"):
                    try:
                        content = line[line.find("DX de")+5:].strip()
                        parts = content.split()
                        if len(parts) < 3:
                            continue
                        de_call = parts[0].rstrip(':').upper()
                        freq_str = parts[1]
                        dx_call = parts[2].upper()
                        comment = " ".join(parts[3:]).upper()

                        try:
                            freq_raw = float(freq_str)
                        except:
                            continue
                        band, mode = get_band_and_mode_smart(freq_raw, comment)
                        info = get_country_info(dx_call)

                        # v9.5 — géolocalisation fine par zone d'appel + jitter
                        lat, lon, _geo_precise = get_precise_latlon(dx_call)
                        if not lat and not lon:
                            lat, lon = info['lat'], info['lon']
                        dist_km = 0.0
                        if lat != 0.0 and lon != 0.0:
                            dist_km = calculate_distance(user_lat, user_lon, lat, lon)

                        # Position du spotter (DE) — nécessaire pour savoir si CE spot a été
                        # fait par une station proche de notre propre QTH (cf. pavé Balises).
                        de_dist_km = None
                        try:
                            de_lat, de_lon, _de_precise = get_precise_latlon(de_call)
                            if not de_lat and not de_lon:
                                de_info = get_country_info(de_call)
                                de_lat, de_lon = de_info['lat'], de_info['lon']
                            if de_lat and de_lon:
                                de_dist_km = calculate_distance(user_lat, user_lon, de_lat, de_lon)
                        except Exception:
                            pass

                        spd_score = calculate_spd_score(dx_call, band, mode, comment, info['c'], dist_km)
                        color = BAND_COLORS.get(band, '#00f3ff')
                        
                        # Générer un spot_id unique pour le Path Optimizer
                        spot_id = f"{dx_call}-{int(time.time())}"

                        record_surge_data(band)

                        spot_obj = {
                            "timestamp": time.time(), "time": time.strftime("%H:%M"),
                            "freq": freq_str, "dx_call": dx_call, "de_call": de_call,
                            "de_dist_km": de_dist_km, "band": band, "mode": mode,
                            "country": info['c'], "lat": lat, "lon": lon,
                            "score": spd_score,
                            "is_wanted": spd_score >= SPD_THRESHOLD,
                            "is_rare": is_rare_prefix(dx_call),
                            "via_eme": ("EME" in comment),
                            "color": color,
                            "type": "VHF" if band in VHF_BANDS else "HF",
                            "distance_km": dist_km,
                            "spot_id": spot_id # Ajout de l'ID
                        }
                        spots_buffer.append(spot_obj)

                        # ── v10.0 : Predictor — collecte SQLite ─────────────
                        try:
                            _is_wl = spot_obj.get("dx_call","").upper() in watchlist
                            predictor.record_spot(spot_obj, is_watchlist=_is_wl)
                        except Exception as _pe:
                            logger.debug(f"predictor.record_spot: {_pe}")

                        # ── v10.0 : Alertes ntfy ───────────────────────────
                        try:
                            _dx_up = spot_obj.get("dx_call","").upper()
                            if _dx_up in watchlist:
                                alerter.on_watchlist_spot(spot_obj)
                            with lotw_lock:
                                _dxcc_by_band = lotw_data.get("dxcc_by_band", {})
                            _band = spot_obj.get("band","")
                            _cty  = spot_obj.get("country","")
                            _confirmed_on_band = _dxcc_by_band.get(_band, set())
                            if _cty and _cty != "Unknown" and _cty not in _confirmed_on_band:
                                alerter.on_new_dxcc(spot_obj, [_band])
                        except Exception as _ae:
                            logger.debug(f"alerter: {_ae}")

                        # Mettre à jour l'activité watchlist si le call est suivi
                        _dx = spot_obj.get("dx_call", "").upper()
                        if _dx and _dx in watchlist:
                            with wl_activity_lock:
                                entry = wl_activity.get(_dx, {})
                                if isinstance(entry, dict):
                                    entry["last_spot"] = spot_obj.get("timestamp", time.time())
                                else:
                                    entry = {"last_spot": spot_obj.get("timestamp", time.time()), "end_date": None, "added": time.time()}
                                wl_activity[_dx] = entry
                        # Tracking Watchlist: petit historique RAM (léger, filtrable)
                        try:
                            with spot_history_lock:
                                spot_history.append({
                                    "ts": spot_obj.get("timestamp", time.time()),
                                    "dx": spot_obj.get("dx_call"),
                                    "de": spot_obj.get("de_call"),
                                    "de_dist_km": spot_obj.get("de_dist_km"),
                                    "band": spot_obj.get("band"),
                                    "mode": spot_obj.get("mode"),
                                    "score": spd_score,
                                    "dxcc": info.get('c'),
                                    "dist_km": dist_km,
                                    # freq_khz best-effort (float) si possible
                                    "freq_khz": (float(str(spot_obj.get("freq")).replace(",", ".")) if spot_obj.get("freq") is not None else None),
                                })
                        except Exception:
                            pass
                        logger.info(f"SPOT: {dx_call} ({band}, {mode}) -> SPD: {spd_score} pts (Dist: {dist_km:.0f}km)")
                    except Exception as e:
                        logger.error(f"Erreur de traitement du spot '{line[:50]}...': {e}")

        except Exception as e:
            logger.error(f"ERREUR CRITIQUE Cluster {host}:{port}: {e}. Basculement vers un autre cluster.")
            time.sleep(10)
        finally:
            with tn_lock:
                if tn_current is tn:
                    tn_current = None
            if tn:
                try:
                    tn.close()
                except Exception:
                    pass

        idx = (idx + 1) % len(CLUSTERS)

# --- ROUTES ---
@app.route("/api/world/events")
def api_map_events():
    band = request.args.get("band")
    window_min = int(request.args.get("window", 60))

    now = time.time()
    recent = [
        s for s in spots_buffer
        if now - s["timestamp"] <= window_min * 60
        and s.get("lat") and s.get("lon")
        and (not band or s["band"] == band)
    ]

    clusters = cluster_spots(recent)

    events = []
    for c in clusters:
        spots = c["spots"]
        if len(spots) < 3:
            continue

        dxcc = set(s["country"] for s in spots if s.get("country"))
        distances = [s.get("distance_km", 0) for s in spots]

        event = {
            "band": spots[0]["band"],
            "center": c["center"],
            "spot_count": len(spots),
            "dxcc_count": len(dxcc),
            "max_distance_km": int(max(distances)),
            "calls": list({s["dx_call"] for s in spots})[:10],
            "score": int(
                len(spots) * 5
                + len(dxcc) * 15
                + max(distances) / 200
            )
        }

        events.append(event)

    events.sort(key=lambda e: e["score"], reverse=True)

    return jsonify({
        "ok": True,
        "count": len(events),
        "events": events[:10]
    })
@app.get("/api/meta/summary")
def api_meta_summary():
    if not META_SUMMARY.exists():
        return jsonify({"status": "no_summary"}), 404
    try:
        return jsonify(json.loads(META_SUMMARY.read_text(encoding="utf-8")))
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/')
def index():
    return render_template('index.html', version=APP_VERSION, my_call=MY_CALL,
                           hf_bands=HF_BANDS, vhf_bands=VHF_BANDS, band_colors=BAND_COLORS,
                           spd_threshold=SPD_THRESHOLD, user_qra=user_qra)

@app.route("/ai.html")
def ai_page():
    return render_template("ai.html")

@app.route("/map")
def map_page():
    return render_template("map.html", version=APP_VERSION, my_call=MY_CALL, user_qra=user_qra)

@app.route("/map.html")
def map_html_compat():
    return redirect(url_for("map_page"))

@app.route("/world")
def world_page():
    return render_template("world.html")

@app.route('/update_qra', methods=['POST'])
@require_api_token
def update_qra():
    global user_qra, user_lat, user_lon
    new_qra = request.form.get('qra_locator', '').upper().strip()
    if not new_qra:
        return redirect(url_for('index'))
    new_lat, new_lon = qra_to_lat_lon(new_qra)
    valid = new_lat is not None and new_lon is not None
    if valid:
        user_qra = new_qra
        user_lat = new_lat
        user_lon = new_lon
        save_user_config()  # Persister le changement dans data/config.json
        logger.info(f"QTH mis à jour: {user_qra}")
    else:
        logger.warning(f"Tentative de mise à jour QTH invalide: {new_qra}")
    return redirect(url_for('index'))


@app.route('/api/update_mycall', methods=['POST'])
@require_api_token
def api_update_mycall():
    """Changer MY_CALL et le persister dans data/config.json."""
    global MY_CALL
    new_call = request.json.get('my_call', '').upper().strip()
    if not new_call or len(new_call) < 3 or len(new_call) > 10:
        return jsonify({'ok': False, 'error': 'Invalid callsign (3-10 chars)'}), 400
    MY_CALL = new_call
    save_user_config()
    logger.info(f"MY_CALL changé : {MY_CALL}")
    return jsonify({'ok': True, 'my_call': MY_CALL})


def cluster_send_line(line: str) -> bool:
    """Send a raw line to the connected DX cluster. Returns True if sent."""
    global tn_current
    if not line:
        return False
    with tn_lock:
        tn = tn_current
    if tn is None:
        return False
    try:
        _socket_send(tn, line + "\n")
        return True
    except Exception:
        return False

@app.route('/spot', methods=['POST'])
@app.route('/api/spot', methods=['POST'])
@require_api_token
def api_spot():
    """Spot a callsign to the DX cluster: expects JSON {freq, call, comment}."""
    data = request.get_json(silent=True) or {}
    call = (data.get('call') or '').strip().upper()
    freq = (data.get('freq') or '').strip()
    comment = (data.get('comment') or '').strip()
    if not call or not re.match(r"^[A-Z0-9/]{3,}$", call):
        return jsonify({'ok': False, 'error': 'CALL invalid'}), 400
    # freq: allow "14074.0" or "14.074" etc. We send what user provided if numeric
    try:
        f = float(freq.replace(',', '.'))
    except Exception:
        return jsonify({'ok': False, 'error': 'FREQ invalid'}), 400
    if f <= 0:
        return jsonify({'ok': False, 'error': 'FREQ invalid'}), 400
    # Keep formatting close to what clusters commonly show
    # If user entered MHz (< 1000), convert to kHz-ish? Here we assume: < 1000 => MHz*1000 (14.074 -> 14074.0)
    if f < 1000:
        f_out = f * 1000.0
    else:
        f_out = f
    freq_out = f"{f_out:.1f}"
    # Build cluster command
    cmd = f"DX {freq_out} {call} {comment}".strip()
    sent = cluster_send_line(cmd)
    if not sent:
        return jsonify({'ok': False, 'error': 'Cluster not connected'}), 503
    logger.info(f"Spot TX: {cmd}")
    return jsonify({'ok': True, 'sent': cmd})

@app.route('/user_location.json')
def get_user_location():
    return jsonify({'qra': user_qra, 'lat': user_lat, 'lon': user_lon})

def _enrich_spot_lotw(spot):
    """Ajoute le statut LoTW à un spot si session active."""
    with lotw_lock:
        if not lotw_session['logged_in']:
            return spot
        call = (spot.get('dx_call') or '').upper()
        country = get_country_info(call).get('c', '')
        spot = dict(spot)
        spot['lotw_call_confirmed'] = call in lotw_data['confirmed_calls']
        spot['lotw_dxcc_confirmed'] = country in lotw_data['confirmed_dxcc']
        spot['lotw_dxcc_new']       = bool(country) and country != 'Unknown' and country not in lotw_data['worked_dxcc']
        spot['lotw_active']         = True
    return spot

@app.route('/spots.json')
def get_spots():
    now = time.time()
    filter_band = request.args.get('band')
    filter_mode = request.args.get('mode')
    all_spots = [s for s in spots_buffer if (now - s['timestamp']) < SPOT_LIFETIME]
    if filter_band and filter_band != "All":
        all_spots = [s for s in all_spots if s['band'] == filter_band]
    if filter_mode and filter_mode != "All":
        all_spots = [s for s in all_spots if s['mode'] == filter_mode]
    all_spots = [_enrich_spot_lotw(s) for s in reversed(all_spots)]
    return jsonify(all_spots)

@app.route('/surge.json')
def get_surge_status():
    active_surges = analyze_surges()
    return jsonify({"surges": active_surges, "timestamp": time.time()})

@app.route('/ai-insight')
@app.route('/ai_insight')
def analysis_page():
    """Page AI Insight — anciennement /analysis."""
    return render_template('ai_insight.html', my_call=MY_CALL)

@app.route('/analysis.html')
@app.route('/analysis')
def analysis_page_alias():
    """Rétrocompatibilité — redirige vers /ai-insight."""
    return redirect(url_for('analysis_page'))

# --- NOUVELLE ROUTE STATISTIQUES DXCC 24H ---

@app.route('/dxcc_stats_24h.json')
def dxcc_stats_24h():
    """
    Calcule et retourne les statistiques DXCC sur 24 heures.
    Inclut les listes dynamiques pour les calls longue distance et les entités rares.
    """
    now = time.time()
    # Spots dans les dernières 24 heures (86400 secondes)
    all_spots_history = spots_buffer # Utiliser le buffer comme historique
    historical_spots = [s for s in all_spots_history if (now - s['timestamp']) < 86400] 

    # Initialisation des compteurs et listes
    dxcc_by_mode = Counter()
    dxcc_by_band = Counter()
    unique_dxcc_set = set()
    high_spd_spots_count = 0
    
    # Nouvelles listes demandées pour le front-end
    rare_dxcc_entities = set()
    long_distance_calls = set()
    
    # Itération sur les spots historiques
    for spot in historical_spots:
        dxcc = spot.get('country') 
        mode = spot.get('mode')
        band = spot.get('band')
        spd = spot.get('score')
        distance_km = spot.get('distance_km')
        call = spot.get('dx_call') 
        
        if dxcc:
            unique_dxcc_set.add(dxcc)
            if mode:
                dxcc_by_mode[mode] += 1
            if band:
                dxcc_by_band[band] += 1

        # 1. Spots rares (SPD>=seuil) + entités rares (préfixes explicitement rares)
        if spd is not None and spd >= SPD_THRESHOLD and dxcc:
            high_spd_spots_count += 1
        if spot.get('is_rare') and dxcc:
            rare_dxcc_entities.add(dxcc)

        # 2. Calcul des calls Longue Distance (> 10000 km)
        # On ne compte que les indicatifs uniques pour la liste
        if distance_km is not None and distance_km >= 10000 and call:
            long_distance_calls.add(call)

    total_spots_24h = len(historical_spots)
    rarity_rate_percent = f"{(high_spd_spots_count / total_spots_24h * 100):.2f}%" if total_spots_24h > 0 else "0.00%"
    last_updated_time = time.strftime("%H:%M:%S", time.gmtime(now))

    # --- Fenêtre courte pour anomalies (2 heures) ---
    recent_spots = [s for s in all_spots_history if (now - s['timestamp']) < 7200]
    recent_by_band = Counter(s.get('band') for s in recent_spots if s.get('band'))

    # Fréquence la plus vue sur 6m (pour affichage anomalies)
    freq6 = [s.get('freq') for s in recent_spots if s.get('band') == '6m' and s.get('freq')]
    top6 = Counter(freq6).most_common(1)
    top_freq_6m = top6[0][0] if top6 else None
    # Dernier spot 6m sur la fenêtre courte (2h) : permet une expiration fiable après 2h sans activité
    last6 = None
    for sp in recent_spots:
        if sp.get('band') == '6m':
            if (last6 is None) or (sp.get('timestamp', 0) > last6.get('timestamp', 0)):
                last6 = sp
    last6_age_sec = int(now - last6['timestamp']) if last6 and last6.get('timestamp') else None
    last6_time = last6.get('time') if last6 else None
    last6_call = last6.get('dx_call') if last6 else None
    last6_freq = last6.get('freq') if last6 else None

    # Activités rares : liste "call + heure + fréquence" avec raz naturelle via fenêtre glissante
    RARE_WINDOW_SEC = 3 * 3600  # 3 heures
    rare_recent = [sp for sp in all_spots_history if (now - sp.get('timestamp', 0)) < RARE_WINDOW_SEC and sp.get('is_rare')]
    last_by_call = {}
    for sp in rare_recent:
        c = sp.get('dx_call')
        if not c:
            continue
        prev = last_by_call.get(c)
        if (prev is None) or (sp.get('timestamp', 0) > prev.get('timestamp', 0)):
            last_by_call[c] = sp
    rare_spots_list = sorted(last_by_call.values(), key=lambda x: x.get('timestamp', 0), reverse=True)[:20]
    recent_rare_spots = [
        {
            'call': sp.get('dx_call'),
            'time': sp.get('time'),
            'freq': sp.get('freq'),
            'band': sp.get('band'),
            'mode': sp.get('mode'),
            'country': sp.get('country'),
            'timestamp': sp.get('timestamp')
        }
        for sp in rare_spots_list
    ]



    return jsonify({
        "unique_dxcc_count": len(unique_dxcc_set),
        "total_spots_24h": total_spots_24h,
        "rarity_rate_percent": rarity_rate_percent,
        "high_spd_spots": high_spd_spots_count,
        "dxcc_by_mode": dict(dxcc_by_mode),
        "dxcc_by_band": dict(dxcc_by_band),
        "last_updated": last_updated_time,

        # Fenêtre courte (2h) pour anomalies
        "recent_by_band": dict(recent_by_band),
        "recent_top_freq": {"6m": top_freq_6m},
        "last_6m": {"age_sec": last6_age_sec, "time": last6_time, "call": last6_call, "freq": last6_freq},
        "recent_rare_spots": recent_rare_spots,
        
        # Clés pour les listes dynamiques
        "rare_dxcc_entities": sorted(list(rare_dxcc_entities)), 
        "long_distance_calls_count": len(long_distance_calls), 
        "long_distance_calls": sorted(list(long_distance_calls))
    })

@app.post("/api/meta/run")
def run_meta():
    """
    Relance la méta-analyse (génère data/meta/summary.json etc.)
    Sécurité:
      - Si META_RUN_TOKEN est défini => header X-META-TOKEN requis.
      - Sinon => autorisé uniquement depuis le LAN (192.168.x.x / 10.x.x.x / 127.0.0.1).
    """
    try:
        ip = request.remote_addr or ""
        token = request.headers.get("X-META-TOKEN", "")

        # Si token configuré -> token obligatoire
        if META_RUN_TOKEN:
            if token != META_RUN_TOKEN:
                return jsonify({"status": "forbidden"}), 403
        else:
            # Sinon: on limite au LAN (évite exposition accidentelle)
            if not (ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("127.")):
                return jsonify({"status": "forbidden"}), 403

        META_DIR.mkdir(parents=True, exist_ok=True)

        log_path = request.args.get("log", str(LOG_PATH_DEFAULT))
        cmd = ["python3", str(ANALYZER), "--log", log_path, "--outdir", str(META_DIR)]

        # Vérification préalable : le script analyzer existe-t-il vraiment ?
        # Sans ce contrôle, une absence de fichier produit un CalledProcessError
        # opaque (juste un code retour, aucun message exploitable).
        if not ANALYZER.exists():
            return jsonify({
                "status": "error",
                "msg": f"Script d'analyse introuvable : {ANALYZER} — vérifiez qu'il est bien déployé sur le serveur."
            }), 500

        result = subprocess.run(cmd, timeout=120, capture_output=True, text=True)
        if result.returncode != 0:
            return jsonify({
                "status": "failed",
                "code": result.returncode,
                "stderr": (result.stderr or "")[-2000:],
                "stdout": (result.stdout or "")[-500:],
            }), 500

        return jsonify({"status": "ok"})
    except subprocess.TimeoutExpired:
        return jsonify({"status": "timeout"}), 504
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500
@app.route('/wanted.json')
def get_ranking():
    now = time.time()
    active = [s for s in spots_buffer if (now - s['timestamp']) < SPOT_LIFETIME]
    def get_top_for_list(spot_list):
        ranked = sorted(spot_list, key=lambda x: x['score'], reverse=True)
        seen, top = set(), []
        for s in ranked:
            if s['dx_call'] not in seen:
                top.append(s)
                seen.add(s['dx_call'])
            if len(top) >= TOP_RANKING_LIMIT:
                break
        return top
    hf_spots = [s for s in active if s['type'] == 'HF']
    vhf_spots = [s for s in active if s['type'] == 'VHF']
    return jsonify({"hf": get_top_for_list(hf_spots), "vhf": get_top_for_list(vhf_spots)})

def _parse_end_date_from_title(title):
    """Extrait la date de fin depuis un titre NG3K.
    Ex: '5Z4 · Kenya · → 16 Jun 2026' → '2026-06-16'
        'FO · French Polynesia · → 20 Jul 2026' → '2026-07-20'
    """
    import re
    if not title:
        return None
    MONTHS = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
               'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}
    # Pattern: → DD Mon YYYY ou → D Mon YYYY
    m = re.search(r'→\s*(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})', title)
    if m:
        day   = int(m.group(1))
        month = MONTHS.get(m.group(2).lower())
        year  = int(m.group(3))
        if month:
            return f"{year:04d}-{month:02d}-{day:02d}"
    return None


@app.route('/watchlist.json', methods=['GET', 'POST', 'DELETE'])
def manage_watchlist():
    if request.method == 'GET':
        return jsonify(sorted(list(watchlist)))
    # Jeton requis uniquement pour les méthodes mutatives — GET reste
    # ouvert car lu en permanence par les 3 modes d'affichage.
    provided = request.headers.get("X-API-Token", "")
    if not _secrets.compare_digest(provided, API_TOKEN):
        return jsonify({'ok': False, 'error': 'Jeton API manquant ou invalide'}), 401
    data = request.get_json(force=True, silent=True)
    if not data or 'call' not in data:
        return abort(400)
    call = data['call'].upper().strip()
    if request.method == 'POST':
        watchlist.add(call)
        # Enregistrer end_date si fournie (ex: depuis le Briefing)
        end_date = data.get('end_date') or _parse_end_date_from_title(data.get('title', ''))
        with wl_activity_lock:
            entry = wl_activity.get(call, {})
            if not isinstance(entry, dict):
                entry = {"last_spot": None, "end_date": None, "added": time.time()}
            entry["added"] = entry.get("added") or time.time()
            if end_date:
                entry["end_date"] = end_date
            wl_activity[call] = entry
        save_wl_activity()
        logger.info(f"Ajout à la watchlist: {call} (end_date={end_date})")
    if request.method == 'DELETE' and call in watchlist:
        watchlist.remove(call)
        logger.info(f"Retrait de la watchlist: {call}")
    save_watchlist()
    return jsonify({"status": "ok"})
@app.post("/api/watchlist/purge")
def purge_watchlist():
    global watchlist
    data = request.get_json(silent=True) or {}
    calls_to_remove = [x.upper() for x in data.get("calls", []) if isinstance(x, str)]
    removed = []
    for call in calls_to_remove:
        if call in watchlist:
            watchlist.remove(call)
            removed.append(call)
    if removed:
        save_watchlist()
        logger.info(f"Purge watchlist: {len(removed)} calls supprimes")
    return jsonify({"status": "ok", "removed": removed, "count": len(removed)})

@app.get("/api/watchlist/stale")
def watchlist_stale():
    """Retourne les calls éligibles à la purge.
    Logique v2 (end_date) :
      1. Si end_date connue et dépassée → pré-coché (expédition terminée)
      2. Si end_date inconnue et jamais spotté depuis X jours → pré-coché
      3. Si end_date future → non inclus (expédition en cours)
      4. Si spotté récemment → non inclus (call actif)
    """
    from datetime import date as _date
    days = int(request.args.get("days", 7))
    now  = time.time()
    today = _date.today()
    grace_days = days  # nb jours après end_date avant de purger

    with wl_activity_lock:
        activity = dict(wl_activity)

    # Enrichir avec les spots récents en mémoire
    for s in spots_buffer:
        call = s.get("dx_call", "").upper()
        ts   = s.get("timestamp", 0)
        if call in {x.upper() for x in watchlist}:
            entry = activity.get(call, {})
            if not isinstance(entry, dict):
                entry = {"last_spot": float(entry), "end_date": None, "added": float(entry)}
            if ts > (entry.get("last_spot") or 0):
                entry["last_spot"] = ts
            activity[call] = entry

    stale_items = []
    for x in sorted(watchlist):
        call  = x.upper()
        entry = activity.get(call, {})
        if not isinstance(entry, dict):
            entry = {"last_spot": float(entry) if entry else None, "end_date": None, "added": None}

        end_date_str  = entry.get("end_date")
        last_spot_ts  = entry.get("last_spot")
        added_ts      = entry.get("added")

        # Calculer end_date en objet date
        end_date = None
        if end_date_str:
            try:
                parts = end_date_str.split("-")
                end_date = _date(int(parts[0]), int(parts[1]), int(parts[2]))
            except Exception:
                pass

        # Décision d'inclusion
        reason = None

        if end_date:
            days_since_end = (today - end_date).days
            if days_since_end >= grace_days:
                # Expédition terminée depuis grace_days jours
                reason = f"Expédition terminée il y a {days_since_end}j"
            elif days_since_end < 0:
                # Expédition encore en cours → pas dans la liste
                continue
            else:
                # Dans la période de grâce → inclure mais pas coché
                reason = f"Expédition terminée récemment ({days_since_end}j)"
        else:
            # Pas de end_date — basé sur l'activité
            if last_spot_ts:
                age_days = int((now - last_spot_ts) / 86400)
                if age_days < days:
                    continue  # Actif récemment
                reason = f"Inactif depuis {age_days}j"
            else:
                # Jamais spotté — inclure si ajouté il y a plus de grace_days
                if added_ts:
                    age_added = int((now - added_ts) / 86400)
                    if age_added < grace_days:
                        continue
                reason = "Jamais spotté"

        last_seen_utc = None
        if last_spot_ts:
            last_seen_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(last_spot_ts))

        stale_items.append({
            "call":         x,
            "reason":       reason,
            "end_date":     end_date_str,
            "last_seen_utc": last_seen_utc,
            "pre_checked":  end_date is not None and (today - end_date).days >= grace_days,
        })

    # Trier : expéditions terminées en premier, puis inactifs, puis jamais vus
    def sort_key(o):
        if o["end_date"]:
            return (0, o["end_date"])
        if o["last_seen_utc"]:
            return (1, o["last_seen_utc"])
        return (2, o["call"])

    stale_items.sort(key=sort_key)
    return jsonify({"stale": stale_items, "days": days, "total": len(stale_items)})

@app.get("/api/watchlist/tracking.json")
def api_watchlist_tracking():
    """Tracking watchlist: derniers spots par call (alimente le pavé Index)."""
    try:
        limit = int(request.args.get("limit", 10))
    except Exception:
        limit = 10
    limit = max(1, min(limit, 50))

    q = (request.args.get("q") or "").strip().upper()
    dx_only = (request.args.get("dx_only", "1").strip() not in ("0", "false", "False"))

    calls = sorted(list(watchlist))
    if q:
        calls = [c for c in calls if q in c]

    wanted = set(calls)
    out = {c: [] for c in calls}
    now = time.time()

    with spot_history_lock:
        hist = list(spot_history)

    for s in reversed(hist):
        try:
            dx = (s.get("dx") or "").strip().upper()
            de = (s.get("de") or "").strip().upper()

            hit = None
            if dx in wanted:
                hit = dx
            elif (not dx_only) and de in wanted:
                hit = de

            if not hit:
                continue
            if len(out[hit]) >= limit:
                continue

            ts = float(s.get("ts", now))
            out[hit].append({
                "utc": time.strftime("%H:%M", time.gmtime(ts)),
                "age_min": int((now - ts) / 60),
                "band": s.get("band"),
                "mode": s.get("mode"),
                "freq_khz": s.get("freq_khz"),
                "de": s.get("de"),
                "dx": s.get("dx"),
            })
        except Exception:
            continue

        if calls and all(len(out[c]) >= limit for c in calls):
            break

    return jsonify({
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "limit": limit,
        "dx_only": dx_only,
        "q": q,
        "calls": out
    })

@app.route('/rss.json')
def get_rss():
    return jsonify({"ticker": ticker_info["text"]})

def _get_recent_spots_fallback(minutes: int = 15, limit: int = 300):
    """
    Récupère les spots récents depuis les structures globales probables.
    Ne crashe jamais : retourne une liste (éventuellement vide).
    """
    import time

    now = time.time()
    min_ts = now - (minutes * 60)

    # Liste de noms globaux courants dans ce type d'app
    candidates = [
        "spots_history",
        "recent_spots",
        "spots_buffer",
        "spots",
        "SPOTS",
        "telnet_spots",
        "cluster_spots",
    ]

    container = None
    for name in candidates:
        if name in globals():
            container = globals()[name]
            break

    if container is None:
        return []

    # Convertit en liste
    try:
        items = list(container)
    except Exception:
        return []

    # Filtre temporel (essaie plusieurs clés possibles)
    def ts_of(s):
        if not isinstance(s, dict):
            return None
        for k in ("t", "ts", "time_ts", "timestamp", "epoch", "created_ts"):
            v = s.get(k)
            if isinstance(v, (int, float)):
                return float(v)
        return None

    filtered = []
    for s in reversed(items):  # souvent plus récent à la fin
        if isinstance(s, dict):
            ts = ts_of(s)
            if ts is None or ts >= min_ts:
                filtered.append(s)
        if len(filtered) >= limit:
            break

    # on remet dans l'ordre chrono
    return list(reversed(filtered))


@app.route("/api/map/spots")
def api_map_spots():
    minutes = int(request.args.get("minutes", 15))
    limit = int(request.args.get("limit", 300))
    band = (request.args.get("band") or "").strip()
    mode = (request.args.get("mode") or "").strip()

    # 1) Récupère les spots récents depuis TON buffer/stock (ex: deque spots_history)
    spots = _get_recent_spots_fallback(minutes=minutes, limit=limit)

    # 2) Filtre simple
    if band:
        spots = [s for s in spots if (s.get("band") == band)]
    if mode:
        spots = [s for s in spots if (s.get("mode") == mode)]

    # 3) Ajoute lat/lon (si déjà présents, garde; sinon enrichis via cty.dat)
    #    Ici: on suppose que ton pipeline met déjà lat/lon dans chaque spot.
    qth = {"lat": user_lat, "lon": user_lon, "qra": user_qra}

    return jsonify({
        "ok": True,
        "minutes": minutes,
        "count": len(spots),
        "qth": qth,
        "spots": spots
    })

# =========================================================
# FORECAST / WORLD MAP — V1 (proxy local, non prédictif)
# =========================================================

def classify_cluster(cluster_spots):
    """Classifie un cluster avec règles simples et explicables."""
    if not cluster_spots:
        return "suspect", "low", {"spot_count": 0, "unique_calls": 0, "duration_min": 0}

    spot_count = len(cluster_spots)
    calls = set()
    timestamps = []

    for s in cluster_spots:
        dx = s.get("dx_call") or s.get("dx")
        if dx:
            calls.add(dx)
        ts = s.get("timestamp")
        if isinstance(ts, (int, float)):
            timestamps.append(ts)

    unique_calls = len(calls)
    duration_min = int((max(timestamps) - min(timestamps)) / 60) if timestamps else 0

    if spot_count >= 6 and unique_calls >= 3 and duration_min >= 10:
        status, confidence = "confirmed", "high"
    elif spot_count >= 3:
        status, confidence = "suspect", "medium"
    else:
        status, confidence = "suspect", "low"

    return status, confidence, {
        "spot_count": spot_count,
        "unique_calls": unique_calls,
        "duration_min": duration_min
    }

@app.route("/api/forecast/anomalies")
def api_forecast_anomalies():
    try:
        band = request.args.get("band", "all")
        window_min = int(request.args.get("window", 180))

        now = time.time()
        since_ts = now - window_min * 60

        spots = [
            s for s in spots_buffer
            if s.get("timestamp", 0) >= since_ts
            and (band == "all" or s.get("band") == band)
            and s.get("lat") is not None
            and s.get("lon") is not None
        ]

        if not spots:
            return jsonify({
                "ok": True,
                "mode": "calibration",
                "clusters": [],
                "count": 0,
                "spot_count": 0
            })

        # ---------- distance km ----------
        def distance_km(a, b):
            R = 6371.0
            lat1 = math.radians(a["lat"])
            lon1 = math.radians(a["lon"])
            lat2 = math.radians(b["lat"])
            lon2 = math.radians(b["lon"])
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            h = math.sin(dlat / 2)**2 + \
                math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
            return 2 * R * math.asin(math.sqrt(h))

        # ---------- clustering ----------
        MAX_DIST_KM = 250
        clusters = []

        for spot in spots:
            added = False
            for cluster in clusters:
                if distance_km(spot, cluster["center"]) <= MAX_DIST_KM:
                    cluster["spots"].append(spot)
                    added = True
                    break
            if not added:
                clusters.append({
                    "center": {"lat": spot["lat"], "lon": spot["lon"]},
                    "spots": [spot]
                })

        results = []

        for c in clusters:
            spots_c = c["spots"]
            timestamps = [s["timestamp"] for s in spots_c]
            calls = {s.get("dx") for s in spots_c if s.get("dx")}

            duration_min = int((max(timestamps) - min(timestamps)) / 60)
            spot_count = len(spots_c)
            unique_calls = len(calls)

            if spot_count < 3:
                status = "calibration"
                confidence = "low"
            elif spot_count < 6 or duration_min < 20:
                status = "suspect"
                confidence = "medium"
            else:
                status = "confirmed"
                confidence = "high"

            results.append({
                "band": band,
                "center": c["center"],
                "status": status,
                "confidence": confidence,
                "metrics": {
                    "spot_count": spot_count,
                    "unique_calls": unique_calls,
                    "duration_min": duration_min
                },
                "examples": [
                    {
                        "dx": s.get("dx"),
                        "freq_khz": s.get("freq"),
                        "mode": s.get("mode"),
                        "utc": datetime.utcfromtimestamp(
                            s["timestamp"]
                        ).strftime("%Y-%m-%dT%H:%M:%SZ")
                    }
                    for s in spots_c[:3]
                ]
            })

        if any(r["status"] == "confirmed" for r in results):
            mode = "active"
        elif any(r["status"] == "suspect" for r in results):
            mode = "suspect"
        else:
            mode = "calibration"

        return jsonify({
            "ok": True,
            "mode": mode,
            "clusters": results,
            "count": len(results),
            "spot_count": len(spots)
        })

    except Exception as e:
        logger.exception("api_forecast_anomalies failed")
        return jsonify({
            "ok": False,
            "error": str(e),
            "mode": "error",
            "clusters": []
        }), 500


def distance_km(a, b):
    """Distance Haversine en km entre deux points dict {'lat','lon'}"""
    R = 6371.0

    lat1 = math.radians(a["lat"])
    lon1 = math.radians(a["lon"])
    lat2 = math.radians(b["lat"])
    lon2 = math.radians(b["lon"])

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    h = math.sin(dlat / 2)**2 + \
        math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2

    return 2 * R * math.asin(math.sqrt(h)) 

@app.route("/api/forecast/heatmap.png")
def api_forecast_heatmap():
    from PIL import Image
    import io

    w = int(request.args.get("w", 720))
    h = int(request.args.get("h", 360))

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return Response(buf.getvalue(), mimetype="image/png")

# --- SOLAR ROUTES (XML + JSON) ---
@app.route('/solar.xml')
@app.route('/api/solar.xml')
def get_solar_xml():
    with solar_lock:
        xml = solar_xml_cache
    return Response(xml, mimetype='application/xml; charset=utf-8')

@app.route('/solar.json')
@app.route('/api/solar.json')
def get_solar_json():
    with solar_lock:
        data = dict(solar_cache)
    return jsonify(data)
# --- END SOLAR ROUTES ---


# --- DX BRIEFING (Data-to-Text, deterministic, cached) ---
dx_briefing_lock = threading.Lock()
dx_briefing_cache = {
    "ts": 0.0,  # ts=0 force refresh au premier appel
    "fr": None,
    "en": None,
}

def _to_int(x):
    try:
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return int(x)
        s = str(x)
        m = re.search(r"(-?\d+)", s)
        return int(m.group(1)) if m else None
    except Exception:
        return None

def _to_float(x):
    try:
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x)
        m = re.search(r"(-?\d+(?:\.\d+)?)", s)
        return float(m.group(1)) if m else None
    except Exception:
        return None

def _sfi_status(sfi):
    if sfi is None:
        return ("UNKNOWN", "N/A")
    if sfi < 90:
        return ("POOR", "SFI<90")
    if sfi < 120:
        return ("FAIR", "90≤SFI<120")
    if sfi < 160:
        return ("GOOD", "120≤SFI<160")
    return ("EXCELLENT", "SFI≥160")

def _geomag_status(a_idx, k_idx):
    # Simple, readable status
    if a_idx is None and k_idx is None:
        return ("UNKNOWN", "A/K=N/A")
    # Prefer K when available (more direct short-term indicator)
    if k_idx is not None:
        if k_idx <= 2:
            return ("QUIET", "K≤2")
        if k_idx <= 4:
            return ("UNSETTLED", "2<K≤4")
        if k_idx <= 6:
            return ("ACTIVE", "4<K≤6")
        return ("STORM", "K>6")
    # Fallback to A
    if a_idx is not None:
        if a_idx <= 10:
            return ("QUIET", "A≤10")
        if a_idx <= 20:
            return ("UNSETTLED", "10<A≤20")
        if a_idx <= 50:
            return ("ACTIVE", "20<A≤50")
        return ("STORM", "A>50")
    return ("UNKNOWN", "A/K=N/A")

def _hf_outlook_text(sfi, k_idx, lang="fr"):
    # Keep it practical and short. K makes things unstable.
    k_penalty = (k_idx is not None and k_idx >= 4)
    if lang == "en":
        if sfi is None:
            base = "HF outlook uncertain (missing SFI)."
        elif sfi < 90:
            base = "HF likely poor: focus on 40/80m at night; 10/12m mostly closed."
        elif sfi < 120:
            base = "HF fair: 15–20m often workable; 10–12m unstable."
        elif sfi < 160:
            base = "HF good: 10–12–15m may open daytime; 20m strong."
        else:
            base = "HF excellent: 10–12m wide open potential; strong 15–20m."
        if k_penalty:
            base += " Geomagnetic conditions are unsettled: expect fades/auroral skew."
        return base

    # FR
    if sfi is None:
        base = "Prévision HF incertaine (SFI manquant)."
    elif sfi < 90:
        base = "HF faible : privilégie 40/80m la nuit ; 10/12m souvent fermés."
    elif sfi < 120:
        base = "HF correcte : 15–20m souvent praticables ; 10–12m instables."
    elif sfi < 160:
        base = "HF bonne : 10–12–15m possibles en journée ; 20m solide."
    else:
        base = "HF excellente : gros potentiel 10–12m ; 15–20m très forts."
    if k_penalty:
        base += " Géomagnétique agité : fades possibles, trajets polaires perturbés."
    return base

def build_dx_briefing(lang="fr"):
    lang = (lang or "fr").lower()
    lang = "en" if lang.startswith("en") else "fr"

    now = time.time()
    # Snapshot data (avoid holding locks too long)
    with solar_lock:
        sc = dict(solar_cache)

    sfi = _to_int(sc.get("sfi"))
    a_idx = _to_int(sc.get("a"))
    k_idx = _to_float(sc.get("k"))
    ts_utc = sc.get("ts_utc") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Analyze recent spots (lightweight)
    recent_window = 2 * 3600  # 2h for briefing
    active_window = 30 * 60   # 30m for "what's hot"
    now_ts = time.time()

    recent = [s for s in spots_buffer if (now_ts - s.get("timestamp", 0)) < recent_window]
    active = [s for s in recent if (now_ts - s.get("timestamp", 0)) < active_window]

    # Band activity (active 30m)
    band_counts = Counter(s.get("band") for s in active if s.get("band"))
    top_bands = [b for b, _ in band_counts.most_common(5)]

    # Mode activity (active 30m)
    mode_counts = Counter(s.get("mode") for s in active if s.get("mode"))
    top_modes = [m for m, _ in mode_counts.most_common(4)]

    # DXCC / Countries in 2h
    dxcc_counts = Counter(s.get("country") for s in recent if s.get("country") and s.get("country") != "Unknown")
    top_dxcc = [c for c, _ in dxcc_counts.most_common(5)]

    # Long distance calls (2h)
    long_calls = {s.get("dx_call") for s in recent if (s.get("distance_km") or 0) >= 10000 and s.get("dx_call")}
    long_calls_count = len(long_calls)

    # High SPD (rare)
    high_spd = [s for s in recent if (s.get("score") or 0) >= SPD_THRESHOLD]
    high_spd_count = len(high_spd)

    # Surges
    try:
        surges = analyze_surges()
    except Exception:
        surges = []

    sfi_stat, sfi_rule = _sfi_status(sfi)
    geo_stat, geo_rule = _geomag_status(a_idx, k_idx)

    if lang == "en":
        title = "DX Briefing"
        bullets = []

        bullets.append(f"Solar: SFI={sfi if sfi is not None else 'N/A'} ({sfi_stat}), A={a_idx if a_idx is not None else 'N/A'}, K={k_idx if k_idx is not None else 'N/A'} ({geo_stat}).")
        bullets.append(_hf_outlook_text(sfi, k_idx, lang="en"))

        if top_bands:
            bullets.append("Hot bands (30m): " + ", ".join(top_bands))
        if top_modes:
            bullets.append("Hot modes (30m): " + ", ".join(top_modes))
        if surges:
            bullets.append("Surge alerts: " + ", ".join(surges))
        if top_dxcc:
            bullets.append("Top DXCC (2h): " + ", ".join(top_dxcc))
        bullets.append(f"Long-distance calls (≥10,000 km / 2h): {long_calls_count}. High-SPD spots (2h): {high_spd_count}.")

        text = " ".join(bullets)

    else:
        title = "DX Briefing"
        bullets = []

        bullets.append(f"Solaire : SFI={sfi if sfi is not None else 'N/A'} ({sfi_stat}), A={a_idx if a_idx is not None else 'N/A'}, K={k_idx if k_idx is not None else 'N/A'} ({geo_stat}).")
        bullets.append(_hf_outlook_text(sfi, k_idx, lang="fr"))

        if top_bands:
            bullets.append("Bandes chaudes (30 min) : " + ", ".join(top_bands))
        if top_modes:
            bullets.append("Modes chauds (30 min) : " + ", ".join(top_modes))
        if surges:
            bullets.append("Alertes surge : " + ", ".join(surges))
        if top_dxcc:
            bullets.append("Top DXCC (2h) : " + ", ".join(top_dxcc))
        bullets.append(f"Longue distance (≥10 000 km / 2h) : {long_calls_count}. Spots rares (SPD≥{SPD_THRESHOLD}) sur 2h : {high_spd_count}.")

        text = " ".join(bullets)

    payload = {
        "ok": True,
        "version": APP_VERSION,
        "title": title,
        "lang": lang,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "solar_ts_utc": ts_utc,
        "briefing": text,
        "bullets": bullets,
        "metrics": {
            "sfi": sfi if sfi is not None else "N/A",
            "a": a_idx if a_idx is not None else "N/A",
            "k": k_idx if k_idx is not None else "N/A",
            "sfi_status": sfi_stat,
            "geomag_status": geo_stat,
            "top_bands_30m": top_bands,
            "top_modes_30m": top_modes,
            "surges": surges,
            "top_dxcc_2h": top_dxcc,
            "long_distance_calls_2h": long_calls_count,
            "high_spd_spots_2h": high_spd_count,
        }
    }
    return payload

@app.route('/api/dx_briefing.json')
@app.route('/dx_briefing.json')
def api_dx_briefing():
    """
    Deterministic DX briefing (cached, lightweight for Raspberry Pi).
    Query params:
      - lang=fr|en
      - force=1 to bypass cache
    """
    lang = (request.args.get('lang') or 'fr').lower()
    force = request.args.get('force') in ('1', 'true', 'yes')
    now = time.time()

    with dx_briefing_lock:
        cache_age = now - (dx_briefing_cache.get('ts') or 0.0)
        cached = dx_briefing_cache.get('en' if lang.startswith('en') else 'fr')
        if (not force) and cached is not None and cache_age < 600:  # 10 minutes
            return jsonify(cached)

    payload = build_dx_briefing(lang=lang)
    with dx_briefing_lock:
        dx_briefing_cache['ts'] = now
        dx_briefing_cache[payload['lang']] = payload
    return jsonify(payload)
# --- END DX BRIEFING ---


# =============================================================
# IA BRIEF VOCAL — Perplexity API (optionnel)
# =============================================================
ai_brief_lock = threading.Lock()
ai_brief_cache = {"ts": 0.0, "text": None, "lang": None}


def _band_velocity(spots, band, window_sec=300):
    """Retourne le nombre de spots sur une bande dans les dernières window_sec secondes."""
    now_ts = time.time()
    return sum(1 for s in spots
               if s.get("band") == band and (now_ts - s.get("timestamp", 0)) < window_sec)


def _build_ai_context(lang="fr"):
    """Compile un contexte riche avec tendances temporelles pour raisonnement IA."""
    with solar_lock:
        sc = dict(solar_cache)

    now_ts = time.time()

    # Fenêtres temporelles
    w5  = [s for s in spots_buffer if (now_ts - s.get("timestamp", 0)) < 300]
    w15 = [s for s in spots_buffer if (now_ts - s.get("timestamp", 0)) < 900]
    w30 = [s for s in spots_buffer if (now_ts - s.get("timestamp", 0)) < 1800]
    w1h = [s for s in spots_buffer if (now_ts - s.get("timestamp", 0)) < 3600]

    # Vélocité par bande : tendance montante/descendante/stable
    band_velocity = {}
    for band in HF_BANDS + VHF_BANDS:
        v5  = _band_velocity(spots_buffer, band, 300)
        v30 = _band_velocity(spots_buffer, band, 1800)
        rate_30 = v30 / 6  # moyenne spots/5min sur 30min
        if v5 > 0 or v30 > 0:
            trend = "montante" if v5 > rate_30 * 1.5 else \
                    "descendante" if (v5 < rate_30 * 0.5 and rate_30 > 0) else "stable"
            band_velocity[band] = {
                "spots_5min": v5,
                "spots_30min": v30,
                "tendance": trend
            }

    # Watchlist — détail par call : dernier spot, âge, bande, fréquence
    watchlist_detail = []
    for call in sorted(watchlist):
        spots_wl = [s for s in w1h if s.get("dx_call", "").upper() == call]
        if spots_wl:
            last = max(spots_wl, key=lambda s: s.get("timestamp", 0))
            age_min = int((now_ts - last.get("timestamp", 0)) / 60)
            watchlist_detail.append({
                "call": call,
                "age_min": age_min,
                "band": last.get("band"),
                "mode": last.get("mode"),
                "freq": last.get("freq"),
                "score": last.get("score"),
            })

    # Spots rares avec détail
    rare_detail = []
    seen_rare = set()
    for s in sorted(w1h, key=lambda x: x.get("timestamp", 0), reverse=True):
        if s.get("is_rare") and s.get("dx_call") not in seen_rare:
            seen_rare.add(s.get("dx_call"))
            age_min = int((now_ts - s.get("timestamp", 0)) / 60)
            rare_detail.append({
                "call": s.get("dx_call"),
                "country": s.get("country"),
                "band": s.get("band"),
                "mode": s.get("mode"),
                "age_min": age_min,
                "score": s.get("score"),
            })
            if len(rare_detail) >= 5:
                break

    # Longue distance avec détail
    long_dist_detail = []
    seen_ld = set()
    for s in sorted(w1h, key=lambda x: x.get("distance_km", 0), reverse=True):
        if (s.get("distance_km") or 0) >= 10000 and s.get("dx_call") not in seen_ld:
            seen_ld.add(s.get("dx_call"))
            long_dist_detail.append({
                "call": s.get("dx_call"),
                "country": s.get("country"),
                "band": s.get("band"),
                "dist_km": int(s.get("distance_km", 0)),
                "age_min": int((now_ts - s.get("timestamp", 0)) / 60),
            })
            if len(long_dist_detail) >= 3:
                break

    # Tendance activité globale
    global_trend = "stable"
    if len(w30) > 0:
        rate_5  = len(w5)
        rate_30 = len(w30) / 6
        if rate_5 > rate_30 * 1.8:
            global_trend = "forte accélération"
        elif rate_5 > rate_30 * 1.3:
            global_trend = "accélération"
        elif rate_5 < rate_30 * 0.4:
            global_trend = "forte baisse"
        elif rate_5 < rate_30 * 0.7:
            global_trend = "baisse"

    try:
        surges = analyze_surges()
    except Exception:
        surges = []

    return {
        "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "my_call": MY_CALL,
        "solar": {
            "sfi": sc.get("sfi"), "a": sc.get("a"),
            "k": sc.get("k"), "kp": sc.get("kp")
        },
        "activite": {
            "spots_5min": len(w5),
            "spots_15min": len(w15),
            "spots_30min": len(w30),
            "spots_1h": len(w1h),
            "tendance_globale": global_trend,
        },
        "bandes": {b: v for b, v in band_velocity.items() if v["spots_30min"] > 0},
        "watchlist": watchlist_detail,
        "spots_rares": rare_detail,
        "longue_distance": long_dist_detail,
        "surges": surges,
    }


def call_perplexity_brief(lang="fr"):
    """Appelle l'API Perplexity et retourne le texte du brief IA, ou None en cas d'erreur."""
    if not AI_BRIEF_ENABLED:
        return None

    ctx = _build_ai_context(lang)

    # Résumé lisible des bandes avec tendance
    bandes_actives = []
    for band, v in ctx["bandes"].items():
        trend_sym = "↑" if v["tendance"] == "montante" else \
                    "↓" if v["tendance"] == "descendante" else "→"
        bandes_actives.append(f"{band}({v['spots_5min']}sp/5min {trend_sym})")

    watchlist_str = ""
    if ctx["watchlist"]:
        parts = [f"{w['call']} sur {w['band']} {w['mode']} il y a {w['age_min']}min"
                 for w in ctx["watchlist"]]
        watchlist_str = " ; ".join(parts)

    rares_str = ""
    if ctx["spots_rares"]:
        parts = [f"{r['call']} ({r['country']}) {r['band']} il y a {r['age_min']}min"
                 for r in ctx["spots_rares"]]
        rares_str = " ; ".join(parts)

    ld_str = ""
    if ctx["longue_distance"]:
        parts = [f"{l['call']} {l['country']} {l['dist_km']}km {l['band']}"
                 for l in ctx["longue_distance"]]
        ld_str = " ; ".join(parts)

    lang_instr = "en français" if lang == "fr" else "in English"

    prompt = (
        f"Tu es un expert DX radio. Analyse ces données LIVE et dis à l'opérateur {MY_CALL} "
        f"CE QU'IL DOIT FAIRE MAINTENANT — pas ce qu'il voit déjà à l'écran.\n\n"
        f"DONNÉES ({ctx['ts_utc']}) :\n"
        f"- Solaire : SFI={ctx['solar']['sfi']}, A={ctx['solar']['a']}, K={ctx['solar']['k']}\n"
        f"- Activité : {ctx['activite']['spots_5min']} spots/5min, tendance {ctx['activite']['tendance_globale']}\n"
        f"- Bandes avec tendance : {', '.join(bandes_actives) or 'aucune'}\n"
        f"- Watchlist active : {watchlist_str or 'aucune'}\n"
        f"- Entités rares (1h) : {rares_str or 'aucune'}\n"
        f"- Longue distance (>10000km) : {ld_str or 'aucune'}\n"
        f"- Surges : {', '.join(ctx['surges']) or 'aucun'}\n\n"
        f"RÈGLES DE RÉPONSE :\n"
        f"- 2-3 phrases maximum, {lang_instr}, ton opérateur radio direct\n"
        f"- Commence par l'action prioritaire (ex: 'Va sur 15m maintenant', 'VP2ELX sur watchlist, pile-up léger, tente-le')\n"
        f"- Si watchlist active : mentionne-la en premier\n"
        f"- Si tendance montante sur une bande : dis-le explicitement\n"
        f"- Si rien d'urgent : dis-le clairement plutôt que de reformuler les chiffres\n"
        f"- NE PAS répéter les chiffres bruts déjà visibles (SFI, K, comptages)\n"
        f"- Réponds UNIQUEMENT avec le texte du brief, sans introduction"
    )

    try:
        resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": AI_BRIEF_MODEL,
                "max_tokens": AI_BRIEF_MAX_TOKENS,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"AI brief Perplexity failed: {e}")
        return None


@app.route("/api/ai_brief.json")
def api_ai_brief():
    """
    Brief vocal IA via Perplexity (optionnel, activé si PERPLEXITY_API_KEY est défini).
    Params:
      - lang=fr|en
      - force=1 pour ignorer le cache
    Retourne: {"ok": true, "enabled": true, "text": "...", "lang": "fr", "cached": false}
    """
    if not AI_BRIEF_ENABLED:
        return jsonify({
            "ok": True, "enabled": False,
            "text": None, "reason": "PERPLEXITY_API_KEY not set"
        })

    lang = (request.args.get("lang") or "fr").lower()
    lang = "en" if lang.startswith("en") else "fr"
    force = request.args.get("force") in ("1", "true", "yes")
    now = time.time()

    with ai_brief_lock:
        age = now - ai_brief_cache["ts"]
        if (not force and ai_brief_cache["text"]
                and ai_brief_cache["lang"] == lang
                and age < AI_BRIEF_CACHE_TTL):
            return jsonify({
                "ok": True, "enabled": True,
                "text": ai_brief_cache["text"],
                "lang": lang, "cached": True, "age_sec": int(age)
            })

    text = call_perplexity_brief(lang=lang)
    fallback = False

    if text is None:
        # Fallback sur le brief déterministe si Perplexity échoue
        payload = build_dx_briefing(lang=lang)
        text = payload.get("briefing", "")
        fallback = True

    with ai_brief_lock:
        ai_brief_cache.update({"ts": now, "text": text, "lang": lang})

    return jsonify({
        "ok": True, "enabled": True, "text": text,
        "lang": lang, "cached": False, "fallback": fallback
    })


@app.route("/api/ai_brief_status.json")
def api_ai_brief_status():
    """Indique si la feature IA est activée (utilisé par le widget JS)."""
    return jsonify({
        "enabled": AI_BRIEF_ENABLED,
        "model": AI_BRIEF_MODEL if AI_BRIEF_ENABLED else None
    })

# --- END IA BRIEF VOCAL ---


def _strip_html(value: str) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(cleaned)).strip()

def _entry_timestamp(entry) -> float:
    for key in ("published_parsed", "updated_parsed"):
        ts = entry.get(key)
        if ts:
            return float(calendar.timegm(ts))
    return time.time()

def _entry_summary(entry, limit: int = 220) -> str:
    summary = entry.get("summary") or entry.get("description") or ""
    summary = _strip_html(summary)
    if len(summary) > limit:
        return summary[: limit - 1].rstrip() + "…"
    return summary

def _load_briefing_sources():
    if BRIEFING_SOURCES_FILE.exists():
        try:
            data = json.loads(BRIEFING_SOURCES_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [
                    src for src in data
                    if isinstance(src, dict) and src.get("url") and src.get("name")
                ]
        except Exception:
            pass
    return BRIEFING_DEFAULT_SOURCES

def _fetch_feed(url: str, retries: int = 2, retry_delay_s: float = 2.0):
    last_exc = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": BRIEFING_USER_AGENT, "Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=BRIEFING_FEED_TIMEOUT) as r:
                data = r.read()
            return feedparser.parse(data)
        except Exception as e:
            last_exc = e
            is_dns_error = "name resolution" in str(e) or "Errno -3" in str(e) or "Errno -2" in str(e)
            if attempt < retries and is_dns_error:
                logger.warning(f"_fetch_feed: échec DNS/réseau sur {url} ({e}) — retry {attempt+1}/{retries} dans {retry_delay_s}s")
                time.sleep(retry_delay_s)
                continue
            raise
    raise last_exc

def _fetch_html(url: str, retries: int = 2, retry_delay_s: float = 2.0):
    """Fetch HTML avec retry sur erreurs réseau transitoires (DNS, timeout).
    Une résolution DNS qui échoue une fois n'est pas forcément un vrai
    problème — un court retry évite de perdre tout un cycle de refresh
    pour un blip réseau passager."""
    last_exc = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={
            "User-Agent": BRIEFING_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*",
            "Accept-Language": "en-US,en;q=0.9,fr-FR;q=0.8",
        })
        try:
            with urllib.request.urlopen(req, timeout=BRIEFING_FEED_TIMEOUT) as r:
                return r.read().decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as e:
            logger.warning(f"_fetch_html: HTTP {e.code} sur {url} — probable blocage anti-bot (User-Agent/Cloudflare)")
            raise  # une erreur HTTP (403 etc.) ne se résoudra pas avec un retry immédiat
        except Exception as e:
            last_exc = e
            is_dns_error = "name resolution" in str(e) or "Errno -3" in str(e) or "Errno -2" in str(e)
            if attempt < retries and is_dns_error:
                logger.warning(f"_fetch_html: échec DNS/réseau sur {url} ({e}) — retry {attempt+1}/{retries} dans {retry_delay_s}s")
                time.sleep(retry_delay_s)
                continue
            logger.warning(f"_fetch_html: échec sur {url} ({e})")
            raise
    raise last_exc

def fetch_qo100_news(timeout: int = 10):
    """
    Récupère les news QO-100 DX Club.
    Tente /news puis / avec plusieurs sélecteurs CSS.
    """
    ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    hdrs = {"User-Agent": ua, "Accept": "text/html,application/xhtml+xml,*/*", "Accept-Language": "en-US,en;q=0.9"}
    results = []

    for url in [QO100_NEWS_URL, "https://qo100dx.club/"]:
        try:
            response = requests.get(url, headers=hdrs, timeout=timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            # Essayer plusieurs sélecteurs
            candidates = (
                soup.select("article") or
                soup.select(".post, .news-item, .entry") or
                soup.select("div.item, li.item") or
                []
            )

            for article in candidates:
                # Titre
                h_tag = article.find(["h1","h2","h3","h4"])
                if not h_tag:
                    continue
                link_tag = h_tag.find("a") or article.find("a")
                if not link_tag:
                    continue
                title = link_tag.get_text(strip=True)
                link  = link_tag.get("href","")
                if link.startswith("/"):
                    link = "https://qo100dx.club" + link

                # Date
                date_obj = None
                time_tag = article.find("time")
                if time_tag:
                    try:
                        date_obj = datetime.fromisoformat(time_tag.get("datetime",""))
                    except Exception:
                        pass

                # Résumé
                p_tag = article.find("p")
                summary = _strip_html(p_tag.get_text(strip=True))[:200] if p_tag else ""

                if title:
                    results.append({
                        "title":    title,
                        "date":     date_obj,
                        "date_str": time_tag.get_text(strip=True) if time_tag else "",
                        "link":     link,
                        "summary":  summary,
                    })

            if results:
                break  # On a trouvé quelque chose, pas besoin d'essayer l'autre URL

        except Exception as e:
            logger.warning(f"QO100 fetch error ({url}): {e}")
            continue

    results.sort(key=lambda x: x["date"] if x["date"] else datetime.min, reverse=True)
    return results

def _extract_html_items(source_id: str, html_text: str, limit: int):
    soup = BeautifulSoup(html_text, "html.parser")
    items = []

    if source_id == "dxnews":
        for article in soup.select("article, .post, .entry, div.item"):
            # Titre + lien
            title_link = article.select_one("h1 a, h2 a, h3 a, h4 a, .entry-title a, .post-title a")
            if not title_link:
                continue
            title = _strip_html(title_link.get_text(strip=True))
            link  = title_link.get("href") or ""
            # Résumé — essayer plusieurs conteneurs
            summary = ""
            for sel in [".entry-content p", ".entry-summary p", ".post-content p",
                        ".excerpt p", "p.summary", "p"]:
                tag = article.select_one(sel)
                if tag:
                    txt = _strip_html(tag.get_text(strip=True))
                    if txt and len(txt) > 20:
                        summary = txt[:300]
                        break
            # Date
            time_tag  = article.select_one("time")
            published = time_tag.get("datetime") if time_tag else None
            if not title:
                continue
            items.append({
                "title": title,
                "link": link,
                "published_utc": published,
                "summary": summary,
            })
            if len(items) >= limit:
                break

    elif source_id == "ng3k":
        import re, datetime
        # Format multi-lignes NG3K :
        # "Jan 22-Mar 31, 2026"
        # "DXCC: Curacao"
        # "Callsign: PJ2"
        # "QSL: LoTW"
        # "Source: OPDX (Sep 8, 2025)"
        # "Info: By W2APF..."
        text = soup.get_text("\n")
        now_dt = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

        months_re = r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
        date_line_re = re.compile(
            rf'^({months_re}\s+\d{{1,2}}(?:-(?:{months_re}\s+)?\d{{1,2}})?(?:,\s*\d{{4}})?)\s*$',
            re.IGNORECASE
        )

        def parse_end_date(date_str):
            """Extrait la date de fin depuis 'Mar 8-Apr 4, 2026' ou 'Mar 18-31, 2026'."""
            months_map = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
                          'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}
            yr_m = re.search(r'(\d{4})', date_str)
            yr = int(yr_m.group(1)) if yr_m else now_dt.year
            # Séparer début et fin sur le '-'
            parts = re.split(r'-', date_str.replace(yr_m.group(0),'').strip().rstrip(',') if yr_m else date_str)
            end_raw = parts[-1].strip()
            # Si end_raw est juste un numéro, prendre le mois du début
            if re.match(r'^\d+$', end_raw):
                mon_m = re.search(months_re, parts[0], re.IGNORECASE)
                if mon_m:
                    end_raw = mon_m.group(0) + ' ' + end_raw
            try:
                return datetime.datetime.strptime(f"{end_raw} {yr}", "%b %d %Y")
            except:
                return None

        lines = [l.strip() for l in text.split('\n')]
        i = 0
        while i < len(lines) and len(items) < limit:
            line = lines[i]
            dm = date_line_re.match(line)
            if dm:
                date_str = dm.group(1)
                end_dt = parse_end_date(date_str)
                # Ignorer les expéditions terminées
                if end_dt and end_dt < now_dt - datetime.timedelta(days=1):
                    i += 1
                    continue
                # Lire les lignes suivantes
                dxcc = callsign = qsl = source = info = ''
                j = i + 1
                while j < len(lines) and j < i + 10:
                    l = lines[j]
                    if re.match(r'^DXCC:\s*', l, re.I):
                        val = re.sub(r'^DXCC:\s*', '', l, flags=re.I).strip()
                        # Valeur peut être sur la ligne suivante si vide
                        if not val and j+1 < len(lines):
                            val = lines[j+1].strip()
                        dxcc = val
                    elif re.match(r'^Callsign:\s*', l, re.I):
                        val = re.sub(r'^Callsign:\s*', '', l, flags=re.I).strip()
                        if not val and j+1 < len(lines):
                            val = lines[j+1].strip()
                        callsign = val
                    elif re.match(r'^QSL:\s*', l, re.I):
                        val = re.sub(r'^QSL:\s*', '', l, flags=re.I).strip()
                        if not val and j+1 < len(lines):
                            val = lines[j+1].strip()
                        qsl = val
                    elif re.match(r'^Source:\s*', l, re.I):
                        # Source: valeur parfois sur la ligne suivante
                        val = re.sub(r'^Source:\s*', '', l, flags=re.I).strip()
                        if not val and j+1 < len(lines):
                            src_name = lines[j+1].strip()
                            src_date = lines[j+2].strip() if j+2 < len(lines) else ''
                            val = f"{src_name} {src_date}".strip()
                        source = val
                    elif re.match(r'^Info:\s*', l, re.I):
                        info = re.sub(r'^Info:\s*', '', l, flags=re.I).strip()
                    elif date_line_re.match(l):
                        break  # prochaine entrée
                    j += 1

                if not callsign:
                    i += 1
                    continue

                # Construire date lisible
                end_label = end_dt.strftime("→ %d %b %Y") if end_dt else date_str
                title = f"{callsign} · {dxcc} · {end_label}"
                summary_parts = []
                if info:    summary_parts.append(info[:150])
                if qsl:     summary_parts.append(f"QSL: {qsl}")
                if source:  summary_parts.append(f"Source: {source}")

                items.append({
                    "title": title,
                    "link": "https://www.ng3k.com/misc/adxo.html",
                    "published_utc": end_dt.strftime("%Y-%m-%dT00:00:00Z") if end_dt else None,
                    "summary": " · ".join(summary_parts),
                })
                i = j
            else:
                i += 1

    elif source_id == "arrl":
        import re, datetime
        # Structure ARRL News (arrl.org/news) : chaque article est un <li>/<div>
        # avec un lien titre + une date "MM/DD/YYYY" juste avant + un résumé texte.
        # On cherche les liens vers /news/<slug> (articles individuels), en excluant
        # les liens de navigation (/news, /news/index/page:N, /news-tips, etc.)
        seen_links = set()
        for a in soup.select("a[href*='/news/']"):
            href = a.get("href") or ""
            if not re.search(r'/news/[a-z0-9][a-z0-9-]{10,}$', href, re.IGNORECASE):
                continue  # exclut /news, /news/index/page:2/model:News, /news-tips...
            if href in seen_links:
                continue
            title = _strip_html(a.get_text(strip=True))
            if not title or len(title) < 8:
                continue
            seen_links.add(href)

            # Chercher la date "MM/DD/YYYY" dans le texte environnant (bloc parent)
            published = None
            parent_text = _strip_html(a.parent.get_text(" ", strip=True)) if a.parent else ""
            date_m = re.search(r'(\d{2})/(\d{2})/(\d{4})', parent_text)
            if date_m:
                try:
                    dt = datetime.datetime(int(date_m.group(3)), int(date_m.group(1)), int(date_m.group(2)))
                    published = dt.strftime("%Y-%m-%dT00:00:00Z")
                except ValueError:
                    pass

            # Résumé : texte du bloc parent, en retirant le titre et la date
            summary = parent_text
            if date_m:
                summary = summary.replace(date_m.group(0), "")
            summary = summary.replace(title, "").strip(" |")
            summary = re.sub(r'^#+\s*\|?\s*', '', summary).strip(" |")
            summary = summary[:300]

            items.append({
                "title": title,
                "link": href if href.startswith("http") else f"https://www.arrl.org{href}",
                "published_utc": published,
                "summary": summary,
            })
            if len(items) >= limit:
                break

    elif source_id == "dxmaps":
        for row in soup.select("table tr"):
            cols = row.find_all("td")
            if len(cols) < 2:
                continue
            title = _strip_html(cols[0].get_text(" ", strip=True))
            detail = _strip_html(cols[1].get_text(" ", strip=True))
            link_tag = cols[0].find("a") or cols[1].find("a")
            href = link_tag.get("href") if link_tag else None
            if not title:
                continue
            items.append({
                "title": title,
                "link": href,
                "published_utc": None,
                "summary": detail,
            })
            if len(items) >= limit:
                break

    elif source_id == "qo100dx":
        for entry in fetch_qo100_news(timeout=BRIEFING_FEED_TIMEOUT):
            items.append({
                "title":         entry.get("title") or "Sans titre",
                "link":          entry.get("link"),
                "published_utc": entry.get("date_str") or None,
                "summary":       entry.get("summary") or "",
            })
            if len(items) >= limit:
                break

    return items

def _build_briefing_payload(limit: int = BRIEFING_ITEM_LIMIT):
    sources = _load_briefing_sources()
    source_payloads = []
    combined_items = []
    now = time.time()

    for src in sources:
        fetched_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        items = []
        status = "ok"
        error = None

        try:
            source_type = src.get("type", "rss")
            if source_type == "html":
                source_id = src.get("id", "")
                html_text = ""
                if source_id != "qo100dx":
                    html_text = _fetch_html(src["url"])
                extracted = _extract_html_items(source_id, html_text, limit)
                if html_text and not extracted:
                    logger.warning(
                        f"_build_briefing_payload: source '{source_id}' — fetch OK "
                        f"({len(html_text)} octets reçus) mais 0 article extrait. "
                        f"Les sélecteurs CSS dans _extract_html_items() sont probablement "
                        f"obsolètes (structure HTML du site changée) — à vérifier."
                    )
                for entry in extracted:
                    items.append({
                        "title": entry.get("title") or "Sans titre",
                        "link": entry.get("link"),
                        "published_utc": entry.get("published_utc"),
                        "summary": entry.get("summary") or "",
                        "source_id": src.get("id"),
                        "timestamp": now,
                    })
            else:
                parsed = _fetch_feed(src["url"])
                entries = parsed.entries or []
                for entry in entries[: limit * 2]:
                    ts = _entry_timestamp(entry)
                    item = {
                        "title": _strip_html(entry.get("title", "Sans titre")) or "Sans titre",
                        "link": entry.get("link"),
                        "published_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
                        "summary": _entry_summary(entry),
                        "source_id": src.get("id"),
                        "timestamp": ts,
                    }
                    items.append(item)
            items.sort(key=lambda it: it["timestamp"], reverse=True)
            items = items[:limit]
            combined_items.extend(items)
        except Exception as exc:
            status = "error"
            error = str(exc)

        source_payloads.append({
            "id": src.get("id"),
            "name": src.get("name"),
            "url": src.get("url"),
            "site": src.get("site"),
            "status": status,
            "error": error,
            "fetched_utc": fetched_utc,
            "items": items,
        })

    combined_items.sort(key=lambda it: it["timestamp"], reverse=True)
    combined_items = combined_items[: limit * 2]

    for item in combined_items:
        item.pop("timestamp", None)

    payload = {
        "ok": True,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "cache": {
            "ttl_seconds": BRIEFING_CACHE_TTL,
            "generated_epoch": now,
        },
        "sources": source_payloads,
        "items": combined_items,
        "total_sources": len(source_payloads),
    }
    return payload

briefing_lock = threading.Lock()
briefing_cache = {
    "ts": 0.0,
    "payload": None,
}

# ═══════════════════════════════════════════════════════════
# WSJT-X UDP WORKER — Écoute le flux UDP WSJT-X sur le réseau
# Protocol: https://sourceforge.net/p/wsjt/wsjtx/ci/master/tree/Network/NetworkMessage.hpp
# ═══════════════════════════════════════════════════════════

import socket
import struct

# État WSJT-X partagé (thread-safe via lock)
wsjtx_lock = threading.Lock()
wsjtx_state = {
    "connected":    False,          # Heartbeat reçu récemment
    "last_seen":    0.0,            # Timestamp dernier message
    "dial_freq":    None,           # Fréquence VFO en Hz
    "mode":         None,           # Mode actif (FT8, FT4, …)
    "dx_call":      "",             # DXCall courant dans WSJT-X
    "tx_enabled":   False,          # TX activé
    "decoding":     False,          # Décodage en cours
    "version":      "",             # Version WSJT-X
    "last_decode":  None,           # Dernier décodage (dict)
    "session_spots": 0,             # Spots injectés cette session
}

# Buffer spécifique spots WSJT-X (pour affichage dédié)
wsjtx_spots = deque(maxlen=200)

# ── Module Météo : échantillon SNR non filtré (tous décodages, pas seulement CQ/calling_me) ──
# Utilisé pour la moyenne glissante SNR (indicateur de bruit local), cf. compute_noise_correlation()
snr_buffer = deque(maxlen=600)  # ~ jusqu'à 20-30 min de décodages selon le débit
snr_buffer_lock = threading.Lock()

def get_snr_rolling_average(window_start_s=0, window_end_s=1200):
    """Moyenne SNR sur une fenêtre glissante définie en secondes dans le passé.
    Par défaut : moyenne sur les 20 dernières minutes (0 à 1200s en arrière).
    Pour comparer avec 'il y a 1h', appeler avec window_start_s=3600, window_end_s=4200."""
    now = time.time()
    lo = now - window_end_s
    hi = now - window_start_s
    with snr_buffer_lock:
        values = [snr for (ts, snr, mode, band) in snr_buffer if lo <= ts <= hi]
    if not values:
        return None
    return round(sum(values) / len(values), 1)

def get_snr_reference_band(window_s=1200):
    """Bande la plus représentée dans l'échantillon SNR récent (20 min par défaut).
    C'est LA bande à laquelle se rapporte la moyenne SNR affichée — indispensable
    pour que l'utilisateur sache de quoi parle le pavé corrélation (le SNR n'a pas
    le même sens/niveau de bruit d'une bande à l'autre)."""
    now = time.time()
    lo = now - window_s
    with snr_buffer_lock:
        bands = [band for (ts, snr, mode, band) in snr_buffer if ts >= lo and band]
    if not bands:
        return None
    return Counter(bands).most_common(1)[0][0]

# ── Constantes message type WSJT-X ──
WSJTX_MAGIC   = 0xadbccbda
WSJTX_SCHEMA  = 2
MSG_HEARTBEAT = 0
MSG_STATUS    = 1
MSG_DECODE    = 2
MSG_CLEAR     = 3
MSG_REPLY     = 4
MSG_QSOLOG    = 5
MSG_CLOSE     = 6
MSG_REPLAY    = 7
MSG_HALT      = 8
MSG_FREETEXT  = 9


def _wsjtx_read_utf8(data, offset):
    """Lit une QString Qt (uint32 length + bytes) depuis data[offset]."""
    if offset + 4 > len(data):
        return "", offset + 4
    length = struct.unpack_from(">I", data, offset)[0]
    offset += 4
    if length == 0xFFFFFFFF:   # null QString
        return "", offset
    if offset + length > len(data):
        return "", offset + length
    text = data[offset:offset + length].decode("utf-8", errors="replace")
    return text, offset + length


def _wsjtx_read_bool(data, offset):
    if offset >= len(data):
        return False, offset + 1
    return bool(data[offset]), offset + 1


def _wsjtx_read_uint8(data, offset):
    if offset >= len(data):
        return 0, offset + 1
    return data[offset], offset + 1


def _wsjtx_read_uint32(data, offset):
    if offset + 4 > len(data):
        return 0, offset + 4
    return struct.unpack_from(">I", data, offset)[0], offset + 4


def _wsjtx_read_int32(data, offset):
    if offset + 4 > len(data):
        return 0, offset + 4
    return struct.unpack_from(">i", data, offset)[0], offset + 4


def _wsjtx_read_uint64(data, offset):
    if offset + 8 > len(data):
        return 0, offset + 8
    return struct.unpack_from(">Q", data, offset)[0], offset + 8


def _wsjtx_read_double(data, offset):
    if offset + 8 > len(data):
        return 0.0, offset + 8
    return struct.unpack_from(">d", data, offset)[0], offset + 8


def _wsjtx_parse_header(data):
    """Retourne (magic, schema, msg_type, id_str, next_offset) ou None."""
    if len(data) < 8:
        return None
    magic, schema = struct.unpack_from(">II", data, 0)
    if magic != WSJTX_MAGIC:
        return None
    msg_type, offset = _wsjtx_read_uint32(data, 8)
    id_str, offset = _wsjtx_read_utf8(data, offset)
    return magic, schema, msg_type, id_str, offset


def _wsjtx_parse_heartbeat(data, offset):
    """MSG_HEARTBEAT : max_schema(uint32) + version(utf8) + revision(utf8)"""
    max_schema, offset = _wsjtx_read_uint32(data, offset)
    version, offset   = _wsjtx_read_utf8(data, offset)
    revision, offset  = _wsjtx_read_utf8(data, offset)
    return {"max_schema": max_schema, "version": version, "revision": revision}


def _wsjtx_parse_status(data, offset):
    """MSG_STATUS — état complet de la radio."""
    dial_freq, offset  = _wsjtx_read_uint64(data, offset)
    mode, offset       = _wsjtx_read_utf8(data, offset)
    dx_call, offset    = _wsjtx_read_utf8(data, offset)
    report, offset     = _wsjtx_read_utf8(data, offset)
    tx_mode, offset    = _wsjtx_read_utf8(data, offset)
    tx_enabled, offset = _wsjtx_read_bool(data, offset)
    transmitting, offset = _wsjtx_read_bool(data, offset)
    decoding, offset   = _wsjtx_read_bool(data, offset)
    return {
        "dial_freq":    dial_freq,
        "mode":         mode,
        "dx_call":      dx_call,
        "tx_enabled":   tx_enabled,
        "transmitting": transmitting,
        "decoding":     decoding,
    }


def _wsjtx_parse_decode(data, offset):
    """MSG_DECODE — un décodage FT8/FT4/JT65/…"""
    is_new,  offset = _wsjtx_read_bool(data, offset)
    time_ms, offset = _wsjtx_read_uint32(data, offset)   # ms depuis minuit UTC
    snr,     offset = _wsjtx_read_int32(data, offset)
    dt,      offset = _wsjtx_read_double(data, offset)
    delta_f, offset = _wsjtx_read_uint32(data, offset)   # Hz
    mode,    offset = _wsjtx_read_utf8(data, offset)
    message, offset = _wsjtx_read_utf8(data, offset)
    low_conf,offset = _wsjtx_read_bool(data, offset)
    return {
        "is_new":   is_new,
        "time_ms":  time_ms,
        "snr":      snr,
        "dt":       dt,
        "delta_f":  delta_f,
        "mode":     mode,
        "message":  message,
        "low_conf": low_conf,
    }


def _wsjtx_parse_qsolog(data, offset):
    """MSG_QSOLOG — QSO loggé."""
    # time_off (QDateTime = uint64 julian day + uint32 ms + uint8 tz)
    jd,     offset = _wsjtx_read_uint64(data, offset)
    ms_day, offset = _wsjtx_read_uint32(data, offset)
    tz,     offset = _wsjtx_read_uint8(data, offset)
    dx_call,offset = _wsjtx_read_utf8(data, offset)
    mode,   offset = _wsjtx_read_utf8(data, offset)
    report_sent, offset = _wsjtx_read_utf8(data, offset)
    report_rcvd, offset = _wsjtx_read_utf8(data, offset)
    tx_power,    offset = _wsjtx_read_utf8(data, offset)
    comments,    offset = _wsjtx_read_utf8(data, offset)
    name,        offset = _wsjtx_read_utf8(data, offset)
    return {
        "dx_call":      dx_call,
        "mode":         mode,
        "report_sent":  report_sent,
        "report_rcvd":  report_rcvd,
        "comments":     comments,
    }


def _maidenhead_to_latlon(grid):
    """Convertit un locator Maidenhead (4 ou 6 caractères) en (lat, lon) centre de la case."""
    grid = grid.strip().upper()
    if len(grid) < 4:
        return None, None
    try:
        # Paire de chiffres 1 : champs (A-R)
        lon = (ord(grid[0]) - ord('A')) * 20 - 180
        lat = (ord(grid[1]) - ord('A')) * 10 - 90
        # Paire de chiffres 2 : sous-champs (0-9)
        lon += int(grid[2]) * 2
        lat += int(grid[3]) * 1
        # Centre de la case 4 caractères
        lon += 1.0
        lat += 0.5
        if len(grid) >= 6:
            # Paire de chiffres 3 : cases (A-X)
            lon += (ord(grid[4]) - ord('A')) * (2 / 24) - (2 / 24) * 12
            lat += (ord(grid[5]) - ord('A')) * (1 / 24) - (1 / 24) * 12
            # Centre de la case 6 caractères
            lon += 1 / 24
            lat += 0.5 / 24
        return round(lat, 4), round(lon, 4)
    except Exception:
        return None, None


def _wsjtx_extract_locator(msg):
    """Extrait le locator Maidenhead depuis un message FT8.
    Ex: 'CQ W6GY DM04' → 'DM04'
        'CQ DX K1JT FN20' → 'FN20'
    """
    import re
    LOCATOR_RE = re.compile(r'^[A-R]{2}\d{2}([A-X]{2})?$')
    parts = msg.strip().upper().split()
    for p in reversed(parts):   # le locator est souvent le dernier token
        if LOCATOR_RE.match(p):
            return p
    return None


def _wsjtx_extract_callsign_from_message(msg):
    """Extrait le callsign DX depuis un message FT8/FT4.
    Formats supportés :
      CQ CALL LOC       → CALL
      CQ DX CALL LOC    → CALL
      CQ EU CALL LOC    → CALL (modificateurs régionaux)
      CALL1 CALL2 ...   → CALL2 (stations m'appelant)
    """
    import re
    msg = msg.strip().upper()
    parts = msg.split()
    if not parts:
        return None

    # Pattern callsign valide (pas un locator)
    CALL_RE  = re.compile(r'^[A-Z0-9]{1,3}[0-9][A-Z]{1,5}(/[A-Z0-9]+)?$')
    LOCATOR  = re.compile(r'^[A-Z]{2}\d{2}([A-Z]{2})?$')
    MODIFIER = re.compile(r'^(DX|NA|SA|EU|AS|AF|OC|AN|[A-Z]{1,2})$')

    def is_call(s):
        return bool(CALL_RE.match(s)) and not LOCATOR.match(s)

    if parts[0] == 'CQ':
        # Parcourir les tokens après CQ — ignorer les modificateurs et locators
        for tok in parts[1:]:
            if LOCATOR.match(tok):
                continue
            if MODIFIER.match(tok) and not is_call(tok):
                continue
            if is_call(tok):
                return tok
        return None

    # Stations qui m'appellent : "MY_CALL THEIRCALL ..."
    # Le 2ème token est souvent l'appelant
    if len(parts) >= 2 and is_call(parts[1]):
        return parts[1]

    return None


def _wsjtx_inject_spot(decode, dial_freq_hz, wsjtx_mode):
    """Transforme un décodage WSJT-X en spot et l'injecte dans spots_buffer."""
    msg = decode.get("message", "").strip()
    if not msg or decode.get("low_conf"):
        return

    # Injecter uniquement :
    # 1. CQ — stations qui cherchent un correspondant
    # 2. Stations qui m'appellent directement (contiennent MY_CALL)
    msg_up = msg.upper()
    is_cq         = msg_up.startswith("CQ")
    is_calling_me = MY_CALL.upper() in msg_up
    if not is_cq and not is_calling_me:
        return

    dx_call = _wsjtx_extract_callsign_from_message(msg)
    if not dx_call or len(dx_call) < 3:
        return
    if dx_call.upper() == MY_CALL.upper():
        return  # ne pas se spotter soi-même

    # Fréquence : VFO + offset delta_f
    freq_hz  = (dial_freq_hz or 0) + decode.get("delta_f", 0)
    freq_khz = freq_hz / 1000.0
    freq_str = f"{freq_khz:.1f}"

    # Bande et mode
    band, mode = get_band_and_mode_smart(freq_khz / 1000.0, wsjtx_mode or decode.get("mode", "FT8"))

    # Infos géographiques — priorité : 1) Locator Maidenhead 2) Zone d'appel 3) Centroïde pays
    info    = get_country_info(dx_call)
    country = info.get("c", "Unknown")
    locator = _wsjtx_extract_locator(msg)
    locator_used = False

    if locator:
        loc_lat, loc_lon = _maidenhead_to_latlon(locator)
        if loc_lat is not None and loc_lon is not None:
            lat, lon = loc_lat, loc_lon
            locator_used = True
        else:
            lat, lon, _ = get_precise_latlon(dx_call)
    else:
        lat, lon, _ = get_precise_latlon(dx_call)

    if not lat and not lon:
        lat = info.get("lat", 0.0)
        lon = info.get("lon", 0.0)

    if not lat and not lon:
        return   # Pas de données géo

    dist_km = 0.0
    try:
        dist_km = calculate_distance(user_lat, user_lon, lat, lon)
    except Exception:
        pass

    spd_score = calculate_spd_score(dx_call, band, mode, msg, country, dist_km)
    color     = BAND_COLORS.get(band, "#00f3ff")

    snr = decode.get("snr", 0)
    now = time.time()

    spot_obj = {
        "timestamp":   now,
        "time":        time.strftime("%H:%M"),
        "freq":        freq_str,
        "dx_call":     dx_call,
        "band":        band,
        "mode":        mode,
        "country":     country,
        "lat":         lat,
        "lon":         lon,
        "score":       spd_score,
        "is_wanted":   spd_score >= SPD_THRESHOLD,
        "is_rare":     is_rare_prefix(dx_call),
        "via_eme":     False,
        "color":       color,
        "type":        "VHF" if band in VHF_BANDS else "HF",
        "distance_km": dist_km,
        "spot_id":     f"{dx_call}-wsjtx-{int(now)}",
        "source":      "WSJTX",
        "locator":     locator or "",
        "locator_used": locator_used,
        "calling_me":  is_calling_me,
        "snr":         snr,
        "comment":     f"SNR {snr:+d}dB via WSJT-X",
    }

    # Déduplication : même call dans les 30 dernières secondes (2 périodes FT8)
    # Vérifie les 50 derniers spots pour couvrir les sessions actives
    with threading.Lock():
        for s in list(wsjtx_spots)[-50:]:
            if s.get("dx_call") == dx_call and (now - s.get("timestamp", 0)) < 30:
                return

    spots_buffer.append(spot_obj)
    wsjtx_spots.append(spot_obj)
    # Mettre à jour l'activité watchlist
    _dx = spot_obj.get("dx_call", "").upper()
    if _dx and _dx in watchlist:
        with wl_activity_lock:
            entry = wl_activity.get(_dx, {})
            if isinstance(entry, dict):
                entry["last_spot"] = spot_obj.get("timestamp", time.time())
            else:
                entry = {"last_spot": spot_obj.get("timestamp", time.time()), "end_date": None, "added": time.time()}
            wl_activity[_dx] = entry

    with wsjtx_lock:
        wsjtx_state["session_spots"] += 1

    tag = " [⚡ CALLING ME]" if is_calling_me else ""
    loc_tag = f" [{locator}→precise]" if locator_used else " [country centroid]"
    logger.info(f"WSJTX SPOT{tag}: {dx_call} ({country}) {band} {mode} SNR{snr:+d}dB {freq_str}kHz{loc_tag}")


def wsjtx_worker():
    """Thread UDP — écoute les messages WSJT-X et les traite."""
    threading.current_thread().name = "WSJTXWorker"
    log = logging.getLogger(__name__)

    if not WSJTX_ENABLED:
        log.info("WSJTXWorker désactivé (WSJTX_ENABLED=False)")
        return

    sock = None
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", WSJTX_UDP_PORT))
            sock.settimeout(30.0)
            log.info(f"WSJTXWorker en écoute sur UDP:{WSJTX_UDP_PORT}")

            while True:
                try:
                    data, addr = sock.recvfrom(65535)
                except socket.timeout:
                    # Vérifier si connexion perdue
                    with wsjtx_lock:
                        if wsjtx_state["connected"] and (time.time() - wsjtx_state["last_seen"]) > 60:
                            wsjtx_state["connected"] = False
                            log.info("WSJTXWorker: WSJT-X déconnecté (timeout 60s)")
                    continue

                result = _wsjtx_parse_header(data)
                if result is None:
                    continue

                _, schema, msg_type, wsjtx_id, offset = result
                now = time.time()

                with wsjtx_lock:
                    wsjtx_state["last_seen"] = now

                if msg_type == MSG_HEARTBEAT:
                    hb = _wsjtx_parse_heartbeat(data, offset)
                    with wsjtx_lock:
                        wsjtx_state["connected"] = True
                        wsjtx_state["version"]   = hb.get("version", "")
                    log.info(f"WSJTXWorker: Heartbeat reçu — WSJT-X {hb.get('version','')}")

                elif msg_type == MSG_STATUS:
                    st = _wsjtx_parse_status(data, offset)
                    with wsjtx_lock:
                        wsjtx_state["connected"]  = True
                        wsjtx_state["dial_freq"]  = st["dial_freq"]
                        wsjtx_state["mode"]       = st["mode"]
                        wsjtx_state["dx_call"]    = st["dx_call"]
                        wsjtx_state["tx_enabled"] = st["tx_enabled"]
                        wsjtx_state["decoding"]   = st["decoding"]

                elif msg_type == MSG_DECODE:
                    dec = _wsjtx_parse_decode(data, offset)
                    with wsjtx_lock:
                        wsjtx_state["last_decode"] = dec
                        dial_freq = wsjtx_state["dial_freq"]
                        wsjtx_mode = wsjtx_state["mode"]

                    # Accumule TOUS les décodages (pas seulement CQ/calling_me) pour la
                    # moyenne glissante SNR utilisée par le module Météo (corrélation bruit).
                    # La bande est dérivée du dial_freq courant — c'est la bande de référence
                    # affichée dans le pavé "Corrélation bruit/météo".
                    try:
                        snr_band = find_band((dial_freq or 0) / 1000.0) if dial_freq else None
                        with snr_buffer_lock:
                            snr_buffer.append((time.time(), dec.get("snr", 0), wsjtx_mode, snr_band))
                    except Exception:
                        pass

                    _wsjtx_inject_spot(dec, dial_freq, wsjtx_mode)

                elif msg_type == MSG_QSOLOG:
                    qso = _wsjtx_parse_qsolog(data, offset)
                    log.info(f"WSJTXWorker: QSO loggé — {qso.get('dx_call','?')} {qso.get('mode','?')}")

                elif msg_type == MSG_CLOSE:
                    with wsjtx_lock:
                        wsjtx_state["connected"] = False
                    log.info("WSJTXWorker: WSJT-X fermé (MSG_CLOSE)")

        except OSError as e:
            log.warning(f"WSJTXWorker socket error: {e}")
            if sock:
                try: sock.close()
                except: pass
            time.sleep(10)
        except Exception as e:
            log.error(f"WSJTXWorker erreur inattendue: {e}", exc_info=True)
            time.sleep(15)


# ── API WSJT-X ──────────────────────────────────────────────

@app.route("/api/wsjtx/status")
def api_wsjtx_status():
    """Retourne l'état actuel de WSJT-X."""
    with wsjtx_lock:
        st = dict(wsjtx_state)
    # Fréquence en MHz pour lisibilité
    if st["dial_freq"]:
        st["dial_mhz"] = round(st["dial_freq"] / 1_000_000, 6)
    st["enabled"] = WSJTX_ENABLED
    return jsonify(st)


@app.route("/api/wsjtx/spots")
def api_wsjtx_spots():
    """Retourne les derniers spots WSJT-X (max 50)."""
    now = time.time()
    spots = [
        s for s in wsjtx_spots
        if (now - s.get("timestamp", 0)) < WSJTX_SPOT_LIFETIME
    ]
    spots.sort(key=lambda s: s.get("timestamp", 0), reverse=True)
    return jsonify({"spots": spots[:50], "count": len(spots)})


def briefing_refresh_worker():
    logger = logging.getLogger(__name__)
    while True:
        now = time.time()
        try:
            payload = _build_briefing_payload(limit=BRIEFING_ITEM_LIMIT)
            payload["cache"]["age_seconds"] = 0
            payload["cache"]["next_refresh_utc"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + BRIEFING_CACHE_TTL)
            )
            with briefing_lock:
                briefing_cache["ts"] = now
                briefing_cache["payload"] = payload
            logger.info("Briefing cache refreshed.")
        except Exception as exc:
            logger.warning(f"Briefing refresh failed: {exc}")
        time.sleep(BRIEFING_CACHE_TTL)


@app.route('/api/briefing/debug')
def briefing_debug():
    """Debug: montre le raw HTML + items parsés d'une source briefing."""
    source_id = request.args.get('source', 'ng3k')
    sources = _load_briefing_sources()
    src = next((s for s in sources if s['id'] == source_id), None)
    if not src:
        return jsonify({'error': f'source {source_id} introuvable'})
    try:
        if source_id == 'qo100dx':
            entries = fetch_qo100_news(timeout=15)
            return jsonify({
                'source': source_id,
                'entries_count': len(entries),
                'entries_sample': entries[:3],
            })
        html = _fetch_html(src['url'])
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        # Montrer les tags article trouvés
        articles = soup.select('article, .post, .entry, div.item')
        article_info = []
        for a in articles[:3]:
            h = a.select_one('h1 a, h2 a, h3 a, h4 a')
            p = a.select_one('p')
            article_info.append({
                'tag': a.name,
                'classes': a.get('class', []),
                'title': h.get_text(strip=True) if h else None,
                'first_p': p.get_text(strip=True)[:200] if p else None,
                'html_snippet': str(a)[:400],
            })
        # Items parsés
        items = _extract_html_items(source_id, html, 5)
        return jsonify({
            'source': source_id,
            'url': src['url'],
            'html_len': len(html),
            'articles_found': len(articles),
            'article_samples': article_info,
            'parsed_items': items[:3],
        })
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()})

@app.route("/api/briefing/refresh", methods=["POST"])
@require_api_token
def briefing_force_refresh():
    """Force le rechargement du cache briefing."""
    with briefing_lock:
        briefing_cache["ts"] = 0.0
        briefing_cache["payload"] = None
    logger.info("Briefing cache cleared — will refresh on next request")
    return jsonify({"ok": True, "message": "Cache vidé, rechargement au prochain accès"})

@app.route("/briefing")
@app.route("/briefing.html")
def briefing_page():
    return render_template("briefing.html")

@app.route("/api/briefing.json")
def api_briefing():
    limit = int(request.args.get("limit", BRIEFING_ITEM_LIMIT))
    force = request.args.get("force") in ("1", "true", "yes")
    now = time.time()

    with briefing_lock:
        cache_age = now - (briefing_cache.get("ts") or 0.0)
        cached = briefing_cache.get("payload")
        if (not force) and cached is not None and cache_age < BRIEFING_CACHE_TTL:
            cached["cache"]["age_seconds"] = int(cache_age)
            cached["cache"]["next_refresh_utc"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(briefing_cache["ts"] + BRIEFING_CACHE_TTL)
            )
            return jsonify(cached)

    payload = _build_briefing_payload(limit=limit)
    payload["cache"]["age_seconds"] = 0
    payload["cache"]["next_refresh_utc"] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + BRIEFING_CACHE_TTL)
    )
    with briefing_lock:
        briefing_cache["ts"] = now
        briefing_cache["payload"] = payload
    return jsonify(payload)



@app.route("/api/weather/local.json")
def api_weather_local():
    """Snapshot des conditions locales (Open-Meteo, cache 10 min) + tendance
    barométrique sur ~2h (indicateur météo réel : une baisse rapide de
    pression est un signe fiable de dégradation à venir)."""
    data = weather_cache.get("data")
    if data is None:
        return jsonify({"ok": False, "error": "Pas encore de données météo disponibles"}), 503
    return jsonify({
        "ok": True,
        **data,
        "pressure_trend": get_pressure_trend(),
        "fetched_at": weather_cache.get("ts"),
        "age_s": int(time.time() - weather_cache.get("ts", time.time())),
    })


@app.route("/api/weather/lightning.json")
def api_weather_lightning():
    """Impacts de foudre de la dernière heure dans le rayon d'intérêt."""
    _lightning_prune()
    with lightning_lock:
        strikes = sorted(lightning_buffer, key=lambda s: s["ts"], reverse=True)
    now = time.time()
    for s in strikes:
        s["age_s"] = int(now - s["ts"])
    return jsonify({
        "ok": True,
        "count_1h": len(strikes),
        "strikes": strikes[:100],  # cap raisonnable pour le payload JSON
        "radius_km": LIGHTNING_RADIUS_KM,
        "ts": now,
    })


@app.route("/api/weather/wspr.json")
def api_weather_wspr():
    """Snapshot WSPR courant (débogage/transparence — source prioritaire
    de la corrélation bruit/météo)."""
    data = wspr_cache.get("data")
    if data is None:
        return jsonify({"ok": False, "error": "Pas encore de données WSPR disponibles"}), 503
    return jsonify({
        "ok": True,
        **data,
        "radius_km": WSPR_RADIUS_KM,
        "fetched_at": wspr_cache.get("ts"),
        "age_s": int(time.time() - wspr_cache.get("ts", time.time())),
    })


@app.route("/api/weather/synthesis.json")
def api_weather_synthesis():
    """Jauge de synthèse HF/VHF pour le nouveau dashboard météo."""
    return jsonify(compute_global_synthesis())


@app.route("/api/weather/band_activity.json")
def api_weather_band_activity():
    """Activité par bande (spots/24h), séparée HF/VHF."""
    return jsonify(get_band_activity_24h())


@app.route("/api/weather/beacons.json")
def api_weather_beacons():
    """Balises VHF/UHF/SHF réellement spotées par des stations proches du QTH."""
    events = get_beacon_reception_events()
    with beacon_update_lock:
        status = dict(beacon_update_status)
    return jsonify({
        "received": events["events"],
        "info": events["info"],
        "update_status": status,
        "ts": time.time(),
    })


@app.route("/api/weather/alerts.json")
def api_weather_alerts():
    """Alertes dérivées des données réelles (QRN, VHF, ducting, pression)."""
    return jsonify({"alerts": get_weather_alerts(), "ts": time.time()})


@app.route("/api/weather/correlation.json")
def api_weather_correlation():
    """Synthèse texte de corrélation bruit local / activité électrique."""
    return jsonify(compute_noise_correlation())


@app.route("/weather")
def weather_page():
    return render_template("weather.html", version=APP_VERSION, my_call=MY_CALL,
                           qth_lat=user_lat, qth_lon=user_lon,
                           lightning_radius_km=LIGHTNING_RADIUS_KM,
                           band_colors=BAND_COLORS)


@app.route('/history.json')
def get_history():
    """Retourne l'historique 30min/12h avec détails : bande dominante par slot."""
    now_utc = time.gmtime(time.time())
    current_hour = now_utc.tm_hour
    current_minute = now_utc.tm_min
    current_slot = ((current_hour * 2) + (current_minute // 30)) % HISTORY_SLOTS

    # Labels des 24 slots (H-00:00 = plus récent)
    labels = []
    slot_details = []  # [{band: "20m", count: 45}, ...]
    for i in range(HISTORY_SLOTS):
        slot = (current_slot - i + HISTORY_SLOTS) % HISTORY_SLOTS
        hours_ago = (HISTORY_SLOTS - 1 - i) * HISTORY_PERIOD_MINUTES // 60
        minutes_ago = (HISTORY_SLOTS - 1 - i) * HISTORY_PERIOD_MINUTES % 60
        labels.append(f"H-{hours_ago:02d}:{minutes_ago:02d}")
        
        # Trouver la bande dominante pour ce slot
        with history_lock:
            band_counts = {}
            for band in HISTORY_BANDS:
                band_counts[band] = history_30min.get(band, [0]*HISTORY_SLOTS)[slot] or 0
            
            dominant_band = max(band_counts, key=band_counts.get) if band_counts else "?"
            dominant_count = band_counts.get(dominant_band, 0)
        
        slot_details.append({
            "band": dominant_band,
            "count": dominant_count
        })

    with history_lock:
        data = {band: list(hist) for band, hist in history_30min.items()}

    # Rotate data to show most recent first
    current_data = {}
    for band in HISTORY_BANDS:
        rotated = data[band][current_slot:] + data[band][:current_slot]
        current_data[band] = rotated

    return jsonify({
        "labels": labels,
        "data": current_data,
        "slot_details": slot_details,
        "ts": time.time()
    })

@app.route('/live_bands.json')
def get_live_bands_data():
    now = time.time()
    active_spots = [s for s in spots_buffer if (now - s['timestamp']) < SPOT_LIFETIME]
    hf_spots = [s for s in active_spots if s['type'] == 'HF']
    vhf_spots = [s for s in active_spots if s['type'] == 'VHF']
    hf_counts = Counter(s['band'] for s in hf_spots if s['band'] in HF_BANDS)
    vhf_counts = Counter(s['band'] for s in vhf_spots if s['band'] in VHF_BANDS)

    hf_data = {
        "labels": [b for b in HF_BANDS if hf_counts[b] > 0],
        "data": [hf_counts[b] for b in HF_BANDS if hf_counts[b] > 0],
        "colors": [BAND_COLORS[b] for b in HF_BANDS if hf_counts[b] > 0]
    }
    vhf_data = {
        "labels": [b for b in VHF_BANDS if vhf_counts[b] > 0],
        "data": [vhf_counts[b] for b in VHF_BANDS if vhf_counts[b] > 0],
        "colors": [BAND_COLORS[b] for b in VHF_BANDS if vhf_counts[b] > 0]
    }
    return jsonify({"hf": hf_data, "vhf": vhf_data})





# Cache de vérification de mise à jour (évite le rate-limiting GitHub)
_update_cache = {"data": None, "ts": 0}
UPDATE_CACHE_TTL = 24 * 3600  # 24 heures

@app.route('/api/check_update')
def check_update():
    """Vérifie si une nouvelle version est disponible sur GitHub (cache 6h)."""
    GITHUB_VERSION_URL = "https://raw.githubusercontent.com/F1SMV/Spot-Watcher-DX/main/version.json"
    global _update_cache

    now = time.time()
    if _update_cache["data"] and (now - _update_cache["ts"]) < UPDATE_CACHE_TTL:
        return jsonify(_update_cache["data"])

    try:
        req = urllib.request.Request(GITHUB_VERSION_URL, headers={'User-Agent': 'Spot-Watcher-DX/6.6'})
        with urllib.request.urlopen(req, timeout=10) as r:
            remote_data = json.loads(r.read().decode('utf-8'))

        remote_version = remote_data.get("version", "0.0.0")
        current_version = APP_VERSION.split()[-1]

        # Comparaison sémantique : le bandeau n'apparaît que si GitHub
        # propose une version STRICTEMENT supérieure à la locale.
        # Évite les faux positifs quand on tourne sur une version locale
        # plus récente que le dépôt (ex. v10.0 local vs v9.5 sur GitHub).
        def _ver_tuple(v):
            try:
                return tuple(int(x) for x in v.strip().split("."))
            except Exception:
                return (0, 0, 0)

        update_available = _ver_tuple(remote_version) > _ver_tuple(current_version)

        result = {
            "update_available": update_available,
            "current_version": current_version,
            "latest_version": remote_version,
            "release_date": remote_data.get("release_date"),
            "changelog_url": remote_data.get("changelog_url"),
            "download_url": remote_data.get("download_url")
        }
        _update_cache = {"data": result, "ts": now}
        return jsonify(result)

    except Exception as e:
        logger.warning(f"Impossible de vérifier les mises à jour: {e}")
        # En cas d'erreur, retourner le cache même expiré s'il existe
        if _update_cache["data"]:
            return jsonify(_update_cache["data"])
        return jsonify({"update_available": False, "error": str(e)})


# ============================================================
# VOACAP-LIKE PROPAGATION ESTIMATE
# Modèle simplifié basé sur SFI/Kp (W6ELprop-inspired)
# Calcul local, pas de dépendance externe
# ============================================================

# Coordonnées des zones RX cibles
VOACAP_ZONES = {
    'EU': {'name': 'Europe',          'lat': 50.0,  'lon': 10.0},
    'NA': {'name': 'Amérique du Nord','lat': 40.0,  'lon': -95.0},
    'SA': {'name': 'Amérique du Sud', 'lat': -15.0, 'lon': -60.0},
    'AS': {'name': 'Asie',            'lat': 35.0,  'lon': 105.0},
    'OC': {'name': 'Océanie',         'lat': -25.0, 'lon': 135.0},
    'AF': {'name': 'Afrique',         'lat': 0.0,   'lon': 20.0},
}

# Bandes HF radioamateur (MHz)
VOACAP_BANDS = [3.5, 7.0, 10.1, 14.0, 18.1, 21.0, 24.9, 28.0]
VOACAP_BAND_LABELS = ['80m','40m','30m','20m','17m','15m','12m','10m']

def _voacap_muf(sfi, dist_km):
    """Estime la MUF selon SFI et distance (formule empirique simplifiée)."""
    # MUF de base augmente avec le SFI
    base_muf = 5.0 + (sfi - 60) * 0.18
    # Correction distance : trajets courts favorisent les hautes fréquences
    if dist_km < 500:
        dist_factor = 0.6
    elif dist_km < 2000:
        dist_factor = 0.8 + (dist_km - 500) / 7500
    elif dist_km < 8000:
        dist_factor = 1.0 + (dist_km - 2000) / 20000
    else:
        dist_factor = 1.3
    return min(35.0, max(4.0, base_muf * dist_factor))

def _voacap_reliability(freq_mhz, muf, luf, hour_utc, dist_km, kp):
    """Calcule la fiabilité (0-1) pour une bande/heure donnée."""
    import math
    # Fenêtre MUF/LUF : fiabilité max au milieu
    if freq_mhz > muf * 1.15:
        return 0.0
    if freq_mhz < luf * 0.85:
        return 0.0

    # Score de base : position dans la fenêtre
    center = (muf + luf) / 2
    half = (muf - luf) / 2 if muf > luf else 1.0
    dist_from_center = abs(freq_mhz - center) / max(half, 0.1)
    base = max(0.0, 1.0 - dist_from_center ** 1.5)

    # Correction heure : nuit favorise les basses fréquences
    night = (hour_utc < 6 or hour_utc >= 20)
    if night and freq_mhz > 14:
        base *= max(0.1, 1.0 - (freq_mhz - 14) * 0.08)
    if not night and freq_mhz < 7:
        base *= max(0.1, 1.0 - (7 - freq_mhz) * 0.15)

    # Correction Kp : perturbations géomagnétiques réduisent la propagation
    if kp is not None:
        kp_val = float(kp)
        if kp_val >= 5:
            base *= max(0.05, 1.0 - (kp_val - 4) * 0.18)

    return min(1.0, max(0.0, base))

def _voacap_luf(dist_km, hour_utc):
    """Estime la LUF (fréquence minimale utilisable)."""
    # La nuit la LUF baisse (absorption D moindre)
    night = (hour_utc < 6 or hour_utc >= 20)
    if dist_km < 1000:
        base = 4.0 if night else 7.0
    elif dist_km < 5000:
        base = 3.5 if night else 5.5
    else:
        base = 3.0 if night else 4.5
    return base

_voacap_cache = {}
_voacap_cache_ts = {}
VOACAP_TTL = 1800  # 30 min

@app.route('/api/voacap')
def api_voacap():
    """Prédiction de propagation HF par zone et heure UTC."""
    import math
    zone = request.args.get('zone', 'EU').upper()
    if zone not in VOACAP_ZONES:
        return jsonify({'error': f'Zone inconnue: {zone}'}), 400

    now = time.time()
    cache_key = f"{zone}-{int(now // VOACAP_TTL)}"
    if cache_key in _voacap_cache:
        return jsonify(_voacap_cache[cache_key])

    # Récupérer SFI et Kp actuels
    with solar_lock:
        sol = dict(solar_cache)
    try:
        sfi = float(sol.get('sfi', 100))
    except:
        sfi = 100.0
    kp = sol.get('kp')

    # Distance TX→RX
    rx = VOACAP_ZONES[zone]
    tx_lat, tx_lon = user_lat, user_lon
    rx_lat, rx_lon = rx['lat'], rx['lon']
    dist_km = calculate_distance(tx_lat, tx_lon, rx_lat, rx_lon)

    # Calcul pour chaque heure (0-23) et chaque bande
    grid = {}  # grid[band_label][hour] = reliability 0-100
    for i, freq in enumerate(VOACAP_BANDS):
        band = VOACAP_BAND_LABELS[i]
        grid[band] = []
        for h in range(24):
            muf = _voacap_muf(sfi, dist_km)
            # Variation diurne de la MUF : +20% en milieu de journée
            hour_angle = math.pi * (h - 12) / 12
            muf_h = muf * (1.0 + 0.2 * math.cos(hour_angle))
            luf = _voacap_luf(dist_km, h)
            rel = _voacap_reliability(freq, muf_h, luf, h, dist_km, kp)
            grid[band].append(round(rel * 100))

    # MUF et LUF à l'heure actuelle UTC
    import datetime
    utc_hour = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).hour
    muf_now = _voacap_muf(sfi, dist_km) * (1 + 0.2 * math.cos(math.pi * (utc_hour - 12) / 12))
    luf_now = _voacap_luf(dist_km, utc_hour)

    result = {
        'zone': zone,
        'zone_name': rx['name'],
        'dist_km': round(dist_km),
        'sfi': sfi,
        'kp': kp,
        'muf': round(muf_now, 1),
        'luf': round(luf_now, 1),
        'bands': VOACAP_BAND_LABELS,
        'grid': grid,
        'generated_utc': datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).strftime('%H:%M UTC')
    }
    _voacap_cache[cache_key] = result
    return jsonify(result)

# ============================================================
# INTÉGRATION LoTW (Logbook of the World)
# Identifiants jamais stockés sur disque — session mémoire uniquement
# ============================================================

lotw_session = {
    "login": None,
    "password": None,
    "logged_in": False,
    "last_sync": None,
    "error": None
}

# Données importées depuis LoTW (en mémoire uniquement)
def save_lotw_cache():
    """Persiste lotw_data sur disque pour survie au redémarrage."""
    try:
        LOTW_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with lotw_lock:
            cache = {
                "confirmed_calls":    list(lotw_data.get("confirmed_calls", [])),
                "confirmed_dxcc":     list(lotw_data.get("confirmed_dxcc", [])),
                "confirmed_dxcc_nums":list(lotw_data.get("confirmed_dxcc_nums", [])),
                "worked_dxcc":        list(lotw_data.get("worked_dxcc", [])),
                "worked_calls":       list(lotw_data.get("worked_calls", [])),
                "dxcc_by_band":       {b: list(v) for b, v in lotw_data.get("dxcc_by_band", {}).items()},
                "total_qso":          lotw_data.get("total_qso", 0),
                "total_confirmed":    lotw_data.get("total_confirmed", 0),
                "saved_at":           time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "login":              lotw_session.get("login", ""),
            }
        with open(LOTW_CACHE_FILE, "w") as f:
            json.dump(cache, f)
        logger.info(f"LoTW cache sauvegardé: {len(cache['confirmed_dxcc'])} DXCC confirmés")
    except Exception as e:
        logger.warning(f"Impossible de sauvegarder le cache LoTW: {e}")


def load_lotw_cache():
    """Recharge lotw_data depuis le cache disque au démarrage."""
    if not LOTW_CACHE_FILE.exists():
        return
    try:
        with open(LOTW_CACHE_FILE, "r") as f:
            cache = json.load(f)
        with lotw_lock:
            lotw_data["confirmed_calls"]     = set(cache.get("confirmed_calls", []))
            lotw_data["confirmed_dxcc"]      = set(cache.get("confirmed_dxcc", []))
            lotw_data["confirmed_dxcc_nums"] = set(cache.get("confirmed_dxcc_nums", []))
            lotw_data["worked_dxcc"]         = set(cache.get("worked_dxcc", []))
            lotw_data["worked_calls"]        = set(cache.get("worked_calls", []))
            lotw_data["dxcc_by_band"]        = {b: list(v) for b, v in cache.get("dxcc_by_band", {}).items()}
            lotw_data["total_qso"]           = cache.get("total_qso", 0)
            lotw_data["total_confirmed"]     = cache.get("total_confirmed", 0)
            lotw_session["login"]            = cache.get("login", "")
            lotw_session["logged_in"]        = bool(cache.get("confirmed_dxcc"))
            lotw_session["last_sync"]        = cache.get("saved_at", "cache")
        logger.info(f"LoTW cache rechargé: {len(lotw_data['confirmed_dxcc'])} DXCC, {lotw_data['total_qso']} QSOs")
    except Exception as e:
        logger.warning(f"Impossible de charger le cache LoTW: {e}")


lotw_data = {
    "confirmed_calls": set(),      # calls déjà confirmés (QSL reçue)
    "confirmed_dxcc": set(),       # entités DXCC confirmées
    "worked_dxcc": set(),          # entités DXCC travaillées (pas forcément confirmées)
    "dxcc_by_band": {},            # {band: set(dxcc)} confirmés par bande
    "total_qso": 0,
    "total_confirmed": 0,
}
lotw_lock = threading.Lock()

def _parse_adif_lotw(adif_text, all_confirmed=False):
    """Parse un fichier ADIF LoTW et retourne la liste des QSOs.
    all_confirmed=True : tous les records sont considérés confirmés (requête qso_qsl=yes).
    """
    import re
    qsos = []
    upper = adif_text.upper()
    eoh = upper.find('<EOH>')
    if eoh == -1:
        return []
    # Avancer après le tag complet <eoh> ou <EOH>
    body = adif_text[eoh + 5:]

    def get_field(record, field):
        m = re.search(rf'<{re.escape(field)}:\d+(?::\w+)?>([^<]*)', record, re.IGNORECASE)
        return m.group(1).strip() if m else ''

    for record in re.split(r'<[Ee][Oo][Rr]>', body):
        record = record.strip()
        if not record:
            continue
        call = get_field(record, 'CALL')
        if not call:
            continue
        band = get_field(record, 'BAND').lower()
        dxcc = get_field(record, 'DXCC')

        if all_confirmed:
            confirmed = True
        else:
            # Pour requête qso_qsl=no : vérifier si QSL reçue quand même
            qsl = get_field(record, 'QSL_RCVD')
            confirmed = qsl.upper() == 'Y'

        qsos.append({
            'call':      call.upper(),
            'band':      band,
            'dxcc':      dxcc,
            'confirmed': confirmed
        })
    return qsos

@app.route('/api/lotw/login', methods=['POST'])
@require_api_token
def lotw_login():
    """Connexion LoTW : importe TOUS les QSOs (confirmés ou non)."""
    data = request.get_json(force=True)
    login    = (data.get('login') or '').strip()
    password = (data.get('password') or '').strip()
    if not login or not password:
        return jsonify({'ok': False, 'error': 'Login et mot de passe requis'}), 400

    # Étape 1 : tous les QSOs uploadés (qso_qsl=no = tous, pas seulement confirmés)
    url_all = (
        f"https://lotw.arrl.org/lotwuser/lotwreport.adi"
        f"?login={urllib.parse.quote(login)}"
        f"&password={urllib.parse.quote(password)}"
        f"&qso_query=1"
        f"&qso_qsl=no"
        f"&qso_mydetail=yes"
        f"&qso_qsorxsince=1900-01-01"
    )
    # Étape 2 : uniquement les QSLs confirmées (pour marquer confirmed)
    url_qsl = (
        f"https://lotw.arrl.org/lotwuser/lotwreport.adi"
        f"?login={urllib.parse.quote(login)}"
        f"&password={urllib.parse.quote(password)}"
        f"&qso_query=1"
        f"&qso_qsl=yes"
        f"&qso_mydetail=yes"
        f"&qso_qsorxsince=1900-01-01"
        f"&qso_qslsince=1900-01-01"
    )

    raw_all = raw_qsl = ''
    try:
        headers = {'User-Agent': f'Spot-Watcher-DX/{APP_VERSION}'}
        req = urllib.request.Request(url_all, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as r:
            raw_all = r.read().decode('utf-8', errors='replace')
        req2 = urllib.request.Request(url_qsl, headers=headers)
        with urllib.request.urlopen(req2, timeout=60) as r:
            raw_qsl = r.read().decode('utf-8', errors='replace')
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Erreur réseau: {e}'}), 502

    # Détecter échec d'auth
    if '<EOH>' not in raw_all.upper():
        return jsonify({'ok': False, 'error': 'Login ou mot de passe incorrect — vérifiez vos identifiants LoTW'}), 401

    # SÉCURITÉ v11 : data/ (privé, non world-readable) au lieu de /tmp,
    # + permissions restreintes 600. Le nom de fichier fixe fait qu'il est
    # de toute façon écrasé à chaque synchro LoTW — pas d'accumulation,
    # et l'utilité diagnostic (inspection ponctuelle) reste préservée.
    debug_dir = Path("data")
    debug_dir.mkdir(parents=True, exist_ok=True)
    debug_all_path = debug_dir / "lotw_debug_all.adi"
    debug_qsl_path = debug_dir / "lotw_debug_qsl.adi"
    try:
        with open(debug_all_path, 'w', encoding='utf-8') as f:
            f.write(raw_all)
        with open(debug_qsl_path, 'w', encoding='utf-8') as f:
            f.write(raw_qsl)
        os.chmod(debug_all_path, 0o600)
        os.chmod(debug_qsl_path, 0o600)
        logger.info(f"LoTW debug: fichiers sauvegardés dans data/lotw_debug_*.adi (privé)")
        logger.info(f"LoTW debug: {len(raw_all)} chars (all), {len(raw_qsl)} chars (qsl)")
    except Exception as e:
        logger.warning(f"LoTW debug save failed: {e}")

    # Parser les deux fichiers
    qsos_all = _parse_adif_lotw(raw_all, all_confirmed=False)
    qsos_qsl = _parse_adif_lotw(raw_qsl, all_confirmed=True)

    logger.info(f"LoTW parsed: {len(qsos_all)} QSOs total, {len(qsos_qsl)} confirmés")

    # Construire les sets
    # Note: le champ DXCC est souvent absent dans l'ADIF LoTW
    # → on utilise get_country_info() sur le callsign (via cty.dat)
    confirmed_calls = set()
    confirmed_dxcc  = set()
    worked_dxcc     = set()
    worked_calls    = set()
    dxcc_by_band    = {}
    total_confirmed = len(qsos_qsl)

    # Tous les QSOs = travaillés
    for q in qsos_all:
        call = q['call']
        worked_calls.add(call)
        dxcc = q['dxcc'] or get_country_info(call).get('c', '')
        if dxcc and dxcc != 'Unknown':
            worked_dxcc.add(dxcc)

    # QSLs confirmées — déduplication par nom de pays (simple et fiable)
    confirmed_dxcc_nums = set()
    for q in qsos_qsl:
        call = q['call']
        confirmed_calls.add(call)
        info = get_country_info(call)
        dxcc = q['dxcc'] or info.get('c', '')
        if not dxcc or dxcc == 'Unknown':
            continue
        confirmed_dxcc.add(dxcc)
        band = q['band']
        if band:
            dxcc_by_band.setdefault(band, set()).add(dxcc)

    with lotw_lock:
        lotw_session['login']     = login
        lotw_session['logged_in'] = True
        lotw_session['last_sync'] = time.strftime('%H:%M UTC')
        lotw_session['error']     = None
        lotw_data['confirmed_calls'] = confirmed_calls
        lotw_data['confirmed_dxcc']      = confirmed_dxcc
        lotw_data['confirmed_dxcc_nums'] = confirmed_dxcc_nums
        lotw_data['worked_dxcc']         = worked_dxcc
        lotw_data['worked_calls']    = worked_calls
        lotw_data['dxcc_by_band']    = {b: list(v) for b, v in dxcc_by_band.items()}
        lotw_data['total_qso']        = len(qsos_all)
        lotw_data['total_confirmed']  = total_confirmed

    dxcc_count = len(confirmed_dxcc)
    logger.info(f"LoTW sync OK: {len(qsos_all)} QSOs, {total_confirmed} confirmés, {dxcc_count} DXCC")
    save_lotw_cache()
    return jsonify({
        'ok': True,
        'total_qso': len(qsos_all),
        'total_confirmed': total_confirmed,
        'total_dxcc': dxcc_count,
        'last_sync': lotw_session['last_sync']
    })

@app.route('/api/lotw/diag')
def lotw_diag():
    """Diagnostic : montre les premiers QSOs parsés et la résolution DXCC."""
    with lotw_lock:
        if not lotw_session['logged_in']:
            return jsonify({'error': 'Non connecté'})
        confirmed = list(lotw_data['confirmed_dxcc'])[:20]
        nums = list(lotw_data.get('confirmed_dxcc_nums', set()))[:20]
        total_dxcc = len(lotw_data.get('confirmed_dxcc_nums') or lotw_data['confirmed_dxcc'])
        confirmed_calls_sample = list(lotw_data['confirmed_calls'])[:10]

    # Re-parser quelques lignes du fichier debug pour voir ce qui sort
    sample_resolutions = []
    for call in confirmed_calls_sample:
        info = get_country_info(call)
        sample_resolutions.append({
            'call': call,
            'country': info.get('c'),
            'dxcc_num': info.get('dxcc_num', 0)
        })

    return jsonify({
        'total_dxcc_shown': total_dxcc,
        'confirmed_dxcc_count': len(confirmed),
        'confirmed_dxcc_nums_count': len(nums),
        'confirmed_dxcc_sample': confirmed,
        'confirmed_dxcc_nums_sample': sorted(nums)[:20],
        'call_resolutions': sample_resolutions,
    })

@app.route('/api/lotw/logout', methods=['POST'])
@require_api_token
def lotw_logout():
    """Efface toutes les données LoTW de la mémoire."""
    with lotw_lock:
        lotw_session.update({'login': None, 'password': None, 'logged_in': False,
                             'last_sync': None, 'error': None})
        lotw_data['confirmed_calls'] = set()
        lotw_data['confirmed_dxcc']  = set()
        lotw_data['worked_dxcc']     = set()
        lotw_data['dxcc_by_band']    = {}
        lotw_data['total_qso']        = 0
        lotw_data['total_confirmed']  = 0
    return jsonify({'ok': True})

@app.route('/api/lotw/status')
def lotw_status():
    """Retourne l'état LoTW et les stats."""
    with lotw_lock:
        if not lotw_session['logged_in']:
            return jsonify({'logged_in': False})
        # Stats par bande
        band_stats = {b: len(v) for b, v in lotw_data['dxcc_by_band'].items()}
        return jsonify({
            'logged_in':       True,
            'login':           lotw_session['login'],
            'last_sync':       lotw_session['last_sync'],
            'total_qso':       lotw_data['total_qso'],
            'total_confirmed': lotw_data['total_confirmed'],
            'total_dxcc':      len(lotw_data['confirmed_dxcc']),
            'band_stats':      band_stats,
        })

@app.route('/api/lotw/check_call')
def lotw_check_call():
    """Vérifie si un call/DXCC est déjà confirmé."""
    call = (request.args.get('call') or '').upper().strip()
    if not call:
        return jsonify({'error': 'call requis'}), 400
    with lotw_lock:
        if not lotw_session['logged_in']:
            return jsonify({'logged_in': False})
        info = get_country_info(call)
        dxcc = info.get('c', '')
        return jsonify({
            'call':            call,
            'call_confirmed':  call in lotw_data['confirmed_calls'],
            'dxcc':            dxcc,
            'dxcc_confirmed':  dxcc in lotw_data['confirmed_dxcc'],
            'dxcc_new':        dxcc not in lotw_data['worked_dxcc'],
        })

@app.route('/api/lotw/spots_status')
def lotw_spots_status():
    """Enrichit tous les spots courants avec leur statut LoTW."""
    with lotw_lock:
        if not lotw_session['logged_in']:
            return jsonify({'logged_in': False, 'spots': []})
        confirmed_calls = lotw_data['confirmed_calls']
        confirmed_dxcc  = lotw_data['confirmed_dxcc']
        worked_dxcc     = lotw_data['worked_dxcc']

    # Récupérer les spots actifs
    with spot_lock if 'spot_lock' in dir() else threading.Lock():
        try:
            spots_list = list(recent_spots[-200:]) if recent_spots else []
        except:
            spots_list = []

    result = []
    for s in spots_list:
        call = (s.get('dx_call') or '').upper()
        info = get_country_info(call)
        dxcc = info.get('c', '')
        result.append({
            'call':           call,
            'call_confirmed': call in confirmed_calls,
            'dxcc_confirmed': dxcc in confirmed_dxcc,
            'dxcc_new':       bool(dxcc) and dxcc not in worked_dxcc,
        })
    return jsonify({'logged_in': True, 'spots': result})


# ============================================================
# LoTW × BRIEFING : opportunités DXCC dans les 15 prochains jours
# ============================================================

def _extract_callsign_from_text(text):
    """Extrait le premier callsign radio-amateur d'un texte."""
    import re
    if not text:
        return None
    first = text.strip().split()[0].upper() if text.strip() else ''
    if re.match(r'^[A-Z0-9]{1,3}[0-9][A-Z]{1,4}$', first.split('/')[0]):
        return first.split('/')[0]
    m = re.search(r'[A-Z0-9]{1,3}[0-9][A-Z]{1,4}', text.upper())
    return m.group(0) if m else None

def _extract_end_date_from_text(text):
    """Tente d'extraire une date de fin depuis le texte (ex: 'until April 5', 'until 05/04')."""
    import re, datetime
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    # Format "until DD Month YYYY" ou "until Month DD"
    months = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
              'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12,
              'january':1,'february':2,'march':3,'april':4,'june':6,
              'july':7,'august':8,'september':9,'october':10,'november':11,'december':12}

    patterns = [
        r'until\s+(\d{1,2})\s+([a-zA-Z]+)\s*(\d{4})?',
        r'until\s+([a-zA-Z]+)\s+(\d{1,2})\s*,?\s*(\d{4})?',
        r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                g = m.groups()
                if pat == patterns[0]:
                    day, mon_str, yr = int(g[0]), g[1][:3].lower(), int(g[2]) if g[2] else now.year
                    mon = months.get(mon_str)
                    if mon:
                        return datetime.datetime(yr, mon, day)
                elif pat == patterns[1]:
                    mon_str, day, yr = g[0][:3].lower(), int(g[1]), int(g[2]) if g[2] else now.year
                    mon = months.get(mon_str)
                    if mon:
                        return datetime.datetime(yr, mon, day)
            except:
                pass
    return None

@app.route('/api/lotw/opportunities')
def lotw_opportunities():
    """Croise le briefing DX avec le log LoTW pour identifier les opportunités DXCC."""
    import datetime, re

    with lotw_lock:
        if not lotw_session['logged_in']:
            return jsonify({'logged_in': False, 'opportunities': []})
        confirmed_dxcc = set(lotw_data['confirmed_dxcc'])
        worked_dxcc    = set(lotw_data['worked_dxcc'])
        dxcc_by_band   = dict(lotw_data.get('dxcc_by_band', {}))

    # Récupérer les items du briefing
    with briefing_lock:
        bp = briefing_cache.get('payload')
    if not bp:
        return jsonify({'logged_in': True, 'opportunities': [], 'error': 'Briefing non chargé'})

    items = bp.get('items', [])
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    horizon = now + datetime.timedelta(days=21)
    opportunities = []

    for item in items:
        title   = item.get('title', '')
        summary = item.get('summary', '')
        full    = f"{title} {summary}"

        # Extraire callsign
        call = _extract_callsign_from_text(title) or _extract_callsign_from_text(full)
        if not call:
            continue

        # Résoudre le DXCC via cty.dat
        country_info = get_country_info(call)
        dxcc = country_info.get('c', '')
        if not dxcc or dxcc == 'Unknown':
            continue

        # Date de fin
        end_date = _extract_end_date_from_text(full)
        days_left = None
        if end_date:
            if end_date < now:
                continue  # expédition terminée
            days_left = (end_date - now).days

        # Classer l'opportunité
        if dxcc not in worked_dxcc:
            status = 'new'           # jamais travaillé
            priority = 1
        elif dxcc not in confirmed_dxcc:
            status = 'worked_unconfirmed'  # travaillé mais pas confirmé
            priority = 2
        else:
            # Vérifier les bandes manquantes
            HF_BANDS = ['160m','80m','40m','30m','20m','17m','15m','12m','10m']
            confirmed_bands = set()  # unused, replaced below
            # Reconstruire correctement
            confirmed_bands_for_dxcc = set()
            for band, dxcc_list in dxcc_by_band.items():
                if dxcc in dxcc_list:
                    confirmed_bands_for_dxcc.add(band)
            missing = [b for b in HF_BANDS if b not in confirmed_bands_for_dxcc]
            if missing:
                status = 'band_missing'
                priority = 3
            else:
                continue  # tout bon, pas d'opportunité

        # Déduplication : même call de base (ignore suffixes /P /MM etc.)
        base_call = call.split('/')[0]
        if any(o['call'].split('/')[0] == base_call for o in opportunities):
            continue
        # Déduplication : même DXCC (garder la priorité la plus haute)
        if any(o['dxcc'] == dxcc for o in opportunities):
            existing = next(o for o in opportunities if o['dxcc'] == dxcc)
            if priority < existing['_priority']:
                opportunities.remove(existing)
            else:
                continue

        opp = {
            'call':      call,
            'dxcc':      dxcc,
            'title':     title[:80],
            'status':    status,
            'days_left': days_left,
            'link':      item.get('link'),
            '_priority': priority,
        }
        if status == 'band_missing':
            opp['missing_bands'] = missing[:5]
        opportunities.append(opp)

    # Trier : priorité puis jours restants
    opportunities.sort(key=lambda o: (o['_priority'], o.get('days_left') or 999))

    # Déduplication finale par DXCC et call de base (filet de sécurité)
    seen_dxcc = set()
    seen_calls = set()
    unique_opps = []
    for o in opportunities:
        base = o['call'].split('/')[0]
        if base in seen_calls or o['dxcc'] in seen_dxcc:
            continue
        seen_calls.add(base)
        if o['dxcc']:
            seen_dxcc.add(o['dxcc'])
        o.pop('_priority', None)
        unique_opps.append(o)

    return jsonify({'logged_in': True, 'opportunities': unique_opps[:20]})

# ============================================================
# PAGE SATELLITES — Tracking orbital temps réel
# ============================================================

import urllib.request as _ureq

# TLE sources CelesTrak (groupes)
SAT_TLE_URLS = {
    'amateur':  'https://celestrak.org/SOCRATES/query.php?CATNR=40901&FORMAT=TLE',
    'weather':  'https://celestrak.org/TLE/query.php?GROUP=weather&FORMAT=TLE',
    'amateur2': 'https://celestrak.org/TLE/query.php?GROUP=amateur&FORMAT=TLE',
    'stations': 'https://celestrak.org/TLE/query.php?GROUP=stations&FORMAT=TLE',
}

# Satellites d'intérêt avec leur NORAD ID
# Satellites par défaut (modifiables depuis l'interface)
SATELLITES_DEFAULT = {
    25544: {'name': 'ISS (ZARYA)',          'type': 'station','color': '#00f3ff', 'icon': '🛸'},
    43017: {'name': 'AO-91 (RadFxSat)',    'type': 'amateur','color': '#00ff80', 'icon': '📻'},
    43137: {'name': 'AO-92 (Fox-1D)',      'type': 'amateur','color': '#00ff80', 'icon': '📻'},
    27607: {'name': 'SO-50 (SaudiSat 1C)', 'type': 'amateur','color': '#00cc66', 'icon': '📻'},
    39444: {'name': 'LilacSat-2',          'type': 'amateur','color': '#00cc66', 'icon': '📻'},
    44109: {'name': 'AO-109 (RadFxSat-2)', 'type': 'amateur','color': '#00ff80', 'icon': '📻'},
}
# Alias utilisé dans le code
SATELLITES_OF_INTEREST = SATELLITES_DEFAULT

# Cache TLE
_tle_cache = {}
_tle_cache_ts = 0
TLE_CACHE_TTL = 6 * 3600  # 6h

# URL source TLE AMSAT (fichier complet, toujours à jour)
# Sources TLE par ordre de priorité
# Sources TLE v10.1 — Format JSON OMM (CelesTrak GP API)
# Migration obligatoire : les numéros de catalogue > 69999 (prévu ~juillet 2026)
# ne seront plus disponibles en format TLE texte.
# Les champs JSON : OBJECT_NAME, NORAD_CAT_ID, TLE_LINE1, TLE_LINE2
#   → TLE_LINE1/TLE_LINE2 sont directement compatibles avec sgp4.twoline2rv()
#   → NORAD_CAT_ID est un entier (pas limité à 5 chiffres)
#
# Note CelesTrak : rafraîchir max 1x/2h — bloque les IP qui spamment.
# Notre TLE_CACHE_TTL est déjà à 3600s, donc on est dans les clous.

TLE_JSON_SOURCES = [
    # Satellites amateurs (AO-91, AO-92, AO-73, RS-44, SO-50, FO-29, etc.)
    ('CelesTrak-Amateur', 'https://celestrak.org/NORAD/elements/gp.php?GROUP=amateur&FORMAT=json'),
    # Stations spatiales (ISS, CSS Tiangong...)
    ('CelesTrak-Stations', 'https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=json'),
]

# Fallback TLE texte (AMSAT nasa.all) — pour les satellites amateurs historiques
# et en cas d'indisponibilité de CelesTrak.
# Ce fallback sera obsolète après juillet 2026 pour les nouveaux satellites.
TLE_SOURCES = [
    ('AMSAT-fallback', 'https://www.amsat.org/amsat/ftp/keps/current/nasa.all'),
]

def _fetch_url(url):
    """Télécharge une URL et retourne le texte décodé."""
    try:
        req = _ureq.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; Spot-Watcher-DX)',
            'Accept': '*/*',
        })
        with _ureq.urlopen(req, timeout=20) as r:
            raw = r.read()
            text = raw.decode('latin-1', errors='replace').strip()
            if text and len(text) > 50:
                return text
    except Exception as e:
        logger.debug(f"TLE fetch {url}: {e}")
    return ''

def _fetch_all_tles():
    """
    Télécharge les TLE depuis les sources JSON OMM (CelesTrak GP API) en priorité,
    avec fallback sur les sources TLE texte (AMSAT nasa.all).

    Format JSON retourné par CelesTrak :
      [{"OBJECT_NAME": "AO-91",
        "NORAD_CAT_ID": 43017,
        "TLE_LINE1": "1 43017U...",
        "TLE_LINE2": "2 43017...",
        ...}, ...]

    TLE_LINE1/TLE_LINE2 sont directement passables à sgp4.twoline2rv() —
    aucun changement dans le reste du code.
    NORAD_CAT_ID est un entier Python natif, pas limité à 5 chiffres.
    Compatible avec les futurs numéros > 99999 (nécessaires à partir de ~juillet 2026).
    """
    import json as _json
    combined_text = ''
    json_tles = {}  # {norad_id: (name, tle1, tle2)}
    json_ok = False

    # ── Tentative 1 : sources JSON OMM (CelesTrak GP API) ───────────────────
    for source_name, url in TLE_JSON_SOURCES:
        text = _fetch_url(url)
        if not text:
            continue
        try:
            data = _json.loads(text)
            if not isinstance(data, list) or not data:
                logger.warning(f"TLE JSON {source_name}: réponse vide ou invalide")
                continue
            count = 0
            for obj in data:
                try:
                    norad = int(obj.get('NORAD_CAT_ID') or obj.get('CCSDS_OMM_VERS', '0'))
                    if norad <= 0:
                        continue
                    name  = obj.get('OBJECT_NAME', str(norad)).strip()
                    tle1  = obj.get('TLE_LINE1', '').strip()
                    tle2  = obj.get('TLE_LINE2', '').strip()
                    if tle1 and tle2 and norad not in json_tles:
                        json_tles[norad] = (name, tle1, tle2)
                        count += 1
                except (ValueError, TypeError):
                    continue
            logger.info(f"TLE JSON {source_name}: {count} satellites chargés")
            json_ok = True
        except _json.JSONDecodeError as e:
            logger.warning(f"TLE JSON {source_name}: JSON invalide ({e})")

    # ── Tentative 2 : fallback TLE texte (AMSAT nasa.all) ───────────────────
    for source_name, url in TLE_SOURCES:
        text = _fetch_url(url)
        if text:
            logger.info(f"TLE texte {source_name}: {text.count(chr(10))} lignes")
            combined_text += text + '\n'

    if not json_ok and not combined_text:
        logger.error("TLE: toutes les sources ont échoué (JSON + fallback texte)")
    elif not json_ok:
        logger.warning("TLE: sources JSON indisponibles, fallback texte utilisé")

    return json_tles, combined_text

def _parse_tle_text(text):
    """Parse TLE → dict {norad_id: (name, tle1, tle2)}.
    Robuste au format AMSAT nasa.all (header texte + noms libres).
    Stratégie : scanner toutes les lignes, détecter les paires "1 NNNNN / 2 NNNNN".
    """
    import re
    TLE1 = re.compile(r'^1 (\d{5})')
    TLE2 = re.compile(r'^2 (\d{5})')
    SKIP = re.compile(r'QST|@amsat|\.AMSAT|Orbital|2Line|SB KEPS|New England|From Orb|\$ORB')

    lines = [l.rstrip() for l in text.replace('\r','').split('\n')]
    result = {}
    i = 0
    while i < len(lines) - 1:
        m1 = TLE1.match(lines[i].strip())
        if m1:
            # Ligne TLE1 trouvée — chercher TLE2 juste après
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            m2 = TLE2.match(lines[j].strip()) if j < len(lines) else None
            if m2 and m1.group(1) == m2.group(1):
                norad = int(m1.group(1))
                tle1  = lines[i].strip()
                tle2  = lines[j].strip()
                # Chercher le nom : ligne(s) avant TLE1 qui ne sont pas TLE ni header
                name = str(norad)
                for k in range(i-1, max(i-3, -1), -1):
                    candidate = lines[k].strip()
                    if not candidate:
                        continue
                    if TLE1.match(candidate) or TLE2.match(candidate):
                        break
                    if not SKIP.search(candidate):
                        name = candidate
                        break
                if norad not in result:
                    result[norad] = (name, tle1, tle2)
                i = j + 1
                continue
        i += 1
    return result

def _load_tle_cache():
    """
    Charge ou rafraîchit le cache TLE.
    Priorité : JSON OMM (CelesTrak GP API) → fallback texte (AMSAT nasa.all).
    Le JSON supporte les NORAD > 99999 (requis après ~juillet 2026).
    """
    global _tle_cache, _tle_cache_ts
    now = time.time()
    if _tle_cache and (now - _tle_cache_ts) < TLE_CACHE_TTL:
        return _tle_cache

    json_tles, fallback_text = _fetch_all_tles()

    # Fusionner : JSON en priorité, puis fallback texte pour les manquants
    all_tles = dict(json_tles)

    if fallback_text:
        text_tles = _parse_tle_text(fallback_text)
        merged = 0
        for norad, data in text_tles.items():
            if norad not in all_tles:
                all_tles[norad] = data
                merged += 1
        if merged:
            logger.info(f"TLE fallback texte: {merged} satellites ajoutés")

    if all_tles:
        _tle_cache = all_tles
        _tle_cache_ts = now
        json_count = len(json_tles)
        total = len(all_tles)
        active_ids = _get_active_sat_ids()
        found = sum(1 for nid in active_ids if nid in all_tles)
        logger.info(f"TLE cache: {total} satellites ({json_count} JSON + {total-json_count} texte), "
                    f"{found}/{len(active_ids)} satellites d'intérêt trouvés")
    else:
        logger.error("TLE cache: aucune donnée disponible, conservation de l'ancien cache")
    return _tle_cache

# Fichier de config satellites actifs
SAT_CONFIG_FILE = Path("data/satellites_config.json")

def _get_active_sat_ids():
    """Retourne la liste des NORAD IDs actifs (fichier config ou défaut).

    Le fallback sur SATELLITES_OF_INTEREST ne doit s'appliquer QUE si le
    fichier de config n'existe pas ou est illisible — jamais si l'utilisateur
    a explicitement choisi une liste vide ou courte (ex: après avoir retiré
    tous ses satellites, ou désactivé un satellite désorbité). Un ancien bug
    ici retombait sur la liste par défaut dès que la liste active était
    vide, ce qui réaffichait silencieusement les satellites que l'utilisateur
    venait justement de retirer."""
    if SAT_CONFIG_FILE.exists():
        try:
            cfg = json.loads(SAT_CONFIG_FILE.read_text(encoding='utf-8'))
            return [int(s['norad']) for s in cfg if s.get('active', True)]
        except Exception as e:
            logger.warning(f"satellites_config.json illisible: {e}")
    return list(SATELLITES_OF_INTEREST.keys())

def _get_sat_meta(norad_id):
    """Retourne les métadonnées d'un satellite (config ou défaut)."""
    if SAT_CONFIG_FILE.exists():
        try:
            cfg = json.loads(SAT_CONFIG_FILE.read_text(encoding='utf-8'))
            for s in cfg:
                if int(s['norad']) == norad_id:
                    return s
        except: pass
    return SATELLITES_OF_INTEREST.get(norad_id, {
        'name': str(norad_id), 'type': 'unknown',
        'color': '#aaaaaa', 'icon': '🛰️'
    })

def _save_sat_config(satellites):
    """Sauvegarde la configuration des satellites."""
    SAT_CONFIG_FILE.parent.mkdir(exist_ok=True)
    SAT_CONFIG_FILE.write_text(json.dumps(satellites, ensure_ascii=False, indent=2), encoding='utf-8')

def _dt_to_jd(dt_utc):
    """Convertit un datetime UTC en Julian Date (jd entier, fraction)."""
    import datetime as dt
    J2000 = dt.datetime(2000, 1, 1, 12, tzinfo=dt.timezone.utc)
    delta = (dt_utc - J2000).total_seconds() / 86400.0
    jd_full = 2451545.0 + delta
    jd_int  = int(jd_full)
    jd_frac = jd_full - jd_int
    return jd_int, jd_frac

def _compute_satellite_position(tle1, tle2, lat_obs, lon_obs, alt_obs=0.0):
    """Calcule position + az/el via sgp4."""
    if not SGP4_AVAILABLE:
        return {'error': 'sgp4 non installé pour cet interpréteur Python — lance: python3 -m pip install sgp4 --break-system-packages'}
    try:
        import math, datetime as dt

        sat = _Satrec.twoline2rv(tle1, tle2)
        now_utc = dt.datetime.now(dt.timezone.utc)
        jd, fr = _dt_to_jd(now_utc)
        e, r, v = sat.sgp4(jd, fr)
        if e != 0:
            return {'error': f'sgp4 erreur code {e}'}

        # ECI → géodésique
        import math
        gmst = _gmst(now_utc)
        lon_sat = math.degrees(math.atan2(r[1], r[0])) - math.degrees(gmst)
        lon_sat = ((lon_sat + 180) % 360) - 180
        rxy = math.sqrt(r[0]**2 + r[1]**2)
        lat_sat = math.degrees(math.atan2(r[2], rxy))
        alt_sat = math.sqrt(r[0]**2 + r[1]**2 + r[2]**2) - 6371.0

        az, el = _azel(r, lat_obs, lon_obs, alt_obs, now_utc)

        return {
            'lat':     round(lat_sat, 2),
            'lon':     round(lon_sat, 2),
            'alt_km':  round(alt_sat, 1),
            'az':      round(az, 1),
            'el':      round(el, 1),
            'visible': el > 0,
            'utc':     now_utc.strftime('%H:%M:%S UTC'),
        }
    except Exception as e:
        return {'error': str(e)}

def _gmst(dt_utc):
    """Greenwich Mean Sidereal Time en radians."""
    import math, datetime as dt
    J2000 = dt.datetime(2000, 1, 1, 12, tzinfo=dt.timezone.utc)
    d = (dt_utc - J2000).total_seconds() / 86400.0
    return math.radians((280.46061837 + 360.98564736629 * d) % 360)

def _azel(r_eci, lat, lon, alt_km, dt_utc):
    """Azimut et élévation depuis un observateur (degrés)."""
    import math
    gmst = _gmst(dt_utc)
    lon_rad = math.radians(lon)
    lat_rad = math.radians(lat)
    lst = gmst + lon_rad

    # Vecteur observateur en ECI
    R_earth = 6371.0 + alt_km
    ox = R_earth * math.cos(lat_rad) * math.cos(lst)
    oy = R_earth * math.cos(lat_rad) * math.sin(lst)
    oz = R_earth * math.sin(lat_rad)

    # Vecteur range
    rx, ry, rz = r_eci[0]-ox, r_eci[1]-oy, r_eci[2]-oz
    rng = math.sqrt(rx**2 + ry**2 + rz**2)

    # SEZ coordinates
    s = (math.sin(lat_rad)*math.cos(lst)*rx +
         math.sin(lat_rad)*math.sin(lst)*ry -
         math.cos(lat_rad)*rz)
    e = -math.sin(lst)*rx + math.cos(lst)*ry
    z = (math.cos(lat_rad)*math.cos(lst)*rx +
         math.cos(lat_rad)*math.sin(lst)*ry +
         math.sin(lat_rad)*rz)

    el = math.degrees(math.asin(z / rng))
    # SEZ : S pointe au SUD → -s pointe au NORD
    # az astronomique (N=0°, E=90°, S=180°, W=270°) = atan2(e, -s)
    az = math.degrees(math.atan2(e, -s)) % 360
    return az, el

def _next_passes(tle1, tle2, lat_obs, lon_obs, n_passes=5):
    """Calcule les n prochains passages AOS/TCA/LOS."""
    try:
        import math, datetime as dt
        if not SGP4_AVAILABLE:
            return [{'error': 'sgp4 non disponible'}]
        sat = _Satrec.twoline2rv(tle1, tle2)
        now_utc = dt.datetime.now(dt.timezone.utc)
        passes = []
        step = dt.timedelta(seconds=30)
        t = now_utc
        in_pass = False
        aos = tca = None
        tca_el = -90
        limit = now_utc + dt.timedelta(hours=24)

        while t < limit and len(passes) < n_passes:
            jd_i, jd_f = _dt_to_jd(t)
            e, r, v = sat.sgp4(jd_i, jd_f)
            if e == 0:
                az, el = _azel(r, lat_obs, lon_obs, 0, t)
                if el > 0 and not in_pass:
                    in_pass = True
                    aos = t
                    tca_el = el
                    tca = t
                elif el > 0 and in_pass:
                    if el > tca_el:
                        tca_el = el
                        tca = t
                elif el <= 0 and in_pass:
                    in_pass = False
                    if tca_el > 5:
                        passes.append({
                            'aos': aos.strftime('%d/%m %H:%MZ'),
                            'tca': tca.strftime('%H:%MZ'),
                            'los': t.strftime('%H:%MZ'),
                            'max_el': round(tca_el, 1),
                            'duration': int((t - aos).total_seconds() / 60),
                        })
            t += step

        return passes
    except Exception as e:
        return [{'error': str(e)}]

def _next_passes_raw(tle1, tle2, lat_obs, lon_obs, n_passes=8, horizon_hours=48):
    """Variante de _next_passes qui retourne des objets datetime bruts
    (aos_dt/tca_dt/los_dt) au lieu de chaînes formatées — nécessaire pour
    calculer une intersection temporelle entre deux observateurs (co-visibilité).
    Horizon élargi à 48h par défaut (vs 24h pour l'affichage simple) car il
    faut suffisamment de passages des deux côtés pour trouver un recouvrement."""
    try:
        import datetime as dt
        if not SGP4_AVAILABLE:
            return [{'error': 'sgp4 non disponible'}]
        sat = _Satrec.twoline2rv(tle1, tle2)
        now_utc = dt.datetime.now(dt.timezone.utc)
        passes = []
        step = dt.timedelta(seconds=30)
        t = now_utc
        in_pass = False
        aos = tca = None
        tca_el = -90
        limit = now_utc + dt.timedelta(hours=horizon_hours)

        while t < limit and len(passes) < n_passes:
            jd_i, jd_f = _dt_to_jd(t)
            e, r, v = sat.sgp4(jd_i, jd_f)
            if e == 0:
                az, el = _azel(r, lat_obs, lon_obs, 0, t)
                if el > 0 and not in_pass:
                    in_pass = True
                    aos = t
                    tca_el = el
                    tca = t
                elif el > 0 and in_pass:
                    if el > tca_el:
                        tca_el = el
                        tca = t
                elif el <= 0 and in_pass:
                    in_pass = False
                    if tca_el > 5:
                        passes.append({
                            'aos_dt': aos, 'tca_dt': tca, 'los_dt': t,
                            'max_el': round(tca_el, 1),
                        })
            t += step

        return passes
    except Exception as e:
        return [{'error': str(e)}]

def compute_covisibility(tle1, tle2, lat_a, lon_a, lat_b, lon_b, n_passes=8, horizon_hours=48):
    """Calcule les fenêtres de co-visibilité d'un satellite entre deux
    observateurs (station A = QTH utilisateur, station B = correspondant).
    Une fenêtre de co-visibilité est l'intersection temporelle entre un
    passage de A et un passage de B — les deux stations voient le satellite
    simultanément, condition nécessaire pour un QSO satellite entre elles.

    Ne fabrique jamais de recouvrement approximatif : si les fenêtres AOS/LOS
    ne se chevauchent pas réellement (calcul sgp4 indépendant pour chaque
    station), aucune entrée n'est retournée pour cette paire de passages."""
    passes_a = _next_passes_raw(tle1, tle2, lat_a, lon_a, n_passes, horizon_hours)
    passes_b = _next_passes_raw(tle1, tle2, lat_b, lon_b, n_passes, horizon_hours)

    if passes_a and 'error' in passes_a[0]:
        return {'error': passes_a[0]['error']}
    if passes_b and 'error' in passes_b[0]:
        return {'error': passes_b[0]['error']}

    windows = []
    for pa in passes_a:
        for pb in passes_b:
            overlap_start = max(pa['aos_dt'], pb['aos_dt'])
            overlap_end = min(pa['los_dt'], pb['los_dt'])
            if overlap_start < overlap_end:
                duration_s = (overlap_end - overlap_start).total_seconds()
                if duration_s < 30:
                    continue  # recouvrement trop court pour être exploitable
                windows.append({
                    'start': overlap_start.strftime('%d/%m %H:%M:%SZ'),
                    'end': overlap_end.strftime('%H:%M:%SZ'),
                    'duration_s': int(duration_s),
                    'max_el_a': pa['max_el'],
                    'max_el_b': pb['max_el'],
                })

    windows.sort(key=lambda w: w['start'])
    return {'windows': windows}

@app.route('/satellites')
@app.route('/satellites.html')
def satellites_page():
    return render_template('satellites.html', my_call=MY_CALL,
                           user_lat=user_lat, user_lon=user_lon)

@app.route('/api/satellites/positions')
def api_satellite_positions():
    """Retourne les positions actuelles de tous les satellites actifs."""
    tles = _load_tle_cache()
    active_ids = _get_active_sat_ids()
    result = []
    for norad_id in active_ids:
        meta = _get_sat_meta(norad_id)
        tle_name = tles[norad_id][0] if norad_id in tles else meta.get('name', str(norad_id))
        sat_type = meta.get('type', 'unknown')
        if sat_type == 'unknown':
            sat_type = _infer_sat_type(norad_id, tle_name)
        sat_icon = meta.get('icon', '') or _infer_sat_icon(sat_type, tle_name)
        if norad_id not in tles:
            sat_name = meta.get('name', str(norad_id))
            result.append({'norad': norad_id, 'name': sat_name,
                           'type': sat_type,
                           'color': meta.get('color','#aaa'),
                           'icon': sat_icon,
                           'error': f"TLE indisponible pour {sat_name} (NORAD {norad_id}) — probablement désorbité, à retirer de la liste via ⚙"})
            continue
        tle_name, tle1, tle2 = tles[norad_id]
        pos = _compute_satellite_position(tle1, tle2, user_lat, user_lon)
        if pos:
            # Nom : config > TLE > NORAD
            sat_name = meta.get('name') or tle_name or str(norad_id)
            if sat_name == str(norad_id) and tle_name and tle_name != str(norad_id):
                sat_name = tle_name
            pos.update({'norad': norad_id,
                        'name':  sat_name,
                        'type':  sat_type,
                        'color': meta.get('color','#aaa'),
                        'icon':  sat_icon})
            result.append(pos)
    return jsonify({'positions': result,
                    'observer': {'lat': user_lat, 'lon': user_lon, 'call': MY_CALL},
                    'ts': time.time()})

@app.route('/api/satellites/passes/<int:norad_id>')
def api_satellite_passes(norad_id):
    """Retourne les prochains passages d'un satellite."""
    tles = _load_tle_cache()
    if norad_id not in tles:
        return jsonify({'error': f'TLE non disponible pour NORAD {norad_id}'}), 404
    tle_name, tle1, tle2 = tles[norad_id]
    # Priorité : config utilisateur > SATELLITES_OF_INTEREST > nom TLE > NORAD
    meta = _get_sat_meta(norad_id)
    name = meta.get('name') or tle_name or str(norad_id)
    # Si le nom est juste le NORAD en string, utiliser le nom TLE
    if name == str(norad_id) and tle_name and tle_name != str(norad_id):
        name = tle_name
    passes = _next_passes(tle1, tle2, user_lat, user_lon)
    return jsonify({'norad': norad_id, 'name': name, 'passes': passes})

@app.route('/api/satellites/covisibility/<int:norad_id>')
def api_satellite_covisibility(norad_id):
    """Calcule les fenêtres où un satellite est visible SIMULTANÉMENT
    depuis TON QTH et depuis la position d'un correspondant (paramètre
    'locator', ex: ?locator=IO91). Nécessaire pour planifier un QSO
    satellite : les deux stations doivent voir le satellite en même temps.

    Inspiré de la fonction 'satellite co-visibility' de HamClock 4.28
    (hams.at). Calcul 100% local via sgp4 — aucune dépendance externe."""
    locator = request.args.get('locator', '').strip().upper()
    if not locator:
        return jsonify({'error': "Paramètre 'locator' requis (ex: ?locator=IO91)"}), 400

    # Validation stricte du format Maidenhead avant conversion : qra_to_lat_lon()
    # ne rejette pas les lettres hors A-R (ex: 'ZZ99' produirait des coordonnées
    # hors plage -90/90 et -180/180 sans erreur) — on valide donc ici en amont.
    import re as _re_loc
    if not _re_loc.match(r'^[A-R]{2}[0-9]{2}([A-X]{2})?$', locator):
        return jsonify({'error': f"Locator invalide : '{locator}' (format attendu : AA00 ou AA00aa)"}), 400

    corr_lat, corr_lon = qra_to_lat_lon(locator)
    if corr_lat is None or corr_lon is None:
        return jsonify({'error': f"Locator invalide : '{locator}'"}), 400

    tles = _load_tle_cache()
    if norad_id not in tles:
        return jsonify({'error': f'TLE non disponible pour NORAD {norad_id}'}), 404
    tle_name, tle1, tle2 = tles[norad_id]
    meta = _get_sat_meta(norad_id)
    name = meta.get('name') or tle_name or str(norad_id)
    if name == str(norad_id) and tle_name and tle_name != str(norad_id):
        name = tle_name

    result = compute_covisibility(tle1, tle2, user_lat, user_lon, corr_lat, corr_lon)
    if 'error' in result:
        return jsonify({'error': result['error']}), 500

    return jsonify({
        'norad': norad_id,
        'name': name,
        'observer_a': {'call': MY_CALL, 'lat': round(user_lat, 3), 'lon': round(user_lon, 3)},
        'observer_b': {'locator': locator.upper(), 'lat': round(corr_lat, 3), 'lon': round(corr_lon, 3)},
        'windows': result['windows'],
    })

@app.route('/api/satellites/footprint/<int:norad_id>')
def api_satellite_footprint(norad_id):
    """Retourne le footprint (cercle de visibilité) d'un satellite."""
    import math
    tles = _load_tle_cache()
    if norad_id not in tles:
        return jsonify({'error': 'TLE non disponible'}), 404
    _, tle1, tle2 = tles[norad_id]
    pos = _compute_satellite_position(tle1, tle2, user_lat, user_lon)
    if not pos or 'error' in pos:
        return jsonify({'error': pos.get('error', 'Erreur calcul')}), 500

    alt_km = pos['alt_km']
    lat_sat = pos['lat']
    lon_sat = pos['lon']

    # Rayon du footprint (demi-angle de visibilité)
    R_earth = 6371.0
    rho = math.acos(R_earth / (R_earth + alt_km))  # en radians
    rho_deg = math.degrees(rho)

    # Générer le cercle (72 points)
    points = []
    lat_r = math.radians(lat_sat)
    lon_r = math.radians(lon_sat)
    rho_r = rho  # déjà en radians

    for i in range(73):
        az = math.radians(i * 5)
        lat_p = math.asin(
            math.sin(lat_r) * math.cos(rho_r) +
            math.cos(lat_r) * math.sin(rho_r) * math.cos(az)
        )
        lon_p = lon_r + math.atan2(
            math.sin(az) * math.sin(rho_r) * math.cos(lat_r),
            math.cos(rho_r) - math.sin(lat_r) * math.sin(lat_p)
        )
        points.append([math.degrees(lat_p), math.degrees(lon_p)])

    return jsonify({
        'norad': norad_id,
        'lat': lat_sat,
        'lon': lon_sat,
        'alt_km': alt_km,
        'footprint_radius_deg': round(rho_deg, 2),
        'footprint_points': points,
    })

def _infer_sat_type(norad_id: int, name: str) -> str:
    """
    Infère le type d'un satellite depuis son NORAD ou son nom.
    L'API AMSAT ne fournit pas de champ type — on déduit depuis
    les mots-clés dans le nom TLE (AO, SO, RS, FO, JO, TO, CO...)
    qui sont les préfixes conventionnels des satellites amateurs OSCAR.
    """
    # Correspondance NORAD connue en priorité
    if norad_id in SATELLITES_DEFAULT:
        return SATELLITES_DEFAULT[norad_id].get('type', 'unknown')

    name_up = name.upper()

    # Noms de satellites de stations spatiales
    if any(k in name_up for k in ('ISS', 'CSS', 'TIANGONG', 'ZARYA', 'ZVEZDA', 'MIR')):
        return 'station'

    # Satellites météo
    if any(k in name_up for k in ('NOAA', 'METOP', 'METEOR', 'GOES', 'FENGYUN', 'METEOSAT')):
        return 'weather'

    # Satellites amateurs — préfixes OSCAR et noms connus
    AMATEUR_KEYWORDS = (
        'AO-', 'AO ', 'SO-', 'SO ', 'FO-', 'FO ', 'JO-', 'JO ', 'TO-', 'TO ',
        'CO-', 'CO ', 'RS-', 'RS ', 'UO-', 'HO-', 'KO-', 'DO-',
        'OSCAR', 'AMSAT', 'FUNCUBE', 'FOX-', 'LILACSAT', 'RADFXSAT',
        'XW-', 'CAS-', 'DIWATA', 'AISAT', 'UVSQ', 'TEVEL',
        'SAUDISAT 1C', 'PCSAT', 'LAPAN', 'LUCKY-7',
    )
    if any(k in name_up for k in AMATEUR_KEYWORDS):
        return 'amateur'

    return 'unknown'


def _infer_sat_icon(sat_type: str, name: str) -> str:
    """Retourne l'icône emoji selon le type."""
    if sat_type == 'station': return '🛸'
    if sat_type == 'weather': return '🌤'
    if sat_type == 'amateur': return '📻'
    return '🛰️'


@app.route('/api/satellites/catalog')
def api_satellites_catalog():
    """Retourne tous les satellites disponibles dans le cache TLE."""
    tles = _load_tle_cache()
    active_ids = set(_get_active_sat_ids())
    catalog = []
    for norad_id, (name, tle1, tle2) in sorted(tles.items(), key=lambda x: x[1][0]):
        meta = _get_sat_meta(norad_id)
        # Utiliser le type de la config si connu, sinon inférer depuis le nom
        sat_type = meta.get('type', 'unknown')
        if sat_type == 'unknown':
            sat_type = _infer_sat_type(norad_id, name)
        sat_icon = meta.get('icon', '') or _infer_sat_icon(sat_type, name)
        catalog.append({
            'norad':  norad_id,
            'name':   name,
            'active': norad_id in active_ids,
            'type':   sat_type,
            'color':  meta.get('color', '#aaaaaa'),
            'icon':   sat_icon,
        })
    return jsonify({'catalog': catalog, 'total': len(catalog)})

@app.route('/api/satellites/list')
def api_satellites_list():
    """Liste tous les satellites disponibles avec leur statut actif/inactif."""
    active_ids = set(_get_active_sat_ids())
    tles = _tle_cache  # ne pas forcer reload ici
    result = []
    for norad_id, meta in SATELLITES_OF_INTEREST.items():
        result.append({
            'norad':   norad_id,
            'name':    meta['name'],
            'type':    meta['type'],
            'icon':    meta['icon'],
            'color':   meta['color'],
            'active':  norad_id in active_ids,
            'has_tle': norad_id in tles,
        })
    return jsonify({'satellites': result})

@app.route('/api/satellites/config', methods=['POST'])
@require_api_token
def api_satellites_config():
    """Met à jour la liste des satellites actifs. Une liste vide est un
    état valide (l'utilisateur peut vouloir ne plus suivre aucun satellite
    temporairement, notamment après avoir retiré le dernier de sa liste
    via ✕) — ne jamais rejeter cette requête."""
    data = request.get_json(force=True)
    satellites = data.get('satellites', [])
    valid = []
    for s in satellites:
        if 'norad' not in s or 'name' not in s:
            continue
        valid.append({
            'norad':  int(s['norad']),
            'name':   s['name'],
            'type':   s.get('type', 'unknown'),
            'color':  s.get('color', '#aaaaaa'),
            'icon':   s.get('icon', '🛰️'),
            'active': bool(s.get('active', True)),
        })
    _save_sat_config(valid)
    # Invalider le cache positions (pas TLE — les keps restent valides)
    return jsonify({'ok': True, 'saved': len([s for s in valid if s['active']])})

@app.route('/api/satellites/refresh_tle', methods=['POST'])
@require_api_token
def api_tle_refresh():
    """Force le rechargement des TLE depuis CelesTrak."""
    global _tle_cache, _tle_cache_ts
    _tle_cache = {}
    _tle_cache_ts = 0
    tles = _load_tle_cache()
    found = {str(nid): nid in tles for nid in SATELLITES_OF_INTEREST}
    return jsonify({
        'ok': True,
        'total_tles': len(tles),
        'satellites_found': found,
        'message': f'{len(tles)} TLE rechargés depuis CelesTrak'
    })

@app.route('/api/satellites/lookup/<int:norad_id>')
def api_satellite_lookup(norad_id):
    """Recherche un satellite par son NORAD ID directement sur CelesTrak,
    indépendamment de sa catégorisation en GROUP (amateur/stations/etc.).

    Nécessaire car un satellite tout juste lancé peut mettre plusieurs
    jours à être classé dans le groupe 'amateur' par CelesTrak — il
    n'apparaît donc pas dans le catalogue habituel (_load_tle_cache, qui
    n'interroge que GROUP=amateur et GROUP=stations) tant que cette
    catégorisation n'est pas faite, même si son TLE existe déjà."""
    url = f"https://celestrak.org/NORAD/elements/gp.php?CATNR={norad_id}&FORMAT=json"
    try:
        text = _fetch_url(url)
        if not text:
            return jsonify({'ok': False, 'error': 'CelesTrak injoignable ou NORAD introuvable'}), 404
        import json as _json
        data = _json.loads(text)
        if not isinstance(data, list) or not data:
            return jsonify({'ok': False, 'error': f'Aucun satellite trouvé pour NORAD {norad_id}'}), 404
        obj = data[0]
        name = obj.get('OBJECT_NAME', str(norad_id)).strip()
        tle1 = obj.get('TLE_LINE1', '').strip()
        tle2 = obj.get('TLE_LINE2', '').strip()
        if not tle1 or not tle2:
            return jsonify({'ok': False, 'error': 'TLE incomplet pour ce satellite'}), 404

        # Injecte directement dans le cache TLE en mémoire pour que le
        # satellite soit immédiatement utilisable (positions/passages/
        # co-visibilité) sans attendre le prochain refresh périodique.
        _tle_cache[norad_id] = (name, tle1, tle2)

        return jsonify({
            'ok': True,
            'norad': norad_id,
            'name': name,
            'type': _infer_sat_type(norad_id, name),
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/satellites/tle_debug')
def api_tle_debug():
    """Debug: teste chaque source TLE et montre les 5 premières lignes."""
    results = []
    for name, url in TLE_SOURCES:
        text = _fetch_url(url)
        lines = [l for l in text.split('\n') if l.strip()][:6] if text else []
        results.append({
            'source': name,
            'url': url,
            'chars': len(text),
            'lines_total': text.count('\n') if text else 0,
            'first_lines': lines,
            'ok': bool(text),
        })
    # Aussi montrer les NORAD trouvés
    tles = _tle_cache
    found = {str(nid): nid in tles for nid in SATELLITES_OF_INTEREST}
    return jsonify({'sources': results, 'cache_sats': len(tles), 'found': found})

@app.route('/api/satellites/tle_status')
def api_tle_status():
    """Statut du cache TLE."""
    tles = _load_tle_cache()
    found = {nid: nid in tles for nid in SATELLITES_OF_INTEREST}
    return jsonify({'total_tles': len(tles), 'satellites': found,
                    'cache_age_s': int(time.time() - _tle_cache_ts)})


# Cache fréquences SatNOGS en mémoire {norad_id: (ts, [transmitters])}
_freq_cache: dict = {}
_FREQ_CACHE_TTL = 6 * 3600  # 6h — les fréquences changent rarement


@app.route('/api/satellites/frequencies/<int:norad_id>')
def api_satellite_frequencies(norad_id):
    """
    Fréquences uplink/downlink d'un satellite depuis SatNOGS DB.
    Mise en cache 6h en mémoire pour ne pas surcharger l'API publique.
    Retourne les transmetteurs actifs triés par type (FM, Linear, APRS…).
    """
    now = time.time()
    cached_ts, cached_data = _freq_cache.get(norad_id, (0, None))

    if cached_data is not None and (now - cached_ts) < _FREQ_CACHE_TTL:
        return jsonify({'ok': True, 'norad': norad_id,
                        'transmitters': cached_data, 'source': 'cache'})

    try:
        import urllib.request
        url = f"https://db.satnogs.org/api/transmitters/?format=json&satellite__norad_cat_id={norad_id}&alive=true"
        req = urllib.request.Request(url, headers={'User-Agent': f'NeuralDXWatcher/{APP_VERSION}'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = json.loads(resp.read().decode())

        transmitters = []
        for t in raw:
            mode = t.get('mode', '') or ''
            uplink   = t.get('uplink_low') or t.get('uplink_high')
            downlink = t.get('downlink_low') or t.get('downlink_high')
            if not downlink and not uplink:
                continue
            def fmt_mhz(hz):
                if not hz:
                    return None
                return round(hz / 1e6, 4)

            entry = {
                'description': t.get('description', '') or mode or 'Transponder',
                'mode':        mode,
                'type':        t.get('type', ''),
                'uplink_mhz':   fmt_mhz(uplink),
                'downlink_mhz': fmt_mhz(downlink),
                'invert':      t.get('invert', False),
                'baud':        t.get('baud'),
            }
            transmitters.append(entry)

        # Trier : downlink seul en dernier, FM avant Linear avant les autres
        order = {'FM': 0, 'AFSK': 1, 'FSK': 2, 'Linear': 3, 'CW': 4}
        transmitters.sort(key=lambda x: order.get(x['mode'], 9))

        _freq_cache[norad_id] = (now, transmitters)
        return jsonify({'ok': True, 'norad': norad_id,
                        'transmitters': transmitters, 'source': 'satnogs'})

    except Exception as e:
        logger.debug(f"api_satellite_frequencies {norad_id}: {e}")
        # Si SatNOGS injoignable, retourner cache expiré si disponible
        if cached_data is not None:
            return jsonify({'ok': True, 'norad': norad_id,
                            'transmitters': cached_data, 'source': 'cache_expired'})
        return jsonify({'ok': False, 'norad': norad_id,
                        'transmitters': [], 'error': str(e)})



# ═══════════════════════════════════════════════════════════════════════════
# v10.4 — REALITY CHECK : croisement VOACAP (théorie) vs spots réels
# Retourne pour chaque bande × créneau 3h, un score d'activité 0-100
# basé sur les spots reçus dans les 24 dernières heures pour la zone.
# ═══════════════════════════════════════════════════════════════════════════

_REALITY_ZONE_DXCC = {
    # Continents mappés vers préfixes DXCC principaux
    # (détection zone via cty.dat ou préfixe callsign)
    'EU': {'F','G','I','DL','EA','ON','PA','OZ','SM','OH','OK','SP','HA','HB','LA','LZ','ER','ES','LY','YL','9A','S5','YU','Z3','E7','T7','SV','SP','TA','UR','R','UA'},
    'NA': {'K','W','N','VE','VA','XE','CO','HP','HR','V3','TG','TI','YS','YN'},
    'AS': {'JA','JR','JH','JE','JF','JG','JI','JK','JL','JM','JN','JO','JP','JQ','BY','BG','BH','BA','BD','HL','HM','DS','DT','VU','9M','9V','YB','YC','YE','A4','A6','A7','A9','HS','E2','XV','XU','XW','YA','JT'},
    'OC': {'VK','ZL','FO','FK','H4','P2','V6','V7','T2','T8','KH','KH0','KH2','KH6','KH8','KH9','ZK','ZL7'},
    'AF': {'ZS','ZR','5T','5U','5V','5Z','6W','7X','9G','9J','9L','9U','9X','CN','D2','D4','ED','ET','J5','SU','S9','ST','TL','TN','TR','TT','TU','TY','TZ','V5','XT','Z2','ZD7','ZD8','ZD9'},
    'SA': {'CE','CX','HC','HK','LU','OA','PY','PJ','VP8','VP2','ZP','9Y','8P','6Y','V2','J3','J6','J7','J8','FG','FM','FS','FY'},
}


def _reality_dxcc_zone(call: str) -> str:
    """Retourne la zone continentale (EU/NA/AS/OC/AF/SA) d'un callsign."""
    if not call:
        return ''
    c = call.upper().split('/')[0]
    # Test préfixes 2-3 chars → 1 char
    for length in (3, 2, 1):
        prefix = c[:length]
        for zone, prefixes in _REALITY_ZONE_DXCC.items():
            if prefix in prefixes:
                return zone
    return ''


@app.route('/api/reality-check/<zone>')
def api_reality_check(zone):
    """
    Agrège les spots des dernières 24h par bande × créneau 3h × zone.
    Retourne un JSON compatible avec le tableau VOACAP : {band: [pct_06z, pct_09z, pct_12z, pct_15z, pct_18z, pct_21z]}
    Le pourcentage est une **intensité relative** normalisée sur le max toutes bandes confondues.
    """
    zone = zone.upper()
    if zone not in _REALITY_ZONE_DXCC:
        return jsonify({'ok': False, 'error': f'zone inconnue: {zone}'}), 400

    try:
        db_path = "data/predictor.sqlite"
        if not os.path.exists(db_path):
            return jsonify({'ok': True, 'zone': zone, 'reality': {}, 'source': 'no_db'})

        cutoff = time.time() - 24 * 3600
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        # Vérifier le nom réel de la table et des colonnes
        try:
            cur.execute("SELECT ts, band, dx_call FROM spot_log WHERE ts >= ?", (cutoff,))
            rows = cur.fetchall()
        except sqlite3.OperationalError:
            # Schéma différent — retourner vide plutôt que planter
            conn.close()
            return jsonify({'ok': True, 'zone': zone, 'reality': {}, 'source': 'schema_mismatch'})
        conn.close()

        # Créneaux de 3h : 0=00-03z, 1=03-06z, 2=06-09z, ...
        # Mais le tableau VOACAP affiche : 06z, 09z, 12z, 15z, 18z, 21z
        # → 6 créneaux commençant à 06z, 09z, 12z, 15z, 18z, 21z
        slot_starts = [6, 9, 12, 15, 18, 21]
        bands_wanted = {'50MHz', '70MHz', '144MHz', '432MHz'}
        bands_map = {'6m': '50MHz', '4m': '70MHz', '2m': '144MHz', '70cm': '432MHz',
                     '50MHz': '50MHz', '70MHz': '70MHz', '144MHz': '144MHz', '432MHz': '432MHz'}

        # Compter les spots par (band, slot)
        counts = {b: [0] * 6 for b in ['50MHz', '70MHz', '144MHz', '432MHz']}
        for ts, band, dx_call in rows:
            if not band or not dx_call:
                continue
            b_norm = bands_map.get(str(band).lower(), bands_map.get(band, band))
            if b_norm not in counts:
                continue
            # Filtrer par zone
            if _reality_dxcc_zone(dx_call) != zone:
                continue
            hour = time.gmtime(ts).tm_hour
            # Trouver le créneau (06z couvre 06-08, 09z couvre 09-11, etc.)
            slot_idx = None
            for i, start in enumerate(slot_starts):
                if start <= hour < start + 3:
                    slot_idx = i
                    break
            if slot_idx is not None:
                counts[b_norm][slot_idx] += 1

        # Normaliser : max toutes bandes/créneaux confondus = 100%
        all_vals = [v for arr in counts.values() for v in arr]
        max_v = max(all_vals) if all_vals else 0
        reality = {}
        for band, arr in counts.items():
            if max_v > 0:
                reality[band] = [round(v / max_v * 100) for v in arr]
            else:
                reality[band] = [0] * 6

        return jsonify({'ok': True, 'zone': zone, 'reality': reality,
                        'total_spots': sum(all_vals), 'source': 'spot_log'})

    except Exception as e:
        logger.debug(f"api_reality_check: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500



# ═══════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════
# v12.2 — MY SIGNAL via MQTT PSK Reporter (remplace le polling HTTP en usage
# normal, celui-ci reste comme repli si le flux MQTT est indisponible)
#
# Source : mqtt.pskreporter.info:1883, broker public gratuit (Tom M0LTE),
# rediffusion temps réel de pskreporter.info. Topic RX confirmé (doc
# officielle mqtt.pskreporter.info + pentafive/pskr-ha-bridge) :
#   pskr/filter/v2/+/+/{MY_CALL}/+/#
# → capte tous les rapports où MY_CALL est l'ÉMETTEUR (sc), c-à-d les
# stations qui ME reçoivent — exactement ce que MY SIGNAL affiche.
#
# Format payload JSON confirmé à la source (mqtt.pskreporter.info) :
#   sq=seq, f=freq Hz, md=mode, rp=SNR dB, t=epoch, sc=sender call,
#   sl=sender locator, rc=receiver call, rl=receiver locator,
#   sa/ra=ADIF DXCC sender/receiver, b=band
#
# Avantage vs polling HTTP : push temps réel (secondes, pas minutes),
# aucun risque de rate-limit (le HTTP `retrieve.pskreporter.info` a déjà
# déclenché un throttling silencieux une fois — cf. historique v11.3).
# paho-mqtt est déjà une dépendance du projet (module foudre) — rien de
# nouveau à installer.
# ═══════════════════════════════════════════════════════════════════════════

_mysignal_mqtt_buffer = deque(maxlen=200)   # rapports reçus en direct
_mysignal_mqtt_lock = threading.Lock()
_mysignal_mqtt_status = {
    "connected": False,
    "last_message_ts": None,
    "connected_since": None,
    "error": None,
}
MYSIGNAL_MQTT_RETENTION_S = 1800  # 30 min, cohérent avec flowStartSeconds=-1800 du fallback HTTP


def _mysignal_mqtt_on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        topic = f"pskr/filter/v2/+/+/{MY_CALL}/+/#"
        client.subscribe(topic)
        with _mysignal_mqtt_lock:
            _mysignal_mqtt_status["connected"] = True
            _mysignal_mqtt_status["connected_since"] = time.time()
            _mysignal_mqtt_status["error"] = None
        logger.info(f"MySignalMqttWorker: connecté, abonné à {topic}")
    else:
        with _mysignal_mqtt_lock:
            _mysignal_mqtt_status["connected"] = False
            _mysignal_mqtt_status["error"] = f"CONNACK rc={rc}"
        logger.warning(f"MySignalMqttWorker: échec connexion MQTT (rc={rc})")


def _mysignal_mqtt_on_disconnect(client, userdata, rc, properties=None):
    with _mysignal_mqtt_lock:
        _mysignal_mqtt_status["connected"] = False
    logger.warning(f"MySignalMqttWorker: déconnecté (rc={rc}) — reconnexion automatique")


def _mysignal_mqtt_on_message(client, userdata, msg):
    """Parse un rapport de réception PSK Reporter et l'ajoute au buffer.
    Ne lève jamais d'exception — un payload malformé est ignoré, pas fatal."""
    try:
        data = json.loads(msg.payload.decode("utf-8", errors="ignore"))

        rx_call = data.get("rc")
        rx_loc = data.get("rl")
        freq_hz = data.get("f")
        mode = data.get("md")
        snr = data.get("rp")
        ts = data.get("t")

        if not rx_call or not ts:
            return

        dist_km = None
        rx_lat_out, rx_lon_out = None, None
        if rx_loc:
            try:
                rx_lat, rx_lon = _maidenhead_to_latlon(rx_loc)
                dist_km = round(calculate_distance(user_lat, user_lon, rx_lat, rx_lon))
                rx_lat_out, rx_lon_out = round(rx_lat, 3), round(rx_lon, 3)
            except Exception:
                pass

        entry = {
            "call": rx_call,
            "locator": rx_loc,
            "lat": rx_lat_out,
            "lon": rx_lon_out,
            "freq_mhz": round(freq_hz / 1e6, 4) if freq_hz else None,
            "band": find_band(freq_hz / 1000) if freq_hz else None,
            "mode": mode,
            "snr": int(snr) if snr not in (None, "") else None,
            "distance_km": dist_km,
            "ts": int(ts),
        }

        with _mysignal_mqtt_lock:
            _mysignal_mqtt_buffer.append(entry)
            _mysignal_mqtt_status["last_message_ts"] = time.time()

    except Exception as e:
        logger.debug(f"MySignalMqttWorker: payload ignoré ({e})")


def mysignal_mqtt_worker():
    """Écoute le flux MQTT PSK Reporter en continu pour MY SIGNAL.
    Reconnexion automatique en cas de coupure. Dégrade proprement (log +
    retry) si le broker est indisponible — api_my_signal() bascule alors
    sur le polling HTTP existant (cf. _my_signal_cache)."""
    threading.current_thread().name = "MySignalMqttWorker"
    logger.info("MySignalMqttWorker démarré (flux MQTT PSK Reporter temps réel).")
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        logger.warning("MySignalMqttWorker: paho-mqtt non installé — repli permanent sur "
                        "le polling HTTP PSK Reporter (cache 90s).")
        return

    while True:
        try:
            client = mqtt.Client()
            client.on_connect = _mysignal_mqtt_on_connect
            client.on_disconnect = _mysignal_mqtt_on_disconnect
            client.on_message = _mysignal_mqtt_on_message
            client.connect("mqtt.pskreporter.info", 1883, keepalive=60)
            client.loop_forever()
        except Exception as e:
            with _mysignal_mqtt_lock:
                _mysignal_mqtt_status["connected"] = False
                _mysignal_mqtt_status["error"] = str(e)
            logger.warning(f"MySignalMqttWorker: connexion perdue ou échouée ({e}), retry dans 30s")
            time.sleep(30)


def _mysignal_mqtt_snapshot():
    """Construit un résultat au même format que le fallback HTTP
    (_my_signal_cache) à partir du buffer MQTT en direct. Retourne None
    si aucune donnée récente n'est disponible (le flux MQTT n'a encore
    rien reçu, ou le buffer est vide après purge des entrées trop
    anciennes) — dans ce cas api_my_signal() bascule sur le HTTP."""
    now = time.time()
    cutoff = now - MYSIGNAL_MQTT_RETENTION_S

    with _mysignal_mqtt_lock:
        connected = _mysignal_mqtt_status["connected"]
        raw_entries = [e for e in _mysignal_mqtt_buffer if e["ts"] >= cutoff]

    if not connected or not raw_entries:
        return None

    # Dédupliquer par call (garder le plus récent), ajouter age_s, trier
    seen = {}
    for e in raw_entries:
        if e["call"] not in seen or e["ts"] >= seen[e["call"]]["ts"]:
            seen[e["call"]] = e
    entries = []
    for e in sorted(seen.values(), key=lambda x: -x["ts"])[:20]:
        entry = dict(e)
        entry["age_s"] = max(0, int(now - e["ts"]))
        entries.append(entry)

    return {
        "ok": True,
        "call": MY_CALL,
        "count": len(entries),
        "max_distance_km": max((e["distance_km"] for e in entries if e["distance_km"]), default=0),
        "reports": entries,
        "source": "pskreporter-mqtt",
        "ts": now,
        "fetched_at": now,
        "cache_ttl": 0,  # push temps réel, pas de notion de TTL
        "mqtt_status": {
            "connected": connected,
            "last_message_age_s": (
                int(now - _mysignal_mqtt_status["last_message_ts"])
                if _mysignal_mqtt_status["last_message_ts"] else None
            ),
        },
    }


# v10.5 — MY SIGNAL : self-monitoring via PSK Reporter
# "Qui m'entend, où, avec quel SNR" — sans jamais avoir à ouvrir un site tiers.
# Source : PSK Reporter API publique (FT8/FT4/WSPR), cache 90s (politique
# d'usage PSK Reporter : ne pas interroger plus d'1x/minute).
# ═══════════════════════════════════════════════════════════════════════════

_my_signal_cache = {'ts': 0, 'data': None}
_MY_SIGNAL_CACHE_TTL = 90  # secondes — compromis réactivité vs rate limit PSK Reporter
# (pskreporter.info/pskdev.html : "retrieve reception data no more often than
# once every five minutes" — l'ancienne valeur de 90s l'enfreignait de 3.3x,
# ce qui pouvait déclencher un throttling silencieux côté PSK Reporter après
# un certain temps de fonctionnement continu : plus aucune donnée neuve ne
# remonte, sans erreur visible ("PSK reporter semble ne rien recevoir").


def _my_signal_refresh_ages(result, now):
    """Recalcule age_s pour chaque report à partir de son 'ts' absolu.

    Sans ça, age_s reste figé à la valeur calculée lors du fetch PSK Reporter
    d'origine — si un fetch live échoue ensuite (PSK Reporter indisponible,
    timeout), le fallback sert ces données en cache indéfiniment avec un
    age_s qui ne grandit jamais. Le filtre de fraîcheur 5 min côté frontend
    ne se déclenche alors jamais, et l'ancienne enveloppe reste affichée
    pour toujours au lieu de disparaître ("carte figée").
    """
    if not result or not result.get('reports'):
        return result
    for e in result['reports']:
        if e.get('ts'):
            e['age_s'] = max(0, int(now - e['ts']))
    return result


@app.route('/api/my-signal')
def api_my_signal():
    """
    Retourne les stations ayant récemment reçu MY_CALL, via PSK Reporter.
    Chaque entrée : indicatif receveur, locator, distance, bande, mode, SNR, âge.

    v12.2 — priorité au flux MQTT temps réel (mysignal_mqtt_worker). Si le
    flux MQTT est connecté et a des données récentes, on les sert directement
    (push temps réel, pas de délai de cache). Sinon, repli automatique et
    transparent sur le polling HTTP existant (_my_signal_cache) — aucune
    régression possible même si le broker MQTT est down.
    """
    now = time.time()

    mqtt_result = _mysignal_mqtt_snapshot()
    if mqtt_result is not None:
        return jsonify(mqtt_result)

    if _my_signal_cache['data'] is not None and (now - _my_signal_cache['ts']) < _MY_SIGNAL_CACHE_TTL:
        return jsonify(_my_signal_refresh_ages(_my_signal_cache['data'], now))

    try:
        import urllib.request, urllib.parse, re as _re

        # PSK Reporter n'a pas de vraie API JSON pure — le seul endpoint utilisable
        # côté serveur est JSONP (callback wrapper). On demande un callback nommé
        # et on retire le wrapper "cb(...)" avant le parsing JSON.
        params = urllib.parse.urlencode({
            'senderCallsign': MY_CALL,
            'flowStartSeconds': '-1800',
            'callback': 'cb',
        })
        url = f"https://retrieve.pskreporter.info/query?{params}"
        req = urllib.request.Request(url, headers={
            'User-Agent': f'NeuralDXWatcher/{APP_VERSION} ({MY_CALL})'
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode('utf-8', errors='replace').strip()

        # Retirer le wrapper JSONP : "cb(...)"
        m = _re.match(r'^\s*cb\s*\((.*)\)\s*;?\s*$', body, _re.DOTALL)
        payload = m.group(1) if m else body
        raw = json.loads(payload)

        reports = raw.get('receptionReport', [])
        if isinstance(reports, dict):
            reports = [reports]  # PSK Reporter renvoie un objet seul si un seul report

        entries = []
        for r in reports:
            try:
                rx_call = r.get('receiverCallsign', '')
                rx_loc  = r.get('receiverLocator', '')
                freq_hz = float(r.get('frequency', 0) or 0)
                mode    = r.get('mode', '')
                snr     = r.get('sNR')
                ts      = int(r.get('flowStartSeconds', 0) or 0)
                if not rx_call or not ts:
                    continue

                dist_km = None
                rx_lat_out, rx_lon_out = None, None
                if rx_loc:
                    try:
                        rx_lat, rx_lon = _maidenhead_to_latlon(rx_loc)
                        dist_km = round(calculate_distance(user_lat, user_lon, rx_lat, rx_lon))
                        rx_lat_out, rx_lon_out = round(rx_lat, 3), round(rx_lon, 3)
                    except Exception:
                        pass

                entries.append({
                    'call':     rx_call,
                    'locator':  rx_loc,
                    'lat':      rx_lat_out,
                    'lon':      rx_lon_out,
                    'freq_mhz': round(freq_hz / 1e6, 4) if freq_hz else None,
                    'band':     find_band(freq_hz / 1000) if freq_hz else None,
                    'mode':     mode,
                    'snr':      int(snr) if snr not in (None, '') else None,
                    'distance_km': dist_km,
                    'age_s':    max(0, int(now - ts)),
                    'ts':       ts,
                })
            except (ValueError, TypeError):
                continue

        # Dédupliquer par call (garder le plus récent), trier par plus récent
        seen = {}
        for e in entries:
            if e['call'] not in seen or e['ts'] > seen[e['call']]['ts']:
                seen[e['call']] = e
        entries = sorted(seen.values(), key=lambda x: -x['ts'])[:20]

        result = {
            'ok': True,
            'call': MY_CALL,
            'count': len(entries),
            'max_distance_km': max((e['distance_km'] for e in entries if e['distance_km']), default=0),
            'reports': entries,
            'source': 'pskreporter',
            'ts': now,
            'fetched_at': now,               # dernière interrogation réelle de PSK Reporter
            'cache_ttl': _MY_SIGNAL_CACHE_TTL,  # prochaine interrogation possible dans (cache_ttl - âge)
        }
        _my_signal_cache['data'] = result
        _my_signal_cache['ts'] = now
        return jsonify(result)

    except Exception as e:
        logger.debug(f"api_my_signal: {e}")
        # Fallback : cache expiré si dispo, sinon vide
        if _my_signal_cache['data'] is not None:
            return jsonify(_my_signal_refresh_ages(_my_signal_cache['data'], now))
        return jsonify({'ok': False, 'call': MY_CALL, 'reports': [], 'error': str(e), 'cache_ttl': _MY_SIGNAL_CACHE_TTL})


# Log statut sgp4
if SGP4_AVAILABLE:
    logger.info("sgp4 disponible et fonctionnel")
else:
    logger.warning("sgp4 NON DISPONIBLE — lance: python3 -m pip install sgp4 --break-system-packages")

# ═══════════════════════════════════════════════════════════════════════════
# v10.0 — NOUVELLES ROUTES
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/presence", methods=["POST"])
def api_presence():
    """Heartbeat opérateur — suspend les push ntfy si l'op est sur la page."""
    try:
        alerter.record_presence()
        predictor.record_session_heartbeat()
    except Exception:
        pass
    return jsonify({"ok": True, "ts": time.time()})


@app.route("/api/predictions")
def api_predictions():
    """Prédictions personnalisées (moteur Es/HF + DXCC manquants)."""
    try:
        with solar_lock:
            sfi = float(solar_cache.get("sfi") or 120)
            kp  = float(solar_cache.get("kp")  or 2)
    except Exception:
        sfi, kp = 120, 2

    try:
        with lotw_lock:
            dxcc_by_band = lotw_data.get("dxcc_by_band", {})
            confirmed    = lotw_data.get("confirmed_dxcc", set())
        if dxcc_by_band:
            missing = []
            for band, confirmed_set in dxcc_by_band.items():
                for s in list(spots_buffer)[-500:]:
                    cty = s.get("country", "")
                    if cty and cty != "Unknown" and cty not in confirmed_set:
                        missing.append({"dxcc": cty, "band": band,
                                        "mode": s.get("mode", "")})
            if missing:
                predictor.sync_missing_dxcc(missing)
                predictor.invalidate_cache()
    except Exception:
        pass

    preds = predictor.get_predictions(sfi=sfi, kp=kp)
    return jsonify({"predictions": preds, "ts": time.time()})


@app.route("/api/predictor/stats")
def api_predictor_stats():
    return jsonify(predictor.get_stats())


@app.route("/api/ntfy/status")
def api_ntfy_status():
    return jsonify(alerter.get_status())


@app.route("/api/ntfy/test", methods=["POST"])
@require_api_token
def api_ntfy_test():
    try:
        alerter._send(
            title   = "🔔 NEURAL DX — Test OK",
            message = f"Les alertes push fonctionnent · {MY_CALL} v{APP_VERSION}",
            priority= "default",
            tags    = ["white_check_mark"],
        )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/history_highlights.json")
def history_highlights():
    """Retourne les calls les plus marquants (SPD élevé) des 5 dernières heures,
    groupés par tranche horaire d'1h. Pour chaque tranche : top calls par score SPD."""
    HOURS = 5
    now = time.time()
    cutoff = now - HOURS * 3600

    # Grouper par tranche horaire (H-0 = heure en cours, H-1 = il y a 1h, etc.)
    slots = {i: [] for i in range(HOURS)}  # {0: [spots], 1: [spots], ...}

    with spot_history_lock:
        for entry in spot_history:
            ts = entry.get("ts", 0)
            if ts < cutoff:
                continue
            age_h = int((now - ts) // 3600)
            if age_h >= HOURS:
                continue
            slots[age_h].append(entry)

    # Pour chaque tranche, extraire les calls marquants
    result = []
    for hour_offset in range(HOURS):
        entries = slots[hour_offset]
        if not entries:
            result.append({
                "hour_label": f"H-{hour_offset}",
                "total_spots": 0,
                "top_calls": [],
                "dominant_band": None
            })
            continue

        # Dédupliquer par call en gardant le meilleur score
        best_by_call = {}
        for e in entries:
            call = e.get("dx")
            if not call:
                continue
            score = e.get("score") or 0
            if call not in best_by_call or score > best_by_call[call].get("score", 0):
                best_by_call[call] = {
                    "call": call,
                    "score": score,
                    "band": e.get("band"),
                    "mode": e.get("mode"),
                    "dxcc": e.get("dxcc"),
                    "dist_km": e.get("dist_km"),
                    "ts": e.get("ts")
                }

        # Trier par score SPD décroissant, prendre le top 5
        top_calls = sorted(best_by_call.values(), key=lambda x: x["score"], reverse=True)[:5]

        # Bande dominante
        band_counts = Counter(e.get("band") for e in entries if e.get("band"))
        dominant_band = band_counts.most_common(1)[0][0] if band_counts else None

        result.append({
            "hour_label": f"H-{hour_offset}",
            "total_spots": len(entries),
            "top_calls": top_calls,
            "dominant_band": dominant_band
        })

    return jsonify({"hours": result, "spd_threshold": SPD_THRESHOLD, "ts": now})


@app.route("/api/spot_history")
def api_spot_history():
    """Historique compact pour les sparklines DX Feed."""
    minutes = min(int(request.args.get("minutes", 60)), 180)
    cutoff  = time.time() - minutes * 60
    result  = {}
    with spot_history_lock:
        for entry in spot_history:
            ts = entry.get("ts", 0)
            if ts < cutoff:
                continue
            dx = entry.get("dx", "")
            if not dx:
                continue
            if dx not in result:
                result[dx] = []
            result[dx].append(int(ts))
    return jsonify({"window_min": minutes, "calls": result, "ts": time.time()})


if __name__ == "__main__":
    load_cty_dat()
    load_watchlist()
    load_user_config()  # Charger MY_CALL et user_qra depuis config.json

    logger.info(f"\n--- {APP_VERSION} ---")
    load_lotw_cache()
    load_wl_activity()
    logger.info(f"QTH de départ: {user_qra} ({user_lat:.2f}, {user_lon:.2f})")

    threading.Thread(target=telnet_worker, daemon=True).start()
    threading.Thread(target=ticker_worker, daemon=True).start()
    threading.Thread(target=solar_worker, daemon=True).start()
    threading.Thread(target=history_maintenance_worker, daemon=True).start()
    threading.Thread(target=briefing_refresh_worker, daemon=True).start()
    threading.Thread(target=wsjtx_worker, daemon=True).start()
    threading.Thread(target=weather_worker, daemon=True).start()
    threading.Thread(target=lightning_worker, daemon=True).start()
    threading.Thread(target=wspr_worker, daemon=True).start()
    threading.Thread(target=beacon_update_worker, daemon=True).start()
    threading.Thread(target=mysignal_mqtt_worker, daemon=True).start()

    def _freq_preload_worker():
        """
        Pré-charge les fréquences SatNOGS pour tous les satellites actifs
        au démarrage, en arrière-plan non-bloquant.
        Délai initial 15s pour laisser le serveur démarrer proprement,
        puis 2s entre chaque satellite pour ne pas surcharger l'API.
        Résultat : quand l'utilisateur clique sur un satellite, le cache
        est déjà chaud → affichage immédiat au lieu d'attendre 2-8s.
        """
        import time as _time, urllib.request as _req, json as _json
        _time.sleep(15)  # attendre que Flask soit prêt
        active_ids = _get_active_sat_ids()
        logger.info(f"Freq preload: démarrage pour {len(active_ids)} satellites")
        for norad_id in active_ids:
            try:
                now = _time.time()
                # Sauter si déjà en cache valide
                cached_ts, cached_data = _freq_cache.get(norad_id, (0, None))
                if cached_data is not None and (now - cached_ts) < _FREQ_CACHE_TTL:
                    continue
                url = (f"https://db.satnogs.org/api/transmitters/"
                       f"?format=json&satellite__norad_cat_id={norad_id}&alive=true")
                request = _req.Request(url, headers={'User-Agent': f'NeuralDXWatcher/{APP_VERSION}'})
                with _req.urlopen(request, timeout=8) as resp:
                    raw = _json.loads(resp.read().decode())
                transmitters = []
                for t in raw:
                    uplink   = t.get('uplink_low') or t.get('uplink_high')
                    downlink = t.get('downlink_low') or t.get('downlink_high')
                    if not downlink and not uplink:
                        continue
                    def fmt_mhz(hz):
                        return round(hz / 1e6, 4) if hz else None
                    transmitters.append({
                        'description': t.get('description', '') or t.get('mode', '') or 'Transponder',
                        'mode':        t.get('mode', ''),
                        'type':        t.get('type', ''),
                        'uplink_mhz':   fmt_mhz(uplink),
                        'downlink_mhz': fmt_mhz(downlink),
                        'invert':      t.get('invert', False),
                        'baud':        t.get('baud'),
                    })
                order = {'FM': 0, 'AFSK': 1, 'FSK': 2, 'Linear': 3, 'CW': 4}
                transmitters.sort(key=lambda x: order.get(x['mode'], 9))
                _freq_cache[norad_id] = (_time.time(), transmitters)
                logger.debug(f"Freq preload: NORAD {norad_id} → {len(transmitters)} transmetteurs")
            except Exception as ex:
                logger.debug(f"Freq preload NORAD {norad_id}: {ex}")
            _time.sleep(2)  # 2s entre chaque requête SatNOGS
        logger.info("Freq preload: terminé")

    threading.Thread(target=_freq_preload_worker, daemon=True).start()

    logger.info("Tous les Workers ont été démarrés. Lancement du serveur Flask...")
    # SÉCURITÉ v11 : debug=False — le débogueur Werkzeug interactif expose
    # une exécution de code arbitraire sur le réseau local si une exception
    # non gérée survient. Critique même en LAN domestique.
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False, use_reloader=False)
