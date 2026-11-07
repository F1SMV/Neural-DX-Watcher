"""Tests hors réseau de tools/sync_satellites.py. Lancer depuis la racine : python3 -m unittest test_sync_satellites -v"""
import unittest
from datetime import date

from tools.sync_satellites import attach_norad, check_tle, discover, sync
from tools.enrich_satellites import index_satnogs

TODAY = date(2026, 11, 6)

RECORDS = [
    {"name": "CAS-6", "names": "TO-108", "norad_cat_id": 44881, "status": "in orbit", "launched": "2026-03-30"},
    {"name": "ERMINAZ-2U", "names": "", "norad_cat_id": 98207, "status": "in orbit", "launched": "2026-10-01"},
    {"name": "NEWSAT-1", "names": "", "norad_cat_id": 99001, "status": "future", "launched": None},
    {"name": "OLDSAT", "names": "", "norad_cat_id": 90001, "status": "in orbit", "launched": "2024-01-01"},
    {"name": "DEADSAT", "names": "", "norad_cat_id": 90002, "status": "dead", "launched": "2026-10-20"},
]


class TestNorad(unittest.TestCase):
    def test_ajoute_norad_par_alias_satnogs(self):
        sat = {"name": "TO-108 (CAS-6)", "status": "actif"}
        self.assertTrue(attach_norad(sat, index_satnogs(RECORDS)))
        self.assertEqual(sat["norad"], 44881)

    def test_ne_change_pas_un_norad_existant(self):
        sat = {"name": "TO-108 (CAS-6)", "norad": 1}
        self.assertFalse(attach_norad(sat, index_satnogs(RECORDS)))
        self.assertEqual(sat["norad"], 1)

    def test_satellite_inconnu_reste_sans_norad(self):
        sat = {"name": "CUBESAT INCONNU"}
        self.assertFalse(attach_norad(sat, index_satnogs(RECORDS)))
        self.assertNotIn("norad", sat)


class TestTle(unittest.TestCase):
    def test_actif_sans_norad_passe_statut_inconnu(self):
        sat = {"name": "X", "status": "actif"}
        self.assertIsNotNone(check_tle(sat, {44881}))
        self.assertEqual(sat["status"], "statut_inconnu")
        self.assertIn("pas de NORAD", sat["status_reason"])

    def test_actif_norad_absent_des_tle_passe_statut_inconnu(self):
        sat = {"name": "X", "status": "actif", "norad": 98207}
        check_tle(sat, {44881})
        self.assertEqual(sat["status"], "statut_inconnu")
        self.assertIn("absent des TLE", sat["status_reason"])

    def test_actif_avec_tle_inchange(self):
        sat = {"name": "X", "status": "actif", "norad": 44881}
        self.assertIsNone(check_tle(sat, {44881}))
        self.assertEqual(sat["status"], "actif")

    def test_a_venir_sans_norad_passe_statut_inconnu(self):
        sat = {"name": "CAS-7A", "status": "a_venir"}
        self.assertIsNotNone(check_tle(sat, set()))
        self.assertEqual(sat["status"], "statut_inconnu")

    def test_a_venir_avec_norad_inchange(self):
        sat = {"name": "X", "status": "a_venir", "norad": 99001}
        self.assertIsNone(check_tle(sat, set()))
        self.assertEqual(sat["status"], "a_venir")

    def test_autre_statut_non_touche(self):
        sat = {"name": "X", "status": "en_deploiement"}
        self.assertIsNone(check_tle(sat, set()))
        self.assertEqual(sat["status"], "en_deploiement")


