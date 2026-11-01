"""Tests du pavé radioamateur (ham_radar). Lancer : python3 -m unittest test_ham_radar -v"""
import json
import unittest
from pathlib import Path

import ham_radar as hr

REGISTRY = Path(__file__).parent / "data" / "ham_satellites.json"


def _raw(sats, sources=None):
    srcs = sources or [
        {"id": "a", "label": "Source A", "url": "https://a.example/", "date": "2026"},
        {"id": "b", "label": "Source B", "url": "https://b.example/", "date": "2026"},
    ]
    return {"updated": "2026-10-28", "sources": srcs, "satellites": sats}


class TestRegistreReel(unittest.TestCase):
    def setUp(self):
        self.reg = hr.load_registry(REGISTRY)

    def test_aucune_erreur_sur_le_registre_livre(self):
        self.assertEqual(self.reg["errors"], [])

    def test_chaque_satellite_cite_au_moins_une_source(self):
        for e in self.reg["satellites"]:
            self.assertTrue(e.get("sources"), e["name"])

    def test_pas_de_date_de_lancement_inventee(self):
        # Une date publiée doit être une chaîne ISO ou null, jamais une valeur devinée.
        for e in self.reg["satellites"]:
            lv = e.get("launch")
            self.assertTrue(lv is None or isinstance(lv, str), e["name"])

    def test_fox1e_donnees_sources(self):
        p = hr.build_payload(self.reg)
        fox = next(i for i in p["groups"]["hors_service"] if i["name"] == "Fox-1E")
        self.assertEqual(fox["launch"], "2021-01-17")
        self.assertFalse(fox["confirmed"])          # une seule source : pas confirmé

    def test_fo29_confirme_et_nouvellement_actif(self):
        p = hr.build_payload(self.reg)
        fo = next(i for i in p["groups"]["actif"] if i["name"].startswith("FO-29"))
        self.assertTrue(fo["confirmed"])
        self.assertTrue(fo["recently_active"])


class TestValidation(unittest.TestCase):
    def test_statut_inconnu_rejete(self):
        r = hr.validate(_raw([{"name": "X", "status": "bizarre", "sources": ["a"]}]))
        self.assertEqual(r["satellites"], [])
        self.assertTrue(any("statut inconnu" in e for e in r["errors"]))

    def test_source_inconnue_signalee(self):
        r = hr.validate(_raw([{"name": "X", "status": "actif", "sources": ["zzz"]}]))
        self.assertTrue(any("source inconnue" in e for e in r["errors"]))

    def test_source_non_https_rejetee(self):
        bad = [{"id": "a", "label": "A", "url": "http://a.example/"}]
        r = hr.validate(_raw([], sources=bad))
        self.assertNotIn("a", r["sources"])
        self.assertTrue(any("source invalide" in e for e in r["errors"]))

    def test_satellite_sans_nom_ignore(self):
        r = hr.validate(_raw([{"status": "actif", "sources": ["a"]}]))
        self.assertEqual(r["satellites"], [])

    def test_registre_non_dict(self):
        r = hr.validate(["pas", "un", "dict"])
        self.assertEqual(r["satellites"], [])
        self.assertTrue(r["errors"])


class TestRecoupement(unittest.TestCase):
    def test_deux_sources_donnent_confirme(self):
        r = hr.validate(_raw([{"name": "X", "status": "actif", "sources": ["a", "b"]}]))
        p = hr.build_payload(r)
        self.assertTrue(p["groups"]["actif"][0]["confirmed"])
        self.assertEqual(len(p["groups"]["actif"][0]["sources"]), 2)

    def test_une_source_donne_non_confirme(self):
        r = hr.validate(_raw([{"name": "X", "status": "actif", "sources": ["a"]}]))
        self.assertFalse(hr.build_payload(r)["groups"]["actif"][0]["confirmed"])

    def test_meme_source_deux_fois_ne_compte_pas_double(self):
        r = hr.validate(_raw([{"name": "X", "status": "actif", "sources": ["a", "a"]}]))
        item = hr.build_payload(r)["groups"]["actif"][0]
        self.assertEqual(len(item["sources"]), 1)
        self.assertFalse(item["confirmed"])


class TestPayload(unittest.TestCase):
    def test_tous_les_statuts_presents(self):
        p = hr.build_payload(hr.load_registry(REGISTRY))
        self.assertEqual(set(p["groups"].keys()), set(hr.STATUSES))
        self.assertEqual(set(p["labels"].keys()), set(hr.STATUSES))

    def test_stats_coherentes(self):
        p = hr.build_payload(hr.load_registry(REGISTRY))
        total = sum(len(v) for v in p["groups"].values())
        self.assertEqual(p["stats"]["total"], total)
        self.assertLessEqual(p["stats"]["confirmed"], total)

    def test_payload_serialisable_json(self):
        p = hr.build_payload(hr.load_registry(REGISTRY))
        json.dumps(p)

    def test_champs_absents_donnent_none_pas_crash(self):
        r = hr.validate(_raw([{"name": "X", "status": "a_venir", "sources": ["a"]}]))
        item = hr.build_payload(r)["groups"]["a_venir"][0]
        self.assertIsNone(item["uplink"])
        self.assertFalse(item["recently_active"])


if __name__ == "__main__":
    unittest.main()
