"""
predictor.py — Moteur prédictif personnel NEURAL DX WATCHER v10.0
==================================================================
Brique 1 : Collecte SQLite (sessions, spots observés, DXCC manquants)
Brique 2 : Scoring probabiliste par bande/heure/saison
Brique 3 : Génération de prédictions exploitables par le frontend

Usage :
    from predictor import Predictor
    p = Predictor(db_path="data/predictor.sqlite", my_call="F1SMV")
    p.record_spot(spot_obj)          # appelé dans telnet_worker
    p.record_session_heartbeat()     # appelé depuis /api/presence
    predictions = p.get_predictions()  # consommé par /api/predictions
"""

import sqlite3
import time
import math
import threading
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("predictor")

# ─── Patterns sporadic-E historiques (source : DXMaps / archives 2010-2024) ───
# Structure : { month : { utc_hour : base_probability_0_1 } }
# Probabilité d'une ouverture 6m Es sur path EU→XX pour une heure donnée.
ES_SEASONAL_HOURLY = {
    # Mois peak : mai-juillet (NH). Valeurs normalisées 0..1
    1:  {h: 0.04 for h in range(24)},
    2:  {h: 0.05 for h in range(24)},
    3:  {h: 0.07 for h in range(24)},
    4:  {h: max(0.07, 0.15 * math.sin(max(0,(h-8)/14*math.pi))) for h in range(24)},
    5:  {h: max(0.10, 0.55 * math.sin(max(0,(h-7)/15*math.pi))) for h in range(24)},
    6:  {h: max(0.12, 0.75 * math.sin(max(0,(h-7)/16*math.pi))) for h in range(24)},
    7:  {h: max(0.10, 0.65 * math.sin(max(0,(h-8)/15*math.pi))) for h in range(24)},
    8:  {h: max(0.07, 0.30 * math.sin(max(0,(h-8)/14*math.pi))) for h in range(24)},
    9:  {h: max(0.05, 0.12 * math.sin(max(0,(h-9)/12*math.pi))) for h in range(24)},
    10: {h: max(0.04, 0.08 * math.sin(max(0,(h-9)/11*math.pi))) for h in range(24)},
    11: {h: 0.04 for h in range(24)},
    12: {h: 0.04 for h in range(24)},
}

# Path modifiers : certaines directions sont favorisées en Es
# Couples DXCC prefix → boost multiplicateur
ES_PATH_BOOST = {
    "JA": 0.45, "JT": 0.55, "UA0": 0.50, "VK": 0.40,
    "W":  0.38, "VE": 0.35, "PY": 0.30,
    "EA": 0.90, "F":  0.95, "DL": 0.92, "I":  0.88,
    "SP": 0.85, "OM": 0.84, "OK": 0.84, "OZ": 0.80,
    "SM": 0.78, "OH": 0.78, "LA": 0.76, "SV": 0.75,
    "LZ": 0.72, "TA": 0.68, "4X": 0.65, "5B": 0.65,
    "ZS": 0.35, "VU": 0.42, "HL": 0.48,
}

# Pénalités bande : facteur multiplicateur pour d'autres bandes que 6m
BAND_FACTORS = {
    "6m": 1.00, "10m": 0.80, "12m": 0.60, "15m": 0.70,
    "17m": 0.55, "20m": 0.50, "40m": 0.35, "80m": 0.20,
}

WINDOW_HOURS = 3   # durée d'une fenêtre de prédiction
PRED_HORIZON = 24  # heures dans le futur à prédire
TOP_N_PRED   = 5   # nombre de prédictions à retourner

DB_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_start   REAL NOT NULL,
    ts_last    REAL NOT NULL,
    bands      TEXT DEFAULT '[]'    -- JSON list
);

CREATE TABLE IF NOT EXISTS spot_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         REAL NOT NULL,
    dx_call    TEXT NOT NULL,
    dxcc       TEXT,
    band       TEXT,
    mode       TEXT,
    freq_khz   REAL,
    spd_score  REAL,
    is_watchlist INTEGER DEFAULT 0,
    is_wanted  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS missing_dxcc (
    dxcc       TEXT NOT NULL,
    band       TEXT NOT NULL,
    mode       TEXT DEFAULT '',
    updated_at REAL NOT NULL,
    PRIMARY KEY (dxcc, band, mode)
);

CREATE TABLE IF NOT EXISTS es_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         REAL NOT NULL,
    month      INTEGER,
    hour_utc   INTEGER,
    path_prefix TEXT,
    band       TEXT DEFAULT '6m',
    spot_count INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_spot_log_ts     ON spot_log(ts);
