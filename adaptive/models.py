"""
adaptive/models.py — Adaptive Models & Versioning (CDC v13 §14)

Gère les versions de configurations, leur statut (CANDIDATE/VALIDATED/ACTIVE/DEPRECATED),
et l'application dynamique au scoring live.

Usage :
    from adaptive.models import ModelRegistry
    registry = ModelRegistry(db_path="data/predictor.sqlite")
    
    # Obtenir la config active
    active_cfg = registry.get_active_model()
    
    # Créer une candidate (issu d'un optimizer run)
    registry.create_candidate(
        config={"distance_bonus_hf": 3},
        source_run_id=5,
        metrics={"ece": 0.012, "f1": 0.75}
    )
    
    # Valider et promouvoir (§15)
    result = registry.validate_and_promote(candidate_id=10)
"""

import sqlite3
import logging
import time
import json

logger = logging.getLogger("adaptive.models")

# ── Table SQLite ─────────────────────────────────────────────────────────

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS model_versions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    version_str         TEXT    UNIQUE,
    config              TEXT    NOT NULL,
    status              TEXT    NOT NULL DEFAULT 'CANDIDATE',
    ts_created          REAL    NOT NULL,
    ts_promoted         REAL,
    source_run_id       INTEGER,
    metrics_ece         REAL,
    metrics_f1          REAL,
    metrics_brier       REAL,
    metrics_n_preds     INTEGER,
    notes               TEXT,
    FOREIGN KEY(source_run_id) REFERENCES optimizer_runs(id)
);

