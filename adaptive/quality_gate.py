"""
adaptive/quality_gate.py — Quality Gate & Model Promotion (CDC v13 §15)

Valide les candidates avant promotion à ACTIVE.
Checks : ECE <0.2, F1 >0.60, n_predictions >10k, pas de drift.

Usage :
    from adaptive.quality_gate import QualityGate
    qg = QualityGate(db_path="data/predictor.sqlite")
    
    # Valider une candidate
    result = qg.validate_and_promote(candidate_id=10)
    # → {"ok": True/False, "passed_checks": [...], "failed_checks": [...], "promoted": True/False}
"""

import sqlite3
import logging
import time
from adaptive.models import ModelRegistry

logger = logging.getLogger("adaptive.quality_gate")

# ── Validation Thresholds ────────────────────────────────────────────────

QUALITY_CHECKS = {
    "ece_max":           0.20,   # ECE doit être < 0.20
    "f1_min":            0.60,   # F1 doit être > 0.60
    "n_predictions_min": 10000,  # Au moins 10k predictions
    "drift_tolerance":   0.05,   # Dérive ECE acceptable (+5%)
}


class QualityGate:
    """Valide les candidates avant promotion."""

    def __init__(self, db_path="data/predictor.sqlite"):
        self.db_path = db_path
        self.registry = ModelRegistry(db_path)

    def validate_and_promote(self, candidate_id):
        """Valide une candidate et la promeut si elle passe tous les checks.
        
        Args:
            candidate_id: ID de la candidate à valider
            
        Returns:
            {
                "ok": True/False,
                "candidate_id": ...,
                "passed_checks": [...],
                "failed_checks": [...],
                "promoted": True/False,
                "message": "..."
            }
        """
        candidate = self.registry.get_candidate(candidate_id)
        if not candidate:
            return {
                "ok": False,
                "candidate_id": candidate_id,
                "promoted": False,
                "message": f"Candidate {candidate_id} not found or not CANDIDATE status",
            }

        # Effectuer les checks
        checks_passed = []
        checks_failed = []

        # Check 1: ECE
        if candidate["metrics_ece"] is not None:
            if candidate["metrics_ece"] < QUALITY_CHECKS["ece_max"]:
                checks_passed.append(f"ECE OK ({candidate['metrics_ece']:.4f} < {QUALITY_CHECKS['ece_max']})")
            else:
                checks_failed.append(f"ECE FAIL ({candidate['metrics_ece']:.4f} >= {QUALITY_CHECKS['ece_max']})")
        else:
            checks_failed.append("ECE is NULL")

        # Check 2: F1
        if candidate["metrics_f1"] is not None:
            if candidate["metrics_f1"] > QUALITY_CHECKS["f1_min"]:
                checks_passed.append(f"F1 OK ({candidate['metrics_f1']:.4f} > {QUALITY_CHECKS['f1_min']})")
            else:
                checks_failed.append(f"F1 FAIL ({candidate['metrics_f1']:.4f} <= {QUALITY_CHECKS['f1_min']})")
        else:
            checks_failed.append("F1 is NULL")

        # Check 3: N predictions
        if candidate["metrics_n_preds"] is not None:
            if candidate["metrics_n_preds"] >= QUALITY_CHECKS["n_predictions_min"]:
                checks_passed.append(f"N_preds OK ({candidate['metrics_n_preds']:,} >= {QUALITY_CHECKS['n_predictions_min']:,})")
            else:
                checks_failed.append(f"N_preds FAIL ({candidate['metrics_n_preds']:,} < {QUALITY_CHECKS['n_predictions_min']:,})")
        else:
            checks_failed.append("N_preds is NULL")

        # Check 4: Drift (comparer avec ACTIVE)
        active = self.registry.get_active_model()
        if active and active["metrics"]["ece"] is not None:
            ece_active = active["metrics"]["ece"]
            ece_candidate = candidate["metrics_ece"]
            drift = (ece_candidate - ece_active) / ece_active if ece_active > 0 else 0
            
            if drift < QUALITY_CHECKS["drift_tolerance"]:
                if drift > 0:
                    checks_passed.append(f"Drift OK (+{drift*100:.1f}% < {QUALITY_CHECKS['drift_tolerance']*100:.0f}%)")
                else:
                    checks_passed.append(f"Drift GOOD ({drift*100:.1f}% improvement)")
            else:
                checks_failed.append(f"Drift FAIL (+{drift*100:.1f}% >= {QUALITY_CHECKS['drift_tolerance']*100:.0f}%)")
        else:
            checks_passed.append("Drift check SKIPPED (no active model)")

        # Décision
        promoted = False
        if not checks_failed:
            # Tous les checks passent
            promoted = self.registry._set_active(candidate_id)
            message = f"[QG PASS] All checks passed. Model promoted to ACTIVE." if promoted else "[QG FAIL] Could not promote (DB error)"
        else:
            message = f"[QG REJECT] {len(checks_failed)} check(s) failed"

        logger.info(f"[QG] Candidate {candidate_id}: "
                   f"passed={len(checks_passed)}, failed={len(checks_failed)}, promoted={promoted}")

        return {
            "ok": True,
            "candidate_id": candidate_id,
            "passed_checks": checks_passed,
            "failed_checks": checks_failed,
            "promoted": promoted,
            "message": message,
        }

    def auto_validate_latest(self):
        """Valide automatiquement la dernière candidate (ex. appelé après optimizer).
        
        Returns:
            Result du validate_and_promote ou None si pas de candidate.
        """
        candidates = self.registry.list_candidates(limit=1)
        if not candidates:
            logger.info("[QG] No candidates to validate")
            return None

        latest = candidates[0]
        logger.info(f"[QG] Auto-validating latest candidate: v{latest['id']}")
        return self.validate_and_promote(latest["id"])

    def get_status(self):
        """État global du système de modèles."""
        try:
            active = self.registry.get_active_model()
            stats = self.registry.stats()
            candidates = self.registry.list_candidates(limit=3)
            
            return {
                "ok": True,
                "active_model": active,
                "stats": stats,
                "latest_candidates": candidates,
                "thresholds": QUALITY_CHECKS,
            }
        except Exception as e:
            logger.warning(f"get_status: {e}")
            return {"ok": False, "error": str(e)}
