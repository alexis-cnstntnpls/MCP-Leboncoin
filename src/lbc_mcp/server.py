"""Serveur MCP : les outils Leboncoin exposes a Claude / ChatGPT.

Inclut les outils de base (search_ads, get_ad, get_seller) ainsi que
les outils avances de suivi (historique de prix, veille automatique et bonnes affaires).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal, TypeVar

import anyio.to_thread
import lbc
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from .database import Database
from .formatting import ad_to_dict, price_stats, seller_to_dict, write_export
from .leboncoin import Criteria, Leboncoin, LeboncoinError, parse_ad_id, prepare_search

T = TypeVar("T")

# Construits depuis lbc pour suivre ses mises a jour
CategoryName = Literal[tuple(category.name for category in lbc.Category)]  # type: ignore[valid-type]
RegionName = Literal[tuple(region.name for region in lbc.Region)]  # type: ignore[valid-type]

# Au-dela, la reponse ne tient plus confortablement dans le contexte de Claude.
MAX_INLINE_RESULTS = 300

INSTRUCTIONS = """\
Recherche d'annonces Leboncoin (France) avec suivi des prix et veille automatique.

- search_ads : recherche d'annonces avec filtres, tri et pagination.
- get_ad : fiche detaillee d'une annonce et son historique de prix.
- get_seller : informations et avis d'un vendeur.
- get_price_history : historique des variations de prix d'une annonce.
- get_recent_deals : meilleures baisses de prix et opportunites recentes.
- add_watchlist / list_watchlist : gestion de la veille automatique en arriere-plan.
"""

mcp = MCPServer(name="leboncoin", instructions=INSTRUCTIONS)
gateway = Leboncoin()
db = Database()

# Verrou FIFO strict : une seule requete Leboncoin traitee a la fois tous agents confondus
REQUEST_QUEUE_LOCK = anyio.Lock()

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)


async def _run(function: Callable[..., T], *args: Any) -> T:
    """Execute un appel bloquant hors de la boucle d'evenements, serialise en file d'attente FIFO."""
    async with REQUEST_QUEUE_LOCK:
        try:
            return await anyio.to_thread.run_sync(function, *args)
        except LeboncoinError as exc:
            raise ToolError(str(exc)) from None


@mcp.tool(title="Rechercher des annonces Leboncoin", annotations=READ_ONLY)
async def search_ads(
    ctx: Context,
    query: Annotated[
        str | None,
        Field(description="Mots-cles. 'velo OR trottinette' pour l'un ou l'autre."),
    ] = None,
    category: Annotated[
        CategoryName,
        Field(description="Categorie ; les sous-categories sont prefixees par leur parent."),
    ] = "TOUTES_CATEGORIES",
    city: Annotated[
        str | None,
        Field(
            description="Commune francaise autour de laquelle chercher : nom ('Lyon'), "
            "code postal ('69003') ou 'Saint-Denis (974)' pour lever une homonymie."
        ),
    ] = None,
    radius_km: Annotated[float, Field(ge=1, le=200, description="Rayon autour de city.")] = 10,
    departments: Annotated[
        list[str] | None,
        Field(description="Numeros ('69', '5') ou noms ('Gironde') de departements."),
    ] = None,
    regions: Annotated[list[RegionName] | None, Field(description="Regions.")] = None,
    price_min: Annotated[int | None, Field(ge=0, description="Prix minimum en euros.")] = None,
    price_max: Annotated[int | None, Field(ge=0, description="Prix maximum en euros.")] = None,
    sort: Literal["relevance", "newest", "oldest", "price_asc", "price_desc"] = "relevance",
    seller_type: Annotated[
        Literal["all", "private", "pro"],
        Field(description="Particuliers, professionnels ou les deux."),
    ] = "all",
    shippable_only: Annotated[bool, Field(description="Seulement avec livraison.")] = False,
    title_only: Annotated[bool, Field(description="Chercher les mots-cles dans le titre seul.")] = False,
    ad_type: Annotated[
        Literal["offer", "demand"],
        Field(description="offer : annonces de vente/offre ; demand : demandes."),
    ] = "offer",
    filters: Annotated[
        dict[str, dict[str, int | None] | list[str | int | None]] | None,
        Field(
            description="Filtres avances, par cle d'API Leboncoin. Intervalle : [min, max] ou "
            "{'min': x, 'max': y}, une borne pouvant etre null. Enumeration : liste de codes texte."
        ),
    ] = None,
    url: Annotated[
        str | None,
        Field(
            description="URL d'une recherche faite sur leboncoin.fr. Si fournie, elle remplace "
            "tous les autres criteres."
        ),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=100, description="Annonces par page.")] = 35,
    page: Annotated[int, Field(ge=1, description="Premiere page a recuperer.")] = 1,
    pages: Annotated[
        int,
        Field(ge=1, le=50, description="Nombre de pages consecutives a recuperer."),
    ] = 1,
    export_format: Annotated[
        Literal["csv", "json"] | None,
        Field(description="Ecrit toutes les annonces trouvees dans un fichier export."),
    ] = None,
) -> dict[str, Any]:
    """Recherche des annonces sur Leboncoin.
    
    Enregistre automatiquement les annonces dans la base de donnees locale pour
    historiser les prix et reperer les futures baisses de prix.
    """
    if export_format is None and limit * pages > MAX_INLINE_RESULTS:
        raise ToolError(
            f"{limit * pages} annonces demandees : au-dela de {MAX_INLINE_RESULTS}, "
            "utiliser export_format='csv' ou 'json'."
        )

    criteria = Criteria(
        query=query,
        url=url,
        category=category,
        city=city,
        radius_km=radius_km,
        departments=departments or [],
        regions=regions or [],
        price_min=price_min,
        price_max=price_max,
        sort=sort,
        seller_type=seller_type,
        shippable_only=shippable_only,
        title_only=title_only,
        ad_type=ad_type,
        filters=filters or {},
    )
    prepared = await _run(prepare_search, criteria)
    start = page if page > 1 else prepared.first_page
    notes = list(prepared.notes)

    ads: list[lbc.Ad] = []
    seen: set[int] = set()
    first_result: lbc.Search | None = None
    next_page: int | None = start

    for current in range(start, start + pages):
        try:
            result = await _run(gateway.search_page, prepared, limit, current)
        except ToolError as exc:
            if not ads:
                raise
            notes.append(f"Arret a la page {current} : {exc}")
            break
        first_result = first_result or result
        for ad in result.ads:
            if ad.id not in seen:
                seen.add(ad.id)
                ads.append(ad)
                try:
                    db.record_ad(ad_to_dict(ad, full=True))
                except Exception:
                    pass

        next_page = current + 1
        if pages > 1:
            await ctx.report_progress(current - start + 1, pages, f"{len(ads)} annonces")
        if not result.ads or (result.max_pages and current >= result.max_pages):
            next_page = None
            break

    assert first_result is not None
    response: dict[str, Any] = {
        "total": first_result.total,
        "total_private": first_result.total_private,
        "total_pro": first_result.total_pro,
        "total_shippable": first_result.total_shippable,
        "returned": len(ads),
        "next_page": next_page,
        "price_stats": price_stats(ads),
    }
    if notes:
        response["notes"] = notes

    formatted_ads = []
    for ad in ads:
        d = ad_to_dict(ad)
        try:
            hist = db.get_price_history(ad.id)
            if hist and hist.get("price_drop_pct", 0) > 0:
                d["price_drop_pct"] = hist["price_drop_pct"]
                d["first_price"] = hist["first_price"]
        except Exception:
            pass
        formatted_ads.append(d)

    if export_format:
        label = query or (category if category != "TOUTES_CATEGORIES" else "recherche")
        path = await anyio.to_thread.run_sync(write_export, ads, export_format, label)
        response["export_file"] = str(path)
        response["sample"] = formatted_ads[:5]
    else:
        response["ads"] = formatted_ads

    return response


@mcp.tool(title="Detail d'une annonce Leboncoin", annotations=READ_ONLY)
async def get_ad(
    ad: Annotated[str, Field(description="Identifiant numerique ou URL de l'annonce.")],
) -> dict[str, Any]:
    """Detail complet d'une annonce : description, photos, attributs,
    vendeur et historique des prix enregistres."""
    ad_obj = await _run(gateway.get_ad, ad)
    data = ad_to_dict(ad_obj, full=True)
    try:
        db.record_ad(data)
    except Exception:
        pass

    hist = db.get_price_history(data["id"])
    if hist:
        data["price_history"] = hist["history"]
        data["min_price"] = hist["min_price"]
        data["max_price"] = hist["max_price"]
        data["price_drop_pct"] = hist["price_drop_pct"]

    return data


@mcp.tool(title="Profil d'un vendeur Leboncoin", annotations=READ_ONLY)
async def get_seller(
    seller: Annotated[
        str,
        Field(description="seller_id renvoye par get_ad, ou identifiant/URL d'une annonce du vendeur."),
    ],
) -> dict[str, Any]:
    """Profil d'un vendeur : anciennete, note sur 5, avis, delai de reponse
    et annonces en ligne."""
    user, ad = await _run(gateway.get_seller, seller)
    data = seller_to_dict(user)
    if ad is not None:
        data["from_ad"] = {"id": ad.id, "title": ad.subject}
    return data


@mcp.tool(title="Historique de prix d'une annonce", annotations=READ_ONLY)
async def get_price_history(
    ad: Annotated[str, Field(description="Identifiant numerique ou URL de l'annonce.")],
) -> dict[str, Any]:
    """Consulte l'historique des prix enregistres pour une annonce Leboncoin."""
    ad_id = parse_ad_id(ad)
    hist = await anyio.to_thread.run_sync(db.get_price_history, ad_id)
    if not hist:
        try:
            ad_obj = await _run(gateway.get_ad, ad_id)
            db.record_ad(ad_to_dict(ad_obj, full=True))
            hist = await anyio.to_thread.run_sync(db.get_price_history, ad_id)
        except Exception:
            pass

    if not hist:
        raise ToolError(f"Aucun historique enregistre pour l'annonce {ad_id}.")
    return hist


