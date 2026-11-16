# Guide de Déploiement — MCP Leboncoin & Moteur de Veille Autonome

Ce guide fournit la procédure complète pour déployer et configurer le serveur MCP Leboncoin amélioré sur le VPS Ubuntu (`/home/ubuntu/leboncoin-mcp`).

---

## 1. Origine du blocage DataDome et Résolution

### Diagnostic
- **Pourquoi le serveur précédent échouait systématiquement :** L'API `https://api.leboncoin.fr/finder/search` et le site sont filtrés au niveau CDN par DataDome. Toute requête sans cookie de session légitime (`datadome=...`) est bloquée dès l'étape HTTP (code 403 / captcha challenge), même derrière une IP résidentielle et même avec Playwright ou `curl_cffi`.
- **Pourquoi le navigateur habituel fonctionnait :** Le navigateur dispose d'un jeton de session `datadome` valide, accordé suite à la navigation normale et persistant jusqu'à **1 an** (`Cookie expires: 2027-11-16`).
- **Solution mise en place :** Le module `lbc_mcp.cookie` intègre ce jeton dans chaque session `lbc` et requêtes API. L'extraction locale est 100% automatique sur Linux, et paramétrable sur VPS via `LBC_DATADOME_COOKIE` ou `~/.config/leboncoin/datadome.txt`.

---

## 2. Déploiement sur le VPS Ubuntu (Oracle Cloud)

Toutes les commandes ci-dessous sont sur une seule ligne et directement copiables.

### Étape 1 : Mettre à jour le code sur le VPS
```bash
cd /home/ubuntu/leboncoin-mcp && git fetch origin && git checkout feature/autonomous-collector || git pull
```

### Étape 2 : Mettre à jour l'environnement virtuel Python
```bash
/home/ubuntu/leboncoin-mcp/.venv/bin/pip install --upgrade pip && /home/ubuntu/leboncoin-mcp/.venv/bin/pip install -e /home/ubuntu/leboncoin-mcp
```

### Étape 3 : Configurer le cookie DataDome et les permissions
```bash
sudo mkdir -p /home/lbcvpn/.config/leboncoin && sudo tee /home/lbcvpn/.config/leboncoin/datadome.txt > /dev/null << 'EOF'
ErD5rUSs1A3Bo7D0O925m5E9oG2HNuhN2sXu7UYzG2umMbbvDED1yWnVVqZ~cJaXxtMXFdPuymChhlnYO9uUfxe3yArsmISYTr6M_d9Kj9AgrJKw3~3lp75pHUXi5ipw
EOF
sudo chown -R lbcvpn:lbcvpn /home/lbcvpn/.config
```

### Étape 4 : Mettre à jour le service systemd
```bash
sudo systemctl edit leboncoin-mcp --drop-in=override.conf
```
Contenu recommandé pour l'override :
```ini
[Service]
User=lbcvpn
Group=lbcvpn
WorkingDirectory=/home/ubuntu/leboncoin-mcp
ExecStart=/home/ubuntu/leboncoin-mcp/.venv/bin/python /home/ubuntu/leboncoin-mcp/run_http.py
Environment="LBC_MIN_INTERVAL=2"
Environment="LBC_IMPERSONATE=chrome131"
Environment="MCP_PORT=8000"
Environment="MCP_HOST=127.0.0.1"
Environment="MCP_PUBLIC_HOST=mcp-lbc.duckdns.org"
Environment="ENABLE_MONITOR=1"
Environment="MONITOR_INTERVAL_SECONDS=300"
Environment="LBC_COOKIE_FILE=/home/lbcvpn/.config/leboncoin/datadome.txt"
Environment="LBC_DB_PATH=/home/lbcvpn/.local/share/leboncoin/leboncoin.db"
Restart=always
RestartSec=5
```

Commande en une seule ligne pour appliquer l'override systemd :
```bash
sudo tee /etc/systemd/system/leboncoin-mcp.service.d/override.conf << 'EOF'
[Service]
User=lbcvpn
Group=lbcvpn
WorkingDirectory=/home/ubuntu/leboncoin-mcp
ExecStart=/home/ubuntu/leboncoin-mcp/.venv/bin/python /home/ubuntu/leboncoin-mcp/run_http.py
Environment="LBC_MIN_INTERVAL=2"
Environment="LBC_IMPERSONATE=chrome131"
Environment="MCP_PORT=8000"
Environment="MCP_HOST=127.0.0.1"
Environment="MCP_PUBLIC_HOST=mcp-lbc.duckdns.org"
Environment="ENABLE_MONITOR=1"
Environment="MONITOR_INTERVAL_SECONDS=300"
Environment="LBC_COOKIE_FILE=/home/lbcvpn/.config/leboncoin/datadome.txt"
Environment="LBC_DB_PATH=/home/lbcvpn/.local/share/leboncoin/leboncoin.db"
Restart=always
RestartSec=5
EOF
sudo systemctl daemon-reload && sudo systemctl restart leboncoin-mcp
```

### Étape 5 : Vérifier le statut et les logs
```bash
sudo systemctl status leboncoin-mcp --no-pager
```

```bash
sudo journalctl -u leboncoin-mcp -n 30 --no-pager
```

---

## 3. Test de validation MCP en ligne de commande

### Initialisation MCP (Streamable HTTP)
```bash
curl -i --max-time 10 -X POST http://127.0.0.1:8000/mcp -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test-client","version":"1.0.0"}}}'
```

### Test de recherche réelle d'annonces (QNAP TS-410)
```bash
curl -s --max-time 20 -X POST http://127.0.0.1:8000/mcp -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_ads","arguments":{"query":"QNAP TS-410","limit":5}}}'
```

---

## 4. Outils MCP Disponibles dans ChatGPT / Claude

1. **`search_ads`** : Recherche d'annonces (mots-clés, filtres de prix, catégorie, ville, rayon, départements, tri). Enregistre automatiquement les annonces dans la base de données SQLite locale pour débuter le suivi de prix.
2. **`get_ad`** : Fiche détaillée de l'annonce (description complète, photos, vendeur, localisation, historique complet des prix et variation en pourcentage).
3. **`get_seller`** : Profil du vendeur (note sur 5, nombre d'avis, taux et délai de réponse, total d'annonces).
4. **`get_price_history`** : Historique chronologique précis des prix d'une annonce (prix initial, prix actuel, prix minimum/maximum, pourcentage de baisse).
5. **`get_recent_deals`** : Liste des annonces ayant subi les baisses de prix les plus importantes (style RacingTech).
6. **`add_watchlist`** : Ajoute une recherche à surveiller automatiquement en tâche de fond (toutes les X minutes).
7. **`list_watchlist`** : Affiche les recherches actuellement surveillées par le démon autonome.
