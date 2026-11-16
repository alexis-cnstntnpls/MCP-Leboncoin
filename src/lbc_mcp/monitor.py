"""Moteur de collecte autonome et de surveillance des annonces Leboncoin.

Permet une veille continue comparable a RacingTech :
- Scrute periodiquement les recherches enregistrees (watchlist)
- Enregistre les annonces et leur historique de prix en base SQLite
- Detecte immediatement les nouvelles annonces et les baisses de prix
- Notifie optionnellement via webhook Discord ou Telegram
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from datetime import datetime, timezone
from typing import Any

import requests

from .database import Database
from .formatting import ad_to_dict
from .leboncoin import Criteria, Leboncoin, prepare_search

logger = logging.getLogger(__name__)


class CollectorService:
    """Service de collecte et de veille automatique en arriere-plan."""

    def __init__(self, db: Database | None = None, gateway: Leboncoin | None = None):
        self.db = db or Database()
        self.gateway = gateway or Leboncoin()
        self.discord_webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip() or None
        self.telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() or None
        self.telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip() or None
        self._running = False

    def notify(self, event: dict[str, Any]) -> None:
        """Envoie une alerte si un webhook est configure."""
        event_type = event.get("event")
        title = event.get("title", "Annonce Leboncoin")
        url = event.get("url", "https://www.leboncoin.fr")
        price = event.get("price") or event.get("new_price")

        if event_type == "new":
            msg = f"🆕 **Nouvelle annonce Leboncoin**\n**{title}**\n💰 Prix : {price} €\n🔗 {url}"
        elif event_type == "price_drop":
            old_p = event.get("old_price")
            drop = event.get("drop_pct")
            msg = f"📉 **Baisse de prix (-{drop}%)**\n**{title}**\n💰 Nouveau prix : {price} € (au lieu de {old_p} €)\n🔗 {url}"
        else:
            return

        # Discord Webhook
        if self.discord_webhook:
            try:
                payload = {
                    "content": msg,
                    "embeds": [{
                        "title": title,
                        "url": url,
                        "color": 3066993 if event_type == "new" else 15158332,
                        "fields": [
                            {"name": "Prix", "value": f"{price} €", "inline": True},
                            {"name": "Type", "value": "Nouvelle annonce" if event_type == "new" else f"Baisse (-{event.get('drop_pct')}%)", "inline": True}
                        ]
                    }]
                }
                requests.post(self.discord_webhook, json=payload, timeout=8)
            except Exception as exc:
                logger.warning("Erreur notification Discord : %s", exc)

        # Telegram
        if self.telegram_token and self.telegram_chat_id:
            try:
                tg_url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
                requests.post(tg_url, json={"chat_id": self.telegram_chat_id, "text": msg, "parse_mode": "Markdown"}, timeout=8)
            except Exception as exc:
                logger.warning("Erreur notification Telegram : %s", exc)

    def scan_watchlist_item(self, item: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
        """Scanne une recherche surveillee et enregistre les annonces."""
        criteria = Criteria(
            query=item.get("query"),
            category=item.get("category") or "TOUTES_CATEGORIES",
            price_min=int(item["price_min"]) if item.get("price_min") is not None else None,
            price_max=int(item["price_max"]) if item.get("price_max") is not None else None,
            city=item.get("city"),
            radius_km=float(item.get("radius_km", 10)),
            departments=item.get("departments") or [],
            shippable_only=bool(item.get("shippable_only")),
            sort="newest",
        )

        try:
            prepared = prepare_search(criteria)
            result = self.gateway.search_page(prepared, limit=limit, page=1)
        except Exception as exc:
            logger.error("Erreur lors de la recherche '%s' : %s", item.get("name"), exc)
            return []

        events = []
        for ad in result.ads:
            ad_dict = ad_to_dict(ad, full=True)
            event = self.db.record_ad(ad_dict)
            if event.get("event") in ("new", "price_drop"):
                events.append(event)
                self.notify(event)

        self.db.update_watchlist_last_check(item["id"])
        return events

    def run_cycle(self) -> dict[str, Any]:
        """Execute un cycle de verification de toutes les veilles actives."""
        items = self.db.list_watchlist(active_only=True)
        if not items:
            return {"scanned": 0, "events": []}

        all_events = []
        for item in items:
            events = self.scan_watchlist_item(item)
            all_events.extend(events)
            # Petite temporisation de politesse entre les recherches
            time.sleep(random.uniform(2.0, 4.0))

        return {"scanned": len(items), "events": all_events}

    def start_loop(self, default_interval: int = 300) -> None:
        """Lance la boucle de surveillance continue."""
        self._running = True
        logger.info("Demarrage du moteur de collecte en continu (intervalle de base: %d s)", default_interval)

        while self._running:
            try:
                res = self.run_cycle()
                if res["events"]:
                    logger.info("Cycle termine : %d veilles scannees, %d alertes generees", res["scanned"], len(res["events"]))
            except Exception as exc:
                logger.exception("Erreur dans la boucle de collecte : %s", exc)

            # Pause aleatoire entre les cycles
            jitter = random.randint(-15, 15)
            sleep_duration = max(60, default_interval + jitter)
            time.sleep(sleep_duration)

    def stop(self) -> None:
        self._running = False
