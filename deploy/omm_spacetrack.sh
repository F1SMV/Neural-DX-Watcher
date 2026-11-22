#!/bin/sh
# Télécharge les TLE de tes satellites actifs depuis Space-Track.
# En cas d'échec, l'ancien fichier est conservé.
set -eu
DIR="$HOME/Neural-DX-Watcher"
ENV="$HOME/.config/neural-dx/spacetrack.env"
USER_ST=$(sed -n 's/^SPACETRACK_USER=//p' "$ENV")
PASS_ST=$(sed -n 's/^SPACETRACK_PASS=//p' "$ENV")
JAR=$(mktemp)
TMP="$DIR/data/omm_local.json.tmp"
trap 'rm -f "$JAR"' EXIT

NORADS=$(python3 -I -c 'import json,sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
print(",".join(str(int(s["norad"])) for s in cfg if s.get("active", True)))' "$DIR/data/satellites_config.json")

curl -fsS -c "$JAR" -o /dev/null --max-time 60 \
  --data-urlencode "identity=$USER_ST" \
  --data-urlencode "password=$PASS_ST" \
  https://www.space-track.org/ajaxauth/login
curl -fsS -b "$JAR" --max-time 120 -o "$TMP" \
  "https://www.space-track.org/basicspacedata/query/class/gp/NORAD_CAT_ID/$NORADS/format/json"
curl -fsS -b "$JAR" -o /dev/null https://www.space-track.org/ajaxauth/logout || true

N=$(python3 -I -c 'import json,sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
assert isinstance(d, list) and d and all("NORAD_CAT_ID" in o for o in d)
print(len(d))' "$TMP")
mv "$TMP" "$DIR/data/omm_local.json"
echo "$(date -u +%FT%TZ) Space-Track OK: $N objets"
