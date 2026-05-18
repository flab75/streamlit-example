import asyncio
import hashlib
import random
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urlencode

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


# ── Données de démonstration (fallback final) ─────────────────────────────────


def _mock_listings(criteria: dict, source: str) -> List[Dict]:
    random.seed(hash(str(criteria) + source) % (2 ** 32))
    ville = criteria.get("ville", "France")
    prix_max = criteria.get("prix_max", 300000)
    surface_min = criteria.get("surface_min", 0)

    templates = [
        {"title": "Ferme rénovée avec source et pré",
         "description": "Belle ferme en pierre rénovée, source captée, vaste pré de 2 hectares. Puits ancien restauré. Idéal pour projet de vie à la campagne."},
        {"title": "Longère avec étang et terrain",
         "description": "Longère normande avec étang privatif de 3000 m², terrain arboré. Grange attenante. Ruisseau en limite de propriété."},
        {"title": "Corps de ferme avec mare et verger",
         "description": "Corps de ferme traditionnel, mare aménagée, verger productif. Hameau calme, campagne authentique."},
        {"title": "Mas provençal avec vivier",
         "description": "Mas en pierre sèche, vivier pour poissons, terrain de 4000 m². Environnement rural, proche rivière."},
        {"title": "Bergerie réhabilitée avec cours d'eau",
         "description": "Ancienne bergerie entièrement réhabilitée, cours d'eau traversant la propriété, terrain de 1,5 ha."},
        {"title": "Maison rurale avec lac privé",
         "description": "Maison de caractère avec lac privé de 5000 m², hectares de prairie. Grange convertible."},
        {"title": "Grange aménagée avec puits et jardin",
         "description": "Grange réaménagée avec grand puits fonctionnel, jardin potager, terrain boisé. Havre de paix en campagne."},
        {"title": "Maison de campagne avec ruisseau",
         "description": "Maison de campagne avec ruisseau traversant la propriété, terrain de 3500 m². Proximité forêt."},
    ]
    locations = [
        f"{ville} - hameau des Chênes", f"{ville} - lieu-dit la Fontaine",
        f"{ville} - La Ferme Haute", f"Proche {ville} - campagne",
        f"{ville} - hameau de la Croix", f"{ville} - Les Grands Prés",
    ]

    listings = []
    for _ in range(random.randint(6, 12)):
        tmpl = random.choice(templates)
        surface = random.randint(max(80, surface_min), 280)
        terrain = random.randint(1500, 40000)
        prix = random.randint(60000, min(prix_max, 280000))
        uid = hashlib.md5(f"{source}-{_}-{ville}-{prix}".encode()).hexdigest()[:8]
        listings.append({
            "id": f"{source}-{uid}",
            "source": source,
            "title": tmpl["title"],
            "price": prix,
            "surface_m2": surface,
            "terrain_m2": terrain,
            "description": tmpl["description"],
            "location": random.choice(locations),
            "url": "",
            "is_mock": True,
            "date_scraped": datetime.now().isoformat(),
        })
    return listings


# ── PAP.fr — flux RSS (méthode principale, aucune anti-bot) ───────────────────


def _parse_price_from_text(text: str) -> int:
    """Extrait un prix numérique depuis un texte libre."""
    text = text.replace("\xa0", " ").replace(" ", " ")
    m = re.search(r"([\d][\d\s]{2,8})\s*€", text)
    if m:
        return int(re.sub(r"\s", "", m.group(1)))
    return 0


def _parse_surface_from_text(text: str) -> Optional[int]:
    m = re.search(r"(\d+)\s*m[²2]", text)
    return int(m.group(1)) if m else None


def _parse_terrain_from_text(text: str) -> Optional[int]:
    # "terrain de X m²" ou "Xha" ou "X hectares"
    m = re.search(r"terrain[^0-9]*(\d+[\s\d]*)\s*m[²2]", text, re.I)
    if m:
        return int(re.sub(r"\s", "", m.group(1)))
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*h(?:a|ectare)", text, re.I)
    if m:
        return int(float(m.group(1).replace(",", ".")) * 10000)
    return None


