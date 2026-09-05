#!/usr/bin/env python3
"""
verify_deployment.py — Vérification rapide des fichiers v12.4
Utilisation : python3 verify_deployment.py
"""
import os
import sys
from pathlib import Path

REQUIRED_FILES = {
    # Backend (3)
    'webapp.py': {'type': 'Python', 'min_size': 100000, 'desc': 'Flask principal'},
    'country_meta.py': {'type': 'Python', 'min_size': 1000, 'desc': 'Enrichissement pays'},
    'dxcc_hunt.py': {'type': 'Python', 'min_size': 2000, 'desc': 'Logique Hunt DXCC'},
    
    # Frontend (7)
    'hunt.html': {'type': 'HTML', 'min_size': 10000, 'desc': 'Mode Hunt'},
    'briefing.html': {'type': 'HTML', 'min_size': 10000, 'desc': 'Actualités'},
    'map.html': {'type': 'HTML', 'min_size': 10000, 'desc': 'Carte'},
    'world.html': {'type': 'HTML', 'min_size': 10000, 'desc': 'Monde DX'},
    'satellites.html': {'type': 'HTML', 'min_size': 10000, 'desc': 'Satellites'},
    'weather.html': {'type': 'HTML', 'min_size': 10000, 'desc': 'Météo'},
    'ai_insight.html': {'type': 'HTML', 'min_size': 10000, 'desc': 'AI Insight'},
    
    # Docs (2)
    'README_FR.md': {'type': 'Doc', 'min_size': 1000, 'desc': 'Doc FR'},
    'README_EN.md': {'type': 'Doc', 'min_size': 1000, 'desc': 'Doc EN'},
}

OPTIONAL_FILES = {
    'test_dxcc_hunt.py': {'type': 'Test', 'desc': '13/13 tests Hunt'},
    'test_country_meta.py': {'type': 'Test', 'desc': '16/16 tests Pays'},
    'index.html': {'type': 'HTML', 'desc': 'Dashboard (mise à jour)'},
}

def check_file_size(filepath, min_size):
    """Vérifier qu'un fichier existe et a une taille raisonnable"""
    try:
        size = os.path.getsize(filepath)
        if size < min_size:
            return False, f"trop petit ({size} < {min_size})"
        return True, size
    except FileNotFoundError:
        return False, "fichier absent"

def check_file_content(filepath, patterns):
    """Vérifier la présence de patterns dans un fichier"""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        results = {}
        for pattern_name, pattern in patterns.items():
            results[pattern_name] = pattern in content
        return results
    except Exception as e:
        return {'error': str(e)}

def main():
    print("=" * 70)
    print("🔍 Vérification Déploiement Neural DX Watcher v12.4")
    print("=" * 70)
    
    cwd = Path.cwd()
    print(f"\n📁 Répertoire courant : {cwd}\n")
    
    # Fichiers obligatoires
    print("✅ FICHIERS OBLIGATOIRES (10)")
    print("-" * 70)
    required_ok = 0
    required_total = len(REQUIRED_FILES)
    
    for filename, info in REQUIRED_FILES.items():
        filepath = cwd / filename
        exists, status = check_file_size(filepath, info['min_size'])
        symbol = "✓" if exists else "✗"
        size_str = f"({status:,}b)" if isinstance(status, int) else f"({status})"
        print(f"  {symbol} {filename:20s} {size_str:20s} | {info['desc']}")
        if exists:
            required_ok += 1
    
    print(f"\nRésultat : {required_ok}/{required_total} fichiers OK")
    
    if required_ok < required_total:
        print(f"\n⚠️  ATTENTION : {required_total - required_ok} fichier(s) manquant(s) !")
    
    # Fichiers optionnels
    print("\n\n⚠️  FICHIERS OPTIONNELS (tests unitaires)")
    print("-" * 70)
    optional_ok = 0
    optional_total = len(OPTIONAL_FILES)
    
    for filename, info in OPTIONAL_FILES.items():
        filepath = cwd / filename
        exists = filepath.exists()
        symbol = "✓" if exists else "✗"
        print(f"  {symbol} {filename:20s} {'présent' if exists else 'absent':20s} | {info['desc']}")
        if exists:
            optional_ok += 1
    
    # Vérifications spécifiques : nav sur HTML
    print("\n\n🎯 VÉRIFICATIONS SPÉCIFIQUES")
    print("-" * 70)
    
    html_files = [f for f in REQUIRED_FILES.keys() if f.endswith('.html')]
    nav_ok = 0
    print("\nNav 🎯 HUNT présente :")
    for filename in html_files:
        filepath = cwd / filename
        if filepath.exists():
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            has_nav = 'nav class="top-nav"' in content
            has_hunt_link = 'href="/hunt"' in content
            if has_nav and has_hunt_link:
                print(f"  ✓ {filename}")
                nav_ok += 1
            else:
                print(f"  ✗ {filename} (nav={has_nav}, hunt_link={has_hunt_link})")
    
    print(f"\nRésultat : {nav_ok}/{len(html_files)} pages avec nav OK")
    
    # Vérifications Python
    print("\n\nPython syntaxe :")
    python_files = [f for f in REQUIRED_FILES.keys() if f.endswith('.py')]
    python_ok = 0
    for filename in python_files:
        filepath = cwd / filename
        if filepath.exists():
            try:
                import py_compile
                py_compile.compile(str(filepath), doraise=True)
                print(f"  ✓ {filename}")
                python_ok += 1
            except Exception as e:
                print(f"  ✗ {filename} : {e}")
    
    print(f"\nRésultat : {python_ok}/{len(python_files)} fichiers Python OK")
    
    # Résumé final
    print("\n\n" + "=" * 70)
    all_required_ok = required_ok == required_total
    all_nav_ok = nav_ok == len(html_files)
    all_python_ok = python_ok == len(python_files)
    
    if all_required_ok and all_nav_ok and all_python_ok:
        print("✅ RÉSULTAT : PRÊT POUR DÉPLOIEMENT !")
        print("\nProchaine étape :")
        print("  1. Copier webapp.py, country_meta.py, dxcc_hunt.py sur le Pi")
        print("  2. Copier les 7 .html dans templates/ sur le Pi")
        print("  3. pkill -f 'python.*webapp.py' && bash start.sh")
        return 0
    else:
        print("❌ RÉSULTAT : Problèmes détectés")
        if not all_required_ok:
            print(f"   - Fichiers manquants : {required_total - required_ok}")
        if not all_nav_ok:
            print(f"   - Pages sans nav : {len(html_files) - nav_ok}")
        if not all_python_ok:
            print(f"   - Erreurs Python : {len(python_files) - python_ok}")
        return 1

if __name__ == '__main__':
    sys.exit(main())
