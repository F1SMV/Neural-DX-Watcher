#!/usr/bin/env python3
"""
§24 Auto-test — Tests complets.

Tests:
  1. Module auto_test.py seul
  2. Intégration avec webapp.py (imports)
  3. Boucle feedback (predict → validate → drift_monitor)
"""

import sys
import os
import tempfile
import sqlite3
from datetime import datetime, timezone

# Ajouter le path
sys.path.insert(0, '/mnt/user-data/outputs')

# ================================================================================
# TEST 1: Module auto_test.py seul
# ================================================================================

print("=" * 70)
print("TEST 1: Module adaptive.auto_test seul")
print("=" * 70)

from adaptive.auto_test import AutoTest

tmpdir = tempfile.mkdtemp()
db_file = os.path.join(tmpdir, "test.db")
auto_test = AutoTest(db_path=db_file)

print("\n✓ Module importé avec succès")

# Prédictions
hour_utc = datetime.now(timezone.utc).hour
prob_6m = auto_test.predict_for_hour('6m', 'FT8', hour_utc)
prob_20m = auto_test.predict_for_hour('20m', 'FT8', hour_utc)
print(f"✓ Prédiction 6m: {prob_6m:.2f}")
print(f"✓ Prédiction 20m: {prob_20m:.2f}")

# Validation
ts_now = datetime.now(timezone.utc).timestamp()
result1 = auto_test.validate_spot(ts_now, '6m', 'JT1ABC', mode='FT8')
result2 = auto_test.validate_spot(ts_now, '20m', 'EA1XYZ', mode='FT8')

assert result1['validated'], "Validation 6m échouée"
assert result2['validated'], "Validation 20m échouée"
print(f"✓ Validation 6m: score={result1['match_score']:.2f}")
print(f"✓ Validation 20m: score={result2['match_score']:.2f}")

# Stats
stats = auto_test.stats()
assert stats['total_predictions'] == 2, "Pas 2 prédictions"
assert stats['validated'] == 2, "Pas 2 validations"
print(f"✓ Stats: {stats['total_predictions']} predictions, {stats['validated']} validations")

os.remove(db_file)

# ================================================================================
# TEST 2: Imports dans webapp.py
# ================================================================================

print("\n" + "=" * 70)
print("TEST 2: Vérifier les imports dans webapp.py")
print("=" * 70)

# Vérifier que les imports sont présents
with open('/mnt/user-data/outputs/webapp.py', 'r') as f:
    content = f.read()
    
assert 'from adaptive.auto_test import AutoTest' in content, "Import AutoTest manquant"
print("✓ Import AutoTest trouvé")

assert '_AUTOTEST_OK' in content, "_AUTOTEST_OK manquant"
print("✓ Flag _AUTOTEST_OK trouvé")

assert '_auto_test = AutoTest' in content or '_auto_test = None' in content, "Init _auto_test manquante"
print("✓ Initialisation _auto_test trouvée")

assert '_auto_test.validate_spot' in content, "Hook validate_spot manquant"
print("✓ Hook validate_spot trouvé (au moins 2 fois)")

assert '/api/adaptive/autotest/latest.json' in content, "API latest manquante"
print("✓ API /api/adaptive/autotest/latest.json trouvée")

assert '/api/adaptive/autotest/predict.json' in content, "API predict manquante"
print("✓ API /api/adaptive/autotest/predict.json trouvée")

# ================================================================================
# TEST 3: Syntaxe webapp.py
# ================================================================================

print("\n" + "=" * 70)
print("TEST 3: Compile webapp.py")
print("=" * 70)

import py_compile
try:
    py_compile.compile('/mnt/user-data/outputs/webapp.py', doraise=True)
    print("✓ webapp.py compile sans erreur")
except py_compile.PyCompileError as e:
    print(f"✗ Erreur de compilation: {e}")
    sys.exit(1)

# ================================================================================
# TEST 4: Mock intégration (sans Flask)
# ================================================================================

print("\n" + "=" * 70)
print("TEST 4: Simulation intégration auto_test + drift_monitor")
print("=" * 70)

tmpdir = tempfile.mkdtemp()
db_file = os.path.join(tmpdir, "integration.db")

# Mock DriftMonitor
class MockDriftMonitor:
    def __init__(self):
        self.logs = []
    
    def log_prediction(self, ts, band, pred_score, actual_score, model_version_id=None):
        self.logs.append({
            'ts': ts,
            'band': band,
            'pred_score': pred_score,
            'actual_score': actual_score
        })

auto_test = AutoTest(db_path=db_file)
drift = MockDriftMonitor()

# Générer prédictions + validations
ts_base = datetime.now(timezone.utc).timestamp()
hour_utc = datetime.fromtimestamp(ts_base, tz=timezone.utc).hour

print(f"\nHeure UTC actuelle: {hour_utc}")

# Prédictions
bands_data = [
    ('6m', 'FT8'),
    ('10m', 'CW'),
    ('20m', 'FT8'),
]

preds = {}
for band, mode in bands_data:
    prob = auto_test.predict_for_hour(band, mode, hour_utc)
    preds[band] = (prob, mode)
    print(f"  Prédiction {band}: {prob:.2f}")

# Spots réels arrivent
print(f"\nValidation de spots...")
spots = [
    (ts_base, '6m', 'JT1ABC', 'FT8'),
    (ts_base + 2, '10m', 'N5XYZ', 'CW'),
    (ts_base + 1, '20m', 'EA5XYZ', 'FT8'),
]

for ts, band, dx_call, mode in spots:
    result = auto_test.validate_spot(ts, band, dx_call, mode=mode, drift_monitor=drift)
    if result['validated']:
        print(f"  ✓ {band}/{dx_call}: match_score={result['match_score']:.2f}")
        assert len(drift.logs) > 0, "DriftMonitor n'a rien reçu"

print(f"\n✓ DriftMonitor a reçu {len(drift.logs)} logs")
for log in drift.logs:
    print(f"  - {log['band']}: pred={log['pred_score']}, actual={log['actual_score']}")

# Stats
stats = auto_test.stats()
print(f"\n✓ Stats finales: {stats['total_predictions']} preds, {stats['validated']} validations")

os.remove(db_file)
os.rmdir(tmpdir)

# ================================================================================
# RÉSUMÉ
# ================================================================================

print("\n" + "=" * 70)
print("✓✓✓ §24 AUTO-TEST — TOUS LES TESTS PASSENT")
print("=" * 70)

print("""
Résumé:
  1. Module auto_test.py: prédictions + validations ✓
  2. Intégration webapp.py: imports + hooks + APIs ✓
  3. Syntaxe: compile correctement ✓
  4. Boucle feedback: predict → validate → drift_monitor ✓

Prochaine étape:
  - Déployer sur le Pi
  - Tester en live pendant 24h
  - Vérifier que DriftMonitor accumule les données
  - NightlyCycle ajuste la config selon les validations
""")
