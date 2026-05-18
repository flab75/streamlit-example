import streamlit as st
import anthropic
import json
import os
import pandas as pd
from datetime import datetime
from pathlib import Path
import random

st.set_page_config(
    page_title="Agent Immobilier IA",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
PROSPECTS_FILE = DATA_DIR / "prospects.json"


def load_prospects():
    if PROSPECTS_FILE.exists():
        with open(PROSPECTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_prospects_to_file(prospects):
    with open(PROSPECTS_FILE, "w", encoding="utf-8") as f:
        json.dump(prospects, f, indent=2, ensure_ascii=False)


# ── Tool implementations ──────────────────────────────────────────────────────

PRIX_M2_REF = {
    "paris": 10200, "lyon": 4950, "marseille": 3800, "bordeaux": 5200,
    "toulouse": 4300, "nice": 5000, "nantes": 4600, "strasbourg": 4200,
    "montpellier": 4400, "rennes": 4700, "lille": 3600, "grenoble": 3900,
}


def search_properties(
    ville: str,
    type_bien: str = "tous",
    prix_min: int = None,
    prix_max: int = None,
    surface_min: int = None,
):
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


def save_prospect(
    nom: str,
    email: str,
    budget: int,
    type_bien: str,
    ville: str,
    telephone: str = "",
    notes: str = "",
):
    prospects = load_prospects()
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
    save_prospects_to_file(prospects)
    return {"success": True, "id": p["id"], "message": f"Prospect '{nom}' enregistré (ID: {p['id']})"}


def list_prospects_tool(statut: str = None):
    prospects = load_prospects()
    if statut:
        prospects = [p for p in prospects if p.get("statut") == statut]
    return {"total": len(prospects), "prospects": prospects}


def analyze_market(ville: str):
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


# ── Tools schema ──────────────────────────────────────────────────────────────

TOOLS_SCHEMA = [
    {
        "name": "search_properties",
        "description": (
            "Recherche des transactions immobilières récentes (données DVF) "
            "dans une ville française. Retourne des biens avec prix, surface et date."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ville": {"type": "string", "description": "Ville (ex: Lyon, Paris, Nantes)"},
                "type_bien": {
                    "type": "string",
                    "enum": ["appartement", "maison", "tous"],
                    "description": "Type de bien immobilier",
                },
                "prix_min": {"type": "integer", "description": "Prix minimum en €"},
                "prix_max": {"type": "integer", "description": "Prix maximum en €"},
                "surface_min": {"type": "integer", "description": "Surface minimum en m²"},
            },
            "required": ["ville"],
        },
    },
    {
        "name": "save_prospect",
        "description": "Enregistre un nouveau prospect acheteur dans la base CRM.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nom": {"type": "string", "description": "Nom complet du prospect"},
                "email": {"type": "string", "description": "Adresse email"},
                "budget": {"type": "integer", "description": "Budget maximum en €"},
                "type_bien": {"type": "string", "description": "Type de bien recherché"},
                "ville": {"type": "string", "description": "Ville ou zone souhaitée"},
                "telephone": {"type": "string", "description": "Numéro de téléphone"},
                "notes": {"type": "string", "description": "Notes et critères supplémentaires"},
            },
            "required": ["nom", "email", "budget", "type_bien", "ville"],
        },
    },
    {
        "name": "list_prospects_tool",
        "description": "Affiche la liste des prospects enregistrés dans le CRM.",
        "input_schema": {
            "type": "object",
            "properties": {
                "statut": {
                    "type": "string",
                    "enum": ["nouveau", "contacté", "qualifié", "signé"],
                    "description": "Filtrer par statut (optionnel)",
                }
            },
        },
    },
    {
        "name": "analyze_market",
        "description": (
            "Analyse le marché immobilier d'une ville : prix au m², "
            "tendances, tension du marché et délai de vente moyen."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ville": {"type": "string", "description": "Ville à analyser"}
            },
            "required": ["ville"],
        },
    },
]

SYSTEM_PROMPT = """Tu es un assistant expert en prospection immobilière pour les agents immobiliers français.

Tes missions :
- Analyser le marché immobilier par zone géographique
- Rechercher des biens correspondant aux critères des prospects
- Gérer la base de données des prospects (CRM)
- Conseiller sur les stratégies de prospection

Règles :
- Réponds toujours en français, de façon professionnelle et concise
- Utilise les outils pour toute recherche ou action CRM
- Quand tu enregistres un prospect, confirme les informations sauvegardées
- Quand tu analyses un marché, donne des recommandations actionnables
- Structure tes réponses avec des puces ou tableaux quand c'est pertinent"""


# ── Agent loop ────────────────────────────────────────────────────────────────


def blocks_to_params(blocks):
    result = []
    for b in blocks:
        if b.type == "text":
            result.append({"type": "text", "text": b.text})
        elif b.type == "tool_use":
            result.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
    return result


