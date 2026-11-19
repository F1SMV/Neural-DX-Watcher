#!/bin/sh
# Met à jour data/omm_local.json depuis la release GitHub omm-latest.
# Lancé chaque jour par cron. En cas d'échec, l'ancien fichier est conservé.
set -eu

DIR="$(cd "$(dirname "$0")/.." && pwd)"
URL="https://github.com/F1SMV/Neural-DX-Watcher/releases/download/omm-latest/omm_amateur.json"
TMP="$DIR/data/omm_local.json.tmp"
DST="$DIR/data/omm_local.json"

curl -fsS --retry 3 --retry-delay 20 --max-time 120 -o "$TMP" "$URL"

python3 -I -c '
import json, sys
d = json.load(open(sys.argv[1]))
assert isinstance(d, list) and len(d) >= 50, "fichier OMM invalide"
' "$TMP"

mv "$TMP" "$DST"
N=$(python3 -I -c 'import json, sys; print(len(json.load(open(sys.argv[1]))))' "$DST")
echo "$(date -u +%FT%TZ) OMM mis à jour: $N objets"
