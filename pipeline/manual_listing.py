"""
Extraction d'informations depuis un texte d'annonce collé manuellement.
Génère aussi des liens de recherche pour retrouver l'annonce en ligne.
"""

import hashlib
import re
from datetime import datetime
from typing import Optional
from urllib.parse import quote_plus


def extract_from_text(text: str) -> dict:
    """
    Extrait les champs structurés d'un texte d'annonce brut.
    Retourne un dict compatible avec le format interne des listings.
    """
    t = text.strip()

    title = _extract_title(t)
    price = _extract_price(t)
    surface = _extract_surface(t)
    terrain = _extract_terrain(t)
    location = _extract_location(t)
    nb_pieces = _extract_nb_pieces(t)
    url = _extract_url(t)

    uid = hashlib.md5(t.encode()).hexdigest()[:8]

    return {
        "id": f"manual-{uid}",
        "source": "manuel",
        "title": title or "Annonce saisie manuellement",
        "price": price or 0,
        "surface_m2": surface,
        "terrain_m2": terrain,
        "nb_pieces": nb_pieces,
        "description": t[:1000],
        "location": location or "",
        "url": url or "",
        "is_mock": False,
        "is_manual": True,
        "date_scraped": datetime.now().isoformat(),
        "search_links": build_search_links(title, price, surface, location, t),
    }


# ── Extracteurs ───────────────────────────────────────────────────────────────

def _extract_title(text: str) -> Optional[str]:
    """Prend la première ligne non vide comme titre."""
    for line in text.splitlines():
        line = line.strip()
        if line and len(line) > 5:
            return line[:150]
    return None


def _extract_price(text: str) -> Optional[int]:
    text = text.replace("\xa0", " ").replace(" ", " ").replace(" ", " ")
    patterns = [
        r"([\d][\d\s]{2,9})\s*€",
        r"Prix\s*:?\s*([\d][\d\s]{2,9})\s*(?:€|EUR|euros?)",
        r"([\d][\d\s]{2,9})\s*(?:€|EUR|euros?)",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            val = int(re.sub(r"\s", "", m.group(1)))
            if 10_000 <= val <= 20_000_000:
                return val
    return None


def _extract_surface(text: str) -> Optional[int]:
    patterns = [
        r"surface\s+(?:habitable\s*)?:?\s*(\d+)\s*m[²2]",
        r"(\d+)\s*m[²2]\s+(?:habitables?|shab)",
        r"(\d{2,4})\s*m[²2](?!\s*de\s+terrain)",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            val = int(m.group(1))
            if 10 <= val <= 5000:
                return val
    return None


def _extract_terrain(text: str) -> Optional[int]:
    patterns = [
        r"terrain\s*:?\s*(\d[\d\s]*)\s*m[²2]",
        r"(\d[\d\s]*)\s*m[²2]\s+de\s+terrain",
        r"terrain\s+de\s+(\d[\d\s]*)\s*m[²2]",
        r"(\d+(?:[.,]\d+)?)\s*h(?:a|ectare)",
        r"(\d[\d\s]*)\s*m[²2]\s*(?:\(terrain\)|\[terrain\])",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            raw = m.group(1).replace(" ", "").replace(",", ".")
            if "ha" in p or "ectare" in p:
                return int(float(raw) * 10_000)
            return int(re.sub(r"\s", "", raw))
    return None


def _extract_location(text: str) -> Optional[str]:
    # Code postal français (5 chiffres) suivi ou précédé d'une ville
    m = re.search(
        r"([A-ZÀ-Ÿa-zà-ÿ\s\-]{3,30})\s*[\(\[–-]?\s*(\d{5})\s*[\)\]]?",
        text, re.UNICODE
    )
    if m:
        return f"{m.group(1).strip()} ({m.group(2)})"

    m = re.search(r"(\d{5})\s*[-–]?\s*([A-ZÀ-Ÿa-zà-ÿ\s\-]{3,30})", text, re.UNICODE)
    if m:
        return f"{m.group(2).strip()} ({m.group(1)})"

    # "à/près de/commune de <Ville>"
    m = re.search(
        r"(?:à|commune\s+de|près\s+de|secteur|proche)\s+([A-ZÀ-Ÿa-zà-ÿ\-]{3,30})",
        text, re.I | re.UNICODE
    )
    if m:
        return m.group(1).strip().title()

    # Departement entre parenthèses
    m = re.search(r"\((\d{2})\)", text)
    if m:
        return f"Dpt {m.group(1)}"

    return None


def _extract_nb_pieces(text: str) -> Optional[int]:
    m = re.search(r"(\d)\s*pièces?", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d)\s*p(?:\.|\b)", text)
    if m and 1 <= int(m.group(1)) <= 20:
        return int(m.group(1))
    return None


def _extract_url(text: str) -> Optional[str]:
    m = re.search(r"https?://\S+", text)
    return m.group(0).rstrip(".,;)") if m else None


# ── Liens de recherche ────────────────────────────────────────────────────────

def build_search_links(
    title: Optional[str],
    price: Optional[int],
    surface: Optional[int],
    location: Optional[str],
    full_text: str,
) -> dict:
    """
    Génère des liens permettant de retrouver l'annonce en ligne.
    Retourne un dict { "label": "url", ... }
    """
    # Construit un fragment de recherche pertinent
    parts = []
    if title:
        # 4-5 premiers mots du titre (plus discriminants)
        words = title.split()[:5]
        parts.append(" ".join(words))
    if location:
        loc_clean = re.sub(r"\(.*?\)", "", location).strip()
        parts.append(loc_clean)
    if price:
        parts.append(f"{price:,}".replace(",", " ") + " €")

    query_full = " ".join(parts)
    query_title_only = " ".join(title.split()[:6]) if title else query_full

    # Code postal / département extrait de la localisation
    cp_match = re.search(r"\b(\d{5})\b", location or "")
    cp = cp_match.group(1) if cp_match else ""
    dept2 = cp[:2] if cp else ""

    links: dict = {}

    # 1. Google
    links["Google"] = (
        f"https://www.google.com/search?q={quote_plus(query_full + ' site:pap.fr OR site:seloger.com OR site:leboncoin.fr OR site:proprietes-rurales.com')}"
    )

    # 2. PAP.fr
    pap_params = {"recherche": query_title_only}
    links["PAP.fr"] = (
        f"https://www.pap.fr/annonce/ventes-maisons-g302?recherche={quote_plus(query_title_only)}"
        + (f"&cp={cp}" if cp else "")
    )

    # 3. SeLoger
    links["SeLoger"] = (
        "https://www.seloger.com/list.htm?projects=2&types=2"
        + (f"&places=[{{cp:{cp}}}]" if cp else "")
        + (f"&price=0/{price}" if price else "")
        + (f"&surface={surface or 0}/0" if surface else "")
    )

    # 4. LeBonCoin
    links["LeBonCoin"] = (
        f"https://www.leboncoin.fr/recherche?category=9&text={quote_plus(query_title_only)}"
        + (f"&locations={quote_plus(location.split('(')[0].strip())}" if location else "")
    )

    # 5. Propriétés Rurales
    links["Propriétés Rurales"] = (
        f"https://www.proprietes-rurales.com/catalogue/vente/?recherche={quote_plus(query_title_only)}"
        + (f"&departement={dept2}" if dept2 else "")
    )

    # 6. Bien'ici (aggrégateur)
    links["Bien'ici"] = (
        f"https://www.bienici.com/recherche/vente/france/maison"
        + (f"?prix_max={price}" if price else "")
        + (f"&surface_min={surface}" if surface else "")
    )

    return links
