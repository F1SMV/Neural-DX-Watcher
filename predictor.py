"""
predictor.py — Moteur prédictif personnel NEURAL DX WATCHER v11.0
====================================================================
Refonte complète depuis la v10.0 (coefficients manuels non mesurés) vers
un moteur qui :
  1. résout correctement les préfixes DXCC via cty.dat (dxcc_resolver.py)
     — corrige le bug historique où _extract_prefix() découpait aveuglément
     les 3 premiers caractères, y compris sur un nom de pays LoTW
     ("Germany" → "GER" au lieu de "DL").
  2. distingue 4 modèles de propagation : HF (ionosphérique/MUF), Es 6m,
     tropo VHF/UHF, et un boost TEP (trans-équatorial) superposable.
  3. enregistre chaque prédiction émise, puis vérifie automatiquement à
     l'échéance si elle s'est réalisée (comparaison aux spots réels reçus).
  4. affiche une fiabilité MESURÉE ("X% sur 30 jours — N observations"),
     pas une confiance affichée arbitrairement.
  5. calcule la probabilité en mélangeant l'heuristique avec un taux
     empirique tiré de l'historique réel (bande, heure, saison, direction)
     via un lissage bayésien simple — plus l'historique est riche, plus le
     score final se rapproche de la réalité observée plutôt que du modèle
     théorique de départ.

Limitation connue et assumée : le lissage empirique porte sur bande/heure/
saison/direction, PAS sur SFI/Kp historiques (ces séries ne sont pas
encore journalisées). Une table solar_log est prévue et prête à l'usage
(record_solar_sample) pour une v12 qui pourra affiner ce dernier axe —
non branchée automatiquement, à appeler depuis solar_worker si souhaité.

Usage (API publique inchangée vis-à-vis de webapp.py, sauf ajouts) :
    from predictor import Predictor
    p = Predictor(db_path="data/predictor.sqlite", my_call="F1SMV", cty_path="cty.dat")
    p.record_spot(spot_obj)
    p.record_session_heartbeat()
    predictions = p.get_predictions()
    p.verify_predictions()          # NOUVEAU — à appeler périodiquement (maintenance_worker)
    p.get_reliability_stats()       # NOUVEAU — pour affichage frontend
"""

import sqlite3
import time
import math
import threading
import logging
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dxcc_resolver import get_resolver

logger = logging.getLogger("predictor")

# ─── Patterns Es saisonniers/horaires (source : DXMaps / archives 2010-2024) ───
ES_SEASONAL_HOURLY = {
    1:  {h: 0.04 for h in range(24)},
    2:  {h: 0.05 for h in range(24)},
    3:  {h: 0.07 for h in range(24)},
    4:  {h: max(0.07, 0.15 * math.sin(max(0, (h - 8) / 14 * math.pi))) for h in range(24)},
    5:  {h: max(0.10, 0.55 * math.sin(max(0, (h - 7) / 15 * math.pi))) for h in range(24)},
    6:  {h: max(0.12, 0.75 * math.sin(max(0, (h - 7) / 16 * math.pi))) for h in range(24)},
    7:  {h: max(0.10, 0.65 * math.sin(max(0, (h - 8) / 15 * math.pi))) for h in range(24)},
    8:  {h: max(0.07, 0.30 * math.sin(max(0, (h - 8) / 14 * math.pi))) for h in range(24)},
    9:  {h: max(0.05, 0.12 * math.sin(max(0, (h - 9) / 12 * math.pi))) for h in range(24)},
    10: {h: max(0.04, 0.08 * math.sin(max(0, (h - 9) / 11 * math.pi))) for h in range(24)},
    11: {h: 0.04 for h in range(24)},
    12: {h: 0.04 for h in range(24)},
}

# Boost directionnel Es par préfixe (path EU → XX). Utilisé par le modèle Es.
ES_PATH_BOOST = {
    "JA": 0.45, "JT": 0.55, "UA0": 0.50, "VK": 0.40,
    "W":  0.38, "VE": 0.35, "PY": 0.30,
    "EA": 0.90, "F":  0.95, "DL": 0.92, "I":  0.88,
    "SP": 0.85, "OM": 0.84, "OK": 0.84, "OZ": 0.80,
    "SM": 0.78, "OH": 0.78, "LA": 0.76, "SV": 0.75,
    "LZ": 0.72, "TA": 0.68, "4X": 0.65, "5B": 0.65,
    "ZS": 0.35, "VU": 0.42, "HL": 0.48,
}

