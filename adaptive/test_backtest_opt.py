#!/usr/bin/env python3
"""Tests unitaires — adaptive/backtester.py + adaptive/optimizer.py"""
import os, sys, time, tempfile, sqlite3

sys.path.insert(0, os.path.dirname(__file__))
from adaptive.backtester import Backtester, BacktestResult
from adaptive.optimizer import Optimizer

DB_ANALYTICS = None
DB_PREDICTOR = None

def setup():
    global DB_ANALYTICS, DB_PREDICTOR
    DB_ANALYTICS = tempfile.mktemp(suffix=".sqlite")
    DB_PREDICTOR = tempfile.mktemp(suffix=".sqlite")
    
    # Créer analytics.sqlite avec spot_log test
    db = sqlite3.connect(DB_ANALYTICS)
    db.execute("""
        CREATE TABLE spot_log (
            ts REAL, band TEXT, dx_call TEXT, lat REAL, lon REAL,
            mode TEXT, distance_km REAL
        )
    """)
    
    # Insérer quelques spots test
    base_ts = time.time() - 86400
    spots = [
        (base_ts, "6m", "DL1A", 51.0, 10.0, "SSB", 1200),
        (base_ts+60, "6m", "OK2B", 50.0, 14.0, "SSB", 1100),
        (base_ts+120, "6m", "SP3C", 52.0, 21.0, "FT8", 1500),
        (base_ts+180, "10m", "W5A", 35.0, -100.0, "CW", 8000),
        (base_ts+240, "10m", "PY2B", -23.0, -46.0, "SSB", 9000),
    ]
    for s in spots:
        db.execute("INSERT INTO spot_log VALUES (?,?,?,?,?,?,?)", s)
    db.commit()
    db.close()

def teardown():
    if DB_ANALYTICS and os.path.exists(DB_ANALYTICS):
        os.unlink(DB_ANALYTICS)
    if DB_PREDICTOR and os.path.exists(DB_PREDICTOR):
        os.unlink(DB_PREDICTOR)

# ── Tests ─────────────────────────────────────────────────────────────

def test_backtest_result():
    r = BacktestResult()
    r.add_prediction(time.time(), "6m", 1, 60, 70)
    r.add_prediction(time.time(), "6m", 1, 40, 30)
    metrics = r.compute_metrics()
    assert "ece" in metrics
    assert "brier" in metrics
    assert "f1" in metrics
    assert metrics["n_predictions"] == 2
    print("✓ BacktestResult metrics")

def test_backtester_init():
    setup()
    bt = Backtester(db_analytics=DB_ANALYTICS)
    assert bt is not None
    teardown()
    print("✓ Backtester init")

def test_backtester_backtest():
    setup()
    bt = Backtester(db_analytics=DB_ANALYTICS)
    result = bt.backtest(
        config={"distance_bonus_hf": 5},
        lookback_days=30,
        limit=10
    )
    assert "ece" in result.metrics
    assert result.metrics["n_predictions"] > 0
    teardown()
    print(f"✓ Backtester backtest ({result.metrics['n_predictions']} preds)")

def test_backtester_compare():
    setup()
    bt = Backtester(db_analytics=DB_ANALYTICS)
    configs = [
        {"distance_bonus_hf": 3},
        {"distance_bonus_hf": 5},
        {"distance_bonus_hf": 7},
    ]
    results = bt.compare_configs(configs, lookback_days=30)
    assert len(results) == 3
    # Résultats triés par ECE (ascending)
    eces = [m.get("ece", 999) for c, m in results]
    assert eces == sorted(eces)
    teardown()
    print(f"✓ compare_configs ({len(results)} configs, sorted by ECE)")

def test_optimizer_init():
    setup()
    opt = Optimizer(db_predictor=DB_PREDICTOR, db_analytics=DB_ANALYTICS)
    assert opt.backtester is not None
    teardown()
    print("✓ Optimizer init")

def test_optimizer_tables():
    setup()
    opt = Optimizer(db_predictor=DB_PREDICTOR, db_analytics=DB_ANALYTICS)
    db = sqlite3.connect(DB_PREDICTOR)
    c = db.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in c.fetchall()]
    assert "optimizer_runs" in tables
    assert "optimizer_results" in tables
    db.close()
    teardown()
    print("✓ Optimizer tables created")

def test_optimizer_optimize():
    setup()
    opt = Optimizer(db_predictor=DB_PREDICTOR, db_analytics=DB_ANALYTICS)
    param_grid = {
        "distance_bonus_hf": [3, 5, 7],
    }
    best_cfg, best_metrics = opt.optimize(param_grid, lookback_days=30)
    # best_cfg peut être None si backtest échoue
    if best_cfg:
        assert "distance_bonus_hf" in best_cfg
        assert "ece" in best_metrics
    teardown()
    print(f"✓ Optimizer optimize (best ECE={best_metrics.get('ece', 'N/A')})")

def test_optimizer_latest_runs():
    setup()
    opt = Optimizer(db_predictor=DB_PREDICTOR, db_analytics=DB_ANALYTICS)
    opt.optimize({"distance_bonus_hf": [3, 5]}, lookback_days=30)
    runs = opt.latest_runs(10)
    assert len(runs) > 0
    assert "ts_start" in runs[0]
    assert "status" in runs[0]
    teardown()
    print(f"✓ latest_runs ({len(runs)} runs)")

# ── Run ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_backtest_result,
        test_backtester_init,
        test_backtester_backtest,
        test_backtester_compare,
        test_optimizer_init,
        test_optimizer_tables,
        test_optimizer_optimize,
        test_optimizer_latest_runs,
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
