#!/usr/bin/env python3
"""
Radio Spot Watcher DX — ntfy.sh Alert Engine v1.0
Envoie des alertes ntfy.sh pour :
  - New DXCC spotted (jamais travaillé auparavant)
  - Watchlist call détecté
  - Ouverture 6m (>5 spots/10min)

Usage:
  python3 ntfy_alerts.py --config /path/to/config.json
  
Config example (data/config.json):
  "ntfy_alerts": {
    "enabled": true,
    "ntfy_url": "http://ntfy.sh",  # self-hosted: http://192.168.1.79:9000
    "topic": "radio-dx-f1smv",
    "watchlist": ["EA", "JA", "VK", "JT1", "ZL"],
    "suppress_if_active": true  # pas d'alerte si on regarde déjà la page
  }
"""

import json
import sqlite3
import requests
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Set

logger = logging.getLogger("ntfy_alerts")
logger.setLevel(logging.DEBUG)

class NtfyAlertEngine:
    """Moteur d'alertes ntfy.sh pour Radio Spot Watcher DX"""
    
    def __init__(self, db_path: str, config: dict):
        self.db_path = db_path
        self.config = config.get("ntfy_alerts", {})
        self.ntfy_url = self.config.get("ntfy_url", "http://ntfy.sh")
        self.topic = self.config.get("topic", "radio-dx-alerts")
        self.watchlist: Set[str] = set(self.config.get("watchlist", []))
        self.enabled = self.config.get("enabled", False)
        
        # Tracking des alertes envoyées (éviter flood)
        self.sent_alerts: Dict[str, datetime] = {}
        self.alert_cooldown_sec = 300  # 5 min min entre alertes identiques
        
    def _can_alert(self, key: str) -> bool:
        """Vérifier si assez de temps s'est écoulé depuis la dernière alerte (key)"""
        if key not in self.sent_alerts:
            return True
        elapsed = (datetime.utcnow() - self.sent_alerts[key]).total_seconds()
        return elapsed > self.alert_cooldown_sec
    
    def _send_ntfy(self, title: str, message: str, priority: str = "default", tags: str = "") -> bool:
        """
        POST à ntfy.sh avec headers priorités
        
        Priorités: low, default, high, urgent
        """
        if not self.enabled:
            logger.debug(f"Alerts disabled. Skip: {title}")
            return False
            
        try:
            headers = {
                "Title": title,
                "Message": message,
                "Priority": priority,
                "Tags": tags,  # comma-separated, ex: "radio,dxcc,newdxcc"
            }
            url = f"{self.ntfy_url}/{self.topic}"
            resp = requests.post(url, headers=headers, timeout=3)
            
            if resp.status_code == 200:
                logger.info(f"✓ ntfy sent: {title}")
                return True
            else:
                logger.warning(f"✗ ntfy failed ({resp.status_code}): {title}")
                return False
        except Exception as e:
            logger.error(f"ntfy POST error: {e}")
            return False
    
    def check_new_dxcc(self, conn: sqlite3.Connection) -> List[Dict]:
        """
        Détecter NEW DXCC : spot sur entité jamais travaillée (pas en LoTW)
        
        Retourne: liste {call, entity, band, freq_mhz, snr_db}
        """
        alerts = []
        
        try:
            # Récupérer les NEW DXCC des 10 dernières minutes
            cursor = conn.cursor()
            ten_min_ago = datetime.utcnow() - timedelta(minutes=10)
            
            query = """
            SELECT DISTINCT
                s.call,
                s.entity,
                s.band,
                s.freq_mhz,
                s.snr_db,
                s.timestamp
            FROM spot_log s
            LEFT JOIN lotw_log l ON s.call = l.call AND s.entity = l.entity
            WHERE s.timestamp > ?
                AND l.call IS NULL  -- pas en LoTW
                AND s.entity IS NOT NULL
            ORDER BY s.timestamp DESC
            LIMIT 20
            """
            
            rows = cursor.execute(query, (ten_min_ago.isoformat(),)).fetchall()
            
            for row in rows:
                call, entity, band, freq_mhz, snr_db, ts = row
                key = f"newdxcc_{entity}_{band}"
                
                if self._can_alert(key):
                    title = f"🔥 NEW DXCC: {entity}"
                    msg = f"{call} on {band} @ {freq_mhz:.2f} MHz (SNR {snr_db:+.0f})"
                    
                    self._send_ntfy(
                        title, msg,
                        priority="high",
                        tags="newdxcc,alert"
                    )
                    
                    self.sent_alerts[key] = datetime.utcnow()
                    alerts.append({
                        "call": call,
                        "entity": entity,
                        "band": band,
                        "freq_mhz": freq_mhz,
                        "snr_db": snr_db
                    })
        
        except Exception as e:
            logger.error(f"check_new_dxcc error: {e}")
        
        return alerts
    
    def check_watchlist(self, conn: sqlite3.Connection) -> List[Dict]:
        """
        Déclencher alerte si call de la watchlist apparaît
        """
        alerts = []
        
        if not self.watchlist:
            return alerts
        
        try:
            cursor = conn.cursor()
            five_min_ago = datetime.utcnow() - timedelta(minutes=5)
            
            # Chercher les watchlist calls récents (5 dernières minutes)
            placeholders = ','.join(['?' for _ in self.watchlist])
            query = f"""
            SELECT call, entity, band, freq_mhz, snr_db, timestamp
            FROM spot_log
            WHERE entity IN ({placeholders})
                AND timestamp > ?
            ORDER BY timestamp DESC
            """
            
            params = list(self.watchlist) + [five_min_ago.isoformat()]
            rows = cursor.execute(query, params).fetchall()
            
            for row in rows:
                call, entity, band, freq_mhz, snr_db, ts = row
                key = f"watchlist_{entity}_{band}"
                
                if self._can_alert(key):
                    title = f"📡 Watchlist: {entity}"
                    msg = f"{call} on {band} @ {freq_mhz:.2f} MHz"
                    
                    self._send_ntfy(
                        title, msg,
                        priority="default",
                        tags="watchlist"
                    )
                    
                    self.sent_alerts[key] = datetime.utcnow()
                    alerts.append({
                        "call": call,
                        "entity": entity,
                        "band": band
                    })
        
        except Exception as e:
            logger.error(f"check_watchlist error: {e}")
        
        return alerts
    
    def check_6m_opening(self, conn: sqlite3.Connection, threshold: int = 5) -> bool:
        """
        Déclencher alerte si Es ouverture 6m forte détectée
        (> N spots en 10 minutes)
        """
        try:
            cursor = conn.cursor()
            ten_min_ago = datetime.utcnow() - timedelta(minutes=10)
            
            query = """
            SELECT COUNT(*) as spot_count
            FROM spot_log
            WHERE band = '6m' AND timestamp > ?
            """
            
            count = cursor.execute(query, (ten_min_ago.isoformat(),)).fetchone()[0]
            
            key = "es_opening_6m"
            if count >= threshold and self._can_alert(key):
                title = f"🌍 6m Es OPENING!"
                msg = f"{count} spots detected in last 10 min — Activity surge"
                
                self._send_ntfy(
                    title, msg,
                    priority="urgent",
                    tags="6m,es,opening"
                )
                
                self.sent_alerts[key] = datetime.utcnow()
                logger.info(f"6m opening alert sent ({count} spots)")
                return True
        
        except Exception as e:
            logger.error(f"check_6m_opening error: {e}")
        
        return False
    
    def run_all_checks(self, db_path_or_conn=None) -> Dict:
        """
        Exécuter tous les checks en une passe
        
        Args:
            db_path_or_conn: chemin DB (str) ou connexion SQLite existante
                            Si None, utilise self.db_path
        """
        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "new_dxcc": [],
            "watchlist": [],
            "es_6m": False,
            "errors": []
        }
        
        conn = None
        close_after = False
        
        try:
            # Résoudre si c'est une connexion ou un chemin
            if db_path_or_conn is None:
                db_path = self.db_path
                conn = sqlite3.connect(db_path)
                close_after = True
            elif isinstance(db_path_or_conn, str):
                conn = sqlite3.connect(db_path_or_conn)
                close_after = True
            else:
                # Assume it's a connection object
                conn = db_path_or_conn
                close_after = False
            
            conn.row_factory = sqlite3.Row
            
            result["new_dxcc"] = self.check_new_dxcc(conn)
            result["watchlist"] = self.check_watchlist(conn)
            result["es_6m"] = self.check_6m_opening(conn)
        
        except Exception as e:
            result["errors"].append(str(e))
            logger.error(f"run_all_checks fatal: {e}")
        
        finally:
            if close_after and conn:
                conn.close()
        
        return result


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="ntfy.sh Alert Engine for Radio Spot Watcher DX")
    parser.add_argument("--config", default="data/config.json", help="Config file path")
    parser.add_argument("--db", default="data/analytics.sqlite", help="Analytics DB path")
    args = parser.parse_args()
    
    # Load config
    try:
        with open(args.config) as f:
            config = json.load(f)
    except FileNotFoundError:
        logger.error(f"Config not found: {args.config}")
        exit(1)
    
    # Run
    engine = NtfyAlertEngine(args.db, config)
    result = engine.run_all_checks(args.db)  # Passe le chemin DB
    
    print(json.dumps(result, indent=2))
