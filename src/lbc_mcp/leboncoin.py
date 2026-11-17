"""Acces a Leboncoin, entierement delegue a la bibliotheque lbc.

Ce module traduit les criteres recus par les outils MCP en appels lbc, et
rien de plus : lbc s'occupe de la session, de l'imitation d'un navigateur et
du format de l'API.

Leboncoin est protege par Datadome, qui filtre d'abord sur l'empreinte TLS du
client. lbc en tire une au hasard parmi quatre ; lors des essais du
19/09/2026, seule chrome_android passait (8 sur 8), les autres etant refusees
des la premiere requete. On la fixe donc, sauf si LBC_IMPERSONATE dit autre
chose. Le seuil de debit tolere n'etant pas connu, toutes les requetes passent
en plus par un client unique, derriere un verrou qui les espace d'au moins
LBC_MIN_INTERVAL secondes, meme quand plusieurs outils sont appeles en parallele.
"""

from __future__ import annotations

import json
import os
import random
import re
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, TypeVar

import lbc
from curl_cffi.requests.exceptions import RequestException
from lbc.exceptions import DatadomeError, InvalidValue, NotFoundError, RequestError

from .cookie import get_datadome_cookie

T = TypeVar("T")

# Les deux tris par prix sont inverses dans lbc 1.1.6 : Sort.CHEAPEST envoie
# price/desc et renvoie les annonces les plus cheres en premier. On choisit donc
# le membre par sa valeur, ce qui reste juste le jour ou lbc corrige les noms.
SORTS: dict[str, lbc.Sort] = {
    "relevance": lbc.Sort(("relevance", None)),
    "newest": lbc.Sort(("time", "desc")),
    "oldest": lbc.Sort(("time", "asc")),
    "price_asc": lbc.Sort(("price", "asc")),
    "price_desc": lbc.Sort(("price", "desc")),
}

# L'API accepte une borne seule, mais lbc exige les deux bornes d'un intervalle.
# Une borne absente est remplacee par une valeur hors d'atteinte.
RANGE_FLOOR = 0
RANGE_CEILING = 999_999_999

DEFAULT_IMPERSONATE = "chrome_android"

BLOCKED_MESSAGE = (
    "Leboncoin (Datadome) a refuse la requete. Fournir un cookie valide via la variable "
    "d'environnement LBC_DATADOME_COOKIE ou le fichier ~/.config/leboncoin/datadome.txt, "
    "espacer davantage les requetes (variable LBC_MIN_INTERVAL) ou passer par un proxy "
    "residentiel francais (variable LBC_PROXY)."
)

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class LeboncoinError(Exception):
    """Echec anticipe, dont le message peut etre montre tel quel a Claude."""


# --- Criteres de recherche -------------------------------------------------


@dataclass
class Criteria:
    """Criteres d'une recherche, tels que les outils MCP les recoivent."""

    query: str | None = None
    url: str | None = None
    category: str = "TOUTES_CATEGORIES"
    city: str | None = None
    radius_km: float = 10
    departments: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    price_min: int | None = None
    price_max: int | None = None
    sort: str = "relevance"
    seller_type: str = "all"
    shippable_only: bool = False
    title_only: bool = False
    ad_type: str = "offer"
    filters: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreparedSearch:
    """Arguments prets pour `lbc.Client.search`, avec ce qu'il faut en dire."""

    kwargs: dict[str, Any]
    first_page: int = 1
    notes: list[str] = field(default_factory=list)