@mcp.tool(title="Bonnes affaires et baisses de prix", annotations=READ_ONLY)
async def get_recent_deals(
    min_drop_pct: Annotated[float, Field(ge=0, description="Pourcentage minimal de baisse de prix.")] = 5.0,
    limit: Annotated[int, Field(ge=1, le=50, description="Nombre maximal d'annonces a renvoyer.")] = 20,
) -> dict[str, Any]:
    """Renvoie les annonces ayant connu les plus fortes baisses de prix enregistrees en base."""
    deals = await anyio.to_thread.run_sync(db.get_recent_deals, limit, min_drop_pct)
    return {"count": len(deals), "deals": deals}


@mcp.tool(title="Ajouter une recherche en veille automatique")
async def add_watchlist(
    name: Annotated[str, Field(description="Nom descriptif de la recherche a surveiller.")],
    query: Annotated[str | None, Field(description="Mots-cles a surveiller.")] = None,
    category: Annotated[CategoryName, Field(description="Categorie.")] = "TOUTES_CATEGORIES",
    price_min: Annotated[int | None, Field(description="Prix minimum.")] = None,
    price_max: Annotated[int | None, Field(description="Prix maximum.")] = None,
    city: Annotated[str | None, Field(description="Ville.")] = None,
    radius_km: Annotated[float, Field(description="Rayon en km.")] = 10.0,
    departments: Annotated[list[str] | None, Field(description="Departements.")] = None,
    shippable_only: Annotated[bool, Field(description="Livraison uniquement.")] = False,
    interval_seconds: Annotated[int, Field(ge=60, le=86400, description="Intervalle entre scans en secondes.")] = 300,
) -> dict[str, Any]:
    """Ajoute une recherche a la veille automatique en arriere-plan (detection de nouvelles annonces et baisses de prix)."""
    w_id = await anyio.to_thread.run_sync(
        db.add_watchlist,
        name,
        query,
        category,
        price_min,
        price_max,
        city,
        radius_km,
        departments,
        shippable_only,
        interval_seconds,
    )
    return {
        "status": "added",
        "watchlist_id": w_id,
        "name": name,
        "query": query,
        "interval_seconds": interval_seconds,
    }


@mcp.tool(title="Lister les recherches surveillees", annotations=READ_ONLY)
async def list_watchlist() -> dict[str, Any]:
    """Liste toutes les recherches activement surveillees en arriere-plan."""
    items = await anyio.to_thread.run_sync(db.list_watchlist, True)
    return {"count": len(items), "watchlist": items}


def main() -> None:
    mcp.run()
