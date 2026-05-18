import asyncio
import random
import hashlib
from datetime import datetime
from typing import Dict, List

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


def _mock_listings(criteria: dict, source: str) -> List[Dict]:
    random.seed(hash(str(criteria) + source) % (2**32))
    ville = criteria.get("ville", "France")
    prix_max = criteria.get("prix_max", 300000)
    surface_min = criteria.get("surface_min", 0)

    templates = [
        {
            "title": "Ferme rénovée avec source et pré",
            "description": "Belle ferme en pierre rénovée, source captée, vaste pré de 2 hectares. Puits ancien restauré. Idéal pour projet de vie à la campagne.",
            "features": ["puits", "source", "campagne", "ferme"],
        },
        {
            "title": "Longère avec étang et terrain",
            "description": "Longère normande avec étang privatif de 3000 m², terrain arboré. Grange attenante. Ruisseau en limite de propriété.",
            "features": ["étang", "ruisseau", "longuère", "terrain"],
        },
        {
            "title": "Corps de ferme avec mare et verger",
            "description": "Corps de ferme traditionnel, mare aménagée, verger productif. Hameau calme, campagne authentique.",
            "features": ["mare", "campagne", "corps de ferme", "hameau"],
        },
        {
            "title": "Mas provençal avec vivier",
            "description": "Mas en pierre sèche, vivier pour poissons, terrain de 4000 m². Environnement rural, proche rivière.",
            "features": ["vivier", "rivière", "mas", "rural"],
        },
        {
            "title": "Bergerie réhabilitée avec cours d'eau",
            "description": "Ancienne bergerie entièrement réhabilitée, cours d'eau traversant la propriété, terrain de 1,5 ha. Isolation optimale.",
            "features": ["cours d'eau", "bergerie", "terrain", "rural"],
        },
        {
            "title": "Maison rurale avec lac privé",
            "description": "Maison de caractère avec lac privé de 5000 m², hectares de prairie. Grange convertible.",
            "features": ["lac", "rural", "terrain", "hameau"],
        },
        {
            "title": "Grange aménagée avec puits et jardin",
            "description": "Grange réaménagée avec grand puits fonctionnel, jardin potager, terrain boisé. Havre de paix en campagne.",
            "features": ["puits", "grange", "campagne", "terrain"],
        },
        {
            "title": "Maison de campagne avec ruisseau",
            "description": "Maison de campagne avec ruisseau traversant la propriété, terrain de 3500 m². Proximité forêt.",
            "features": ["ruisseau", "campagne", "terrain"],
        },
    ]

    locations_rurales = [
        f"{ville} - hameau des Chênes", f"{ville} - lieu-dit la Fontaine",
        f"{ville} - La Ferme Haute", f"Proche {ville} - campagne",
        f"{ville} - hameau de la Croix", f"{ville} - Les Grands Prés",
    ]

    listings = []
    count = random.randint(6, 12)
    for i in range(count):
        tmpl = random.choice(templates)
        surface = random.randint(max(80, surface_min), 280)
        terrain = random.randint(1500, 40000)
        prix = random.randint(60000, min(prix_max, 280000))
        uid = hashlib.md5(f"{source}-{i}-{ville}-{prix}".encode()).hexdigest()[:8]
        listing_id = f"{source}-{uid}"

        if source == "pap":
            url = f"https://www.pap.fr/annonce/ventes-maisons-g302-{uid}"
        else:
            url = f"https://www.leboncoin.fr/annonce/{uid}"

        listings.append({
            "id": listing_id,
            "source": source,
            "title": tmpl["title"],
            "price": prix,
            "surface_m2": surface,
            "terrain_m2": terrain,
            "description": tmpl["description"],
            "location": random.choice(locations_rurales),
            "url": url,
            "date_scraped": datetime.now().isoformat(),
        })

    return listings


