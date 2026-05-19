"""
Scraper Fluximmo — API officielle d'annonces immobilières françaises.
Documentation : https://doc.fluximmo.io/
Auth : header  x-api-key: <clé>
Base URL : https://api.fluximmo.io/v2
"""

import hashlib
import logging
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://api.fluximmo.io/v2"

# Mapping types de biens Fluximmo → label interne
_TYPE_BIEN_MAP = {
    "maison": ["maison", "villa", "chalet"],
    "appartement": ["appartement", "studio", "loft"],
    "terrain": ["terrain"],
    "ferme": ["ferme", "corps de ferme", "domaine", "propriété"],
}

# Champs de réponse Fluximmo → champs internes (noms connus de la V2)
_FIELD_ALIASES = {
    # prix
    "prix": "price", "price": "price", "prix_vente": "price",
    "loyer": "price",
    # surface habitable
    "surface": "surface_m2", "surface_habitable": "surface_m2",
    "surface_m2": "surface_m2",
    # terrain
    "terrain": "terrain_m2", "surface_terrain": "terrain_m2",
    "terrain_m2": "terrain_m2",
    # localisation
    "ville": "ville", "city": "ville",
    "departement": "departement", "dept": "departement",
    "code_postal": "code_postal", "cp": "code_postal",
    # description
    "titre": "title", "title": "title", "libelle": "title",
    "description": "description", "texte": "description",
    # url
    "url": "url", "lien": "url", "link": "url", "url_annonce": "url",
    # source
    "source": "source", "portail": "source", "origine": "source",
    # date
    "date_publication": "pub_date", "date": "pub_date",
    "created_at": "pub_date", "published_at": "pub_date",
    # id
    "id": "api_id", "_id": "api_id", "reference": "api_id",
    "id_annonce": "api_id",
    # type
    "type_bien": "type_bien", "type": "type_bien",
    "categorie": "type_bien",
    # nb pièces
    "nb_pieces": "nb_pieces", "pieces": "nb_pieces",
    "nb_rooms": "nb_pieces",
}


def _normalize_listing(raw: dict) -> dict:
    """Normalise un objet annonce brut Fluximmo vers le format interne."""
    out: dict = {}
    for k, v in raw.items():
        key_lower = k.lower()
        target = _FIELD_ALIASES.get(key_lower)
        if target:
            out[target] = v
        else:
            out[k] = v  # conserve les champs non mappés

    # Construire location depuis ville + dept + cp
    parts = []
    if out.get("ville"):
        parts.append(str(out["ville"]))
    if out.get("departement"):
        parts.append(str(out["departement"]))
    if out.get("code_postal"):
        parts.append(str(out["code_postal"]))
    location = " - ".join(parts) if parts else raw.get("location", "")

    # Normaliser les types numériques
    price = out.get("price", 0)
    if isinstance(price, str):
        price = int("".join(c for c in price if c.isdigit()) or "0")
    surface = out.get("surface_m2")
    if isinstance(surface, str):
        surface = int("".join(c for c in surface if c.isdigit()) or "0") or None
    terrain = out.get("terrain_m2")
    if isinstance(terrain, str):
        terrain = int("".join(c for c in terrain if c.isdigit()) or "0") or None

    api_id = str(out.get("api_id", ""))
    url = str(out.get("url", "") or "")
    uid = hashlib.md5((api_id or url or str(raw)).encode()).hexdigest()[:8]

    return {
        "id": f"fluximmo-{api_id or uid}",
        "source": str(out.get("source", "fluximmo")),
        "title": str(out.get("title", "")),
        "price": int(price) if price else 0,
        "surface_m2": surface,
        "terrain_m2": terrain,
        "description": str(out.get("description", "")),
        "location": location,
        "url": url,
        "is_mock": False,
        "date_scraped": datetime.now().isoformat(),
        "pub_date": str(out.get("pub_date", "")),
        "type_bien": str(out.get("type_bien", "")),
        "nb_pieces": out.get("nb_pieces"),
        "_raw": raw,  # conservé pour debug
    }


