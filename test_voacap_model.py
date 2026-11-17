"""Tests de voacap_model.py — cohérence accueil / insight (v14).

Avant v14 : LUF en paliers (saut à 1000 km), accueil en heure UTC, insight en heure
solaire du point milieu. Les deux vues ne donnaient pas la même propagation.
"""
import unittest

import voacap_model as vm


class TestLuf(unittest.TestCase):
    def test_continue_en_distance(self):
        for night in (12, 2):
            for seuil in (1000, 5000, 10000):
                a, b = vm.luf(seuil - 0.1, night), vm.luf(seuil + 0.1, night)
                self.assertLess(abs(a - b), 0.01, f"saut à {seuil} km, heure {night}")

    def test_decroissante_en_distance(self):
        for h in (12, 2):
            valeurs = [vm.luf(d, h) for d in range(100, 12000, 100)]
            self.assertTrue(all(x >= y - 1e-9 for x, y in zip(valeurs, valeurs[1:])))

    def test_valeurs_d_ancrage(self):
        self.assertAlmostEqual(vm.luf(500, 12), 7.0)
        self.assertAlmostEqual(vm.luf(500, 2), 4.0)
        self.assertAlmostEqual(vm.luf(5000, 12), 5.5)
        self.assertAlmostEqual(vm.luf(20000, 12), 4.5)

    def test_nuit_plus_basse_que_jour(self):
        self.assertLess(vm.luf(3000, 2), vm.luf(3000, 12))


class TestHeureLocale(unittest.TestCase):
    def test_point_milieu_meme_lieu(self):
        self.assertAlmostEqual(vm.midpoint_lon(43.0, 5.9, 43.0, 5.9), 5.9, places=3)

    def test_point_milieu_entre_deux_extremites(self):
        lon = vm.midpoint_lon(43.0, 5.9, 35.0, 139.0)
        self.assertGreater(lon, 5.9)
        self.assertLess(lon, 139.0)

    def test_heure_locale_decalee_par_longitude(self):
        self.assertEqual(vm.local_hour(12, 90.0), 18)
        self.assertEqual(vm.local_hour(12, -90.0), 6)
        self.assertEqual(vm.local_hour(23, 30.0), 1)

    def test_distance_haversine(self):
        d = vm.distance_km(43.0, 5.9, 35.0, 139.0)
        self.assertTrue(10000 < d < 10250)   # Toulon-Japon ≈ 10 120 km


class TestCoherenceAccueilInsight(unittest.TestCase):
    """L'accueil (par heure UTC) et l'insight (par point milieu) doivent lire le même profil."""

    TX = (43.0, 5.9)          # La Seyne-sur-Mer
    RX = (35.0, 139.0)        # Japon
    FREQS = [7.1, 14.2, 21.2]

    def test_profil_identique_pour_les_deux_vues(self):
        prof = vm.profile(*self.TX, *self.RX, sfi=120, kp=2, freqs=self.FREQS)
        self.assertEqual(sorted(prof), list(range(24)))
        for h in range(24):
            # Une seule source : accueil et insight lisent la même entrée à la même heure UTC.
            self.assertEqual(prof[h]["local_hour"], vm.local_hour(h, prof[h]["mid_lon"]))
            for f in self.FREQS:
                self.assertIn(f, prof[h]["rel"])

    def test_fiabilite_nulle_hors_fenetre(self):
        prof = vm.profile(*self.TX, *self.RX, sfi=60, kp=None, freqs=[28.0])
        self.assertTrue(all(prof[h]["rel"][28.0] == 0.0 for h in range(24)))

    def test_kp_eleve_reduit(self):
        calme = vm.profile(*self.TX, *self.RX, sfi=150, kp=1, freqs=[14.2])
        orage = vm.profile(*self.TX, *self.RX, sfi=150, kp=7, freqs=[14.2])
        self.assertLessEqual(max(orage[h]["rel"][14.2] for h in range(24)),
                             max(calme[h]["rel"][14.2] for h in range(24)))

    def test_mode_sans_sfi_pas_de_crash(self):
        prof = vm.profile(*self.TX, *self.RX, sfi=None, kp=None, freqs=self.FREQS)
        self.assertEqual(len(prof), 24)


if __name__ == "__main__":
    unittest.main()
