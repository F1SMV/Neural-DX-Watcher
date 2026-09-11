"""
analytics.py — Moteur d'analytique DX — NEURAL DX WATCHER v12.5
================================================================
Insights calculés sur l'historique des spots reçus.

SOURCES DE DONNÉES, PAR ORDRE DE PRIORITÉ
------------------------------------------
Le module ne dépend d'aucun composant externe pour fonctionner. Il essaie
successivement :

  1. `data/analytics.sqlite` — sa PROPRE base, alimentée par
     `record_spot()` appelé depuis webapp.py au moment où le spot arrive.
     C'est la source de référence : son écriture est maîtrisée ici, donc
     garantie.

  2. `data/predictor.sqlite` (table `spot_log`) — la base du module
     `predictor`, si celui-ci tourne. Utilisée en complément quand elle
     contient davantage d'historique.

  3. Les spots en mémoire transmis par l'appelant — repli immédiat qui
     permet d'afficher quelque chose dès le premier démarrage, sans
     attendre qu'une base se constitue.

Cette redondance existe parce que `predictor.py` est optionnel : quand il
n'est pas importable, webapp.py lui substitue un stub dont `record_spot`
ne fait rien, silencieusement. Une analytique qui n'aurait dépendu que de
lui serait restée vide indéfiniment sans le moindre message d'erreur.

DEUX PRINCIPES DE CONCEPTION
----------------------------

1. **Adaptatif au volume réel.** Une base qui vient d'être créée ne
   contient que quelques heures. Des fenêtres figées à 30 jours
   produiraient des grilles vides et des probabilités nulles partout. Le
   module mesure la profondeur réelle de l'historique (`span_hours`) et
   choisit ses fenêtres et seuils en conséquence, en annonçant son niveau
   de maturité (`maturity`) pour que l'interface sache quoi montrer.

2. **Agrégation côté SQL.** Les comptages sont faits par SQLite
   (`GROUP BY` sur le créneau horaire), pas en Python : sur 130 000 spots
   cela ramène quelques milliers de lignes au lieu de 130 000. Les
   correspondances date→(jour, heure) sont calculées en arithmétique
   modulaire plutôt qu'avec `datetime.fromtimestamp`, dont le coût
   unitaire dominait le temps total.

Robustesse : les schémas sont découverts à l'exécution (`PRAGMA
table_info`). Toute source absente ou incompatible est ignorée au profit
de la suivante ; si aucune n'est exploitable, chaque fonction renvoie une
structure de même forme marquée `available: False`, jamais une valeur
inventée.

Absence de donnée ≠ absence de condition : un créneau sans historique est
rendu `null`, pas `0`.
"""

import os
import sqlite3
import threading
import time
from typing import Optional

# Index 0 = lundi, conforme à datetime.weekday()
WEEKDAY_LABELS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]

# Le 1er janvier 1970 (epoch) était un jeudi, soit weekday() == 3. Cette
# constante permet de déduire le jour de la semaine d'un créneau horaire
# par simple arithmétique, sans construire d'objet datetime.
EPOCH_WEEKDAY = 3

_COLUMN_CANDIDATES = {
    "ts":      ["ts", "timestamp", "time", "spot_ts"],
    "band":    ["band"],
    "call":    ["dx_call", "call", "dxcall", "callsign"],
    "country": ["country", "dxcc", "entity"],
    "mode":    ["mode"],
}

# Base propre au module (écriture maîtrisée) et base optionnelle du
# module predictor (lecture seule, peut ne jamais se remplir).
OWN_DB_PATH = "data/analytics.sqlite"
OWN_TABLE = "spots"
PREDICTOR_DB_PATH = "data/predictor.sqlite"
PREDICTOR_TABLE = "spot_log"

DEFAULT_DB_PATH = OWN_DB_PATH
DEFAULT_TABLE = OWN_TABLE

# Rétention : au-delà, les lignes sont purgées. 90 jours correspond à la
# fenêtre déjà retenue par predictor pour rester cohérent.
RETENTION_DAYS = 90

# ── Paliers de maturité de l'historique ───────────────────────────────
# En dessous de 6h on ne prétend rien analyser ; l'interface affiche une
# simple jauge de collecte. Les paliers suivants débloquent les analyses
# à mesure que l'échantillon devient significatif.
MATURITY_LEVELS = [
    # (span minimal en heures, identifiant, libellé)
    (0,        "collecting", "Collecte en cours"),
    (6,        "basic",      "Profil horaire"),
    (48,       "daily",      "Tendances quotidiennes"),
    (14 * 24,  "weekly",     "Analyse hebdomadaire"),
]


