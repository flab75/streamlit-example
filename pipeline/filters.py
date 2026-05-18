from typing import Dict, List


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

    def apply(self, listings: List[Dict]) -> List[Dict]:
        return [l for l in listings if self._passes(l)]

    def _passes(self, listing: dict) -> bool:
        if self.sources and listing.get("source") not in self.sources:
            return False

        price = listing.get("price", 0)
        # price=0 signifie "non extrait" — on ne filtre pas sur les prix inconnus
        if price > 0:
            if self.prix_min and price < self.prix_min:
                return False
            if self.prix_max and price > self.prix_max:
                return False

        surface = listing.get("surface_m2")
        # surface=None signifie "non extraite" — pas de filtrage sur valeur inconnue
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

        return True

    def _has_water(self, listing: dict) -> bool:
        text = f"{listing.get('title', '')} {listing.get('description', '')}".lower()
        return any(kw in text for kw in self.WATER_KEYWORDS)

    def _is_countryside(self, listing: dict) -> bool:
        text = f"{listing.get('title', '')} {listing.get('description', '')}".lower()
        return any(kw in text for kw in self.COUNTRYSIDE_KEYWORDS)
