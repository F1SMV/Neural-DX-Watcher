"""
ntfy_alerts.py — Alertes push intelligentes NEURAL DX WATCHER v10.0
====================================================================
Intégration ntfy.sh (self-hosted ou cloud) pour trois types d'alertes :
  1. Watchlist spotté
  2. NEW DXCC sur bande manquante
  3. Ouverture 6m détectée (surge > threshold)

Anti-spam : cooldown SQLite par call/type.
Filtre présence : pause si l'opérateur est sur la page (heartbeat < 45s).

Configuration (variables d'env ou webapp.py) :
  NTFY_URL      = "https://ntfy.sh/neural-dx-f1smv-XXXXXX"
  NTFY_TOKEN    = ""        # optionnel si topic privé authentifié
  NTFY_ENABLED  = True
  NTFY_COOLDOWN = 900       # 15 min entre deux alertes identiques
  NTFY_PRESENCE_WINDOW = 45 # secondes — si l'op est là, on se tait
"""

import os
import time
import json
import sqlite3
import logging
import threading
from pathlib import Path

try:
    import requests as _requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

logger = logging.getLogger("ntfy_alerts")

NTFY_URL              = os.getenv("NTFY_URL", "")
NTFY_TOKEN            = os.getenv("NTFY_TOKEN", "")
NTFY_ENABLED          = os.getenv("NTFY_ENABLED", "1") == "1" and bool(NTFY_URL)
NTFY_COOLDOWN         = int(os.getenv("NTFY_COOLDOWN", "900"))
NTFY_PRESENCE_WINDOW  = int(os.getenv("NTFY_PRESENCE_WINDOW", "45"))

# Seuil de spots 6m sur 10 min pour déclencher l'alerte ouverture
NTFY_6M_SURGE_THRESHOLD = int(os.getenv("NTFY_6M_SURGE_THRESHOLD", "5"))

