#!/usr/bin/env python3
"""bench_physics.py — modèle physique HF validé par blocs temporels (lecture seule).

Hypothèses physiques :
  - la MUF dépend de l'élévation solaire aux DEUX extrémités du chemin et au milieu ;
  - l'effet dépend de la bande : hautes bandes = jour, basses bandes = nuit (interactions) ;
  - l'ionisation (SFI, Kp) module l'ouverture, surtout en hautes bandes.
Étiquette : y = 1 si au moins un spot reçu dans la fenêtre 3 h, pour (bande, préfixe).

Validation : 5 blocs temporels ; pour chaque bloc k≥2, entraînement sur les blocs précédents,
test sur le bloc k. Recalage de l'ordonnée à l'origine sur la fin de l'entraînement.
Décision : validé seulement si AUC > 0,6 ET gain > 0 sur TOUS les blocs testés.

Usage : python3 bench_physics.py data/predictor.sqlite cty.dat [min_spots=20]
Dossier du projet requis (bench_solar.py, diag_hf.py, dxcc_resolver.py, cty.dat).
"""
import bisect
import math
import random
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from bench_solar import solar_elevation, midpoint, make_coords, QTH_LAT, QTH_LON
from diag_hf import auc, brier

WIN = 3 * 3600
NEG_KEEP = 0.35      # sous-échantillonnage des négatifs (corrigé par le recalage)


def sigmoid(z):
    if z < -30:
        return 1e-13
    if z > 30:
        return 1 - 1e-13
    return 1 / (1 + math.exp(-z))


def band_group(band):
    digits = "".join(c for c in band if c.isdigit())
    m = int(digits) if digits else 20
    if m >= 40:
        return 0          # 160/80/40 m : nuit
    if m >= 17:
        return 1          # 30/20/17 m : transition
    return 2              # 15 m et plus haut : jour


