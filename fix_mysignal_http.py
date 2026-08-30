#!/usr/bin/env python3
"""
Fix MY SIGNAL (panneau PSK Reporter, page accueil) — webapp.py

Diagnostic complet (session 28/08/2026) :
  - Broker MQTT mqtt.pskreporter.info accepte la connexion, confirme la
    souscription (SUBACK), mais ne pousse AUCUN message (0 sur le firehose
    mondial). Service tiers non garanti, hors de notre controle.
  - Le fallback HTTP existait mais envoyait la mauvaise requete : sans le
    parametre rronly=1, PSK Reporter renvoie "activeReceiver" (recepteurs
    actifs) au lieu de "receptionReport" (rapports concernant F1SMV).
    -> raw.get('receptionReport', []) etait donc toujours vide.
  - En plus, cache TTL=90s -> trop d'interrogations -> PSK Reporter renvoie
    "Your IP has made too many queries too often" (rate-limit).

Verifie hors app : senderCallsign=F1SMV&rronly=1 => 342 rapports reels.

CORRECTIONS :
  1. Ajouter 'rronly': '1' aux parametres de la requete HTTP.
  2. Detecter le message de rate-limit et basculer proprement sur le cache.
  3. Passer le cache TTL de 90s a 300s (regle officielle PSK Reporter :
     pas plus d'1 requete / 5 min).

Usage sur le Pi :
    cd ~/Spot-Watcher-DX
    python3 fix_mysignal_http.py
    pkill -f "python.*webapp.py" ; bash start.sh
"""
import sys, py_compile
from pathlib import Path

W = Path("webapp.py")
if not W.exists():
    print("❌ webapp.py introuvable. Lance depuis ~/Spot-Watcher-DX"); sys.exit(1)

src = W.read_text(encoding="utf-8")
bak = Path("webapp.py.before_mysignal_fix")
bak.write_text(src, encoding="utf-8")
print(f"✅ Backup : {bak.name}")

changes = 0

# ── FIX 1 : ajouter rronly=1 dans les parametres de la requete ──
old_params = """        params = urllib.parse.urlencode({
            'senderCallsign': MY_CALL,
            'flowStartSeconds': '-1800',
            'callback': 'cb',
        })"""
new_params = """        params = urllib.parse.urlencode({
            'senderCallsign': MY_CALL,
            'flowStartSeconds': '-1800',
            'rronly': '1',          # v12.3 FIX: sans ca, PSK Reporter renvoie
                                    # 'activeReceiver' au lieu de 'receptionReport'
            'callback': 'cb',
        })"""
if old_params in src:
    src = src.replace(old_params, new_params); changes += 1
    print("✅ FIX 1 : rronly=1 ajoute a la requete HTTP")
else:
    print("⚠️  FIX 1 : bloc params non trouve (deja applique ?)")

# ── FIX 2 : detecter le rate-limit avant de parser le JSON ──
old_parse = """        # Retirer le wrapper JSONP : \"cb(...)\"
        m = _re.match(r'^\\s*cb\\s*\\((.*)\\)\\s*;?\\s*$', body, _re.DOTALL)
        payload = m.group(1) if m else body
        raw = json.loads(payload)"""
new_parse = """        # v12.3 FIX: detecter le message de rate-limit PSK Reporter
        if 'too many queries' in body.lower():
            logger.warning(\"api_my_signal: PSK Reporter rate-limit (IP throttled) \"
                           \"— on sert le cache et on rallonge l'intervalle.\")
            if _my_signal_cache['data'] is not None:
                return jsonify(_my_signal_refresh_ages(_my_signal_cache['data'], now))
            return jsonify({'ok': False, 'call': MY_CALL, 'reports': [],
                            'error': 'rate_limited', 'cache_ttl': _MY_SIGNAL_CACHE_TTL})

        # Retirer le wrapper JSONP : \"cb(...)\"
        m = _re.match(r'^\\s*cb\\s*\\((.*)\\)\\s*;?\\s*$', body, _re.DOTALL)
        payload = m.group(1) if m else body
        raw = json.loads(payload)"""
if old_parse in src:
    src = src.replace(old_parse, new_parse); changes += 1
    print("✅ FIX 2 : detection rate-limit ajoutee")
else:
    print("⚠️  FIX 2 : bloc parsing non trouve (deja applique ?)")

# ── FIX 3 : TTL 90s -> 300s (regle officielle : 1 requete / 5 min) ──
old_ttl = "_MY_SIGNAL_CACHE_TTL = 90  # secondes"
new_ttl = "_MY_SIGNAL_CACHE_TTL = 300  # secondes — regle PSK Reporter: 1 requete / 5 min max (evite le rate-limit)"
if old_ttl in src:
    src = src.replace(old_ttl, new_ttl); changes += 1
    print("✅ FIX 3 : cache TTL 90s -> 300s")
else:
    print("⚠️  FIX 3 : ligne TTL non trouvee (deja applique ?)")

if changes == 0:
    print("\n⚠️  Aucun changement applique. Fichier peut-etre deja corrige.")
    sys.exit(0)

W.write_text(src, encoding="utf-8")
try:
    py_compile.compile("webapp.py", doraise=True)
    print(f"\n✅ {changes}/3 correctifs appliques. Syntaxe OK.")
except py_compile.PyCompileError as e:
    print(f"\n❌ Erreur syntaxe : {e}")
    print(f"   Restaure : cp {bak.name} webapp.py")
    sys.exit(1)

print()
print("═══════════════════════════════════════════")
print("PROCHAINE ETAPE — IMPORTANT :")
print("  Le rate-limit PSK Reporter dure quelques minutes.")
print("  1. Attendre ~5 min AVANT de relancer (sinon toujours throttle).")
print("  2. pkill -f 'python.*webapp.py'")
print("  3. bash start.sh")
print("  4. Ouvrir la page d'accueil -> panneau MY SIGNAL")
print("     doit afficher vos rapports (342 dispo cote PSK Reporter).")
print("═══════════════════════════════════════════")