CREATE TABLE IF NOT EXISTS model_active (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    current_version_id  INTEGER UNIQUE,
    ts_switched     REAL,
    FOREIGN KEY(current_version_id) REFERENCES model_versions(id)
);
"""

_CREATE_IDX = """
CREATE INDEX IF NOT EXISTS idx_mv_status ON model_versions(status);
CREATE INDEX IF NOT EXISTS idx_mv_ts_created ON model_versions(ts_created DESC);
"""

# ── Status Lifecycle ─────────────────────────────────────────────────────
STATUSES = ("CANDIDATE", "VALIDATED", "ACTIVE", "DEPRECATED", "ROLLBACK")


class ModelRegistry:
    """Gère les versions de modèles et leur cycle de vie."""

    def __init__(self, db_path="data/predictor.sqlite"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        try:
            db = sqlite3.connect(self.db_path)
            db.executescript(_CREATE_TABLE)
            db.executescript(_CREATE_IDX)
            db.commit()
            
            # Créer la ligne model_active si n'existe pas
            db.execute("INSERT OR IGNORE INTO model_active (id) VALUES (1)")
            db.commit()
            db.close()
            
            logger.info("model_versions table ready")
        except Exception as e:
            logger.warning(f"ModelRegistry DB init: {e}")

    def _gen_version_str(self):
        """Génère un version string unique (v_<timestamp_sec>_<counter>)."""
        # Récupérer le dernier ID pour éviter les collisions si créé trop vite
        try:
            db = sqlite3.connect(self.db_path)
            c = db.cursor()
            c.execute("SELECT COUNT(*) FROM model_versions")
            counter = c.fetchone()[0]
            db.close()
        except:
            counter = 0
        return f"v_{int(time.time())}_{counter}"

    def create_candidate(self, config, source_run_id=None, metrics=None):
        """Crée une nouvelle candidate (depuis optimizer run).
        
        Args:
            config: dict de config
            source_run_id: ID de la run d'optimisation
            metrics: dict {"ece": ..., "f1": ..., "brier": ..., "n_predictions": ...}
        
        Returns:
            version_id si succès, None sinon.
        """
        metrics = metrics or {}
        version_str = self._gen_version_str()
        
        try:
            db = sqlite3.connect(self.db_path)
            c = db.cursor()
            c.execute("""
                INSERT INTO model_versions
                (version_str, config, status, ts_created, source_run_id,
                 metrics_ece, metrics_f1, metrics_brier, metrics_n_preds)
                VALUES (?, ?, 'CANDIDATE', ?, ?, ?, ?, ?, ?)
            """, (
                version_str, json.dumps(config), time.time(), source_run_id,
                metrics.get("ece"), metrics.get("f1"), metrics.get("brier"),
                metrics.get("n_predictions"),
            ))
            db.commit()
            version_id = c.lastrowid
            db.close()
            
            logger.info(f"[MODEL] Candidate created: v{version_id} "
                       f"(ece={metrics.get('ece')}, f1={metrics.get('f1')})")
            return version_id
            
        except Exception as e:
            logger.warning(f"create_candidate: {e}")
            return None

    def get_active_model(self):
        """Retourne la config ACTIVE actuellement.
        
        Returns:
            {"version_id": ..., "config": {...}, "metrics": {...}} ou None
        """
        try:
            db = sqlite3.connect(self.db_path)
            db.row_factory = sqlite3.Row
            
            row = db.execute("""
                SELECT mv.id, mv.version_str, mv.config, 
                       mv.metrics_ece, mv.metrics_f1, mv.metrics_brier, mv.metrics_n_preds
                FROM model_versions mv
                JOIN model_active ma ON ma.current_version_id = mv.id
                WHERE mv.status = 'ACTIVE'
            """).fetchone()
            
            db.close()
            
            if row:
                return {
                    "version_id": row["id"],
                    "version_str": row["version_str"],
                    "config": json.loads(row["config"]),
                    "metrics": {
                        "ece": row["metrics_ece"],
                        "f1": row["metrics_f1"],
                        "brier": row["metrics_brier"],
                        "n_predictions": row["metrics_n_preds"],
                    }
                }
            return None
            
        except Exception as e:
            logger.warning(f"get_active_model: {e}")
            return None

    def get_candidate(self, candidate_id):
        """Récupère les détails d'une candidate."""
        try:
            db = sqlite3.connect(self.db_path)
            db.row_factory = sqlite3.Row
            
            row = db.execute("""
                SELECT * FROM model_versions WHERE id = ? AND status = 'CANDIDATE'
            """, (candidate_id,)).fetchone()
            
            db.close()
            
            if row:
                return dict(row)
            return None
            
        except Exception as e:
            logger.warning(f"get_candidate: {e}")
            return None

    def list_candidates(self, limit=10):
        """Liste les candidates non validées."""
        try:
            db = sqlite3.connect(self.db_path)
            db.row_factory = sqlite3.Row
            
            rows = db.execute("""
                SELECT * FROM model_versions 
                WHERE status = 'CANDIDATE'
                ORDER BY ts_created DESC
                LIMIT ?
            """, (limit,)).fetchall()
            
            db.close()
            return [dict(r) for r in rows]
            
        except Exception as e:
            logger.warning(f"list_candidates: {e}")
            return []

    def list_versions(self, limit=20):
        """Liste toutes les versions."""
        try:
            db = sqlite3.connect(self.db_path)
            db.row_factory = sqlite3.Row
            
            rows = db.execute("""
                SELECT id, version_str, status, ts_created, ts_promoted,
                       metrics_ece, metrics_f1, metrics_brier
                FROM model_versions
                ORDER BY ts_created DESC
                LIMIT ?
            """, (limit,)).fetchall()
            
            db.close()
            return [dict(r) for r in rows]
            
        except Exception as e:
            logger.warning(f"list_versions: {e}")
            return []

    def _set_active(self, version_id):
        """Change le modèle ACTIVE."""
        try:
            db = sqlite3.connect(self.db_path)
            c = db.cursor()
            
            # Marquer ancien ACTIVE → DEPRECATED
            c.execute("""
                UPDATE model_versions SET status = 'DEPRECATED'
                WHERE status = 'ACTIVE'
            """)
            
            # Nouveau ACTIVE
            c.execute("""
                UPDATE model_versions SET status = 'ACTIVE', ts_promoted = ?
                WHERE id = ?
            """, (time.time(), version_id))
            
            # Mettre à jour model_active
            c.execute("""
                UPDATE model_active SET current_version_id = ?, ts_switched = ?
                WHERE id = 1
            """, (version_id, time.time()))
            
            db.commit()
            db.close()
            
            logger.info(f"[MODEL] Version {version_id} is now ACTIVE")
            return True
            
        except Exception as e:
            logger.warning(f"_set_active: {e}")
            return False

    def stats(self):
        """Statistiques globales."""
        try:
            db = sqlite3.connect(self.db_path)
            c = db.cursor()
            
            c.execute("SELECT COUNT(*) FROM model_versions WHERE status = 'CANDIDATE'")
            n_candidates = c.fetchone()[0]
            
            c.execute("SELECT COUNT(*) FROM model_versions WHERE status = 'ACTIVE'")
            n_active = c.fetchone()[0]
            
            c.execute("SELECT COUNT(*) FROM model_versions")
            n_total = c.fetchone()[0]
            
            db.close()
            
            return {
                "total_versions": n_total,
                "n_candidates": n_candidates,
                "n_active": n_active,
            }
            
        except Exception as e:
            logger.warning(f"stats: {e}")
            return {}