def scrape_pap_rss(criteria: dict) -> List[Dict]:
    """
    Scrape PAP.fr via le flux RSS public.
    Retourne des annonces RÉELLES avec leurs URLs cliquables.
    Aucune protection anti-bot sur les flux RSS.
    """
    if not REQUESTS_AVAILABLE:
        return []

    prix_max = criteria.get("prix_max", 0)
    surface_min = criteria.get("surface_min", 0)

    # PAP.fr expose ses recherches en XML/RSS
    base_url = "https://www.pap.fr/annonce/ventes-maisons-g302.xml"
    params: dict = {}
    if prix_max:
        params["prix-max"] = prix_max
    if surface_min:
        params["surface-min"] = surface_min

    url = base_url + ("?" + urlencode(params) if params else "")
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; FeedFetcher/1.0)",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        channel = root.find("channel")
        items = channel.findall("item") if channel is not None else root.findall(".//item")

        listings = []
        for item in items:
            try:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                desc_html = item.findtext("description") or ""
                pub_date = item.findtext("pubDate") or ""

                if not link or not title:
                    continue

                # Nettoyer HTML de la description
                desc_text = re.sub(r"<[^>]+>", " ", desc_html)
                desc_text = re.sub(r"\s+", " ", desc_text).strip()

                price = _parse_price_from_text(desc_text) or _parse_price_from_text(title)
                surface = _parse_surface_from_text(desc_text)
                terrain = _parse_terrain_from_text(desc_text)

                # Localisation : PAP inclut souvent la ville dans le titre
                location_match = re.search(r"(?:pièces?\s+|[–-]\s*)([A-ZÀ-Ÿa-zà-ÿ\s\-]+?)(?:\s*\(|\s*$)", title)
                location = location_match.group(1).strip() if location_match else ""

                uid = hashlib.md5(link.encode()).hexdigest()[:8]
                listings.append({
                    "id": f"pap-{uid}",
                    "source": "pap",
                    "title": title,
                    "price": price,
                    "surface_m2": surface,
                    "terrain_m2": terrain,
                    "description": desc_text[:500],
                    "location": location,
                    "url": link,         # URL réelle de l'annonce PAP
                    "is_mock": False,
                    "date_scraped": datetime.now().isoformat(),
                    "pub_date": pub_date,
                })
            except Exception:
                continue

        return listings

    except Exception:
        return []


# ── SeLoger — flux RSS (alternative LeBonCoin) ────────────────────────────────


def scrape_seloger_rss(criteria: dict) -> List[Dict]:
    """
    SeLoger expose un flux RSS pour les recherches de maisons.
    URLs réelles, accessible sans anti-bot.
    """
    if not REQUESTS_AVAILABLE:
        return []

    prix_max = criteria.get("prix_max", 0)
    surface_min = criteria.get("surface_min", 0)

    # SeLoger : recherche maisons à vendre, toute France
    params = {
        "projects": "2",       # vente
        "types": "2",          # maison
        "natures": "1,2,4",
    }
    if prix_max:
        params["prix_max"] = prix_max
    if surface_min:
        params["surface_min"] = surface_min

    url = "https://www.seloger.com/list.xml?" + urlencode(params)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; FeedFetcher/1.0)",
        "Accept": "application/rss+xml, application/xml, */*",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        items = root.findall(".//item")

        listings = []
        for item in items:
            try:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                desc_html = item.findtext("description") or ""

                if not link or not title:
                    continue

                desc_text = re.sub(r"<[^>]+>", " ", desc_html)
                desc_text = re.sub(r"\s+", " ", desc_text).strip()

                price = _parse_price_from_text(desc_text) or _parse_price_from_text(title)
                surface = _parse_surface_from_text(desc_text)
                terrain = _parse_terrain_from_text(desc_text)

                uid = hashlib.md5(link.encode()).hexdigest()[:8]
                listings.append({
                    "id": f"seloger-{uid}",
                    "source": "seloger",
                    "title": title,
                    "price": price,
                    "surface_m2": surface,
                    "terrain_m2": terrain,
                    "description": desc_text[:500],
                    "location": "",
                    "url": link,
                    "is_mock": False,
                    "date_scraped": datetime.now().isoformat(),
                })
            except Exception:
                continue

        return listings

    except Exception:
        return []


