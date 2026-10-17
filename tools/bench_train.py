#!/usr/bin/env python3
"""bench_train.py — entraînement sur TOUTES les fenêtres étiquetées depuis spot_log (lecture seule).

Idée : le modèle actuel n'apprend que des 5 prévisions émises (échantillon biaisé).
Ici chaque fenêtre de 3 h × (bande, préfixe) reçoit une étiquette réelle :
  y = 1 si au moins un spot a été reçu dans la fenêtre, 0 sinon.
Variables :
  - élévation solaire au point milieu du chemin QTH -> cible
  - heure UTC (encodage cos/sin) ; saison retirée (trop peu de jours pour l'estimer)
  - taux historique du couple (bande, préfixe), appris UNIQUEMENT sur le passé (70 %)
Validation : régression logistique entraînée sur les 70 % anciennes fenêtres,
mesurée sur les 30 % récentes. Comparée à la base et à une version sans taux historique.

Usage : python3 bench_train.py data/predictor.sqlite cty.dat [min_spots=20]
À lancer dans le dossier du projet (dxcc_resolver.py, cty.dat, bench_solar.py, diag_hf.py).
"""
import math
import random
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from bench_solar import solar_elevation, midpoint, make_coords, QTH_LAT, QTH_LON
from diag_hf import auc, brier

WIN = 3 * 3600


def sigmoid(z):
    if z < -30:
        return 1e-13
    if z > 30:
        return 1 - 1e-13
    return 1 / (1 + math.exp(-z))


def fit_logistic(X, y, epochs=6, lr=0.05, l2=1e-5, seed=1):
    """Régression logistique par descente de gradient stochastique."""
    w = [0.0] * len(X[0])
    idx = list(range(len(X)))
    rnd = random.Random(seed)
    for _ in range(epochs):
        rnd.shuffle(idx)
        for i in idx:
            xi, yi = X[i], y[i]
            g = sigmoid(sum(a * b for a, b in zip(w, xi))) - yi
            for j in range(len(w)):
                w[j] -= lr * (g * xi[j] + l2 * w[j])
    return w


def predict(w, X):
    return [sigmoid(sum(a * b for a, b in zip(w, xi))) for xi in X]


