import re
import unicodedata
from typing import Dict, List

from .geo_data import DEPARTEMENTS, DEPT_NAME_TO_CODE, dept_codes_for_region, resolve_dept


def _normalize(s: str) -> str:
    return unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()


class PropertyFilter:
    WATER_KEYWORDS = [
        "eau", "puits", "source", "ruisseau", "rivière", "étang",
        "mare", "lac", "vivier", "cours d'eau",
    ]
    COUNTRYSIDE_KEYWORDS = [
        "campagne", "rural", "hameau", "ferme", "grange", "bergerie",
        "longuère", "mas", "corps de ferme", "terrain", "hectare",
    ]

    def __init__(self, config: dict):
        self.prix_min = config.get("prix_min", 0)
        self.prix_max = config.get("prix_max", 0)
        self.surface_min = config.get("surface_min", 0)
        self.terrain_min = config.get("terrain_min", 0)
        self.mots_cles_requis = [k.strip().lower() for k in config.get("mots_cles_requis", []) if k.strip()]
        self.mots_cles_exclus = [k.strip().lower() for k in config.get("mots_cles_exclus", []) if k.strip()]
        self.filtrer_eau = config.get("filtrer_eau", False)
        self.filtrer_campagne = config.get("filtrer_campagne", False)
        self.sources = config.get("sources", [])

        # Localisation
        self.filtre_region = (config.get("filtre_region") or "").strip()
        self.filtre_departement = (config.get("filtre_departement") or "").strip()
        self.filtre_ville = (config.get("filtre_ville") or "").strip()

        # Pré-calcul : codes de départements candidats pour le filtrage
        self._dept_codes_region: list[str] = (
            dept_codes_for_region(self.filtre_region) if self.filtre_region else []
        )
        dept_code, dept_name = resolve_dept(self.filtre_departement) if self.filtre_departement else (None, None)
        self._dept_code: str | None = dept_code
        self._dept_name: str | None = dept_name

    # ── Méthode principale ────────────────────────────────────────────────────

    def apply(self, listings: List[Dict]) -> List[Dict]:
        return [l for l in listings if self._passes(l)]

    def _passes(self, listing: dict) -> bool:
        if self.sources and listing.get("source") not in self.sources:
            return False

        price = listing.get("price", 0)
        if price > 0:
            if self.prix_min and price < self.prix_min:
                return False
            if self.prix_max and price > self.prix_max:
                return False

        surface = listing.get("surface_m2")
        if surface is not None and surface > 0:
            if self.surface_min and surface < self.surface_min:
                return False

        terrain = listing.get("terrain_m2")
        if terrain is not None and terrain > 0:
            if self.terrain_min and terrain < self.terrain_min:
                return False

        text = f"{listing.get('title', '')} {listing.get('description', '')}".lower()

        for kw in self.mots_cles_requis:
            if kw not in text:
                return False
        for kw in self.mots_cles_exclus:
            if kw in text:
                return False

        if self.filtrer_eau and not self._has_water(listing):
            return False
        if self.filtrer_campagne and not self._is_countryside(listing):
            return False

        if not self._matches_location(listing):
            return False

        return True

    # ── Localisation ──────────────────────────────────────────────────────────

    def _location_text(self, listing: dict) -> str:
        """Texte complet de localisation : location + titre + description."""
        return " ".join([
            listing.get("location", ""),
            listing.get("title", ""),
            listing.get("description", ""),
        ]).lower()

    def _matches_location(self, listing: dict) -> bool:
        """
        Retourne True si l'annonce correspond aux filtres de localisation.
        Logique : chaque filtre actif doit être satisfait (AND).
        Un filtre non renseigné est ignoré.
        """
        if not self.filtre_region and not self.filtre_departement and not self.filtre_ville:
            return True  # Aucun filtre géographique

        loc = self._location_text(listing)

        # Filtre ville — le plus précis, testé en premier
        if self.filtre_ville:
            if _normalize(self.filtre_ville) not in _normalize(loc):
                return False

        # Filtre département
        if self.filtre_departement:
            if not self._dept_matches(loc, listing.get("location", "")):
                return False

        # Filtre région (vérifié uniquement si département non renseigné pour éviter double contrainte)
        if self.filtre_region and not self.filtre_departement:
            if not self._region_matches(loc, listing.get("location", "")):
                return False

        return True

    def _dept_matches(self, loc_lower: str, raw_location: str) -> bool:
        """Vérifie si la localisation correspond au département filtré."""
        if not self._dept_code:
            return False

        # 1. Nom du département dans le texte
        if self._dept_name and _normalize(self._dept_name) in _normalize(loc_lower):
            return True

        # 2. Code postal commençant par le code département (ex: 24xxx pour Dordogne)
        code = self._dept_code.lstrip("0") or "0"
        if re.search(rf'\b{re.escape(self._dept_code)}\d{{3}}\b', raw_location):
            return True
        # Code sur 2 chiffres sans zéro initial
        if code != self._dept_code and re.search(rf'\b{re.escape(code)}\d{{4}}\b', raw_location):
            return True

        # 3. Code département brut dans le texte (ex: "(24)" ou "24 -")
        if re.search(rf'\b{re.escape(self._dept_code)}\b', raw_location):
            return True

        return False

    def _region_matches(self, loc_lower: str, raw_location: str) -> bool:
        """Vérifie si la localisation correspond à la région filtrée."""
        # 1. Nom de la région dans le texte
        if _normalize(self.filtre_region) in _normalize(loc_lower):
            return True

        # 2. Un code postal correspondant à un département de la région
        for dept_code in self._dept_codes_region:
            dept_name = DEPARTEMENTS.get(dept_code, "")
            if dept_name and _normalize(dept_name) in _normalize(loc_lower):
                return True
            if re.search(rf'\b{re.escape(dept_code)}\d{{3}}\b', raw_location):
                return True

        return False

    # ── Mots-clés ─────────────────────────────────────────────────────────────

    def _has_water(self, listing: dict) -> bool:
        text = f"{listing.get('title', '')} {listing.get('description', '')}".lower()
        return any(kw in text for kw in self.WATER_KEYWORDS)

    def _is_countryside(self, listing: dict) -> bool:
        text = f"{listing.get('title', '')} {listing.get('description', '')}".lower()
        return any(kw in text for kw in self.COUNTRYSIDE_KEYWORDS)

    # ── Résumé des filtres actifs (pour l'UI) ─────────────────────────────────

    def active_filters_summary(self) -> list[str]:
        items = []
        if self.filtre_region:
            items.append(f"Région : {self.filtre_region}")
        if self.filtre_departement:
            label = f"{self._dept_name} ({self._dept_code})" if self._dept_name else self.filtre_departement
            items.append(f"Département : {label}")
        if self.filtre_ville:
            items.append(f"Ville / commune : {self.filtre_ville}")
        if self.prix_min:
            items.append(f"Prix min : {self.prix_min:,} €")
        if self.prix_max:
            items.append(f"Prix max : {self.prix_max:,} €")
        if self.surface_min:
            items.append(f"Surface ≥ {self.surface_min} m²")
        if self.terrain_min:
            items.append(f"Terrain ≥ {self.terrain_min:,} m²")
        if self.filtrer_eau:
            items.append("Eau requise (puits / source / étang…)")
        if self.filtrer_campagne:
            items.append("Campagne requise (ferme / hameau…)")
        if self.mots_cles_requis:
            items.append(f"Mots requis : {', '.join(self.mots_cles_requis)}")
        if self.mots_cles_exclus:
            items.append(f"Mots exclus : {', '.join(self.mots_cles_exclus)}")
        return items
