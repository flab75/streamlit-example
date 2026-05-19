"""
Scraper Fluximmo V1 — API officielle d'annonces immobilières françaises.
Endpoint confirmé : GET https://api.fluximmo.io/v1/adverts/search
Auth : header x-api-key: <clé>
"""

import hashlib
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.fluximmo.io/v1"
_ENDPOINT = "/adverts/search"

# Champs réponse Fluximmo V1 → format interne
_FIELD_ALIASES = {
    "unique_id":      "api_id",
    "id":             "api_id",
    "title":          "title",
    "description":    "description",
    # Prix — Fluximmo V1 expose price et price_per_area
    "price":          "price",
    "prix":           "price",
    "price_per_area": "price_per_area",   # €/m² (calculé si price absent)
    # Surfaces
    "surface":        "surface_m2",
    "living_surface": "surface_m2",
    "surface_habitable": "surface_m2",
    "land_surface":   "terrain_m2",       # terrain
    "terrain":        "terrain_m2",
    # Localisation
    "city":           "ville",
    "ville":          "ville",
    "zip_code":       "code_postal",
    "cp":             "code_postal",
    "postal_code":    "code_postal",
    "department":     "departement",
    "departement":    "departement",
    "region":         "region",
    "latitude":       "lat",
    "longitude":      "lng",
    # Source / URL
    "url":            "url",
    "website":        "source",
    "site_id":        "site_id",
    "agency":         "agency",
    # Type
    "ads_type":       "ads_type",          # "buy" / "rent"
    "property_type":  "type_bien",
    "type":           "type_bien",
    # Pièces / surface
    "rooms":          "nb_pieces",
    "nb_pieces":      "nb_pieces",
    "floor":          "floor",
    # Dates
    "created_at":     "pub_date",
    "published_at":   "pub_date",
    "date":           "pub_date",
}


def _normalize_listing(raw: dict) -> dict:
    out: dict = {}
    for k, v in raw.items():
        target = _FIELD_ALIASES.get(k)
        out[target if target else k] = v

    # Localisation — on inclut toujours le code postal ou le département
    # pour que le PropertyFilter puisse filtrer géographiquement
    parts = []
    if out.get("ville"):
        parts.append(str(out["ville"]).title())
    cp = str(out.get("code_postal", "") or "").strip()
    dept = str(out.get("departement", "") or "").strip()
    if cp:
        parts.append(f"({cp})")
    elif dept:
        # Convertit le code numérique dept en code postal partiel pour la détection
        parts.append(f"({dept})")
    location = " ".join(parts) if parts else ""

    # Prix — utilise price direct, ou calcule depuis price_per_area × surface
    def _int(v):
        try:
            return int(str(v).replace(" ", "").replace(",", "").replace("\xa0", ""))
        except Exception:
            return 0

    price = _int(out.get("price", 0))
    if not price and out.get("price_per_area") and out.get("terrain_m2"):
        price = _int(out["price_per_area"]) * _int(out["terrain_m2"])
    if not price and out.get("price_per_area") and out.get("surface_m2"):
        price = _int(out["price_per_area"]) * _int(out["surface_m2"])

    surface = _int(out.get("surface_m2")) or None
    terrain = _int(out.get("terrain_m2")) or None

    api_id = str(out.get("api_id", ""))
    url = str(out.get("url", "") or "")
    uid = hashlib.md5((api_id or url or str(raw)).encode()).hexdigest()[:8]

    source = str(out.get("source", "fluximmo"))
    # "bienici.com" → label affiché, mais la source interne reste "fluximmo"
    website_label = source.split(".")[0] if "." in source else source

    return {
        "id":           f"fluximmo-{api_id or uid}",
        "source":       "fluximmo",         # toujours "fluximmo" pour le filtre
        "website":      website_label,       # portail d'origine pour l'affichage
        "title":        str(out.get("title", "")),
        "price":        price,
        "surface_m2":   surface,
        "terrain_m2":   terrain,
        "description":  str(out.get("description", ""))[:800],
        "location":     location,
        "url":          url,
        "is_mock":      False,
        "date_scraped": datetime.now().isoformat(),
        "pub_date":     str(out.get("pub_date", "")),
        "type_bien":    str(out.get("type_bien", "")),
        "nb_pieces":    out.get("nb_pieces"),
        "price_per_area": _int(out.get("price_per_area", 0)) or None,
    }


