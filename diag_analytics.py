#!/usr/bin/env python3
"""
diag_analytics.py — Diagnostic de la chaîne d'analytique
=========================================================
À lancer depuis le répertoire de l'application :

    cd ~/Spot-Watcher-DX && python3 diag_analytics.py

Répond à une seule question : pourquoi la page AI Insight est-elle vide ?
Chaque point de la chaîne est vérifié séparément, du module jusqu'à la
réponse de l'API, de sorte que le maillon défaillant soit désigné plutôt
que deviné.

N'écrit rien et ne modifie rien : peut être lancé pendant que
l'application tourne.
"""

import json
import os
import sqlite3
import sys
import time

OK, KO, WARN, INFO = "\033[92m✓\033[0m", "\033[91m✗\033[0m", "\033[93m!\033[0m", "·"

problems = []
notes = []


def title(t):
    print(f"\n\033[1m{t}\033[0m")
    print("─" * 66)


def human_age(seconds):
    if seconds is None:
        return "—"
    if seconds < 90:
        return f"{int(seconds)} s"
    if seconds < 5400:
        return f"{seconds/60:.0f} min"
    if seconds < 172800:
        return f"{seconds/3600:.1f} h"
    return f"{seconds/86400:.1f} j"


print("\n" + "═" * 66)
print("  DIAGNOSTIC ANALYTIQUE — Neural DX Watcher")
print("═" * 66)
print(f"  Répertoire : {os.getcwd()}")
print(f"  Heure      : {time.strftime('%Y-%m-%d %H:%M:%S')}")

# ── 1. Le module est-il présent et importable ? ───────────────────────
title("1. Module analytics.py")

analytics = None
if not os.path.exists("analytics.py"):
    print(f"  {KO} analytics.py introuvable dans ce répertoire")
    problems.append("Copier analytics.py dans ~/Spot-Watcher-DX/")
else:
    print(f"  {OK} analytics.py présent")
    try:
        import analytics
        print(f"  {OK} import réussi")
        required = ["init_store", "record_spot", "store_status", "compute_all"]
        missing = [f for f in required if not hasattr(analytics, f)]
        if missing:
            print(f"  {KO} fonctions absentes : {', '.join(missing)}")
            problems.append("analytics.py est une version périmée — le remplacer")
        else:
            print(f"  {OK} version à jour (collecte autonome disponible)")
    except Exception as exc:
        print(f"  {KO} import impossible : {exc}")
        problems.append(f"Corriger l'import de analytics.py : {exc}")

# ── 2. La base d'analytique se remplit-elle ? ─────────────────────────
title("2. Base d'analytique (data/analytics.sqlite)")

own_rows = 0
own_span = 0.0
if analytics is None:
    print(f"  {WARN} ignoré (module non chargé)")
else:
    st = analytics.store_status()
    if not st["exists"]:
        print(f"  {KO} base absente : {st['path']}")
        print(f"      Elle est créée au démarrage de webapp.py.")
        problems.append(
            "webapp.py n'a pas créé la base : vérifier qu'il s'agit bien de "
            "la version v12.5 (chercher 'init_store' dedans) et le relancer")
    else:
        own_rows = st["rows"]
        own_span = st["span_hours"]
        print(f"  {OK} base présente")
        if own_rows == 0:
            print(f"  {KO} 0 ligne enregistrée")
            problems.append(
                "La base existe mais reste vide : webapp.py n'appelle pas "
                "analytics.record_spot() — vérifier que webapp.py est bien "
                "la version v12.5")
        else:
            print(f"  {OK} {own_rows:,} lignes, {own_span} h d'historique")
            age = time.time() - st["last_ts"] if st["last_ts"] else None
            if age is not None and age > 3600:
                print(f"  {WARN} dernière écriture il y a {human_age(age)}")
                problems.append(
                    "La collecte semble arrêtée : vérifier la connexion aux "
                    "clusters DX depuis la page d'accueil")
            else:
                print(f"  {OK} dernière écriture il y a {human_age(age)}")
        if st["write_errors"]:
            print(f"  {WARN} {st['write_errors']} erreurs d'écriture "
                  f"(dernière : {st['last_error']})")

# ── 3. La base du predictor (optionnelle) ─────────────────────────────
title("3. Base predictor (optionnelle)")

pred_path = "data/predictor.sqlite"
if not os.path.exists(pred_path):
    print(f"  {INFO} {pred_path} absente")
    print(f"      Sans conséquence : l'analytique tient sa propre base.")
