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

DATA_DIR = Path(__file__).parent.parent / "data"


class PipelineConfig:
    def __init__(self):
        self.sources: List[str] = ["pap", "seloger"]
        self.prix_min: int = 0
        self.prix_max: int = 300000
        self.surface_min: int = 80
        self.terrain_min: int = 0
        self.filtrer_eau: bool = False
        self.filtrer_campagne: bool = False
        self.mots_cles_requis: List[str] = []
        self.mots_cles_exclus: List[str] = []
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
        self.ville_recherche: str = "France"


async def run_pipeline(config: PipelineConfig) -> dict:
    criteria = {
        "ville": config.ville_recherche,
        "prix_max": config.prix_max,
        "surface_min": config.surface_min,
    }
    all_listings = await run_scrapers(config.sources, criteria)

    pf = PropertyFilter(config.__dict__)
    filtered = pf.apply(all_listings)

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
