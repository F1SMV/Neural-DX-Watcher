"""
dxcc_resolver.py — Résolution DXCC unifiée via cty.dat
========================================================
Remplace toute logique de découpage naïf d'indicatif (call[:3]) par une
vraie résolution basée sur la base cty.dat déjà téléchargée par webapp.py.

Gère 3 formats d'entrée différents sans distinction requise en amont :
  - un indicatif brut       ("F4ABC", "DL9XYZ/P")
  - un préfixe déjà correct ("DL", "F")
  - un nom d'entité DXCC    ("Germany", "France")  ← cas LoTW identifié comme bug

Usage :
    from dxcc_resolver import get_resolver
    resolver = get_resolver("cty.dat")
    info = resolver.resolve("Germany")   # ou "DL9XYZ", ou "DL"
    # info = {"prefix": "DL", "entity": "Fed. Rep. of Germany",
    #         "continent": "EU", "cq_zone": 14, "itu_zone": 28,
    #         "lat": 51.0, "lon": -10.0}

Si cty.dat est absent ou illisible, le résolveur bascule en mode dégradé
(log un warning une seule fois) et retombe sur un découpage [:3] — l'app
ne casse jamais, elle perd juste la précision directionnelle.
"""

import re
import logging
import unicodedata
from pathlib import Path
from typing import Optional

logger = logging.getLogger("dxcc_resolver")

# Alias manuels pour les variantes de noms d'entité les plus fréquentes
# entre cty.dat et les libellés retournés par LoTW (qui ne suivent pas
# toujours l'intitulé exact de cty.dat).
_ENTITY_ALIASES = {
    "USA": "UNITED STATES OF AMERICA",
    "UNITED STATES": "UNITED STATES OF AMERICA",
    "UK": "ENGLAND",
    "UNITED KINGDOM": "ENGLAND",
    "GREAT BRITAIN": "ENGLAND",
    "RUSSIA": "EUROPEAN RUSSIA",
    "SOUTH KOREA": "REPUBLIC OF KOREA",
    "NORTH KOREA": "DEMOCRATIC PEOPLE'S REP. OF KOREA",
    "CZECH REPUBLIC": "CZECH REP.",
    "SLOVAKIA": "SLOVAK REP.",
    "IVORY COAST": "COTE D'IVOIRE",
    "VATICAN": "VATICAN",
    "VATICAN CITY": "VATICAN",
}


def _normalize_entity_name(name: str) -> str:
    """Normalise un nom d'entité pour comparaison tolérante."""
    if not name:
        return ""
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    n = n.upper().strip()
    n = re.sub(r"[.\-,()]", "", n)
    n = re.sub(r"\s+", " ", n)
    return _ENTITY_ALIASES.get(n, n)


