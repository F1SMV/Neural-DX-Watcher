"""Diagnostic mémoire de la webapp (v14) : la croissance nocturne a-t-elle disparu ?

Lit un journal produit sur le Pi par :
    while true; do echo "$(date -u +%FT%TZ) $(ps -o rss= -p $(pgrep -f webapp.py | head -1))"; sleep 300; done > rss_nuit.log

Usage (depuis la racine du projet) :
    python3 tools/diag_memory.py rss_nuit.log

Pour chaque nuit, compare le RSS juste avant le cycle nocturne (03:00 UTC) au RSS une
heure après. Référence v13 : +17 à +18 Mo par nuit. Seuil v14 : moins de 5 Mo.
"""
import sys
from datetime import datetime, timedelta, timezone

CYCLE_HOUR_UTC = 3          # adaptive/nightly_cycle.py est lancé à 03:00 UTC
SETTLE_MIN = 60             # mesure « après » : 60 min après le début du cycle
MAX_GAP_MIN = 30            # un point à plus de 30 min de l'instant visé est ignoré
THRESHOLD_MB = 5.0
RSS_CEILING_MB = 200.0      # plafond retenu à la clôture de la phase 0


def parse_log(lines):
    """Renvoie [(datetime UTC, RSS en Mo)], lignes illisibles ignorées (processus arrêté)."""
    points = []
    for line in lines:
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            ts = datetime.strptime(parts[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            rss_kb = int(parts[1])
        except ValueError:
            continue
        if rss_kb > 0:
            points.append((ts, rss_kb / 1024.0))
    points.sort()
    return points


def _nearest(points, target):
    best = min(points, key=lambda p: abs(p[0] - target), default=None)
    if best is None or abs(best[0] - target) > timedelta(minutes=MAX_GAP_MIN):
        return None
    return best


def nightly_deltas(points):
    """Renvoie [(date du cycle, RSS avant, RSS après, écart)] pour chaque nuit couverte."""
    out = []
    if not points:
        return out
    day = points[0][0].replace(hour=CYCLE_HOUR_UTC, minute=0, second=0, microsecond=0)
    while day <= points[-1][0]:
        before = _nearest([p for p in points if p[0] <= day], day - timedelta(minutes=5))
        after = _nearest([p for p in points if p[0] > day], day + timedelta(minutes=SETTLE_MIN))
        # Un redémarrage entre les deux mesures fausserait l'écart : le RSS chute fortement.
        if before and after and after[1] > before[1] * 0.7:
            out.append((day.date().isoformat(), before[1], after[1], after[1] - before[1]))
        day += timedelta(days=1)
    return out


def verdict(deltas):
    """« ok », « croissance » ou « insuffisant » (moins d'une nuit mesurée)."""
    if not deltas:
        return "insuffisant"
    return "ok" if all(d[3] < THRESHOLD_MB for d in deltas) else "croissance"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__)
        return 2
    try:
        with open(argv[0], encoding="utf-8", errors="replace") as f:
            points = parse_log(f)
    except OSError as exc:
        print(f"Journal illisible : {exc}")
        return 2
    if not points:
        print("Aucune mesure exploitable dans le journal.")
        return 1
    print(f"{len(points)} mesures, du {points[0][0]:%Y-%m-%d %H:%M} au {points[-1][0]:%Y-%m-%d %H:%M} UTC")
    print(f"RSS : début {points[0][1]:.0f} Mo, fin {points[-1][1]:.0f} Mo, "
          f"maximum {max(p[1] for p in points):.0f} Mo (plafond {RSS_CEILING_MB:.0f} Mo)")
    deltas = nightly_deltas(points)
    for day, before, after, delta in deltas:
        print(f"  cycle du {day} : {before:.0f} Mo -> {after:.0f} Mo ({delta:+.1f} Mo)")
    v = verdict(deltas)
    if v == "insuffisant":
        print("Verdict : aucune nuit complète mesurée (il faut des points autour de 03:00 UTC).")
        return 1
    if v == "ok":
        print(f"Verdict : pas de croissance nocturne sur {len(deltas)} nuit(s) (seuil {THRESHOLD_MB:.0f} Mo). "
              "Trois nuits sont demandées avant d'étiqueter la v14.")
        return 0
    print(f"Verdict : croissance nocturne encore présente (seuil {THRESHOLD_MB:.0f} Mo).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