class SchemaUnavailable(Exception):
    """Base absente, table manquante ou colonnes indispensables absentes."""


# ═══════════════════════════════════════════════════════════════════════
# Écriture — base propre au module
# ═══════════════════════════════════════════════════════════════════════

_write_lock = threading.Lock()
_write_state = {"ready": False, "path": None, "errors": 0, "written": 0,
                "last_error": None, "last_write_ts": None}


def init_store(db_path: str = OWN_DB_PATH) -> bool:
    """
    Crée la base d'analytique si nécessaire. Idempotent.

    Appelé une fois au démarrage de webapp.py. Un échec n'est pas fatal :
    le module se rabattra sur les autres sources, et `store_status()`
    permet d'en rendre compte à l'exploitant.
    """
    with _write_lock:
        try:
            directory = os.path.dirname(db_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            conn = sqlite3.connect(db_path, timeout=5.0)
            try:
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {OWN_TABLE} ("
                    "  ts REAL NOT NULL,"
                    "  band TEXT NOT NULL,"
                    "  dx_call TEXT,"
                    "  mode TEXT,"
                    "  country TEXT"
                    ")"
                )
                # L'index doit être créé après la table, jamais dans le
                # même executescript qu'un ALTER TABLE.
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{OWN_TABLE}_ts "
                    f"ON {OWN_TABLE}(ts)"
                )
                conn.commit()
            finally:
                conn.close()
            _write_state.update(ready=True, path=db_path, last_error=None)
            return True
        except Exception as exc:
            _write_state.update(ready=False, path=db_path, last_error=str(exc))
            return False


def record_spot(spot: dict, db_path: str = OWN_DB_PATH) -> bool:
    """
    Enregistre un spot dans la base d'analytique.

    Conçu pour être appelé sur le chemin critique de réception : toute
    erreur est absorbée et comptabilisée plutôt que propagée, un défaut
    d'analytique ne devant jamais interrompre la collecte des spots.
    """
    if not spot:
        return False

    band = str(spot.get("band") or "").strip()
    if not band:
        return False

    ts = spot.get("timestamp")
    if ts is None:
        ts = time.time()
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        return False

    with _write_lock:
        if not _write_state["ready"]:
            # Première tentative après un échec d'init : on réessaie une
            # fois, la base ayant pu être créée entre-temps.
            pass
        try:
            conn = sqlite3.connect(db_path, timeout=2.0)
            try:
                conn.execute(
                    f"INSERT INTO {OWN_TABLE} (ts, band, dx_call, mode, country) "
                    "VALUES (?,?,?,?,?)",
                    (ts, band,
                     str(spot.get("dx_call") or "")[:32],
                     str(spot.get("mode") or "")[:16],
                     str(spot.get("country") or "")[:64]),
                )
                conn.commit()
            finally:
                conn.close()
            _write_state["written"] += 1
            _write_state["last_write_ts"] = ts
            _write_state["ready"] = True
            return True
        except Exception as exc:
            _write_state["errors"] += 1
            _write_state["last_error"] = str(exc)
            return False


def cleanup_store(days: int = RETENTION_DAYS, db_path: str = OWN_DB_PATH) -> int:
    """Purge les lignes au-delà de la rétention. Retourne le nombre supprimé."""
    cutoff = time.time() - days * 86400
    with _write_lock:
        try:
            conn = sqlite3.connect(db_path, timeout=5.0)
            try:
                cur = conn.execute(f"DELETE FROM {OWN_TABLE} WHERE ts < ?", (cutoff,))
                conn.commit()
                return cur.rowcount or 0
            finally:
                conn.close()
        except Exception as exc:
            _write_state["last_error"] = str(exc)
            return 0


def store_status(db_path: str = OWN_DB_PATH) -> dict:
    """
    État de la collecte — sert au diagnostic quand la page reste vide.

    Distingue les causes possibles : base jamais créée, créée mais jamais
    écrite, ou écrite mais avec des erreurs.
    """
    status = {
        "path": db_path,
        "exists": os.path.exists(db_path),
        "writes_ok": _write_state["written"],
        "write_errors": _write_state["errors"],
        "last_error": _write_state["last_error"],
        "rows": 0, "first_ts": None, "last_ts": None, "span_hours": 0.0,
    }
    if not status["exists"]:
        return status
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3.0)
        try:
            cur = conn.execute(
                f"SELECT COUNT(*), MIN(ts), MAX(ts) FROM {OWN_TABLE}")
            n, first, last = cur.fetchone()
            status["rows"] = int(n or 0)
            status["first_ts"] = first
            status["last_ts"] = last
            if first and last:
                status["span_hours"] = round((float(last) - float(first)) / 3600, 1)
        finally:
            conn.close()
    except Exception as exc:
        status["last_error"] = str(exc)
    return status


