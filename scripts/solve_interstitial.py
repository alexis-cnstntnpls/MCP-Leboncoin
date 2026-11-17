#!/usr/bin/env python3
"""Script de resolution automatique du Device Check DataDome et renouvellement de session Leboncoin.

Fonctionnement :
1. Teste l'etat de la session sur le VPS. Si un challenge interstitial (t=it) apparait,
   il recupere l'URL exacte du challenge.
2. Ouvre un tunnel SSH securise vers le proxy residentiel WireGuard du VPS (127.0.0.1:1080).
3. Lance Patchright (Chromium furtif en affichage reel) a travers ce tunnel residentiel.
4. Resout le challenge du Device Check avec la meme IP residentielle que le serveur MCP.
5. Recupere le nouveau cookie datadome et l'injecte immediatement dans /var/lib/leboncoin-mcp/datadome.txt sur le VPS.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_HOST = "oracle-oci-perso"
LOCAL_SOCKS_PORT = 11080


def run_cmd(cmd: str) -> tuple[int, str, str]:
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return res.returncode, res.stdout, res.stderr


def probe_vps_status(host: str = DEFAULT_HOST) -> tuple[bool, str | None]:
    """Interroge l'API Leboncoin depuis le VPS pour verifier si le cookie actuel est valide
    ou recuperer l'URL du challenge en cas de blocage."""
    print(f"[*] Verification de l'acces Leboncoin depuis le VPS ({host})...")
    remote_code = """
import lbc, os
client = lbc.Client(impersonate='chrome_android', max_retries=0)
cookie = open('/var/lib/leboncoin-mcp/datadome.txt').read().strip() if os.path.exists('/var/lib/leboncoin-mcp/datadome.txt') else ''
if cookie:
    client.session.cookies.set('datadome', cookie, domain='.leboncoin.fr')
try:
    res = client.search(text='test', limit=1)
    print('STATUS: 200')
    print('COUNT:', len(res.ads))
except Exception as e:
    print('STATUS: 403')
    from lbc.utils import build_search_payload_with_args
    r = client.session.post('https://api.leboncoin.fr/finder/search', json=build_search_payload_with_args(text='test', limit=1))
    print('BODY:', r.text)
"""
    b64 = base64.b64encode(remote_code.strip().encode("utf-8")).decode("utf-8")
    cmd = f'ssh {host} "sudo -u lbcvpn /home/ubuntu/leboncoin-mcp/.venv/bin/python -c \\"import base64; exec(base64.b64decode(\'{b64}\'))\\""'
    code, out, err = run_cmd(cmd)
    
    if "STATUS: 200" in out:
        print("[+] Le cookie actuel sur le VPS est 100% VALIDE et OPERATIONNEL !")
        return True, None

    # Extraction de l'URL du challenge
    m = re.search(r'https://geo\.captcha-delivery\.com[^\s"\'}]+', out)
    if m:
        challenge_url = m.group(0).replace("\\/", "/")
        print(f"[*] Challenge detecte : {challenge_url[:75]}...")
        return False, challenge_url

    print(f"[-] Reponse inattendue du VPS : {out.strip()} {err.strip()}")
    return False, None


def push_cookie_to_vps(cookie_val: str, host: str = DEFAULT_HOST) -> bool:
    """Met a jour le cookie sur le VPS sous l'utilisateur lbcvpn."""
    cmd = (
        f"ssh {host} \"echo '{cookie_val}' | sudo tee /var/lib/leboncoin-mcp/datadome.txt > /dev/null "
        f"&& sudo chown lbcvpn:lbcvpn /var/lib/leboncoin-mcp/datadome.txt "
        f"&& sudo chmod 600 /var/lib/leboncoin-mcp/datadome.txt\""
    )
    code, _, err = run_cmd(cmd)
    if code == 0:
        print("[+] Cookie de session synchronise avec succes sur le VPS !")
        return True
    print(f"[-] Echec de synchronisation vers le VPS : {err}")
    return False