def _extract_list(data) -> Optional[List[dict]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("adverts", "data", "results", "items", "listings",
                    "annonces", "biens", "records", "ads"):
            if key in data and isinstance(data[key], list):
                return data[key]
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return None


def _build_params(criteria: dict, limit: int = 50) -> dict:
    params: dict = {
        "ads_type": "buy",        # vente (vs "rent")
        "limit": limit,
        "page": 1,
    }
    if criteria.get("prix_max"):
        params["price_max"] = criteria["prix_max"]
        params["prix_max"] = criteria["prix_max"]
    if criteria.get("prix_min"):
        params["price_min"] = criteria["prix_min"]
        params["prix_min"] = criteria["prix_min"]
    if criteria.get("surface_min"):
        params["surface_min"] = criteria["surface_min"]
        params["living_surface_min"] = criteria["surface_min"]
    if criteria.get("terrain_min"):
        params["land_surface_min"] = criteria["terrain_min"]

    dept = criteria.get("filtre_departement", "")
    if dept:
        try:
            from .geo_data import resolve_dept
            code, name = resolve_dept(dept)
            if code:
                params["department"] = code
                params["departement"] = code
        except Exception:
            params["department"] = dept

    if criteria.get("filtre_ville"):
        params["city"] = criteria["filtre_ville"].upper()

    return params


# ── Fonction principale ────────────────────────────────────────────────────────

def scrape_fluximmo(api_key: str, criteria: dict) -> Tuple[List[Dict], Optional[str]]:
    """
    Interroge GET https://api.fluximmo.io/v1/adverts/search
    Retourne (listings, error_message).
    """
    try:
        import requests
    except ImportError:
        return [], "Module 'requests' manquant."

    url = _BASE_URL + _ENDPOINT
    headers = {"x-api-key": api_key, "Accept": "application/json"}
    params = _build_params(criteria)

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=20)
    except requests.exceptions.ConnectionError:
        return [], "Impossible de contacter api.fluximmo.io — vérifiez votre connexion."
    except requests.exceptions.Timeout:
        return [], "Timeout — api.fluximmo.io ne répond pas."
    except Exception as e:
        return [], f"Erreur réseau : {e}"

    if resp.status_code == 401:
        return [], f"Clé API invalide ou expirée (HTTP 401). Réponse : {resp.text[:200]}"
    if resp.status_code == 403:
        return [], f"Accès refusé (HTTP 403). Quota ou droits insuffisants. Réponse : {resp.text[:200]}"
    if resp.status_code == 429:
        return [], "Quota API Fluximmo dépassé (HTTP 429). Réessayez dans quelques instants."
    if resp.status_code != 200:
        return [], f"HTTP {resp.status_code} : {resp.text[:300]}"

    try:
        data = resp.json()
    except Exception:
        return [], f"Réponse non-JSON depuis {url} : {resp.text[:200]}"

    # Vérifier erreur applicative
    if isinstance(data, dict) and "error" in data:
        ec = data["error"].get("code") if isinstance(data["error"], dict) else ""
        em = data["error"].get("message", str(data["error"])) if isinstance(data["error"], dict) else str(data["error"])
        return [], f"Erreur API Fluximmo (code {ec}) : {em}"

    raw_list = _extract_list(data)
    if raw_list is None:
        keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
        return [], (
            f"Format de réponse inattendu depuis {url}.\n"
            f"Clés reçues : {keys}\n"
            f"Réponse brute : {str(data)[:400]}"
        )

    listings = []
    for raw in raw_list:
        try:
            listings.append(_normalize_listing(raw))
        except Exception as e:
            logger.debug("Erreur normalisation annonce Fluximmo : %s", e)

    logger.info("Fluximmo : %d annonces récupérées", len(listings))
    return listings, None


# ── Diagnostic ────────────────────────────────────────────────────────────────

_BASE_CANDIDATES = [
    "https://api.fluximmo.io/v1",
    "https://api.fluximmo.io/v2",
    "https://api.fluximmo.io",
    "https://api.fluximmo.com/v1",
    "https://api.fluximmo.com/v2",
    "https://api.fluximmo.com",
]

_ENDPOINT_CANDIDATES = [
    "/adverts/search",
    "/adverts",
    "/search",
    "/search/adverts",
    "/ads",
    "/ads/search",
    "/annonces",
    "/annonces/search",
    "/listings",
    "/biens",
    "/properties",
    "",
]


def diagnose_api(api_key: str) -> list[dict]:
    try:
        import requests
    except ImportError:
        return [{"url": "N/A", "status": "ERREUR", "detail": "Module requests manquant", "type": ""}]

    report = []
    h = {"x-api-key": api_key, "Accept": "application/json"}

    def _probe(url, method="GET", body=None):
        try:
            if method == "POST":
                r = requests.post(url, headers={**h, "Content-Type": "application/json"},
                                  json=body or {}, timeout=8)
            else:
                r = requests.get(url, headers=h, params={"limit": 1, "page": 1, "ads_type": "buy"}, timeout=8)
            raw = r.text[:800]
            rtype = method
            try:
                j = r.json()
                ec = j.get("error", {}).get("code") if isinstance(j, dict) else None
                em = j.get("error", {}).get("message", "") if isinstance(j, dict) else ""
                if ec == 10003:
                    rtype += " [route inconnue — 10003]"
                elif ec:
                    rtype += f" [erreur API code={ec}: {em}]"
            except Exception:
                pass
            return {"url": url, "status": r.status_code, "detail": raw, "type": rtype}
        except requests.exceptions.ConnectionError:
            return {"url": url, "status": "CONNEXION_REFUSEE", "detail": "", "type": method}
        except Exception as e:
            return {"url": url, "status": "ERR", "detail": str(e)[:200], "type": method}

    for base in _BASE_CANDIDATES:
        for ep in _ENDPOINT_CANDIDATES:
            report.append(_probe(base + ep))

    search_body = {"holdings": ["CLASS_HOUSE"], "ads_type": "buy", "limit": 1}
    for base in ["https://api.fluximmo.io/v1", "https://api.fluximmo.io/v2"]:
        for ep in ["/adverts/search", "/search"]:
            report.append(_probe(base + ep, method="POST", body=search_body))

    seen: set = set()
    return [r for r in report if not (r["url"] in seen or seen.add(r["url"]))]
