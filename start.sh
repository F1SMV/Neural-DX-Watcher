#!/bin/bash
export PYTHONPATH=$(pwd)

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}[INIT] Démarrage de Radio Spot Watcher DX v7.6 crée par F1SMV...${NC}"
sleep 10

# 1. Nettoyage des ports
for PORT in 5000 8000; do
    PID=$(lsof -t -i:$PORT)
    if [ -n "$PID" ]; then
        echo -e "${RED}[WARN] Port $PORT occupé par PID $PID — arrêt...${NC}"
        kill -9 $PID
        sleep 1
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

# 3. Dépendances (dont sgp4)
echo -e "${YELLOW}[CHECK] Installation/vérification des dépendances...${NC}"
pip install --quiet flask requests beautifulsoup4 feedparser telnetlib3 sgp4

# Vérification sgp4
python3 -c "from sgp4.api import Satrec; print('[OK] sgp4 disponible')" || {
    echo -e "${RED}[ERROR] sgp4 toujours indisponible — tentative forcée...${NC}"
    pip install --force-reinstall sgp4
}

# 4. Répertoires nécessaires
mkdir -p data logs

# 5. Lancement
echo -e "${GREEN}[START] Lancement Flask...${NC}"
python3 webapp.py