# ═══════════════════════════════════════════════════════════════════════
# Lecture — agrégation déléguée à SQLite
# ═══════════════════════════════════════════════════════════════════════

def _connect(db_path: str):
    """Ouvre la base en lecture seule (aucune écriture possible)."""
    if not os.path.exists(db_path):
        raise SchemaUnavailable(f"base absente: {db_path}")
    try:
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error as exc:
        raise SchemaUnavailable(f"connexion échouée: {exc}") from exc


def _resolve_schema(conn, table: str) -> dict:
    """Introspecte le schéma réel : rôle logique -> nom de colonne."""
    cur = conn.cursor()
    try:
        cur.execute(f"PRAGMA table_info({table})")
        rows = cur.fetchall()
    except sqlite3.Error as exc:
        raise SchemaUnavailable(f"PRAGMA échoué: {exc}") from exc

    if not rows:
        raise SchemaUnavailable(f"table '{table}' introuvable")

    present = {str(r[1]).lower(): str(r[1]) for r in rows}
    mapping = {
        role: next((present[c.lower()] for c in cands if c.lower() in present), None)
        for role, cands in _COLUMN_CANDIDATES.items()
    }

    if not mapping["ts"] or not mapping["band"]:
        raise SchemaUnavailable("colonnes 'ts' et/ou 'band' absentes")
    return mapping


def _query_source(db_path: str, table: str, hours: int, now: float):
    """
    Interroge UNE source et renvoie (slots, span) ou lève SchemaUnavailable.

    Le regroupement est fait par SQLite : une ligne par couple
    (heure, bande) présent, au lieu d'une ligne par spot.
    """
    cutoff = now - hours * 3600
    conn = _connect(db_path)
    try:
        schema = _resolve_schema(conn, table)
        ts_col, band_col = schema["ts"], schema["band"]
        cur = conn.cursor()

        try:
            cur.execute(
                f"SELECT MIN({ts_col}), MAX({ts_col}), COUNT(*) FROM {table} "
                f"WHERE {ts_col} > 0 AND {ts_col} <= ?", (now + 3600,))
            first_ts, last_ts, total = cur.fetchone()
        except sqlite3.Error as exc:
            raise SchemaUnavailable(f"SELECT étendue échoué: {exc}") from exc

        try:
            cur.execute(
                f"SELECT CAST({ts_col} / 3600 AS INTEGER) AS slot, {band_col}, COUNT(*) "
                f"FROM {table} "
                f"WHERE {ts_col} >= ? AND {ts_col} <= ? AND {band_col} IS NOT NULL "
                f"AND {band_col} != '' GROUP BY slot, {band_col}",
                (cutoff, now + 3600))
            rows = cur.fetchall()
        except sqlite3.Error as exc:
            raise SchemaUnavailable(f"SELECT agrégé échoué: {exc}") from exc
    finally:
        conn.close()

    slots = {}
    for slot, band, count in rows:
        if slot is None or band is None:
            continue
        slots.setdefault(int(slot), {})[str(band).strip()] = int(count)

    span_hours = 0.0
    if first_ts and last_ts:
        try:
            span_hours = max(0.0, (float(last_ts) - float(first_ts)) / 3600.0)
        except (TypeError, ValueError):
            span_hours = 0.0

    return slots, {"first_ts": first_ts, "last_ts": last_ts,
                   "total": int(total or 0), "span_hours": round(span_hours, 1)}


