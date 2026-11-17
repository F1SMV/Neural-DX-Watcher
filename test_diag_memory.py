"""Tests de tools/diag_memory.py."""
import unittest
from datetime import datetime, timedelta, timezone

from tools import diag_memory as dm


def log(start, hours, rss_at):
    """Journal toutes les 5 min ; rss_at(datetime) -> RSS en Ko."""
    t, out = start, []
    while t < start + timedelta(hours=hours):
        out.append(f"{t:%Y-%m-%dT%H:%M:%SZ} {rss_at(t)}")
        t += timedelta(minutes=5)
    return out


START = datetime(2026, 11, 13, 20, 0, tzinfo=timezone.utc)


class TestDiagMemory(unittest.TestCase):
    def test_parse_ignore_lignes_incompletes(self):
        pts = dm.parse_log(["2026-11-13T20:00:00Z 102400", "2026-11-13T20:05:00Z", "bruit", ""])
        self.assertEqual(len(pts), 1)
        self.assertEqual(pts[0][1], 100.0)

    def test_stable(self):
        pts = dm.parse_log(log(START, 60, lambda t: 100_000))
        deltas = dm.nightly_deltas(pts)
        self.assertEqual(len(deltas), 3)
        self.assertEqual(dm.verdict(deltas), "ok")

    def test_palier_v13_detecte(self):
        """+17 Mo à chaque cycle de 03:00 UTC, comme mesuré en phase 0."""
        def rss(t):
            nights = sum(1 for d in range(3)
                         if t >= START.replace(hour=3, minute=10) + timedelta(days=d + 1))
            return 100_000 + nights * 17_400
        deltas = dm.nightly_deltas(dm.parse_log(log(START, 60, rss)))
        self.assertEqual(dm.verdict(deltas), "croissance")
        self.assertAlmostEqual(deltas[0][3], 17.0, delta=0.1)

    def test_redemarrage_ecarte(self):
        """Un redémarrage pendant la nuit ne doit pas passer pour une baisse."""
        cut = START.replace(hour=3, minute=20) + timedelta(days=1)
        pts = dm.parse_log(log(START, 12, lambda t: 150_000 if t < cut else 80_000))
        self.assertEqual(dm.nightly_deltas(pts), [])

    def test_journal_sans_nuit(self):
        pts = dm.parse_log(log(START, 2, lambda t: 100_000))
        self.assertEqual(dm.verdict(dm.nightly_deltas(pts)), "insuffisant")
        self.assertEqual(dm.verdict(dm.nightly_deltas([])), "insuffisant")


if __name__ == "__main__":
    unittest.main()
