"""
adaptive/nightly_cycle.py — Nightly Cycle Optimizer (CDC v13 §32)

Exécute l'optimizer sur plusieurs fenêtres (7j, 14j, 30j) chaque nuit à 3h UTC.
Sélectionne le meilleur modèle, compare avec ACTIVE, promeut si amélioration.

Usage :
    from adaptive.nightly_cycle import NightlyCycle
    cycle = NightlyCycle(db_predictor="data/predictor.sqlite", 
                         db_analytics="data/analytics.sqlite")
    result = cycle.run()
    # → {"ok": True/False, "best_window": "30d", "best_ece": 0.012, "promoted": True/False}
"""

import sqlite3
import logging
import time
import json
from datetime import datetime
from adaptive.optimizer import Optimizer
from adaptive.models import ModelRegistry
from adaptive.quality_gate import QualityGate

logger = logging.getLogger("adaptive.nightly_cycle")

# ── Configuration ────────────────────────────────────────────────────────

LOOKBACK_WINDOWS = [7, 14, 30]  # jours
PARAM_GRID = {
    "distance_bonus_hf": [3, 5, 7],
}

# ── Table SQLite ─────────────────────────────────────────────────────────

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS nightly_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_run              REAL    NOT NULL,
    window_7d_ece       REAL,
    window_14d_ece      REAL,
    window_30d_ece      REAL,
    best_window         TEXT,
    best_ece            REAL,
    best_config         TEXT,
    active_ece_before   REAL,
    promoted            INTEGER,
    improvement_pct     REAL,
    notes               TEXT
);