def prepare_search(criteria: Criteria) -> PreparedSearch:
    """Traduit des criteres en arguments lbc. Peut interroger l'API geo (ville)."""
    if criteria.url:
        url, page, notes = clean_search_url(criteria.url)
        return PreparedSearch(kwargs={"url": url}, first_page=page, notes=notes)

    try:
        category = lbc.Category[criteria.category.upper()]
    except KeyError:
        raise LeboncoinError(f"Categorie inconnue : {criteria.category!r}.") from None

    kwargs: dict[str, Any] = {
        "text": (criteria.query or "").strip() or None,
        "category": category,
        "sort": SORTS[criteria.sort],
        "ad_type": lbc.AdType(criteria.ad_type),
        "shippable": criteria.shippable_only or None,
        "search_in_title_only": criteria.title_only,
    }
    if criteria.seller_type != "all":
        kwargs["owner_type"] = lbc.OwnerType(criteria.seller_type)

    notes: list[str] = []
    locations: list[Any] = [parse_region(r) for r in criteria.regions]
    locations += [parse_department(d) for d in criteria.departments]
    if criteria.city:
        name, dept, lat, lng = geocode_city(criteria.city)
        radius_m = max(1, round(criteria.radius_km * 1000))
        locations.append(lbc.City(lat=lat, lng=lng, radius=radius_m, city=name))
        notes.append(f"Ville retenue : {name} ({dept}), rayon {criteria.radius_km:g} km.")
    if locations:
        kwargs["locations"] = locations

    filters = dict(criteria.filters)
    if criteria.price_min is not None or criteria.price_max is not None:
        filters["price"] = {"min": criteria.price_min, "max": criteria.price_max}
    for key, value in filters.items():
        kwargs[key] = normalize_filter(key, value)

    return PreparedSearch(kwargs=kwargs, notes=notes)


def normalize_filter(key: str, value: Any) -> list[Any]:
    """Met un filtre avance sous la forme attendue par lbc.

    lbc range une liste d'entiers dans les intervalles et une liste de chaines
    dans les enumerations. On accepte en plus {"min": .., "max": ..} et les
    bornes nulles, que lbc refuse.
    """
    if isinstance(value, dict):
        unknown = set(value) - {"min", "max"}
        if unknown:
            raise LeboncoinError(f"Filtre {key!r} : cles inconnues {sorted(unknown)}.")
        return _range(key, value.get("min"), value.get("max"))

    if isinstance(value, (str, int, float)):
        value = [value]
    if not isinstance(value, (list, tuple)) or not value:
        raise LeboncoinError(f"Filtre {key!r} : liste ou {{min, max}} attendu.")

    if all(isinstance(v, str) for v in value):
        return list(value)
    if len(value) == 2 and all(v is None or isinstance(v, (int, float)) for v in value):
        return _range(key, value[0], value[1])
    if all(isinstance(v, (int, str)) for v in value):
        return [str(v) for v in value]
    raise LeboncoinError(
        f"Filtre {key!r} : utiliser [min, max] pour un intervalle ou une liste de "
        "codes texte pour une enumeration."
    )


def _range(key: str, low: Any, high: Any) -> list[int]:
    if low is None and high is None:
        raise LeboncoinError(f"Filtre {key!r} : au moins une borne est requise.")
    try:
        low = RANGE_FLOOR if low is None else int(low)
        high = RANGE_CEILING if high is None else int(high)
    except (TypeError, ValueError):
        raise LeboncoinError(f"Filtre {key!r} : les bornes doivent etre des nombres.") from None
    if low > high:
        raise LeboncoinError(f"Filtre {key!r} : le minimum depasse le maximum.")
    return [low, high]


# --- URL de recherche ------------------------------------------------------

# Ordre impose par lbc : "search_in" modifie le filtre cree par "text", et
# "shippable" celui cree par "locations". Dans le desordre, lbc plante.
_URL_KEY_ORDER = {"text": 0, "search_in": 1, "locations": 2}
# Parametres de navigation du site, qui ne sont pas des filtres.
_URL_IGNORED_KEYS = {"page", "kst", "from"}