def _build_params(criteria: dict, page: int = 1, limit: int = 50) -> dict:
    """Construit les paramètres de requête Fluximmo depuis les critères pipeline."""
    params: dict = {
        "type_transaction": "vente",
        "type_bien": "maison",
        "page": page,
        "limit": limit,
    }

    if criteria.get("prix_max"):
        params["prix_max"] = criteria["prix_max"]
    if criteria.get("prix_min"):
        params["prix_min"] = criteria["prix_min"]
    if criteria.get("surface_min"):
        params["surface_min"] = criteria["surface_min"]
    if criteria.get("terrain_min"):
        params["terrain_min"] = criteria["terrain_min"]

    # Localisation
    dept = criteria.get("filtre_departement", "")
    if dept:
        try:
            from .geo_data import resolve_dept
            code, name = resolve_dept(dept)
            if code:
                params["departement"] = code
        except Exception:
            params["departement"] = dept

    if criteria.get("filtre_ville"):
        params["ville"] = criteria["filtre_ville"]

    if criteria.get("filtre_region"):
        params["region"] = criteria["filtre_region"]

    return params


def scrape_fluximmo(api_key: str, criteria: dict) -> tuple[List[Dict], Optional[str]]:
    """
    Interroge l'API Fluximmo et retourne (listings, error_message).
    error_message est None si tout s'est bien passé.
    """
    try:
        import requests
    except ImportError:
        return [], "Le module 'requests' n'est pas installé."

    headers = {
        "x-api-key": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    params = _build_params(criteria)
    listings: List[Dict] = []
    error_msg: Optional[str] = None

    # Endpoints candidates (la doc mentionne /annonces pour la V2)
    endpoints_to_try = [
        f"{BASE_URL}/annonces",
        f"{BASE_URL}/annonces/search",
        f"{BASE_URL}/search/annonces",
        f"{BASE_URL}/biens",
    ]

    for endpoint in endpoints_to_try:
        try:
            resp = requests.get(endpoint, headers=headers, params=params, timeout=20)

            if resp.status_code == 404:
                continue  # essaie le prochain endpoint

            if resp.status_code == 401:
                return [], f"Clé API Fluximmo invalide ou expirée (HTTP 401)."

            if resp.status_code == 403:
                return [], f"Accès refusé (HTTP 403) — vérifiez vos droits ou votre quota."

            if resp.status_code == 429:
                return [], f"Quota API Fluximmo dépassé (HTTP 429). Réessayez plus tard."

            if resp.status_code >= 500:
                error_msg = f"Erreur serveur Fluximmo (HTTP {resp.status_code})."
                continue

            if resp.status_code == 200:
                try:
                    data = resp.json()
                except Exception:
                    error_msg = f"Réponse non-JSON de {endpoint}."
                    continue

                # Cherche la liste d'annonces dans la réponse
                raw_list = _extract_list(data)
                if raw_list is None:
                    error_msg = (
                        f"Format de réponse inattendu depuis {endpoint}. "
                        f"Clés reçues : {list(data.keys()) if isinstance(data, dict) else type(data).__name__}"
                    )
                    continue

                for raw in raw_list:
                    try:
                        listings.append(_normalize_listing(raw))
                    except Exception as e:
                        logger.warning("Erreur normalisation annonce Fluximmo : %s", e)

                logger.info(
                    "Fluximmo : %d annonces récupérées depuis %s",
                    len(listings), endpoint
                )
                return listings, None  # succès

            error_msg = f"HTTP {resp.status_code} depuis {endpoint}: {resp.text[:200]}"

        except requests.exceptions.ConnectionError:
            return [], (
                "Impossible de contacter api.fluximmo.io — vérifiez votre connexion internet. "
                "Si vous utilisez un proxy ou un VPN, désactivez-le temporairement."
            )
        except requests.exceptions.Timeout:
            error_msg = f"Timeout lors de l'appel à {endpoint}."
            continue
        except Exception as e:
            error_msg = f"Erreur inattendue ({type(e).__name__}): {e}"
            continue

    return listings, error_msg or "Aucun endpoint Fluximmo n'a répondu correctement."


def _extract_list(data) -> Optional[List[dict]]:
    """Extrait la liste d'annonces depuis la réponse API (formats variés)."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "annonces", "results", "items", "listings", "biens", "records"):
            if key in data and isinstance(data[key], list):
                return data[key]
        # Réponse avec pagination : {"total": N, "page": 1, "data": [...]}
        for v in data.values():
            if isinstance(v, list) and v:
                return v
    return None
