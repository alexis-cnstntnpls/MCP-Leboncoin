"""Gestion du cookie DataDome pour l'acces Leboncoin.

DataDome bloque par defaut les requetes automatisees depourvues de cookie
valide. Ce module permet de fournir le cookie DataDome :
1. Par la variable d'environnement LBC_DATADOME_COOKIE
2. Par un fichier de cookie (variable LBC_COOKIE_FILE ou ~/.config/leboncoin/cookie.txt)
3. Par extraction automatique depuis le trousseau Chrome local si disponible.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import sqlite3
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_COOKIE_FILE = Path.home() / ".config" / "leboncoin" / "datadome.txt"


def extract_from_chrome_local() -> str | None:
    """Tente d'extraire automatiquement le cookie datadome depuis le profil Chrome local."""
    possible_paths = [
        Path.home() / ".var" / "app" / "com.google.Chrome" / "config" / "google-chrome" / "Default" / "Cookies",
        Path.home() / ".config" / "google-chrome" / "Default" / "Cookies",
        Path.home() / ".config" / "google-chrome" / "Default" / "Network" / "Cookies",
        Path.home() / ".config" / "chromium" / "Default" / "Cookies",
    ]
    
    db_path = None
    for p in possible_paths:
        if p.is_file():
            db_path = p
            break
            
    if not db_path:
        return None

    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError:
        logger.debug("cryptography non disponible pour l'extraction de cookies Chrome")
        return None

    # Recuperation de la cle Safe Storage via secret-tool
    raw_secret = None
    try:
        res = subprocess.run(
            ["secret-tool", "lookup", "application", "chrome"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if res.returncode == 0 and res.stdout.strip():
            raw_secret = res.stdout.strip().encode("utf-8")
    except Exception:
        pass

    if not raw_secret:
        raw_secret = b"peanuts"

    key = hashlib.pbkdf2_hmac("sha1", raw_secret, b"saltysalt", 1, 16)

    try:
        conn = sqlite3.connect(f"file:{db_path}?immutable=1", uri=True)
        cur = conn.cursor()
        cur.execute(
            "SELECT encrypted_value FROM cookies WHERE host_key LIKE '%leboncoin.fr%' AND name='datadome'"
        )
        row = cur.fetchone()
        conn.close()
        if not row or not row[0]:
            return None

        enc = row[0]
        if not enc.startswith(b"v10") and not enc.startswith(b"v11"):
            return None

        cipher = Cipher(algorithms.AES(key), modes.CBC(b" " * 16))
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(enc[3:]) + decryptor.finalize()
        pad = decrypted[-1]
        if isinstance(pad, int) and pad <= 16:
            payload = decrypted[:-pad]
            # DataDome cookie est une chaine de 128 caracteres a la fin du payload
            if len(payload) >= 128:
                cookie = payload[-128:].decode("utf-8", errors="ignore")
                if len(cookie) == 128 and all(c.isalnum() or c in "_~-" for c in cookie):
                    return cookie
    except Exception as exc:
        logger.debug("Erreur extraction cookie Chrome: %s", exc)

    return None


def get_datadome_cookie() -> str | None:
    """Renvoie le cookie DataDome configure ou extrait."""
    # 1. Variable d'environnement directe
    env_cookie = os.environ.get("LBC_DATADOME_COOKIE", "").strip()
    if env_cookie:
        return env_cookie

    # 2. Fichier configure ou standard
    cookie_file_path = os.environ.get("LBC_COOKIE_FILE", "").strip()
    candidate_paths = [Path(cookie_file_path)] if cookie_file_path else [
        DEFAULT_COOKIE_FILE,
        Path("/var/lib/leboncoin-mcp/datadome.txt"),
        Path.home() / ".config" / "leboncoin" / "cookie.txt",
    ]

    for p in candidate_paths:
        if p.is_file():
            try:
                content = p.read_text(encoding="utf-8").strip()
                if content:
                    return content
            except OSError:
                pass

    # 3. Extraction automatique locale
    return extract_from_chrome_local()
