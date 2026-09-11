"""Tests analytics.py v2 — NEURAL DX WATCHER v12.5"""
import json
import os
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timezone, timedelta

import analytics


# ── Fabriques de bases de test ────────────────────────────────────────

def _tmp_path():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        p = f.name
    os.unlink(p)
    return p


def make_db(rows, schema="standard"):
    """Crée une base jetable. Renvoie son chemin."""
    p = _tmp_path()
    conn = sqlite3.connect(p)
    if schema == "standard":
        conn.execute("CREATE TABLE spot_log (ts REAL, band TEXT, dx_call TEXT, mode TEXT)")
        conn.executemany("INSERT INTO spot_log VALUES (?,?,?,?)", rows)
    elif schema == "alt":
        conn.execute("CREATE TABLE spot_log (timestamp REAL, band TEXT, callsign TEXT)")
        conn.executemany("INSERT INTO spot_log VALUES (?,?,?)",
                         [(r[0], r[1], r[2]) for r in rows])
    elif schema == "broken":
        conn.execute("CREATE TABLE spot_log (ts REAL, foo TEXT)")
    conn.commit()
    conn.close()
    return p


def uniform_db(hours, per_hour=20, band="20m", now=None):
    """Base couvrant `hours` heures, activité régulière."""
    if now is None:
        now = time.time()
    rows = []
    for h in range(hours):
        base = now - h * 3600
        for i in range(per_hour):
            rows.append((base - i * 60, band, f"DX{i}", "FT8"))
    return make_db(rows), now


# ── Schéma et dégradation ─────────────────────────────────────────────

class TestSchema(unittest.TestCase):
    def test_db_absente(self):
        r = analytics.compute_heatmap("/nonexistent/nope.sqlite")
        self.assertFalse(r["available"])
        self.assertIn("absente", r["reason"])

    def test_schema_incompatible(self):
        p = make_db([], schema="broken")
        self.assertFalse(analytics.compute_heatmap(p)["available"])
        os.unlink(p)

    def test_schema_alternatif(self):
        """Colonnes timestamp/callsign au lieu de ts/dx_call."""
        now = time.time()
        rows = [(now - i * 3600, "20m", "W1AW") for i in range(1, 100)]
        p = make_db(rows, schema="alt")
        r = analytics.compute_recent(p, now=now)
        self.assertTrue(r["available"], r.get("reason"))
        os.unlink(p)

    def test_table_vide(self):
        p = make_db([])
        self.assertFalse(analytics.compute_recent(p)["available"])
        os.unlink(p)


class TestMaturite(unittest.TestCase):
    """Le module doit annoncer honnêtement ce qu'il peut analyser."""

    def test_paliers(self):
        cases = [(2, "collecting"), (8, "basic"), (24 * 3, "daily"),
                 (24 * 20, "weekly")]
        for hours, expected in cases:
            p, now = uniform_db(hours)
            m = analytics.compute_all(p, now=now)["maturity"]
            self.assertEqual(m["level"], expected,
                             f"{hours}h devrait donner '{expected}', pas '{m['level']}'")
            os.unlink(p)

    def test_palier_suivant_annonce(self):
        p, now = uniform_db(10)
        m = analytics.compute_all(p, now=now)["maturity"]
        self.assertIsNotNone(m["next_level"])
        self.assertGreater(m["hours_remaining"], 0)
        os.unlink(p)

    def test_maturite_max_sans_suite(self):
        p, now = uniform_db(24 * 20, per_hour=2)
        m = analytics.compute_all(p, now=now)["maturity"]
        self.assertEqual(m["level"], "weekly")
        self.assertIsNone(m["next_level"])
        os.unlink(p)


class TestDemarrageAFroid(unittest.TestCase):
    """Cas signalé en production : base de quelques heures seulement."""

    def test_recent_disponible_des_deux_heures(self):
        p, now = uniform_db(2)
        r = analytics.compute_recent(p, now=now)
        self.assertTrue(r["available"], "recent doit fonctionner dès 2h")
        self.assertGreater(r["total"], 0)
        self.assertTrue(any(pt["count"] > 0 for pt in r["series"]))
        os.unlink(p)

    def test_heatmap_refusee_sous_48h(self):
        p, now = uniform_db(24)
        r = analytics.compute_heatmap(p, now=now)
        self.assertFalse(r["available"])
        self.assertIn("court", r["reason"])
        os.unlink(p)

    def test_patterns_refuse_sous_12h(self):
        """Sans période de comparaison, tout paraîtrait en hausse."""
        p, now = uniform_db(4)
        r = analytics.compute_patterns(p, now=now)
        self.assertFalse(r["available"])
        os.unlink(p)

    def test_patterns_actif_a_24h(self):
        p, now = uniform_db(24)
        r = analytics.compute_patterns(p, now=now)
        self.assertTrue(r["available"])
        self.assertTrue(r["bands"])
        os.unlink(p)

    def test_forecast_mode_horaire_si_peu_historique(self):
        p, now = uniform_db(48)
        r = analytics.compute_forecast(p, now=now)
        self.assertTrue(r["available"])
        self.assertEqual(r["basis"], "hour")
        os.unlink(p)


