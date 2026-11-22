# Mise à jour quotidienne des TLE (Space-Track)

Télécharge chaque nuit les éléments orbitaux (OMM JSON) des satellites
configurés, depuis Space-Track, dans `data/omm_local.json`.
Ce fichier est lu en premier par l'application. Il contient les NORAD > 99999
(notation Alpha-5, ex. 101101 = UNNE-1B), absents du fichier AMSAT.

## Fichiers

- `deploy/omm_spacetrack.sh` : le script de téléchargement.
- `data/satellites_config.json` : la liste des satellites suivis (champ `norad`, `active`).
- `data/omm_local.json` : le résultat, régénéré chaque nuit (ne pas committer).
- `~/.config/neural-dx/spacetrack.env` : tes identifiants (hors dépôt, ne pas committer).

## Installation (à faire une fois, par machine)

1. Créer un compte gratuit sur https://www.space-track.org.

2. Créer le fichier d'identifiants, avec les droits restreints :

   ```bash
   mkdir -p ~/.config/neural-dx
   nano ~/.config/neural-dx/spacetrack.env
   ```

   Contenu, sans guillemets :

   ```
   SPACETRACK_USER=ton_identifiant
   SPACETRACK_PASS=ton_mot_de_passe
   ```

   Puis : `chmod 600 ~/.config/neural-dx/spacetrack.env`

3. Rendre le script exécutable et le tester :

   ```bash
   chmod +x ~/Neural-DX-Watcher/deploy/omm_spacetrack.sh
   ~/Neural-DX-Watcher/deploy/omm_spacetrack.sh
   ```

   Résultat attendu : `... Space-Track OK: N objets`.

4. Planifier l'exécution quotidienne à 04:30 :

   ```bash
   (crontab -l 2>/dev/null; echo '30 4 * * * /home/eric/Neural-DX-Watcher/deploy/omm_spacetrack.sh >> /home/eric/Neural-DX-Watcher/omm_spacetrack.log 2>&1') | crontab -
   crontab -l
   ```

   Adapte le chemin `/home/eric/...` au compte utilisé.

## Vérification

```bash
tail -5 ~/Neural-DX-Watcher/omm_spacetrack.log
ls -l ~/Neural-DX-Watcher/data/omm_local.json
```

Le log doit contenir `Space-Track OK` avec la date de la nuit. La date de
modification du fichier doit être 04:30 (heure locale).

## Ajouter un satellite

Ajoute une entrée dans `data/satellites_config.json` avec son NORAD et
`"active": true`, puis relance le script. Le cron le prendra en compte la nuit suivante.

## Dépannage

- `Login Failed` ou `401` : identifiants incorrects dans `spacetrack.env`.
- Log vide : vérifier le cron avec `journalctl -u cron --since "04:00"`.
- `mv : ... .tmp introuvable` : deux exécutions simultanées. Vérifier `crontab -l` (pas de doublon).