# Bandes HF : facteur de dépendance MUF/SFI (10m très dépendant, 80m peu)
HF_BAND_SFI_FACTOR = {
    "10m": 1.00, "12m": 0.90, "15m": 0.80, "17m": 0.65,
    "20m": 0.50, "40m": 0.25, "80m": 0.10, "160m": 0.05,
}
# Bandes HF : préférence diurne (1.0) vs nocturne (0.0) — 10-20m favorisées
# le jour (MUF haute), 40-160m favorisées la nuit (absorption D-layer nulle).
HF_BAND_DIURNAL_PREF = {
    "10m": 1.0, "12m": 0.95, "15m": 0.85, "17m": 0.65,
    "20m": 0.45, "40m": 0.15, "80m": 0.05, "160m": 0.02,
}

# Bandes tropo VHF/UHF : moins saisonnier que Es, plus dépendant d'un
# gradient anticyclonique qu'on ne mesure pas ici — on approxime par un
# bonus crépusculaire (inversions de couche fréquentes matin/soir).
TROPO_BANDS = {"2m", "4m", "70cm", "23cm"}
ES_BANDS = {"6m"}

# Bandes où le TEP (Trans-Equatorial Propagation) peut se superposer,
# typiquement en soirée locale près des équinoxes, sur des trajets qui
# traversent l'équateur géomagnétique.
TEP_ELIGIBLE_BANDS = {"6m", "10m", "15m"}

WINDOW_HOURS = 3
PRED_HORIZON = 24
TOP_N_PRED   = 5

# Poids du prior (heuristique) dans le lissage bayésien empirique.
# Plus élevé = il faut plus d'observations réelles pour que l'empirique
# prenne le dessus sur le modèle théorique de départ.
EMPIRICAL_PRIOR_WEIGHT = 8
HISTORY_INDEX_TTL = 1800  # 30 min — recalcul de l'index empirique

DB_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_start   REAL NOT NULL,
    ts_last    REAL NOT NULL,
    bands      TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS spot_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         REAL NOT NULL,
    dx_call    TEXT NOT NULL,
    dxcc       TEXT,
    prefix     TEXT,
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

CREATE TABLE IF NOT EXISTS prediction_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    created_ts        REAL NOT NULL,
    target_ts_start   REAL NOT NULL,
    target_ts_end     REAL NOT NULL,
    target_hour_bucket INTEGER NOT NULL,
    band             TEXT NOT NULL,
    dxcc             TEXT NOT NULL,
    prefix           TEXT NOT NULL,
    model            TEXT NOT NULL,
    predicted_score  REAL NOT NULL,
    verified         INTEGER DEFAULT 0,
    realized         INTEGER,
    observed_spots   INTEGER DEFAULT 0,
    verified_ts      REAL,
    UNIQUE(band, prefix, target_hour_bucket)
);

CREATE TABLE IF NOT EXISTS solar_log (
    ts  REAL PRIMARY KEY,
    sfi REAL,
    kp  REAL
);

