"""
adaptive/events.py — Propagation Events FSM (CDC v13 §8)

Machine d'état par bande :
    IDLE → RISING → OPENING → STRONG → PEAK → DECLINING → CLOSED

Chaque événement conserve : bande, début, pic, fin, durée, mécanisme,
confiance, spots, calls, locators, distances, SPD, bearing dominant,
zones, météo et solaire.

Usage :
    from adaptive.events import PropagationFSM
    fsm = PropagationFSM(db_path="data/predictor.sqlite")
    fsm.feed_spot(spot_obj)           # appelé par telnet_worker
    state = fsm.get_state("6m")       # état courant
    events = fsm.recent_events("6m")  # événements terminés
"""

import sqlite3
import time
import math
import logging
import threading
from collections import defaultdict, deque

logger = logging.getLogger("adaptive.events")

# ── États ────────────────────────────────────────────────────────────────
STATES = ("IDLE", "RISING", "OPENING", "STRONG", "PEAK", "DECLINING", "CLOSED")

# ── Seuils par catégorie de bande ────────────────────────────────────────
# (spots/window, unique_calls, unique_locators_4char)
# Ajustables par l'Optimizer (§13) ultérieurement.

_ES_THRESHOLDS = {
    "window_sec":       300,      # fenêtre glissante 5 min
    "rising_spots":     3,        # IDLE → RISING
    "opening_spots":    6,        # RISING → OPENING
    "opening_locators": 3,
    "strong_spots":     15,       # OPENING → STRONG
    "strong_locators":  5,
    "strong_dist_km":   1000,
    "declining_drop":   0.5,      # ratio spot_rate / peak_rate pour DECLINING
    "closed_spots":     2,        # sous ce seuil → CLOSED
    "closed_sustain_s": 600,      # soutenu 10 min sous le seuil
}

_HF_THRESHOLDS = {
    "window_sec":       300,
    "rising_spots":     5,
    "opening_spots":    10,
    "opening_locators": 4,
    "strong_spots":     25,
    "strong_locators":  8,
    "strong_dist_km":   3000,
    "declining_drop":   0.5,
    "closed_spots":     3,
    "closed_sustain_s": 600,
}

_TROPO_THRESHOLDS = {
    "window_sec":       600,      # fenêtre plus large (tropo = lent)
    "rising_spots":     2,
    "opening_spots":    4,
    "opening_locators": 2,
    "strong_spots":     10,
    "strong_locators":  4,
    "strong_dist_km":   400,
    "declining_drop":   0.5,
    "closed_spots":     1,
    "closed_sustain_s": 900,
}

VHF_BANDS = {"6m", "4m", "2m", "70cm", "23cm"}
ES_BANDS = {"6m", "4m"}
TROPO_BANDS = {"2m", "70cm", "23cm"}

def _thresholds_for(band):
    if band in ES_BANDS:
        return dict(_ES_THRESHOLDS)
    if band in TROPO_BANDS:
        return dict(_TROPO_THRESHOLDS)
    return dict(_HF_THRESHOLDS)


# ── Helpers géo ──────────────────────────────────────────────────────────

def _locator_4(lat, lon):
    """Maidenhead 4 chars depuis lat/lon."""
    try:
        lon2 = lon + 180
        lat2 = lat + 90
        a = int(lon2 / 20)
        b = int(lat2 / 10)
        c = int((lon2 - a * 20) / 2)
        d = int(lat2 - b * 10)
        return f"{chr(65+a)}{chr(65+b)}{c}{d}"
    except Exception:
        return "XX00"

