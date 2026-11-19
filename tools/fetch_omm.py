#!/usr/bin/env python3
"""Télécharge le groupe amateur CelesTrak (OMM JSON), valide et écrit le fichier.

Utilisé par GitHub Actions (voir .github/workflows/omm-daily.yml).
En cas d'échec, le fichier précédent n'est pas modifié et le script sort en erreur.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=amateur&FORMAT=json"
UA = "NeuralDXWatcher/14.0 (+https://github.com/F1SMV/Neural-DX-Watcher)"
MIN_OBJECTS = 50
REQUIRED_KEYS = ("NORAD_CAT_ID", "OBJECT_NAME", "EPOCH", "MEAN_MOTION")


def fetch(url, tries=3, timeout=60):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, OSError) as exc:
            last = exc
            if i < tries - 1:
                time.sleep(15 * (i + 1))
    raise RuntimeError(f"téléchargement impossible après {tries} essais: {last}")


def validate(raw):
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"JSON inattendu: type {type(data).__name__}")
    if len(data) < MIN_OBJECTS:
        raise ValueError(f"trop peu d'objets: {len(data)} (minimum {MIN_OBJECTS})")
    for obj in data[:5]:
        missing = [k for k in REQUIRED_KEYS if k not in obj]
        if missing:
            raise ValueError(f"champs absents: {missing}")
    return data


def main(out_path):
    raw = fetch(URL)
    data = validate(raw)
    tmp = out_path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(raw)
    os.replace(tmp, out_path)
    print(f"OK {len(data)} objets -> {out_path}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: fetch_omm.py CHEMIN_SORTIE", file=sys.stderr)
        sys.exit(2)
    try:
        sys.exit(main(sys.argv[1]))
    except Exception as exc:  # erreur explicite pour le journal Actions
        print(f"ERREUR: {exc}", file=sys.stderr)
        sys.exit(1)
