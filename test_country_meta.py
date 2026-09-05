"""
test_country_meta.py — Validation country_meta.py avant intégration webapp.py
"""

import sys, time, json
sys.path.insert(0, "/home/claude/work")
import country_meta
from country_meta import get_country_meta, _parse_utc_offset, ALIASES

FAILED = []

def check(name, condition):
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {name}")
    if not condition:
        FAILED.append(name)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
    def json(self):
        return self._payload


def reset_cache():
    country_meta._cache = {}
    country_meta._cache_loaded = True  # empêche de recharger depuis le disque


# ══════════════════════════════════════════════════════════════════
print("=== TEST 1 : _parse_utc_offset ===")
check("'UTC+10:00' -> 10.0", _parse_utc_offset("UTC+10:00") == 10.0)
check("'UTC-03:30' -> -3.5", _parse_utc_offset("UTC-03:30") == -3.5)
check("'UTC' -> 0.0", _parse_utc_offset("UTC") == 0.0)
check("'' -> None", _parse_utc_offset("") is None)
check("'garbage' -> None", _parse_utc_offset("garbage") is None)
check("None -> None", _parse_utc_offset(None) is None)


# ══════════════════════════════════════════════════════════════════
print("\n=== TEST 2 : lookup réussi (mock API) ===")
reset_cache()

def fake_get_pngn(url, timeout=5):
    assert "papua" in url.lower()
    return FakeResponse(200, [{
        "name": {"common": "Papua New Guinea"},
        "capital": ["Port Moresby"],
        "population": 10329931,
        "flag": "🇵🇬",
        "timezones": ["UTC+10:00"],
    }])

meta = get_country_meta("Papua New Guinea", fake_get_pngn, local_utc_offset=2.0)
check("flag correct", meta["flag"] == "🇵🇬")
check("capital correcte", meta["capital"] == "Port Moresby")
check("population correcte", meta["population"] == 10329931)
check("tz_diff_hours = 10 - 2 = 8.0", meta["tz_diff_hours"] == 8.0)


# ══════════════════════════════════════════════════════════════════
print("\n=== TEST 3 : cache — pas de second appel réseau ===")
call_count = {"n": 0}
def counting_get(url, timeout=5):
    call_count["n"] += 1
    return FakeResponse(200, [{"name": {"common": "X"}, "capital": ["Y"],
                               "population": 1, "flag": "🏳", "timezones": ["UTC"]}])

reset_cache()
get_country_meta("Testland", counting_get, local_utc_offset=1.0)
get_country_meta("Testland", counting_get, local_utc_offset=1.0)
get_country_meta("Testland", counting_get, local_utc_offset=1.0)
check("1 seul appel réseau malgré 3 lookups (cache actif)", call_count["n"] == 1)


# ══════════════════════════════════════════════════════════════════
print("\n=== TEST 4 : tz_diff recalculé même depuis le cache (heure d'été) ===")
reset_cache()
get_country_meta("Testland2", counting_get, local_utc_offset=1.0)  # hiver, offset 1
meta_summer = get_country_meta("Testland2", counting_get, local_utc_offset=2.0)  # été, offset 2
check("tz_diff recalculé avec le nouvel offset local (pas figé au 1er appel)",
      meta_summer["tz_diff_hours"] == -2.0)  # UTC(0) - 2.0 = -2.0


# ══════════════════════════════════════════════════════════════════
print("\n=== TEST 5 : alias DXCC -> pays réel ===")
reset_cache()
called_with_url = {}
def fake_get_corsica(url, timeout=5):
    called_with_url["url"] = url
    return FakeResponse(200, [{"name": {"common": "France"}, "capital": ["Paris"],
                               "population": 67000000, "flag": "🇫🇷", "timezones": ["UTC+01:00"]}])

meta_corsica = get_country_meta("Corsica", fake_get_corsica, local_utc_offset=1.0)
check("Corsica -> requête faite vers 'France' (alias)", "france" in called_with_url["url"].lower())
check("Corsica -> données de France retournées (approximation assumée)",
      meta_corsica["capital"] == "Paris")


# ══════════════════════════════════════════════════════════════════
print("\n=== TEST 6 : API renvoie 404 / pays inconnu -> None, pas de crash ===")
reset_cache()
def fake_get_404(url, timeout=5):
    return FakeResponse(404, None)

meta_404 = get_country_meta("Nonexistent Country XYZ", fake_get_404, local_utc_offset=1.0)
check("404 -> None (pas de crash)", meta_404 is None)


# ══════════════════════════════════════════════════════════════════
print("\n=== TEST 7 : API renvoie une liste vide -> None ===")
reset_cache()
def fake_get_empty(url, timeout=5):
    return FakeResponse(200, [])

meta_empty = get_country_meta("Weird Entity", fake_get_empty, local_utc_offset=1.0)
check("Liste vide -> None", meta_empty is None)


# ══════════════════════════════════════════════════════════════════
print("\n=== TEST 8 : exception réseau (timeout, DNS...) -> None, pas de crash ===")
reset_cache()
def fake_get_exception(url, timeout=5):
    raise ConnectionError("simulated network failure")

meta_exc = get_country_meta("France", fake_get_exception, local_utc_offset=1.0)
check("Exception réseau -> None (pas de crash)", meta_exc is None)


# ══════════════════════════════════════════════════════════════════
print("\n=== TEST 9 : exception réseau MAIS cache existant -> fallback sur le cache ===")
reset_cache()
get_country_meta("Japan", fake_get_pngn.__wrapped__ if hasattr(fake_get_pngn, '__wrapped__') else
                  (lambda url, timeout=5: FakeResponse(200, [{
                      "name": {"common": "Japan"}, "capital": ["Tokyo"],
                      "population": 125000000, "flag": "🇯🇵", "timezones": ["UTC+09:00"]}])),
                  local_utc_offset=1.0)

meta_fallback = get_country_meta("Japan", fake_get_exception, local_utc_offset=1.0)
check("Panne réseau mais cache dispo -> données du cache retournées",
      meta_fallback is not None and meta_fallback["capital"] == "Tokyo")


# ══════════════════════════════════════════════════════════════════
print("\n=== TEST 10 : dxcc_name vide/None -> None immédiat, pas d'appel réseau ===")
reset_cache()
call_count2 = {"n": 0}
def counting_get2(url, timeout=5):
    call_count2["n"] += 1
    return FakeResponse(200, [])

check("chaîne vide -> None", get_country_meta("", counting_get2) is None)
check("None -> None", get_country_meta(None, counting_get2) is None)
check("Aucun appel réseau déclenché", call_count2["n"] == 0)


# ══════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
if FAILED:
    print(f"❌ {len(FAILED)} TEST(S) ÉCHOUÉ(S) :")
    for f in FAILED:
        print(f"   - {f}")
    sys.exit(1)
else:
    print("✅ TOUS LES TESTS PASSENT (100%)")
    sys.exit(0)