else:
    try:
        conn = sqlite3.connect(f"file:{pred_path}?mode=ro", uri=True, timeout=3)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        print(f"  {INFO} tables : {', '.join(tables) if tables else '(aucune)'}")
        if "spot_log" in tables:
            n, first, last = conn.execute(
                "SELECT COUNT(*), MIN(ts), MAX(ts) FROM spot_log").fetchone()
            if n:
                span = (last - first) / 3600 if (first and last) else 0
                print(f"  {OK} spot_log : {n:,} lignes, {span:.1f} h")
            else:
                print(f"  {WARN} spot_log vide")
                notes.append(
                    "predictor.py ne collecte rien (module probablement "
                    "absent) — sans conséquence depuis la v12.5")
        else:
            print(f"  {WARN} pas de table spot_log")
        conn.close()
    except Exception as exc:
        print(f"  {WARN} lecture impossible : {exc}")

# ── 4. Que renvoie réellement le calcul ? ─────────────────────────────
title("4. Résultat du calcul")

if analytics is None:
    print(f"  {WARN} ignoré (module non chargé)")
else:
    try:
        t0 = time.perf_counter()
        data = analytics.compute_all()
        ms = (time.perf_counter() - t0) * 1000
        src = data.get("source") or "aucune"
        print(f"  {INFO} source retenue : {src}")
        print(f"  {INFO} calcul en {ms:.0f} ms")
        m = data.get("maturity", {})
        print(f"  {INFO} maturité : {m.get('label')} ({m.get('span_hours')} h)")

        any_ok = False
        for key, label in (("recent", "Activité récente"),
                           ("forecast", "Prochaines heures"),
                           ("heatmap", "Quand ça ouvre"),
                           ("patterns", "Tendances")):
            blk = data.get(key, {})
            if blk.get("available"):
                any_ok = True
                print(f"  {OK} {label}")
            else:
                print(f"  {INFO} {label} — en attente : {blk.get('reason', '?')}")

        if not any_ok:
            problems.append(
                "Aucune analyse disponible : il n'y a pas encore de spots "
                "collectés. Vérifier la réception sur la page d'accueil.")
    except Exception as exc:
        print(f"  {KO} le calcul a échoué : {exc}")
        problems.append(f"Erreur de calcul à investiguer : {exc}")

# ── 5. webapp.py est-il la bonne version ? ────────────────────────────
title("5. Intégration dans webapp.py")

if not os.path.exists("webapp.py"):
    print(f"  {KO} webapp.py introuvable — mauvais répertoire ?")
    problems.append("Se placer dans ~/Spot-Watcher-DX/")
else:
    src = open("webapp.py", encoding="utf-8", errors="ignore").read()
    checks = [
        ("import du module",      "import analytics as _analytics_mod"),
        ("création de la base",   "_analytics_mod.init_store()"),
        ("collecte des spots",    "_analytics_mod.record_spot(spot_obj)"),
        ("route /api/analytics",  '@app.route("/api/analytics")'),
        ("repli mémoire",         "memory_spots=memory_spots"),
    ]
    missing = []
    for label, needle in checks:
        if needle in src:
            print(f"  {OK} {label}")
        else:
            print(f"  {KO} {label}")
            missing.append(label)
    if missing:
        problems.append(
            "webapp.py n'est pas à jour (manque : " + ", ".join(missing) +
            ") — déployer la version v12.5")

# ── 6. La page est-elle déployée ? ────────────────────────────────────
title("6. Page ai_insight.html")

tpl = "templates/ai_insight.html"
if not os.path.exists(tpl):
    print(f"  {KO} {tpl} introuvable")
    problems.append("Copier ai_insight.html dans templates/")
else:
    html = open(tpl, encoding="utf-8", errors="ignore").read()
    if "maturity-bar" in html and "recentRenderer" in html:
        print(f"  {OK} version v12.5 (bandeau de maturité + activité récente)")
    else:
        print(f"  {KO} version antérieure")
        problems.append("Remplacer templates/ai_insight.html par la v12.5")

# ── Verdict ───────────────────────────────────────────────────────────
print("\n" + "═" * 66)
if not problems:
    print("  \033[92mAucun problème détecté.\033[0m")
    if own_rows:
        print(f"  Collecte active : {own_rows:,} spots, {own_span} h d'historique.")
        if own_span < 48:
            print(f"  La heatmap et les tendances s'activeront vers "
                  f"{max(0, 48 - own_span):.0f} h d'historique.")
    for n in notes:
        print(f"  {INFO} {n}")
else:
    print(f"  \033[91m{len(problems)} point(s) à corriger :\033[0m\n")
    for i, p in enumerate(problems, 1):
        print(f"   {i}. {p}")
print("═" * 66 + "\n")

sys.exit(1 if problems else 0)