def solve(H, g):
    """Résout H x = g (Gauss, pivot partiel)."""
    n = len(g)
    A = [row[:] + [g[i]] for i, row in enumerate(H)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(A[r][c]))
        A[c], A[p] = A[p], A[c]
        piv = A[c][c] or 1e-12
        for r in range(c + 1, n):
            f = A[r][c] / piv
            if f:
                for k in range(c, n + 1):
                    A[r][k] -= f * A[c][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        s = A[r][n] - sum(A[r][k] * x[k] for k in range(r + 1, n))
        x[r] = s / (A[r][r] or 1e-12)
    return x


def newton(X, y, lam=1.0, iters=10):
    """Régression logistique par Newton-Raphson, régularisation L2 (ordonnée exclue)."""
    d = len(X[0])
    w = [0.0] * d
    for _ in range(iters):
        g = [0.0] * d
        H = [[0.0] * d for _ in range(d)]
        for xi, yi in zip(X, y):
            p = sigmoid(sum(a * b for a, b in zip(w, xi)))
            e, v = p - yi, p * (1 - p)
            for j in range(d):
                g[j] += e * xi[j]
                vj = v * xi[j]
                Hj = H[j]
                for k in range(j, d):
                    Hj[k] += vj * xi[k]
        for j in range(d):
            for k in range(j):
                H[j][k] = H[k][j]
            if j > 0:
                g[j] += lam * w[j]
                H[j][j] += lam
        delta = solve(H, g)
        w = [a - b for a, b in zip(w, delta)]
        if max(abs(x) for x in delta) < 1e-6:
            break
    return w


def logit(p):
    return math.log(p / (1 - p))


def load_heartbeats(db):
    """Battements de présence du cluster (critère d'activité indépendant des spots)."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
    out = []
    for (tname,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        if not any(k in tname.lower() for k in ("heartbeat", "session", "uptime", "alive")):
            continue
        cols = [c[1].lower() for c in con.execute(f"PRAGMA table_info({tname})").fetchall()]
        tc = next((c for c in cols if c in ("ts", "ts_utc", "timestamp", "created_ts", "last_seen")), None)
        if not tc:
            continue
        vals = [float(r[0]) for r in con.execute(f"SELECT {tc} FROM {tname}").fetchall() if r[0] is not None]
        if vals:
            out = vals
            print(f"Présence du cluster : table {tname} ({len(vals)} battements)")
            break
    con.close()
    return out


def main(db, cty, min_spots):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
    spots = con.execute("SELECT ts, band, prefix FROM spot_log WHERE prefix IS NOT NULL").fetchall()
    # table de mesures solaires : première table qui a ts + sfi (et kp si présent)
    solar = []
    for (tname,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        cols = [c[1].lower() for c in con.execute(f"PRAGMA table_info({tname})").fetchall()]
        ts_c = next((c for c in cols if c in ("ts", "ts_utc", "timestamp", "created_ts")), None)
        sfi_c = next((c for c in cols if "sfi" in c), None)
        kp_c = next((c for c in cols if c == "kp" or c.startswith("kp")), None)
        if ts_c and sfi_c:
            q = f"SELECT {ts_c}, {sfi_c}, {kp_c if kp_c else 'NULL'} FROM {tname} ORDER BY {ts_c}"
            solar = [(float(t), float(s), float(k) if k is not None else None)
                     for t, s, k in con.execute(q).fetchall() if s is not None]
            if solar:
                print(f"Mesures solaires : table {tname} ({len(solar)} lignes)")
                break
    con.close()
    if not solar:
        print("Aucune mesure SFI enregistrée : modèle sans ionisation (lacune à corriger dans le prédicteur).")
    st_ts = [s[0] for s in solar]

    def solar_at(ts):
        if not solar:
            return None, None
        i = bisect.bisect_left(st_ts, ts)
        cands = [j for j in (i - 1, i) if 0 <= j < len(solar)]
        j = min(cands, key=lambda j: abs(st_ts[j] - ts))
        return solar[j][1], solar[j][2]

    if not spots:
        print("spot_log vide.")
        return
    coords = make_coords(cty)
    count, pos = defaultdict(int), set()
    wmin = wmax = None
    for ts, band, prefix in spots:
        w = int(ts // WIN)
        count[(band, prefix)] += 1
        pos.add((band, prefix, w))
        wmin = w if wmin is None else min(wmin, w)
        wmax = w if wmax is None else max(wmax, w)
    pairs = [k for k, c in count.items() if c >= min_spots]
    win_total = defaultdict(int)
    for ts, _b, _p in spots:
        win_total[int(ts // WIN)] += 1
    hb = load_heartbeats(db)
    lo_w, hi_w = min(win_total), max(win_total)
    if hb:
        active = {int(t // WIN) for t in hb if lo_w <= int(t // WIN) <= hi_w}
        print(f"Fenêtres avec cluster présent : {len(active)} / {hi_w - lo_w + 1}")
    else:
        med = sorted(win_total.values())[len(win_total) // 2] if win_total else 0
        thr = max(10, 0.05 * med)
        active = {w for w, c in win_total.items() if c >= thr}
        print("⚠ Aucune table de présence du cluster : critère basé sur les spots (biais possible, "
              "à remplacer par des battements de présence).")
        print(f"Fenêtres actives (≥{thr:.0f} spots) : {len(active)} / {len(win_total)}")
    if len(active) < 50:
        print("Trop peu de fenêtres actives pour valider.")
        return
    aw = sorted(active)
    wmin, wmax = aw[0], aw[-1]

    rows = []
    cache = {}
    for band, prefix in pairs:
        if prefix not in cache:
            cache[prefix] = coords(prefix)
        c = cache[prefix]
        if c is None:
            continue
        mlat, mlon = midpoint(QTH_LAT, QTH_LON, c[0], c[1])
        g = band_group(band)
        for w in aw:
            t = w * WIN + WIN / 2
            d = datetime.fromtimestamp(t, tz=timezone.utc)
            el_mid = solar_elevation(mlat, mlon, t)
            el_qth = solar_elevation(QTH_LAT, QTH_LON, t)
            el_dx = solar_elevation(c[0], c[1], t)
            sfi, kp = solar_at(t)
            rows.append(dict(w=w, band=band, prefix=prefix, g=g, em=el_mid,
                             ee=min(el_qth, el_dx), sfi=sfi, kp=kp,
                             h=d.hour + d.minute / 60, y=1 if (band, prefix, w) in pos else 0))
    print(f"{len(spots)} spots, {len(pairs)} couples ≥ {min_spots} spots, "
          f"{wmax - wmin + 1} fenêtres, {len(rows)} lignes étiquetées")
    if len(rows) < 1000:
        print("Pas assez de données.")
        return
    has_sfi = all(r["sfi"] is not None for r in rows)
    rows.sort(key=lambda r: r["w"])

    def base_feats(r, te_val, model):
        ang = 2 * math.pi * r["h"] / 24
        if model == "A":   # une seule pente, sans bande ni ionisation
            return [1.0, r["em"] / 90, math.cos(ang), math.sin(ang)]
        if model == "D":   # popularité + heure, sans physique
            return [1.0, math.cos(ang), math.sin(ang), te_val]
        x = [1.0]
        x += [r["em"] / 90 * (r["g"] == k) for k in range(3)]
        x += [r["ee"] / 90 * (r["g"] == k) for k in range(3)]
        x += [math.cos(ang), math.sin(ang)]
        if has_sfi:
            sc = (r["sfi"] - 100) / 30
            x += [sc, sc * (r["g"] == 2), (r["kp"] or 2) / 9]
        if model == "B":
            x.append(te_val)
        return x

    def fold(k, nb=5):
        nw = len(aw)
        i_tr, i_te = int(nw * k / nb), int(nw * (k + 1) / nb)
        cut_tr = aw[i_tr] if i_tr < nw else wmax + 1
        cut_te = aw[i_te] if i_te < nw else wmax + 1
        tail_w = aw[int(i_tr * 0.8)] if i_tr > 0 else cut_tr
        train = [r for r in rows if r["w"] < cut_tr]
        test = [r for r in rows if cut_tr <= r["w"] < cut_te]
        if len(train) < 1000 or len(test) < 500:
            return None
        ytr = [r["y"] for r in train]
        base_tr = sum(ytr) / len(ytr)
        if base_tr <= 0 or base_tr >= 1:
            print(f"  bloc {k+1} ignoré : pas de positifs ou pas de négatifs dans l'entraînement")
            return None
        hits, n = defaultdict(int), defaultdict(int)
        for r in train:
            key = (r["band"], r["prefix"])
            n[key] += 1
            hits[key] += r["y"]
        m = 20.0

        def te(r):
            key = (r["band"], r["prefix"])
            p = (hits[key] + m * base_tr) / (n[key] + m)
            return logit(p) - logit(base_tr)

        rnd = random.Random(k)
        sub = [r for r in train if r["y"] == 1 or rnd.random() < NEG_KEEP]
        models = {}
        for name in ("A", "B", "C", "D"):
            Xs = [base_feats(r, te(r), name) for r in sub]
            ys = [r["y"] for r in sub]
            d = len(Xs[0])
            mu = [0.0] * d
            sd = [1.0] * d
            for j in range(1, d):
                vals = [x[j] for x in Xs]
                mu[j] = sum(vals) / len(vals)
                sd[j] = (sum((v - mu[j]) ** 2 for v in vals) / len(vals)) ** 0.5 or 1.0
            Xz = [[x[0]] + [(x[j] - mu[j]) / sd[j] for j in range(1, d)] for x in Xs]
            w = newton(Xz, ys)
            # recalage de l'ordonnée sur la fin de l'entraînement, données complètes
            tail = [r for r in train if r["w"] >= tail_w]
            tgt = sum(r["y"] for r in tail) / len(tail)
            Xt = [[1.0] + [(base_feats(r, te(r), name)[j] - mu[j]) / sd[j] for j in range(1, d)] for r in tail]
            lo, hi = -10.0, 10.0
            for _ in range(50):
                mid = (lo + hi) / 2
                ww = [w[0] + mid] + w[1:]
                pm = sum(sigmoid(sum(a * b for a, b in zip(ww, x))) for x in Xt) / len(Xt)
                lo, hi = (mid, hi) if pm < tgt else (lo, mid)
            w[0] += (lo + hi) / 2
            Xte = [[1.0] + [(base_feats(r, te(r), name)[j] - mu[j]) / sd[j] for j in range(1, d)] for r in test]
            models[name] = [sigmoid(sum(a * b for a, b in zip(w, x))) for x in Xte]

        yte = [r["y"] for r in test]
        base_te = sum(yte) / len(yte)
        bbase = base_te * (1 - base_te)
        pbase = [base_tr] * len(test)
        return dict(k=k, n=len(test), rate=base_te, bbase=bbase, yte=yte,
                    base=pbase, A=models["A"], B=models["B"], C=models["C"], D=models["D"])

    results = [f for f in (fold(k) for k in range(1, 5)) if f]
    if not results:
        print("Pas assez de blocs pour valider.")
        return
    print("\nBloc | n test | taux | A 1 pente | B complet | C sans taux | D taux+heure | gain B")
    ok_b = ok_phys = 0
    for f in results:
        aA, aB, aC, aD = (auc(f[x], f["yte"]) for x in ("A", "B", "C", "D"))
        gB = 1 - brier(f["B"], f["yte"]) / f["bbase"]
        print(f"  {f['k']+1}   | {f['n']:>6} | {f['rate']:.3f} | {aA:.3f}     | {aB:.3f}     | {aC:.3f}       | {aD:.3f}        | {gB:+.2f}")
        if aB > 0.6 and gB > 0:
            ok_b += 1
        if aB > aD + 0.05 and aC > 0.6:
            ok_phys += 1
    n = len(results)
    print("\n--- Verdict ---")
    if ok_b == n and ok_phys == n:
        print(f"VALIDÉ : modèle complet AUC > 0,6 et gain > 0 sur {n} blocs ; l'élévation apporte au-delà "
              f"de la popularité et de l'heure ; le modèle tient sans le taux historique.")
    else:
        print(f"NON VALIDÉ : complet OK sur {ok_b}/{n} blocs ; apport physique au-delà de (taux+heure) "
              f"sur {ok_phys}/{n} blocs. Le signal vient probablement de la popularité, pas de la physique.")


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "data/predictor.sqlite"
    cty = sys.argv[2] if len(sys.argv) > 2 else "cty.dat"
    mins = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    main(db, cty, mins)
