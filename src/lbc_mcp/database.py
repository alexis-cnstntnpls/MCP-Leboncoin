"""Base de donnees SQLite pour le suivi des annonces, des prix et des alertes.

Permet de reproduire les fonctionnalites de RacingTech :
- Historique complet des prix d'une annonce
- Detection des baisses de prix
- Alertes sur nouvelles annonces
- Listes de surveillance (watchlists)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "leboncoin" / "leboncoin.db"


def get_db_path() -> Path:
    env_path = os.environ.get("LBC_DB_PATH", "").strip()
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_PATH


class Database:
    """Gestionnaire SQLite thread-safe pour le stockage des annonces et de l'historique."""

    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            db_path = get_db_path()
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._local = threading.local()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.db_path), timeout=30.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS ads (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                category TEXT,
                city TEXT,
                zipcode TEXT,
                department TEXT,
                region TEXT,
                seller_id TEXT,
                seller_name TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                first_price REAL,
                current_price REAL,
                min_price REAL,
                max_price REAL,
                price_drop_pct REAL DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                image_url TEXT,
                raw_json TEXT
            );

            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ad_id INTEGER NOT NULL REFERENCES ads(id) ON DELETE CASCADE,
                price REAL NOT NULL,
                recorded_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                query TEXT,
                category TEXT DEFAULT 'TOUTES_CATEGORIES',
                price_min REAL,
                price_max REAL,
                city TEXT,
                radius_km REAL DEFAULT 10,
                departments TEXT,
                shippable_only INTEGER DEFAULT 0,
                check_interval_seconds INTEGER DEFAULT 300,
                last_checked_at TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ad_id INTEGER NOT NULL REFERENCES ads(id) ON DELETE CASCADE,
                alert_type TEXT NOT NULL,
                title TEXT NOT NULL,
                old_price REAL,
                new_price REAL,
                drop_pct REAL,
                url TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_ads_last_seen ON ads(last_seen_at);
            CREATE INDEX IF NOT EXISTS idx_price_history_ad_id ON price_history(ad_id, recorded_at);
            CREATE INDEX IF NOT EXISTS idx_alerts_created_at ON alerts(created_at);
            CREATE INDEX IF NOT EXISTS idx_watchlist_active ON watchlist(is_active);
            """)

    def record_ad(self, ad_dict: dict[str, Any]) -> dict[str, Any]:
        """Enregistre ou met a jour une annonce.
        
        Renvoie un dictionnaire d'evenement si une nouveaute ou une baisse de prix
        est detectee :
        - {"event": "new", "ad": ...}
        - {"event": "price_drop", "old_price": ..., "new_price": ..., "drop_pct": ..., "ad": ...}
        - {"event": "updated", "ad": ...}
        """
        now = datetime.now(timezone.utc).isoformat()
        ad_id = int(ad_dict["id"])
        title = ad_dict.get("title", "")
        url = ad_dict.get("url", f"https://www.leboncoin.fr/ad/{ad_id}")
        price = float(ad_dict["price"]) if ad_dict.get("price") is not None else None
        city = ad_dict.get("city")
        zipcode = ad_dict.get("zipcode")
        department = ad_dict.get("department")
        category = ad_dict.get("category")
        seller_id = ad_dict.get("seller_id")
        seller_name = ad_dict.get("seller_name")
        images = ad_dict.get("images")
        image_url = ad_dict.get("image") or (images[0] if isinstance(images, list) and images else None)
        raw_json = json.dumps(ad_dict, ensure_ascii=False)

        event: dict[str, Any] = {"event": "none", "ad_id": ad_id}

        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM ads WHERE id = ?", (ad_id,))
            existing = cur.fetchone()

            if existing is None:
                # Nouvelle annonce
                first_price = price
                current_price = price
                min_price = price
                max_price = price
                price_drop_pct = 0.0

                cur.execute("""
                    INSERT INTO ads (
                        id, title, url, category, city, zipcode, department,
                        seller_id, seller_name, first_seen_at, last_seen_at,
                        first_price, current_price, min_price, max_price,
                        price_drop_pct, is_active, image_url, raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ad_id, title, url, category, city, zipcode, department,
                    seller_id, seller_name, now, now,
                    first_price, current_price, min_price, max_price,
                    price_drop_pct, 1, image_url, raw_json
                ))

                if price is not None:
                    cur.execute(
                        "INSERT INTO price_history (ad_id, price, recorded_at) VALUES (?, ?, ?)",
                        (ad_id, price, now)
                    )

                event = {
                    "event": "new",
                    "ad_id": ad_id,
                    "title": title,
                    "price": price,
                    "url": url,
                    "city": city
                }

                cur.execute("""
                    INSERT INTO alerts (ad_id, alert_type, title, old_price, new_price, drop_pct, url, created_at)
                    VALUES (?, 'new_ad', ?, NULL, ?, 0, ?, ?)
                """, (ad_id, title, price, url, now))

            else:
                # Annonce existante : verifier le prix
                old_current_price = existing["current_price"]
                first_price = existing["first_price"]
                min_price = existing["min_price"]
                max_price = existing["max_price"]

                if price is not None and old_current_price is not None and price != old_current_price:
                    # Changement de prix detecte
                    cur.execute(
                        "INSERT INTO price_history (ad_id, price, recorded_at) VALUES (?, ?, ?)",
                        (ad_id, price, now)
                    )
                    min_price = min(min_price, price) if min_price is not None else price
                    max_price = max(max_price, price) if max_price is not None else price

                    if price < old_current_price:
                        # Baisse de prix !
                        drop_pct = round(((old_current_price - price) / old_current_price) * 100, 1)
                        event = {
                            "event": "price_drop",
                            "ad_id": ad_id,
                            "title": title,
                            "old_price": old_current_price,
                            "new_price": price,
                            "drop_pct": drop_pct,
                            "url": url,
                        }
                        cur.execute("""
                            INSERT INTO alerts (ad_id, alert_type, title, old_price, new_price, drop_pct, url, created_at)
                            VALUES (?, 'price_drop', ?, ?, ?, ?, ?, ?)
                        """, (ad_id, title, old_current_price, price, drop_pct, url, now))
                    else:
                        event = {"event": "price_increase", "ad_id": ad_id, "old_price": old_current_price, "new_price": price}

                    price_drop_pct = round(((max_price - price) / max_price) * 100, 1) if max_price and max_price > 0 else 0.0

                    cur.execute("""
                        UPDATE ads SET
                            title = ?,
                            last_seen_at = ?,
                            current_price = ?,
                            min_price = ?,
                            max_price = ?,
                            price_drop_pct = ?,
                            is_active = 1,
                            raw_json = ?
                        WHERE id = ?
                    """, (title, now, price, min_price, max_price, price_drop_pct, raw_json, ad_id))
                else:
                    # Mise a jour date de dernier passage
                    cur.execute("UPDATE ads SET last_seen_at = ?, is_active = 1 WHERE id = ?", (now, ad_id))
                    event = {"event": "seen", "ad_id": ad_id}

            conn.commit()

        return event

    def get_price_history(self, ad_id: int) -> dict[str, Any] | None:
        """Renvoie l'historique des prix d'une annonce."""
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM ads WHERE id = ?", (ad_id,))
            ad = cur.fetchone()
            if not ad:
                return None

            cur.execute(
                "SELECT price, recorded_at FROM price_history WHERE ad_id = ? ORDER BY recorded_at ASC",
                (ad_id,)
            )
            history = [{"price": r["price"], "recorded_at": r["recorded_at"]} for r in cur.fetchall()]

            return {
                "ad_id": ad["id"],
                "title": ad["title"],
                "url": ad["url"],
                "current_price": ad["current_price"],
                "first_price": ad["first_price"],
                "min_price": ad["min_price"],
                "max_price": ad["max_price"],
                "price_drop_pct": ad["price_drop_pct"],
                "first_seen_at": ad["first_seen_at"],
                "last_seen_at": ad["last_seen_at"],
                "history": history
            }

    def get_recent_deals(self, limit: int = 20, min_drop_pct: float = 0.0) -> list[dict[str, Any]]:
        """Renvoie les annonces ayant connu les plus fortes baisses de prix ou les plus recentes."""
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, title, url, current_price, first_price, max_price, price_drop_pct, city, first_seen_at, last_seen_at
                FROM ads
                WHERE is_active = 1 AND price_drop_pct >= ?
                ORDER BY price_drop_pct DESC, last_seen_at DESC
                LIMIT ?
            """, (min_drop_pct, limit))
            return [dict(r) for r in cur.fetchall()]

    def get_recent_alerts(self, limit: int = 20) -> list[dict[str, Any]]:
        """Renvoie les dernieres alertes generees."""
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, ad_id, alert_type, title, old_price, new_price, drop_pct, url, created_at
                FROM alerts
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            return [dict(r) for r in cur.fetchall()]

    # --- Gestion de la Watchlist (recherches surveillees) ---

    def add_watchlist(
        self,
        name: str,
        query: str | None = None,
        category: str = "TOUTES_CATEGORIES",
        price_min: float | None = None,
        price_max: float | None = None,
        city: str | None = None,
        radius_km: float = 10,
        departments: list[str] | None = None,
        shippable_only: bool = False,
        interval_seconds: int = 300,
    ) -> int:
        """Ajoute une recherche a surveiller regulierement."""
        now = datetime.now(timezone.utc).isoformat()
        dept_str = ",".join(departments) if departments else None
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO watchlist (
                    name, query, category, price_min, price_max, city, radius_km,
                    departments, shippable_only, check_interval_seconds, is_active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """, (
                name, query, category, price_min, price_max, city, radius_km,
                dept_str, 1 if shippable_only else 0, interval_seconds, now
            ))
            conn.commit()
            return cur.lastrowid

    def list_watchlist(self, active_only: bool = True) -> list[dict[str, Any]]:
        """Liste les recherches enregistrees en veille."""
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            query = "SELECT * FROM watchlist WHERE is_active = 1 ORDER BY id ASC" if active_only else "SELECT * FROM watchlist ORDER BY id ASC"
            cur.execute(query)
            rows = []
            for r in cur.fetchall():
                d = dict(r)
                if d.get("departments"):
                    d["departments"] = d["departments"].split(",")
                else:
                    d["departments"] = []
                d["shippable_only"] = bool(d["shippable_only"])
                rows.append(d)
            return rows

    def update_watchlist_last_check(self, watchlist_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._get_connection() as conn:
            conn.execute("UPDATE watchlist SET last_checked_at = ? WHERE id = ?", (now, watchlist_id))
            conn.commit()

    def set_watchlist_active(self, watchlist_id: int, is_active: bool) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute("UPDATE watchlist SET is_active = ? WHERE id = ?", (1 if is_active else 0, watchlist_id))
            conn.commit()
