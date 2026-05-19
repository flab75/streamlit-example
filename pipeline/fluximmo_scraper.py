"""
Scraper Fluximmo — API officielle d'annonces immobilières françaises.
Documentation : https://doc.fluximmo.io/
Auth : header  x-api-key: <clé>
"""

import hashlib
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Candidats base URL × version ──────────────────────────────────────────────
_BASE_CANDIDATES = [
    "https://api.fluximmo.io/v2",
    "https://api.fluximmo.io/v1",
    "https://api.fluximmo.io",
    "https://api.fluximmo.com/v2",
    "https://api.fluximmo.com",
]

# ── Candidats chemins endpoint annonces ───────────────────────────────────────
# Ordre : du plus probable au moins probable
_ENDPOINT_CANDIDATES = [
    # Patterns classiques API immobilière FR
    "/search",
    "/search/adverts",
    "/search/annonces",
    "/ads",
    "/ads/search",
    "/adverts",
    "/adverts/search",
    "/annonces",
    "/annonces/search",
    # Patterns REST générique
    "/listings",
    "/listings/search",
    "/real-estate-ads",
    "/real-estate-ads/search",
    "/biens",
    "/properties",
    "/properties/search",
    "/flux",
    # Racine versionnée
    "",
]

# ── Noms de clés d'API alternatives ───────────────────────────────────────────
_API_KEY_HEADERS = ["x-api-key", "Authorization", "X-API-KEY", "api-key"]

# ── Mapping champs réponse → format interne ───────────────────────────────────
_FIELD_ALIASES = {
    "prix": "price", "price": "price", "prix_vente": "price", "loyer": "price",
    "surface": "surface_m2", "surface_habitable": "surface_m2", "surface_m2": "surface_m2",
    "terrain": "terrain_m2", "surface_terrain": "terrain_m2", "terrain_m2": "terrain_m2",
    "ville": "ville", "city": "ville",
    "departement": "departement", "dept": "departement", "department": "departement",
    "code_postal": "code_postal", "cp": "code_postal", "zip": "code_postal",
    "postal_code": "code_postal",
    "titre": "title", "title": "title", "libelle": "title", "name": "title",
    "description": "description", "texte": "description", "text": "description",
    "url": "url", "lien": "url", "link": "url", "url_annonce": "url",
    "source": "source", "portail": "source", "origine": "source", "portal": "source",
    "date_publication": "pub_date", "date": "pub_date", "created_at": "pub_date",
    "published_at": "pub_date", "publication_date": "pub_date",
    "id": "api_id", "_id": "api_id", "reference": "api_id", "id_annonce": "api_id",
    "type_bien": "type_bien", "type": "type_bien", "categorie": "type_bien",
    "property_type": "type_bien", "holdings": "type_bien",
    "nb_pieces": "nb_pieces", "pieces": "nb_pieces", "rooms": "nb_pieces",
    "nb_rooms": "nb_pieces",
    "latitude": "lat", "lat": "lat",
    "longitude": "lng", "lng": "lng", "lon": "lng",
}


def _normalize_listing(raw: dict) -> dict:
    out: dict = {}
    for k, v in raw.items():
        target = _FIELD_ALIASES.get(k.lower())
        out[target if target else k] = v

    parts = []
    if out.get("ville"):
        parts.append(str(out["ville"]))
    if out.get("departement"):
        parts.append(str(out["departement"]))
    if out.get("code_postal"):
        parts.append(str(out["code_postal"]))
    location = " - ".join(parts) or raw.get("location", "")

    def _int(v, default=0):
        try:
            return int(str(v).replace(" ", "").replace("\xa0", "").replace(",", ""))
        except Exception:
            return default

    price = _int(out.get("price", 0))
    surface = _int(out.get("surface_m2")) or None
    terrain = _int(out.get("terrain_m2")) or None

    api_id = str(out.get("api_id", ""))
    url = str(out.get("url", "") or "")
    uid = hashlib.md5((api_id or url or str(raw)).encode()).hexdigest()[:8]

    return {
        "id": f"fluximmo-{api_id or uid}",
        "source": str(out.get("source", "fluximmo")),
        "title": str(out.get("title", "")),
        "price": price,
        "surface_m2": surface,
        "terrain_m2": terrain,
        "description": str(out.get("description", ""))[:800],
        "location": location,
        "url": url,
        "is_mock": False,
        "date_scraped": datetime.now().isoformat(),
        "pub_date": str(out.get("pub_date", "")),
        "type_bien": str(out.get("type_bien", "")),
        "nb_pieces": out.get("nb_pieces"),
    }