# ── LeBonCoin — requests + BeautifulSoup (sans Playwright) ───────────────────


def scrape_leboncoin_requests(criteria: dict) -> List[Dict]:
    """
    Tente de scraper LeBonCoin via requests (sans navigateur headless).
    LeBonCoin n'a pas de flux RSS public — cette méthode peut être bloquée
    selon les protections actives.
    """
    if not REQUESTS_AVAILABLE:
        return []

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    prix_max = criteria.get("prix_max", 0)
    ville = criteria.get("ville", "")

    params = {"category": "9", "real_estate_type": "2,1"}
    if prix_max:
        params["price"] = f"0-{prix_max}"
    if ville:
        params["locations"] = ville

    url = "https://www.leboncoin.fr/recherche?" + urlencode(params)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Referer": "https://www.leboncoin.fr/",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        listings = []

        for ad in soup.select("article, [data-qa-id='aditem_container']")[:20]:
            try:
                link_el = ad.select_one("a[href*='/ad/'], a[href*='/annonce/']")
                if not link_el:
                    continue
                href = link_el.get("href", "")
                full_url = f"https://www.leboncoin.fr{href}" if href.startswith("/") else href
                if not re.search(r"/\d{8,}", full_url):
                    continue

                title_el = ad.select_one("[data-qa-id='aditem_title'], h2, h3")
                price_el = ad.select_one("[data-qa-id='aditem_price'], [class*='price']")
                location_el = ad.select_one("[data-qa-id='aditem_location'], [class*='location']")

                title = title_el.get_text(strip=True) if title_el else "Bien immobilier"
                price_text = price_el.get_text(strip=True) if price_el else ""
                location = location_el.get_text(strip=True) if location_el else ""
                price = _parse_price_from_text(price_text)

                uid = hashlib.md5(full_url.encode()).hexdigest()[:8]
                listings.append({
                    "id": f"lbc-{uid}",
                    "source": "leboncoin",
                    "title": title,
                    "price": price,
                    "surface_m2": None,
                    "terrain_m2": None,
                    "description": "",
                    "location": location,
                    "url": full_url,
                    "is_mock": False,
                    "date_scraped": datetime.now().isoformat(),
                })
            except Exception:
                continue

        return listings

    except Exception:
        return []


# ── Coordinateur des scrapers ─────────────────────────────────────────────────


async def run_scrapers(sources: List[str], criteria: dict) -> List[Dict]:
    """
    Lance tous les scrapers configurés.
    Ordre de priorité pour chaque source :
      PAP    → RSS (fiable) → Playwright → mock
      LeBonCoin → requests → Playwright → mock
      SeLoger → RSS (fiable) → mock
    """
    all_listings: List[Dict] = []

    if "pap" in sources:
        listings = scrape_pap_rss(criteria)
        if listings:
            all_listings.extend(listings)
        else:
            # Playwright en fallback
            listings = await _scrape_pap_playwright(criteria)
            all_listings.extend(listings if listings else _mock_listings(criteria, "pap"))

    if "leboncoin" in sources:
        listings = scrape_leboncoin_requests(criteria)
        if listings:
            all_listings.extend(listings)
        else:
            listings = await _scrape_leboncoin_playwright(criteria)
            all_listings.extend(listings if listings else _mock_listings(criteria, "leboncoin"))

    if "seloger" in sources:
        listings = scrape_seloger_rss(criteria)
        all_listings.extend(listings if listings else _mock_listings(criteria, "seloger"))

    return all_listings


# ── Playwright (fallback) ─────────────────────────────────────────────────────


def _is_real_listing_url_pap(url: str) -> bool:
    return bool(url and re.search(r"-\d{5,}/?$", url))


