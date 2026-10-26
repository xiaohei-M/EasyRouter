# -*- coding: utf-8 -*-
"""SQLite 持久化：设备别名、累计流量、设备档案。"""
import os
import sqlite3
import threading
import time


class Store:
    def __init__(self, db_path):
        d = os.path.dirname(db_path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS aliases (
                    mac TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    updated INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS traffic_totals (
                    ip TEXT PRIMARY KEY,
                    rx INTEGER NOT NULL DEFAULT 0,
                    tx INTEGER NOT NULL DEFAULT 0,
                    updated INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS known (
                    mac TEXT PRIMARY KEY,
                    first_seen INTEGER NOT NULL,
                    last_seen INTEGER NOT NULL,
                    last_ip TEXT NOT NULL DEFAULT ''
                );
                """
            )
            self.conn.commit()

    # ---------- 设备别名 ----------
    def get_aliases(self):
        with self.lock:
            rows = self.conn.execute("SELECT mac, name FROM aliases").fetchall()
            return {r["mac"]: r["name"] for r in rows}

    def set_alias(self, mac, name):
        mac = (mac or "").strip().upper()
        name = (name or "").strip()
        with self.lock:
            if not mac:
                return False
            if not name:
                self.conn.execute("DELETE FROM aliases WHERE mac=?", (mac,))
            else:
                self.conn.execute(
                    "INSERT INTO aliases (mac, name, updated) VALUES (?,?,?) "
                    "ON CONFLICT(mac) DO UPDATE SET name=excluded.name, updated=excluded.updated",
                    (mac, name, int(time.time())),
                )
            self.conn.commit()
        return True

    # ---------- 累计流量 ----------
    def get_totals(self):
        with self.lock:
            rows = self.conn.execute("SELECT ip, rx, tx FROM traffic_totals").fetchall()
            return {r["ip"]: (r["rx"], r["tx"]) for r in rows}

    def save_totals(self, totals):
        now = int(time.time())
        with self.lock:
            self.conn.executemany(
                "INSERT INTO traffic_totals (ip, rx, tx, updated) VALUES (?,?,?,?) "
                "ON CONFLICT(ip) DO UPDATE SET rx=excluded.rx, tx=excluded.tx, updated=excluded.updated",
                [(ip, rx, tx, now) for ip, (rx, tx) in totals.items()],
            )
            self.conn.commit()

    def replace_aliases(self, aliases):
        with self.lock:
            self.conn.execute("DELETE FROM aliases")
            self.conn.executemany(
                "INSERT INTO aliases (mac, name, updated) VALUES (?,?,?)",
                [(mac, name, int(time.time())) for mac, name in aliases.items() if name])
            self.conn.commit()

    def replace_totals(self, totals):
        with self.lock:
            self.conn.execute("DELETE FROM traffic_totals")
            self.conn.executemany(
                "INSERT INTO traffic_totals (ip, rx, tx, updated) VALUES (?,?,?,?)",
                [(ip, rx, tx, int(time.time())) for ip, (rx, tx) in totals.items()])
            self.conn.commit()

    # ---------- 设备档案 ----------
    def known_update(self, rows):
        """rows: [(mac, first_seen, last_seen, last_ip), ...]"""
        with self.lock:
            self.conn.executemany(
                "INSERT INTO known (mac, first_seen, last_seen, last_ip) VALUES (?,?,?,?) "
                "ON CONFLICT(mac) DO UPDATE SET last_seen=excluded.last_seen, last_ip=excluded.last_ip",
                rows,
            )
            self.conn.commit()

    def known_get(self):
        with self.lock:
            rows = self.conn.execute("SELECT mac, first_seen, last_seen, last_ip FROM known").fetchall()
            return [dict(r) for r in rows]

    def close(self):
        with self.lock:
            self.conn.close()
