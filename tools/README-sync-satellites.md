# Synchronisation du registre des satellites

`tools/sync_satellites.py` met à jour `data/ham_satellites.json` à partir de
SatNOGS et des sources TLE. Il s'exécute à la demande : l'application
(`webapp.py`) ne fait aucun appel réseau pour cela.

## Ce qu'il fait

1. **NORAD manquant** : rapproche le satellite de SatNOGS par son nom et ajoute le NORAD.
2. **Statut** : un satellite « actif » sans NORAD dans les TLE passe en
   « statut_inconnu » (affiché « Statut non confirmé »). Il n'est pas supprimé.
3. **Découverte** : signale les satellites SatNOGS récents ou à venir absents du
   registre. Ils sont ajoutés seulement avec `--discover`, marqués `a_valider: true`.

## Sources TLE

Union de trois sources, dans l'ordre :

1. `data/omm_local.json` : fichier Space-Track (voir `deploy/README-omm-spacetrack.md`).
2. AMSAT (`nasa.all`) : NORAD à 5 chiffres uniquement.
3. CelesTrak (JSON) : parfois injoignable depuis le Pi.

Une source en échec est signalée et n'arrête pas la synchro. Si aucune source
n'est disponible, le registre n'est pas modifié.

## Utilisation

Depuis la racine du projet :

```bash
python3 tools/sync_satellites.py              # rapport seul, rien n'est écrit
python3 tools/sync_satellites.py --write      # réécrit le registre (sauvegarde .bak)
python3 tools/sync_satellites.py --discover   # ajoute aussi les nouveaux satellites (à valider)
```

Vérifie toujours le rapport avant `--write`.

## Tests

Hors réseau :

```bash
python3 -m unittest test_sync_satellites -v
```

## Limites

- Le registre lu est `data/ham_satellites.json`. Vérifie que l'application
  l'utilise bien ; sinon la synchro n'a pas d'effet à l'écran.
- Le script n'est pas planifié par défaut. Il peut l'être comme `omm_spacetrack.sh`,
  mais CelesTrak demande de ne pas l'interroger plus d'une fois par heure.
