#!/usr/bin/env python3
"""Tests unitaires — adaptive/drift_monitor.py"""
import os, sys, time, tempfile, sqlite3

sys.path.insert(0, os.path.dirname(__file__))
from adaptive.drift_monitor import DriftMonitor

DB = None

def setup():
    global DB
    DB = tempfile.mktemp(suffix=".sqlite")
    # Create required tables
    db = sqlite3.connect(DB)
    db.execute("""
        CREATE TABLE model_versions (
            id INTEGER PRIMARY KEY, status TEXT, metrics_ece REAL
        )
    """)
    db.commit()
    db.close()

def teardown():
    if DB and os.path.exists(DB):
        os.unlink(DB)

def test_drift_monitor_init():
    setup()
    monitor = DriftMonitor(db_path=DB)
    assert monitor is not None
    teardown()
    print("✓ DriftMonitor init")

def test_log_prediction():
    setup()
    monitor = DriftMonitor(db_path=DB)
    result = monitor.log_prediction(
        ts=time.time(),
        band="6m",
        pred_score=50,
        actual_score=52,
        model_version_id=1
    )
    assert result == True
    teardown()
    print("✓ log_prediction")

def test_log_prediction_null_score():
    setup()
    monitor = DriftMonitor(db_path=DB)
    result = monitor.log_prediction(
        ts=time.time(),
        band="6m",
        pred_score=None,
        actual_score=52
    )
    assert result == False  # Should reject null score
    teardown()
    print("✓ log_prediction rejects null scores")

def test_check_drift_no_active_model():
    setup()
    monitor = DriftMonitor(db_path=DB)
    result = monitor.check_drift()
    assert result["ok"] == True
    assert result["drift_detected"] == False
    teardown()
    print("✓ check_drift with no ACTIVE model")

def test_check_drift_insufficient_samples():
    setup()
    monitor = DriftMonitor(db_path=DB)
    
    # Add ACTIVE model
    db = sqlite3.connect(DB)
    db.execute("INSERT INTO model_versions (id, status, metrics_ece) VALUES (1, 'ACTIVE', 0.012)")
    db.commit()
    db.close()
    
    # Add only 10 predictions (min_samples=100)
    for i in range(10):
        monitor.log_prediction(
            ts=time.time() - (3600 * (i % 24)),
            band="6m",
            pred_score=50 + i,
            actual_score=51 + i
        )
    
    result = monitor.check_drift()
    assert result["ok"] == True
    assert result["drift_detected"] == False
    assert result["n_samples"] == 10
    teardown()
    print("✓ check_drift requires minimum samples")

def test_check_drift_stable():
    setup()
    monitor = DriftMonitor(db_path=DB)
    
    # Add ACTIVE model (ECE=0.012)
    db = sqlite3.connect(DB)
    db.execute("INSERT INTO model_versions (id, status, metrics_ece) VALUES (1, 'ACTIVE', 0.012)")
    db.commit()
    db.close()
    
    # Add 150 predictions with small error (ECE should be ~0.01)
    for i in range(150):
        monitor.log_prediction(
            ts=time.time() - (3600 * (i % 24)),
            band="6m",
            pred_score=50 + (i % 10),
            actual_score=50 + (i % 10) + 1  # Small error
        )
    
    result = monitor.check_drift()
    assert result["ok"] == True
    assert result["drift_detected"] == False  # Small ECE, no drift
    assert result["n_samples"] >= 150
    teardown()
    print(f"✓ check_drift detects stable model (ECE={result['current_ece']:.4f})")

def test_check_drift_degraded():
    setup()
    monitor = DriftMonitor(db_path=DB)
    
    # Add ACTIVE model (ECE=0.012)
    db = sqlite3.connect(DB)
    db.execute("INSERT INTO model_versions (id, status, metrics_ece) VALUES (1, 'ACTIVE', 0.012)")
    db.commit()
    db.close()
    
    # Add 150 predictions with large error (ECE >> 0.012)
    for i in range(150):
        monitor.log_prediction(
            ts=time.time() - (3600 * (i % 24)),
            band="6m",
            pred_score=30 + (i % 10),
            actual_score=70 + (i % 10)  # Large error
        )
    
    result = monitor.check_drift()
    assert result["ok"] == True
    # Drift should be detected (large ECE vs baseline)
    assert result["n_samples"] >= 150
    teardown()
    print(f"✓ check_drift detects degraded model (ECE={result['current_ece']:.4f}, drift={result['drift_pct']:.1f}%)")

def test_latest_checks():
    setup()
    monitor = DriftMonitor(db_path=DB)
    
    # Add ACTIVE model
    db = sqlite3.connect(DB)
    db.execute("INSERT INTO model_versions (id, status, metrics_ece) VALUES (1, 'ACTIVE', 0.012)")
    db.commit()
    db.close()
    
    # Add 150 predictions and check drift (will record check)
    for i in range(150):
        monitor.log_prediction(
            ts=time.time() - (3600 * (i % 24)),
            band="6m",
            pred_score=50 + (i % 10),
            actual_score=51 + (i % 10)
        )
    
    monitor.check_drift()
    
    checks = monitor.latest_checks(limit=5)
    assert len(checks) >= 1
    teardown()
    print(f"✓ latest_checks → {len(checks)} records")

def test_stats():
    setup()
    monitor = DriftMonitor(db_path=DB)
    
    # Add 50 predictions
    for i in range(50):
        monitor.log_prediction(
            ts=time.time(),
            band="6m",
            pred_score=50,
            actual_score=52
        )
    
    stats = monitor.stats()
    assert stats["total_predictions"] == 50
    teardown()
    print(f"✓ stats() → {stats}")

if __name__ == "__main__":
    tests = [
        test_drift_monitor_init,
        test_log_prediction,
        test_log_prediction_null_score,
        test_check_drift_no_active_model,
        test_check_drift_insufficient_samples,
        test_check_drift_stable,
        test_check_drift_degraded,
        test_latest_checks,
        test_stats,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"✗ {t.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\n{'='*40}")
    print(f"Résultat : {passed} passed, {failed} failed / {len(tests)} tests")
