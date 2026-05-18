"""
Serveur MCP (Model Context Protocol) pour l'agent de prospection immobilière.
Expose les mêmes outils que l'application Streamlit, utilisables dans Claude Desktop.

Lancement :
    python mcp_server.py

Ou via uvx :
    uvx --from . mcp-server-immo
"""

from mcp.server.fastmcp import FastMCP
import json
import random
from datetime import datetime
from pathlib import Path

mcp = FastMCP("agent-immobilier")

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
PROSPECTS_FILE = DATA_DIR / "prospects.json"

PRIX_M2_REF = {
    "paris": 10200, "lyon": 4950, "marseille": 3800, "bordeaux": 5200,
    "toulouse": 4300, "nice": 5000, "nantes": 4600, "strasbourg": 4200,
    "montpellier": 4400, "rennes": 4700, "lille": 3600, "grenoble": 3900,
}


def _load_prospects():
    if PROSPECTS_FILE.exists():
        with open(PROSPECTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_prospects(prospects):
    with open(PROSPECTS_FILE, "w", encoding="utf-8") as f:
        json.dump(prospects, f, indent=2, ensure_ascii=False)


@mcp.tool()
def search_properties(
    ville: str,
    type_bien: str = "tous",
    prix_min: int = None,
    prix_max: int = None,
    surface_min: int = None,
) -> dict:
    """
    Recherche des transactions immobilières récentes (DVF) dans une ville française.

    Args:
        ville: Ville cible (ex: Lyon, Paris, Nantes)
        type_bien: "appartement", "maison" ou "tous"
        prix_min: Prix minimum en euros
        prix_max: Prix maximum en euros
        surface_min: Surface minimum en m²
    """
    prix_m2_base = PRIX_M2_REF.get(ville.lower(), random.randint(2000, 5000))
    types = ["appartement", "maison"] if type_bien == "tous" else [type_bien]
    results = []

    for _ in range(random.randint(5, 12)):
        t = random.choice(types)
        surface = (
            random.randint(25, 120) if t == "appartement" else random.randint(80, 220)
        )
        if surface_min and surface < surface_min:
            continue
        prix = int(surface * prix_m2_base * random.uniform(0.85, 1.15))
        if prix_min and prix < prix_min:
            continue
        if prix_max and prix > prix_max:
            continue
        results.append(
            {
                "ref": f"DVF-{random.randint(10000, 99999)}",
                "type": t,
                "ville": ville,
                "surface_m2": surface,
                "prix": prix,
                "prix_m2": round(prix / surface),
                "nb_pieces": (
                    random.randint(1, 5) if t == "appartement" else random.randint(3, 7)
                ),
                "date_transaction": (
                    f"2024-{random.randint(1,12):02d}-{random.randint(1,28):02d}"
                ),
            }
        )

    return {
        "ville": ville,
        "type_bien": type_bien,
        "nb_resultats": len(results),
        "biens": results,
        "source": "DVF Etalab (simulé — connecter l'API réelle en production)",
    }


@mcp.tool()
def save_prospect(
    nom: str,
    email: str,
    budget: int,
    type_bien: str,
    ville: str,
    telephone: str = "",
    notes: str = "",
) -> dict:
    """
    Enregistre un nouveau prospect acheteur dans la base CRM locale.

    Args:
        nom: Nom complet du prospect
        email: Adresse email
        budget: Budget maximum en euros
        type_bien: Type de bien recherché (appartement, maison…)
        ville: Ville ou zone souhaitée
        telephone: Numéro de téléphone (optionnel)
        notes: Notes et critères supplémentaires
    """
    prospects = _load_prospects()
    p = {
        "id": f"P{len(prospects)+1:04d}",
        "nom": nom,
        "email": email,
        "telephone": telephone,
        "budget": budget,
        "type_bien": type_bien,
        "ville": ville,
        "notes": notes,
        "statut": "nouveau",
        "date_creation": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    prospects.append(p)
    _save_prospects(prospects)
    return {"success": True, "id": p["id"], "message": f"Prospect '{nom}' enregistré (ID: {p['id']})"}


@mcp.tool()
def list_prospects(statut: str = None) -> dict:
    """
    Affiche la liste des prospects enregistrés dans le CRM.

    Args:
        statut: Filtrer par statut — "nouveau", "contacté", "qualifié", "signé"
    """
    prospects = _load_prospects()
    if statut:
        prospects = [p for p in prospects if p.get("statut") == statut]
    return {"total": len(prospects), "prospects": prospects}


@mcp.tool()
def analyze_market(ville: str) -> dict:
    """
    Analyse le marché immobilier d'une ville française.
    Retourne les prix au m², tendances, tension du marché et délai de vente.

    Args:
        ville: Ville à analyser
    """
    market_data = {
        "paris": {"min": 7000, "max": 14000, "median": 10200, "evolution": "+2.1%", "tension": "très forte"},
        "lyon": {"min": 3500, "max": 6800, "median": 4950, "evolution": "+1.5%", "tension": "forte"},
        "marseille": {"min": 2200, "max": 6000, "median": 3800, "evolution": "+0.8%", "tension": "modérée"},
        "bordeaux": {"min": 3500, "max": 7200, "median": 5200, "evolution": "-0.5%", "tension": "modérée"},
        "toulouse": {"min": 3000, "max": 5800, "median": 4300, "evolution": "+3.2%", "tension": "forte"},
        "nice": {"min": 3500, "max": 8000, "median": 5000, "evolution": "+1.2%", "tension": "forte"},
        "nantes": {"min": 3000, "max": 6500, "median": 4600, "evolution": "+2.8%", "tension": "forte"},
        "rennes": {"min": 3200, "max": 6200, "median": 4700, "evolution": "+1.9%", "tension": "forte"},
        "lille": {"min": 2500, "max": 5000, "median": 3600, "evolution": "+0.5%", "tension": "modérée"},
        "strasbourg": {"min": 2800, "max": 5500, "median": 4200, "evolution": "+1.1%", "tension": "modérée"},
    }
    d = market_data.get(
        ville.lower(),
        {
            "min": random.randint(1500, 3000),
            "max": random.randint(4000, 7000),
            "median": random.randint(2500, 5000),
            "evolution": f"{random.uniform(-2, 4):.1f}%",
            "tension": random.choice(["faible", "modérée", "forte"]),
        },
    )
    return {
        "ville": ville,
        "prix_m2": d,
        "delai_vente_moyen": f"{random.randint(30, 100)} jours",
        "nb_ventes_annuelles_estimees": random.randint(500, 8000),
        "recommandation": (
            "Marché vendeur — bonne période pour vendre"
            if "forte" in d["tension"]
            else "Marché équilibré — négociation possible"
        ),
    }


if __name__ == "__main__":
    mcp.run()
