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
import urllib.request
import urllib.parse
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
APP_VERSION = "9.3"
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
MSK144_FREQ = 144.360
MSK144_TOLERANCE_KHZ = 10 / 1000

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
    ("cluster.dx.de", 7300),
    ("telnet.wxc.kr", 23)
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
BRIEFING_USER_AGENT = "Spot-Watcher-DX/8.1 (+https://github.com/)"
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
        "id": "dxnews",
        "name": "DXNews",
        "url": "https://dxnews.com/",
        "site": "https://dxnews.com/",
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
    """Fetch latest NOAA planetary Kp index (table JSON). Returns dict or None."""
    try:
        req = urllib.request.Request(NOAA_KP_URL, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode('utf-8', errors='ignore'))

        # Expected format: [ ["time_tag","Kp","a_running","station_count"], ["2026-...","3.67","22","8"], ... ]
        if not isinstance(data, list) or len(data) < 2 or not isinstance(data[0], list):
            return None

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
    except Exception as e:
        logging.getLogger(__name__).warning(f"Kp NOAA fetch failed: {e}")
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
        k_display = f"{kp_val:.2f}" if isinstance(kp_val, (int, float)) else k_idx

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

        logger.info(f"SOLAR updated: SFI={sfi} A={a_idx} K={k_display} (Kp={kp_val})")

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

# --- PLAGES DE FREQUENCES CW ---
CW_RANGES = [
    ('160m', 1.810, 1.838), ('80m', 3.500, 3.560), ('40m', 7.000, 7.035),
    ('30m', 10.100, 10.134), ('20m', 14.000, 14.069), ('17m', 18.068, 18.095),
    ('15m', 21.000, 21.070), ('12m', 24.890, 24.913), ('10m', 28.000, 28.070),
]

# --- FRÉQUENCES FT4/FT8 (en kHz) ---
FT8_VHF_FREQ_RANGE_KHZ = (144171, 144177)

