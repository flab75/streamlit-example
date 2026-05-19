import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False

SHEETS_COLUMNS = ["Date", "Source", "Titre", "Prix", "Surface", "Terrain", "Lieu", "URL", "Prix/m² DVF", "Estimation", "Score"]


class ListingStorage:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.listings_file = self.data_dir / "listings.json"
        self.seen_ids_file = self.data_dir / "seen_ids.json"

    def load_listings(self) -> List[Dict]:
        if not self.listings_file.exists():
            return []
        try:
            with open(self.listings_file, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

    def save_listing(self, listing: dict):
        listings = self.load_listings()
        existing_ids = {l.get("id") for l in listings}
        if listing.get("id") not in existing_ids:
            listings.append(listing)
        else:
            listings = [listing if l.get("id") == listing.get("id") else l for l in listings]
        with open(self.listings_file, "w", encoding="utf-8") as f:
            json.dump(listings, f, indent=2, ensure_ascii=False)

    def _load_seen_ids(self) -> set:
        if not self.seen_ids_file.exists():
            return set()
        try:
            with open(self.seen_ids_file, encoding="utf-8") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, OSError):
            return set()

    def _save_seen_ids(self, seen: set):
        with open(self.seen_ids_file, "w", encoding="utf-8") as f:
            json.dump(list(seen), f)

    def is_seen(self, listing_id: str) -> bool:
        return listing_id in self._load_seen_ids()

    def mark_seen(self, listing_id: str):
        seen = self._load_seen_ids()
        seen.add(listing_id)
        self._save_seen_ids(seen)

    def get_new_listings(self, listings: List[Dict]) -> List[Dict]:
        seen = self._load_seen_ids()
        return [l for l in listings if l.get("id") not in seen]


class GoogleSheetsStorage:
    def __init__(self, credentials_file: str, spreadsheet_id: str):
        self.credentials_file = credentials_file
        self.spreadsheet_id = spreadsheet_id
        self._client = None
        self._sheet = None

    def _get_sheet(self):
        if self._sheet is not None:
            return self._sheet
        if not GSPREAD_AVAILABLE:
            raise RuntimeError("gspread not installed")
        scopes = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(self.credentials_file, scopes=scopes)
        self._client = gspread.authorize(creds)
        spreadsheet = self._client.open_by_key(self.spreadsheet_id)
        self._sheet = spreadsheet.sheet1
        headers = self._sheet.row_values(1)
        if not headers:
            self._sheet.append_row(SHEETS_COLUMNS)
        return self._sheet

    def append_listing(self, listing: dict):
        sheet = self._get_sheet()
        dvf = listing.get("dvf_stats", {})
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            listing.get("source", ""),
            listing.get("title", ""),
            listing.get("price", ""),
            listing.get("surface_m2", ""),
            listing.get("terrain_m2", ""),
            listing.get("location", ""),
            listing.get("url", ""),
            dvf.get("prix_m2_median", ""),
            dvf.get("estimation_prix", ""),
            dvf.get("analyse", ""),
        ]
        sheet.append_row(row)

    def is_available(self) -> bool:
        if not GSPREAD_AVAILABLE:
            return False
        if not self.credentials_file or not self.spreadsheet_id:
            return False
        try:
            creds_path = Path(self.credentials_file)
            return creds_path.exists()
        except Exception:
            return False