CREATE INDEX IF NOT EXISTS idx_spot_log_ts       ON spot_log(ts);
CREATE INDEX IF NOT EXISTS idx_spot_log_dx       ON spot_log(dx_call);
CREATE INDEX IF NOT EXISTS idx_spot_log_band     ON spot_log(band);
CREATE INDEX IF NOT EXISTS idx_es_events_month   ON es_events(month, hour_utc);
CREATE INDEX IF NOT EXISTS idx_pred_log_target   ON prediction_log(target_ts_end);
CREATE INDEX IF NOT EXISTS idx_pred_log_verified ON prediction_log(verified);
"""


class Predictor:
    """Moteur prédictif personnel NEURAL DX — v11 (mesuré, pas heuristique seul)."""

    def __init__(self, db_path: str = "data/predictor.sqlite",
                 my_call: str = "F1SMV", cty_path: str = "cty.dat"):
        self.db_path  = Path(db_path)
        self.my_call  = my_call
        self._lock    = threading.Lock()
        self._session_id: Optional[int] = None
        self._session_ts_last: float = 0
        self._session_bands: set = set()

        self._resolver = get_resolver(cty_path)

        self._pred_cache: list = []
        self._pred_cache_ts: float = 0
        self._pred_cache_ttl: float = 600

        self._history_index: dict = {}
        self._history_index_ts: float = 0

        self._init_db()
        logger.info(
            f"Predictor v11 initialisé → {self.db_path} "
            f"(résolveur DXCC: {'dégradé' if self._resolver.is_degraded() else 'actif'} "
            f"— {self._resolver.stats()})"
        )

    # ──────────────────────────────────────────────────────────────
    # Init DB — connexion persistante unique (cf. correctif v10 conservé)
    # ──────────────────────────────────────────────────────────────
    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(
            str(self.db_path), check_same_thread=False, timeout=30
        )
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(DB_SCHEMA)
        self._db.commit()

        # Migration douce : ajouter la colonne prefix si absente (bases v10
        # existantes créées avant cette refonte). DOIT s'exécuter AVANT la
        # création de l'index sur cette colonne, sinon SQLite échoue avec
        # "no such column: prefix" si la table préexistait sans elle.
        try:
            self._db.execute("ALTER TABLE spot_log ADD COLUMN prefix TEXT")
            self._db.commit()
            logger.info("Predictor: migration — colonne 'prefix' ajoutée à spot_log")
        except sqlite3.OperationalError:
            pass  # colonne déjà présente

        # Index sur prefix — créé séparément, après garantie que la colonne existe.
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_spot_log_prefix ON spot_log(prefix)")
        self._db.commit()

    def _conn(self) -> sqlite3.Connection:
        return self._db

    def close(self):
        try:
            self._db.close()
        except Exception:
            pass

    def reload_cty(self):
        """À appeler après un téléchargement d'un nouveau cty.dat."""
        self._resolver.reload()
        logger.info(f"Predictor: cty.dat rechargé — {self._resolver.stats()}")

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

            # Résolution DXCC unifiée (corrige l'ancien bug _extract_prefix)
            info = self._resolver.resolve(dx_call)
            prefix = info["prefix"] if info else dx_call.upper()[:3]

            with self._lock, self._conn() as conn:
                conn.execute(
                    "INSERT INTO spot_log(ts, dx_call, dxcc, prefix, band, mode, "
                    "freq_khz, spd_score, is_watchlist, is_wanted) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (ts, dx_call, dxcc, prefix, band, mode, freq_khz, score,
                     int(is_watchlist), is_wanted)
                )
                if band in ES_BANDS:
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    conn.execute(
                        "INSERT INTO es_events(ts, month, hour_utc, path_prefix, band, spot_count) "
                        "VALUES (?,?,?,?,?,1)",
                        (ts, dt.month, dt.hour, prefix, band)
                    )
                self._session_bands.add(band)
        except Exception as e:
            logger.warning(f"Predictor.record_spot: {e}")

    # ──────────────────────────────────────────────────────────────
    # Brique 1b : Collecte — sessions opérateur
    # ──────────────────────────────────────────────────────────────
    def record_session_heartbeat(self):
        now = time.time()
        try:
            with self._lock, self._conn() as conn:
                if self._session_id is None or (now - self._session_ts_last) > 120:
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
        missing = [{"dxcc": "JT1"|"Germany"|"F4ABC", "band": "6m", "mode": "FT8"}, ...]
        Le champ "dxcc" peut être un préfixe, un indicatif ou un nom de pays —
        peu importe, la résolution est déléguée à dxcc_resolver au moment
        du scoring (get_predictions), pas ici (on stocke la valeur brute).
        """
        now = time.time()
        try:
            with self._lock, self._conn() as conn:
                conn.execute("DELETE FROM missing_dxcc")
                conn.executemany(
                    "INSERT OR REPLACE INTO missing_dxcc(dxcc, band, mode, updated_at) VALUES (?,?,?,?)",
                    [(m["dxcc"], m["band"], m.get("mode", ""), now) for m in missing]
                )
            logger.info(f"Predictor: {len(missing)} DXCC manquants sync")
        except Exception as e:
            logger.warning(f"Predictor.sync_missing_dxcc: {e}")

    # ──────────────────────────────────────────────────────────────
    # Brique 1d (nouveau) : Collecte solaire — prête pour v12
    # ──────────────────────────────────────────────────────────────
    def record_solar_sample(self, sfi: float, kp: float):
        """
        À appeler périodiquement depuis solar_worker (webapp.py) pour
        commencer à journaliser l'historique SFI/Kp. Non branché
        automatiquement dans cette version — l'appel est à ajouter
        manuellement côté webapp.py si l'on souhaite affiner le modèle
        HF avec une corrélation SFI/Kp historique réelle (v12).
        """
        try:
            with self._lock, self._conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO solar_log(ts, sfi, kp) VALUES (?,?,?)",
                    (time.time(), sfi, kp)
                )
        except Exception as e:
            logger.debug(f"Predictor.record_solar_sample: {e}")

    # ──────────────────────────────────────────────────────────────
    # Brique 2 : Scoring — dispatch par modèle de propagation
    # ──────────────────────────────────────────────────────────────
    def _band_model(self, band: str) -> str:
        if band in ES_BANDS:
            return "es"
        if band in TROPO_BANDS:
            return "tropo"
        return "hf"

    def _score_window(self, month: int, hour_utc: int, band: str,
                       prefix: str, sfi: float, kp: float) -> tuple[float, str]:
        """Retourne (score 0..1, nom du modèle utilisé)."""
        model = self._band_model(band)
        if model == "es":
            heuristic = self._score_es(month, hour_utc, band, prefix, sfi, kp)
        elif model == "tropo":
            heuristic = self._score_tropo(month, hour_utc, band, prefix)
        else:
            heuristic = self._score_hf(month, hour_utc, band, prefix, sfi, kp)

        # Boost TEP superposable, indépendant du modèle de base
        if band in TEP_ELIGIBLE_BANDS:
            heuristic += self._tep_boost(month, hour_utc, prefix)

        heuristic = min(1.0, max(0.0, heuristic))

        # Lissage empirique : mélange avec le taux réellement observé
        # dans l'historique pour ce bin (band, heure, mois, préfixe).
        empirical_rate, n_obs = self._empirical_rate(band, hour_utc, month, prefix)
        if n_obs > 0:
            k = EMPIRICAL_PRIOR_WEIGHT
            final = (heuristic * k + empirical_rate * n_obs) / (k + n_obs)
        else:
            final = heuristic

        return min(1.0, max(0.0, final)), model

    def _score_es(self, month, hour_utc, band, prefix, sfi, kp) -> float:
        es_base = ES_SEASONAL_HOURLY.get(month, {}).get(hour_utc, 0.04)
        path_boost = 0.50  # neutre par défaut
        for pfx, boost in ES_PATH_BOOST.items():
            if prefix.startswith(pfx):
                path_boost = boost
                break
        # Es quasi indépendant du SFI ; forte dégradation si Kp élevé (orage géomagnétique)
        solar_f = 1.0
        if kp > 5:
            solar_f *= max(0.3, 1.0 - (kp - 5) * 0.12)
        history_bonus = self._es_history_bonus(month, hour_utc, prefix, band)
        return es_base * path_boost * solar_f + history_bonus

    def _score_hf(self, month, hour_utc, band, prefix, sfi, kp) -> float:
        sfi_factor = HF_BAND_SFI_FACTOR.get(band, 0.30)
        solar_f = max(0.05, min(1.0, (sfi - 65) / 135)) * sfi_factor
        if kp > 4:
            solar_f *= max(0.15, 1.0 - (kp - 4) * 0.18)
        # Préférence diurne/nocturne selon la bande (approx via sin sur 24h,
        # pic vers 12z pour les bandes hautes, creux vers 12z pour les basses)
        diurnal_pref = HF_BAND_DIURNAL_PREF.get(band, 0.5)
        diurnal = 0.5 + 0.5 * math.cos((hour_utc - 12) / 24 * 2 * math.pi)
        diurnal_score = diurnal * diurnal_pref + (1 - diurnal) * (1 - diurnal_pref)
        return solar_f * (0.35 + diurnal_score * 0.65)

    def _score_tropo(self, month, hour_utc, band, prefix) -> float:
        # Tropo : peu saisonnier, bonus crépusculaire (inversions matin/soir),
        # légèrement meilleur en été (gradients thermiques plus marqués).
        summer_bonus = 0.10 if month in (6, 7, 8, 9) else 0.0
        is_dawn_dusk = hour_utc in (5, 6, 7, 18, 19, 20, 21)
        base = 0.22 + (0.15 if is_dawn_dusk else 0.0) + summer_bonus
        return min(0.85, base)

    def _tep_boost(self, month, hour_utc, prefix) -> float:
        """
        Boost TEP : trajets traversant l'équateur géomagnétique, en soirée
        locale, proche des équinoxes (mars/avril, septembre/octobre).
        Approximation : on ne connaît pas la latitude exacte du DX ici sans
        appel supplémentaire au résolveur — le boost est appliqué de façon
        conservative sur la fenêtre horaire/saisonnière uniquement.
        """
        is_equinox_season = month in (3, 4, 9, 10)
        is_evening = 16 <= hour_utc <= 21
        if is_equinox_season and is_evening:
            return 0.12
        return 0.0

    def _es_history_bonus(self, month: int, hour_utc: int, prefix: str, band: str) -> float:
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) as c FROM es_events "
                    "WHERE month BETWEEN ? AND ? AND hour_utc BETWEEN ? AND ? "
                    "AND path_prefix=? AND band=?",
                    (max(1, month - 1), min(12, month + 1),
                     max(0, hour_utc - 1), min(23, hour_utc + 1), prefix, band)
                ).fetchone()
                count = row["c"] if row else 0
                return min(0.15, math.log1p(count) * 0.04)
        except Exception:
            return 0.0

    # ──────────────────────────────────────────────────────────────
    # Index empirique (bande, heure, mois, préfixe) — recalculé toutes les 30 min
    # ──────────────────────────────────────────────────────────────
    def _build_history_index(self):
        """
        Reconstruit un index en mémoire {(band,prefix,hour_bucket,month): count}
        depuis les 120 derniers jours de spot_log, plus un total par bande
        pour normaliser en taux relatif (même logique que /api/reality-check).
        """
        cutoff = time.time() - 120 * 86400
        index = {}
        band_totals = {}
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT ts, band, prefix FROM spot_log WHERE ts >= ? AND prefix IS NOT NULL",
                    (cutoff,)
                ).fetchall()
            for r in rows:
                dt = datetime.fromtimestamp(r["ts"], tz=timezone.utc)
                hour_bucket = dt.hour  # bucket fin (lissé ±1 à la lecture)
                key = (r["band"], r["prefix"], hour_bucket, dt.month)
                index[key] = index.get(key, 0) + 1
                band_totals[r["band"]] = band_totals.get(r["band"], 0) + 1
        except Exception as e:
            logger.debug(f"Predictor._build_history_index: {e}")

        self._history_index = {"bins": index, "band_totals": band_totals}
        self._history_index_ts = time.time()

    def _empirical_rate(self, band: str, hour_utc: int, month: int, prefix: str) -> tuple[float, int]:
        """Retourne (taux empirique 0..1, nb d'observations dans le bin élargi)."""
        if (time.time() - self._history_index_ts) > HISTORY_INDEX_TTL or not self._history_index:
            self._build_history_index()

        bins = self._history_index.get("bins", {})
        band_totals = self._history_index.get("band_totals", {})
        total = band_totals.get(band, 0)
        if total == 0:
            return 0.0, 0

        # Élargir ±1h et considérer le mois exact + voisins immédiats
        n = 0
        for dh in (-1, 0, 1):
            for dm in (-1, 0, 1):
                h = (hour_utc + dh) % 24
                m = ((month - 1 + dm) % 12) + 1
                n += bins.get((band, prefix, h, m), 0)

        # Taux relatif : intensité de ce bin vs. intensité moyenne attendue
        # si l'activité était uniformément répartie sur 24h × 12 mois.
        expected_uniform = total / (24 * 12) * 9  # 9 = 3×3 cases élargies
        rate = min(1.0, n / expected_uniform) if expected_uniform > 0 else 0.0
        return rate, n

    # ──────────────────────────────────────────────────────────────
    # Brique 3 : Génération des prédictions
    # ──────────────────────────────────────────────────────────────
    def get_predictions(self, sfi: float = 120, kp: float = 2) -> list[dict]:
        now = time.time()
        if now - self._pred_cache_ts < self._pred_cache_ttl and self._pred_cache:
            return self._pred_cache

        missing = self._get_missing_dxcc()
        candidates = []

        for delta_h in range(1, PRED_HORIZON + 1):
            future_ts = now + delta_h * 3600
            future_dt = datetime.fromtimestamp(future_ts, tz=timezone.utc)
            month, hour_utc = future_dt.month, future_dt.hour

            for m in missing[:30]:
                dxcc_raw = m["dxcc"]
                band     = m["band"]
                mode     = m.get("mode", "")

                # Résolution unifiée — gère indicatif, préfixe ou nom de pays
                info   = self._resolver.resolve(dxcc_raw)
                prefix = info["prefix"] if info else dxcc_raw.upper()[:3]

                score, model = self._score_window(month, hour_utc, band, prefix, sfi, kp)
                if score < 0.20:
                    continue

                label = self._format_label(future_dt, band, dxcc_raw)
                tip   = self._format_tip(future_dt, band, dxcc_raw, mode, score, model)
                candidates.append({
                    "ts_utc":   int(future_ts),
                    "hour_utc": hour_utc,
                    "delta_h":  delta_h,
                    "band":     band,
                    "dxcc":     dxcc_raw,
                    "prefix":   prefix,
                    "mode":     mode,
                    "model":    model,
                    "score":    round(score, 3),
                    "label":    label,
                    "tip":      tip,
                    "missing":  True,
                })

        candidates.sort(key=lambda x: -x["score"])
        seen, top = set(), []
        for c in candidates:
            key = (c["band"], c["dxcc"])
            if key not in seen:
                seen.add(key)
                top.append(c)
            if len(top) >= TOP_N_PRED:
                break

        # Ajouter le contexte de fiabilité mesurée à chaque prédiction
        reliability = self.get_reliability_stats()
        for c in top:
            c["reliability"] = reliability

        self._log_predictions(top, now)

        self._pred_cache    = top
        self._pred_cache_ts = now
        return top

    def invalidate_cache(self):
        self._pred_cache_ts = 0

    # ──────────────────────────────────────────────────────────────
    # Brique 4 : Journalisation + auto-vérification des prédictions
    # ──────────────────────────────────────────────────────────────
    def _log_predictions(self, predictions: list[dict], now: float):
        """
        Enregistre chaque prédiction émise pour vérification ultérieure.
        Dédupliqué par (band, prefix, heure cible arrondie) via contrainte
        UNIQUE — une même fenêtre n'est journalisée qu'une fois, même si
        get_predictions() est rappelé plusieurs fois avant son échéance.
        """
        try:
            with self._lock, self._conn() as conn:
                for p in predictions:
                    target_start = p["ts_utc"]
                    target_end   = target_start + WINDOW_HOURS * 3600
                    hour_bucket  = int(target_start // 3600)
                    conn.execute(
                        "INSERT OR IGNORE INTO prediction_log "
                        "(created_ts, target_ts_start, target_ts_end, target_hour_bucket, "
                        " band, dxcc, prefix, model, predicted_score) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (now, target_start, target_end, hour_bucket,
                         p["band"], p["dxcc"], p["prefix"], p["model"], p["score"])
                    )
        except Exception as e:
            logger.debug(f"Predictor._log_predictions: {e}")

    def verify_predictions(self):
        """
        À appeler périodiquement (ex: depuis maintenance_worker, toutes les
        heures) — vérifie les prédictions dont la fenêtre cible est échue
        et non encore vérifiée, en comparant aux spots réellement reçus.
        Une prédiction est "réalisée" si au moins 1 spot correspondant
        (même bande, même préfixe) a été observé dans sa fenêtre cible.
        """
        now = time.time()
        try:
            with self._lock, self._conn() as conn:
                pending = conn.execute(
                    "SELECT id, band, prefix, target_ts_start, target_ts_end "
                    "FROM prediction_log WHERE verified=0 AND target_ts_end < ?",
                    (now,)
                ).fetchall()

                for row in pending:
                    count_row = conn.execute(
                        "SELECT COUNT(*) as c FROM spot_log "
                        "WHERE band=? AND prefix=? AND ts BETWEEN ? AND ?",
                        (row["band"], row["prefix"], row["target_ts_start"], row["target_ts_end"])
                    ).fetchone()
                    observed = count_row["c"] if count_row else 0
                    realized = 1 if observed >= 1 else 0
                    conn.execute(
                        "UPDATE prediction_log SET verified=1, realized=?, "
                        "observed_spots=?, verified_ts=? WHERE id=?",
                        (realized, observed, now, row["id"])
                    )
            if pending:
                logger.info(f"Predictor: {len(pending)} prédictions vérifiées")
        except Exception as e:
            logger.warning(f"Predictor.verify_predictions: {e}")

    def get_reliability_stats(self, days: int = 30) -> dict:
        """
        Fiabilité MESURÉE du prédicteur — pas une valeur affichée par défaut.
        Retourne {"reliability_pct": int|None, "observations": int, "days": int,
                  "by_model": {"es": {...}, "hf": {...}, "tropo": {...}}}
        None si aucune observation encore vérifiée (prédicteur trop jeune).
        """
        cutoff = time.time() - days * 86400
        try:
            with self._conn() as conn:
                overall = conn.execute(
                    "SELECT COUNT(*) as n, SUM(realized) as hits FROM prediction_log "
                    "WHERE verified=1 AND created_ts > ?", (cutoff,)
                ).fetchone()
                n_total = overall["n"] or 0
                hits_total = overall["hits"] or 0

                by_model = {}
                for model in ("es", "hf", "tropo"):
                    row = conn.execute(
                        "SELECT COUNT(*) as n, SUM(realized) as hits FROM prediction_log "
                        "WHERE verified=1 AND created_ts > ? AND model=?",
                        (cutoff, model)
                    ).fetchone()
                    n_m = row["n"] or 0
                    hits_m = row["hits"] or 0
                    by_model[model] = {
                        "reliability_pct": round(100 * hits_m / n_m) if n_m > 0 else None,
                        "observations": n_m,
                    }

            return {
                "reliability_pct": round(100 * hits_total / n_total) if n_total > 0 else None,
                "observations": n_total,
                "days": days,
                "by_model": by_model,
            }
        except Exception as e:
            logger.debug(f"Predictor.get_reliability_stats: {e}")
            return {"reliability_pct": None, "observations": 0, "days": days, "by_model": {}}

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
    def _format_label(dt: datetime, band: str, dxcc: str) -> str:
        return f"{dt.hour:02d}h UTC · {band} → {dxcc}"

    @staticmethod
    def _format_tip(dt: datetime, band: str, dxcc: str, mode: str, score: float, model: str) -> str:
        pct  = int(score * 100)
        hour = dt.hour
        end  = (hour + WINDOW_HOURS) % 24
        mood = "forte" if score > 0.6 else "modérée" if score > 0.35 else "faible"
        mode_str = f" en {mode}" if mode else ""
        model_label = {"es": "Es", "hf": "HF", "tropo": "tropo"}.get(model, model)
        return (
            f"Probabilité {mood} ({pct}%, modèle {model_label}) d'ouverture {band} "
            f"vers {dxcc}{mode_str} entre {hour:02d}z et {end:02d}z — "
            f"{dxcc} te manque{' sur cette bande' if band != '6m' else ''}."
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
                "reliability":      self.get_reliability_stats(),
                "resolver":         self._resolver.stats(),
            }
        except Exception as e:
            return {"error": str(e)}

    def cleanup_old_data(self, days: int = 90):
        cutoff = time.time() - days * 86400
        try:
            with self._lock, self._conn() as conn:
                conn.execute("DELETE FROM spot_log WHERE ts < ?", (cutoff,))
                conn.execute("DELETE FROM es_events WHERE ts < ?", (cutoff,))
                conn.execute("DELETE FROM sessions WHERE ts_last < ?", (cutoff,))
                # Garder prediction_log plus longtemps (180j) pour un historique
                # de fiabilité significatif — c'est une table légère.
                conn.execute("DELETE FROM prediction_log WHERE created_ts < ?",
                             (time.time() - 180 * 86400,))
                conn.execute("DELETE FROM solar_log WHERE ts < ?", (cutoff,))
            logger.info(f"Predictor: données > {days}j purgées")
        except Exception as e:
            logger.warning(f"Predictor.cleanup: {e}")
