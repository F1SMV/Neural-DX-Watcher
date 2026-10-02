#!/usr/bin/env python3
"""
§24 Auto-test — Valider prédictions live vs spots réels.

Prédit l'arrivée de spots (bande, heure, saison) et compare vs spots réels.
Alimente DriftMonitor pour détection de dégradation du modèle.

Tables SQLite dans predictor.sqlite:
  - auto_test_predictions: ts_created, band, mode, hour_utc, pred_probability, 
                          validation_ts, actual_call, match_score, model_version_id
"""

import sqlite3
import json
import math
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List

class AutoTest:
    """Générateur de prédictions live + validateur."""
    
    # Bandes radio principales
    BANDS = ['6m', '10m', '12m', '15m', '17m', '20m', '30m', '40m', '80m', '160m']
    MODES = ['FT8', 'CW', 'SSB']
    
    # Patterns d'activité par bande et heure (UTC)
    # Format: {band: {hour: activity_base_score (0-100)}}
    BAND_ACTIVITY_PATTERNS = {
        '6m': {0: 10, 6: 15, 12: 60, 18: 80, 23: 20},  # sporadic-E midi-soirée
        '10m': {0: 20, 6: 40, 12: 70, 18: 60, 23: 30},
        '12m': {0: 25, 6: 45, 12: 75, 18: 65, 23: 35},
        '15m': {0: 30, 6: 50, 12: 80, 18: 70, 23: 40},
        '17m': {0: 28, 6: 48, 12: 78, 18: 68, 23: 38},
        '20m': {0: 40, 6: 60, 12: 85, 18: 80, 23: 50},
        '30m': {0: 35, 6: 55, 12: 80, 18: 75, 23: 45},
        '40m': {0: 50, 6: 70, 12: 60, 18: 80, 23: 70},
        '80m': {0: 70, 6: 80, 12: 40, 18: 75, 23: 85},
        '160m': {0: 75, 6: 85, 12: 35, 18: 70, 23: 80},
    }
    
    def __init__(self, db_path: str = "data/predictor.sqlite"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Créer table auto_test_predictions si inexistante."""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS auto_test_predictions (
                    id INTEGER PRIMARY KEY,
                    ts_created REAL NOT NULL,
                    band TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    hour_utc INTEGER NOT NULL,
                    pred_probability REAL NOT NULL,
                    validation_ts REAL,
                    actual_call TEXT,
                    match_score REAL,
                    model_version_id INTEGER,
                    notes TEXT
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_pred_validation ON auto_test_predictions(band, hour_utc, validation_ts)")
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[WARN] AutoTest._init_db: {e}")
    
    def predict_for_hour(self, band: str, mode: str, hour_utc: int, model_version_id: Optional[int] = None) -> float:
        """
        Prédire la probabilité d'activité pour une bande à une heure donnée.
        
        Returns: probabilité 0-1
        """
        if band not in self.BANDS:
            return 0.0
        
        # Pattern de base
        pattern = self.BAND_ACTIVITY_PATTERNS.get(band, {})
        
        # Interpolation linéaire entre heures
        h_floor = (hour_utc // 6) * 6  # Round to nearest 6h
        h_ceil = (h_floor + 6) % 24
        
        base_floor = pattern.get(h_floor, 50) / 100.0
        base_ceil = pattern.get(h_ceil, 50) / 100.0
        
        # Interpolation simple
        frac = (hour_utc % 6) / 6.0
        pred_prob = base_floor * (1 - frac) + base_ceil * frac
        
        # Mode bonus (FT8 plus actif)
        if mode == 'FT8':
            pred_prob *= 1.1
        elif mode == 'SSB':
            pred_prob *= 0.9
        
        # Clamp [0, 1]
        pred_prob = max(0.0, min(1.0, pred_prob))
        
        # Créer la prédiction
        ts = datetime.now(timezone.utc).timestamp()
        self._record_prediction(ts, band, mode, hour_utc, pred_prob, model_version_id)
        
        return pred_prob
    
    def _record_prediction(self, ts: float, band: str, mode: str, hour_utc: int, 
                          prob: float, model_version_id: Optional[int] = None):
        """Enregistrer la prédiction en DB."""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("""
                INSERT INTO auto_test_predictions 
                (ts_created, band, mode, hour_utc, pred_probability, model_version_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (ts, band, mode, hour_utc, prob, model_version_id))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[WARN] AutoTest._record_prediction: {e}")
    
    def validate_spot(self, ts: float, band: str, dx_call: str, mode: str = 'FT8',
                     drift_monitor=None) -> Dict:
        """
        Valider un spot réel contre les prédictions en attente.
        
        Algorithme:
        1. Trouver prédictions pour cette bande dans les 2 dernières heures (± 1h)
        2. Calculer match_score (1.0 si match exact, décroît avec l'âge)
        3. Enregistrer validation + score
        4. Envoyer au DriftMonitor
        
        Returns: {"pred_id": int, "match_score": float, "validated": bool}
        """
        hour_utc = datetime.fromtimestamp(ts, tz=timezone.utc).hour
        
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            # Trouver prédiction non-validée pour cette bande dans ±1h (window flexible)
            c.execute("""
                SELECT id, pred_probability, ts_created, hour_utc
                FROM auto_test_predictions
                WHERE band = ? AND validation_ts IS NULL
                  AND ABS(hour_utc - ?) <= 1
                ORDER BY ts_created DESC
                LIMIT 1
            """, (band, hour_utc))
            
            row = c.fetchone()
            if not row:
                conn.close()
                return {"pred_id": None, "match_score": 0.0, "validated": False}
            
            pred_id, pred_prob, ts_created, pred_hour = row
            
            # Score de match : basé sur temps écoulé
            age_sec = ts - ts_created
            age_min = age_sec / 60.0
            
            # Score décroît linéairement : 1.0 à t=0, 0.0 à t=60min
            match_score = max(0.0, 1.0 - (age_min / 60.0))
            
            # Bonus si call semble rare/intéressant (heuristique simple)
            call_len = len(dx_call)
            if call_len <= 4:  # Court = probablement intéressant
                match_score *= 1.1
            
            match_score = min(1.0, match_score)
            
            # Enregistrer validation
            c.execute("""
                UPDATE auto_test_predictions
                SET validation_ts = ?, actual_call = ?, match_score = ?
                WHERE id = ?
            """, (ts, dx_call, match_score, pred_id))
            
            conn.commit()
            conn.close()
            
            # Envoyer au DriftMonitor si disponible
            if drift_monitor:
                try:
                    pred_score = int(pred_prob * 100)
                    actual_score = int(match_score * 100)
                    drift_monitor.log_prediction(ts, band, pred_score, actual_score, model_version_id=None)
                except Exception as e:
                    print(f"[WARN] AutoTest.validate_spot → drift_monitor: {e}")
            
            return {
                "pred_id": pred_id,
                "match_score": match_score,
                "validated": True,
                "pred_prob": pred_prob,
                "dx_call": dx_call
            }
        
        except Exception as e:
            print(f"[WARN] AutoTest.validate_spot: {e}")
            return {"pred_id": None, "match_score": 0.0, "validated": False}
    
    def get_recent_predictions(self, limit: int = 50, band: Optional[str] = None) -> List[Dict]:
        """Récupérer les prédictions récentes."""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            query = "SELECT id, ts_created, band, mode, hour_utc, pred_probability, actual_call, match_score FROM auto_test_predictions"
            params = []
            
            if band:
                query += " WHERE band = ?"
                params.append(band)
            
            query += " ORDER BY ts_created DESC LIMIT ?"
            params.append(limit)
            
            c.execute(query, params)
            
            rows = c.fetchall()
            conn.close()
            
            result = []
            for row in rows:
                result.append({
                    "id": row[0],
                    "ts_created": row[1],
                    "band": row[2],
                    "mode": row[3],
                    "hour_utc": row[4],
                    "pred_probability": row[5],
                    "actual_call": row[6],
                    "match_score": row[7]
                })
            
            return result
        
        except Exception as e:
            print(f"[WARN] AutoTest.get_recent_predictions: {e}")
            return []
    
    def stats(self) -> Dict:
        """Statistiques globales."""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            # Total prédictions
            c.execute("SELECT COUNT(*) FROM auto_test_predictions")
            total_preds = c.fetchone()[0]
            
            # Prédictions validées
            c.execute("SELECT COUNT(*) FROM auto_test_predictions WHERE validation_ts IS NOT NULL")
            validated = c.fetchone()[0]
            
            # Score moyen
            c.execute("SELECT AVG(match_score) FROM auto_test_predictions WHERE match_score IS NOT NULL")
            avg_score = c.fetchone()[0] or 0.0
            
            # Par bande
            c.execute("""
                SELECT band, COUNT(*), AVG(match_score)
                FROM auto_test_predictions
                WHERE validation_ts IS NOT NULL
                GROUP BY band
            """)
            
            per_band = {}
            for band, count, avg in c.fetchall():
                per_band[band] = {"count": count, "avg_score": avg or 0.0}
            
            conn.close()
            
            return {
                "total_predictions": total_preds,
                "validated": validated,
                "avg_match_score": avg_score,
                "per_band": per_band
            }
        
        except Exception as e:
            print(f"[WARN] AutoTest.stats: {e}")
            return {}


if __name__ == "__main__":
    # Test unitaire minimal
    import tempfile
    import os
    
    # DB temporaire
    tmpdir = tempfile.mkdtemp()
    db_file = os.path.join(tmpdir, "test.db")
    
    auto_test = AutoTest(db_path=db_file)
    
    # Heure UTC courante pour synchroniser prédiction et validation
    ts_now = datetime.now(timezone.utc).timestamp()
    hour_now = datetime.fromtimestamp(ts_now, tz=timezone.utc).hour
    
    # Test 1: Prédiction
    print(f"TEST 1: Prédiction pour 6m à {hour_now}h UTC")
    prob = auto_test.predict_for_hour('6m', 'FT8', hour_now)
    print(f"  Probabilité: {prob:.2f}")
    assert prob > 0.0, f"Expected >0.0, got {prob}"
    print("  ✓ PASS")
    
    # Test 2: Validation
    print("\nTEST 2: Validation spot vs prédiction")
    result = auto_test.validate_spot(ts_now, '6m', 'JT1ABC', mode='FT8')
    print(f"  Match score: {result['match_score']:.2f}")
    assert result['validated'], f"Validation échouée: {result}"
    print("  ✓ PASS")
    
    # Test 3: Stats
    print("\nTEST 3: Statistiques")
    stats = auto_test.stats()
    print(f"  Total prédictions: {stats['total_predictions']}")
    print(f"  Validées: {stats['validated']}")
    print(f"  Score moyen: {stats['avg_match_score']:.2f}")
    assert stats['total_predictions'] >= 1, "Pas de prédiction enregistrée"
    print("  ✓ PASS")
    
    # Cleanup
    os.remove(db_file)
    os.rmdir(tmpdir)
    
    print("\n✓✓✓ §24 Auto-test — Tous les tests passent")
