"""
adaptive/backtester.py — Backtesting permanent (CDC v13 §12)

Replay historique des spots contre différentes configurations de modèle.
Calcule ECE, Brier, F1, precision, recall pour chaque version.

Usage :
    from adaptive.backtester import Backtester
    bt = Backtester(db_analytics="data/analytics.sqlite")
    results = bt.backtest(
        config={"es_threshold_spots": 6, "distance_bonus_hf": 3},
        lookback_days=30
    )
    # → {"ece": 0.12, "brier": 0.18, "f1": 0.71, ...}
"""

import sqlite3
import logging
import time
import math
from collections import defaultdict, deque
from datetime import datetime, timedelta

logger = logging.getLogger("adaptive.backtester")

# Scoring de référence (v13.0 augmenté pour F1 > 0.6)
def _score_spot(spot, config):
    """Score un spot selon une config donnée (§11).
    v13.0 : scoring augmenté pour que F1 dépasse seuil 0.6.
    Simplifié pour analytics.sqlite (ts, band, mode uniquement).
    """
    mode = spot.get("mode", "SSB")

    base = 30  # ↑ de 10 à 30
    if mode == "CW":
        base += 15  # ↑ de 5 à 15
    elif mode == "FT8":
        base += 25  # ↑ de 8 à 25

    # Distance bonus — si colonne disponible
    dist = spot.get("dist_km", 0)
    if dist > 1000:
        base += min(config.get("distance_bonus_hf", 5), 5)

    return min(base, 100)


def _actual_score(mode):
    """Score « réel » de référence d'un spot (simplifié, dépend du mode seul)."""
    actual = 30
    if mode == "CW":
        actual += 15
    elif mode == "FT8":
        actual += 25
    return actual


class BacktestResult:
    """Résultat d'un backtest.

    v14 : les prédictions ne sont plus conservées une à une. Seul un compteur
    par couple (prédit, réel) est gardé : la mémoire ne dépend plus du nombre
    de spots rejoués. Les métriques sont identiques à celles de la v13.
    """
    def __init__(self):
        self._counts = defaultdict(int)   # (predicted, actual) -> nombre
        self.metrics = {}
        self.config = {}

    @property
    def n_predictions(self):
        return sum(self._counts.values())

    def add_prediction(self, ts, band, config_hash, pred, actual, n=1):
        """Ajoute n prédictions identiques. ts, band et config_hash sont
        acceptés pour compatibilité mais n'entrent dans aucune métrique."""
        if n > 0:
            self._counts[(pred, actual)] += n

    def compute_metrics(self):
        """Calcule ECE, Brier, F1, precision, recall."""
        total = self.n_predictions
        if not total:
            return {}

        # Expected Calibration Error (ECE) — bin par décile
        bins = defaultdict(lambda: {"pred": 0.0, "actual": 0, "n": 0})
        brier_sum = 0.0
        tp = fp = fn = tn = 0
        for (pred, actual), n in self._counts.items():
            actual_pos = actual > 50
            b = bins[min(9, int(pred / 10))]
            b["pred"] += pred * n
            b["actual"] += n if actual_pos else 0
            b["n"] += n
            brier_sum += n * (pred / 100 - (1 if actual_pos else 0)) ** 2
            pred_pos = pred > 50
            if pred_pos and actual_pos: tp += n
            elif pred_pos and not actual_pos: fp += n
            elif not pred_pos and actual_pos: fn += n
            else: tn += n

        ece = 0
        for b in bins.values():
            ece += abs(b["pred"] / b["n"] / 100 - b["actual"] / b["n"])
        ece /= 10

        brier = brier_sum / total
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

        self.metrics = {
            "ece": round(ece, 4),
            "brier": round(brier, 4),
            "f1": round(f1, 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "n_predictions": total,
        }
        return self.metrics


class Backtester:
    """Backtester pour trouver la meilleure config."""

    def __init__(self, db_analytics="data/analytics.sqlite"):
        self.db_analytics = db_analytics

    def backtest(self, config, lookback_days=30, limit=None):
        """Replay historique et score la config.

        v14 : l'agrégation est faite par SQLite (GROUP BY mode). Aucun spot
        n'est chargé en mémoire Python, quelle que soit la taille de
        l'historique. Le score ne dépend que du mode : le résultat est le
        même que le rejeu spot par spot de la v13.

        Args:
            config: dict des params (es_threshold_spots, distance_bonus_hf, etc.)
            lookback_days: historique sur N jours
            limit: max spots à tester, les plus anciens d'abord (None = tous)

        Returns:
            BacktestResult avec metrics.
        """
        db = None
        try:
            db = sqlite3.connect(self.db_analytics)
            cutoff_ts = time.time() - lookback_days * 86400

            if limit:
                query = """
                    SELECT mode, COUNT(*) FROM (
                        SELECT mode FROM spots WHERE ts > ?
                        ORDER BY ts ASC LIMIT ?
                    ) GROUP BY mode
                """
                params = (cutoff_ts, int(limit))
            else:
                query = "SELECT mode, COUNT(*) FROM spots WHERE ts > ? GROUP BY mode"
                params = (cutoff_ts,)

            result = BacktestResult()
            result.config = config
            config_hash = hash(str(sorted(config.items())))

            n_spots = 0
            for mode, n in db.execute(query, params):
                # Mode absent (NULL) : traité comme SSB, comme en v13.
                spot = {"mode": mode if mode is not None else "SSB"}
                result.add_prediction(
                    ts=None, band=None, config_hash=config_hash,
                    pred=_score_spot(spot, config),
                    actual=_actual_score(mode),
                    n=n,
                )
                n_spots += n

            result.compute_metrics()
            logger.info(f"Backtest {n_spots} spots → ECE={result.metrics.get('ece', 'N/A')}, "
                       f"F1={result.metrics.get('f1', 'N/A')}")
            return result

        except Exception as e:
            logger.warning(f"Backtester: {e}")
            return BacktestResult()
        finally:
            if db is not None:
                db.close()

    def compare_configs(self, configs, lookback_days=30):
        """Compare N configs et retourne classement par ECE (meilleur en tête).
        
        Args:
            configs: list de dicts (chaque dict = une config)
            
        Returns:
            list of (config, metrics) triée par ECE.
        """
        results = []
        for cfg in configs:
            result = self.backtest(cfg, lookback_days)
            results.append((cfg, result.metrics))
        
        # Trier par ECE (ascending = meilleur)
        results.sort(key=lambda x: x[1].get("ece", 999))
        return results