def dispatch_tool(name, tool_input):
    try:
        if name == "search_properties":
            out = search_properties(**tool_input)
        elif name == "save_prospect":
            out = save_prospect(**tool_input)
        elif name == "list_prospects_tool":
            out = list_prospects_tool(**tool_input)
        elif name == "analyze_market":
            out = analyze_market(**tool_input)
        else:
            out = {"error": f"Outil inconnu: {name}"}
        return json.dumps(out, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def run_agent_turn(client, user_message, history):
    messages = history + [{"role": "user", "content": user_message}]
    tool_events = []

    while True:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS_SCHEMA,
            messages=messages,
        )

        text_response = " ".join(b.text for b in resp.content if b.type == "text")

        if resp.stop_reason == "end_turn":
            messages.append({"role": "assistant", "content": blocks_to_params(resp.content)})
            return text_response, tool_events, messages

        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": blocks_to_params(resp.content)})
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    result_str = dispatch_tool(block.name, block.input)
                    tool_events.append(
                        {
                            "tool": block.name,
                            "input": block.input,
                            "output": json.loads(result_str),
                        }
                    )
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": result_str}
                    )
            messages.append({"role": "user", "content": tool_results})
        else:
            return text_response, tool_events, messages


# ── UI ────────────────────────────────────────────────────────────────────────


def render_tool_events(tool_events):
    for event in tool_events:
        with st.expander(f"🔧 Outil `{event['tool']}`"):
            col1, col2 = st.columns(2)
            with col1:
                st.caption("Paramètres")
                st.json(event["input"])
            with col2:
                st.caption("Résultat")
                st.json(event["output"])


def main():
    st.title("🏠 Agent de Prospection Immobilière")

    # ── Sidebar ──
    with st.sidebar:
        st.header("⚙️ Configuration")
        api_key = st.text_input(
            "Clé API Anthropic",
            type="password",
            value=os.environ.get("ANTHROPIC_API_KEY", ""),
            help="Obtenez votre clé sur console.anthropic.com",
        )
        if not api_key:
            st.warning("Clé API requise pour utiliser l'agent")

        st.divider()
        st.header("👥 Prospects")
        prospects = load_prospects()
        if prospects:
            df = pd.DataFrame(
                [
                    {
                        "Nom": p["nom"],
                        "Ville": p["ville"],
                        "Budget": f"{p['budget']:,} €",
                        "Statut": p["statut"],
                    }
                    for p in prospects
                ]
            )
            st.dataframe(df, use_container_width=True, hide_index=True)
            csv_data = pd.DataFrame(prospects).to_csv(index=False, encoding="utf-8")
            st.download_button(
                "📥 Exporter CSV",
                csv_data,
                "prospects.csv",
                "text/csv",
                use_container_width=True,
            )
        else:
            st.info("Aucun prospect enregistré")

        st.divider()
        if st.button("🗑️ Nouvelle conversation", use_container_width=True):
            st.session_state.history = []
            st.session_state.display = []
            st.rerun()

    # ── Session state ──
    if "history" not in st.session_state:
        st.session_state.history = []
    if "display" not in st.session_state:
        st.session_state.display = []

    # ── Chat display ──
    if not st.session_state.display:
        with st.chat_message("assistant"):
            st.markdown(
                """
**Bonjour ! Je suis votre agent de prospection immobilière.**

Je peux vous aider à :
- 🔍 Rechercher des biens par ville et critères (prix, surface, type)
- 📊 Analyser le marché local (prix m², tendances, délais de vente)
- 👥 Enregistrer et consulter vos prospects dans le CRM

*Exemples :*
> "Analyse le marché à Lyon"
> "Cherche des appartements à Nantes entre 200k et 350k€"
> "Enregistre : Jean Dupont, jean@mail.com, budget 400k, maison, Bordeaux"
> "Liste mes prospects"
            """
            )

    for msg in st.session_state.display:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("tools"):
                render_tool_events(msg["tools"])

    # ── Chat input ──
    if prompt := st.chat_input("Votre question immobilière..."):
        if not api_key:
            st.error("Veuillez entrer votre clé API Anthropic dans la barre latérale.")
            return

        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Analyse en cours..."):
                client = anthropic.Anthropic(api_key=api_key)
                response_text, tool_events, new_history = run_agent_turn(
                    client, prompt, st.session_state.history
                )
            st.markdown(response_text)
            if tool_events:
                render_tool_events(tool_events)

        st.session_state.history = new_history
        st.session_state.display.append({"role": "user", "content": prompt})
        st.session_state.display.append(
            {"role": "assistant", "content": response_text, "tools": tool_events}
        )

        if any(e["tool"] == "save_prospect" for e in tool_events):
            st.rerun()


if __name__ == "__main__":
    main()
