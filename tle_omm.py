"""Éléments orbitaux OMM (CelesTrak GP, FORMAT=json) → lignes TLE (v14).

Pourquoi : les NORAD supérieurs à 99999 ne tiennent pas dans un TLE texte. CelesTrak
publie ces satellites en OMM ; on les écrit en Alpha-5 (ex. 101101 → A1101), que
sgp4 relit tel quel. Si la source fournit déjà TLE_LINE1 / TLE_LINE2, on les garde.
"""
import json
import os
from datetime import datetime

from sgp4 import omm as _omm
from sgp4.api import Satrec
from sgp4.exporter import export_tle

_REQUIRED = ("NORAD_CAT_ID", "EPOCH", "MEAN_MOTION", "ECCENTRICITY", "INCLINATION",
             "RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY", "BSTAR",
             "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT", "OBJECT_ID", "CLASSIFICATION_TYPE",
             "EPHEMERIS_TYPE", "ELEMENT_SET_NO", "REV_AT_EPOCH")


def _fields(obj):
    """Copie des champs OMM, époque normalisée (sgp4 exige une fraction de seconde)."""
    f = {k: obj[k] for k in _REQUIRED}
    f["OBJECT_ID"] = str(f["OBJECT_ID"])
    f["CLASSIFICATION_TYPE"] = str(f["CLASSIFICATION_TYPE"])
    epoch = str(f["EPOCH"]).strip()
    if "." not in epoch:
        epoch += ".000000"
    datetime.strptime(epoch, "%Y-%m-%dT%H:%M:%S.%f")   # lève ValueError si format inconnu
    f["EPOCH"] = epoch
    return f


def omm_to_tle(obj):
    """Renvoie (norad, nom, ligne1, ligne2). Lève KeyError / ValueError / TypeError si invalide."""
    norad = int(obj["NORAD_CAT_ID"])
    if norad <= 0:
        raise ValueError("NORAD invalide")
    name = str(obj.get("OBJECT_NAME", str(norad))).strip()
    tle1 = str(obj.get("TLE_LINE1") or "").strip()
    tle2 = str(obj.get("TLE_LINE2") or "").strip()
    if tle1 and tle2:
        return norad, name, tle1, tle2
    sat = Satrec()
    _omm.initialize(sat, _fields(obj))
    tle1, tle2 = export_tle(sat)
    if len(tle1) != 69 or len(tle2) != 69:
        raise ValueError("lignes TLE de longueur inattendue")
    return norad, name, tle1, tle2


def parse_omm_json(text):
    """Texte JSON CelesTrak → ({norad: (nom, ligne1, ligne2)}, nombre d'objets rejetés)."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return {}, 0
    if not isinstance(data, list):
        return {}, 0
    out, skipped = {}, 0
    for obj in data:
        try:
            norad, name, tle1, tle2 = omm_to_tle(obj)
        except (KeyError, ValueError, TypeError, AttributeError):
            skipped += 1
            continue
        out.setdefault(norad, (name, tle1, tle2))
    return out, skipped


def load_omm_file(path):
    """Lit un fichier OMM déposé à la main (ex. liste CelesTrak téléchargée sur un PC).

    Absent ou illisible : ({}, 0). Même format que parse_omm_json.
    """
    if not os.path.isfile(path):
        return {}, 0
    try:
        with open(path, encoding="utf-8") as f:
            return parse_omm_json(f.read())
    except OSError:
        return {}, 0