class TestNonRegression(unittest.TestCase):
    """Une analyse activée ne doit jamais se re-désactiver en grandissant."""

    def test_forecast_ne_perd_pas_de_creneaux(self):
        prev = -1
        for hours in (24, 48, 24 * 5, 24 * 10, 24 * 15, 24 * 20, 24 * 25):
            p, now = uniform_db(hours, per_hour=5)
            f = analytics.compute_forecast(p, now=now)
            rated = sum(1 for s in f["slots"] if s["probability"] is not None)
            self.assertGreaterEqual(
                rated, prev,
                f"régression à {hours}h : {prev} créneaux chiffrés puis {rated}")
            prev = rated
            os.unlink(p)

    def test_bascule_weekday_seulement_si_gagnante(self):
        """Passer en mode weekday ne doit pas réduire la couverture."""
        p, now = uniform_db(24 * 16, per_hour=4)
        f = analytics.compute_forecast(p, now=now)
        rated = sum(1 for s in f["slots"] if s["probability"] is not None)
        self.assertEqual(rated, 6, f"couverture incomplète en base '{f['basis']}'")
        os.unlink(p)


# ── Exactitude des calculs ────────────────────────────────────────────

class TestArithmetique(unittest.TestCase):
    def test_equivalence_datetime(self):
        """L'arithmétique modulaire doit égaler datetime, sinon tout décale."""
        import random
        for _ in range(20000):
            ts = random.uniform(0, time.time() + 5 * 365 * 86400)
            slot = int(ts // 3600)
            wd, hr = analytics._slot_weekday_hour(slot)
            dt = datetime.fromtimestamp(slot * 3600, tz=timezone.utc)
            self.assertEqual((wd, hr), (dt.weekday(), dt.hour))


class TestHeatmap(unittest.TestCase):
    def setUp(self):
        # Ancrage déterministe : mercredi 2026-06-10 12:00 UTC
        self.now = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc).timestamp()
        rows = []
        # Bruit de fond sur 28 jours
        for h in range(28 * 24):
            base = self.now - h * 3600
            for i in range(2):
                rows.append((base - i * 60, "20m", "W1AW", "CW"))
        # Pic marqué le mardi 14h UTC
        for w in range(4):
            base = (datetime(2026, 6, 9, 14, 30, tzinfo=timezone.utc)
                    - timedelta(days=7 * w)).timestamp()
            rows += [(base, "6m", f"DX{i}", "FT8") for i in range(20)]
        self.p = make_db(rows)

    def tearDown(self):
        os.unlink(self.p)

    def test_forme_grille(self):
        r = analytics.compute_heatmap(self.p, now=self.now)
        self.assertTrue(r["available"])
        self.assertEqual(len(r["grid"]), 7)
        self.assertTrue(all(len(row) == 24 for row in r["grid"]))

    def test_pic_mardi_14h(self):
        r = analytics.compute_heatmap(self.p, days=30, band="6m", now=self.now)
        self.assertEqual(r["best_slot"]["weekday"], 1, "mardi attendu")
        self.assertEqual(r["best_slot"]["hour"], 14)

    def test_moyenne_et_non_cumul(self):
        """4 mardis x 20 spots => moyenne ~20, jamais 80."""
        r = analytics.compute_heatmap(self.p, days=30, band="6m", now=self.now)
        self.assertLessEqual(r["peak_value"], 21.0)

    def test_filtre_bande(self):
        a = analytics.compute_heatmap(self.p, band="6m", now=self.now)
        b = analytics.compute_heatmap(self.p, band="20m", now=self.now)
        self.assertNotEqual(a["total_spots"], b["total_spots"])

    def test_case_non_observee_est_none(self):
        r = analytics.compute_heatmap(self.p, days=3, band="6m", now=self.now)
        vals = [v for row in r["grid"] for v in row]
        self.assertIn(None, vals, "les cases hors fenêtre doivent être None")


