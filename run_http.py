#!/usr/bin/env python3
"""Point d'entrée Streamable HTTP pour le serveur MCP Leboncoin et le moteur de veille.

Ce script :
1. Lance le transport MCP Streamable HTTP pour ChatGPT / Claude
2. Lance le daemon de veille en arrière-plan (CollectorService) si activé (ENABLE_MONITOR=1)
3. Configure la sécurité réseau (TransportSecuritySettings) pour accepter les reverse-proxies
"""

import logging
import os
import sys
import threading
from pathlib import Path

# Ajouter src au PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent / "src"))

from mcp.server.transport_security import TransportSecuritySettings
from lbc_mcp.database import Database
from lbc_mcp.monitor import CollectorService
from lbc_mcp.server import mcp

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("leboncoin-mcp")


def start_background_collector():
    """Démarre la boucle de surveillance en arrière-plan si activée."""
    if os.environ.get("ENABLE_MONITOR", "0").strip() not in ("1", "true", "True"):
        logger.info("Veille automatique en arrière-plan désactivée (ENABLE_MONITOR=0)")
        return

    interval = int(os.environ.get("MONITOR_INTERVAL_SECONDS", "300"))
    logger.info("Lancement de la veille automatique en arrière-plan (intervalle: %d s)...", interval)

    collector = CollectorService()
    t = threading.Thread(target=collector.start_loop, args=(interval,), daemon=True, name="LBC-Collector")
    t.start()


def main():
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8000"))
    path = os.environ.get("MCP_PATH", "/mcp")
    public_host = os.environ.get("MCP_PUBLIC_HOST", "localhost")

    allowed_hosts = [
        "127.0.0.1",
        "127.0.0.1:*",
        "localhost",
        "localhost:*",
        public_host,
        f"{public_host}:*",
        "*",
    ]

    security_settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
        allowed_hosts=allowed_hosts,
        allowed_origins=["https://chatgpt.com", "https://claude.ai", "*"],
    )

    # Lancement du daemon de veille
    start_background_collector()

    logger.info("Démarrage du serveur MCP Streamable HTTP sur http://%s:%d%s", host, port, path)
    logger.info("Host public autorisé : %s", public_host)

    mcp.run(
        transport="streamable-http",
        host=host,
        port=port,
        streamable_http_path=path,
        transport_security=security_settings,
    )


if __name__ == "__main__":
    main()
