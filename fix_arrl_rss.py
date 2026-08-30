#!/usr/bin/env python3
"""
Fix ARRL News dans webapp.py — passer de HTML (cassé) à RSS (fonctionne).
Le flux https://www.arrl.org/arrl.rss est un vrai RSS standard.

Usage sur le Pi:
    cd ~/Spot-Watcher-DX
    python3 fix_arrl_rss.py
"""
import re
import sys
from pathlib import Path

WEBAPP = Path("webapp.py")

if not WEBAPP.exists():
    print("❌ webapp.py introuvable. Lance ce script depuis ~/Spot-Watcher-DX")
    sys.exit(1)

content = WEBAPP.read_text(encoding="utf-8")
backup = WEBAPP.with_suffix(".py.before_arrl_rss")
backup.write_text(content, encoding="utf-8")
print(f"✅ Backup créé : {backup.name}")

# ── Correction 1 : la source ARRL dans BRIEFING_DEFAULT_SOURCES ──
# On remplace le bloc ARRL (type html, url /news) par (type rss, url /arrl.rss)
# Variantes possibles selon l'état du fichier

variants = [
    # Variante A : ARRL type html avec url /news
    (
        '''    {
        "id": "arrl",
        "name": "ARRL News",
        "url": "https://www.arrl.org/news",
        "site": "https://www.arrl.org/news",
        "type": "html",
    },''',
        '''    {
        "id": "arrl",
        "name": "ARRL News",
        "url": "https://www.arrl.org/arrl.rss",
        "site": "https://www.arrl.org/news",
        "type": "rss",
    },''',
    ),
]

applied = False
for old, new in variants:
    if old in content:
        content = content.replace(old, new)
        applied = True
        print("✅ Source ARRL corrigée : type html → rss, url → arrl.rss")
        break

if not applied:
    # ARRL peut-être déjà absent (supprimé lors d'un essai précédent).
    # On vérifie s'il faut le réinsérer après DX-World.
    if '"id": "arrl"' not in content:
        print("⚠️  ARRL absent des sources — réinsertion après DX-World…")
        dxworld_block = '''    {
        "id": "dxworld",
        "name": "DX-World",
        "url": "https://www.dx-world.net/feed/",
        "site": "https://www.dx-world.net/",
        "type": "rss",
    },'''
        arrl_block = dxworld_block + '''
    {
        "id": "arrl",
        "name": "ARRL News",
        "url": "https://www.arrl.org/arrl.rss",
        "site": "https://www.arrl.org/news",
        "type": "rss",
    },'''
        if dxworld_block in content:
            content = content.replace(dxworld_block, arrl_block)
            applied = True
            print("✅ Source ARRL réinsérée (type rss)")
        else:
            print("❌ Bloc DX-World introuvable — correction manuelle requise")
            sys.exit(1)
    else:
        # ARRL existe déjà — vérifier qu'il est bien en RSS
        if '"url": "https://www.arrl.org/arrl.rss"' in content:
            print("✅ ARRL déjà configuré en RSS — rien à changer")
        else:
            print("⚠️  ARRL présent mais URL inattendue — vérifier manuellement")

# ── Sauvegarde ──
WEBAPP.write_text(content, encoding="utf-8")

# ── Validation syntaxe ──
import py_compile
try:
    py_compile.compile("webapp.py", doraise=True)
    print("✅ Syntaxe webapp.py OK")
except py_compile.PyCompileError as e:
    print(f"❌ Erreur syntaxe : {e}")
    print(f"   Restaure avec : cp {backup.name} webapp.py")
    sys.exit(1)

print()
print("═══════════════════════════════════════════")
print("✅ Fix ARRL RSS appliqué avec succès")
print("═══════════════════════════════════════════")
print()
print("Redémarrer :")
print("  pkill -f 'python.*webapp.py'")
print("  bash start.sh")
print()
print("Vérifier (attendre ~30s le refresh du cache) :")
print("  curl -s 'http://192.168.1.81:8000/api/dx_briefing.json' | grep -o 'ARRL[^\"]*' | head -3")