class TestPatterns(unittest.TestCase):
    def setUp(self):
        self.now = time.time()
        rows = []
        rows += [(self.now - 3600 * i, "6m", "DX", "FT8") for i in range(1, 100)]
        rows += [(self.now - 86400 * 7 - 3600 * i, "6m", "DX", "FT8")
                 for i in range(1, 20)]
        rows += [(self.now - 3600 * i * 2, "20m", "W1AW", "CW") for i in range(1, 60)]
        rows += [(self.now - 86400 * 7 - 3600 * i * 2, "20m", "W1AW", "CW")
                 for i in range(1, 60)]
        rows += [(self.now - 3600 * i, "160m", "X", "CW") for i in range(1, 4)]
        self.p = make_db(rows)

    def tearDown(self):
        os.unlink(self.p)

    def test_volume_insuffisant_non_chiffre(self):
        r = analytics.compute_patterns(self.p, window_days=7, now=self.now)
        b = next(x for x in r["bands"] if x["band"] == "160m")
        self.assertEqual(b["trend"], "insufficient")
        self.assertIsNone(b["change_pct"])

    def test_bande_neuve_sans_pourcentage(self):
        """previous=0 ne doit pas produire de division par zéro."""
        now = time.time()
        # 40h d'historique sur 20m pour fixer l'étendue (fenêtre = 20h),
        # et 4m présent uniquement dans les 10 dernières heures : sa
        # fenêtre précédente est donc réellement vide.
        rows = [(now - 3600 * i, "20m", "W1AW", "CW") for i in range(1, 41)]
        for h in range(10):
            rows += [(now - 3600 * h - 60 * j, "4m", "DX", "FT8") for j in range(3)]
        p = make_db(rows)
        r = analytics.compute_patterns(p, now=now)
        b = next(x for x in r["bands"] if x["band"] == "4m")
        self.assertEqual(b["previous_count"], 0, "la bande doit être absente avant")
        self.assertEqual(b["trend"], "up")
        self.assertIsNone(b["change_pct"], "aucun % calculable depuis zéro")
        os.unlink(p)

    def test_tri_par_volume(self):
        r = analytics.compute_patterns(self.p, window_days=7, now=self.now)
        counts = [b["recent_count"] for b in r["bands"]]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_fenetre_adaptative(self):
        """Sans window_days imposé, la fenêtre suit l'historique."""
        p, now = uniform_db(30)
        r = analytics.compute_patterns(p, now=now)
        self.assertTrue(r["available"])
        self.assertLessEqual(r["window_hours"], 24)
        os.unlink(p)


class TestForecast(unittest.TestCase):
    def test_probabilites_bornees(self):
        p, now = uniform_db(24 * 10, per_hour=3)
        r = analytics.compute_forecast(p, now=now)
        for s in r["slots"]:
            if s["probability"] is not None:
                self.assertGreaterEqual(s["probability"], 0)
                self.assertLessEqual(s["probability"], 100)
        os.unlink(p)

    def test_nombre_de_creneaux(self):
        p, now = uniform_db(24 * 5)
        r = analytics.compute_forecast(p, hours_ahead=6, now=now)
        self.assertEqual(len(r["slots"]), 6)
        os.unlink(p)

    def test_creneau_recurrent_detecte(self):
        """Activité systématique => probabilité élevée."""
        p, now = uniform_db(24 * 10, per_hour=6)
        r = analytics.compute_forecast(p, now=now)
        rated = [s for s in r["slots"] if s["probability"] is not None]
        self.assertTrue(rated)
        self.assertGreaterEqual(max(s["probability"] for s in rated), 80)
        os.unlink(p)

    def test_base_annoncee(self):
        p, now = uniform_db(24 * 5)
        r = analytics.compute_forecast(p, now=now)
        self.assertIn(r["basis"], ("hour", "weekday"))
        os.unlink(p)


# ── Forme, robustesse, performance ────────────────────────────────────

