#!/usr/bin/env python3
"""diag_hf.py — diagnostic de calibration (lecture seule).

Usage : python3 diag_hf.py [data/predictor.sqlite] [hf|es|tropo]

Répond à trois questions :
  1. Le score discrimine-t-il ? (AUC : 0,5 = pile ou face, 1 = parfait)
  2. Une recalibration (isotonique, ajustée sur la période ancienne, testée
     sur la période récente) bat-elle le taux de base hors échantillon ?
  3. Les données elles-mêmes sont-elles saines ? (fenêtres silencieuses
     comptées à tort comme « non réalisées », préfixes incohérents, échantillon
     réellement indépendant)
"""
import sqlite3
import sys


def load(db, model):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT created_ts, predicted_score, realized, band, prefix, target_ts_start "
        "FROM prediction_log WHERE verified=1 AND realized IS NOT NULL AND model=? "
        "ORDER BY created_ts", (model,)).fetchall()
    silent = con.execute(
        "SELECT COUNT(*) FROM prediction_log p WHERE verified=1 AND model=? AND realized=0 "
        "AND NOT EXISTS (SELECT 1 FROM spot_log s "
        "WHERE s.ts BETWEEN p.target_ts_start AND p.target_ts_end)", (model,)).fetchone()[0]
    mismatch = con.execute(
        "SELECT COUNT(DISTINCT prefix) FROM prediction_log WHERE model=? "
        "AND prefix NOT IN (SELECT prefix FROM spot_log)", (model,)).fetchone()[0]
    con.close()
    return rows, silent, mismatch


def auc(scores, labels):
    """Aire sous la courbe ROC (Mann-Whitney), gère les ex-aequo."""
    pos = sum(labels)
    neg = len(labels) - pos
    if pos == 0 or neg == 0:
        return None
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    sum_pos = sum(r for r, y in zip(ranks, labels) if y)
    return (sum_pos - pos * (pos + 1) / 2) / (pos * neg)


def isotonic_fit(scores, labels):
    """Régression isotonique (Pool Adjacent Violators). Renvoie des blocs (lo, hi, valeur)."""
    blocks = []  # [somme_y, n, lo, hi]
    for s, y in sorted(zip(scores, labels)):
        blocks.append([y, 1, s, s])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            b = blocks.pop()
            a = blocks[-1]
            a[0] += b[0]
            a[1] += b[1]
            a[3] = b[3]
    return [(b[2], b[3], b[0] / b[1]) for b in blocks]


def iso_predict(model, s):
    for lo, hi, v in model:
        if s <= hi:
            return v
    return model[-1][2]


def brier(preds, labels):
    return sum((p - y) ** 2 for p, y in zip(preds, labels)) / len(labels)


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else "data/predictor.sqlite"
    model = sys.argv[2] if len(sys.argv) > 2 else "hf"
    rows, silent, mismatch = load(db, model)
    n = len(rows)
    if n < 50:
        print(f"Pas assez de lignes vérifiées pour « {model} » : {n}")
        return

    scores = [float(r[1]) for r in rows]
    labels = [int(r[2]) for r in rows]
    base = sum(labels) / n
    print(f"=== Calibration « {model} » : {n} prévisions vérifiées ===")
    print(f"Taux de réalisation : {base:.3f} | Brier de la base : {base * (1 - base):.4f}")
    print(f"Brier brut (score tel quel) : {brier(scores, labels):.4f}")

    a = auc(scores, labels)
    print(f"AUC (discrimination) : {a:.3f}" if a is not None else "AUC : indéterminée")

    # Découpage temporel : 70 % ancien pour ajuster, 30 % récent pour tester
    k = int(0.7 * n)
    tr_s, tr_y, te_s, te_y = scores[:k], labels[:k], scores[k:], labels[k:]
    iso = isotonic_fit(tr_s, tr_y)
    p_iso = [iso_predict(iso, s) for s in te_s]
    p_base = [sum(tr_y) / len(tr_y)] * len(te_y)
    b_raw = brier(te_s, te_y)
    b_iso = brier(p_iso, te_y)
    b_base = brier(p_base, te_y)
    print("\n--- Hors échantillon (30 % les plus récents) ---")
    print(f"Brier score brut     : {b_raw:.4f}")
    print(f"Brier isotonique     : {b_iso:.4f}")
    print(f"Brier taux de base   : {b_base:.4f}")

    print("\n--- Courbe de fiabilité (10 tranches) ---")
    print("tranche        n     prédit  observé")
    for t in range(10):
        lo, hi = t / 10, (t + 1) / 10
        idx = [i for i, s in enumerate(scores) if lo <= s < hi or (t == 9 and s == 1.0)]
        if not idx:
            continue
        pm = sum(scores[i] for i in idx) / len(idx)
        om = sum(labels[i] for i in idx) / len(idx)
        print(f"{lo:.1f}-{hi:.1f} {len(idx):>7}   {pm:.3f}   {om:.3f}")

    # Taille d'échantillon réellement indépendante : une même paire
    # (bande, préfixe) sur une même journée compte pour une seule observation.
    eff = len({(r[3], r[4], int(r[5] // 86400)) for r in rows})
    print("\n--- Qualité des données ---")
    print(f"Observations indépendantes approx. (bande, préfixe, jour) : {eff} sur {n}")
    print(f"Fenêtres sans aucun spot comptées « non réalisées » : {silent}")
    print(f"Préfixes absents de spot_log (risque de faux négatifs) : {mismatch}")

    print("\n--- Verdict ---")
    if a is None:
        print("Données insuffisantes.")
    elif a < 0.6:
        print("Le score discrimine peu (AUC < 0,6) : une recalibration seule ne suffira pas. "
              "Il faut revoir le modèle (le prédicteur doit mieux classer les préfixes).")
    elif b_iso < min(b_raw, b_base):
        print("La recalibration isotonique bat le score brut et le taux de base hors échantillon : "
              "elle est utile, à brancher dans le scoring.")
    else:
        print("Aucun gain hors échantillon par recalibration : afficher le taux de base, "
              "et traiter le modèle lui-même.")


if __name__ == "__main__":
    main()