async def solve_with_patchright(url: str, socks_port: int = LOCAL_SOCKS_PORT) -> str | None:
    """Resout le challenge interstitial a travers le tunnel residentiel."""
    try:
        from patchright.async_api import async_playwright
    except ImportError:
        print("[-] Erreur : Patchright non installe dans l'environnement Python.")
        return None

    solved_cookie = None

    async with async_playwright() as p:
        print(f"[*] Demarrage du navigateur Patchright via le proxy residentiel (port {socks_port})...")
        browser = await p.chromium.launch(
            headless=False,
            proxy={"server": f"socks5://127.0.0.1:{socks_port}"},
            args=["--no-first-run", "--no-default-browser-check"],
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="fr-FR",
            timezone_id="Europe/Paris",
        )
        page = await context.new_page()

        async def on_resp(resp):
            nonlocal solved_cookie
            if ("interstitial" in resp.url or "captcha" in resp.url) and resp.status == 200:
                try:
                    data = await resp.json()
                    if data.get("cookie"):
                        m = re.search(r"datadome=([A-Za-z0-9_~-]+)", data["cookie"])
                        if m:
                            solved_cookie = m.group(1)
                            print(f"[+] Device Check valide ! Nouveau cookie recu : {solved_cookie[:25]}...")
                except Exception:
                    pass

        page.on("response", on_resp)
        print("[*] Resolution du Device Check en cours...")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Attendre la reception du cookie
            for _ in range(20):
                if solved_cookie:
                    break
                await asyncio.sleep(0.5)
            # Laisser le temps a la redirection finale window.location.replace(json.url) de s'executer
            if solved_cookie:
                print("[*] Attente de la finalisation du redirect vers leboncoin...")
                await asyncio.sleep(4)
        except Exception as e:
            print(f"[-] Navigation : {e}")

        if not solved_cookie:
            cookies = await context.cookies()
            for c in cookies:
                if c.get("name") == "datadome" and len(c.get("value", "")) >= 100:
                    solved_cookie = c["value"]
                    print(f"[+] Cookie recupere du contexte : {solved_cookie[:25]}...")
                    break

        await browser.close()

    return solved_cookie


def main():
    parser = argparse.ArgumentParser(description="Resolution Interstitial DataDome Leboncoin")
    parser.add_argument("--url", type=str, help="URL specifique du challenge (optionnel)")
    parser.add_argument("--host", type=str, default=DEFAULT_HOST, help="Hote SSH du VPS")
    parser.add_argument("--force", action="store_true", help="Forcer la resolution meme si le test reussit")
    args = parser.parse_args()

    challenge_url = args.url

    if not challenge_url and not args.force:
        ok, detected_url = probe_vps_status(args.host)
        if ok:
            print("[+] Rien a faire : le serveur MCP fonctionne deja parfaitement.")
            sys.exit(0)
        challenge_url = detected_url

    if not challenge_url:
        # URL par defaut pour amorcer une nouvelle session sur Leboncoin
        challenge_url = "https://www.leboncoin.fr/"

    # 1. Ouvrir le tunnel SSH residentiel vers microsocks sur le VPS
    print(f"[*] Ouverture du tunnel residentiel SSH vers {args.host}:1080...")
    tunnel = subprocess.Popen(
        ["ssh", "-L", f"{LOCAL_SOCKS_PORT}:127.0.0.1:1080", "-N", args.host],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)

    try:
        # Verification IP de sortie du tunnel
        _, ip_out, _ = run_cmd(f"curl -s --socks5-hostname 127.0.0.1:{LOCAL_SOCKS_PORT} https://ifconfig.me/ip")
        print(f"[*] IP de sortie du tunnel : {ip_out.strip()} (doit etre l'IP Freebox)")

        new_cookie = asyncio.run(solve_with_patchright(challenge_url, LOCAL_SOCKS_PORT))

        if new_cookie:
            # Sauvegarde locale
            loc_path = Path.home() / ".config" / "leboncoin" / "datadome.txt"
            loc_path.parent.mkdir(parents=True, exist_ok=True)
            loc_path.write_text(new_cookie.strip() + "\n", encoding="utf-8")
            print(f"[+] Cookie enregistre dans {loc_path}")

            # Envoi sur le VPS
            push_cookie_to_vps(new_cookie, args.host)

            # Test de confirmation
            time.sleep(1)
            probe_vps_status(args.host)
        else:
            print("[-] Echec de la resolution du challenge.")
            sys.exit(1)
    finally:
        tunnel.terminate()
        try:
            tunnel.wait(timeout=2)
        except Exception:
            tunnel.kill()


if __name__ == "__main__":
    main()
