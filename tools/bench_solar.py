#!/usr/bin/env python3
"""bench_solar.py — test physique : élévation solaire au point milieu QTH→cible (lecture seule).

Usage : python3 bench_solar.py [data/predictor.sqlite] [hf] [cty.dat]
À lancer depuis le dossier du projet (importe diag_hf.py et dxcc_resolver.py).

Pour chaque prévision vérifiée :
  - coordonnées de la cible via dxcc_resolver (préfixe -> lat/lon, cty.dat)
  - point milieu du grand cercle QTH -> cible
  - élévation du soleil au point milieu, à l'instant moyen de la fenêtre cible
Sans fuite : les paliers (bins) sont appris sur les 70 % les plus anciens, mesurés sur les 30 % récents.
"""
import math
import sqlite3
import sys
from bisect import bisect_right
from datetime import datetime, timezone
from diag_hf import auc, brier

QTH_LAT, QTH_LON = 43.075703, 5.873444
EDGES = list(range(-90, 91, 15))   # paliers de 15° d'élévation solaire


def solar_elevation(lat, lon, ts):
    """Élévation du soleil (degrés) — formule approchée, précision ~1°."""
    d = datetime.fromtimestamp(ts, timezone.utc)
    doy = d.timetuple().tm_yday
    utc_h = d.hour + d.minute / 60 + d.second / 3600
    B = math.radians(360 / 365 * (doy - 81))
    eot = 9.87 * math.sin(2 * B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)  # minutes
    decl = math.radians(-23.44 * math.cos(math.radians(360 / 365 * (doy + 10))))
    solar_time = utc_h + lon / 15 + eot / 60
    H = math.radians(15 * (solar_time - 12))
    la = math.radians(lat)
    s = math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(H)
    return math.degrees(math.asin(max(-1.0, min(1.0, s))))


def midpoint(lat1, lon1, lat2, lon2):
    """Point milieu du grand cercle entre deux positions."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    l1 = math.radians(lon1)
    dl = math.radians(lon2 - lon1)
    bx = math.cos(p2) * math.cos(dl)
    by = math.cos(p2) * math.sin(dl)
    lat = math.atan2(math.sin(p1) + math.sin(p2),
                     math.sqrt((math.cos(p1) + bx) ** 2 + by ** 2))
    lon = l1 + math.atan2(by, math.cos(p1) + bx)
    return math.degrees(lat), (math.degrees(lon) + 540) % 360 - 180


def make_coords(cty):
    """Retourne une fonction prefix -> (lat, lon) ou None, via dxcc_resolver."""
    from dxcc_resolver import get_resolver
    r = get_resolver(cty)

    def coords(prefix):
        d = r.resolve(prefix)
        if not d or d.get("lat") is None or d.get("lon") is None:
            return None
        return float(d["lat"]), float(d["lon"])
    return coords


def bin_index(x):
    return max(0, min(len(EDGES) - 2, bisect_right(EDGES, x) - 1))


def main(db, model, coords):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
    rows = con.execute(
        "SELECT created_ts, target_ts_start, target_ts_end, prefix, predicted_score, realized "
        "FROM prediction_log WHERE verified=1 AND realized IS NOT NULL AND model=? "
        "ORDER BY created_ts", (model,)).fetchall()
    con.close()

    data, skipped = [], 0
    cache = {}
    for created, s, e, prefix, score, y in rows:
        if prefix not in cache:
            cache[prefix] = coords(prefix)
        c = cache[prefix]
        if c is None:
            skipped += 1
            continue
        mlat, mlon = midpoint(QTH_LAT, QTH_LON, c[0], c[1])
        elev = solar_elevation(mlat, mlon, (s + e) / 2)
        data.append((elev, float(score), int(y)))
    print(f"{len(data)} prévisions avec coordonnées, {skipped} ignorées (préfixe inconnu)")
    if len(data) < 100:
        print("Pas assez de données.")
        return

    cut = int(len(data) * 0.7)
    train, test = data[:cut], data[cut:]
    ytr = [d[2] for d in train]
    yte = [d[2] for d in test]
    bte = sum(yte) / len(yte)
    bbase = bte * (1 - bte)

    # paliers appris sur l'ancien échantillon (Laplace)
    nb = len(EDGES) - 1
    hits, cnt = [0] * nb, [0] * nb
    for el, _, y in train:
        i = bin_index(el)
        cnt[i] += 1
        hits[i] += y
    rate = [(hits[i] + 1) / (cnt[i] + 2) for i in range(nb)]
    base_tr = sum(ytr) / len(ytr)
    rate = [r if cnt[i] >= 8 else base_tr for i, r in enumerate(rate)]

    print("\nPaliers appris (70 % anciens) : élévation solaire -> taux observé")
    for i in range(nb):
        print(f"  {EDGES[i]:>4}..{EDGES[i+1]:<4}°  {rate[i]*100:5.1f}%  n={cnt[i]}")

    p_bin = [rate[bin_index(d[0])] for d in test]
    p_elev = [d[0] for d in test]
    p_A = [d[1] for d in test]
    print(f"\n=== Hors échantillon : {len(test)} prévisions, taux réalisé {bte:.3f}, base Brier {bbase:.4f} ===")
    print(f"{'candidat':<40}{'AUC':>7}{'Brier':>9}{'gain':>8}")
    for nom, p in (("A. score actuel", p_A),
                   ("E. élévation solaire (brute, ordre)", p_elev),
                   ("E. élévation solaire (paliers calibrés)", p_bin)):
        a = auc(p, yte)
        b = brier(p, yte) if max(p) <= 1 else float("nan")
        g = 1 - b / bbase if bbase > 0 and b == b else float("nan")
        print(f"{nom:<40}{a:>7.3f}{b:>9.4f}{g:>+8.2f}")
    a_e = auc(p_elev, yte)
    g_bin = 1 - brier(p_bin, yte) / bbase
    print("\n--- Verdict ---")
    if a_e > 0.6 and g_bin > 0:
        print(f"Signal physique confirmé hors échantillon (AUC {a_e:.3f}, gain paliers {g_bin:+.2f}). À intégrer au scoring HF.")
    else:
        print(f"Pas de signal physique suffisant (AUC {a_e:.3f}, gain paliers {g_bin:+.2f}). Garder l'affichage taux de base pour HF.")


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "data/predictor.sqlite"
    model = sys.argv[2] if len(sys.argv) > 2 else "hf"
    cty = sys.argv[3] if len(sys.argv) > 3 else "cty.dat"
    main(db, model, make_coords(cty))
