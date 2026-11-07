"""Tests hors réseau. Lancer : python3 -m unittest test_enrich_satellites -v"""
import copy
import unittest

from datetime import date

from tools.enrich_satellites import core_name, enrich, index_satnogs, suggest_status

SNG = [
    {"name": "FO-29", "names": "JAS-2", "norad_cat_id": 24278, "status": "alive",
     "launched": "1996-08-17T00:00:00Z", "decayed": None},
    {"name": "TRANSIT 5B-5", "names": "OPS 6582", "norad_cat_id": 965,
     "status": "in orbit", "launched": "1964-12-13T00:00:00Z", "decayed": None},
    {"name": "Lilium-4", "names": "BN0YCA", "norad_cat_id": 99999,
     "status": "future", "launched": "2026-04-02T00:00:00Z", "decayed": None},
]
REG = {
    "updated": "2026-10-28",
    "sources": [{"id": "a", "label": "A", "url": "https://a.example/", "date": "2026"}],
    "satellites": [
        {"name": "FO-29 (JAS-2)", "status": "actif", "launch": None, "sources": ["a"]},
        {"name": "Lilium-4 (BN0YCA)", "status": "en_deploiement", "launch": "2026-03-30", "sources": ["a"]},
        {"name": "SAT-INCONNU", "status": "statut_inconnu", "launch": None, "sources": ["a"]},
    ],
}


class TestNom(unittest.TestCase):
    def test_nom_principal(self):
        self.assertEqual(core_name("FO-29 (JAS-2)"), "fo29")
        self.assertEqual(core_name("CAS-8A / 8B / 8C / 8D"), "cas8a")

    def test_alias_satnogs(self):
        idx = index_satnogs(SNG)
        self.assertIs(idx["jas2"], SNG[0])
        self.assertIs(idx["ops6582"], SNG[1])


class TestEnrich(unittest.TestCase):
    def setUp(self):
        self.raw = copy.deepcopy(REG)
        self.out, self.rep = enrich(self.raw, SNG)
        self.sats = {s["name"]: s for s in self.out["satellites"]}

    def test_source_satnogs_ajoutee_une_seule_fois(self):
        ids = [s["id"] for s in self.out["sources"]]
        self.assertEqual(ids.count("satnogs"), 1)

    def test_date_manquante_reprise_de_satnogs(self):
        fo = self.sats["FO-29 (JAS-2)"]
        self.assertEqual(fo["launch"], "1996-08-17")
        self.assertIn("satnogs", fo["sources"])
        self.assertEqual(self.rep["launch_filled"], ["FO-29 (JAS-2) -> 1996-08-17"])

    def test_desaccord_jamais_ecrase(self):
        lil = self.sats["Lilium-4 (BN0YCA)"]
        self.assertEqual(lil["launch"], "2026-03-30")
        self.assertEqual(lil["launch_check"], "desaccord")
        self.assertTrue(any("Lilium-4" in x for x in self.rep["launch_disagree"]))

    def test_non_trouve_signale(self):
        self.assertIn("SAT-INCONNU", self.rep["unmatched"])
        self.assertNotIn("satnogs", self.sats["SAT-INCONNU"]["sources"])

    def test_registre_de_reference_non_modifie(self):
        # enrich() travaille sur une copie : le registre de référence du module reste intact
        self.assertIsNone(REG["satellites"][0]["launch"])
        self.assertNotIn("satnogs", REG["satellites"][0])


class TestStatutSuggere(unittest.TestCase):
    TODAY = date(2026, 11, 4)

    def test_lancement_ancien_sans_exploitation(self):
        sat = {"name": "X", "status": "en_deploiement", "launch": "2026-03-30"}
        new, why = suggest_status(sat, self.TODAY)
        self.assertEqual(new, "statut_inconnu")
        self.assertIn("219 j", why)

    def test_lancement_recent_reste_en_deploiement(self):
        sat = {"name": "X", "status": "en_deploiement", "launch": "2026-10-20"}
        self.assertEqual(suggest_status(sat, self.TODAY), (None, None))

    def test_seuil_60_jours_exact(self):
        sat = {"name": "X", "status": "en_deploiement", "launch": "2026-09-05"}  # 60 j
        self.assertEqual(suggest_status(sat, self.TODAY), (None, None))
        sat["launch"] = "2026-09-04"  # 61 j
        self.assertEqual(suggest_status(sat, self.TODAY)[0], "statut_inconnu")

    def test_satnogs_dead_donne_hors_service(self):
        sat = {"name": "X", "status": "actif", "launch": None,
               "satnogs": {"status": "re-entered", "decayed": "2025-01-01"}}
        self.assertEqual(suggest_status(sat, self.TODAY)[0], "hors_service")

    def test_satnogs_future_donne_a_venir(self):
        sat = {"name": "X", "status": "statut_inconnu", "launch": None,
               "satnogs": {"status": "future", "decayed": None}}
        self.assertEqual(suggest_status(sat, self.TODAY)[0], "a_venir")

    def test_rapport_contient_les_suggestions(self):
        raw = {"sources": [], "satellites": [
            {"name": "Vieux", "status": "en_deploiement", "launch": "2026-03-30", "sources": []}]}
        _, rep = enrich(raw, [], today=self.TODAY)
        self.assertEqual(len(rep["status_suggestions"]), 1)
        self.assertIn("statut_inconnu", rep["status_suggestions"][0])


class TestApplicationStatut(unittest.TestCase):
    TODAY = date(2026, 11, 4)

    def _raw(self):
        return {"sources": [], "satellites": [
            {"name": "Vieux", "status": "en_deploiement", "launch": "2026-03-30", "sources": []}]}

    def test_sans_option_statut_inchange(self):
        raw = self._raw()
        enrich(raw, [], today=self.TODAY, apply_status=False)
        self.assertEqual(raw["satellites"][0]["status"], "en_deploiement")

    def test_avec_option_statut_applique(self):
        raw = self._raw()
        _, rep = enrich(raw, [], today=self.TODAY, apply_status=True)
        self.assertEqual(raw["satellites"][0]["status"], "statut_inconnu")
        self.assertEqual(rep["status_applied"], ["Vieux"])


if __name__ == "__main__":
    unittest.main()