class TestParseTle(unittest.TestCase):
    TEXT = (
        "CAS-6\n"
        "1 44881U 19065A   26310.50000000  .00000000  00000-0  00000-0 0  9991\n"
        "2 44881  97.5000 100.0000 0010000  90.0000 270.0000 15.10000000 10001\n"
        "ERMINAZ-2U\n"
        "1 98207U 26001A   26310.50000000  .00000000  00000-0  00000-0 0  9992\n"
        "2 98207  97.5000 100.0000 0010000  90.0000 270.0000 15.10000000 10002\n"
    )

    def test_extrait_les_norad_des_lignes_1(self):
        from tools.sync_satellites import parse_tle_norads
        self.assertEqual(parse_tle_norads(self.TEXT), {44881, 98207})

    def test_ignore_les_lignes_2_et_les_noms(self):
        from tools.sync_satellites import parse_tle_norads
        self.assertEqual(parse_tle_norads("2 44881  97.5\nCAS-6\n"), set())


class TestDecouverte(unittest.TestCase):
    def test_detecte_a_venir_et_lancement_recent_seulement(self):
        found = discover(RECORDS, registry_norads=set(), today=TODAY)
        names = {f["name"] for f in found}
        self.assertIn("NEWSAT-1", names)      # à venir
        self.assertIn("ERMINAZ-2U", names)    # lancé le 1er oct. 2026
        self.assertNotIn("OLDSAT", names)     # lancé en 2024
        self.assertNotIn("DEADSAT", names)    # hors service

    def test_ignore_ce_qui_est_deja_dans_le_registre(self):
        found = discover(RECORDS, registry_norads={99001}, today=TODAY)
        self.assertNotIn("NEWSAT-1", {f["name"] for f in found})

    def test_nouveau_satellite_marque_a_valider(self):
        found = discover(RECORDS, registry_norads=set(), today=TODAY)
        self.assertTrue(all(f["a_valider"] for f in found))


class TestSync(unittest.TestCase):
    def test_flux_complet(self):
        doc = {"satellites": [
            {"name": "TO-108 (CAS-6)", "status": "actif", "launch": None},
            {"name": "AO-129 (ERMINAZ-2U)", "status": "actif", "launch": None},
            {"name": "CUBESAT INCONNU", "status": "actif"},
        ]}
        tle = {44881}  # ERMINAZ-2U absent des TLE
        doc, report = sync(doc, RECORDS, tle, TODAY, discover_new=True)
        sats = {s["name"]: s for s in doc["satellites"]}

        self.assertEqual(sats["TO-108 (CAS-6)"]["status"], "actif")
        self.assertEqual(sats["AO-129 (ERMINAZ-2U)"]["norad"], 98207)
        self.assertEqual(sats["AO-129 (ERMINAZ-2U)"]["status"], "statut_inconnu")
        self.assertEqual(sats["CUBESAT INCONNU"]["status"], "statut_inconnu")
        self.assertIn("CUBESAT INCONNU", report["norad_introuvables"])
        self.assertIn("NEWSAT-1", [n[0] for n in report["nouveaux"]])

    def test_decouverte_desactivee_par_defaut(self):
        doc = {"satellites": [{"name": "TO-108 (CAS-6)", "status": "actif"}]}
        doc, report = sync(doc, RECORDS, {44881}, TODAY)
        self.assertEqual(len(doc["satellites"]), 1)          # rien ajouté au registre
        self.assertTrue(any(n[0] == "NEWSAT-1" for n in report["nouveaux"]))  # signalé seulement

    def test_sync_idempotent_avec_decouverte(self):
        doc = {"satellites": [{"name": "TO-108 (CAS-6)", "status": "actif"}]}
        doc, _ = sync(doc, RECORDS, {44881}, TODAY, discover_new=True)
        doc, report = sync(doc, RECORDS, {44881}, TODAY, discover_new=True)
        self.assertEqual(report["statuts_modifies"], [])
        self.assertEqual(report["nouveaux"], [])  # déjà au registre, plus signalé
        self.assertEqual(sum(1 for s in doc["satellites"] if s["name"] == "NEWSAT-1"), 1)


if __name__ == "__main__":
    unittest.main()
