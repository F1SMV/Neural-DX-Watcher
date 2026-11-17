#!/bin/bash
# Neural DX Watcher — installation des services systemd (v14, NF-01).
#
#   neural-dx-watcher.service   lance l'application au démarrage du Pi et la relance en cas d'arrêt anormal
#   neural-dx-satsync.timer     synchronise le registre des satellites une fois par semaine
#
# Usage, depuis la racine du projet, avec l'utilisateur qui fait tourner l'application :
#   ./deploy/install_services.sh              installe et démarre
#   ./deploy/install_services.sh --dry-run    affiche les fichiers sans rien installer
#   ./deploy/install_services.sh --uninstall  arrête et supprime les services
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="${SUDO_USER:-$(id -un)}"
UNIT_DIR="/etc/systemd/system"
APP_UNIT="neural-dx-watcher.service"
SYNC_UNIT="neural-dx-satsync.service"
SYNC_TIMER="neural-dx-satsync.timer"
MODE="${1:-install}"

if [ ! -f "$APP_DIR/start.sh" ] || [ ! -f "$APP_DIR/webapp.py" ]; then
    echo "[ERREUR] start.sh ou webapp.py introuvable dans $APP_DIR" >&2
    exit 1
fi
if [ "$APP_USER" = "root" ]; then
    echo "[ERREUR] Lancer ce script avec l'utilisateur de l'application, pas en root." >&2
    exit 1
fi

# Python du venv s'il existe (créé par start.sh), sinon celui du système.
# sync_satellites.py n'utilise que la bibliothèque standard.
PYTHON="$APP_DIR/venv/bin/python3"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3)"

app_unit() { cat <<UNIT
[Unit]
Description=Neural DX Watcher (F1SMV)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
ExecStart=/bin/bash $APP_DIR/start.sh
Restart=on-failure
RestartSec=20
# Arrêt : SIGTERM à start.sh et à webapp.py, SIGKILL après 20 s.
KillMode=control-group
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
UNIT
}

sync_unit() { cat <<UNIT
[Unit]
Description=Neural DX Watcher : synchronisation du registre des satellites
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$APP_USER
WorkingDirectory=$APP_DIR
ExecStartPre=/bin/mkdir -p $APP_DIR/logs
ExecStart=$PYTHON $APP_DIR/tools/sync_satellites.py --write
StandardOutput=append:$APP_DIR/logs/sat_sync.log
StandardError=append:$APP_DIR/logs/sat_sync.log
UNIT
}

sync_timer() { cat <<UNIT
[Unit]
Description=Neural DX Watcher : synchronisation hebdomadaire des satellites

[Timer]
# Dimanche 05:30, heure locale (après le cycle nocturne de 03:00 UTC). Décalage aléatoire : ne pas charger SatNOGS et AMSAT à heure fixe.
OnCalendar=Sun *-*-* 05:30:00
RandomizedDelaySec=1800
# Pi éteint le dimanche : la synchronisation est rattrapée au démarrage suivant.
Persistent=true

[Install]
WantedBy=timers.target
UNIT
}

case "$MODE" in
--dry-run)
    echo "# ── $UNIT_DIR/$APP_UNIT";   app_unit;   echo
    echo "# ── $UNIT_DIR/$SYNC_UNIT";  sync_unit;  echo
    echo "# ── $UNIT_DIR/$SYNC_TIMER"; sync_timer
    ;;
--uninstall)
    sudo systemctl disable --now "$APP_UNIT" "$SYNC_TIMER" 2>/dev/null || true
    sudo rm -f "$UNIT_DIR/$APP_UNIT" "$UNIT_DIR/$SYNC_UNIT" "$UNIT_DIR/$SYNC_TIMER"
    sudo systemctl daemon-reload
    echo "[OK] Services supprimés. Lancement manuel : ./start.sh"
    ;;
install)
    app_unit   | sudo tee "$UNIT_DIR/$APP_UNIT"   >/dev/null
    sync_unit  | sudo tee "$UNIT_DIR/$SYNC_UNIT"  >/dev/null
    sync_timer | sudo tee "$UNIT_DIR/$SYNC_TIMER" >/dev/null
    sudo systemctl daemon-reload
    # start.sh libère lui-même le port 8000 : une instance lancée à la main est arrêtée proprement.
    sudo systemctl enable --now "$APP_UNIT" "$SYNC_TIMER"
    echo "[OK] Services installés pour $APP_USER dans $APP_DIR"
    echo "     État         : systemctl status $APP_UNIT"
    echo "     Redémarrer   : sudo systemctl restart $APP_UNIT   (ne plus lancer ./start.sh à la main)"
    echo "     Journal      : journalctl -u $APP_UNIT -n 50"
    echo "     Prochaine synchro satellites : systemctl list-timers $SYNC_TIMER"
    ;;
*)
    echo "Usage : $0 [--dry-run | --uninstall]" >&2
    exit 2
    ;;
esac