def _slots_from_memory(spots, hours: int, now: float):
    """
    Repli : agrège une séquence de spots en mémoire (spot_history).

    Permet d'afficher l'activité récente dès le premier démarrage, avant
    qu'aucune base n'ait eu le temps de se constituer.
    """
    cutoff = now - hours * 3600
    slots = {}
    first_ts = last_ts = None
    total = 0

    for s in spots or ():
        try:
            ts = float(s.get("timestamp") or 0)
        except (TypeError, ValueError, AttributeError):
            continue
        if ts < cutoff or ts > now + 3600:
            continue
        band = str(s.get("band") or "").strip()
        if not band:
            continue
        slot = int(ts // 3600)
        slots.setdefault(slot, {})
        slots[slot][band] = slots[slot].get(band, 0) + 1
        total += 1
        first_ts = ts if first_ts is None else min(first_ts, ts)
        last_ts = ts if last_ts is None else max(last_ts, ts)

    span_hours = ((last_ts - first_ts) / 3600.0) if (first_ts and last_ts) else 0.0
    return slots, {"first_ts": first_ts, "last_ts": last_ts, "total": total,
                   "span_hours": round(span_hours, 1)}


def _load_aggregated(db_path: str, hours: int, now: float,
                     table: str = None, memory_spots=None):
    """
    Charge l'activité agrégée en essayant les sources par ordre de
    priorité, et retient celle qui offre le plus d'historique.

    Interroger toutes les sources coûte deux requêtes indexées ; c'est
    négligeable devant le risque de rester aveugle parce que la source
    supposée ne se remplit pas.
    """
    candidates = []

    # Source explicitement demandée (tests, diagnostic)
    if table is not None:
        try:
            return _query_source(db_path, table, hours, now)
        except SchemaUnavailable:
            raise

    # Chemin fourni : les deux conventions de nommage sont essayées, ce
    # qui permet de viser directement une base predictor si besoin. Puis
    # la base predictor à son emplacement habituel. La déduplication
    # évite d'interroger deux fois la même paire.
    seen = set()
    for path, tbl in ((db_path, OWN_TABLE),
                      (db_path, PREDICTOR_TABLE),
                      (PREDICTOR_DB_PATH, PREDICTOR_TABLE)):
        if (path, tbl) in seen:
            continue
        seen.add((path, tbl))
        try:
            slots, span = _query_source(path, tbl, hours, now)
            if span["total"] > 0:
                candidates.append((slots, span, f"{path}:{tbl}"))
        except SchemaUnavailable:
            continue

    if memory_spots:
        slots, span = _slots_from_memory(memory_spots, hours, now)
        if span["total"] > 0:
            candidates.append((slots, span, "memory"))

    if not candidates:
        detail = "base absente" if not os.path.exists(db_path) else "aucune donnée"
        raise SchemaUnavailable(
            f"aucune source de spots exploitable — {detail} "
            f"({db_path}, {PREDICTOR_DB_PATH}, mémoire)")

    # On privilégie la profondeur d'historique ; à profondeur égale, le
    # volume. Une base longue mais creuse reste préférable à 24h denses
    # pour les analyses hebdomadaires.
    slots, span, source = max(
        candidates, key=lambda c: (c[1]["span_hours"], c[1]["total"]))
    span = dict(span)
    span["source"] = source
    return slots, span


def _slot_weekday_hour(slot: int):
    """
    (jour de semaine, heure UTC) d'un créneau, sans objet datetime.

    slot = timestamp // 3600, donc slot % 24 donne l'heure UTC et
    slot // 24 le numéro de jour depuis l'epoch — un jeudi, d'où le
    décalage EPOCH_WEEKDAY.
    """
    hour = slot % 24
    weekday = (slot // 24 + EPOCH_WEEKDAY) % 7
    return weekday, hour


def _maturity(span_hours: float) -> dict:
    """Niveau d'analyse permis par la profondeur d'historique disponible."""
    level_id, label = MATURITY_LEVELS[0][1], MATURITY_LEVELS[0][2]
    for min_h, lid, lbl in MATURITY_LEVELS:
        if span_hours >= min_h:
            level_id, label = lid, lbl

    # Palier suivant, pour annoncer ce qui se débloquera et quand.
    nxt = next(((h, lbl) for h, lid, lbl in MATURITY_LEVELS if span_hours < h), None)

    return {
        "level": level_id,
        "label": label,
        "span_hours": round(span_hours, 1),
        "next_level": nxt[1] if nxt else None,
        "next_at_hours": nxt[0] if nxt else None,
        "hours_remaining": round(max(0.0, nxt[0] - span_hours), 1) if nxt else None,
    }


def _empty(reason: str, **shape) -> dict:
    """
    Réponse indisponible conservant la forme de la réponse pleine.

    L'appelant peut itérer sans garde et se fier au seul drapeau
    `available` : sans cela un `data.slots.forEach(...)` planterait
    précisément quand la base manque, c'est-à-dire quand on veut dégrader
    proprement.
    """
    base = {"available": False, "reason": reason}
    base.update(shape)
    return base


# ═══════════════════════════════════════════════════════════════════════
# 1. ACTIVITÉ RÉCENTE — utile dès la première heure
# ═══════════════════════════════════════════════════════════════════════

def compute_recent(db_path: str = DEFAULT_DB_PATH, hours: int = 24,
                   now: Optional[float] = None, preloaded=None,
                   memory_spots=None) -> dict:
    """
    Activité heure par heure sur les dernières `hours`, et classement des
    bandes sur la même fenêtre.

    C'est la seule analyse qui ne demande aucun historique : elle est
    exploitable dès les premières minutes de collecte et sert de contenu
    principal tant que les analyses long terme ne sont pas mûres.
    """
    if now is None:
        now = time.time()

    empty_shape = {
        "hours": hours, "series": [], "bands": [],
        "total": 0, "peak": 0, "maturity": _maturity(0),
    }

    try:
        slots, span = preloaded if preloaded else _load_aggregated(
            db_path, hours, now, memory_spots=memory_spots)
    except SchemaUnavailable as exc:
        return _empty(str(exc), **empty_shape)

    maturity = _maturity(span["span_hours"])

    if not slots:
        return _empty("aucun spot récent", **{**empty_shape, "maturity": maturity})

    current_slot = int(now // 3600)
    series, band_totals = [], {}

    for offset in range(hours - 1, -1, -1):
        slot = current_slot - offset
        per_band = slots.get(slot, {})
        count = sum(per_band.values())
        _wd, hour = _slot_weekday_hour(slot)
        series.append({"hours_ago": offset, "hour_utc": hour, "count": count})
        for band, n in per_band.items():
            band_totals[band] = band_totals.get(band, 0) + n

    bands = sorted(
        ({"band": b, "count": n} for b, n in band_totals.items()),
        key=lambda x: -x["count"],
    )
    total = sum(band_totals.values())
    peak = max((p["count"] for p in series), default=0)

    return {
        "available": True, "hours": hours, "series": series,
        "bands": bands, "total": total, "peak": peak,
        "maturity": maturity,
    }


# ═══════════════════════════════════════════════════════════════════════
# 2. HEATMAP — quand est-ce que ça ouvre habituellement ?
# ═══════════════════════════════════════════════════════════════════════

def compute_heatmap(db_path: str = DEFAULT_DB_PATH, days: int = 30,
                    band: Optional[str] = None,
                    now: Optional[float] = None, preloaded=None,
                    memory_spots=None) -> dict:
    """
    Activité moyenne par (jour de semaine × heure UTC).

    La fenêtre demandée est ramenée à l'historique réellement disponible :
    inutile de balayer 30 jours quand la base en contient deux, cela ne
    produirait que des cases vides et du temps de calcul perdu.

    La valeur d'une case est une MOYENNE par occurrence, pas un total :
    sur 30 jours il y a environ quatre mardis, un cumul brut avantagerait
    donc mécaniquement les jours les mieux représentés dans la fenêtre.

    Une case jamais observée vaut None (et non 0) : on ne prétend pas
    qu'il n'y a « pas d'activité » là où l'on n'a pas encore regardé.
    """
    if now is None:
        now = time.time()

    empty_shape = {
        "grid": [[None] * 24 for _ in range(7)],
        "weekday_labels": WEEKDAY_LABELS,
        "peak_value": 0.0, "best_slot": None, "total_spots": 0,
        "days": days, "band": band, "maturity": _maturity(0),
    }

    try:
        slots, span = preloaded if preloaded else _load_aggregated(
            db_path, days * 24, now, memory_spots=memory_spots)
    except SchemaUnavailable as exc:
        return _empty(str(exc), **empty_shape)

    maturity = _maturity(span["span_hours"])
    empty_shape["maturity"] = maturity

    # Une heatmap hebdomadaire n'a de sens qu'avec plusieurs occurrences
    # de chaque jour de semaine. En dessous, `compute_recent` est plus
    # informatif et l'interface l'affiche à la place.
    if span["span_hours"] < 48:
        return _empty("historique trop court pour une vue hebdomadaire",
                      **empty_shape)

    if not slots:
        return _empty("aucun spot sur la période", **empty_shape)

    # Fenêtre effective : bornée par ce que contient réellement la base.
    effective_hours = int(min(days * 24, max(48, span["span_hours"])))
    current_slot = int(now // 3600)
    first_slot = current_slot - effective_hours

    counts = [[0] * 24 for _ in range(7)]
    occurrences = [[0] * 24 for _ in range(7)]
    total_spots = 0

    # Un seul balayage des créneaux de la fenêtre. Chaque créneau écoulé
    # compte comme une occurrence de son (jour, heure) — qu'il ait vu des
    # spots ou non — ce qui donne le dénominateur de la moyenne.
    for slot in range(first_slot, current_slot + 1):
        wd, hr = _slot_weekday_hour(slot)
        occurrences[wd][hr] += 1
        per_band = slots.get(slot)
        if not per_band:
            continue
        n = per_band.get(band, 0) if band else sum(per_band.values())
        counts[wd][hr] += n
        total_spots += n

    grid = [
        [round(counts[wd][hr] / occurrences[wd][hr], 2)
         if occurrences[wd][hr] > 0 else None
         for hr in range(24)]
        for wd in range(7)
    ]

    observed = [v for row in grid for v in row if v is not None]
    peak_value = max(observed) if observed else 0.0

    best = None
    if peak_value > 0:
        for wd in range(7):
            for hr in range(24):
                if grid[wd][hr] == peak_value:
                    best = {"weekday": wd, "weekday_label": WEEKDAY_LABELS[wd],
                            "hour": hr, "value": peak_value}
                    break
            if best:
                break

    return {
        "available": True, "grid": grid, "weekday_labels": WEEKDAY_LABELS,
        "peak_value": peak_value, "best_slot": best,
        "total_spots": total_spots,
        "days": round(effective_hours / 24, 1), "band": band,
        "maturity": maturity,
    }


# ═══════════════════════════════════════════════════════════════════════
# 3. PATTERNS — qu'est-ce qui monte / descend ?
# ═══════════════════════════════════════════════════════════════════════

# En deçà de cette variation, on parle de stabilité : le bruit
# d'échantillonnage domine sur des volumes quotidiens de cet ordre.
TREND_THRESHOLD_PCT = 15.0

# Sous ce volume sur la période récente, aucune tendance n'est qualifiée :
# 3 spots contre 1 font « +200 % » sans rien signifier.
MIN_SPOTS_FOR_TREND = 10


def compute_patterns(db_path: str = DEFAULT_DB_PATH,
                     window_days: Optional[int] = None,
                     now: Optional[float] = None, preloaded=None,
                     memory_spots=None) -> dict:
    """
    Tendance par bande : une fenêtre récente comparée à la précédente.

    La largeur de fenêtre s'adapte à l'historique disponible (moitié de
    l'étendue, plafonnée à 7 jours) afin que la comparaison soit possible
    dès une douzaine d'heures de collecte, au lieu d'attendre deux
    semaines pour afficher quoi que ce soit.

    Une bande sous MIN_SPOTS_FOR_TREND est marquée `insufficient` : elle
    reste affichée — savoir qu'une bande est calme est une information —
    mais sans pourcentage trompeur.
    """
    if now is None:
        now = time.time()

    empty_shape = {
        "bands": [], "window_days": window_days or 7, "window_hours": 0,
        "total_recent": 0, "total_previous": 0, "maturity": _maturity(0),
    }

    try:
        # On sonde large : la fenêtre réelle est décidée après lecture de
        # l'étendue effective de l'historique.
        max_hours = (window_days * 48) if window_days else 14 * 24
        slots, span = preloaded if preloaded else _load_aggregated(
            db_path, max_hours, now, memory_spots=memory_spots)
    except SchemaUnavailable as exc:
        return _empty(str(exc), **empty_shape)

    maturity = _maturity(span["span_hours"])
    empty_shape["maturity"] = maturity

    if not slots:
        return _empty("aucun spot sur la période", **empty_shape)

    # Comparer deux fenêtres suppose que l'historique les couvre toutes
    # les deux. En deçà, la fenêtre « précédente » serait vide et chaque
    # bande apparaîtrait en forte hausse — un artefact, pas une tendance.
    if not window_days and span["span_hours"] < 12:
        return _empty("historique trop court pour comparer deux périodes",
                      **empty_shape)

    if window_days:
        window_hours = window_days * 24
    else:
        # Deux fenêtres comparables doivent tenir dans l'historique : on
        # prend donc la moitié de l'étendue, bornée à [6h, 7j].
        window_hours = int(max(6, min(7 * 24, span["span_hours"] / 2)))

    current_slot = int(now // 3600)
    split_slot = current_slot - window_hours
    first_slot = current_slot - 2 * window_hours

    recent, previous = {}, {}
    for slot, per_band in slots.items():
        if slot <= first_slot or slot > current_slot:
            continue
        bucket = recent if slot > split_slot else previous
        for b, n in per_band.items():
            bucket[b] = bucket.get(b, 0) + n

    window_days_eff = window_hours / 24.0
    bands = []
    for b in set(recent) | set(previous):
        r, p = recent.get(b, 0), previous.get(b, 0)

        if r < MIN_SPOTS_FOR_TREND:
            trend, change_pct = "insufficient", None
        elif p == 0:
            # Activité nouvelle : réelle, mais non chiffrable en pourcentage.
            trend, change_pct = "up", None
        else:
            change_pct = round((r - p) / p * 100, 1)
            trend = ("up" if change_pct > TREND_THRESHOLD_PCT else
                     "down" if change_pct < -TREND_THRESHOLD_PCT else "stable")

        bands.append({
            "band": b, "recent_count": r, "previous_count": p,
            "change_pct": change_pct, "trend": trend,
            "daily_avg": round(r / window_days_eff, 1) if window_days_eff else 0.0,
        })

    bands.sort(key=lambda x: -x["recent_count"])

    return {
        "available": True, "bands": bands,
        "window_days": round(window_days_eff, 1),
        "window_hours": window_hours,
        "total_recent": sum(recent.values()),
        "total_previous": sum(previous.values()),
        "maturity": maturity,
    }


# ═══════════════════════════════════════════════════════════════════════
# 4. FORECAST — ça vaut le coup de monter dans N heures ?
# ═══════════════════════════════════════════════════════════════════════

# Occurrences minimales d'un créneau avant d'oser afficher une
# probabilité. Sous ce seuil, « 1 fois sur 2 » ne veut rien dire.
MIN_OCCURRENCES_FOR_FORECAST = 3


def compute_forecast(db_path: str = DEFAULT_DB_PATH, hours_ahead: int = 6,
                     days: int = 30, band: Optional[str] = None,
                     now: Optional[float] = None, preloaded=None,
                     memory_spots=None) -> dict:
    """
    Pour chacune des `hours_ahead` prochaines heures, la fréquence
    d'activité observée sur le même créneau par le passé.

    Deux modes selon l'historique disponible, toujours annoncés par le
    champ `basis` pour que l'affichage reste honnête :

      - `weekday` : même jour de semaine ET même heure. Le plus pertinent
        (l'activité radio a un rythme hebdomadaire), mais exige plusieurs
        semaines de recul.
      - `hour` : même heure, tous jours confondus. Disponible dès un jour
        ou deux ; moins précis, mais bien plus informatif que rien.

    `probability` = créneaux ayant vu au moins un spot / créneaux observés.
    C'est une fréquence constatée, pas une prévision de propagation.
    """
    if now is None:
        now = time.time()

    empty_shape = {
        "slots": [], "best_slot": None, "days_analyzed": days,
        "band": band, "basis": None, "maturity": _maturity(0),
    }

    try:
        slots, span = preloaded if preloaded else _load_aggregated(
            db_path, days * 24, now, memory_spots=memory_spots)
    except SchemaUnavailable as exc:
        return _empty(str(exc), **empty_shape)

    maturity = _maturity(span["span_hours"])
    empty_shape["maturity"] = maturity

    if not slots:
        return _empty("aucun spot sur la période", **empty_shape)

    # Choix de la base de comparaison. Le mode `weekday` est plus
    # pertinent mais exige plusieurs occurrences de chaque jour de
    # semaine ; l'adopter trop tôt ferait REGRESSER l'affichage (des
    # créneaux chiffrés en mode horaire redeviendraient inconnus). On
    # calcule donc les deux et on ne retient `weekday` que s'il couvre au
    # moins autant de créneaux — la précision ne doit jamais se payer
    # d'une perte d'information.
    effective_hours = int(min(days * 24, max(24, span["span_hours"])))
    current_slot = int(now // 3600)
    first_slot = current_slot - effective_hours

    def _index(by_weekday: bool):
        """Occurrences, créneaux actifs et volume, par clé de regroupement."""
        observed, active, volume = {}, {}, {}
        for slot in range(first_slot, current_slot + 1):
            wd, hr = _slot_weekday_hour(slot)
            key = (wd, hr) if by_weekday else hr
            observed[key] = observed.get(key, 0) + 1
            per_band = slots.get(slot)
            if not per_band:
                continue
            n = per_band.get(band, 0) if band else sum(per_band.values())
            if n > 0:
                active[key] = active.get(key, 0) + 1
                volume[key] = volume.get(key, 0) + n
        return observed, active, volume

    def _build(by_weekday: bool):
        observed, active, volume = _index(by_weekday)
        min_occ = MIN_OCCURRENCES_FOR_FORECAST if by_weekday else 2
        out = []
        for offset in range(hours_ahead):
            target_slot = current_slot + offset
            wd, hr = _slot_weekday_hour(target_slot)
            key = (wd, hr) if by_weekday else hr
            occ, act, vol = observed.get(key, 0), active.get(key, 0), volume.get(key, 0)

            if occ < min_occ:
                probability, confidence = None, "low"
            else:
                probability = round(act / occ * 100)
                confidence = "high" if occ >= min_occ * 2 else "medium"

            out.append({
                "offset_h": offset, "hour_utc": hr, "weekday": wd,
                "weekday_label": WEEKDAY_LABELS[wd],
                "probability": probability, "confidence": confidence,
                "observations": occ,
                "avg_spots": round(vol / act, 1) if act else 0.0,
            })
        rated = sum(1 for s in out if s["probability"] is not None)
        return out, rated

    hour_slots, hour_rated = _build(False)
    out, basis = hour_slots, "hour"

    if span["span_hours"] >= 14 * 24:
        wd_slots, wd_rated = _build(True)
        if wd_rated >= hour_rated:
            out, basis = wd_slots, "weekday"

    rated = [s for s in out if s["probability"] is not None]
    best = max(rated, key=lambda s: s["probability"]) if rated else None

    return {
        "available": True, "slots": out, "best_slot": best,
        "days_analyzed": round(effective_hours / 24, 1),
        "band": band, "basis": basis, "maturity": maturity,
    }


# ═══════════════════════════════════════════════════════════════════════
# Agrégat pour la page AI Insight
# ═══════════════════════════════════════════════════════════════════════

def compute_all(db_path: str = DEFAULT_DB_PATH, band: Optional[str] = None,
                now: Optional[float] = None, memory_spots=None) -> dict:
    """
    Les quatre analyses en un appel — la page ne fait ainsi qu'une seule
    requête réseau.

    `memory_spots` est un repli optionnel (typiquement `spot_history` de
    webapp.py) utilisé quand aucune base n'est encore exploitable. Il
    garantit que la page affiche l'activité récente dès le premier
    démarrage, sans attendre la constitution d'un historique.

    Chaque bloc porte son propre `available` ; `maturity` indique à
    l'interface quoi mettre en avant.
    """
    if now is None:
        now = time.time()

    # UN SEUL accès aux sources pour les quatre analyses. Les appeler
    # indépendamment relirait quatre fois les mêmes lignes et referait
    # quatre fois le balayage d'étendue — le poste de coût dominant sur
    # un historique de plusieurs dizaines de milliers de spots. La
    # fenêtre chargée est la plus large des quatre (30 jours).
    try:
        preloaded = _load_aggregated(db_path, 30 * 24, now,
                                     memory_spots=memory_spots)
        source = preloaded[1].get("source", "?")
    except SchemaUnavailable as exc:
        # Aucune source exploitable : chaque analyse rend sa forme vide.
        reason = str(exc)
        empty = _maturity(0)
        return {
            "recent":   _empty(reason, hours=24, series=[], bands=[], total=0,
                               peak=0, maturity=empty),
            "heatmap":  _empty(reason, grid=[[None] * 24 for _ in range(7)],
                               weekday_labels=WEEKDAY_LABELS, peak_value=0.0,
                               best_slot=None, total_spots=0, days=30,
                               band=band, maturity=empty),
            "patterns": _empty(reason, bands=[], window_days=7, window_hours=0,
                               total_recent=0, total_previous=0, maturity=empty),
            "forecast": _empty(reason, slots=[], best_slot=None, days_analyzed=30,
                               band=band, basis=None, maturity=empty),
            "maturity": empty,
            "source": None,
            "reason": reason,
            "generated_at": now,
        }

    recent = compute_recent(db_path, hours=24, now=now, preloaded=preloaded)

    return {
        "recent":   recent,
        "heatmap":  compute_heatmap(db_path, days=30, band=band, now=now,
                                    preloaded=preloaded),
        "patterns": compute_patterns(db_path, now=now, preloaded=preloaded),
        "forecast": compute_forecast(db_path, hours_ahead=6, days=30,
                                     band=band, now=now, preloaded=preloaded),
        "maturity": recent.get("maturity", _maturity(0)),
        "source": source,
        "generated_at": now,
    }
