#!/usr/bin/env python3
"""bench_hf.py — compare le score actuel à des fréquences historiques simples (lecture seule).

Usage : python3 bench_hf.py [data/predictor.sqlite] [hf] [jours_de_reference=14]
Placer à côté de diag_hf.py (il importe auc et brier).

Chaque spot est chargé une seule fois, puis les recherches se font par recherche binaire :
le script reste rapide même avec plusieurs millions de lignes dans spot_log.
Sans fuite : pour une prévision créée à T, seules les fenêtres closes avant T servent de référence.
  A. score actuel du prédicteur
  B. fréquence (bande, préfixe, même heure) sur N jours, lissée (Laplace)
  C. fréquence (bande, même heure), tous préfixes confondus, lissée
"""
import sqlite3
import sys
from bisect import bisect_left, bisect_right
from collections import defaultdict
from diag_hf import auc, brier

DAY = 86400


def fit_isotonic(xs, ys):
    """PAVA : renvoie [(x_debut, valeur)] en escalier, croissant."""
    pts = sorted(zip(xs, ys))
    blocks = []  # [somme, nombre, x_debut]
    for x, y in pts:
        blocks.append([y, 1, x])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            s, c, x0 = blocks.pop()
            blocks[-1][0] += s
            blocks[-1][1] += c
    return [(b[2], b[0] / b[1]) for b in blocks]


def apply_isotonic(steps, x):
    xs0 = [s[0] for s in steps]
    i = bisect_right(xs0, x) - 1
    return steps[max(i, 0)][1]


def out_of_sample(res, y_all):
    """Calibre B sur les 70 % anciens, mesure sur les 30 % récents."""
    cut = int(len(res) * 0.7)
    train, test = res[:cut], res[cut:]
    if len(test) < 50:
        return
    ytr = [r[3] for r in train]
    yte = [r[3] for r in test]
    btr = sum(ytr) / len(ytr)
    bte = sum(yte) / len(yte)
    bbase_te = bte * (1 - bte)
    steps = fit_isotonic([r[2] for r in train], ytr)
    p_iso = [apply_isotonic(steps, r[2]) for r in test]
    print(f"\n=== Test hors échantillon (30 % les plus récents : {len(test)} prévisions) ===")
    print(f"Taux de réalisation test : {bte:.3f} | Brier de la base : {bbase_te:.4f}")
    print(f"{'candidat':<36}{'AUC':>7}{'Brier':>9}{'gain':>8}")
    for nom, p in (("A. score actuel", [r[0] for r in test]),
                   ("B. brut", [r[2] for r in test]),
                   ("B. isotonique (appris sur 70 %)", p_iso)):
        a = auc(p, yte)
        b = brier(p, yte)
        print(f"{nom:<36}{a:>7.3f}{b:>9.4f}{1 - b / bbase_te:>+8.2f}")
    print("Si « B. isotonique » a un gain > 0 hors échantillon, la fréquence historique est exploitable.")


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else "data/predictor.sqlite"
    model = sys.argv[2] if len(sys.argv) > 2 else "hf"
    back = int(sys.argv[3]) if len(sys.argv) > 3 else 14
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)

    print("Chargement des spots…", flush=True)
    by_key = defaultdict(list)   # (band, prefix) -> [ts triés]
    by_band = defaultdict(list)  # band -> [ts triés]
    for ts, band, prefix in con.execute(
            "SELECT ts, band, prefix FROM spot_log ORDER BY ts"):
        by_key[(band, prefix)].append(ts)
        by_band[band].append(ts)
    print(f"  {sum(map(len, by_band.values()))} spots chargés", flush=True)

    def hit(lst, a, b):
        """Vrai s'il existe un élément de lst dans [a, b]."""
        if not lst:
            return False
        i = bisect_left(lst, a)
        return i < len(lst) and lst[i] <= b

    rows = con.execute(
        "SELECT created_ts, predicted_score, realized, band, prefix, target_ts_start, target_ts_end "
        "FROM prediction_log WHERE verified=1 AND realized IS NOT NULL AND model=? "
        "ORDER BY created_ts", (model,)).fetchall()
    con.close()
    print(f"  {len(rows)} prévisions vérifiées à traiter", flush=True)

    res = []  # (score, p_B, p_C, y)
    for k, (created, score, y, band, prefix, s, e) in enumerate(rows, 1):
        if k % 2000 == 0:
            print(f"  {k}/{len(rows)}", flush=True)
        kl = by_key.get((band, prefix), [])
        bl = by_band.get(band, [])
        hb = hc = n = 0
        for d in range(1, back + 1):
            s2, e2 = s - d * DAY, e - d * DAY
            if e2 > created:      # fenêtre pas encore close à la création : fuite
                continue
            n += 1
            hb += hit(kl, s2, e2)
            hc += hit(bl, s2, e2)
        if n < 3:
            continue
        res.append((float(score), (hb + 1) / (n + 2), (hc + 1) / (n + 2), int(y)))

    if len(res) < 50:
        print(f"Pas assez de prévisions évaluables : {len(res)}")
        return
    out_of_sample(res, None)

    y = [r[3] for r in res]
    base = sum(y) / len(y)
    bbase = base * (1 - base)
    print(f"\n=== Benchmark « {model} » : {len(res)} prévisions évaluables (≥3 jours de référence) ===")
    print(f"Taux de réalisation : {base:.3f} | Brier de la base : {bbase:.4f}\n")
    print(f"{'candidat':<36}{'AUC':>7}{'Brier':>9}{'gain':>8}")
    best = None
    for idx, nom in ((0, "A. score actuel"),
                     (1, f"B. bande+préfixe+heure ({back} j)"),
                     (2, f"C. bande+heure, tous préfixes ({back} j)")):
        p = [r[idx] for r in res]
        a = auc(p, y)
        b = brier(p, y)
        gain = 1 - b / bbase if bbase > 0 else float('nan')
        print(f"{nom:<36}{a:>7.3f}{b:>9.4f}{gain:>+8.2f}")
        if idx > 0 and (best is None or (a, gain) > (best[1], best[2])):
            best = (nom, a, gain)

    print("\n--- Verdict ---")
    if best and best[1] > 0.6 and best[2] > 0:
        print(f"Un candidat simple bat le score actuel : {best[0]} "
              f"(AUC {best[1]:.3f}, gain {best[2]:+.2f}). À brancher dans le scoring HF.")
    else:
        print("Aucun candidat simple ne discrimine nettement. Le signal est faible avec ces données : "
              "afficher le taux de base pour HF, et chercher des variables supplémentaires "
              "(distance, direction, SFI historique).")


if __name__ == "__main__":
    main()