class TestFormeStable(unittest.TestCase):
    """Réponse indisponible = même forme que réponse pleine."""

    def test_collections_iterables(self):
        r = analytics.compute_all("/nope/none.sqlite")
        self.assertEqual(len(r["heatmap"]["grid"]), 7)
        self.assertEqual(r["patterns"]["bands"], [])
        self.assertEqual(r["forecast"]["slots"], [])
        self.assertEqual(r["recent"]["series"], [])
        for _ in r["forecast"]["slots"]:
            pass

    def test_cles_identiques(self):
        p, now = uniform_db(24 * 20, per_hour=3)
        for fn in (analytics.compute_recent, analytics.compute_heatmap,
                   analytics.compute_patterns, analytics.compute_forecast):
            full = set(fn(p, now=now).keys())
            void = set(fn("/nope/none.sqlite").keys()) - {"reason"}
            self.assertTrue(void.issubset(full),
                            f"{fn.__name__}: clés divergentes {void - full}")
        os.unlink(p)

    def test_serialisable_json(self):
        p, now = uniform_db(24 * 20, per_hour=3)
        json.dumps(analytics.compute_all(p, now=now))
        json.dumps(analytics.compute_all("/nope/none.sqlite"))
        os.unlink(p)

    def test_maturite_presente_partout(self):
        r = analytics.compute_all("/nope/none.sqlite")
        for k in ("recent", "heatmap", "patterns", "forecast"):
            self.assertIn("maturity", r[k], f"{k} sans maturité")


class TestRobustesse(unittest.TestCase):
    def test_timestamps_aberrants_ignores(self):
        now = time.time()
        rows = [(now - 3600 * i, "20m", "W1AW", "CW") for i in range(1, 20)]
        rows += [(now * 1000, "20m", "BAD", "CW")]     # millisecondes
        rows += [(0, "20m", "OLD", "CW")]               # epoch
        p = make_db(rows)
        r = analytics.compute_recent(p, hours=24, now=now)
        self.assertTrue(r["available"])
        self.assertEqual(r["total"], 19, "les ts aberrants doivent être écartés")
        os.unlink(p)

    def test_band_vide_ignoree(self):
        now = time.time()
        rows = [(now - 3600 * i, "20m", "W", "CW") for i in range(1, 20)]
        rows += [(now - 3600, "", "W", "CW"), (now - 3600, None, "W", "CW")]
        p = make_db(rows)
        r = analytics.compute_recent(p, hours=24, now=now)
        self.assertEqual(r["total"], 19)
        os.unlink(p)

    def test_lecture_seule(self):
        p, now = uniform_db(24 * 3)
        before = os.path.getmtime(p)
        analytics.compute_all(p, now=now)
        self.assertEqual(before, os.path.getmtime(p),
                         "l'analytique ne doit jamais écrire")
        os.unlink(p)

    def test_bande_inexistante(self):
        p, now = uniform_db(24 * 5, band="20m")
        r = analytics.compute_heatmap(p, band="6m", now=now)
        self.assertEqual(r["total_spots"], 0)
        self.assertIsNone(r["best_slot"])
        os.unlink(p)


class TestPerformance(unittest.TestCase):
    """Le Pi 5 est ~3x plus lent : garder une marge confortable."""

    BUDGET_MS = 400

    def test_compute_all_sous_budget(self):
        import random
        now = time.time()
        rows = [(now - random.random() * 30 * 86400,
                 random.choice(["20m", "40m", "6m", "15m"]), "DX", "FT8")
                for _ in range(130000)]
        p = make_db(rows)
        best = min(
            (lambda: (lambda t0: (analytics.compute_all(p, now=now),
                                  (time.perf_counter() - t0) * 1000)[1])(
                time.perf_counter()))()
            for _ in range(3)
        )
        os.unlink(p)
        self.assertLess(best, self.BUDGET_MS,
                        f"compute_all: {best:.0f}ms > budget {self.BUDGET_MS}ms")

    def test_un_seul_acces_base(self):
        """compute_all ne doit pas rouvrir la base pour chaque analyse."""
        p, now = uniform_db(24 * 10, per_hour=3)
        calls = {"n": 0}
        original = analytics._load_aggregated

        def counting(*a, **kw):
            calls["n"] += 1
            return original(*a, **kw)

        analytics._load_aggregated = counting
        try:
            analytics.compute_all(p, now=now)
        finally:
            analytics._load_aggregated = original
        os.unlink(p)
        self.assertEqual(calls["n"], 1,
                         f"{calls['n']} chargements au lieu d'un seul")