_ALERT_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS alerts_sent (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    key     TEXT NOT NULL UNIQUE,   -- "type:call" ou "type:dxcc:band"
    ts      REAL NOT NULL,
    count   INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_alerts_key ON alerts_sent(key);
"""


class NtfyAlerter:
    """Gestionnaire d'alertes push ntfy.sh."""

    def __init__(self, db_path: str = "data/ntfy_alerts.sqlite"):
        self._db_path  = Path(db_path)
        self._lock     = threading.Lock()
        self._presence_ts: float = 0   # dernière vue opérateur
        self._6m_surge_alerted: float = 0

        self._init_db()

        if not NTFY_ENABLED:
            logger.info("NtfyAlerter: NTFY_URL non configuré — alertes désactivées")
        else:
            logger.info(f"NtfyAlerter: actif → {NTFY_URL}")

    # ──────────────────────────────────────────────────────────────
    # DB
    # ──────────────────────────────────────────────────────────────
    def _init_db(self):
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.executescript(_ALERT_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self._db_path), check_same_thread=False, timeout=5)
        c.row_factory = sqlite3.Row
        return c

    # ──────────────────────────────────────────────────────────────
    # Présence opérateur
    # ──────────────────────────────────────────────────────────────
    def record_presence(self):
        """Appelé depuis POST /api/presence — l'opérateur est en train de regarder."""
        with self._lock:
            self._presence_ts = time.time()

    def _operator_present(self) -> bool:
        with self._lock:
            return (time.time() - self._presence_ts) < NTFY_PRESENCE_WINDOW

    # ──────────────────────────────────────────────────────────────
    # Anti-spam
    # ──────────────────────────────────────────────────────────────
    def _can_alert(self, key: str) -> bool:
        """True si on peut envoyer cette alerte (cooldown expiré ou jamais envoyée)."""
        now = time.time()
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT ts FROM alerts_sent WHERE key=?", (key,)
                ).fetchone()
                if row is None:
                    return True
                return (now - row["ts"]) > NTFY_COOLDOWN
        except Exception:
            return True

    def _mark_alerted(self, key: str):
        now = time.time()
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO alerts_sent(key, ts, count) VALUES(?,?,1) "
                    "ON CONFLICT(key) DO UPDATE SET ts=excluded.ts, count=count+1",
                    (key, now)
                )
        except Exception as e:
            logger.warning(f"NtfyAlerter._mark_alerted: {e}")

    # ──────────────────────────────────────────────────────────────
    # Envoi HTTP
    # ──────────────────────────────────────────────────────────────
    def _send(self, title: str, message: str,
              priority: str = "default", tags: list[str] | None = None):
        if not NTFY_ENABLED:
            return
        if not _REQUESTS_OK:
            logger.warning("ntfy: requests non disponible — pip install requests")
            return
        try:
            headers = {
                "Title":    title,
                "Priority": priority,
                "Tags":     ",".join(tags or ["radio"]),
                "Content-Type": "text/plain; charset=utf-8",
            }
            if NTFY_TOKEN:
                headers["Authorization"] = f"Bearer {NTFY_TOKEN}"
            resp = _requests.post(
                NTFY_URL,
                data=message.encode("utf-8"),
                headers=headers,
                timeout=8,
            )
            if resp.status_code >= 300:
                logger.warning(f"ntfy HTTP {resp.status_code}: {resp.text[:120]}")
            else:
                logger.info(f"ntfy ✓ {title!r}")
        except Exception as e:
            logger.warning(f"ntfy send error: {e}")

    # ──────────────────────────────────────────────────────────────
    # Trigger 1 : Watchlist spotté
    # ──────────────────────────────────────────────────────────────
    def on_watchlist_spot(self, spot: dict):
        """Appelé quand un call de la watchlist est spotté."""
        if self._operator_present():
            return
        call = spot.get("dx_call", "")
        key  = f"wl:{call}"
        if not self._can_alert(key):
            return
        band = spot.get("band", "")
        freq = spot.get("freq", "")
        mode = spot.get("mode", "")
        cty  = spot.get("country", "")
        self._send(
            title    = f"📡 {call} spoté — {cty}",
            message  = f"{freq} MHz · {band} · {mode}",
            priority = "high",
            tags     = ["radio", "bell"],
        )
        self._mark_alerted(key)

    # ──────────────────────────────────────────────────────────────
    # Trigger 2 : NEW DXCC sur bande manquante
    # ──────────────────────────────────────────────────────────────
    def on_new_dxcc(self, spot: dict, missing_bands: list[str]):
        """
        Appelé si le DXCC du spot n'est pas confirmé LoTW sur une des bandes active.
        missing_bands = bandes sur lesquelles ce DXCC manque encore.
        """
        if self._operator_present():
            return
        call = spot.get("dx_call", "")
        cty  = spot.get("country", "")
        band = spot.get("band", "")
        if band not in missing_bands:
            return
        key = f"new_dxcc:{cty}:{band}"
        if not self._can_alert(key):
            return
        freq = spot.get("freq", "")
        mode = spot.get("mode", "")
        self._send(
            title    = f"🌍 NEW DXCC — {cty} sur {band}",
            message  = f"{call} · {freq} MHz · {mode} — DXCC manquant sur {band} !",
            priority = "urgent",
            tags     = ["trophy", "tada"],
        )
        self._mark_alerted(key)

    # ──────────────────────────────────────────────────────────────
    # Trigger 3 : Ouverture 6m
    # ──────────────────────────────────────────────────────────────
    def on_6m_surge(self, spots_last_10min: int, top_paths: list[str]):
        """
        Appelé par analyze_surges() quand une ouverture 6m est détectée.
        spots_last_10min : nombre de spots 6m dans les 10 dernières minutes.
        top_paths : ["JA1AA", "EA5BV", …] — premiers callsigns spotés.
        """
        if self._operator_present():
            return
        if spots_last_10min < NTFY_6M_SURGE_THRESHOLD:
            return
        now = time.time()
        if (now - self._6m_surge_alerted) < NTFY_COOLDOWN:
            return

        paths_str = " · ".join(top_paths[:4]) if top_paths else "—"
        self._send(
            title    = f"⚡ 6m OPEN — {spots_last_10min} spots/10min",
            message  = f"Ouverture détectée → {paths_str}",
            priority = "urgent",
            tags     = ["6m", "lightning", "radio"],
        )
        with self._lock:
            self._6m_surge_alerted = now

    # ──────────────────────────────────────────────────────────────
    # Statut (pour /api/ntfy/status)
    # ──────────────────────────────────────────────────────────────
    def get_status(self) -> dict:
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT key, ts, count FROM alerts_sent "
                    "ORDER BY ts DESC LIMIT 20"
                ).fetchall()
            recent = [{"key": r["key"], "ts": r["ts"], "count": r["count"]} for r in rows]
        except Exception:
            recent = []
        return {
            "enabled":         NTFY_ENABLED,
            "url":             NTFY_URL if NTFY_ENABLED else "",
            "cooldown_s":      NTFY_COOLDOWN,
            "presence_window": NTFY_PRESENCE_WINDOW,
            "operator_present": self._operator_present(),
            "surge_threshold": NTFY_6M_SURGE_THRESHOLD,
            "recent_alerts":   recent,
        }
