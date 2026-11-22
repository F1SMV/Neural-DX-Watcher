"""Tests de tle_omm.py — éléments OMM (CelesTrak GP JSON) → TLE (v14).

Cas réel : UNNE-1B (HADES-E2), NORAD 101101 (> 99999), publié le 16 novembre 2026.
Ce NORAD n'existe pas en TLE texte : il doit passer en Alpha-5 (A1101).
"""
import math
import unittest

from sgp4.api import Satrec, jday

import tle_omm as to

HADES = {
    "OBJECT_NAME": "UNNE-1B (HADES-E2)", "OBJECT_ID": "2026-227CP",
    "EPOCH": "2026-11-16T22:40:50.536704", "MEAN_MOTION": 15.19122244,
    "ECCENTRICITY": 0.00024785, "INCLINATION": 97.4375, "RA_OF_ASC_NODE": 29.7097,
    "ARG_OF_PERICENTER": 78.9731, "MEAN_ANOMALY": 281.1782, "EPHEMERIS_TYPE": 0,
    "CLASSIFICATION_TYPE": "U", "NORAD_CAT_ID": 101101, "ELEMENT_SET_NO": 999,
    "REV_AT_EPOCH": 701, "BSTAR": 0.77687467e-3, "MEAN_MOTION_DOT": 0.1627e-3,
    "MEAN_MOTION_DDOT": 0,
}
ISS_TLE = ("ISS (ZARYA)",
           "1 25544U 98067A   26320.50000000  .00016717  00000+0  10270-3 0  9002",
           "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537")


def _alt_km(sat, when):
    jd, fr = jday(*when)
    err, r, _ = sat.sgp4(jd, fr)
    assert err == 0, f"erreur sgp4 {err}"
    return math.sqrt(sum(x * x for x in r)) - 6378.137


def _checksum_ok(line):
    total = sum(int(c) if c.isdigit() else (1 if c == "-" else 0) for c in line[:68])
    return int(line[68]) == total % 10


class TestConversion(unittest.TestCase):
    def test_norad_6_chiffres_en_alpha5(self):
        name, tle1, tle2 = to.omm_to_tle(HADES)[1:]
        self.assertTrue(tle1.startswith("1 A1101U"), tle1)
        self.assertTrue(tle2.startswith("2 A1101 "), tle2)
        self.assertEqual(len(tle1), 69)
        self.assertEqual(len(tle2), 69)
        self.assertEqual(name, "UNNE-1B (HADES-E2)")

    def test_checksums_valides(self):
        _, tle1, tle2 = to.omm_to_tle(HADES)[1:]
        self.assertTrue(_checksum_ok(tle1))
        self.assertTrue(_checksum_ok(tle2))

    def test_meme_orbite_qu_en_omm(self):
        """Les lignes produites donnent la même position que l'OMM d'origine (< 10 m)."""
        _, tle1, tle2 = to.omm_to_tle(HADES)[1:]
        ref = Satrec()
        from sgp4 import omm as _omm
        _omm.initialize(ref, {**HADES, "OBJECT_ID": "2026-227CP", "EPHEMERIS_TYPE": "0",
                              "CLASSIFICATION_TYPE": "U", "ELEMENT_SET_NO": "999",
                              "REV_AT_EPOCH": "701", "NORAD_CAT_ID": "101101",
                              "MEAN_MOTION_DDOT": "0", "MEAN_MOTION_DOT": "0.0001627",
                              "BSTAR": "0.00077687467"})
        sat = Satrec.twoline2rv(tle1, tle2)
        jd, fr = jday(2026, 11, 17, 12, 0, 0)
        _, r1, _ = sat.sgp4(jd, fr)
        _, r0, _ = ref.sgp4(jd, fr)
        self.assertLess(math.dist(r1, r0), 0.01)

    def test_altitude_plausible(self):
        _, tle1, tle2 = to.omm_to_tle(HADES)[1:]
        alt = _alt_km(Satrec.twoline2rv(tle1, tle2), (2026, 11, 17, 12, 0, 0))
        self.assertTrue(480 < alt < 540, alt)      # 15,19 tr/j : orbite basse

    def test_norad_5_chiffres_inchange(self):
        obj = dict(HADES, NORAD_CAT_ID=25544, OBJECT_ID="1998-067A")
        _, tle1, tle2 = to.omm_to_tle(obj)[1:]
        self.assertTrue(tle1.startswith("1 25544U"))
        self.assertTrue(_checksum_ok(tle1) and _checksum_ok(tle2))

    def test_lignes_tle_existantes_prioritaires(self):
        """Si la source fournit déjà les lignes TLE, elles sont reprises telles quelles."""
        obj = {"OBJECT_NAME": ISS_TLE[0], "NORAD_CAT_ID": 25544,
               "TLE_LINE1": ISS_TLE[1], "TLE_LINE2": ISS_TLE[2]}
        self.assertEqual(to.omm_to_tle(obj), (25544, ISS_TLE[0], ISS_TLE[1], ISS_TLE[2]))

    def test_epoque_sans_fraction(self):
        obj = dict(HADES, EPOCH="2026-11-16T22:40:50")
        self.assertEqual(len(to.omm_to_tle(obj)[2]), 69)

    def test_champ_manquant_leve_valueerror(self):
        obj = {k: v for k, v in HADES.items() if k != "BSTAR"}
        with self.assertRaises((KeyError, ValueError)):
            to.omm_to_tle(obj)


class TestParsing(unittest.TestCase):
    def test_json_mixte(self):
        import json
        data = [HADES, {"NORAD_CAT_ID": 1, "OBJECT_NAME": "CASSE"}, "pas un objet"]
        out, skipped = to.parse_omm_json(json.dumps(data))
        self.assertEqual(set(out), {101101})
        self.assertEqual(skipped, 2)

    def test_json_invalide_ou_vide(self):
        self.assertEqual(to.parse_omm_json("pas du json"), ({}, 0))
        self.assertEqual(to.parse_omm_json("[]"), ({}, 0))
        self.assertEqual(to.parse_omm_json('{"a": 1}'), ({}, 0))


class TestFichierLocal(unittest.TestCase):
    def test_fichier_absent(self):
        self.assertEqual(to.load_omm_file("/nonexistent/omm_local.json"), ({}, 0))

    def test_fichier_local_lu(self):
        import json, os, tempfile
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump([HADES], f)
        try:
            found, skipped = to.load_omm_file(path)
            self.assertEqual(set(found), {101101})
            self.assertEqual(skipped, 0)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
