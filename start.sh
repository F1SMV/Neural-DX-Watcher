#!/bin/bash
export PYTHONPATH=$(pwd)

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}[INIT] Démarrage de Neural Dx Watcher v12.2 crée par F1SMV...${NC}"
sleep 10

# 1. Nettoyage des ports — arrêt propre (SIGTERM) avant kill -9 en dernier
# recours seulement. kill -9 direct peut laisser sockets/fichiers dans un
# état incohérent (pas de nettoyage des handlers de signal du process tué).
for PORT in 5000 8000; do
    PID=$(lsof -t -i:$PORT)
    if [ -n "$PID" ]; then
        echo -e "${YELLOW}[WARN] Port $PORT occupé par PID $PID — arrêt propre (SIGTERM)...${NC}"
        kill -TERM $PID 2>/dev/null
        # Attendre jusqu'à 5s que le process se termine proprement
        for i in 1 2 3 4 5; do
            if ! kill -0 $PID 2>/dev/null; then
                break
            fi
            sleep 1
        done
        # Si toujours vivant après 5s, kill -9 en dernier recours
        if kill -0 $PID 2>/dev/null; then
            echo -e "${RED}[WARN] PID $PID ne répond pas à SIGTERM — kill -9 forcé.${NC}"
            kill -9 $PID 2>/dev/null
            sleep 1
        fi
    fi
done
echo -e "${GREEN}[OK] Ports nettoyés.${NC}"

# 2. Environnement virtuel
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}[INSTALL] Création du venv...${NC}"
    python3 -m venv venv
fi
source venv/bin/activate
echo -e "${GREEN}[OK] venv activé : $(which python3)${NC}"

# 3. Dépendances — installées UNE SEULE FOIS, pas à chaque démarrage.
# L'ancien comportement forçait un accès réseau à chaque lancement (pip
# install à chaque boot), fragile pour une app censée tourner en local.
# On vérifie d'abord si tout est déjà importable ; on n'installe que si
# quelque chose manque réellement.
echo -e "${YELLOW}[CHECK] Vérification des dépendances...${NC}"
python3 -c "
import importlib
mods = ['flask', 'requests', 'bs4', 'feedparser', 'telnetlib3']
missing = [m for m in mods if importlib.util.find_spec(m) is None]
try:
    from sgp4.api import Satrec
except ImportError:
    missing.append('sgp4')
exit(1 if missing else 0)
" 2>/dev/null

if [ $? -ne 0 ]; then
    echo -e "${YELLOW}[INSTALL] Dépendances manquantes détectées — installation...${NC}"
    if [ -f "requirements.txt" ]; then
        pip install --quiet -r requirements.txt
    else
        pip install --quiet flask requests beautifulsoup4 feedparser telnetlib3 sgp4
    fi
    # Re-vérification sgp4 spécifiquement (dépendance native, échoue parfois silencieusement)
    python3 -c "from sgp4.api import Satrec; print('[OK] sgp4 disponible')" || {
        echo -e "${RED}[ERROR] sgp4 toujours indisponible — tentative forcée...${NC}"
        pip install --force-reinstall sgp4
    }
else
    echo -e "${GREEN}[OK] Toutes les dépendances sont déjà installées — pas de réinstallation.${NC}"
fi

# 4. Répertoires nécessaires
mkdir -p data logs

# 5. Lancement
echo -e "${GREEN}[START] Lancement Flask...${NC}"
python3 webapp.py
