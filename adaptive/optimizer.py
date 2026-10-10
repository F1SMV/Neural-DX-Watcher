"""
adaptive/optimizer.py — Adaptive Model Optimizer (CDC v13 §13)

Grid search sur les paramètres de la FSM et scoring.
Teste N configurations, choisit la meilleure par ECE.
Versioning + stockage en SQLite.

Usage :
    from adaptive.optimizer import Optimizer
    opt = Optimizer(db_predictor="data/predictor.sqlite")
    best_cfg, best_score = opt.optimize(
        param_grid={
            "es_threshold_spots": [4, 5, 6, 7],
            "distance_bonus_hf": [3, 5, 7],
        },
        n_jobs=4
    )
"""

import sqlite3
import logging
import time
import json
import itertools
from datetime import datetime
from adaptive.backtester import Backtester

logger = logging.getLogger("adaptive.optimizer")

# ── Table SQLite ─────────────────────────────────────────────────────

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS optimizer_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_start        REAL    NOT NULL,
    ts_end          REAL,
    param_grid      TEXT,
    n_configs       INTEGER,
    best_config     TEXT,
    best_ece        REAL,
    best_f1         REAL,
    best_brier      REAL,
    lookback_days   INTEGER,
    status          TEXT    DEFAULT 'RUNNING',
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS optimizer_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER,
    config          TEXT    NOT NULL,
    ece             REAL,
    brier           REAL,
    f1              REAL,
    precision       REAL,
    recall          REAL,
    n_predictions   INTEGER,
    FOREIGN KEY(run_id) REFERENCES optimizer_runs(id)
);
"""

_CREATE_IDX = "CREATE INDEX IF NOT EXISTS idx_opt_run_ts ON optimizer_runs(ts_start);"


class Optimizer:
    """Optimizer pour trouver les meilleurs paramètres."""

    def __init__(self, db_predictor="data/predictor.sqlite",
                 db_analytics="data/analytics.sqlite"):
        self.db_predictor = db_predictor
        self.db_analytics = db_analytics
        self.backtester = Backtester(db_analytics)
        self._init_db()

    def _init_db(self):
        try:
            db = sqlite3.connect(self.db_predictor)
            db.executescript(_CREATE_TABLE)
            db.execute(_CREATE_IDX)
            db.commit()
            db.close()
            logger.info("optimizer tables ready")
        except Exception as e:
            logger.warning(f"Optimizer DB init: {e}")

    def optimize(self, param_grid, lookback_days=30, n_jobs=1):
        """Grid search sur param_grid.
        
        Args:
            param_grid: dict {param_name: [val1, val2, ...], ...}
            lookback_days: historique à backtester
            n_jobs: nb de jobs parallèles (stub : implémentation séquentielle)
            
        Returns:
            (best_config, best_metrics)
        """
        run_id = self._start_run(param_grid, lookback_days)
        
        try:
            # Générer toutes les combos
            keys = list(param_grid.keys())
            configs = []
            for values in itertools.product(*[param_grid[k] for k in keys]):
                cfg = dict(zip(keys, values))
                configs.append(cfg)
            
            logger.info(f"[OPT] Testing {len(configs)} configurations...")
            
            # Backtester chaque combo
            results = self.backtester.compare_configs(configs, lookback_days)
            
            # Stocker les résultats
            for cfg, metrics in results:
                self._store_result(run_id, cfg, metrics)
            
            # Meilleure config (première = ECE minimal)
            if results:
                best_cfg, best_metrics = results[0]
                self._complete_run(run_id, best_cfg, best_metrics)
                logger.info(f"[OPT] Best config: ECE={best_metrics.get('ece')}, "
                           f"F1={best_metrics.get('f1')}")
                return best_cfg, best_metrics
            
            return None, {}
            
        except Exception as e:
            logger.warning(f"Optimizer.optimize: {e}")
            self._complete_run(run_id, {}, {}, status="FAILED")
            return None, {}

    def _start_run(self, param_grid, lookback_days):
        """Crée une entry optimizer_runs."""
        try:
            db = sqlite3.connect(self.db_predictor)
            c = db.cursor()
            c.execute("""
                INSERT INTO optimizer_runs
                (ts_start, param_grid, lookback_days, status)
                VALUES (?, ?, ?, 'RUNNING')
            """, (time.time(), json.dumps(param_grid), lookback_days))
            db.commit()
            run_id = c.lastrowid
            db.close()
            return run_id
        except Exception as e:
            logger.warning(f"_start_run: {e}")
            return None

    def _store_result(self, run_id, config, metrics):
        """Stocke un résultat de backtest."""
        try:
            db = sqlite3.connect(self.db_predictor)
            db.execute("""
                INSERT INTO optimizer_results
                (run_id, config, ece, brier, f1, precision, recall, n_predictions)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id, json.dumps(config),
                metrics.get("ece"), metrics.get("brier"), metrics.get("f1"),
                metrics.get("precision"), metrics.get("recall"),
                metrics.get("n_predictions"),
            ))
            db.commit()
            db.close()
        except Exception as e:
            logger.debug(f"_store_result: {e}")

    def _complete_run(self, run_id, best_config, best_metrics, status="COMPLETED"):
        """Marque un run comme terminé."""
        if not run_id:
            return
        try:
            db = sqlite3.connect(self.db_predictor)
            db.execute("""
                UPDATE optimizer_runs
                SET ts_end=?, status=?, best_config=?, best_ece=?, best_f1=?, best_brier=?
                WHERE id=?
            """, (
                time.time(), status,
                json.dumps(best_config) if best_config else None,
                best_metrics.get("ece"),
                best_metrics.get("f1"),
                best_metrics.get("brier"),
                run_id,
            ))
            db.commit()
            db.close()
            logger.info(f"[OPT] Run {run_id} completed: ece={best_metrics.get('ece')}, f1={best_metrics.get('f1')}")
        except Exception as e:
            logger.warning(f"_complete_run({run_id}): {e}")
            import traceback
            logger.warning(traceback.format_exc())

    def latest_runs(self, limit=10):
        """Historique des optimisations."""
        try:
            db = sqlite3.connect(self.db_predictor)
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT * FROM optimizer_runs ORDER BY ts_start DESC LIMIT ?",
                (limit,)
            ).fetchall()
            db.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"latest_runs: {e}")
            return []

    def run_results(self, run_id):
        """Détails des résultats d'une run."""
        try:
            db = sqlite3.connect(self.db_predictor)
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT * FROM optimizer_results WHERE run_id=? "
                "ORDER BY ece ASC",
                (run_id,)
            ).fetchall()
            db.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"run_results: {e}")
            return []