def _bearing(lat1, lon1, lat2, lon2):
    """Bearing initial en degrés."""
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(rlat2)
    y = math.cos(rlat1) * math.sin(rlat2) - math.sin(rlat1) * math.cos(rlat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360

def _bearing_sector(brg):
    """Bearing → secteur cardinal (N, NE, E, SE, S, SW, W, NW)."""
    sectors = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return sectors[int((brg + 22.5) / 45) % 8]

def _distance(lat1, lon1, lat2, lon2):
    """Distance Haversine en km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Table SQLite ─────────────────────────────────────────────────────────

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS propagation_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    band            TEXT    NOT NULL,
    mechanism       TEXT    DEFAULT 'Unknown',
    state_final     TEXT    NOT NULL,
    ts_start        REAL    NOT NULL,
    ts_peak         REAL,
    ts_end          REAL    NOT NULL,
    duration_sec    REAL,
    peak_spots      INTEGER DEFAULT 0,
    total_spots     INTEGER DEFAULT 0,
    unique_calls    INTEGER DEFAULT 0,
    unique_locators INTEGER DEFAULT 0,
    median_dist_km  REAL,
    max_dist_km     REAL,
    mean_spd        REAL,
    max_spd         REAL,
    bearing_dominant TEXT,
    confidence      TEXT    DEFAULT 'LOW',
    model_version   TEXT
);
"""
_CREATE_IDX = "CREATE INDEX IF NOT EXISTS idx_pe_band_ts ON propagation_events(band, ts_start);"


# ── Band Tracker (état vivant d'une bande) ───────────────────────────────

class _BandTracker:
    """Suit l'activité d'une bande en temps réel et gère les transitions FSM."""

    def __init__(self, band, user_lat=0.0, user_lon=0.0):
        self.band = band
        self.user_lat = user_lat
        self.user_lon = user_lon
        self.th = _thresholds_for(band)
        self.state = "IDLE"
        self.spots = deque()          # (ts, call, lat, lon, spd)
        self.event_spots = []         # spots de l'événement en cours
        self.ts_start = None
        self.ts_peak = None
        self.peak_rate = 0
        self.below_since = None       # timestamp du passage sous closed_spots

    def _window_spots(self, now):
        """Spots dans la fenêtre glissante."""
        cutoff = now - self.th["window_sec"]
        while self.spots and self.spots[0][0] < cutoff:
            self.spots.popleft()
        return list(self.spots)

    def _metrics(self, spots):
        """Calcule les métriques d'activité sur un ensemble de spots."""
        calls = set()
        locators = set()
        distances = []
        bearings = []
        spds = []
        for ts, call, lat, lon, spd in spots:
            calls.add(call)
            loc4 = _locator_4(lat, lon)
            locators.add(loc4)
            if lat and lon and (self.user_lat or self.user_lon):
                d = _distance(self.user_lat, self.user_lon, lat, lon)
                distances.append(d)
                b = _bearing(self.user_lat, self.user_lon, lat, lon)
                bearings.append(b)
            if spd:
                spds.append(spd)
        return {
            "count": len(spots),
            "calls": calls,
            "locators": locators,
            "unique_calls": len(calls),
            "unique_locators": len(locators),
            "distances": sorted(distances),
            "bearings": bearings,
            "spds": spds,
            "median_dist": distances[len(distances)//2] if distances else 0,
            "max_dist": max(distances) if distances else 0,
            "mean_spd": sum(spds)/len(spds) if spds else 0,
            "max_spd": max(spds) if spds else 0,
        }

    def _dominant_bearing(self, bearings):
        if not bearings:
            return None
        # Moyenne circulaire
        sx = sum(math.sin(math.radians(b)) for b in bearings)
        cx = sum(math.cos(math.radians(b)) for b in bearings)
        avg = (math.degrees(math.atan2(sx, cx)) + 360) % 360
        return _bearing_sector(avg)

    def feed(self, ts, call, lat, lon, spd):
        """Ajoute un spot et effectue la transition d'état.
        Retourne un dict événement si un événement vient de se FERMER, sinon None."""
        self.spots.append((ts, call, lat, lon, spd))

        if self.state != "IDLE" and self.state != "CLOSED":
            self.event_spots.append((ts, call, lat, lon, spd))

        now = ts
        win = self._window_spots(now)
        m = self._metrics(win)
        rate = m["count"]
        prev_state = self.state
        closed_event = None

        # ── Transitions ──
        if self.state == "IDLE":
            if rate >= self.th["rising_spots"]:
                self.state = "RISING"
                self.ts_start = now
                self.ts_peak = now
                self.peak_rate = rate
                self.event_spots = list(win)
                self.below_since = None

        elif self.state == "RISING":
            if rate >= self.th["opening_spots"] and m["unique_locators"] >= self.th["opening_locators"]:
                self.state = "OPENING"
            elif rate < self.th["rising_spots"]:
                # Faux départ → retour IDLE
                closed_event = self._close_event(now, "CLOSED")
                self.state = "IDLE"
            if rate > self.peak_rate:
                self.peak_rate = rate
                self.ts_peak = now

        elif self.state == "OPENING":
            if (rate >= self.th["strong_spots"] and
                m["unique_locators"] >= self.th["strong_locators"] and
                m["max_dist"] >= self.th["strong_dist_km"]):
                self.state = "STRONG"
            elif rate < self.th["rising_spots"]:
                self.state = "DECLINING"
            if rate > self.peak_rate:
                self.peak_rate = rate
                self.ts_peak = now

        elif self.state == "STRONG":
            if self.peak_rate > 0 and rate < self.peak_rate * 0.8:
                # Le taux a passé le pic
                self.state = "PEAK"
            if rate > self.peak_rate:
                self.peak_rate = rate
                self.ts_peak = now

        elif self.state == "PEAK":
            if self.peak_rate > 0 and rate <= self.peak_rate * self.th["declining_drop"]:
                self.state = "DECLINING"

        elif self.state == "DECLINING":
            if rate <= self.th["closed_spots"]:
                if self.below_since is None:
                    self.below_since = now
                elif now - self.below_since >= self.th["closed_sustain_s"]:
                    closed_event = self._close_event(now, "CLOSED")
                    self.state = "IDLE"
            else:
                self.below_since = None
                # Rebond possible
                if rate >= self.th["opening_spots"]:
                    self.state = "OPENING"

        if prev_state != self.state:
            logger.info(f"[FSM] {self.band}: {prev_state} → {self.state} "
                        f"(rate={rate}, calls={m['unique_calls']}, "
                        f"loc={m['unique_locators']}, max_d={m['max_dist']:.0f}km)")

        return closed_event

    def _close_event(self, ts_end, final_state):
        """Construit le dict d'un événement terminé."""
        m = self._metrics(self.event_spots)
        mechanism = self._classify_mechanism(m)
        confidence = self._assess_confidence(m)
        evt = {
            "band":             self.band,
            "mechanism":        mechanism,
            "state_final":      final_state,
            "ts_start":         self.ts_start or ts_end,
            "ts_peak":          self.ts_peak,
            "ts_end":           ts_end,
            "duration_sec":     ts_end - (self.ts_start or ts_end),
            "peak_spots":       self.peak_rate,
            "total_spots":      len(self.event_spots),
            "unique_calls":     m["unique_calls"],
            "unique_locators":  m["unique_locators"],
            "median_dist_km":   m["median_dist"],
            "max_dist_km":      m["max_dist"],
            "mean_spd":         m["mean_spd"],
            "max_spd":          m["max_spd"],
            "bearing_dominant": self._dominant_bearing(m["bearings"]),
            "confidence":       confidence,
        }
        # Reset
        self.event_spots = []
        self.ts_start = None
        self.ts_peak = None
        self.peak_rate = 0
        self.below_since = None
        return evt

    def _classify_mechanism(self, m):
        """Classification : Es, Tropo, Mixed, Unknown (§9)."""
        if self.band in ES_BANDS:
            if m["median_dist"] > 800:
                return "Es"
            if m["median_dist"] < 400 and m["max_dist"] < 600:
                return "Tropo"
            return "Mixed" if m["unique_locators"] > 3 else "Unknown"
        if self.band in TROPO_BANDS:
            if m["max_dist"] > 300:
                return "Tropo"
            return "Unknown"
        # HF
        return "HF"

    def _assess_confidence(self, m):
        """Confiance basée sur la quantité/diversité des données (§30)."""
        score = 0
        if m["unique_calls"] >= 10: score += 1
        if m["unique_locators"] >= 5: score += 1
        if m["count"] >= 20: score += 1
        if m["max_dist"] > 500: score += 1
        if score >= 3: return "HIGH"
        if score >= 2: return "MEDIUM"
        return "LOW"

    def get_state_info(self):
        """Retourne l'état courant avec métriques pour l'UI."""
        now = time.time()
        win = self._window_spots(now)
        m = self._metrics(win)
        return {
            "band": self.band,
            "state": self.state,
            "rate": m["count"],
            "unique_calls": m["unique_calls"],
            "unique_locators": m["unique_locators"],
            "max_dist_km": m["max_dist"],
            "bearing": self._dominant_bearing(m["bearings"]),
            "ts_start": self.ts_start,
            "duration_sec": (now - self.ts_start) if self.ts_start else 0,
            "peak_rate": self.peak_rate,
        }


# ── PropagationFSM (façade principale) ──────────────────────────────────

class PropagationFSM:
    """Gestionnaire FSM multi-bandes avec persistence SQLite."""

    def __init__(self, db_path="data/predictor.sqlite",
                 user_lat=0.0, user_lon=0.0):
        self.db_path = db_path
        self.user_lat = user_lat
        self.user_lon = user_lon
        self._trackers = {}   # band → _BandTracker
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        try:
            db = sqlite3.connect(self.db_path)
            db.execute(_CREATE_TABLE)
            db.execute(_CREATE_IDX)
            db.commit()
            db.close()
            logger.info("propagation_events table ready")
        except Exception as e:
            logger.warning(f"FSM DB init: {e}")

    def _tracker(self, band):
        if band not in self._trackers:
            self._trackers[band] = _BandTracker(
                band, self.user_lat, self.user_lon)
        return self._trackers[band]

    def feed_spot(self, spot):
        """Alimente la FSM avec un spot (dict issu de telnet_worker).
        Thread-safe."""
        band = spot.get("band", "")
        if not band or band == "Unknown":
            return
        call = (spot.get("dx_call") or "").upper()
        lat = spot.get("lat", 0.0)
        lon = spot.get("lon", 0.0)
        spd = spot.get("score", 0)
        ts = spot.get("timestamp", time.time())

        with self._lock:
            tracker = self._tracker(band)
            closed_event = tracker.feed(ts, call, lat, lon, spd)
            if closed_event:
                self._store_event(closed_event)

    def _store_event(self, evt):
        """Persiste un événement terminé en SQLite."""
        try:
            db = sqlite3.connect(self.db_path)
            db.execute("""
                INSERT INTO propagation_events
                (band, mechanism, state_final, ts_start, ts_peak, ts_end,
                 duration_sec, peak_spots, total_spots, unique_calls,
                 unique_locators, median_dist_km, max_dist_km,
                 mean_spd, max_spd, bearing_dominant, confidence)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                evt["band"], evt["mechanism"], evt["state_final"],
                evt["ts_start"], evt["ts_peak"], evt["ts_end"],
                evt["duration_sec"], evt["peak_spots"], evt["total_spots"],
                evt["unique_calls"], evt["unique_locators"],
                evt["median_dist_km"], evt["max_dist_km"],
                evt["mean_spd"], evt["max_spd"],
                evt["bearing_dominant"], evt["confidence"],
            ))
            db.commit()
            db.close()
            logger.info(f"[FSM] Event stored: {evt['band']} {evt['mechanism']} "
                        f"{evt['duration_sec']:.0f}s, {evt['total_spots']} spots, "
                        f"conf={evt['confidence']}")
        except Exception as e:
            logger.warning(f"FSM store event: {e}")

    def get_state(self, band):
        """État courant d'une bande (pour l'UI)."""
        with self._lock:
            if band in self._trackers:
                return self._trackers[band].get_state_info()
        return {"band": band, "state": "IDLE", "rate": 0}

    def get_all_states(self):
        """Tous les états courants (pour l'API)."""
        with self._lock:
            return {b: t.get_state_info() for b, t in self._trackers.items()}

    def recent_events(self, band=None, limit=20):
        """Événements terminés récents depuis SQLite."""
        try:
            db = sqlite3.connect(self.db_path)
            db.row_factory = sqlite3.Row
            if band:
                rows = db.execute(
                    "SELECT * FROM propagation_events WHERE band=? "
                    "ORDER BY ts_start DESC LIMIT ?", (band, limit)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM propagation_events "
                    "ORDER BY ts_start DESC LIMIT ?", (limit,)
                ).fetchall()
            db.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"FSM recent_events: {e}")
            return []

    def stats(self):
        """Statistiques globales pour le panneau Adaptive Insight."""
        try:
            db = sqlite3.connect(self.db_path)
            c = db.cursor()
            c.execute("SELECT COUNT(*) FROM propagation_events")
            total = c.fetchone()[0]
            c.execute("SELECT band, COUNT(*), AVG(duration_sec) "
                      "FROM propagation_events GROUP BY band")
            by_band = {r[0]: {"count": r[1], "avg_duration_sec": r[2]}
                       for r in c.fetchall()}
            c.execute("SELECT mechanism, COUNT(*) "
                      "FROM propagation_events GROUP BY mechanism")
            by_mech = {r[0]: r[1] for r in c.fetchall()}
            db.close()
            return {
                "total_events": total,
                "by_band": by_band,
                "by_mechanism": by_mech,
            }
        except Exception as e:
            logger.warning(f"FSM stats: {e}")
            return {"total_events": 0, "by_band": {}, "by_mechanism": {}}
