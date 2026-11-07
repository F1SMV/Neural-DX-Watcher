"""Croise le registre data/ham_satellites.json avec SatNOGS (db.satnogs.org).

Usage (sur le Pi) :
    python3 tools/enrich_satellites.py            # rapport seul
    python3 tools/enrich_satellites.py --write    # réécrit le registre (sauvegarde .bak)

Règles :
- un satellite est rapproché de SatNOGS par son nom principal (sans parenthèses ni « / »),
  comparé au champ « name » puis aux alias « names » ;
- si SatNOGS publie une date de lancement, la source « satnogs » est ajoutée ;
- date de lancement absente du registre -> reprise de SatNOGS ;
- date présente dans les deux et différente -> « desaccord » (jamais écrasée) ;
- aucun appel réseau dans webapp.py : ce script s'exécute à la demande.
"""
import argparse
import json
import re
import shutil
import sys
import urllib.request
from pathlib import Path

SATNOGS_URL = "https://db.satnogs.org/api/satellites/?format=json"
SATNOGS_SOURCE = {
    "id": "satnogs",
    "label": "SatNOGS DB",
    "url": "https://db.satnogs.org/satellites/",
    "date": "",
}
UA = "Neural-DX-Watcher/13.4 (satellite enrichment)"
DEPLOY_MAX_DAYS = 60  # au-delà, « en déploiement » sans preuve d'exploitation
DEAD_STATES = {"dead", "re-entered", "reentered"}
FUTURE_STATES = {"future"}


def _norm(text):
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def core_name(name):
    """« FO-29 (JAS-2) » -> « FO-29 » ; « CAS-8A / 8B » -> « CAS-8A »."""
    base = re.split(r"\s*\(|\s+/\s*", name, maxsplit=1)[0]
    return _norm(base)


def fetch_satnogs(url=SATNOGS_URL, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError("réponse SatNOGS inattendue (liste attendue)")
    return data


def index_satnogs(records):
    """Index par nom normalisé et par alias ; une entrée SatNOGS peut avoir plusieurs alias."""
    idx = {}
    for rec in records:
        keys = {_norm(rec.get("name", ""))}
        keys.update(_norm(a) for a in str(rec.get("names") or "").split(",") if a.strip())
        for k in keys:
            if k:
                idx.setdefault(k, rec)
    return idx


def _date(value):
    return str(value)[:10] if value else None


def suggest_status(sat, today):
    """Retourne (statut suggéré, raison) ou (None, None) si rien à proposer.

    Ne modifie rien : le script propose, l'humain valide.
    """
    from datetime import date
    cur = sat.get("status")
    sn = sat.get("satnogs") or {}
    sn_status = str(sn.get("status") or "").strip().lower()
    if sn_status in DEAD_STATES or sn.get("decayed"):
        if cur != "hors_service":
            return "hors_service", f"SatNOGS : statut « {sn_status or 'désorbité'} »"
        return None, None
    if sn_status in FUTURE_STATES and cur != "a_venir":
        return "a_venir", "SatNOGS : statut « future »"
    if cur == "en_deploiement" and sat.get("launch"):
        try:
            age = (today - date.fromisoformat(sat["launch"])).days
        except ValueError:
            return None, None
        if age > DEPLOY_MAX_DAYS:
            return ("statut_inconnu",
                    f"lancé il y a {age} j (> {DEPLOY_MAX_DAYS} j), exploitation non confirmée")
    return None, None


def _propose(sat, name, today, report, apply_status):
    new, why = suggest_status(sat, today)
    if new:
        report["status_suggestions"].append(f"{name}: {sat.get('status')} -> {new} ({why})")
        if apply_status:
            sat["status"] = new
            report.setdefault("status_applied", []).append(name)


def enrich(registry_raw, satnogs_records, today=None, apply_status=False):
    """Retourne (registre enrichi, rapport). registry_raw = dict brut du JSON."""
    idx = index_satnogs(satnogs_records)
    from datetime import date as _d
    today = today or _d.today()
    report = {"matched": [], "unmatched": [], "launch_filled": [], "launch_disagree": [],
              "status_suggestions": []}
    sources = registry_raw.setdefault("sources", [])
    if not any(s.get("id") == "satnogs" for s in sources):
        sources.append(dict(SATNOGS_SOURCE))

    for sat in registry_raw.get("satellites", []):
        name = sat.get("name", "")
        rec = idx.get(core_name(name))
        if rec is None:
            report["unmatched"].append(name)
            _propose(sat, name, today, report, apply_status)
            continue
        report["matched"].append(name)
        sat["satnogs"] = {
            "norad": rec.get("norad_cat_id"),
            "status": rec.get("status"),
            "launched": _date(rec.get("launched")),
            "decayed": _date(rec.get("decayed")),
        }
        srcs = list(sat.get("sources", []))
        if "satnogs" not in srcs:
            srcs.append("satnogs")
        sat["sources"] = srcs

        snl = sat["satnogs"]["launched"]
        reg = sat.get("launch")
        if snl and not reg:
            sat["launch"] = snl
            report["launch_filled"].append(f"{name} -> {snl}")
        elif snl and reg and reg != snl:
            sat["launch_check"] = "desaccord"
            report["launch_disagree"].append(f"{name}: registre {reg} / SatNOGS {snl}")
        elif snl and reg == snl:
            sat["launch_check"] = "concordant"
        _propose(sat, name, today, report, apply_status)
    return registry_raw, report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default="data/ham_satellites.json")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)

    path = Path(args.registry)
    raw = json.loads(path.read_text(encoding="utf-8"))
    records = fetch_satnogs()
    enriched, rep = enrich(raw, records, apply_status=args.write)

    print(f"SatNOGS : {len(records)} entrées")
    print(f"Rapprochés : {len(rep['matched'])} · non trouvés : {len(rep['unmatched'])}")
    for label in ("launch_filled", "launch_disagree", "status_suggestions"):
        for line in rep[label]:
            print(f"  [{label}] {line}")
    if rep["unmatched"]:
        print("Non trouvés (à vérifier à la main) :", ", ".join(rep["unmatched"]))

    if args.write:
        shutil.copy(path, path.with_suffix(".json.bak"))
        path.write_text(json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Registre réécrit : {path} (sauvegarde .bak) ; statuts modifiés : {len(rep.get('status_applied', []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