class TestCollecteAutonome(unittest.TestCase):
    """La collecte ne doit dépendre d'aucun module externe."""

    def setUp(self):
        self.p = _tmp_path()

    def tearDown(self):
        if os.path.exists(self.p):
            os.unlink(self.p)

    def test_init_cree_la_base(self):
        self.assertTrue(analytics.init_store(self.p))
        self.assertTrue(os.path.exists(self.p))

    def test_init_idempotent(self):
        analytics.init_store(self.p)
        self.assertTrue(analytics.init_store(self.p), "second appel doit réussir")

    def test_record_puis_relecture(self):
        analytics.init_store(self.p)
        now = time.time()
        for h in range(3):
            for i in range(10):
                analytics.record_spot(
                    {"timestamp": now - h*3600 - i*60, "band": "20m",
                     "dx_call": "W1AW", "mode": "CW"}, db_path=self.p)
        st = analytics.store_status(self.p)
        self.assertEqual(st["rows"], 30)
        r = analytics.compute_recent(self.p, now=now)
        self.assertTrue(r["available"])
        self.assertEqual(r["total"], 30)

    def test_spot_sans_bande_rejete(self):
        analytics.init_store(self.p)
        self.assertFalse(analytics.record_spot({"timestamp": time.time()}, db_path=self.p))
        self.assertFalse(analytics.record_spot({"band": "", "timestamp": 1}, db_path=self.p))
        self.assertEqual(analytics.store_status(self.p)["rows"], 0)

    def test_record_absorbe_les_erreurs(self):
        """Sur le chemin critique, une panne d'écriture ne doit pas remonter."""
        try:
            ok = analytics.record_spot({"band": "20m", "timestamp": time.time()},
                                       db_path="/racine/interdite/x.sqlite")
        except Exception as exc:
            self.fail(f"record_spot a propagé une exception : {exc}")
        self.assertFalse(ok)

    def test_timestamp_absent_utilise_maintenant(self):
        analytics.init_store(self.p)
        self.assertTrue(analytics.record_spot({"band": "40m"}, db_path=self.p))
        st = analytics.store_status(self.p)
        self.assertEqual(st["rows"], 1)
        self.assertLess(abs(st["last_ts"] - time.time()), 5)

    def test_cleanup_purge(self):
        analytics.init_store(self.p)
        now = time.time()
        analytics.record_spot({"band": "20m", "timestamp": now - 100*86400}, db_path=self.p)
        analytics.record_spot({"band": "20m", "timestamp": now}, db_path=self.p)
        removed = analytics.cleanup_store(days=90, db_path=self.p)
        self.assertEqual(removed, 1)
        self.assertEqual(analytics.store_status(self.p)["rows"], 1)

    def test_status_distingue_les_causes(self):
        absent = analytics.store_status("/nope/none.sqlite")
        self.assertFalse(absent["exists"])
        analytics.init_store(self.p)
        vide = analytics.store_status(self.p)
        self.assertTrue(vide["exists"])
        self.assertEqual(vide["rows"], 0)


class TestRepliMemoire(unittest.TestCase):
    """Sans aucune base, les spots en mémoire doivent suffire."""

    def _spots(self, hours=6, per_hour=20, now=None):
        now = now or time.time()
        return [{"timestamp": now - h*3600 - i*60, "band": "20m",
                 "dx_call": f"D{i}", "mode": "FT8"}
                for h in range(hours) for i in range(per_hour)], now

    def test_recent_via_memoire(self):
        spots, now = self._spots()
        r = analytics.compute_recent("/nope/none.sqlite", now=now,
                                     memory_spots=spots)
        self.assertTrue(r["available"], "la mémoire doit suffire")
        self.assertEqual(r["total"], 120)

    def test_compute_all_via_memoire(self):
        spots, now = self._spots()
        d = analytics.compute_all("/nope/none.sqlite", now=now,
                                  memory_spots=spots)
        self.assertEqual(d["source"], "memory")
        self.assertTrue(d["recent"]["available"])

    def test_memoire_vide_degrade_proprement(self):
        d = analytics.compute_all("/nope/none.sqlite", memory_spots=[])
        self.assertFalse(d["recent"]["available"])
        self.assertEqual(d["recent"]["series"], [])
        self.assertIsNone(d["source"])

    def test_spots_malformes_ignores(self):
        now = time.time()
        spots = [{"timestamp": now - 60, "band": "20m"},
                 {"band": "20m"},                       # sans timestamp
                 {"timestamp": now - 60},                # sans bande
                 {"timestamp": "abc", "band": "20m"},    # ts invalide
                 None]
        r = analytics.compute_recent("/nope/none.sqlite", now=now,
                                     memory_spots=[s for s in spots if s])
        self.assertTrue(r["available"])
        self.assertEqual(r["total"], 1)

    def test_base_prioritaire_si_plus_profonde(self):
        """Une base plus riche doit primer sur la mémoire."""
        p = _tmp_path()
        analytics.init_store(p)
        now = time.time()
        for h in range(72):
            analytics.record_spot({"timestamp": now - h*3600, "band": "40m"},
                                  db_path=p)
        spots, _ = self._spots(hours=3, now=now)
        d = analytics.compute_all(p, now=now, memory_spots=spots)
        self.assertIn("sqlite", d["source"], "la base doit primer")
        os.unlink(p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
