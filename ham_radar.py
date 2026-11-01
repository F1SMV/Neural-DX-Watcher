"""Pavé « Radioamateur — lancements, fréquences, statuts » (page satellites).

Lecture locale d'un registre curé (data/ham_satellites.json) croisé sur plusieurs
sources. Aucun appel réseau : la page ne bloque jamais sur une source externe.
"""
import json
from pathlib import Path

STATUSES = ("a_venir", "en_deploiement", "actif", "statut_inconnu", "hors_service")
STATUS_LABELS = {
    "a_venir": "À venir",
    "en_deploiement": "En cours de déploiement",
    "actif": "Actifs",
    "statut_inconnu": "Statut non confirmé",
    "hors_service": "Hors service",
}
MIN_SOURCES_CONFIRMED = 2
ITEM_FIELDS = ("name", "status", "launch", "launch_note", "uplink", "downlink",
               "modes", "note", "recently_active")


def validate(data):
    """Valide le registre brut. Retourne un dict normalisé et la liste des erreurs."""
    errors = []
    if not isinstance(data, dict):
        return {"updated": None, "sources": {}, "satellites": [], "errors": ["registre non valide"]}

    sources = {}
    for s in data.get("sources", []):
        sid = s.get("id")
        if not sid or not str(s.get("url", "")).startswith("https://"):
            errors.append(f"source invalide : {sid!r}")
            continue
        sources[sid] = s

    satellites = []
    for e in data.get("satellites", []):
        name = e.get("name")
        if not name:
            errors.append("satellite sans nom")
            continue
        if e.get("status") not in STATUSES:
            errors.append(f"{name} : statut inconnu {e.get('status')!r}")
            continue
        if not e.get("sources"):
            errors.append(f"{name} : aucune source citée")
        unknown = [s for s in e.get("sources", []) if s not in sources]
        if unknown:
            errors.append(f"{name} : source inconnue {unknown}")
        satellites.append(e)

    return {"updated": data.get("updated"), "sources": sources,
            "satellites": satellites, "errors": errors}


def load_registry(path):
    """Charge et valide le registre depuis le disque."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate(raw)


def build_payload(registry):
    """Regroupe les satellites par statut, avec le nombre de sources recoupées."""
    groups = {s: [] for s in STATUSES}
    for e in registry["satellites"]:
        # Dédoublonnage : une même source citée deux fois ne compte pas deux fois.
        known = list(dict.fromkeys(s for s in e.get("sources", []) if s in registry["sources"]))
        item = {k: e.get(k) for k in ITEM_FIELDS}
        item["recently_active"] = bool(e.get("recently_active", False))
        item["sources"] = [
            {"label": registry["sources"][s]["label"], "url": registry["sources"][s]["url"],
             "date": registry["sources"][s].get("date", "")}
            for s in known
        ]
        item["confirmed"] = len(known) >= MIN_SOURCES_CONFIRMED
        groups[e["status"]].append(item)

    total = sum(len(v) for v in groups.values())
    return {
        "updated": registry["updated"],
        "labels": STATUS_LABELS,
        "groups": groups,
        "stats": {
            "total": total,
            "confirmed": sum(1 for v in groups.values() for i in v if i["confirmed"]),
            "recently_active": sum(1 for v in groups.values() for i in v if i["recently_active"]),
        },
        "errors": registry["errors"],
    }
