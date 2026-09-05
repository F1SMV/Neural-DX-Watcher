"""
test_dxcc_hunt.py — Validation dxcc_hunt.py avant intégration webapp.py
Boucle : écrire -> simuler -> détecter edge cases -> corriger -> revalider
"""

import time
import sys
sys.path.insert(0, "/home/claude")
from dxcc_hunt import compute_hunt_list, STATUS_LABELS, STATUS_PRIORITY

# ── Fonctions injectées, répliquant le comportement réel de webapp.py ──

def calculate_bearing(lat1, lon1, lat2, lon2):
    import math
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
    brng = math.degrees(math.atan2(x, y))
    return (brng + 360) % 360

def bearing_to_compass(deg):
    if deg is None:
        return "?"
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    idx = int((deg + 22.5) // 45) % 8
    return dirs[idx]

RARE_PREFIXES = ["5V7", "3Y0", "FT5", "VP8/G"]
def is_rare_prefix(call):
    c = (call or "").upper()
    return any(c.startswith(p) for p in RARE_PREFIXES)


def make_spot(dx_call, country, band, mode="FT8", freq="14074.0",
              lat=48.0, lon=2.0, distance_km=1000.0, ts=None,
              score=0, is_wanted=False):
    return {
        "dx_call": dx_call, "country": country, "band": band, "mode": mode,
        "freq": freq, "lat": lat, "lon": lon, "distance_km": distance_km,
        "timestamp": ts if ts is not None else time.time(),
        "score": score, "is_wanted": is_wanted,
    }

FAILED = []

def check(name, condition):
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {name}")
    if not condition:
        FAILED.append(name)


# ══════════════════════════════════════════════════════════════════
print("=== TEST 1 : cas basique — 3 statuts distincts ===")

confirmed_dxcc = {"France", "Germany"}
worked_dxcc    = {"France", "Germany", "Spain"}   # Spain worked mais pas confirmé
dxcc_by_band   = {"20m": {"France"}, "40m": {"Germany"}}  # France confirmé 20m only

spots = [
    make_spot("5V7A",  "Togo",    "20m"),                     # jamais travaillé -> new
    make_spot("EA5BV", "Spain",   "20m"),                     # worked, pas confirmé -> worked_unconfirmed
    make_spot("F4ABC", "France",  "40m"),                     # confirmé 20m mais PAS 40m -> band_missing
    make_spot("DL1XYZ","Germany", "40m"),                     # confirmé 40m -> PAS une opportunité
]

hunt, total = compute_hunt_list(
    spots, confirmed_dxcc, worked_dxcc, dxcc_by_band,
    user_lat=43.076112, user_lon=5.873671,
    calculate_bearing_fn=calculate_bearing,
    bearing_to_compass_fn=bearing_to_compass,
    is_rare_fn=is_rare_prefix,
)

check("total_found == 3 (Germany/40m exclu)", total == 3)
check("hunt contient 3 entrées (pas plus)", len(hunt) == 3)
statuses = {e["country"]: e["status"] for e in hunt}
check("Togo -> new", statuses.get("Togo") == "new")
check("Spain -> worked_unconfirmed", statuses.get("Spain") == "worked_unconfirmed")
check("France -> band_missing", statuses.get("France") == "band_missing")
check("Germany absent (déjà confirmé sur 40m)", "Germany" not in statuses)

# Tri : priorité 1 (new) doit être en tête
check("Ordre : Togo (new) en premier", hunt[0]["country"] == "Togo")


# ══════════════════════════════════════════════════════════════════
print("\n=== TEST 2 : dédup (country, band) — garde le plus récent ===")

now = time.time()
spots2 = [
    make_spot("OLD1CALL", "Togo", "20m", ts=now - 500),
    make_spot("NEW1CALL", "Togo", "20m", ts=now - 10),   # plus récent -> doit gagner
]
hunt2, total2 = compute_hunt_list(
    spots2, set(), set(), {},
    user_lat=43.076112, user_lon=5.873671,
    calculate_bearing_fn=calculate_bearing,
    bearing_to_compass_fn=bearing_to_compass,
    is_rare_fn=is_rare_prefix,
)
check("total_found == 1 (dédup fonctionne)", total2 == 1)
check("Le plus récent (NEW1CALL) est gardé", hunt2[0]["dx_call"] == "NEW1CALL")


# ══════════════════════════════════════════════════════════════════
print("\n=== TEST 3 : exclusion Unknown / vide ===")

spots3 = [
    make_spot("XX1XXX", "Unknown", "20m"),
    make_spot("YY1YYY", "", "20m"),
    make_spot("ZZ1ZZZ", "Chad", "20m"),
]
hunt3, total3 = compute_hunt_list(
    spots3, set(), set(), {},
    user_lat=43.076112, user_lon=5.873671,
    calculate_bearing_fn=calculate_bearing,
    bearing_to_compass_fn=bearing_to_compass,
    is_rare_fn=is_rare_prefix,
)
check("Unknown et vide exclus, seul Chad reste", total3 == 1 and hunt3[0]["country"] == "Chad")


# ══════════════════════════════════════════════════════════════════
print("\n=== TEST 4 : bearing/compass calculés correctement, absent si lat/lon=0 ===")

spots4 = [
    make_spot("VALID1", "Japan", "20m", lat=35.6, lon=139.6),   # coords valides
    make_spot("NOCOORD", "Chad", "20m", lat=0.0, lon=0.0),      # pas de coords -> bearing None
]
hunt4, _ = compute_hunt_list(
    spots4, set(), set(), {},
    user_lat=43.076112, user_lon=5.873671,
    calculate_bearing_fn=calculate_bearing,
    bearing_to_compass_fn=bearing_to_compass,
    is_rare_fn=is_rare_prefix,
)
by_country = {e["country"]: e for e in hunt4}
check("Japan a un bearing calculé (non None)", by_country["Japan"]["bearing_deg"] is not None)
check("Japan a un compass valide", by_country["Japan"]["compass"] in
      ["N","NE","E","SE","S","SW","W","NW"])
check("Japan a lat/lon transmis pour la carte", by_country["Japan"]["lat"] == 35.6 and by_country["Japan"]["lon"] == 139.6)
check("Chad (0,0) -> bearing None", by_country["Chad"]["bearing_deg"] is None)
check("Chad (0,0) -> compass None", by_country["Chad"]["compass"] is None)
check("Chad (0,0) -> lat/lon None (coords invalides)", by_country["Chad"]["lat"] is None and by_country["Chad"]["lon"] is None)


# ══════════════════════════════════════════════════════════════════
print("\n=== TEST 5 : tri par spd_score (signal réel, remplace le simple is_rare) ===")

spots5 = [
    make_spot("F4ABC",  "France", "20m", ts=now, score=15, is_wanted=False),  # score faible
    make_spot("5V7A",   "Togo",   "20m", ts=now, score=95, is_wanted=True),   # score fort (rare+split+distance)
]
hunt5, _ = compute_hunt_list(
    spots5, set(), set(), {},   # rien travaillé -> tout est "new" = même priorité
    user_lat=43.076112, user_lon=5.873671,
    calculate_bearing_fn=calculate_bearing,
    bearing_to_compass_fn=bearing_to_compass,
    is_rare_fn=is_rare_prefix,
)
check("Même priorité -> le meilleur spd_score (5V7A) passe en premier", hunt5[0]["dx_call"] == "5V7A")
check("spd_score transmis correctement (95)", hunt5[0]["spd_score"] == 95)
check("is_wanted transmis correctement (True)", hunt5[0]["is_wanted"] == True)
check("Le second (F4ABC) a bien spd_score=15", hunt5[1]["spd_score"] == 15)


# ══════════════════════════════════════════════════════════════════
print("\n=== TEST 6 : band_filter ===")

spots6 = [
    make_spot("A1", "Chad", "20m"),
    make_spot("A2", "Mali", "6m"),
]
hunt6, total6 = compute_hunt_list(
    spots6, set(), set(), {},
    user_lat=43.076112, user_lon=5.873671,
    calculate_bearing_fn=calculate_bearing,
    bearing_to_compass_fn=bearing_to_compass,
    is_rare_fn=is_rare_prefix,
    band_filter="6m",
)
check("band_filter='6m' -> seul Mali/6m retenu", total6 == 1 and hunt6[0]["country"] == "Mali")


# ══════════════════════════════════════════════════════════════════
print("\n=== TEST 7 : limit tronque mais total_found reste le vrai total ===")

spots7 = [make_spot(f"CALL{i}", f"Country{i}", "20m") for i in range(30)]
hunt7, total7 = compute_hunt_list(
    spots7, set(), set(), {},
    user_lat=43.076112, user_lon=5.873671,
    calculate_bearing_fn=calculate_bearing,
    bearing_to_compass_fn=bearing_to_compass,
    is_rare_fn=is_rare_prefix,
    limit=15,
)
check("total_found == 30 (avant troncature)", total7 == 30)
check("hunt tronqué à 15", len(hunt7) == 15)


# ══════════════════════════════════════════════════════════════════
print("\n=== TEST 8 : liste vide (aucun spot actif) ===")

hunt8, total8 = compute_hunt_list(
    [], set(), set(), {},
    user_lat=43.076112, user_lon=5.873671,
    calculate_bearing_fn=calculate_bearing,
    bearing_to_compass_fn=bearing_to_compass,
    is_rare_fn=is_rare_prefix,
)
check("Liste vide -> hunt=[] et total=0", hunt8 == [] and total8 == 0)


# ══════════════════════════════════════════════════════════════════
print("\n=== TEST 9 : champs manquants dans le spot (robustesse) ===")

spots9 = [{"dx_call": "INCOMPLETE"}]  # pas de country/band/lat/lon/timestamp
try:
    hunt9, total9 = compute_hunt_list(
        spots9, set(), set(), {},
        user_lat=43.076112, user_lon=5.873671,
        calculate_bearing_fn=calculate_bearing,
        bearing_to_compass_fn=bearing_to_compass,
        is_rare_fn=is_rare_prefix,
    )
    check("Spot incomplet -> pas de crash, exclu (pas de country)", total9 == 0)
except Exception as e:
    check(f"Spot incomplet -> CRASH: {e}", False)


# ══════════════════════════════════════════════════════════════════
print("\n=== TEST 10 : exception dans calculate_bearing_fn ne casse pas tout ===")

def broken_bearing(*a, **kw):
    raise ValueError("simulated failure")

spots10 = [make_spot("X1", "Chad", "20m", lat=12.0, lon=15.0)]
try:
    hunt10, total10 = compute_hunt_list(
        spots10, set(), set(), {},
        user_lat=43.076112, user_lon=5.873671,
        calculate_bearing_fn=broken_bearing,
        bearing_to_compass_fn=bearing_to_compass,
        is_rare_fn=is_rare_prefix,
    )
    check("Exception bearing_fn -> pas de crash, bearing_deg=None", 
          total10 == 1 and hunt10[0]["bearing_deg"] is None)
except Exception as e:
    check(f"Exception bearing_fn -> CRASH: {e}", False)


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
