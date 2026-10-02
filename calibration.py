"""
calibration.py — Neural DX Watcher v13.0 — Adaptive Insight Engine (Phase 1 OODA)
================================================================================

Chaînon manquant de la boucle OODA : le prédicteur (predictor.py) MESURE déjà
sa fiabilité (verify_predictions → prediction_log) mais n'AGIT jamais dessus.
Ce module ferme la boucle : il lit les prédictions déjà vérifiées et construit
une COURBE DE CALIBRATION qui transforme un score brut en probabilité réelle.

Principe (spec v13 §11, §19) : un score prédit de 0.70 ne veut PAS dire "70 % de
chances". Il faut le comparer à la fréquence réelle observée. Si, sur toutes les
prédictions dont le score tombait dans [0.6, 0.8], seules 6 % se sont réalisées,
alors la probabilité calibrée de ce bucket est 6 %, pas 70 %.

Ce module NE modifie AUCUNE table, NE duplique PAS verify_predictions(), NE
réécrit AUCUN code. Il lit prediction_log en seule lecture et retourne des
structures Python. C'est un OBSERVATEUR de la boucle, pas un second moteur.

Statuts scientifiques (spec v13 §23) : tout ce qui sort d'ici est ADAPTIVE
(dérivé de l'historique local mesuré), jamais présenté comme OBSERVED.

API publique :
    from calibration import Calibrator
    cal = Calibrator(db_path="data/predictor.sqlite")
    cal.calibration_curve(model="hf")      -> liste de buckets {score, observed, n}
    cal.calibrate(raw_score=0.72, model="hf") -> probabilité calibrée 0..1
    cal.brier_score(model="hf")            -> Brier score + décomposition
    cal.summary(days=90)                   -> dict complet pour l'API frontend

Aucune dépendance externe. Lecture SQLite seule.
"""

import sqlite3
import math
import time
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Bornes des buckets de score (10 tranches de 0.1). Un score prédit tombe dans
# le bucket [b, b+0.1[ ; on compare la fréquence réelle de réalisation à
# l'intervalle. 10 buckets = compromis entre finesse et volume par bucket.
_BUCKET_EDGES = [i / 10.0 for i in range(11)]  # 0.0, 0.1, … 1.0

# Nombre minimal d'observations pour qu'un bucket soit jugé fiable. En-dessous,
# le taux observé est trop bruité pour calibrer — on le marque low_sample.
MIN_BUCKET_SAMPLES = 8

# Lissage de Laplace (pseudo-comptes) : évite qu'un bucket avec 0 réalisation
# sur 3 essais donne une probabilité calibrée de 0 % (trop confiant). On ajoute
# α succès et α échecs virtuels. Faible pour ne pas trop tirer vers 50 %.
_LAPLACE_ALPHA = 1.0

MODELS = ("es", "hf", "tropo")


