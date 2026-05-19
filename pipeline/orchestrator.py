import asyncio
import json
from pathlib import Path
from typing import List

from .scraper import run_scrapers
from .filters import PropertyFilter
from .dvf_enricher import enrich_listing
from .ville_enricher import fetch_ville_data
from .storage import ListingStorage, GoogleSheetsStorage
from .notifier import notify_all
from .fluximmo_scraper import scrape_fluximmo

DATA_DIR = Path(__file__).parent.parent / "data"


class PipelineConfig:
    def __init__(self):
        self.sources: List[str] = ["pap", "seloger", "proprietes-rurales"]
        self.prix_min: int = 0
        self.prix_max: int = 0
        self.surface_min: int = 0
        self.terrain_min: int = 0
        self.filtrer_eau: bool = False
        self.filtrer_campagne: bool = False
        self.mots_cles_requis: List[str] = []
        self.mots_cles_exclus: List[str] = []
        self.filtre_region: str = ""
        self.filtre_departement: str = ""
        self.filtre_ville: str = ""
        self.fluximmo_api_key: str = ""
        self.enrichir_dvf: bool = True
        self.enrichir_ville: bool = True
        self.slack_webhook: str = ""
        self.smtp_host: str = ""
        self.smtp_port: int = 587
        self.smtp_user: str = ""
        self.smtp_password: str = ""
        self.email_destinataire: str = ""
        self.google_sheets_id: str = ""
        self.google_credentials_file: str = ""
        self.ville_recherche: str = "France"  # conservé pour compatibilité


async def run_pipeline(config: PipelineConfig) -> dict:
    ville = (
        getattr(config, "filtre_ville", "")
        or getattr(config, "filtre_departement", "")
        or getattr(config, "ville_recherche", "France")
        or "France"
    )
    criteria = {
        "ville": ville,
        "prix_max": config.prix_max,
        "surface_min": config.surface_min,
        "filtre_departement": getattr(config, "filtre_departement", ""),
        "filtre_ville": getattr(config, "filtre_ville", ""),
        "filtre_region": getattr(config, "filtre_region", ""),
    }
    # ── Fluximmo (priorité maximale si clé configurée) ─────────────────────
    fluximmo_error: str | None = None
    fluximmo_listings: list = []
    if getattr(config, "fluximmo_api_key", ""):
        fluximmo_listings, fluximmo_error = scrape_fluximmo(
            config.fluximmo_api_key, criteria
        )

    # ── Scrapers RSS/requests classiques ──────────────────────────────────
    all_listings = await run_scrapers(config.sources, criteria)

    # Fusion : Fluximmo en tête, sans doublons URL
    if fluximmo_listings:
        seen_urls = {l["url"] for l in fluximmo_listings if l.get("url")}
        deduped_classic = [l for l in all_listings if l.get("url") not in seen_urls]
        all_listings = fluximmo_listings + deduped_classic

    filter_config = dict(config.__dict__)
    if fluximmo_listings and filter_config.get("sources"):
        filter_config["sources"] = list(filter_config["sources"]) + ["fluximmo"]
    pf = PropertyFilter(filter_config)
    filtered = pf.apply(all_listings)

    # Diagnostic Fluximmo : combien passent le filtre
    fluximmo_after_filter = sum(1 for l in filtered if l.get("source") == "fluximmo")

    storage = ListingStorage(DATA_DIR)
    new_listings = storage.get_new_listings(filtered)

    sheets_storage = None
    if config.google_sheets_id and config.google_credentials_file:
        sheets_storage = GoogleSheetsStorage(config.google_credentials_file, config.google_sheets_id)
        if not sheets_storage.is_available():
            sheets_storage = None

    # Cache des données ville pour éviter les appels répétés
    ville_cache: dict = {}

    enriched = []
    notifications_sent = 0
    for listing in new_listings:
        if config.enrichir_dvf:
            listing = enrich_listing(listing)
        if config.enrichir_ville:
            ville = listing.get("location", "").split("-")[0].strip().split(",")[0].strip()
            if ville:
                if ville not in ville_cache:
                    ville_cache[ville] = await fetch_ville_data(ville)
                listing["ville_stats"] = ville_cache[ville]
        storage.save_listing(listing)
        storage.mark_seen(listing["id"])
        if sheets_storage:
            try:
                sheets_storage.append_listing(listing)
            except Exception:
                pass
        notify_all(listing, config.__dict__)
        notifications_sent += 1
        enriched.append(listing)

    return {
        "total_scraped": len(all_listings),
        "fluximmo_count": len(fluximmo_listings),
        "fluximmo_after_filter": fluximmo_after_filter,
        "fluximmo_error": fluximmo_error,
        "fluximmo_listings": fluximmo_listings,
        "after_filter": len(filtered),
        "new_listings": len(new_listings),
        "notifications_sent": notifications_sent,
        "listings": enriched,
    }


def run_pipeline_sync(config: PipelineConfig) -> dict:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(run_pipeline(config))
    finally:
        loop.close()


def load_config() -> PipelineConfig:
    config_file = DATA_DIR / "pipeline_config.json"
    config = PipelineConfig()
    if config_file.exists():
        try:
            with open(config_file, encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                if hasattr(config, k):
                    setattr(config, k, v)
        except (json.JSONDecodeError, OSError):
            pass
    return config


def save_config(config: PipelineConfig):
    DATA_DIR.mkdir(exist_ok=True)
    config_file = DATA_DIR / "pipeline_config.json"
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config.__dict__, f, indent=2, ensure_ascii=False)
