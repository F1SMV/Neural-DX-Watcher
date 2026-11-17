#!/usr/bin/env python3
"""Tests unitaires — adaptive/auto_test.py (CDC §24, taux mesurés v14)."""
import os
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from adaptive.auto_test import AutoTest


def _tmp(suffix=".sqlite"):
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    os.unlink(path)
    return path


def _analytics(rows):
    """Base analytics jetable avec la table réelle « spots »."""
    path = _tmp()
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE spots (ts REAL NOT NULL, band TEXT NOT NULL, "
               "dx_call TEXT, mode TEXT, country TEXT)")
    db.executemany("INSERT INTO spots VALUES (?,?,?,?,?)", rows)
    db.commit()
    db.close()
    return path


NOW = 1_800_000_000.0                      # instant fixe : les tests ne dépendent pas de l'horloge
MIDNIGHT = (int(NOW) // 86400) * 86400


def _spot(days_ago, hour, band, mode="FT8"):
    """Spot à l'heure UTC `hour`, `days_ago` jours avant le jour de NOW."""
    return (MIDNIGHT - days_ago * 86400 + hour * 3600 + 120, band, "DX1AA", mode, "X")


def _history(days, hour=12, band_days=None, band="6m"):
    """`days` jours d'écoute à `hour` (20m), dont `band_days` jours avec `band`."""
    rows = [_spot(d, hour, "20m") for d in range(1, days + 1)]
    rows += [_spot(d, hour, band, "CW") for d in (band_days or [])]
    return rows


# ── Comportement v13 conservé ────────────────────────────────────────────

def test_statique_sans_base_analytics():
    at = AutoTest(db_path=_tmp())
    assert at.measured_rate("20m", 12) is None
    assert abs(at.predict_for_hour("20m", "FT8", 12) - 0.85 * 1.1) < 1e-9
    assert at.get_recent_predictions()[0]["source"] == "statique"


def test_bande_inconnue():
    at = AutoTest(db_path=_tmp())
    assert at.predict_for_hour("2m", "FT8", 12) == 0.0
    assert at.stats()["total_predictions"] == 0


def test_validation_et_stats():
    at = AutoTest(db_path=_tmp())
    ts = datetime.now(timezone.utc).timestamp()
    hour = datetime.fromtimestamp(ts, tz=timezone.utc).hour
    at.predict_for_hour("6m", "FT8", hour)
    at.predict_for_hour("20m", "FT8", hour)
    assert at.validate_spot(ts, "6m", "JT1ABC")["validated"]
    assert at.validate_spot(ts, "20m", "EA1XYZ")["validated"]
    assert not at.validate_spot(ts, "40m", "EA1XYZ")["validated"]
    st = at.stats()
    assert st["total_predictions"] == 2 and st["validated"] == 2
    assert st["sources"] == {"mesure": 0, "statique": 2}


def test_boucle_drift_monitor():
    class Drift:
        logs = []
        def log_prediction(self, ts, band, pred, actual, model_version_id=None):
            self.logs.append((band, pred, actual))
    at, drift = AutoTest(db_path=_tmp()), Drift()
    ts = datetime.now(timezone.utc).timestamp()
    at.predict_for_hour("10m", "CW", datetime.fromtimestamp(ts, tz=timezone.utc).hour)
    at.validate_spot(ts, "10m", "N5XYZ", mode="CW", drift_monitor=drift)
    assert len(drift.logs) == 1 and drift.logs[0][0] == "10m"


# ── Taux mesurés (v14) ───────────────────────────────────────────────────

def test_taux_mesure():
    """6m entendu 3 jours sur 10 à 12 h UTC → 0,3."""
    at = AutoTest(db_path=_tmp(), db_analytics=_analytics(_history(10, band_days=[1, 4, 9])))
    assert at.measured_rate("6m", 12, now=NOW) == (0.3, 3, 10)
    assert at.measured_rate("20m", 12, now=NOW) == (1.0, 10, 10)


def test_bande_jamais_entendue_vaut_zero():
    at = AutoTest(db_path=_tmp(), db_analytics=_analytics(_history(10)))
    assert at.measured_rate("160m", 12, now=NOW) == (0.0, 0, 10)


def test_repli_sous_7_jours():
    at = AutoTest(db_path=_tmp(), db_analytics=_analytics(_history(6, band_days=[1, 2])))
    assert at.measured_rate("6m", 12, now=NOW) is None


def test_heure_sans_ecoute():
    """Aucun spot à 3 h UTC : pas de taux, la station n'écoutait pas."""
    at = AutoTest(db_path=_tmp(), db_analytics=_analytics(_history(10)))
    assert at.measured_rate("20m", 3, now=NOW) is None


def test_jour_en_cours_et_hors_fenetre_exclus():
    rows = _history(10, band_days=[2])
    rows.append((MIDNIGHT + 12 * 3600 + 60, "6m", "DX", "FT8", "X"))      # aujourd'hui
    rows.append(_spot(45, 12, "6m"))                                        # hors des 30 jours
    at = AutoTest(db_path=_tmp(), db_analytics=_analytics(rows))
    assert at.measured_rate("6m", 12, now=NOW) == (0.1, 1, 10)


def test_plusieurs_spots_meme_jour_comptent_une_fois():
    rows = _history(10) + [_spot(3, 12, "6m")] * 50
    at = AutoTest(db_path=_tmp(), db_analytics=_analytics(rows))
    assert at.measured_rate("6m", 12, now=NOW) == (0.1, 1, 10)


def test_base_analytics_absente_ou_cassee():
    at = AutoTest(db_path=_tmp(), db_analytics="/nonexistent/x.sqlite")
    assert at.measured_rate("20m", 12, now=NOW) is None
    broken = _tmp()
    sqlite3.connect(broken).execute("CREATE TABLE autre (x)").connection.close()
    at = AutoTest(db_path=_tmp(), db_analytics=broken)
    assert at.measured_rate("20m", 12, now=NOW) is None
    assert at.predict_for_hour("20m", "FT8", 12) > 0          # repli sur la table fixe


def test_cache_des_taux():
    path = _analytics(_history(10))
    at = AutoTest(db_path=_tmp(), db_analytics=path)
    assert at.measured_rate("6m", 12, now=NOW) == (0.0, 0, 10)
    db = sqlite3.connect(path)
    db.execute("INSERT INTO spots VALUES (?,?,?,?,?)", _spot(2, 12, "6m"))
    db.commit(); db.close()
    assert at.measured_rate("6m", 12, now=NOW + 60)[1] == 0                       # cache
    assert at.measured_rate("6m", 12, now=NOW + AutoTest.RATE_CACHE_SEC + 1)[1] == 1


def test_prediction_mesuree_enregistree():
    """La prédiction porte le taux mesuré et sa source, sans bonus de mode."""
    now = time.time()
    midnight = (int(now) // 86400) * 86400
    rows = []
    for d in range(1, 11):
        rows.append((midnight - d * 86400 + 12 * 3600 + 60, "20m", "DX", "FT8", "X"))
        if d <= 4:
            rows.append((midnight - d * 86400 + 12 * 3600 + 90, "6m", "DX", "SSB", "X"))
    at = AutoTest(db_path=_tmp(), db_analytics=_analytics(rows))
    assert at.predict_for_hour("6m", "FT8", 12) == 0.4
    assert at.predict_for_hour("20m", "FT8", 3) > 0           # 3 h : pas d'écoute → table fixe
    recent = {p["band"]: p for p in at.get_recent_predictions()}
    assert recent["6m"]["source"] == "mesure"
    assert recent["6m"]["source_detail"] == "mesure 4/10 j"
    assert recent["20m"]["source"] == "statique"
    assert at.stats()["sources"] == {"mesure": 1, "statique": 1}


def test_base_predictor_v13_existante():
    """Une table créée par la v13 (lignes sans notes) reste lisible."""
    path = _tmp()
    AutoTest(db_path=path)
    db = sqlite3.connect(path)
    db.execute("INSERT INTO auto_test_predictions (ts_created, band, mode, hour_utc, "
               "pred_probability) VALUES (?,?,?,?,?)", (time.time(), "20m", "FT8", 12, 0.5))
    db.commit(); db.close()
    at = AutoTest(db_path=path)
    assert at.get_recent_predictions()[0]["source"] == "statique"
    assert at.stats()["sources"] == {"mesure": 0, "statique": 1}


# ── Intégration webapp.py ────────────────────────────────────────────────

def test_webapp_cable_la_base_analytics():
    with open(os.path.join(ROOT, "webapp.py"), encoding="utf-8") as f:
        src = f.read()
    assert "from adaptive.auto_test import AutoTest" in src
    assert src.count('db_analytics="data/analytics.sqlite")') >= 2
    assert 'AutoTest(db_path="data/predictor.sqlite")' not in src
    assert "/api/adaptive/autotest/latest.json" in src


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t(); print(f"✓ {t.__name__}")
        except Exception as e:
            failed += 1; print(f"✗ {t.__name__}: {e!r}")
    print(f"\nRésultat : {len(tests) - failed} passed, {failed} failed / {len(tests)} tests")
    sys.exit(1 if failed else 0)