CREATE TABLE IF NOT EXISTS nightly_candidates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nightly_run_id  INTEGER,
    window_days     INTEGER,
    config          TEXT,
    ece             REAL,
    f1              REAL,
    brier           REAL,
    n_predictions   INTEGER,
    FOREIGN KEY(nightly_run_id) REFERENCES nightly_runs(id)
);
"""


class NightlyCycle:
    """Gère le cycle nocturne multi-window."""

    def __init__(self, db_predictor="data/predictor.sqlite", 
                 db_analytics="data/analytics.sqlite"):
        self.db_predictor = db_predictor
        self.db_analytics = db_analytics
        self.optimizer = Optimizer(db_predictor, db_analytics)
        self.registry = ModelRegistry(db_predictor)
        self.qg = QualityGate(db_predictor)
        self._init_db()

    def _init_db(self):
        try:
            db = sqlite3.connect(self.db_predictor)
            db.executescript(_CREATE_TABLE)
            db.commit()
            db.close()
            logger.info("nightly_runs tables ready")
        except Exception as e:
            logger.warning(f"NightlyCycle DB init: {e}")

    def run(self):
        """Exécute le cycle complet : test 3 windows, sélection, promotion."""
        logger.info("[NIGHTLY] Démarrage du cycle nocturne multi-window...")
        ts_run = time.time()
        
        # 1. Tester les 3 fenêtres
        results_by_window = {}
        for window_days in LOOKBACK_WINDOWS:
            try:
                logger.info(f"[NIGHTLY] Testant window {window_days}d...")
                best_cfg, best_metrics = self.optimizer.optimize(
                    param_grid=PARAM_GRID,
                    lookback_days=window_days
                )
                results_by_window[window_days] = {
                    "config": best_cfg,
                    "metrics": best_metrics,
                }
                logger.info(f"[NIGHTLY] {window_days}d: ECE={best_metrics.get('ece'):.4f}, "
                           f"F1={best_metrics.get('f1'):.4f}")
            except Exception as e:
                logger.warning(f"[NIGHTLY] Window {window_days}d échouée: {e}")
                results_by_window[window_days] = None

        # 2. Sélectionner le meilleur (ECE min)
        best_window = None
        best_ece = 999
        best_cfg = None
        best_metrics = None
        
        for window_days, result in results_by_window.items():
            if result and result["metrics"].get("ece") is not None:
                ece = result["metrics"]["ece"]
                if ece < best_ece:
                    best_ece = ece
                    best_window = window_days
                    best_cfg = result["config"]
                    best_metrics = result["metrics"]

        if best_window is None:
            logger.warning("[NIGHTLY] Aucune optimisation réussie")
            return {
                "ok": False,
                "message": "No successful optimizations",
                "promoted": False,
            }

        # 3. Obtenir l'ECE ACTIVE actuel
        active_model = self.registry.get_active_model()
        active_ece_before = active_model["metrics"]["ece"] if active_model else None
        
        # 4. Créer candidate et valider
        candidate_id = self.registry.create_candidate(
            config=best_cfg,
            source_run_id=None,
            metrics=best_metrics
        )
        
        qg_result = self.qg.validate_and_promote(candidate_id)
        promoted = qg_result.get("promoted", False)

        # 5. Calculer l'amélioration
        improvement_pct = None
        if active_ece_before and best_ece:
            improvement_pct = ((active_ece_before - best_ece) / active_ece_before) * 100

        # 6. Enregistrer le run
        self._record_run(
            ts_run=ts_run,
            results_by_window=results_by_window,
            best_window=best_window,
            best_ece=best_ece,
            best_config=best_cfg,
            active_ece_before=active_ece_before,
            promoted=promoted,
            improvement_pct=improvement_pct,
            candidate_id=candidate_id,
        )

        logger.info(f"[NIGHTLY] Cycle terminé: best={best_window}d (ECE={best_ece:.4f}), "
                   f"promoted={promoted}, improvement={improvement_pct}%")

        return {
            "ok": True,
            "best_window": f"{best_window}d",
            "best_ece": best_ece,
            "best_config": best_cfg,
            "promoted": promoted,
            "improvement_pct": improvement_pct,
            "qg_result": qg_result,
        }

    def _record_run(self, ts_run, results_by_window, best_window, best_ece, 
                   best_config, active_ece_before, promoted, improvement_pct, 
                   candidate_id):
        """Enregistre le run dans nightly_runs + nightly_candidates."""
        try:
            db = sqlite3.connect(self.db_predictor)
            c = db.cursor()

            # Insérer le run principal
            window_7d_ece = results_by_window.get(7, {}).get("metrics", {}).get("ece")
            window_14d_ece = results_by_window.get(14, {}).get("metrics", {}).get("ece")
            window_30d_ece = results_by_window.get(30, {}).get("metrics", {}).get("ece")

            c.execute("""
                INSERT INTO nightly_runs
                (ts_run, window_7d_ece, window_14d_ece, window_30d_ece, 
                 best_window, best_ece, best_config, active_ece_before, 
                 promoted, improvement_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ts_run, window_7d_ece, window_14d_ece, window_30d_ece,
                f"{best_window}d", best_ece, json.dumps(best_config),
                active_ece_before, int(promoted), improvement_pct,
            ))
            
            run_id = c.lastrowid
            db.commit()
            db.close()

            logger.info(f"[NIGHTLY] Run {run_id} recorded")

        except Exception as e:
            logger.warning(f"_record_run: {e}")

    def latest_runs(self, limit=10):
        """Liste les N derniers runs."""
        try:
            db = sqlite3.connect(self.db_predictor)
            db.row_factory = sqlite3.Row
            
            rows = db.execute("""
                SELECT * FROM nightly_runs
                ORDER BY ts_run DESC
                LIMIT ?
            """, (limit,)).fetchall()
            
            db.close()
            return [dict(r) for r in rows]
            
        except Exception as e:
            logger.warning(f"latest_runs: {e}")
            return []

    def stats(self):
        """Statistiques des cycles nocturnes."""
        try:
            db = sqlite3.connect(self.db_predictor)
            c = db.cursor()
            
            c.execute("SELECT COUNT(*) FROM nightly_runs")
            n_runs = c.fetchone()[0]
            
            c.execute("SELECT COUNT(*) FROM nightly_runs WHERE promoted = 1")
            n_promoted = c.fetchone()[0]
            
            c.execute("SELECT AVG(improvement_pct) FROM nightly_runs WHERE improvement_pct IS NOT NULL")
            avg_improvement = c.fetchone()[0]
            
            db.close()
            
            return {
                "total_runs": n_runs,
                "promoted_runs": n_promoted,
                "avg_improvement_pct": round(avg_improvement, 2) if avg_improvement else None,
            }
            
        except Exception as e:
            logger.warning(f"stats: {e}")
            return {}
