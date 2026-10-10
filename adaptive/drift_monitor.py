"""
adaptive/drift_monitor.py — Model Drift Monitoring (CDC v13 §25)

Tracks active model's ECE over time, detects drift (degradation),
logs alerts, and triggers re-optimization if drift exceeds threshold.

Usage:
    from adaptive.drift_monitor import DriftMonitor
    monitor = DriftMonitor(db_path="data/predictor.sqlite")
    
    # Log a prediction result
    monitor.log_prediction(ts, band, pred_spd, actual_spd)
    
    # Check for drift (call periodically)
    drift_result = monitor.check_drift()
    # → {"ok": True, "drift_detected": True/False, "current_ece": 0.015, ...}
"""

import sqlite3
import logging
import time
import math
from datetime import datetime, timedelta

logger = logging.getLogger("adaptive.drift_monitor")

# ── Configuration ────────────────────────────────────────────────────────

DRIFT_THRESHOLDS = {
    "ece_absolute_max": 0.25,       # Absolute ECE ceiling (fail-safe)
    "ece_relative_increase": 0.20,  # Allow +20% vs model ECE at promotion
    "window_size_hours": 24,        # Sample window for drift detection
    "min_samples": 100,             # Minimum predictions in window
    "alert_threshold": 0.05,        # Alert if drift > 5%
}

# ── Table SQLite ─────────────────────────────────────────────────────────

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS drift_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              REAL    NOT NULL,
    band            TEXT,
    pred_score      REAL,
    actual_score    REAL,
    error           REAL,
    model_version_id INTEGER
);