def _extract_list(data) -> Optional[List[dict]]:
    """Cherche la liste d'annonces dans n'importe quelle structure de réponse."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("adverts", "data", "annonces", "results", "items",
                    "listings", "biens", "records", "ads", "content"):
            if key in data and isinstance(data[key], list):
                return data[key]
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return None


def _build_params(criteria: dict) -> dict:
    params: dict = {}
    if criteria.get("prix_max"):
        params["prix_max"] = criteria["prix_max"]
        params["price_max"] = criteria["prix_max"]
    if criteria.get("prix_min"):
        params["prix_min"] = criteria["prix_min"]
        params["price_min"] = criteria["prix_min"]
    if criteria.get("surface_min"):
        params["surface_min"] = criteria["surface_min"]
    if criteria.get("terrain_min"):
        params["terrain_min"] = criteria["terrain_min"]

    dept = criteria.get("filtre_departement", "")
    if dept:
        try:
            from .geo_data import resolve_dept
            code, name = resolve_dept(dept)
            if code:
                params["departement"] = code
                params["department"] = code
        except Exception:
            params["departement"] = dept

    if criteria.get("filtre_ville"):
        params["ville"] = criteria["filtre_ville"]
        params["city"] = criteria["filtre_ville"]

    return params


# ── Fonction principale ────────────────────────────────────────────────────────

def scrape_fluximmo(
    api_key: str,
    criteria: dict,
) -> Tuple[List[Dict], Optional[str]]:
    """
    Interroge l'API Fluximmo.
    Retourne (listings, error_message).  error_message=None si succès.
    """
    try:
        import requests
    except ImportError:
        return [], "Module 'requests' manquant."

    params = _build_params(criteria)
    attempt_log: list[str] = []

    # Essai avec plusieurs combinaisons base × endpoint × header
    for base in _BASE_CANDIDATES:
        for endpoint in _ENDPOINT_CANDIDATES:
            url = base + endpoint
            for header_name in _API_KEY_HEADERS:
                headers = {
                    header_name: api_key,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                }
                # Essai GET
                try:
                    resp = requests.get(url, headers=headers, params=params, timeout=12)
                    log_entry = f"GET {url} → HTTP {resp.status_code}"
                    attempt_log.append(log_entry)

                    if resp.status_code == 401:
                        return [], (
                            f"Clé API invalide ou expirée (HTTP 401).\n"
                            f"Clé utilisée : {api_key[:20]}…\n"
                            f"URL testée : {url}\n"
                            f"Réponse : {resp.text[:300]}"
                        )
                    if resp.status_code == 403:
                        attempt_log[-1] += " [FORBIDDEN]"
                        continue
                    if resp.status_code == 429:
                        return [], "Quota API Fluximmo dépassé (HTTP 429). Réessayez plus tard."
                    if resp.status_code == 404:
                        continue
                    if resp.status_code >= 500:
                        attempt_log[-1] += f" [{resp.text[:80]}]"
                        continue

                    # Détecter le code d'erreur 10003 = "route inconnue" (Express)
                    try:
                        err_data = resp.json()
                        err_code = err_data.get("error", {}).get("code") if isinstance(err_data, dict) else None
                        if err_code == 10003:
                            attempt_log[-1] += " [route inexistante]"
                            continue  # ce chemin n'existe pas, essayer le suivant
                        # Toute autre erreur JSON : le chemin existe mais params/auth wrong
                        if err_code and err_code != 0:
                            attempt_log[-1] += f" [erreur API code={err_code}: {err_data.get('error', {}).get('message', '')}]"
                    except Exception:
                        pass

                    if resp.status_code == 200:
                        try:
                            data = resp.json()
                        except Exception:
                            attempt_log[-1] += " [non-JSON]"
                            continue

                        raw_list = _extract_list(data)
                        if raw_list is None:
                            attempt_log[-1] += f" [clés: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}]"
                            continue

                        listings = []
                        for raw in raw_list:
                            try:
                                listings.append(_normalize_listing(raw))
                            except Exception as e:
                                logger.debug("Erreur normalisation : %s", e)

                        logger.info("Fluximmo OK : %d annonces — %s", len(listings), url)
                        return listings, None  # ✅ succès

                except requests.exceptions.ConnectionError as e:
                    attempt_log.append(f"GET {url} → ConnectionError: {e}")
                    break  # inutile de réessayer ce base avec d'autres endpoints
                except requests.exceptions.Timeout:
                    attempt_log.append(f"GET {url} → Timeout")
                    continue
                except Exception as e:
                    attempt_log.append(f"GET {url} → {type(e).__name__}: {e}")
                    continue

                # Essai POST sur les endpoints de recherche
                if "search" in endpoint:
                    try:
                        body = {
                            "holdings": ["CLASS_HOUSE"],
                            "transaction_type": "sell",
                            **{k: v for k, v in params.items()
                               if k in ("prix_max", "prix_min", "surface_min",
                                        "departement", "ville")},
                        }
                        resp2 = requests.post(url, headers=headers, json=body, timeout=12)
                        attempt_log.append(f"POST {url} → HTTP {resp2.status_code}")
                        if resp2.status_code == 200:
                            try:
                                data = resp2.json()
                                raw_list = _extract_list(data)
                                if raw_list is not None:
                                    listings = [_normalize_listing(r) for r in raw_list]
                                    return listings, None
                            except Exception:
                                pass
                    except Exception as e:
                        attempt_log.append(f"POST {url} → {type(e).__name__}: {e}")

                break  # ne pas réessayer avec d'autres header_names si GET 200/non-json

    summary = "\n".join(attempt_log[-20:])  # 20 dernières tentatives
    return [], (
        f"Aucun endpoint Fluximmo n'a fonctionné.\n\n"
        f"Tentatives :\n{summary}\n\n"
        f"→ Lancez le diagnostic depuis l'onglet Configuration pour voir les détails complets."
    )


# ── Diagnostic ────────────────────────────────────────────────────────────────

def diagnose_api(api_key: str) -> list[dict]:
    """
    Teste toutes les combinaisons base × endpoint et retourne un rapport détaillé.
    Identifie les routes qui existent (≠ 10003) même si elles retournent une erreur.
    """
    try:
        import requests
    except ImportError:
        return [{"url": "N/A", "status": "ERREUR", "detail": "Module requests manquant"}]

    report = []
    h = {"x-api-key": api_key, "Accept": "application/json"}

    def _probe(url, method="GET", body=None):
        try:
            if method == "POST":
                r = requests.post(url, headers={**h, "Content-Type": "application/json"},
                                  json=body or {}, timeout=8)
            else:
                r = requests.get(url, headers=h, params={"limit": 1, "page": 1}, timeout=8)
            raw = r.text[:600]
            rtype = f"{method}"
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

    # ── 1. Racines (pour voir le message d'accueil ou les routes disponibles) ──
    for root in ["https://api.fluximmo.io/v2", "https://api.fluximmo.io",
                 "https://api.fluximmo.com/v2", "https://api.fluximmo.com"]:
        report.append(_probe(root))

    # ── 2. OpenAPI / Swagger discovery ────────────────────────────────────────
    for spec_url in [
        "https://api.fluximmo.io/v2/openapi.json",
        "https://api.fluximmo.io/openapi.json",
        "https://api.fluximmo.io/v2/swagger.json",
        "https://api.fluximmo.io/v2/docs",
        "https://api.fluximmo.com/openapi.json",
    ]:
        report.append(_probe(spec_url))

    # ── 3. GET sur toutes combinaisons base × endpoint ────────────────────────
    for base in _BASE_CANDIDATES:
        for endpoint in _ENDPOINT_CANDIDATES:
            report.append(_probe(base + endpoint))

    # ── 4. POST sur les endpoints /search (body JSON Fluximmo connu) ──────────
    search_body = {
        "holdings": ["CLASS_HOUSE"],
        "transaction_type": "sell",
        "limit": 2,
    }
    for base in ["https://api.fluximmo.io/v2", "https://api.fluximmo.io"]:
        for ep in ["/search", "/adverts/search", "/ads/search",
                   "/annonces/search", "/listings/search"]:
            report.append(_probe(base + ep, method="POST", body=search_body))

    # Déduplique les URL identiques (garde le premier résultat)
    seen_urls: set = set()
    deduped = []
    for r in report:
        if r["url"] not in seen_urls:
            seen_urls.add(r["url"])
            deduped.append(r)

    return deduped