class Calibrator:
    """Lit prediction_log (rempli par predictor.verify_predictions) et en dérive
    des probabilités calibrées + le Brier score. Lecture seule, thread-safe."""

    def __init__(self, db_path: str = "data/predictor.sqlite"):
        self.db_path = Path(db_path)
        # Cache des courbes (coûteux à recalculer) — TTL court, la boucle
        # nocturne ou le frontend le rafraîchit.
        self._cache: dict = {}
        self._cache_ts: float = 0.0
        self._cache_ttl: float = 1800  # 30 min

    def _conn(self) -> Optional[sqlite3.Connection]:
        """Connexion lecture seule. Retourne None si la base n'existe pas encore
        (prédicteur jamais lancé) — dégradation propre, jamais de crash."""
        if not self.db_path.exists():
            return None
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=10)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as e:
            logger.debug(f"Calibrator._conn: {e}")
            return None

    def _fetch_verified(self, model: Optional[str], days: int) -> list:
        """Retourne les prédictions vérifiées : liste de (predicted_score, realized).
        model=None → tous modèles confondus."""
        conn = self._conn()
        if conn is None:
            return []
        cutoff = time.time() - days * 86400
        try:
            if model:
                rows = conn.execute(
                    "SELECT predicted_score, realized FROM prediction_log "
                    "WHERE verified=1 AND created_ts > ? AND model=? "
                    "AND predicted_score IS NOT NULL AND realized IS NOT NULL",
                    (cutoff, model)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT predicted_score, realized FROM prediction_log "
                    "WHERE verified=1 AND created_ts > ? "
                    "AND predicted_score IS NOT NULL AND realized IS NOT NULL",
                    (cutoff,)
                ).fetchall()
            return [(float(r["predicted_score"]), int(r["realized"])) for r in rows]
        except sqlite3.Error as e:
            logger.debug(f"Calibrator._fetch_verified: {e}")
            return []
        finally:
            conn.close()

    # ──────────────────────────────────────────────────────────────
    # Courbe de calibration (spec v13 §11)
    # ──────────────────────────────────────────────────────────────
    def calibration_curve(self, model: Optional[str] = None, days: int = 90) -> list:
        """
        Construit la courbe de calibration : pour chaque bucket de score, le taux
        réel de réalisation. Retourne une liste de dicts triés par score :
            [{"score_lo": 0.6, "score_hi": 0.7, "predicted_mid": 0.65,
              "observed": 0.06, "n": 340, "low_sample": False}, ...]
        Un modèle bien calibré a observed ≈ predicted_mid sur chaque bucket.
        """
        data = self._fetch_verified(model, days)
        buckets = []
        for i in range(len(_BUCKET_EDGES) - 1):
            lo, hi = _BUCKET_EDGES[i], _BUCKET_EDGES[i + 1]
            # Dernier bucket inclut 1.0
            in_bucket = [(s, r) for s, r in data
                         if lo <= s < hi or (hi == 1.0 and s == 1.0)]
            n = len(in_bucket)
            if n == 0:
                continue
            hits = sum(r for _, r in in_bucket)
            observed = hits / n
            buckets.append({
                "score_lo": round(lo, 2),
                "score_hi": round(hi, 2),
                "predicted_mid": round((lo + hi) / 2, 3),
                "observed": round(observed, 4),
                "n": n,
                "low_sample": n < MIN_BUCKET_SAMPLES,
            })
        return buckets

    # ──────────────────────────────────────────────────────────────
    # Calibration d'un score brut → probabilité réelle
    # ──────────────────────────────────────────────────────────────
    def calibrate(self, raw_score: float, model: Optional[str] = None,
                  days: int = 90) -> dict:
        """
        Transforme un score brut en probabilité calibrée, via interpolation sur
        la courbe. Retourne {"calibrated": 0.08, "raw": 0.72, "confidence": "GOOD",
        "n_bucket": 340, "status": "ADAPTIVE"}.

        Si l'historique est insuffisant pour ce modèle, retourne le score brut
        inchangé avec status="PREDICTED" (pas encore de calibration locale) —
        cold start honnête (spec v13 §27).
        """
        raw = max(0.0, min(1.0, float(raw_score)))
        curve = self.calibration_curve(model, days)

        # Pas assez de données du tout → renvoyer le brut, non calibré
        total_n = sum(b["n"] for b in curve)
        if total_n < MIN_BUCKET_SAMPLES:
            return {"calibrated": round(raw, 4), "raw": round(raw, 4),
                    "confidence": "LOW", "n_bucket": total_n,
                    "status": "PREDICTED"}  # pas encore ADAPTIVE

        # Trouver le bucket contenant raw
        target = None
        for b in curve:
            if b["score_lo"] <= raw < b["score_hi"] or (b["score_hi"] == 1.0 and raw == 1.0):
                target = b
                break

        if target and not target["low_sample"]:
            # Lissage de Laplace sur le bucket exact
            hits = target["observed"] * target["n"]
            calibrated = (hits + _LAPLACE_ALPHA) / (target["n"] + 2 * _LAPLACE_ALPHA)
            conf = "GOOD" if target["n"] >= 30 else "MEDIUM"
            n_bucket = target["n"]
        else:
            # Bucket vide ou trop peu peuplé → interpolation pondérée par n sur
            # les buckets voisins présents. Évite un trou dur dans la courbe.
            num, den = 0.0, 0.0
            for b in curve:
                if b["low_sample"]:
                    continue
                w = b["n"] / (1 + abs(b["predicted_mid"] - raw) * 10)
                num += b["observed"] * w
                den += w
            calibrated = num / den if den > 0 else raw
            conf = "LOW"
            n_bucket = target["n"] if target else 0

        return {"calibrated": round(calibrated, 4), "raw": round(raw, 4),
                "confidence": conf, "n_bucket": n_bucket, "status": "ADAPTIVE"}

    # ──────────────────────────────────────────────────────────────
    # Brier score (spec v13 §11) — mesure honnête de la qualité probabiliste
    # ──────────────────────────────────────────────────────────────
    def brier_score(self, model: Optional[str] = None, days: int = 90) -> dict:
        """
        Brier score = moyenne de (score_prédit - réalisé)². Plus bas = meilleur.
        0 = parfait, 0.25 = équivalent à toujours prédire 50 %, >0.25 = pire
        qu'une pièce. Décompose aussi en calibration + raffinement (Murphy).

        Retourne {"brier": 0.06, "n": 1160, "baseline": 0.059, "skill": -0.02,
        "reliability": ..., "interpretation": "..."}.
        baseline = Brier d'un prédicteur qui sortirait toujours le taux de base.
        skill = 1 - brier/baseline (>0 = mieux que la base, <0 = pire).
        """
        data = self._fetch_verified(model, days)
        n = len(data)
        if n == 0:
            return {"brier": None, "n": 0, "baseline": None, "skill": None,
                    "interpretation": "Pas encore de prédictions vérifiées",
                    "status": "UNKNOWN"}

        # Brier score
        brier = sum((s - r) ** 2 for s, r in data) / n

        # Taux de base (fréquence réelle globale) et Brier de référence
        base_rate = sum(r for _, r in data) / n
        baseline = base_rate * (1 - base_rate)  # variance de Bernoulli = Brier du "toujours base_rate"

        skill = round(1 - brier / baseline, 4) if baseline > 1e-9 else None

        # Interprétation lisible
        if brier < 0.10:
            interp = "Excellente qualité probabiliste"
        elif brier < 0.18:
            interp = "Bonne qualité probabiliste"
        elif brier < 0.25:
            interp = "Qualité correcte, calibration perfectible"
        else:
            interp = "Probabilités peu fiables — recalibration nécessaire"

        return {
            "brier": round(brier, 4),
            "n": n,
            "base_rate": round(base_rate, 4),
            "baseline": round(baseline, 4),
            "skill": skill,
            "interpretation": interp,
            "status": "ADAPTIVE",
        }

    # ──────────────────────────────────────────────────────────────
    # Erreur de calibration (Expected Calibration Error, spec v13 §11)
    # ──────────────────────────────────────────────────────────────
    def calibration_error(self, model: Optional[str] = None, days: int = 90) -> Optional[float]:
        """
        ECE — moyenne pondérée de |predicted - observed| sur les buckets peuplés.
        0 = parfaitement calibré. >0.15 = calibration franchement mauvaise.
        None si pas assez de données.
        """
        curve = self.calibration_curve(model, days)
        peupled = [b for b in curve if not b["low_sample"]]
        total_n = sum(b["n"] for b in peupled)
        if total_n == 0:
            return None
        ece = sum(b["n"] * abs(b["predicted_mid"] - b["observed"]) for b in peupled) / total_n
        return round(ece, 4)

    # ──────────────────────────────────────────────────────────────
    # Synthèse pour l'API frontend
    # ──────────────────────────────────────────────────────────────
    def summary(self, days: int = 90, use_cache: bool = True) -> dict:
        """
        Synthèse complète par modèle, prête pour /api/adaptive/calibration.json.
        Résultat mis en cache (recalcul coûteux). Structure :
            {"ok": True, "days": 90, "generated_ts": ...,
             "models": {"hf": {"curve": [...], "brier": {...}, "ece": 0.11,
                               "n": 1160, "reliability_pct": 6}, ...},
             "overall": {...}}
        """
        now = time.time()
        if use_cache and self._cache and (now - self._cache_ts) < self._cache_ttl \
                and self._cache.get("days") == days:
            return self._cache

        conn = self._conn()
        if conn is None:
            return {"ok": False, "reason": "predictor.sqlite absent — prédicteur jamais lancé",
                    "days": days, "models": {}}
        conn.close()

        models_out = {}
        for model in MODELS:
            data = self._fetch_verified(model, days)
            n = len(data)
            hits = sum(r for _, r in data)
            models_out[model] = {
                "curve": self.calibration_curve(model, days),
                "brier": self.brier_score(model, days),
                "ece": self.calibration_error(model, days),
                "n": n,
                "reliability_pct": round(100 * hits / n) if n > 0 else None,
            }

        overall = {
            "brier": self.brier_score(None, days),
            "ece": self.calibration_error(None, days),
        }

        result = {
            "ok": True,
            "days": days,
            "generated_ts": now,
            "models": models_out,
            "overall": overall,
        }
        self._cache = result
        self._cache_ts = now
        result_copy = dict(result)
        result_copy["days"] = days
        return result


if __name__ == "__main__":
    # Test direct sur la base réelle (à lancer sur le Pi)
    import json as _json
    cal = Calibrator("data/predictor.sqlite")
    print(_json.dumps(cal.summary(days=90), indent=2, ensure_ascii=False))
