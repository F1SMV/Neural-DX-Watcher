#!/usr/bin/env python3
"""
Unit tests pour ntfy_alerts.py
Valide chaque fonction avec cas limite + edge cases
"""

import sqlite3
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock
from ntfy_alerts import NtfyAlertEngine


class TestNtfyAlertEngine(unittest.TestCase):
    """Tests complets du moteur d'alertes"""
    
    def setUp(self):
        """Créer une DB de test en mémoire"""
        self.test_db = ":memory:"
        self.conn = sqlite3.connect(self.test_db)
        self.conn.row_factory = sqlite3.Row
        self._init_test_db()
        
        # Config de test
        self.test_config = {
            "ntfy_alerts": {
                "enabled": True,
                "ntfy_url": "http://ntfy.test",
                "topic": "test-radio-dx",
                "watchlist": ["EA", "JA", "VK"],
                "suppress_if_active": True
            }
        }
        
        self.engine = NtfyAlertEngine(self.test_db, self.test_config)
    
    def _init_test_db(self):
        """Initialiser les tables de test"""
        cursor = self.conn.cursor()
        
        # Table spot_log (schema simplifié)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS spot_log (
            id INTEGER PRIMARY KEY,
            call TEXT,
            entity TEXT,
            band TEXT,
            freq_mhz REAL,
            snr_db REAL,
            timestamp TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # Table lotw_log (pour vérifier worked DXCC)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS lotw_log (
            call TEXT,
            entity TEXT,
            band TEXT,
            timestamp TEXT,
            PRIMARY KEY (call, entity, band)
        )
        """)
        
        self.conn.commit()
    
    def _insert_spot(self, call, entity, band, freq_mhz, snr_db, minutes_ago=0):
        """Helper : insérer un spot de test"""
        ts = (datetime.utcnow() - timedelta(minutes=minutes_ago)).isoformat()
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO spot_log (call, entity, band, freq_mhz, snr_db, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (call, entity, band, freq_mhz, snr_db, ts))
        self.conn.commit()
    
    def _insert_lotw(self, call, entity, band):
        """Helper : marquer un DXCC comme worked en LoTW"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO lotw_log (call, entity, band, timestamp)
            VALUES (?, ?, ?, ?)
        """, (call, entity, band, datetime.utcnow().isoformat()))
        self.conn.commit()
    
    # ========== TESTS UNITAIRES ==========
    
    def test_engine_init(self):
        """✓ Initialisation du moteur OK"""
        self.assertTrue(self.engine.enabled)
        self.assertEqual(self.engine.topic, "test-radio-dx")
        self.assertIn("EA", self.engine.watchlist)
    
    def test_can_alert_cooldown(self):
        """✓ Cooldown anti-spam fonctionne"""
        key = "test_alert"
        
        # Première alerte : OK
        self.assertTrue(self.engine._can_alert(key))
        self.engine.sent_alerts[key] = datetime.utcnow()
        
        # 2e alerte immédiate : bloquée
        self.assertFalse(self.engine._can_alert(key))
        
        # Après cooldown : OK
        self.engine.sent_alerts[key] = datetime.utcnow() - timedelta(seconds=301)
        self.assertTrue(self.engine._can_alert(key))
    
    @patch('ntfy_alerts.requests.post')
    def test_send_ntfy_success(self, mock_post):
        """✓ Envoi ntfy.sh réussi"""
        mock_post.return_value.status_code = 200
        
        result = self.engine._send_ntfy("Test", "Message", priority="high")
        
        self.assertTrue(result)
        mock_post.assert_called_once()
        
        # Vérifier les headers
        call_args = mock_post.call_args
        self.assertIn("Title", call_args[1]["headers"])
        self.assertEqual(call_args[1]["headers"]["Priority"], "high")
    
    @patch('ntfy_alerts.requests.post')
    def test_send_ntfy_failure(self, mock_post):
        """✓ Gestion des erreurs ntfy.sh"""
        mock_post.return_value.status_code = 500
        
        result = self.engine._send_ntfy("Test", "Message")
        
        self.assertFalse(result)
    
    @patch('ntfy_alerts.requests.post')
    def test_send_ntfy_timeout(self, mock_post):
        """✓ Gestion du timeout ntfy.sh"""
        mock_post.side_effect = Exception("Timeout")
        
        result = self.engine._send_ntfy("Test", "Message")
        
        self.assertFalse(result)
    
    def test_check_new_dxcc_empty(self):
        """✓ Pas d'alerte si aucun NEW DXCC"""
        alerts = self.engine.check_new_dxcc(self.conn)
        self.assertEqual(len(alerts), 0)
    
    @patch('ntfy_alerts.requests.post')
    def test_check_new_dxcc_detected(self, mock_post):
        """✓ Détection NEW DXCC (pas en LoTW)"""
        mock_post.return_value.status_code = 200
        
        # Insérer un spot NEW DXCC (pas en LoTW)
        self._insert_spot("JT1RQ", "JT", "6m", 50.2, -15, minutes_ago=2)
        
        # Pas de JT en LoTW pour ce call
        
        alerts = self.engine.check_new_dxcc(self.conn)
        
        self.assertGreater(len(alerts), 0)
        self.assertEqual(alerts[0]["entity"], "JT")
        mock_post.assert_called()  # Alerte envoyée
    
    @patch('ntfy_alerts.requests.post')
    def test_check_new_dxcc_not_new(self, mock_post):
        """✓ Pas d'alerte si DXCC déjà en LoTW"""
        mock_post.return_value.status_code = 200
        
        # Spot + LoTW existant
        self._insert_spot("EA1AA", "EA", "20m", 14.2, -10, minutes_ago=1)
        self._insert_lotw("EA1AA", "EA", "20m")
        
        alerts = self.engine.check_new_dxcc(self.conn)
        
        # Pas d'alerte car déjà travaillé
        self.assertEqual(len(alerts), 0)
        mock_post.assert_not_called()
    
    @patch('ntfy_alerts.requests.post')
    def test_check_watchlist_detected(self, mock_post):
        """✓ Détection call watchlist"""
        mock_post.return_value.status_code = 200
        
        self._insert_spot("EA1BB", "EA", "20m", 14.2, -8, minutes_ago=1)
        
        alerts = self.engine.check_watchlist(self.conn)
        
        self.assertGreater(len(alerts), 0)
        self.assertEqual(alerts[0]["entity"], "EA")
        mock_post.assert_called()
    
    @patch('ntfy_alerts.requests.post')
    def test_check_watchlist_not_in_list(self, mock_post):
        """✓ Pas d'alerte si entité non dans watchlist"""
        mock_post.return_value.status_code = 200
        
        # Spot ZK (non dans watchlist)
        self._insert_spot("ZK1AA", "ZK", "40m", 7.2, -12, minutes_ago=1)
        
        alerts = self.engine.check_watchlist(self.conn)
        
        self.assertEqual(len(alerts), 0)
        mock_post.assert_not_called()
    
    @patch('ntfy_alerts.requests.post')
    def test_check_6m_opening_below_threshold(self, mock_post):
        """✓ Pas d'alerte ouverture 6m si < seuil"""
        mock_post.return_value.status_code = 200
        
        # Seulement 2 spots 6m
        self._insert_spot("JT1RQ", "JT", "6m", 50.2, -8, minutes_ago=3)
        self._insert_spot("VK2AA", "VK", "6m", 50.2, -5, minutes_ago=2)
        
        result = self.engine.check_6m_opening(self.conn, threshold=5)
        
        self.assertFalse(result)
        mock_post.assert_not_called()
    
    @patch('ntfy_alerts.requests.post')
    def test_check_6m_opening_strong(self, mock_post):
        """✓ Alerte ouverture 6m si > seuil"""
        mock_post.return_value.status_code = 200
        
        # 6 spots en 10 min
        for i in range(6):
            self._insert_spot(f"EA{i}AA", "EA", "6m", 50.2, -10+i, minutes_ago=5-i)
        
        result = self.engine.check_6m_opening(self.conn, threshold=5)
        
        self.assertTrue(result)
        mock_post.assert_called()
        
        # Vérifier que "urgent" priority a été utilisée
        call_args = mock_post.call_args
        self.assertEqual(call_args[1]["headers"]["Priority"], "urgent")
    
    @patch('ntfy_alerts.requests.post')
    def test_run_all_checks(self, mock_post):
        """✓ Exécution complète de tous les checks"""
        mock_post.return_value.status_code = 200
        
        # Préparer scénario mixte
        self._insert_spot("JT1RQ", "JT", "6m", 50.2, -10, minutes_ago=2)  # NEW
        self._insert_spot("EA1BB", "EA", "20m", 14.2, -8, minutes_ago=1)    # Watchlist
        for i in range(6):
            self._insert_spot(f"VK{i}AA", "VK", "6m", 50.2, -5+i, minutes_ago=4)  # 6m opening
        
        # Passer la connexion directement (pas le chemin DB)
        result = self.engine.run_all_checks(self.conn)
        
        self.assertEqual(result["timestamp"][:10], datetime.utcnow().isoformat()[:10])
        self.assertGreater(len(result["new_dxcc"]), 0)
        self.assertGreater(len(result["watchlist"]), 0)
        self.assertTrue(result["es_6m"])
    
    def test_disabled_alerts(self):
        """✓ Aucune alerte si disabled=false"""
        config_disabled = {"ntfy_alerts": {"enabled": False}}
        engine = NtfyAlertEngine(self.test_db, config_disabled)
        
        result = engine._send_ntfy("Test", "Msg")
        self.assertFalse(result)
    
    def tearDown(self):
        """Nettoyer"""
        self.conn.close()


# ========== EXÉCUTION ==========

if __name__ == "__main__":
    # Mode verbose
    unittest.main(verbosity=2)
