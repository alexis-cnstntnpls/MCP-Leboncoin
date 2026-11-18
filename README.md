# Leboncoin MCP Server (France)

Serveur [MCP (Model Context Protocol)](https://modelcontextprotocol.io) complet et résilient pour **Leboncoin France**, conçu pour être connecté à **Claude Desktop**, **Cursor**, **Cline**, **Claude Code** ou **ChatGPT** (via Streamable HTTP).

Ce serveur ne se contente pas de chercher des annonces : il intègre un **moteur de veille autonome**, un **suivi d'historique des prix en base SQLite**, un **collecteur hybride (API + Next.js SSR)** pour résister aux protections anti-bot, ainsi qu'une **méthodologie experte de recherche et d'audit d'annonces (Skill v4.0.0)**.

---

## Sommaire

- [Fonctionnalités clés](#-fonctionnalités-clés)
- [Catalogue des Outils MCP](#-catalogue-des-outils-mcp)
- [Prompts et Ressources MCP](#-prompts-et-ressources-mcp)
- [Architecture & Résilience Anti-Bot (DataDome)](#-architecture--résilience-anti-bot-datadome)
- [Prérequis & Installation](#-prérequis--installation)
- [Modes d'Exécution & Configuration](#-modes-dexécution--configuration)
  - [1. Mode local standard : stdio (Claude Desktop / Cursor)](#1-mode-local-standard--stdio-claude-desktop--cursor)
  - [2. Mode serveur HTTP : Streamable HTTP / SSE (ChatGPT / Accès distant)](#2-mode-serveur-http--streamable-http--sse-chatgpt--accès-distant)
- [Variables d'Environnement](#-variables-denvironnement)
- [Tests & Validation](#-tests--validation)
- [Bibliothèques & Références](#-bibliothèques--références)
- [Licence & Avertissement](#-licence--avertissement)

---

## 🌟 Fonctionnalités clés

1. **Recherche Multi-Critères Avancée :**
   - Recherche par mots-clés, filtres de prix min/max, catégories, types de vendeur (particulier/pro), livraison activée.
   - Géolocalisation intelligente : résolution de communes françaises (`"Lyon"`, `"69003"`, `"Saint-Denis (974)"`) avec rayon en km via l'API officielle `geo.api.gouv.fr`.
   - Réplication directe d'une recherche depuis une URL du site `leboncoin.fr`.
   - Export en masse (jusqu'à des centaines d'annonces) au format CSV (compatible Excel FR) ou JSON.

2. **Historisation Automatique des Prix :**
   - Chaque annonce consultée ou recherchée est enregistrée dans une base de données locale SQLite.
   - Détection des baisses de prix, du prix d'origine et calcul des pourcentages de réduction au fil du temps.

3. **Moteur de Veille en Arrière-Plan (Watchlist) :**
   - Possibilité d'enregistrer des recherches récurrentes surveillées par un démon en tâche de fond.
   - Alertes automatiques en cas de nouvelle annonce détectée ou de baisse de prix.

4. **Résilience Anti-Bot Avancée :**
   - Collecte hybride : interroge l'API mobile ou bascule de façon transparente sur le rendu web **Next.js SSR (`__NEXT_DATA__`)** capable d'extraire les données sans session complexe.
   - Gestion et injection de cookie DataDome (`datadome.txt` ou variable d'environnement).
   - File d'attente FIFO sérialisée avec temporisation aléatoire pour respecter les limites de débit.

5. **Skill Méthodologique Intégrée (v4.0.0) :**
   - Instructions système guidant l'IA pour exclure les annonces déjà vendues ou avec achat en cours (`transaction_status`), repérer les annonces fantômes (croisement favoris / ancienneté), auditer la réputation du vendeur et calculer le coût complet (prix + port + accessoires).

---

## 🛠 Catalogue des Outils MCP

| Outil | Description |
| :--- | :--- |
| **`search_ads`** | Recherche d'annonces avec filtres complets (texte, URL de recherche, catégorie, ville + rayon, départements, régions, tri, prix min/max, livraison, type de vendeur). Enregistre automatiquement les résultats dans la base SQLite locale pour historiser les prix. |
| **`get_ad`** | Fiche détaillée d'une annonce (titre, prix, description complète, photos HD, statut de transaction, géolocalisation, vendeur et historique de prix enregistré). |
| **`get_seller`** | Profil d'un vendeur (nom, type de compte particulier/pro, note sur 5, nombre d'avis vérifiés, date d'inscription et nombre d'annonces en ligne). |
| **`get_price_history`** | Historique chronologique complet des variations de prix d'une annonce enregistrée dans la base locale (prix initial, prix minimum, baisse en pourcentage). |
| **`get_recent_deals`** | Liste les meilleures baisses de prix récemment observées en base (filtrables par pourcentage minimal de baisse). |
| **`add_watchlist`** | Ajoute une recherche à la veille automatique périodique en arrière-plan. |
| **`list_watchlist`** | Liste toutes les veilles actuellement actives avec leurs paramètres et intervalles de scan. |

---

## 💡 Prompts et Ressources MCP

En plus des outils, le serveur expose les primitives natives du protocole MCP :

- **Prompt MCP : `leboncoin_research`**
  - Permet à l'IA d'exécuter une recherche guidée en plusieurs passes (termes exacts, synonymes, équivalences d'usage, opportunités récentes) selon la méthodologie d'évaluation v4.0.0.
  - Arguments : `besoin`, `budget_max` (optionnel), `ville_ou_zone` (optionnel).
- **Ressource MCP : `leboncoin://skill/research-guide`**
  - Fournit le texte intégral de la méthodologie d'audit et de qualification d'annonces Leboncoin consultable directement par les agents IA.

---

## 🛡 Architecture & Résilience Anti-Bot (DataDome)

Leboncoin est protégé par la solution anti-bot DataDome. Ce serveur intègre plusieurs lignes de défense :

1. **Empreinte TLS / JA3 (via `curl_cffi`) :**
   - Les requêtes HTTP imitent fidèlement les navigateurs modernes (`chrome_android` ou `chrome131`) pour éviter le rejet immédiat au niveau handshake TLS.
2. **Collecteur Autonome Next.js SSR :**
   - En cas d'inaccessibilité de l'API mobile, le moteur tente d'extraire les données directement depuis le flux Next.js Server-Side Rendering (`<script id="__NEXT_DATA__">`) de la page web, permettant une récupération propre sans dépendance de jetons applicatifs complexes.
3. **Persistance de session / Cookie DataDome :**
   - Si un cookie `datadome` est requis, le serveur peut le lire automatiquement depuis la variable `LBC_DATADOME_COOKIE`, un fichier `datadome.txt`, ou le trousseau local d'un navigateur sur la machine hôte.
4. **File d'attente FIFO & Débit contrôlé :**
   - Toutes les requêtes sortantes passent par un verrou sérialisé `REQUEST_QUEUE_LOCK` avec un délai paramétrable (`LBC_MIN_DELAY` / `LBC_MAX_DELAY`) pour éviter tout bannissement d'IP lié aux rafales concurrentes.

---

## 📦 Prérequis & Installation

- **Python :** Version 3.10 ou supérieure.
- **Système d'exploitation :** Linux, macOS ou Windows.

### Installation pas à pas

```bash
# 1. Cloner le dépôt
git clone https://github.com/votre-compte/MCP-Leboncoin.git
cd MCP-Leboncoin

# 2. Créer l'environnement virtuel Python
python3 -m venv .venv

# 3. Activer l'environnement virtuel
# Sur Linux / macOS :
source .venv/bin/activate
# Sur Windows :
# .venv\Scripts\activate

# 4. Installer les dépendances en mode éditable
pip install --upgrade pip
pip install -e .
```

---

## 🚀 Modes d'Exécution & Configuration

### 1. Mode local standard : stdio (Claude Desktop / Cursor)

C'est le mode le plus simple pour exécuter le serveur localement sur votre ordinateur personnel.

#### Configuration pour Claude Desktop

Ouvrez le fichier de configuration de Claude Desktop :
- **macOS :** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows :** `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux :** `~/.config/Claude/claude_desktop_config.json`

Ajoutez la section suivante (adaptez le chemin absolu vers votre dossier) :

```json
{
  "mcpServers": {
    "leboncoin": {
      "command": "/chemin/absolu/vers/MCP-Leboncoin/.venv/bin/python",
      "args": ["-m", "lbc_mcp"]
    }
  }
}
```

Redémarrez ensuite Claude Desktop. Le marteau d'outils Leboncoin apparaîtra dans l'interface.

#### Configuration pour Claude Code (CLI)

```bash
claude mcp add leboncoin -- /chemin/absolu/vers/MCP-Leboncoin/.venv/bin/python -m lbc_mcp
```

---

### 2. Mode serveur HTTP : Streamable HTTP / SSE (ChatGPT / Accès distant)

Pour connecter le serveur à **ChatGPT** (menu *Plugins / Serveurs MCP*) ou pour l'exécuter sur une machine distante derrière un reverse-proxy HTTPS (Caddy, Nginx) :

```bash
python run_http.py
```

Par défaut, le serveur écoute sur `http://127.0.0.1:8000/mcp`.

#### Exemple de service systemd (Linux)

Pour un fonctionnement permanent en tâche de fond :

```ini
[Unit]
Description=Serveur MCP Leboncoin
After=network.target

[Service]
Type=simple
User=votre_utilisateur
WorkingDirectory=/chemin/vers/MCP-Leboncoin
Environment="MCP_HOST=127.0.0.1"
Environment="MCP_PORT=8000"
Environment="MCP_PATH=/mcp"
Environment="MCP_PUBLIC_HOST=localhost"
Environment="ENABLE_MONITOR=0"
ExecStart=/chemin/vers/MCP-Leboncoin/.venv/bin/python /chemin/vers/MCP-Leboncoin/run_http.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## ⚙️ Variables d'Environnement

Toutes les variables sont optionnelles et disposent de valeurs par défaut saines :

| Variable | Défaut | Description |
| :--- | :--- | :--- |
| `MCP_HOST` | `127.0.0.1` | Adresse IP d'écoute pour le mode HTTP. |
| `MCP_PORT` | `8000` | Port d'écoute pour le mode HTTP. |
| `MCP_PATH` | `/mcp` | Préfixe du chemin HTTP (ex: `/mcp` ou `/mcp/leboncoin`). |
| `MCP_PUBLIC_HOST` | `localhost` | Nom d'hôte public attendu dans les en-têtes HTTP (utile derrière reverse-proxy). |
| `LBC_DB_PATH` | `~/.local/share/leboncoin/leboncoin.db` | Emplacement du fichier de base de données SQLite. |
| `LBC_COOKIE_FILE` | `~/.config/leboncoin/datadome.txt` | Fichier contenant un cookie DataDome valide. |
| `LBC_DATADOME_COOKIE` | *(aucun)* | Valeur directe d'un cookie DataDome valide. |
| `LBC_IMPERSONATE` | `chrome_android` | Empreinte navigateur TLS (`chrome_android`, `chrome131`, `safari`, etc.). |
| `LBC_MIN_DELAY` | `2.0` | Délai minimal aléatoire (en secondes) entre deux requêtes. |
| `LBC_MAX_DELAY` | `5.0` | Délai maximal aléatoire (en secondes) entre deux requêtes. |
| `LBC_PROXY` | *(aucun)* | Proxy HTTP/SOCKS à utiliser (`http://user:pass@host:port` ou `socks5://...`). |
| `ENABLE_MONITOR` | `0` | Passer à `1` pour démarrer le démon de veille automatique en arrière-plan. |
| `MONITOR_INTERVAL_SECONDS` | `300` | Intervalle de scrutation de la veille (en secondes). |
| `LBC_EXPORT_DIR` | `~/Downloads/leboncoin` | Dossier par défaut des exports de recherche CSV/JSON. |

---

## 🧪 Tests & Validation

### Lancer la suite de tests unitaires

```bash
python -m pytest
```

*(Les tests unitaires utilisent des bouchons et n'émettent pas de requêtes réelles vers Leboncoin).*

### Lancer le test d'intégration de bout en bout (Smoke Test)

```bash
python scripts/smoke_test.py
```

Ce script démarre le serveur MCP en sous-processus `stdio` et exécute un cycle de recherche réel pour vérifier l'accès réseau et la validité des parsers.

---

## 📚 Bibliothèques & Références

Ce projet s'appuie sur d'excellentes bibliothèques open-source :

- **[Model Context Protocol SDK (`mcp`)](https://github.com/modelcontextprotocol/python-sdk)** : SDK officiel Anthropic pour l'implémentation de serveurs et clients MCP.
- **[lbc](https://github.com/etienne-hd/lbc)** par *@etienne-hd* : Client Python non officiel pour l'API Leboncoin.
- **[leboncoin-mcp](https://github.com/BPiroga/leboncoin-mcp)** par *@BPiroga* : Projet initial ayant inspiré cette version améliorée.
- **[curl_cffi](https://github.com/yifeikong/curl_cffi)** : Bibliothèque Python avec bindings libcurl et support natif de l'usurpation d'empreinte TLS / JA3 / JA4.
- **[geo.api.gouv.fr](https://geo.api.gouv.fr)** : API ouverte du gouvernement français pour le géocodage des communes et départements.

---

## ⚖️ Licence & Avertissement

- Ce projet est publié sous **Licence MIT**.
- **Avertissement légal :** Ce logiciel est un projet indépendant et n'a aucun lien d'affiliation avec la société *Leboncoin*. Il utilise des interfaces non documentées susceptibles d'évoluer. Son utilisation doit être réalisée dans le respect des conditions générales d'utilisation de la plateforme.
