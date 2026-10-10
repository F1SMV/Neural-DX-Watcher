#!/usr/bin/env python3
"""
Récupération de data/predictor.sqlite corrompu ("database disk image is malformed").
Corruption isolée à spot_log : on sauve les lignes lisibles (subdivision binaire
sur les pages illisibles), on recopie intégralement les tables saines, on
reconstruit les index à neuf. Non destructif : écrit dans un fichier séparé.

Usage sur le Pi :
    cd ~/Spot-Watcher-DX
    ./start.sh  -> Ctrl-C pour ARRÊTER l'app d'abord (aucune écriture pendant la récup)
    python3 recover_predictor.py
    # si OK : mv data/predictor.sqlite data/predictor.corrupt.bak
    #         mv data/predictor.recovered.sqlite data/predictor.sqlite
"""
import sqlite3, os, sys, time

SRC = os.environ.get('SRC', 'data/predictor.sqlite')
DST = os.environ.get('DST', 'data/predictor.recovered.sqlite')

# Tables saines recopiées en bloc
BULK_TABLES = ['sessions', 'sqlite_sequence', 'missing_dxcc',
               'es_events', 'prediction_log', 'solar_log']

SCHEMA_TABLES = {
    'sessions': "CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, ts_start REAL NOT NULL, ts_last REAL NOT NULL, bands TEXT DEFAULT '[]')",
    'sqlite_sequence': None,  # créée automatiquement par AUTOINCREMENT
    'spot_log': "CREATE TABLE spot_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, dx_call TEXT NOT NULL, dxcc TEXT, band TEXT, mode TEXT, freq_khz REAL, spd_score REAL, is_watchlist INTEGER DEFAULT 0, is_wanted INTEGER DEFAULT 0, prefix TEXT)",
    'missing_dxcc': "CREATE TABLE missing_dxcc (dxcc TEXT NOT NULL, band TEXT NOT NULL, mode TEXT DEFAULT '', updated_at REAL NOT NULL, PRIMARY KEY (dxcc, band, mode))",
    'es_events': "CREATE TABLE es_events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, month INTEGER, hour_utc INTEGER, path_prefix TEXT, band TEXT DEFAULT '6m', spot_count INTEGER DEFAULT 1)",
    'prediction_log': "CREATE TABLE prediction_log (id INTEGER PRIMARY KEY AUTOINCREMENT, created_ts REAL NOT NULL, target_ts_start REAL NOT NULL, target_ts_end REAL NOT NULL, target_hour_bucket INTEGER NOT NULL, band TEXT NOT NULL, dxcc TEXT NOT NULL, prefix TEXT NOT NULL, model TEXT NOT NULL, predicted_score REAL NOT NULL, verified INTEGER DEFAULT 0, realized INTEGER, observed_spots INTEGER DEFAULT 0, verified_ts REAL, UNIQUE(band, prefix, target_hour_bucket))",
    'solar_log': "CREATE TABLE solar_log (ts REAL PRIMARY KEY, sfi REAL, kp REAL)",
}

SCHEMA_INDEXES = [
    "CREATE INDEX idx_spot_log_ts     ON spot_log(ts)",
    "CREATE INDEX idx_spot_log_dx     ON spot_log(dx_call)",
    "CREATE INDEX idx_spot_log_band   ON spot_log(band)",
    "CREATE INDEX idx_spot_log_prefix ON spot_log(prefix)",
    "CREATE INDEX idx_es_events_month ON es_events(month, hour_utc)",
    "CREATE INDEX idx_pred_log_target   ON prediction_log(target_ts_end)",
    "CREATE INDEX idx_pred_log_verified ON prediction_log(verified)",
]

SPOT_COLS = "id, ts, dx_call, dxcc, band, mode, freq_khz, spd_score, is_watchlist, is_wanted, prefix"


def salvage_spot_log(src, dst):
    """Sauve spot_log par plages de rowid ; subdivise sur les plages illisibles."""
    scur = src.cursor()
    scur.execute('SELECT seq FROM sqlite_sequence WHERE name="spot_log"')
    row = scur.fetchone()
    maxid = row[0] if row else 0
    saved = skipped = 0
    stack = [(1, maxid)]
    BULK = 5000
    ph = ", ".join(["?"] * 11)
    ins = f"INSERT OR IGNORE INTO spot_log ({SPOT_COLS}) VALUES ({ph})"
    while stack:
        lo, hi = stack.pop()
        if lo > hi:
            continue
        try:
            scur.execute(
                f"SELECT {SPOT_COLS} FROM spot_log WHERE id BETWEEN ? AND ?",
                (lo, hi))
            rows = scur.fetchall()
            dst.executemany(ins, rows)
            saved += len(rows)
        except Exception:
            if lo == hi:
                skipped += 1            # ligne isolée illisible : on l'abandonne
                continue
            mid = (lo + hi) // 2        # subdivise et réessaie
            stack.append((lo, mid))
            stack.append((mid + 1, hi))
    return saved, skipped, maxid


def main():
    t0 = time.time()
    if not os.path.exists(SRC):
        print(f"ABSENT: {SRC}"); sys.exit(1)
    if os.path.exists(DST):
        os.remove(DST)

    src = sqlite3.connect(SRC)
    dst = sqlite3.connect(DST)

    # 1) tables (sans index)
    for name, ddl in SCHEMA_TABLES.items():
        if ddl:
            dst.execute(ddl)
    dst.commit()

    # 2) tables saines en bloc
    scur = src.cursor()
    for t in BULK_TABLES:
        if t == 'sqlite_sequence':
            continue  # gérée par AUTOINCREMENT, recalculée
        try:
            scur.execute(f"SELECT * FROM {t}")
            rows = scur.fetchall()
            if rows:
                ph = ", ".join(["?"] * len(rows[0]))
                dst.executemany(f"INSERT OR IGNORE INTO {t} VALUES ({ph})", rows)
            print(f"  {t:16s}: {len(rows)} lignes copiées")
        except Exception as e:
            print(f"  {t:16s}: ÉCHEC ({e}) — table ignorée")
    dst.commit()

    # 3) spot_log : salvage
    print("  spot_log        : salvage en cours...")
    saved, skipped, maxid = salvage_spot_log(src, dst)
    dst.commit()
    print(f"  spot_log        : {saved} sauvées / {skipped} perdues (max id {maxid})")

    # 4) index reconstruits à neuf
    for ddl in SCHEMA_INDEXES:
        dst.execute(ddl)
    dst.commit()

    # 5) intégrité
    ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"  integrity_check : {ok}")
    dst.close(); src.close()
    print(f"Terminé en {time.time()-t0:.1f}s -> {DST}")
    return ok == "ok"


if __name__ == "__main__":
    sys.exit(0 if main() else 2)