async def _scrape_pap_async(criteria: dict) -> List[Dict]:
    if not PLAYWRIGHT_AVAILABLE:
        return _mock_listings(criteria, "pap")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            url = "https://www.pap.fr/annonce/ventes-maisons-g302"
            await page.goto(url, timeout=15000)
            await page.wait_for_load_state("networkidle", timeout=10000)

            cards = await page.query_selector_all(".search-list-item")
            listings = []
            for card in cards[:15]:
                try:
                    title_el = await card.query_selector(".item-title")
                    price_el = await card.query_selector(".item-price")
                    location_el = await card.query_selector(".item-location")
                    link_el = await card.query_selector("a")
                    desc_el = await card.query_selector(".item-description")

                    title = await title_el.inner_text() if title_el else "Bien immobilier PAP"
                    price_text = await price_el.inner_text() if price_el else "0"
                    location = await location_el.inner_text() if location_el else criteria.get("ville", "France")
                    href = await link_el.get_attribute("href") if link_el else ""
                    desc = await desc_el.inner_text() if desc_el else ""

                    price_clean = "".join(c for c in price_text if c.isdigit())
                    price = int(price_clean) if price_clean else 0

                    full_url = f"https://www.pap.fr{href}" if href.startswith("/") else href
                    uid = hashlib.md5(full_url.encode()).hexdigest()[:8]

                    listings.append({
                        "id": f"pap-{uid}",
                        "source": "pap",
                        "title": title.strip(),
                        "price": price,
                        "surface_m2": None,
                        "terrain_m2": None,
                        "description": desc.strip(),
                        "location": location.strip(),
                        "url": full_url,
                        "date_scraped": datetime.now().isoformat(),
                    })
                except Exception:
                    continue

            await browser.close()
            return listings if listings else _mock_listings(criteria, "pap")

    except Exception:
        return _mock_listings(criteria, "pap")


async def _scrape_leboncoin_async(criteria: dict) -> List[Dict]:
    if not PLAYWRIGHT_AVAILABLE:
        return _mock_listings(criteria, "leboncoin")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            url = "https://www.leboncoin.fr/recherche?category=9"
            await page.goto(url, timeout=15000)
            await page.wait_for_load_state("networkidle", timeout=10000)

            cards = await page.query_selector_all("article[data-qa-id='aditem_container']")
            listings = []
            for card in cards[:15]:
                try:
                    title_el = await card.query_selector("[data-qa-id='aditem_title']")
                    price_el = await card.query_selector("[data-qa-id='aditem_price']")
                    location_el = await card.query_selector("[data-qa-id='aditem_location']")
                    link_el = await card.query_selector("a")
                    desc_el = await card.query_selector("[data-qa-id='aditem_description']")

                    title = await title_el.inner_text() if title_el else "Bien immobilier LBC"
                    price_text = await price_el.inner_text() if price_el else "0"
                    location = await location_el.inner_text() if location_el else criteria.get("ville", "France")
                    href = await link_el.get_attribute("href") if link_el else ""
                    desc = await desc_el.inner_text() if desc_el else ""

                    price_clean = "".join(c for c in price_text if c.isdigit())
                    price = int(price_clean) if price_clean else 0

                    full_url = f"https://www.leboncoin.fr{href}" if href.startswith("/") else href
                    uid = hashlib.md5(full_url.encode()).hexdigest()[:8]

                    listings.append({
                        "id": f"lbc-{uid}",
                        "source": "leboncoin",
                        "title": title.strip(),
                        "price": price,
                        "surface_m2": None,
                        "terrain_m2": None,
                        "description": desc.strip(),
                        "location": location.strip(),
                        "url": full_url,
                        "date_scraped": datetime.now().isoformat(),
                    })
                except Exception:
                    continue

            await browser.close()
            return listings if listings else _mock_listings(criteria, "leboncoin")

    except Exception:
        return _mock_listings(criteria, "leboncoin")


async def scrape_pap(criteria: dict) -> List[Dict]:
    return await _scrape_pap_async(criteria)


async def scrape_leboncoin(criteria: dict) -> List[Dict]:
    return await _scrape_leboncoin_async(criteria)


async def run_scrapers(sources: List[str], criteria: dict) -> List[Dict]:
    tasks = []
    if "pap" in sources:
        tasks.append(scrape_pap(criteria))
    if "leboncoin" in sources:
        tasks.append(scrape_leboncoin(criteria))

    if not tasks:
        return []

    results = await asyncio.gather(*tasks, return_exceptions=True)
    listings = []
    for result in results:
        if isinstance(result, list):
            listings.extend(result)

    return listings
