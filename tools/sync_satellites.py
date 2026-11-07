"""Synchronise le registre data/ham_satellites.json avec SatNOGS et CelesTrak.

But : qu'un nouveau satellite n'oblige plus à une saisie manuelle du NORAD.

Usage (depuis la racine du projet, sur le Pi) :
    python3 tools/sync_satellites.py            # rapport seul
    python3 tools/sync_satellites.py --write    # réécrit le registre (sauvegarde .bak)

Règles :
1. NORAD : un satellite sans NORAD est rapproché de SatNOGS par son nom principal
   (voir enrich_satellites.core_name). Le NORAD est alors ajouté.
2. TLE : un satellite n'est « actif » que si son NORAD figure dans les TLE CelesTrak.
   Sinon son statut passe à « statut_inconnu » (affiché « Statut non confirmé »).
3. Découverte : un satellite SatNOGS absent du registre, lancé ou à venir récemment,
   est ajouté avec le champ « a_valider: true ». Rien n'est supprimé.
4. Aucun appel réseau dans webapp.py : ce script s'exécute à la demande (cron ou manuel).
   CelesTrak limite les requêtes : ne pas lancer plus d'une fois par heure.
"""
import argparse
import json
import shutil
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.enrich_satellites import (  # noqa: E402
    UA,
    core_name,
    fetch_satnogs,
    index_satnogs,
)

AMSAT_TLE = "https://www.amsat.org/amsat/ftp/keps/current/nasa.all"
CELESTRAK_AMATEUR = "https://celestrak.org/NORAD/elements/gp.php?GROUP=amateur&FORMAT=json"
DISCOVERY_WINDOW_DAYS = 180
REGISTRY = Path("data/ham_satellites.json")


def parse_tle_norads(text):
    """Extrait les NORAD d'un fichier TLE texte (blocs de 3 lignes : nom, ligne 1, ligne 2).

    Le NORAD est aux colonnes 3 à 7 de la ligne 1 (index 2:7).
    """
    norads = set()
    for line in text.splitlines():
        if line.startswith("1 ") and len(line) >= 7 and line[2:7].strip().isdigit():
            norads.add(int(line[2:7]))
    return norads


def fetch_tle_norads(url=AMSAT_TLE, timeout=30):
    """Retourne l'ensemble des NORAD présents dans les TLE (AMSAT par défaut, CelesTrak en option)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", errors="replace")
    if url.endswith(".json"):
        data = json.loads(body)
        if not isinstance(data, list):
            raise ValueError("réponse CelesTrak inattendue (liste attendue)")
        return {int(item["NORAD_CAT_ID"]) for item in data if "NORAD_CAT_ID" in item}
    norads = parse_tle_norads(body)
    if not norads:
        raise ValueError("aucun TLE lu dans la réponse AMSAT")
    return norads


def _items(doc):
    return doc["satellites"] if isinstance(doc, dict) else doc


def _lookup_keys(name):
    """« AO-129 (ERMINAZ-2U) » -> ["ao129", "ermin az2u"] : nom principal puis alias entre parenthèses."""
    keys = [core_name(name)]
    if "(" in name and ")" in name:
        alias = name.split("(", 1)[1].split(")", 1)[0]
        keys.append(core_name(alias))
    return [k for k in keys if k]


def attach_norad(sat, idx):
    """Ajoute le NORAD depuis SatNOGS si le satellite n'en a pas. Retourne True si ajouté."""
    if sat.get("norad"):
        return False
    rec = None
    for key in _lookup_keys(sat.get("name", "")):
        rec = idx.get(key)
        if rec:
            break
    if not rec or not rec.get("norad_cat_id"):
        return False
    sat["norad"] = int(rec["norad_cat_id"])
    return True


def check_tle(sat, tle_norads):
    """Contrôle NORAD / TLE selon le statut.

    - « actif » sans TLE -> « statut_inconnu » ;
    - « a_venir » sans NORAD -> « statut_inconnu » (« à venir » suppose un lancement annoncé,
      pas une simple absence de données).

    Retourne le motif si le statut a été modifié, sinon None.
    """
    norad = sat.get("norad")
    if sat.get("status") == "a_venir" and not norad:
        sat["status"] = "statut_inconnu"
        sat["status_reason"] = "pas de NORAD : lancement non confirmé"
        return sat["status_reason"]
    if sat.get("status") != "actif":
        return None
    if norad and int(norad) in tle_norads:
        return None
    sat["status"] = "statut_inconnu"
    sat["status_reason"] = (
        "pas de NORAD dans le registre" if not norad
        else f"NORAD {norad} absent des TLE CelesTrak"
    )
    return sat["status_reason"]


def discover(records, registry_norads, today, window_days=DISCOVERY_WINDOW_DAYS):
    """Satellites SatNOGS absents du registre, à venir ou lancés depuis peu."""
    cutoff = today - timedelta(days=window_days)
    found = []
    for rec in records:
        norad = rec.get("norad_cat_id")
        if not norad or int(norad) in registry_norads:
            continue
        sn_status = str(rec.get("status") or "").strip().lower()
        launched = str(rec.get("launched") or "")[:10]
        if sn_status == "future":
            status = "a_venir"
        elif sn_status == "in orbit" and launched and launched >= cutoff.isoformat():
            status = "en_deploiement"
        else:
            continue
        found.append({
            "name": rec.get("name", ""),
            "norad": int(norad),
            "status": status,
            "launch": launched or None,
            "a_valider": True,
            "source": "satnogs",
        })
    return found


def sync(doc, records, tle_norads, today, discover_new=False):
    """Applique les règles. Retourne (doc modifié, rapport).

    La découverte n'ajoute rien au registre par défaut : elle n'est qu'un rapport,
    pour éviter d'inonder la page de satellites « à valider ».
    """
    sats = _items(doc)
    idx = index_satnogs(records)
    report = {"norad_ajoutes": [], "norad_introuvables": [], "statuts_modifies": [], "nouveaux": []}

    for sat in sats:
        if attach_norad(sat, idx):
            report["norad_ajoutes"].append((sat["name"], sat["norad"]))
        elif not sat.get("norad"):
            report["norad_introuvables"].append(sat.get("name"))
        reason = check_tle(sat, tle_norads)
        if reason:
            report["statuts_modifies"].append((sat["name"], reason))

    registry_norads = {int(s["norad"]) for s in sats if s.get("norad")}
    for new in discover(records, registry_norads, today):
        report["nouveaux"].append((new["name"], new["norad"], new["status"]))
        if discover_new:
            sats.append(new)

    return doc, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--registry", default=str(REGISTRY))
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--discover", action="store_true",
                        help="ajoute au registre les nouveaux satellites détectés (à valider)")
    args = parser.parse_args(argv)

    path = Path(args.registry)
    doc = json.loads(path.read_text(encoding="utf-8"))
    records = fetch_satnogs()
    tle_norads = fetch_tle_norads()
    doc, report = sync(doc, records, tle_norads, date.today(), discover_new=args.discover)

    for key, label in [
        ("norad_ajoutes", "NORAD ajoutés"),
        ("norad_introuvables", "NORAD introuvables (à traiter à la main)"),
        ("statuts_modifies", "statuts passés en « statut non confirmé »"),
        ("nouveaux", "nouveaux satellites détectés (à valider)"),
    ]:
        print(f"{label} : {len(report[key])}")
        for item in report[key]:
            print("   ", item)

    if args.write:
        shutil.copy(path, path.with_suffix(path.suffix + ".bak"))
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Registre réécrit : {path} (sauvegarde .bak)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
