#!/usr/bin/env python3
"""
tools/log_meta_analyzer.py — Analyseur de log pour la page AI Insight / META ANALYSE
======================================================================================
Script externe appelé par webapp.py (route POST /api/meta/run) :
    python3 tools/log_meta_analyzer.py --log <fichier.log> --outdir <dossier>

Parse les lignes de spots du log applicatif (format émis par webapp.py) :
    2026-07-19 07:38:45 [INFO] TelnetWorker: SPOT: S53WWA (40m, CW) -> SPD: 20 pts (Dist: 855km)

Produit <outdir>/summary.json avec la structure exacte attendue par ai_insight.html :
    {
      "spots": <int total de spots analysés>,
      "range": {"start": "...", "end": "..."},
      "generated_at": "<ISO datetime>",
      "top_spots": [{"dx": "CALL", "spd": <int>, "band": "...", "mode": "..."}, ...]
    }

Conçu pour ne jamais planter : un log absent, vide, ou sans aucune ligne SPOT
produit quand même un summary.json valide (spots=0, top_spots=[]), plutôt
qu'une erreur — la robustesse prime sur l'exhaustivité de l'analyse.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Format exact des lignes de spot émises par webapp.py :
#   logger.info(f"SPOT: {dx_call} ({band}, {mode}) -> SPD: {spd_score} pts (Dist: {dist_km:.0f}km)")
# avec le préfixe de logging standard :
#   '%(asctime)s [%(levelname)s] %(threadName)s: %(message)s'
SPOT_LINE_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\[INFO\]\s+\S+:\s+'
    r'SPOT:\s+(\S+)\s+\((\S+),\s*(\S+)\)\s+->\s+SPD:\s+(\d+)\s+pts'
)

TOP_N = 8
# Ne pas tenter de charger un log gigantesque entièrement en mémoire —
# on ne garde que les N dernières lignes pertinentes pour l'analyse.
MAX_LINES_SCANNED = 500_000


def parse_log(log_path: Path):
    """Retourne la liste des spots parsés : [(datetime, call, band, mode, spd), ...]."""
    entries = []
    if not log_path.exists():
        return entries

    try:
        with log_path.open('r', encoding='utf-8', errors='replace') as f:
            # Lire uniquement les dernières lignes si le fichier est énorme,
            # pour éviter de charger des logs de plusieurs centaines de Mo.
            lines = f.readlines()
            if len(lines) > MAX_LINES_SCANNED:
                lines = lines[-MAX_LINES_SCANNED:]
    except Exception as e:
        print(f"[log_meta_analyzer] Erreur lecture log: {e}", file=sys.stderr)
        return entries

    for line in lines:
        m = SPOT_LINE_RE.match(line)
        if not m:
            continue
        ts_str, call, band, mode, spd = m.groups()
        try:
            dt = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue
        entries.append((dt, call.upper(), band, mode, int(spd)))

    return entries


def build_summary(entries):
    """Construit le dict summary.json depuis la liste de spots parsés."""
    now_iso = datetime.now(timezone.utc).isoformat(timespec='seconds')

    if not entries:
        return {
            "spots": 0,
            "range": {"start": None, "end": None},
            "generated_at": now_iso,
            "top_spots": [],
        }

    dts = [e[0] for e in entries]
    range_start = min(dts).strftime('%Y-%m-%d %H:%M')
    range_end = max(dts).strftime('%Y-%m-%d %H:%M')

    # Meilleur score SPD par indicatif (dédupliqué)
    best_by_call = {}
    for dt, call, band, mode, spd in entries:
        if call not in best_by_call or spd > best_by_call[call]['spd']:
            best_by_call[call] = {'dx': call, 'spd': spd, 'band': band, 'mode': mode}

    top_spots = sorted(best_by_call.values(), key=lambda x: -x['spd'])[:TOP_N]

    return {
        "spots": len(entries),
        "range": {"start": range_start, "end": range_end},
        "generated_at": now_iso,
        "top_spots": top_spots,
    }


def main():
    parser = argparse.ArgumentParser(description="Analyseur de log Neural DX Watcher")
    parser.add_argument('--log', required=True, help="Chemin du fichier log à analyser")
    parser.add_argument('--outdir', required=True, help="Dossier de sortie pour summary.json")
    args = parser.parse_args()

    log_path = Path(args.log)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    entries = parse_log(log_path)
    summary = build_summary(entries)

    out_file = outdir / "summary.json"
    out_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f"[log_meta_analyzer] {summary['spots']} spots analysés → {out_file}")


if __name__ == "__main__":
    main()
