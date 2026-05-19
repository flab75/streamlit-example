import statistics
from typing import Dict, List, Optional

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

GEO_API_URL = "https://geo.api.gouv.fr/communes"
DVF_API_URL = "https://apidf-preprod.cerema.fr/dvf_opendata/geomutations/"


def get_commune_code(ville: str) -> Optional[str]:
    if not REQUESTS_AVAILABLE:
        return None
    try:
        resp = requests.get(
            GEO_API_URL,
            params={"nom": ville, "fields": "code,nom", "boost": "population", "limit": 1},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data:
            return data[0].get("code")
    except Exception:
        pass
    return None


def get_dvf_transactions(code_commune: str, nb_pieces: int = None) -> List[Dict]:
    if not REQUESTS_AVAILABLE:
        return []
    try:
        params = {"code_commune": code_commune, "page_size": 20}
        if nb_pieces is not None:
            params["nb_pieces"] = nb_pieces
        resp = requests.get(DVF_API_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        return results if isinstance(results, list) else []
    except Exception:
        return []


def _extract_price_per_m2(transactions: List[Dict]) -> List[float]:
    prices = []
    for t in transactions:
        valeur = t.get("valeur_fonciere") or t.get("prix")
        surface = t.get("surface_reelle_bati") or t.get("surface_m2")
        if valeur and surface and float(surface) > 0:
            try:
                prices.append(float(valeur) / float(surface))
            except (ValueError, TypeError):
                continue
    return prices


def enrich_listing(listing: dict) -> dict:
    location = listing.get("location", "")
    ville = location.split("-")[0].strip().split(",")[0].strip()
    if not ville:
        return listing

    code = get_commune_code(ville)
    if not code:
        listing["dvf_stats"] = {"error": "Commune non trouvée", "analyse": "Données insuffisantes"}
        return listing

    transactions = get_dvf_transactions(code)
    prices_m2 = _extract_price_per_m2(transactions)

    if not prices_m2:
        listing["dvf_stats"] = {
            "nb_transactions": 0,
            "prix_m2_median": None,
            "estimation_prix": None,
            "analyse": "Pas de données DVF disponibles",
        }
        return listing

    prix_m2_median = statistics.median(prices_m2)
    surface = listing.get("surface_m2")
    estimation_prix = int(prix_m2_median * surface) if surface else None

    prix_annonce = listing.get("price", 0)
    if estimation_prix and prix_annonce:
        ratio = prix_annonce / estimation_prix
        if ratio < 0.85:
            analyse = f"Bien sous-évalué ({ratio:.0%} de l'estimation DVF de {estimation_prix:,} €)"
        elif ratio > 1.15:
            analyse = f"Bien surévalué ({ratio:.0%} de l'estimation DVF de {estimation_prix:,} €)"
        else:
            analyse = f"Bien dans la moyenne du marché (estimation DVF : {estimation_prix:,} €)"
    else:
        analyse = f"Prix médian DVF : {prix_m2_median:.0f} €/m²"

    listing["dvf_stats"] = {
        "prix_m2_median": round(prix_m2_median),
        "nb_transactions": len(transactions),
        "estimation_prix": estimation_prix,
        "analyse": analyse,
    }
    return listing