class DXCCResolver:
    """Résolveur unifié : indicatif / préfixe / nom d'entité → info DXCC."""

    def __init__(self, cty_path: str = "cty.dat"):
        self.cty_path = Path(cty_path)
        self.by_prefix: dict[str, dict] = {}      # "DL" -> record
        self.by_entity: dict[str, dict] = {}       # "GERMANY" (normalisé) -> record
        self.exact_calls: dict[str, dict] = {}     # calls exacts en override (=CALL)
        self._degraded = False
        self._warned_degraded = False
        self.reload()

    # ──────────────────────────────────────────────────────────────
    def reload(self):
        """(Re)charge cty.dat. Appelé au démarrage et après un refresh."""
        self.by_prefix.clear()
        self.by_entity.clear()
        self.exact_calls.clear()
        self._degraded = False

        if not self.cty_path.exists():
            self._degraded = True
            if not self._warned_degraded:
                logger.warning(
                    f"dxcc_resolver: {self.cty_path} introuvable — "
                    f"mode dégradé (découpage naïf des indicatifs)."
                )
                self._warned_degraded = True
            return

        try:
            entities_loaded, prefixes_loaded = self._parse_cty(self.cty_path)
            logger.info(
                f"dxcc_resolver: {entities_loaded} entités DXCC, "
                f"{prefixes_loaded} préfixes chargés depuis {self.cty_path}"
            )
            if entities_loaded == 0:
                self._degraded = True
        except Exception as e:
            logger.warning(f"dxcc_resolver: échec parsing cty.dat ({e}) — mode dégradé")
            self._degraded = True

    # ──────────────────────────────────────────────────────────────
    def _parse_cty(self, path: Path) -> tuple[int, int]:
        """
        Parse le fichier cty.dat (format "big cty" standard).
        Structure par entité :
          Nom entité: CQ: ITU: Continent: Lat: Lon: TZ: Préfixe principal;
              alias1,alias2,=CALLEXACT,alias3;
        Le bloc d'alias peut s'étendre sur plusieurs lignes indentées,
        terminé par un ';'. Tolérant aux variations mineures de format —
        chaque enregistrement est parsé indépendamment (un bloc mal formé
        n'interrompt pas le chargement des autres).
        """
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()

        entities_count = 0
        prefixes_count = 0

        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]

            # Une ligne d'en-tête ne commence jamais par un espace et
            # contient au moins 7 ':' dans sa portion initiale.
            if line and not line[0].isspace() and line.count(":") >= 7:
                try:
                    header_part, _, rest_of_line = line.partition(":")
                    fields = [header_part] + line.split(":")[1:8]
                    # Reconstruction propre : on resplit proprement
                    parts = line.split(":")
                    if len(parts) < 8:
                        i += 1
                        continue

                    entity_name = parts[0].strip()
                    cq_zone     = parts[1].strip()
                    itu_zone    = parts[2].strip()
                    continent   = parts[3].strip()
                    lat         = parts[4].strip()
                    lon         = parts[5].strip()
                    # parts[6] = TZ, ignoré
                    # parts[7] = préfixe principal + début éventuel des alias
                    tail = ":".join(parts[7:])

                    primary_prefix_match = re.match(r"\s*([A-Z0-9/]+)", tail)
                    primary_prefix = primary_prefix_match.group(1) if primary_prefix_match else ""

                    record = {
                        "entity":    entity_name,
                        "prefix":    primary_prefix,
                        "continent": continent,
                        "cq_zone":   int(cq_zone) if cq_zone.isdigit() else None,
                        "itu_zone":  int(itu_zone) if itu_zone.isdigit() else None,
                        "lat":       float(lat) if _is_float(lat) else None,
                        "lon":       -float(lon) if _is_float(lon) else None,
                        # cty.dat exprime la longitude West-positive ;
                        # on la convertit en Est-positif (convention standard lat/lon).
                    }

                    if primary_prefix:
                        self.by_prefix[primary_prefix] = record
                        prefixes_count += 1

                    norm_name = _normalize_entity_name(entity_name)
                    if norm_name:
                        self.by_entity[norm_name] = record

                    entities_count += 1

                    # ── Bloc d'alias : TOUJOURS sur les lignes indentées
                    # suivantes, séparément de la déclaration du préfixe
                    # principal sur la ligne d'en-tête (qui se termine par
                    # son propre ';' sans rapport avec la liste d'alias). ──
                    alias_lines = []
                    j = i
                    while j + 1 < n and lines[j + 1] and lines[j + 1][0].isspace():
                        j += 1
                        alias_lines.append(lines[j])
                        if ";" in lines[j]:
                            break
                    i = j

                    alias_text = " ".join(alias_lines).split(";")[0]
                    tokens = [t.strip() for t in alias_text.split(",") if t.strip()]
                    for tok in tokens:
                        self._index_alias_token(tok, record)
                        prefixes_count += 1

                except Exception:
                    pass  # bloc malformé — on continue sur les suivants

            i += 1

        return entities_count, prefixes_count

    def _index_alias_token(self, token: str, record: dict):
        """Indexe un token d'alias (préfixe simple, override zone, ou call exact)."""
        # Retirer les qualificatifs entre parenthèses/crochets : DL(10)[27]
        clean = re.sub(r"[\(\[\{][^\)\]\}]*[\)\]\}]", "", token).strip()
        if not clean:
            return
        # Callsign exact override : =DL9ABC
        if clean.startswith("="):
            call = clean[1:].strip()
            if call:
                self.exact_calls[call.upper()] = record
            return
        # Plage de préfixes : "D40-D49" ou "D3A-D3Z" (même longueur, un seul
        # caractère final qui varie) → expansion complète, peu coûteuse et
        # couvre la grande majorité des plages réelles de cty.dat.
        if "-" in clean:
            lo, _, hi = clean.partition("-")
            lo, hi = lo.strip(), hi.strip()
            if len(lo) == len(hi) and len(lo) >= 1 and lo[:-1] == hi[:-1]:
                c_lo, c_hi = lo[-1], hi[-1]
                if c_lo.isdigit() and c_hi.isdigit() and c_lo <= c_hi:
                    for d in range(int(c_lo), int(c_hi) + 1):
                        self.by_prefix.setdefault(f"{lo[:-1]}{d}", record)
                    return
                if c_lo.isalpha() and c_hi.isalpha() and c_lo <= c_hi:
                    for code in range(ord(c_lo), ord(c_hi) + 1):
                        self.by_prefix.setdefault(f"{lo[:-1]}{chr(code)}", record)
                    return
            # Plage non expansible simplement : on indexe au moins la borne basse
            clean = lo
        if clean:
            self.by_prefix.setdefault(clean.upper(), record)

    # ──────────────────────────────────────────────────────────────
    def resolve(self, value: str) -> Optional[dict]:
        """
        Résout une valeur (indicatif, préfixe, ou nom d'entité) vers un
        enregistrement DXCC complet. Retourne None si rien ne correspond
        et que le mode dégradé n'a pas de fallback pertinent.
        """
        if not value:
            return None
        value = value.strip()

        if self._degraded:
            # Mode dégradé : découpage naïf, mais AU MOINS explicite et tracé
            prefix = value.upper().split("/")[0][:3]
            return {"prefix": prefix, "entity": "", "continent": "",
                    "cq_zone": None, "itu_zone": None, "lat": None, "lon": None,
                    "degraded": True}

        # 1. Essai comme nom d'entité (le cas LoTW identifié comme bug)
        norm = _normalize_entity_name(value)
        if norm in self.by_entity:
            return self.by_entity[norm]

        # 1b. Fallback tolérant : les noms LoTW sont souvent des versions
        # courtes du nom cty.dat ("Germany" vs "Fed. Rep. of Germany").
        # On cherche une correspondance par mot entier inclus dans le nom.
        if len(norm) >= 3:
            for entity_key, rec in self.by_entity.items():
                entity_words = entity_key.split()
                norm_words = norm.split()
                if any(w in entity_words for w in norm_words if len(w) >= 4):
                    return rec

        # 2. Essai comme indicatif exact (override cty.dat)
        call_upper = value.upper()
        if call_upper in self.exact_calls:
            return self.exact_calls[call_upper]

        # 3. Essai comme indicatif : découpage du suffixe portable (/P, /MM, /5...)
        base_call = call_upper.split("/")[0]
        if base_call in self.exact_calls:
            return self.exact_calls[base_call]

        # 4. Recherche du préfixe le plus long qui matche (longest-prefix-match)
        for length in range(min(len(base_call), 6), 0, -1):
            candidate = base_call[:length]
            if candidate in self.by_prefix:
                return self.by_prefix[candidate]

        # 5. Rien trouvé : fallback naïf mais marqué comme tel
        return {"prefix": base_call[:3], "entity": "", "continent": "",
                "cq_zone": None, "itu_zone": None, "lat": None, "lon": None,
                "unresolved": True}

    def is_degraded(self) -> bool:
        return self._degraded

    def stats(self) -> dict:
        return {
            "entities": len(self.by_entity),
            "prefixes": len(self.by_prefix),
            "exact_calls": len(self.exact_calls),
            "degraded": self._degraded,
        }


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


# ──────────────────────────────────────────────────────────────────
# Singleton — un seul chargement de cty.dat partagé par toute l'app
# ──────────────────────────────────────────────────────────────────
_resolver_instance: Optional[DXCCResolver] = None


def get_resolver(cty_path: str = "cty.dat") -> DXCCResolver:
    """Retourne le résolveur singleton, en le créant au premier appel."""
    global _resolver_instance
    if _resolver_instance is None:
        _resolver_instance = DXCCResolver(cty_path)
    return _resolver_instance


def reload_resolver():
    """À appeler après un téléchargement d'une nouvelle version de cty.dat."""
    if _resolver_instance is not None:
        _resolver_instance.reload()