CREATE INDEX IF NOT EXISTS idx_spot_log_dx     ON spot_log(dx_call);
CREATE INDEX IF NOT EXISTS idx_spot_log_band   ON spot_log(band);
CREATE INDEX IF NOT EXISTS idx_es_events_month ON es_events(month, hour_utc);
"""


class Predictor:
    """Moteur prédictif personnel NEURAL DX v10."""

    def __init__(self, db_path: str = "data/predictor.sqlite", my_call: str = "F1SMV"):
        self.db_path  = Path(db_path)
        self.my_call  = my_call
        self._lock    = threading.Lock()
        self._session_id: Optional[int] = None
        self._session_ts_last: float = 0
        self._session_bands: set = set()

        # Cache prédictions (recalcul toutes les 10 min)
        self._pred_cache: list = []
        self._pred_cache_ts: float = 0
        self._pred_cache_ttl: float = 600

        self._init_db()
        logger.info(f"Predictor initialisé → {self.db_path}")

    # ──────────────────────────────────────────────────────────────
    # Init DB
    # ──────────────────────────────────────────────────────────────
    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Connexion PERSISTANTE unique, réutilisée pour tous les appels.
        # CORRECTIF : l'ancienne implémentation ouvrait une nouvelle
        # connexion SQLite physique à CHAQUE appel (record_spot,
        # get_predictions, etc.). Sur un cluster actif envoyant plusieurs
        # spots/seconde, ça épuise rapidement les descripteurs de fichiers
        # et crée une forte contention sur le WAL — cause directe de
        # l'erreur "unable to open database file" observée en production
        # sur Raspberry Pi (carte SD, I/O plus lente qu'un SSD).
        # check_same_thread=False car telnet_worker/maintenance_worker
        # tournent dans des threads différents ; self._lock protège déjà
        # tous les accès concurrents à cette connexion partagée.
        self._db = sqlite3.connect(
            str(self.db_path), check_same_thread=False, timeout=30
        )
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(DB_SCHEMA)
        self._db.commit()

    def _conn(self) -> sqlite3.Connection:
        """
        Retourne la connexion persistante partagée. Conservé comme méthode
        (plutôt qu'un accès direct à self._db) pour ne pas casser le reste
        du code qui utilise `with self._conn() as conn:` — sqlite3.Connection
        supporte le protocole context manager nativement (commit/rollback
        automatique sans fermer la connexion physique).
        """
        return self._db

    def close(self):
        """Fermeture propre à l'arrêt de l'application (optionnel)."""
        try:
            self._db.close()
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────
    # Brique 1a : Collecte — spots
    # ──────────────────────────────────────────────────────────────
    def record_spot(self, spot: dict, is_watchlist: bool = False):
        """Enregistrer un spot entrant. Appelé depuis telnet_worker."""
        try:
            ts       = spot.get("timestamp", time.time())
            dx_call  = spot.get("dx_call", "")
            dxcc     = spot.get("country", "")
            band     = spot.get("band", "")
            mode     = spot.get("mode", "")
            freq_khz = float(spot.get("freq", 0) or 0)
            score    = float(spot.get("score", 0) or 0)
            is_wanted= int(spot.get("is_wanted", False))

            # Extraire le préfixe DXCC pour classification Es
            dxcc_prefix = self._extract_prefix(dx_call)

            with self._lock, self._conn() as conn:
                conn.execute(
                    "INSERT INTO spot_log(ts, dx_call, dxcc, band, mode, freq_khz, spd_score, is_watchlist, is_wanted) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (ts, dx_call, dxcc, band, mode, freq_khz, score, int(is_watchlist), is_wanted)
                )
                # Si c'est un spot 6m : enregistrer comme événement Es potentiel
                if band == "6m":
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    conn.execute(
                        "INSERT INTO es_events(ts, month, hour_utc, path_prefix, band, spot_count) VALUES (?,?,?,?,?,1)",
                        (ts, dt.month, dt.hour, dxcc_prefix, band)
                    )
                # Session : ajouter la bande
                self._session_bands.add(band)
        except Exception as e:
            logger.warning(f"Predictor.record_spot: {e}")

    # ──────────────────────────────────────────────────────────────
    # Brique 1b : Collecte — sessions opérateur
    # ──────────────────────────────────────────────────────────────
    def record_session_heartbeat(self):
        """Appelé depuis /api/presence (toutes les 30s si l'op est sur la page)."""
        now = time.time()
        try:
            import json
            with self._lock, self._conn() as conn:
                if self._session_id is None or (now - self._session_ts_last) > 120:
                    # Nouvelle session (inactivité > 2 min)
                    cur = conn.execute(
                        "INSERT INTO sessions(ts_start, ts_last, bands) VALUES (?,?,?)",
                        (now, now, json.dumps(list(self._session_bands)))
                    )
                    self._session_id   = cur.lastrowid
                    self._session_bands = set()
                else:
                    conn.execute(
                        "UPDATE sessions SET ts_last=?, bands=? WHERE id=?",
                        (now, json.dumps(list(self._session_bands)), self._session_id)
                    )
                self._session_ts_last = now
        except Exception as e:
            logger.warning(f"Predictor.record_session_heartbeat: {e}")

    # ──────────────────────────────────────────────────────────────
    # Brique 1c : Collecte — DXCC manquants (depuis LoTW)
    # ──────────────────────────────────────────────────────────────
    def sync_missing_dxcc(self, missing: list[dict]):
        """
        Synchroniser la liste des DXCC manquants depuis le cache LoTW.
        missing = [{"dxcc": "JT1", "band": "6m", "mode": "FT8"}, ...]
        """
        now = time.time()
        try:
            with self._lock, self._conn() as conn:
                conn.execute("DELETE FROM missing_dxcc")
                conn.executemany(
                    "INSERT OR REPLACE INTO missing_dxcc(dxcc, band, mode, updated_at) VALUES (?,?,?,?)",
                    [(m["dxcc"], m["band"], m.get("mode",""), now) for m in missing]
                )
            logger.info(f"Predictor: {len(missing)} DXCC manquants sync")
        except Exception as e:
            logger.warning(f"Predictor.sync_missing_dxcc: {e}")

    # ──────────────────────────────────────────────────────────────
    # Brique 2 : Scoring probabiliste
    # ──────────────────────────────────────────────────────────────
    def _score_window(self, month: int, hour_utc: int, band: str,
                      dxcc_prefix: str, sfi: float = 120, kp: float = 2) -> float:
        """
        Score 0..1 pour une fenêtre (mois, heure UTC, bande, direction DXCC).
        """
        # Base Es saisonnière/horaire
        es_base = ES_SEASONAL_HOURLY.get(month, {}).get(hour_utc, 0.04)

        # Boost path
        path_boost = 0.0
        for prefix, boost in ES_PATH_BOOST.items():
            if dxcc_prefix.startswith(prefix):
                path_boost = boost
                break
        if path_boost == 0.0:
            path_boost = 0.50  # préfixe inconnu : neutre

        # Facteur bande
        band_f = BAND_FACTORS.get(band, 0.30)

        # Facteur solaire (SFI) — HF beneficie, 6m peu affecté
        if band == "6m":
            solar_f = 1.0  # Es indépendant du SFI
        else:
            solar_f = max(0.1, min(1.0, (sfi - 70) / 130))
        if kp > 4:
            solar_f *= max(0.2, 1.0 - (kp - 4) * 0.15)

        # Historique local : bonus si on a déjà vu des spots sur ce path/heure
        history_bonus = self._history_bonus(month, hour_utc, dxcc_prefix, band)

        score = es_base * path_boost * band_f * solar_f + history_bonus
        return min(1.0, max(0.0, score))

    def _history_bonus(self, month: int, hour_utc: int, prefix: str, band: str) -> float:
        """Bonus basé sur les événements enregistrés dans es_events."""
        try:
            with self._conn() as conn:
                # Compter les événements dans ±1h et ±1 mois
                row = conn.execute(
                    "SELECT COUNT(*) as c FROM es_events "
                    "WHERE month BETWEEN ? AND ? "
                    "AND hour_utc BETWEEN ? AND ? "
                    "AND path_prefix=? AND band=?",
                    (max(1,month-1), min(12,month+1),
                     max(0,hour_utc-1), min(23,hour_utc+1),
                     prefix, band)
                ).fetchone()
                count = row["c"] if row else 0
                # Bonus logarithmique plafonné à 0.15
                return min(0.15, math.log1p(count) * 0.04)
        except Exception:
            return 0.0

    # ──────────────────────────────────────────────────────────────
    # Brique 3 : Génération des prédictions
    # ──────────────────────────────────────────────────────────────
    def get_predictions(self, sfi: float = 120, kp: float = 2) -> list[dict]:
        """
        Retourne les N meilleures prédictions d'ouverture pour les 24 prochaines heures.
        Chaque prédiction = {"hour_utc", "band", "dxcc", "score", "label", "tip"}
        Résultat mis en cache 10 min.
        """
        now = time.time()
        if now - self._pred_cache_ts < self._pred_cache_ttl and self._pred_cache:
            return self._pred_cache

        dt_now = datetime.fromtimestamp(now, tz=timezone.utc)

        # DXCC manquants prioritaires
        missing = self._get_missing_dxcc()

        candidates = []

        for delta_h in range(1, PRED_HORIZON + 1):
            future_ts   = now + delta_h * 3600
            future_dt   = datetime.fromtimestamp(future_ts, tz=timezone.utc)
            month       = future_dt.month
            hour_utc    = future_dt.hour

            # Pour chaque DXCC manquant, score sur sa bande préférée
            for m in missing[:30]:  # top 30 manquants seulement
                dxcc   = m["dxcc"]
                band   = m["band"]
                mode   = m.get("mode", "")
                prefix = self._extract_prefix(dxcc)

                score = self._score_window(month, hour_utc, band, prefix, sfi, kp)
                if score < 0.20:
                    continue

                label = self._format_label(future_dt, band, dxcc)
                tip   = self._format_tip(future_dt, band, dxcc, mode, score)
                candidates.append({
                    "ts_utc":   int(future_ts),
                    "hour_utc": hour_utc,
                    "delta_h":  delta_h,
                    "band":     band,
                    "dxcc":     dxcc,
                    "mode":     mode,
                    "score":    round(score, 3),
                    "label":    label,
                    "tip":      tip,
                    "missing":  True,
                })

        # Trier par score décroissant, dédupliquer sur (band, dxcc)
        candidates.sort(key=lambda x: -x["score"])
        seen, top = set(), []
        for c in candidates:
            key = (c["band"], c["dxcc"])
            if key not in seen:
                seen.add(key)
                top.append(c)
            if len(top) >= TOP_N_PRED:
                break

        self._pred_cache    = top
        self._pred_cache_ts = now
        return top

    def invalidate_cache(self):
        self._pred_cache_ts = 0

    # ──────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────
    def _get_missing_dxcc(self) -> list[dict]:
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT dxcc, band, mode FROM missing_dxcc ORDER BY band"
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    @staticmethod
    def _extract_prefix(call: str) -> str:
        """Extraire le préfixe DXCC approximatif d'un indicatif."""
        call = call.upper().split("/")[0]
        for length in (3, 2, 1):
            return call[:length]
        return call

    @staticmethod
    def _format_label(dt: datetime, band: str, dxcc: str) -> str:
        hour = dt.hour
        return f"{hour:02d}h UTC · {band} → {dxcc}"

    @staticmethod
    def _format_tip(dt: datetime, band: str, dxcc: str, mode: str, score: float) -> str:
        pct   = int(score * 100)
        hour  = dt.hour
        end   = (hour + WINDOW_HOURS) % 24
        mood  = "forte" if score > 0.6 else "modérée" if score > 0.35 else "faible"
        mode_str = f" en {mode}" if mode else ""
        return (
            f"Probabilité {mood} ({pct}%) d'ouverture {band} "
            f"vers {dxcc}{mode_str} entre {hour:02d}z et {end:02d}z — "
            f"{dxcc} te manque{' sur cette bande' if band!='6m' else ''}."
        )

    # ──────────────────────────────────────────────────────────────
    # Stats (pour dashboard)
    # ──────────────────────────────────────────────────────────────
    def get_stats(self) -> dict:
        try:
            with self._conn() as conn:
                spots_24h = conn.execute(
                    "SELECT COUNT(*) as c FROM spot_log WHERE ts > ?",
                    (time.time() - 86400,)
                ).fetchone()["c"]
                es_30d = conn.execute(
                    "SELECT COUNT(*) as c FROM es_events WHERE ts > ?",
                    (time.time() - 86400 * 30,)
                ).fetchone()["c"]
                missing_count = conn.execute(
                    "SELECT COUNT(*) as c FROM missing_dxcc"
                ).fetchone()["c"]
                sessions_7d = conn.execute(
                    "SELECT COUNT(*) as c FROM sessions WHERE ts_start > ?",
                    (time.time() - 86400 * 7,)
                ).fetchone()["c"]
            return {
                "spots_logged_24h": spots_24h,
                "es_events_30d":    es_30d,
                "missing_dxcc":     missing_count,
                "sessions_7d":      sessions_7d,
            }
        except Exception as e:
            return {"error": str(e)}

    def cleanup_old_data(self, days: int = 90):
        """Purger les données de plus de N jours (appelé par le maintenance_worker)."""
        cutoff = time.time() - days * 86400
        try:
            with self._lock, self._conn() as conn:
                conn.execute("DELETE FROM spot_log WHERE ts < ?", (cutoff,))
                conn.execute("DELETE FROM es_events WHERE ts < ?", (cutoff,))
                conn.execute("DELETE FROM sessions WHERE ts_last < ?", (cutoff,))
            logger.info(f"Predictor: données > {days}j purgées")
        except Exception as e:
            logger.warning(f"Predictor.cleanup: {e}")