async def _scrape_pap_playwright(criteria: dict) -> List[Dict]:
    if not PLAYWRIGHT_AVAILABLE:
        return []
    search_url = "https://www.pap.fr/annonce/ventes-maisons-g302"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="fr-FR",
            )
            page = await context.new_page()
            await page.goto(search_url, timeout=20000)
            await page.wait_for_load_state("domcontentloaded", timeout=15000)

            cards = []
            for sel in [".search-list-item", ".result-item", "article.item", "[data-id]"]:
                cards = await page.query_selector_all(sel)
                if cards:
                    break

            listings = []
            seen: set = set()
            for card in cards[:20]:
                try:
                    link_el = await card.query_selector("a[href*='/annonce/vente']") or await card.query_selector("a[href]")
                    href = await link_el.get_attribute("href") if link_el else ""
                    full_url = f"https://www.pap.fr{href}" if href.startswith("/") else href
                    if not _is_real_listing_url_pap(full_url) or full_url in seen:
                        continue
                    seen.add(full_url)

                    title_el = await card.query_selector(".item-title, h2, h3, [class*='title']")
                    price_el = await card.query_selector(".item-price, [class*='price'], [class*='prix']")
                    location_el = await card.query_selector(".item-location, [class*='location']")

                    title = (await title_el.inner_text()).strip() if title_el else "Bien PAP"
                    price_text = (await price_el.inner_text()).strip() if price_el else ""
                    location = (await location_el.inner_text()).strip() if location_el else ""

                    uid = hashlib.md5(full_url.encode()).hexdigest()[:8]
                    listings.append({
                        "id": f"pap-{uid}", "source": "pap", "title": title,
                        "price": _parse_price_from_text(price_text), "surface_m2": None,
                        "terrain_m2": None, "description": "", "location": location,
                        "url": full_url, "is_mock": False,
                        "date_scraped": datetime.now().isoformat(),
                    })
                except Exception:
                    continue
            await browser.close()
            return listings
    except Exception:
        return []


async def _scrape_leboncoin_playwright(criteria: dict) -> List[Dict]:
    if not PLAYWRIGHT_AVAILABLE:
        return []
    search_url = "https://www.leboncoin.fr/recherche?category=9"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="fr-FR",
            )
            page = await context.new_page()
            await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            await page.goto(search_url, timeout=20000)
            await page.wait_for_load_state("domcontentloaded", timeout=15000)

            cards = await page.query_selector_all("article[data-qa-id='aditem_container'], [data-test-id='ad'], article")
            listings = []
            seen: set = set()
            for card in cards[:20]:
                try:
                    link_el = await card.query_selector("a[href*='/ad/'], a[href*='/annonce/'], a[href]")
                    href = await link_el.get_attribute("href") if link_el else ""
                    full_url = f"https://www.leboncoin.fr{href}" if href.startswith("/") else href
                    if not re.search(r"/\d{8,}", full_url) or full_url in seen:
                        continue
                    seen.add(full_url)

                    title_el = await card.query_selector("[data-qa-id='aditem_title'], h2, h3")
                    price_el = await card.query_selector("[data-qa-id='aditem_price'], [class*='price']")
                    location_el = await card.query_selector("[data-qa-id='aditem_location']")

                    title = (await title_el.inner_text()).strip() if title_el else "Bien LBC"
                    price_text = (await price_el.inner_text()).strip() if price_el else ""
                    location = (await location_el.inner_text()).strip() if location_el else ""

                    uid = hashlib.md5(full_url.encode()).hexdigest()[:8]
                    listings.append({
                        "id": f"lbc-{uid}", "source": "leboncoin", "title": title,
                        "price": _parse_price_from_text(price_text), "surface_m2": None,
                        "terrain_m2": None, "description": "", "location": location,
                        "url": full_url, "is_mock": False,
                        "date_scraped": datetime.now().isoformat(),
                    })
                except Exception:
                    continue
            await browser.close()
            return listings
    except Exception:
        return []