CREATE TABLE IF NOT EXISTS drift_checks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_check            REAL    NOT NULL,
    model_version_id    INTEGER,
    window_size_hours   INTEGER,
    n_samples           INTEGER,
    current_ece         REAL,
    baseline_ece        REAL,
    drift_pct           REAL,
    drift_detected      INTEGER,
    alert_sent          INTEGER,
    notes               TEXT
);
"""

_CREATE_IDX = """
CREATE INDEX IF NOT EXISTS idx_drift_log_ts ON drift_log(ts DESC);
CREATE INDEX IF NOT EXISTS idx_drift_log_band ON drift_log(band);
CREATE INDEX IF NOT EXISTS idx_drift_checks_ts ON drift_checks(ts_check DESC);
"""


class DriftMonitor:
    """Monitors active model's ECE for drift and degradation."""

    def __init__(self, db_path="data/predictor.sqlite"):
        self.db_path = db_path
        self._init_db()
        self._last_alert_ts = {}  # Throttle alerts per model_version_id

    def _init_db(self):
        try:
            db = sqlite3.connect(self.db_path)
            db.executescript(_CREATE_TABLE)
            db.executescript(_CREATE_IDX)
            db.commit()
            db.close()
            logger.info("drift_log tables ready")
        except Exception as e:
            logger.warning(f"DriftMonitor DB init: {e}")

    def log_prediction(self, ts, band, pred_score, actual_score, model_version_id=None):
        """Log a single prediction for drift tracking.
        
        Args:
            ts: timestamp
            band: band name (e.g., '6m', '15m', '2m')
            pred_score: predicted score (0-100)
            actual_score: actual observed score (0-100)
            model_version_id: optional model version for tracking
        
        Returns:
            True if logged, False on error.
        """
        if pred_score is None or actual_score is None:
            return False
        
        error = abs(pred_score - actual_score)
        
        try:
            db = sqlite3.connect(self.db_path)
            c = db.cursor()
            c.execute("""
                INSERT INTO drift_log (ts, band, pred_score, actual_score, error, model_version_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (ts, band, pred_score, actual_score, error, model_version_id))
            db.commit()
            db.close()
            return True
        except Exception as e:
            logger.warning(f"log_prediction: {e}")
            return False

    def check_drift(self, model_version_id=None, baseline_ece=None):
        """Check for ECE drift in recent predictions.
        
        Args:
            model_version_id: version to check (defaults to ACTIVE)
            baseline_ece: baseline ECE for comparison (from model at promotion)
        
        Returns:
            {
                "ok": True/False,
                "drift_detected": True/False,
                "current_ece": 0.015,
                "baseline_ece": 0.012,
                "drift_pct": 25.0,
                "n_samples": 150,
                "alert_triggered": True/False,
                "message": "..."
            }
        """
        try:
            db = sqlite3.connect(self.db_path)
            db.row_factory = sqlite3.Row
            
            # Get ACTIVE model ECE if not provided
            if baseline_ece is None:
                active_row = db.execute("""
                    SELECT metrics_ece FROM model_versions WHERE status = 'ACTIVE'
                """).fetchone()
                if active_row:
                    baseline_ece = active_row["metrics_ece"]
                else:
                    logger.info("[DRIFT] No ACTIVE model, skipping check")
                    return {"ok": True, "drift_detected": False, "message": "No ACTIVE model"}
            
            # Get predictions from last N hours
            window_hours = DRIFT_THRESHOLDS["window_size_hours"]
            ts_cutoff = time.time() - (window_hours * 3600)
            
            rows = db.execute("""
                SELECT pred_score, actual_score FROM drift_log
                WHERE ts > ?
                ORDER BY ts DESC
            """, (ts_cutoff,)).fetchall()
            
            db.close()
            
            if len(rows) < DRIFT_THRESHOLDS["min_samples"]:
                logger.debug(f"[DRIFT] Insufficient samples ({len(rows)} < {DRIFT_THRESHOLDS['min_samples']})")
                return {
                    "ok": True,
                    "drift_detected": False,
                    "n_samples": len(rows),
                    "message": f"Insufficient samples ({len(rows)})"
                }
            
            # Compute ECE (binned calibration error)
            current_ece = self._compute_ece([dict(r) for r in rows])
            
            # Compute drift
            drift_pct = ((current_ece - baseline_ece) / baseline_ece * 100) if baseline_ece > 0 else 0
            
            # Detect drift
            drift_detected = (
                current_ece > DRIFT_THRESHOLDS["ece_absolute_max"] or
                drift_pct > (DRIFT_THRESHOLDS["ece_relative_increase"] * 100)
            )
            
            # Determine alert
            alert_triggered = False
            if drift_detected and drift_pct > (DRIFT_THRESHOLDS["alert_threshold"] * 100):
                alert_triggered = self._send_alert(model_version_id, current_ece, baseline_ece, drift_pct)
            
            # Record check
            self._record_check(
                model_version_id=model_version_id,
                window_hours=window_hours,
                n_samples=len(rows),
                current_ece=current_ece,
                baseline_ece=baseline_ece,
                drift_pct=drift_pct,
                drift_detected=drift_detected,
                alert_sent=alert_triggered,
            )
            
            return {
                "ok": True,
                "drift_detected": drift_detected,
                "current_ece": round(current_ece, 4),
                "baseline_ece": round(baseline_ece, 4),
                "drift_pct": round(drift_pct, 2),
                "n_samples": len(rows),
                "alert_triggered": alert_triggered,
                "message": f"ECE {current_ece:.4f} (baseline {baseline_ece:.4f}), drift {drift_pct:.1f}%",
            }
            
        except Exception as e:
            logger.warning(f"check_drift: {e}")
            return {"ok": False, "error": str(e)}

    def _compute_ece(self, predictions, n_bins=10):
        """Compute Expected Calibration Error — simplified as mean absolute error.
        
        ECE = mean(abs(pred_score - actual_score)) / 100
        Normalized to 0-1 range (lower is better).
        """
        if not predictions:
            return 0.0
        
        errors = []
        for p in predictions:
            pred = p.get("pred_score", 0)
            actual = p.get("actual_score", 0)
            error = abs(pred - actual) / 100.0  # Normalize to 0-1
            errors.append(error)
        
        ece = sum(errors) / len(errors) if errors else 0.0
        return min(ece, 1.0)  # Cap at 1.0

    def _send_alert(self, model_version_id, current_ece, baseline_ece, drift_pct):
        """Send alert if drift exceeds threshold (throttled)."""
        # Throttle: max 1 alert per model per hour
        throttle_key = (model_version_id or "global")
        last_alert = self._last_alert_ts.get(throttle_key, 0)
        
        if time.time() - last_alert < 3600:  # 1 hour throttle
            return False
        
        msg = (f"[DRIFT ALERT] Model v{model_version_id}: ECE {current_ece:.4f} "
               f"vs baseline {baseline_ece:.4f} (+{drift_pct:.1f}%) — "
               f"consider re-optimize")
        logger.warning(msg)
        self._last_alert_ts[throttle_key] = time.time()
        
        return True

    def _record_check(self, model_version_id, window_hours, n_samples, 
                     current_ece, baseline_ece, drift_pct, drift_detected, alert_sent):
        """Record a drift check result."""
        try:
            db = sqlite3.connect(self.db_path)
            c = db.cursor()
            c.execute("""
                INSERT INTO drift_checks
                (ts_check, model_version_id, window_size_hours, n_samples,
                 current_ece, baseline_ece, drift_pct, drift_detected, alert_sent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                time.time(), model_version_id, window_hours, n_samples,
                current_ece, baseline_ece, drift_pct, int(drift_detected), int(alert_sent),
            ))
            db.commit()
            db.close()
        except Exception as e:
            logger.warning(f"_record_check: {e}")

    def latest_checks(self, limit=10):
        """Get latest drift checks."""
        try:
            db = sqlite3.connect(self.db_path)
            db.row_factory = sqlite3.Row
            
            rows = db.execute("""
                SELECT * FROM drift_checks
                ORDER BY ts_check DESC
                LIMIT ?
            """, (limit,)).fetchall()
            
            db.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"latest_checks: {e}")
            return []

    def stats(self):
        """Drift statistics."""
        try:
            db = sqlite3.connect(self.db_path)
            c = db.cursor()
            
            c.execute("SELECT COUNT(*) FROM drift_log")
            n_predictions = c.fetchone()[0]
            
            c.execute("SELECT COUNT(*) FROM drift_checks WHERE drift_detected = 1")
            n_drift_detected = c.fetchone()[0]
            
            c.execute("SELECT COUNT(*) FROM drift_checks WHERE alert_sent = 1")
            n_alerts = c.fetchone()[0]
            
            c.execute("SELECT AVG(drift_pct) FROM drift_checks WHERE drift_detected = 1")
            avg_drift_pct = c.fetchone()[0]
            
            db.close()
            
            return {
                "total_predictions": n_predictions,
                "drift_detections": n_drift_detected,
                "alerts_sent": n_alerts,
                "avg_drift_pct": round(avg_drift_pct, 2) if avg_drift_pct else None,
            }
        except Exception as e:
            logger.warning(f"stats: {e}")
            return {}