def main(db, cty, min_spots):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
    spots = con.execute("SELECT ts, band, prefix FROM spot_log WHERE prefix IS NOT NULL").fetchall()
    con.close()
    if not spots:
        print("spot_log vide.")
        return
    coords = make_coords(cty)

    count = defaultdict(int)
    pos = set()
    wmin = wmax = None
    for ts, band, prefix in spots:
        w = int(ts // WIN)
        count[(band, prefix)] += 1
        pos.add((band, prefix, w))
        wmin = w if wmin is None else min(wmin, w)
        wmax = w if wmax is None else max(wmax, w)

    pairs = [k for k, c in count.items() if c >= min_spots]
    cache = {}
    rows = []  # (window_index, band, prefix, elev, hour, doy, y)
    for prefix_band in pairs:
        band, prefix = prefix_band
        if prefix not in cache:
            cache[prefix] = coords(prefix)
        c = cache[prefix]
        if c is None:
            continue
        mlat, mlon = midpoint(QTH_LAT, QTH_LON, c[0], c[1])
        for w in range(wmin, wmax + 1):
            centre = w * WIN + WIN / 2
            d = datetime.fromtimestamp(centre, tz=timezone.utc)
            el = solar_elevation(mlat, mlon, centre)
            rows.append((w, band, prefix, el, d.hour + d.minute / 60, d.timetuple().tm_yday,
                         1 if (band, prefix, w) in pos else 0))
    print(f"{len(spots)} spots, {len(pairs)} couples (bande, préfixe) ≥ {min_spots} spots, "
          f"{wmax - wmin + 1} fenêtres de 3 h, {len(rows)} lignes étiquetées")
    if len(rows) < 1000:
        print("Pas assez de données.")
        return

    rows.sort(key=lambda r: r[0])

    def run(frac):
        """Entraîne sur les `frac` premières fenêtres, teste sur le reste."""
        cut_w = wmin + int(frac * (wmax - wmin))
        train = [r for r in rows if r[0] < cut_w]
        test = [r for r in rows if r[0] >= cut_w]
        if len(train) < 1000 or len(test) < 1000:
            return None
        hits, n = defaultdict(int), defaultdict(int)
        for r in train:
            n[(r[1], r[2])] += 1
            hits[(r[1], r[2])] += r[6]
        ytr = [r[6] for r in train]
        yte = [r[6] for r in test]
        base_tr = sum(ytr) / len(ytr)
        base_te = sum(yte) / len(yte)
        bbase = base_te * (1 - base_te)
        prior = math.log(base_tr / (1 - base_tr))

        def te(r):
            k = (r[1], r[2])
            p = (hits[k] + 1) / (n[k] + 2)   # taux lissé, appris sur le passé uniquement
            return math.log(p / (1 - p)) - prior

        # saisonnalité volontairement absente : trop peu de jours pour l'estimer
        def feats(r, with_te):
            ang_h = 2 * math.pi * r[4] / 24
            x = [1.0, r[3] / 90, math.cos(ang_h), math.sin(ang_h)]
            if with_te:
                x.append(te(r))
            return x

        Xtr_no = [feats(r, False) for r in train]
        Xtr_full = [feats(r, True) for r in train]
        w_no = fit_logistic(Xtr_no, ytr)
        w_full = fit_logistic(Xtr_full, ytr)

        # recalage de l'ordonnée à l'origine : la moyenne prédite sur la fin du passé
        # doit égaler le taux observé sur cette même fin (dérive du taux de base)
        tail = int(0.8 * len(train))
        def recal(w, X):
            lo, hi = -10.0, 10.0
            target = sum(ytr[tail:]) / max(1, len(ytr[tail:]))
            for _ in range(60):
                mid = (lo + hi) / 2
                ww = list(w); ww[0] += mid
                m = sum(predict(ww, X[tail:])) / max(1, len(X[tail:]))
                if m < target: lo = mid
                else: hi = mid
            ww = list(w); ww[0] += (lo + hi) / 2
            return ww

        w_full_r = recal(w_full, Xtr_full)
        Xte_no = [feats(r, False) for r in test]
        Xte_full = [feats(r, True) for r in test]
        out = {
            "base": [base_tr] * len(test),
            "elev_heure": predict(w_no, Xte_no),
            "full": predict(w_full, Xte_full),
            "full_recal": predict(w_full_r, Xte_full),
        }
        return yte, bbase, base_te, out, w_full

    print(f"\nDécoupes temporelles (passé -> test) :")
    result = None
    for frac in (0.5, 0.6, 0.7):
        res = run(frac)
        if res is None:
            print(f"  {frac:.0%} : données insuffisantes")
            continue
        yte, bbase, base_te, out, w_full = res
        print(f"\n=== Passé {frac:.0%} / test {1-frac:.0%} : {len(yte)} lignes, taux réalisé {base_te:.3f}, base Brier {bbase:.4f} ===")
        print(f"{'modèle':<40}{'AUC':>7}{'Brier':>9}{'gain':>8}")
        for nom, key in (("0. base (taux du passé)", "base"),
                         ("1. élévation + heure", "elev_heure"),
                         ("2. ... + taux historique", "full"),
                         ("3. ... recalé sur la fin du passé", "full_recal")):
            p = out[key]
            a = auc(p, yte)
            b = brier(p, yte)
            print(f"{nom:<40}{a:>7.3f}{b:>9.4f}{1 - b / bbase:>+8.2f}")
        result = (frac, yte, bbase, out)

    if result is None:
        print("Pas assez de données pour une découpe fiable.")
        return
    print("\n--- Verdict (découpe 70/30, modèle 3) ---")
    frac, yte, bbase, out = result
    a3 = auc(out["full_recal"], yte)
    g3 = 1 - brier(out["full_recal"], yte) / bbase
    if a3 > 0.6 and g3 > 0:
        print(f"Exploitable hors échantillon (AUC {a3:.3f}, gain {g3:+.2f}). Candidat pour le scoring HF.")
    else:
        print(f"Pas de gain hors échantillon (AUC {a3:.3f}, gain {g3:+.2f}). Vérifier la stabilité sur les 3 découpes.")


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "data/predictor.sqlite"
    cty = sys.argv[2] if len(sys.argv) > 2 else "cty.dat"
    mins = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    main(db, cty, mins)