def clean_search_url(url: str) -> tuple[str, int, list[str]]:
    """Rend une URL de recherche Leboncoin digeste pour lbc.

    lbc ne decode pas les valeurs (text=clio%204 part tel quel), traite
    `page` comme un filtre et plante sur certains ordres de parametres. On
    reconstruit donc l'URL avec des valeurs decodees, dans un ordre sur, et on
    rend la page demandee a part.
    """
    parts = urllib.parse.urlsplit(url.strip())
    if not parts.netloc.endswith("leboncoin.fr") or not parts.query:
        raise LeboncoinError(
            "URL attendue : une page de recherche leboncoin.fr avec ses filtres, "
            "par exemple https://www.leboncoin.fr/recherche?category=2&text=clio"
        )

    page = 1
    kept: dict[str, str] = {}
    for key, value in urllib.parse.parse_qsl(parts.query):
        if key == "page":
            page = int(value) if value.isdigit() and int(value) > 0 else 1
        elif key not in _URL_IGNORED_KEYS:
            # lbc decoupe la requete sur & et = : ils ne doivent pas survivre au decodage.
            kept[key] = value.replace("&", " ").replace("=", " ")

    notes: list[str] = []
    if "search_in" in kept and "text" not in kept:
        del kept["search_in"]
    if "shippable" in kept and "locations" not in kept:
        del kept["shippable"]
        notes.append(
            "Filtre 'livraison possible' ignore : lbc ne le gere dans une URL "
            "qu'accompagne d'une localisation. Utiliser shippable_only a la place."
        )
    if not kept:
        raise LeboncoinError("Cette URL ne contient aucun filtre de recherche.")

    ordered = sorted(kept, key=lambda k: _URL_KEY_ORDER.get(k, len(_URL_KEY_ORDER)))
    query = "&".join(f"{k}={kept[k]}" for k in ordered)
    return f"https://www.leboncoin.fr/recherche?{query}", page, notes


# --- Localisation ----------------------------------------------------------


def _name_key(text: str) -> str:
    """Cle de comparaison sans accents ni ponctuation : lbc ecrit VAL_DOISE,
    l'utilisateur "Val-d'Oise"."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]", "", text.upper())


_DEPARTMENTS_BY_CODE = {d.value[2]: d for d in lbc.Department}
_DEPARTMENTS_BY_NAME = {_name_key(d.name): d for d in lbc.Department}
_REGIONS_BY_NAME = {_name_key(r.name): r for r in lbc.Region}


def parse_department(value: str) -> lbc.Department:
    """Accepte un numero ("69", "05") ou un nom ("Rhone", "Cotes-d'Armor")."""
    raw = str(value).strip()
    code = raw.lstrip("0") if raw.isdigit() else raw.upper()
    department = _DEPARTMENTS_BY_CODE.get(code) or _DEPARTMENTS_BY_NAME.get(_name_key(raw))
    if department is None:
        raise LeboncoinError(
            f"Departement inconnu : {value!r}. lbc ne connait que la metropole hors "
            "Corse ; pour la Corse et l'outre-mer, passer par regions "
            "(CORSE, GUADELOUPE, MARTINIQUE, GUYANE, REUNION)."
        )
    return department


def parse_region(value: str) -> lbc.Region:
    region = _REGIONS_BY_NAME.get(_name_key(value))
    if region is None:
        raise LeboncoinError(f"Region inconnue : {value!r}.")
    return region


_CITY_WITH_DEPT = re.compile(r"^(?P<name>.+?)\s*\((?P<dept>\d{2,3}|2[AB])\)$", re.I)


@lru_cache(maxsize=256)
def geocode_city(query: str) -> tuple[str, str, float, float]:
    """Trouve le centre d'une commune francaise : (nom, departement, lat, lng).

    lbc attend des coordonnees et ne sait pas les trouver. On interroge l'API
    publique geo.api.gouv.fr, sans cle. Accepte "Lyon", "69003" ou, pour lever
    une homonymie, "Saint-Denis (974)". A nom egal, la plus peuplee l'emporte.
    """
    text = query.strip()
    params = {"fields": "nom,centre,codeDepartement", "limit": "1"}
    if re.fullmatch(r"\d{5}", text):
        params["codePostal"] = text
    else:
        match = _CITY_WITH_DEPT.match(text)
        if match:
            text = match["name"]
            params["codeDepartement"] = match["dept"].upper().zfill(2)
        params |= {"nom": text, "boost": "population"}

    url = "https://geo.api.gouv.fr/communes?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            communes = json.load(response)
    except OSError as exc:
        raise LeboncoinError(f"Localisation de {query!r} impossible : {exc}.") from None

    if not communes or not communes[0].get("centre"):
        raise LeboncoinError(
            f"Commune introuvable : {query!r}. Donner un nom de commune francaise, "
            "un code postal, ou 'Nom (departement)'."
        )
    commune = communes[0]
    lng, lat = commune["centre"]["coordinates"]
    return commune["nom"], commune.get("codeDepartement", "?"), lat, lng


# --- Identifiants ----------------------------------------------------------


def parse_ad_id(value: str | int) -> int:
    """Accepte un identifiant d'annonce ou son URL."""
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    path = urllib.parse.urlsplit(text).path
    numbers = re.findall(r"\d{6,}", path)
    if not numbers:
        raise LeboncoinError(f"Identifiant ou URL d'annonce invalide : {value!r}.")
    return int(numbers[-1])


