"""
voacap_adapter.py — Wrapper autour de voacap_predict.py (skill Reid VOACAP)
Neural DX Watcher v12.6

Exécute une prédiction VOACAP point-à-point (TX -> RX), parse la sortie
texte du script, met en cache 24h en SQLite (calcul coûteux CPU sur Pi 5).

Le script externe n'est jamais vendored ici — installation via install.sh
du repo Reid-n0rc/voacap-skill (voir mémoire projet v12.6-voacap-plan.md).

Format de sortie confirmé (test réel sur le Pi, 2026-09-12) :

    VOACAP prediction: F1SMV -> Test  (2026-09, SSN=75)
     Hour  Best MHz   REL  SNR dB   Frequencies (REL/SNR)
      1.0      7.10  0.88      45   7.10=0.88/45, 14.20=0.66/32, 21.20=0.00/-81
      ...
     24.0      7.10  0.88      45   7.10=0.88/45, 14.20=0.71/35, 21.20=0.00/-67

IMPORTANT — convention d'heure VOACAP/ITSHFBC : le champ "Hour" est indexé
1-24, où l'heure N désigne le créneau UTC (N-1):00-N:00. Donc Hour=1.0 ->
UTC 00, Hour=24.0 -> UTC 23. C'est la convention historique VOACAP/ITSHFBC
(HOUR "ending"), pas une supposition arbitraire — mais à confirmer une fois
en prod en comparant avec un pic d'activité 40m connu du panneau
"Quand ça ouvre" (heatmap analytics.py). Si le décalage est visiblement
faux (ouverture prédite en pleine nuit alors que spots réels sont en
journée), inverser en hour_utc = hour_raw % 24 (ligne _parse_output).
"""

import os
import re
import json
import sqlite3
import subprocess
import time
from pathlib import Path

# Chemin par défaut posé par install.sh — ajuster si install différent
VOACAP_SCRIPT = Path(os.path.expanduser(
    os.environ.get("VOACAP_SCRIPT_PATH", "~/.claude/skills/voacap/scripts/voacap_predict.py")
))

DB_PATH = Path(__file__).parent / "data" / "voacap_cache.sqlite"
CACHE_TTL = 24 * 3600  # 24h — VOACAP est un modèle mensuel/statistique, pas temps réel
SUBPROCESS_TIMEOUT = 30  # secondes

_HOUR_RE = re.compile(r'^\s*(\d+)\.0\s+([\d.]+)\s+([\d.]+)\s+(-?\d+)\s+(.*)$')
_FREQ_RE = re.compile(r'([\d.]+)=([\d.]+)/(-?\d+)')


def _init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS voacap_cache (
            cache_key TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    conn.commit()
    return conn


def _cache_key(tx_lat, tx_lon, rx_lat, rx_lon, month, ssn, freqs):
    freqs_s = ",".join(f"{f:.2f}" for f in sorted(freqs))
    return f"{tx_lat:.3f}_{tx_lon:.3f}_{rx_lat:.3f}_{rx_lon:.3f}_{month}_{ssn}_{freqs_s}"


def _get_cached(key):
    conn = _init_db()
    try:
        row = conn.execute(
            "SELECT payload_json, created_at FROM voacap_cache WHERE cache_key=?",
            (key,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    payload_json, created_at = row
    if time.time() - created_at > CACHE_TTL:
        return None
    return json.loads(payload_json)


def _set_cache(key, payload):
    conn = _init_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO voacap_cache (cache_key, payload_json, created_at) VALUES (?, ?, ?)",
            (key, json.dumps(payload), time.time())
        )
        conn.commit()
    finally:
        conn.close()


def _parse_output(stdout_text):
    """Parse la sortie texte de voacap_predict.py -> liste de dicts par heure UTC."""
    hours = []
    for line in stdout_text.splitlines():
        m = _HOUR_RE.match(line)
        if not m:
            continue
        hour_raw = int(m.group(1))
        hour_utc = (hour_raw - 1) % 24  # cf. docstring module : convention VOACAP 1-24
        best_freq = float(m.group(2))
        rel = float(m.group(3))
        snr = int(m.group(4))
        freqs_str = m.group(5)

        freqs = {}
        for fm in _FREQ_RE.finditer(freqs_str):
            f_mhz = float(fm.group(1))
            freqs[f_mhz] = {"rel": float(fm.group(2)), "snr": int(fm.group(3))}

        hours.append({
            "hour_utc": hour_utc,
            "best_freq_mhz": best_freq,
            "rel": rel,
            "snr": snr,
            "frequencies": freqs,
        })

    hours.sort(key=lambda h: h["hour_utc"])
    return hours


def is_available():
    """Vérifie si le script VOACAP est installé, sans lancer de calcul (rapide, sans subprocess)."""
    return VOACAP_SCRIPT.exists()


def run_prediction(tx_name, tx_lat, tx_lon, rx_name, rx_lat, rx_lon,
                    month, ssn, freqs, use_cache=True):
    """
    Lance (ou récupère du cache) une prédiction VOACAP point-à-point.

    Retourne :
      {"status": "ok", "hours": [...], "circuit": "...", "month": M,
       "ssn": N, "from_cache": bool}
      ou
      {"status": "unavailable", "reason": "..."}
    """
    if not is_available():
        return {"status": "unavailable",
                "reason": f"voacap_predict.py introuvable ({VOACAP_SCRIPT})"}

    freqs = [float(f) for f in freqs]
    key = _cache_key(tx_lat, tx_lon, rx_lat, rx_lon, month, ssn, freqs)

    if use_cache:
        cached = _get_cached(key)
        if cached is not None:
            cached = dict(cached)
            cached["from_cache"] = True
            return cached

    cmd = [
        "python3", str(VOACAP_SCRIPT),
        "--tx-name", tx_name, "--tx-lat", str(tx_lat), "--tx-lon", str(tx_lon),
        "--rx-name", rx_name, "--rx-lat", str(rx_lat), "--rx-lon", str(rx_lon),
        "--month", str(month), "--ssn", str(ssn),
        "--freqs", *[str(f) for f in freqs],
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=SUBPROCESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"status": "unavailable", "reason": f"timeout (>{SUBPROCESS_TIMEOUT}s)"}
    except Exception as e:
        return {"status": "unavailable", "reason": str(e)}

    if result.returncode != 0:
        return {"status": "unavailable",
                "reason": f"exit {result.returncode}: {result.stderr[:300]}"}

    hours = _parse_output(result.stdout)
    if not hours:
        return {"status": "unavailable",
                "reason": "sortie VOACAP non reconnue (format du script modifié ?)"}

    payload = {
        "status": "ok",
        "hours": hours,
        "circuit": f"{tx_name} → {rx_name}",
        "month": month,
        "ssn": ssn,
        "from_cache": False,
    }

    if use_cache:
        _set_cache(key, payload)

    return payload