# --- FRÉQUENCES PSK31 (en kHz) ---
PSK31_HF_FREQ_RANGE_KHZ = (14.069, 14.071)


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
    """Charge l'historique d'activité de la watchlist depuis le disque."""
    global wl_activity
    try:
        if WL_ACTIVITY_FILE.exists():
            with open(WL_ACTIVITY_FILE, "r") as f:
                data = json.load(f)
            with wl_activity_lock:
                wl_activity = {k.upper(): float(v) for k, v in data.items()}
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

        for band in HF_BANDS + [b for b in VHF_BANDS if b not in ['2m', 'QO-100']]:
            timestamps = band_history.get(band, deque())

            while timestamps and timestamps[0] < current_time - SURGE_WINDOW:
                timestamps.popleft()

            count_total = len(timestamps)
            if count_total < MIN_SPOTS_FOR_SURGE:
                continue

            avg_rate = count_total / (SURGE_WINDOW / 60.0)
            recent_count = sum(1 for t in timestamps if t > current_time - 60)

            is_surging = (recent_count > (avg_rate * SURGE_THRESHOLD)) and (recent_count >= MIN_SPOTS_FOR_SURGE)

            if is_surging:
                if band not in bands_in_surge:
                    logger.info(f"ALERTE SURGE {band}: Détectée ({recent_count} spots / min)")
                    surge_bands.append(band)
                if band not in active_surges:
                    active_surges.append(band)
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

    # PRIORITE
    if is_ft2_hf:
        mode = "FT2"
    elif is_ft4_hf or is_ft4_vhf or is_ft4_6m:
        mode = "FT4"
    elif is_ft8_vhf or is_ft8_6m:
        mode = "FT8"

    # CW
    if mode == "SSB":
        for cw_band, min_mhz, max_mhz in CW_RANGES:
            if cw_band == band and min_mhz <= f_mhz <= max_mhz:
                mode = "CW"
                break

    # MSK144
    if band == "2m" and abs(freq_khz - (MSK144_FREQ * 1000)) <= MSK144_TOLERANCE_KHZ:
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
                    logger.warning(f"Cluster {host} a fermé la connexion (EOFError).")
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
                        freq_str = parts[1]
                        dx_call = parts[2].upper()
                        comment = " ".join(parts[3:]).upper()

                        try:
                            freq_raw = float(freq_str)
                        except:
                            continue
                        band, mode = get_band_and_mode_smart(freq_raw, comment)
                        info = get_country_info(dx_call)

                        lat, lon = info['lat'], info['lon']
                        dist_km = 0.0
                        if lat != 0.0 and lon != 0.0:
                            dist_km = calculate_distance(user_lat, user_lon, lat, lon)

                        spd_score = calculate_spd_score(dx_call, band, mode, comment, info['c'], dist_km)
                        color = BAND_COLORS.get(band, '#00f3ff')
                        
                        # Générer un spot_id unique pour le Path Optimizer
                        spot_id = f"{dx_call}-{int(time.time())}"

                        record_surge_data(band)

                        spot_obj = {
                            "timestamp": time.time(), "time": time.strftime("%H:%M"),
                            "freq": freq_str, "dx_call": dx_call, "band": band, "mode": mode,
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
                        # Mettre à jour l'activité watchlist si le call est suivi
                        _dx = spot_obj.get("dx_call", "").upper()
                        if _dx and _dx in watchlist:
                            with wl_activity_lock:
                                wl_activity[_dx] = spot_obj.get("timestamp", time.time())
                        # Tracking Watchlist: petit historique RAM (léger, filtrable)
                        try:
                            with spot_history_lock:
                                spot_history.append({
                                    "ts": spot_obj.get("timestamp", time.time()),
                                    "dx": spot_obj.get("dx_call"),
                                    "de": None,
                                    "band": spot_obj.get("band"),
                                    "mode": spot_obj.get("mode"),
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
        logger.info(f"QTH mis à jour: {user_qra}")
    else:
        logger.warning(f"Tentative de mise à jour QTH invalide: {new_qra}")
    return redirect(url_for('index'))


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

@app.route('/analysis.html')
def analysis_page():
    """Route pour rendre la page d'analyse/AI Insight."""
    return render_template('analysis.html', my_call=MY_CALL)

@app.route('/analysis')
def analysis_page_alias():
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

        subprocess.run(cmd, timeout=120, check=True)

        return jsonify({"status": "ok"})
    except subprocess.TimeoutExpired:
        return jsonify({"status": "timeout"}), 504
    except subprocess.CalledProcessError as e:
        return jsonify({"status": "failed", "code": e.returncode}), 500
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

@app.route('/watchlist.json', methods=['GET', 'POST', 'DELETE'])
def manage_watchlist():
    if request.method == 'GET':
        return jsonify(sorted(list(watchlist)))
    data = request.get_json(force=True, silent=True)
    if not data or 'call' not in data:
        return abort(400)
    call = data['call'].upper().strip()
    if request.method == 'POST':
        watchlist.add(call)
        logger.info(f"Ajout à la watchlist: {call}")
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
    days = int(request.args.get("days", 30))
    since = time.time() - days * 86400
    now   = time.time()

    # Source 1 : wl_activity (persisté sur disque, survit aux redémarrages)
    with wl_activity_lock:
        activity = dict(wl_activity)

    # Source 2 : spots_buffer récents (complète wl_activity pour la session courante)
    for s in spots_buffer:
        call = s.get("dx_call", "").upper()
        ts   = s.get("timestamp", 0)
        if call in [x.upper() for x in watchlist]:
            if call not in activity or ts > activity.get(call, 0):
                activity[call] = ts

    stale_items = []
    for x in sorted(watchlist):
        call   = x.upper()
        last_ts = activity.get(call)

        if last_ts:
            age_days = int((now - last_ts) / 86400)
            last_seen_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(last_ts))
        else:
            # Jamais vu depuis le démarrage — considéré inactif depuis longtemps
            age_days      = 9999
            last_seen_utc = None

        # Inclure dans la liste stale seulement si inactif >= days
        if age_days >= days:
            stale_items.append({
                "call":          x,
                "days_inactive": age_days if age_days < 9999 else None,
                "last_seen_utc": last_seen_utc,
            })

    stale_items.sort(key=lambda o: (-(o["days_inactive"] or 9999), o["call"]))
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

def _fetch_feed(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": BRIEFING_USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=BRIEFING_FEED_TIMEOUT) as r:
        data = r.read()
    return feedparser.parse(data)

def _fetch_html(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": BRIEFING_USER_AGENT, "Accept": "text/html,*/*"})
    with urllib.request.urlopen(req, timeout=BRIEFING_FEED_TIMEOUT) as r:
        return r.read().decode("utf-8", errors="ignore")

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

    # Fréquence : VFO + offset delta_f
    freq_hz  = (dial_freq_hz or 0) + decode.get("delta_f", 0)
    freq_khz = freq_hz / 1000.0
    freq_str = f"{freq_khz:.1f}"

    # Bande et mode
    band, mode = get_band_and_mode_smart(freq_khz / 1000.0, wsjtx_mode or decode.get("mode", "FT8"))

    # Infos géographiques — priorité au locator Maidenhead du message
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
            lat = info.get("lat", 0.0)
            lon = info.get("lon", 0.0)
    else:
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
            wl_activity[_dx] = spot_obj.get("timestamp", time.time())

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



@app.route('/history.json')
def get_history():
    now_utc = time.gmtime(time.time())
    current_hour = now_utc.tm_hour
    current_minute = now_utc.tm_min
    current_slot = ((current_hour * 2) + (current_minute // 30)) % HISTORY_SLOTS

    # Génère les labels pour les 12 dernières heures (24 slots de 30 min)
    labels = []
    for i in range(HISTORY_SLOTS):
        slot = (current_slot - i + HISTORY_SLOTS) % HISTORY_SLOTS
        hours_ago = (HISTORY_SLOTS - 1 - i) * HISTORY_PERIOD_MINUTES // 60
        minutes_ago = (HISTORY_SLOTS - 1 - i) * HISTORY_PERIOD_MINUTES % 60
        target_hour = (current_hour - hours_ago) % 24
        target_minute = (current_minute - minutes_ago) % 60
        labels.append(f"H-{hours_ago:02d}:{minutes_ago:02d}")

    with history_lock:
        data = {band: list(hist) for band, hist in history_30min.items()}

    # Rotate data to show most recent first (H-00:30, H-01:00, etc.)
    current_data = {}
    for band in HISTORY_BANDS:
        rotated = data[band][current_slot:] + data[band][:current_slot]
        current_data[band] = rotated

    return jsonify({"labels": labels, "data": current_data})

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

        result = {
            "update_available": (remote_version != current_version),
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

    # Sauvegarder en /tmp pour debug (fichier temporaire)
    try:
        with open('/tmp/lotw_debug_all.adi', 'w', encoding='utf-8') as f:
            f.write(raw_all)
        with open('/tmp/lotw_debug_qsl.adi', 'w', encoding='utf-8') as f:
            f.write(raw_qsl)
        logger.info(f"LoTW debug: fichiers sauvegardés dans /tmp/lotw_debug_*.adi")
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
TLE_SOURCES = [
    ('AMSAT', 'https://www.amsat.org/amsat/ftp/keps/current/nasa.all'),
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
    """Télécharge les TLE depuis les sources disponibles."""
    combined = ''
    for name, url in TLE_SOURCES:
        text = _fetch_url(url)
        if text:
            logger.info(f"TLE: {name} → {len(text)} chars, {text.count(chr(10))} lignes")
            combined += text + '\n'
    if not combined:
        logger.error("TLE: toutes les sources ont échoué")
    return combined

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
    """Charge ou rafraîchit le cache TLE — un appel par satellite via gp.php."""
    global _tle_cache, _tle_cache_ts
    now = time.time()
    if _tle_cache and (now - _tle_cache_ts) < TLE_CACHE_TTL:
        return _tle_cache

    # Télécharger le fichier TLE complet AMSAT
    text = _fetch_all_tles()
    all_tles = {}
    if text:
        all_tles = _parse_tle_text(text)
        logger.info(f"AMSAT TLE: {len(all_tles)} satellites parsés")

    if all_tles:
        _tle_cache = all_tles
        _tle_cache_ts = now
        active_ids = _get_active_sat_ids()
        found = sum(1 for nid in active_ids if nid in all_tles)
        logger.info(f"TLE cache: {found}/{len(active_ids)} satellites d'intérêt trouvés")
    else:
        logger.error("Impossible de charger les TLE depuis AMSAT")
    return _tle_cache

# Fichier de config satellites actifs
SAT_CONFIG_FILE = Path("data/satellites_config.json")

def _get_active_sat_ids():
    """Retourne la liste des NORAD IDs actifs (fichier config ou défaut)."""
    if SAT_CONFIG_FILE.exists():
        try:
            cfg = json.loads(SAT_CONFIG_FILE.read_text(encoding='utf-8'))
            ids = [int(s['norad']) for s in cfg if s.get('active', True)]
            if ids:
                return ids
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
    az = math.degrees(math.atan2(-e, s)) % 360
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
        if norad_id not in tles:
            result.append({'norad': norad_id, 'name': meta.get('name', str(norad_id)),
                           'type': meta.get('type','unknown'),
                           'color': meta.get('color','#aaa'),
                           'icon': meta.get('icon','🛰️'),
                           'error': 'TLE non disponible'})
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
                        'type':  meta.get('type','unknown'),
                        'color': meta.get('color','#aaa'),
                        'icon':  meta.get('icon','🛰️')})
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

@app.route('/api/satellites/catalog')
def api_satellites_catalog():
    """Retourne tous les satellites disponibles dans le cache TLE."""
    tles = _load_tle_cache()
    active_ids = set(_get_active_sat_ids())
    catalog = []
    for norad_id, (name, tle1, tle2) in sorted(tles.items(), key=lambda x: x[1][0]):
        meta = _get_sat_meta(norad_id)
        catalog.append({
            'norad':  norad_id,
            'name':   name,
            'active': norad_id in active_ids,
            'type':   meta.get('type', 'unknown'),
            'color':  meta.get('color', '#aaaaaa'),
            'icon':   meta.get('icon', '🛰️'),
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
def api_satellites_config():
    """Met à jour la liste des satellites actifs."""
    data = request.get_json(force=True)
    satellites = data.get('satellites', [])
    if not satellites:
        return jsonify({'ok': False, 'error': 'Liste vide'}), 400
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


# Log statut sgp4
if SGP4_AVAILABLE:
    logger.info("sgp4 disponible et fonctionnel")
else:
    logger.warning("sgp4 NON DISPONIBLE — lance: python3 -m pip install sgp4 --break-system-packages")

if __name__ == "__main__":
    load_cty_dat()
    load_watchlist()

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

    logger.info("Tous les Workers ont été démarrés. Lancement du serveur Flask...")
    app.run(host='0.0.0.0', port=WEB_PORT, debug=True, use_reloader=False)