# --- Client ----------------------------------------------------------------


def proxy_from_env() -> lbc.Proxy | None:
    """Lit LBC_PROXY, de la forme http://utilisateur:motdepasse@hote:port."""
    raw = os.environ.get("LBC_PROXY", "").strip()
    if not raw:
        return None
    parts = urllib.parse.urlsplit(raw if "://" in raw else f"http://{raw}")
    if not parts.hostname or not parts.port:
        raise LeboncoinError("LBC_PROXY invalide : forme attendue http://user:pass@hote:port.")
    return lbc.Proxy(
        host=parts.hostname,
        port=parts.port,
        username=urllib.parse.unquote(parts.username) if parts.username else None,
        password=urllib.parse.unquote(parts.password) if parts.password else None,
        scheme=parts.scheme,
    )


class Leboncoin:
    """Client lbc partage, dont les requetes sont espacees, randomisees et serialisees."""

    def __init__(self, min_interval: float | None = None):
        # Delais par defaut : comportement humain randomise entre 3.5s et 7.5s
        self.min_delay = float(os.environ.get("LBC_MIN_DELAY", "3.5"))
        self.max_delay = float(os.environ.get("LBC_MAX_DELAY", "7.5"))
        if min_interval is not None:
            self.min_delay = min_interval
            self.max_delay = max(min_interval, min_interval * 1.5)
        self._client: lbc.Client | None = None
        self._current_cookie: str | None = None
        self._lock = threading.Lock()
        self._last_request = 0.0

    def _call(self, action: Callable[[lbc.Client], T]) -> T:
        with self._lock:
            # Randomisation humaine de l'attente entre deux requetes
            target_delay = random.uniform(self.min_delay, self.max_delay)
            wait = self._last_request + target_delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            # Micro-jitter humain supplementaire
            if self.min_delay > 0:
                time.sleep(random.uniform(0.1, 0.4))

            # Verification et rechargement dynamique du cookie si modifie sur disque
            fresh_cookie = get_datadome_cookie()

            try:
                if self._client is None:
                    client = lbc.Client(
                        proxy=proxy_from_env(),
                        impersonate=os.environ.get("LBC_IMPERSONATE") or DEFAULT_IMPERSONATE,
                        max_retries=0,
                    )
                    if fresh_cookie and hasattr(client, "session"):
                        client.session.cookies.set("datadome", fresh_cookie, domain=".leboncoin.fr")
                    self._client = client
                    self._current_cookie = fresh_cookie
                elif fresh_cookie and fresh_cookie != self._current_cookie and hasattr(self._client, "session"):
                    # Hot-reload du cookie sans redemarrer le client
                    self._client.session.cookies.set("datadome", fresh_cookie, domain=".leboncoin.fr")
                    self._current_cookie = fresh_cookie

                return action(self._client)

            except DatadomeError:
                # Tenter un rechargement immediat du cookie depuis le disque/env
                latest_cookie = get_datadome_cookie()
                if latest_cookie and latest_cookie != self._current_cookie and self._client and hasattr(self._client, "session"):
                    self._client.session.cookies.set("datadome", latest_cookie, domain=".leboncoin.fr")
                    self._current_cookie = latest_cookie
                    try:
                        return action(self._client)
                    except DatadomeError:
                        pass

                self._client = None  # repartir d'une session neuve la prochaine fois
                raise LeboncoinError(BLOCKED_MESSAGE) from None
            except NotFoundError:
                raise LeboncoinError("Introuvable : annonce retiree ou identifiant errone.") from None
            except InvalidValue as exc:
                raise LeboncoinError(f"Critere refuse par lbc : {exc}") from None
            except RequestError as exc:
                raise LeboncoinError(f"Leboncoin a refuse la requete : {exc}") from None
            except RequestException as exc:
                self._client = None
                raise LeboncoinError(f"Leboncoin injoignable : {exc}") from None
            finally:
                self._last_request = time.monotonic()

    def _build_ssr_url(self, kwargs: dict[str, Any], page: int = 1) -> str:
        """Construit l'URL de recherche web Next.js SSR a partir des arguments prepares."""
        if "url" in kwargs and kwargs["url"]:
            base_url = kwargs["url"]
            if page > 1:
                sep = "&" if "?" in base_url else "?"
                return f"{base_url}{sep}page={page}"
            return base_url

        params: dict[str, str] = {}
        if kwargs.get("text"):
            params["text"] = str(kwargs["text"])

        cat = kwargs.get("category")
        if cat and hasattr(cat, "value") and str(cat.value) != "0":
            params["category"] = str(cat.value)

        if page > 1:
            params["page"] = str(page)

        if kwargs.get("shippable"):
            params["shippable"] = "1"

        if kwargs.get("search_in_title_only"):
            params["search_in_title_only"] = "1"

        owner = kwargs.get("owner_type")
        if owner and hasattr(owner, "value"):
            params["owner_type"] = str(owner.value)

        sort = kwargs.get("sort")
        if sort and hasattr(sort, "value"):
            val = sort.value
            if val == ("price", "asc"):
                params["sort"] = "price"
            elif val == ("price", "desc"):
                params["sort"] = "price"
                params["order"] = "desc"
            elif val == ("time", "desc"):
                params["sort"] = "time"
            elif val == ("time", "asc"):
                params["sort"] = "time"
                params["order"] = "asc"

        price = kwargs.get("price")
        if isinstance(price, (list, tuple)) and len(price) == 2:
            p_min_str = str(price[0]) if price[0] is not None and price[0] > 0 else ""
            p_max_str = str(price[1]) if price[1] is not None and price[1] < 999_999_999 else ""
            if p_min_str or p_max_str:
                params["price"] = f"{p_min_str}-{p_max_str}"
        elif isinstance(price, dict):
            p_min = price.get("min")
            p_max = price.get("max")
            p_min_str = str(p_min) if p_min is not None and p_min > 0 else ""
            p_max_str = str(p_max) if p_max is not None and p_max < 999_999_999 else ""
            if p_min_str or p_max_str:
                params["price"] = f"{p_min_str}-{p_max_str}"

        locs = kwargs.get("locations")
        if locs and isinstance(locs, list):
            loc_tokens = []
            for loc in locs:
                if hasattr(loc, "id") and hasattr(loc, "department_code"):
                    loc_tokens.append(f"d_{loc.id}")
                elif hasattr(loc, "id") and hasattr(loc, "name"):
                    loc_tokens.append(f"r_{loc.id}")
                elif hasattr(loc, "lat") and hasattr(loc, "lng"):
                    radius = getattr(loc, "radius", 10000)
                    city_name = getattr(loc, "city", "city")
                    loc_tokens.append(f"{city_name}__{loc.lat}_{loc.lng}_{radius}")
            if loc_tokens:
                params["locations"] = ",".join(loc_tokens)

        return f"https://www.leboncoin.fr/recherche?{urllib.parse.urlencode(params)}"

    def _fetch_ssr_search(self, url: str) -> lbc.Search | None:
        """Collecte les annonces via le rendu Next.js SSR (__NEXT_DATA__)."""
        from curl_cffi import requests as cffi_requests
        proxy_cfg = proxy_from_env()
        proxies = {"http": proxy_cfg.url, "https": proxy_cfg.url} if proxy_cfg else None

        s = cffi_requests.Session(impersonate="chrome")
        if proxies:
            s.proxies = proxies

        r = s.get(url, timeout=20)
        if r.status_code == 200:
            m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r.text)
            if m:
                raw_data = json.loads(m.group(1))
                search_data = raw_data.get("props", {}).get("pageProps", {}).get("searchData", {})
                if search_data and "ads" in search_data:
                    return lbc.Search._build(raw=search_data, client=self._client)
        return None

    def _fetch_ssr_ad(self, ad_ref: str | int) -> lbc.Ad | None:
        """Recupere la fiche detaillee d'une annonce via le rendu Next.js SSR."""
        from curl_cffi import requests as cffi_requests
        proxy_cfg = proxy_from_env()
        proxies = {"http": proxy_cfg.url, "https": proxy_cfg.url} if proxy_cfg else None

        s = cffi_requests.Session(impersonate="chrome")
        if proxies:
            s.proxies = proxies

        url_str = str(ad_ref).strip()
        if "leboncoin.fr/ad/" in url_str:
            target_url = url_str
        else:
            r1 = s.get(f"https://www.leboncoin.fr/recherche?text={url_str}", timeout=20)
            if r1.status_code != 200:
                return None
            m1 = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r1.text)
            if not m1:
                return None
            sd = json.loads(m1.group(1)).get("props", {}).get("pageProps", {}).get("searchData", {})
            ads = sd.get("ads", [])
            if not ads:
                return None
            target_url = ads[0].get("url")
            if not target_url:
                return None

        r2 = s.get(target_url, timeout=20)
        if r2.status_code == 200:
            m2 = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r2.text)
            if m2:
                raw_ad = json.loads(m2.group(1)).get("props", {}).get("pageProps", {}).get("ad", {})
                if raw_ad:
                    return lbc.Ad._build(raw=raw_ad, client=self._client)
        elif r2.status_code in (404, 410):
            raise NotFoundError("Annonce introuvable ou retiree.")
        return None

    def search_page(self, prepared: PreparedSearch, limit: int, page: int) -> lbc.Search:
        with self._lock:
            target_delay = random.uniform(self.min_delay, self.max_delay)
            wait = self._last_request + target_delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            if self.min_delay > 0:
                time.sleep(random.uniform(0.1, 0.4))

            # 1. Tenter la collecte directe via SSR Next.js (sans dependance cookie DataDome)
            try:
                ssr_url = self._build_ssr_url(prepared.kwargs, page=page)
                res = self._fetch_ssr_search(ssr_url)
                if res is not None:
                    if limit < len(res.ads):
                        res.ads = res.ads[:limit]
                    self._last_request = time.monotonic()
                    return res
            except Exception:
                pass

        # 2. Fallback sur le client d'API lbc
        return self._call(lambda client: client.search(**prepared.kwargs, limit=limit, page=page))

    def get_ad(self, ad: str | int) -> lbc.Ad:
        with self._lock:
            target_delay = random.uniform(self.min_delay, self.max_delay)
            wait = self._last_request + target_delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            if self.min_delay > 0:
                time.sleep(random.uniform(0.1, 0.4))

            # 1. Tenter la fiche annonce via SSR Next.js
            try:
                ad_obj = self._fetch_ssr_ad(ad)
                if ad_obj is not None:
                    self._last_request = time.monotonic()
                    return ad_obj
            except NotFoundError:
                raise LeboncoinError("Introuvable : annonce retiree ou identifiant errone.") from None
            except Exception:
                pass

        # 2. Fallback sur le client d'API lbc
        ad_id = parse_ad_id(ad)
        return self._call(lambda client: client.get_ad(ad_id))

    def get_user(self, user_id: str) -> lbc.User:
        return self._call(lambda client: client.get_user(user_id))

    def get_seller(self, reference: str) -> tuple[lbc.User, lbc.Ad | None]:
        """Profil d'un vendeur, a partir de son identifiant ou d'une de ses annonces."""
        reference = reference.strip()
        if UUID_RE.match(reference):
            return self.get_user(reference), None
        ad = self.get_ad(reference)
        if not ad._user_id:
            raise LeboncoinError("Cette annonce n'indique pas son vendeur.")
        return self.get_user(ad._user_id), ad
