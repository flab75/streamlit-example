import anthropic
import json
import os
import pandas as pd
import streamlit as st
from datetime import datetime
from pathlib import Path
import random

from pipeline.orchestrator import (
    PipelineConfig,
    load_config,
    run_pipeline_sync,
    save_config,
)
from pipeline.storage import ListingStorage
from pipeline.filters import PropertyFilter
from pipeline.ville_enricher import get_ville_info_sync, ville_url
from pipeline.geo_data import REGIONS
from pipeline.manual_listing import extract_from_text
from pipeline.fluximmo_scraper import diagnose_api as fluximmo_diagnose

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
        try:
            with open(PROSPECTS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
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
    {
        "name": "get_ville_info",
        "description": (
            "Récupère les scores de qualité de vie d'une ville française depuis villesavivre.fr : "
            "éducation, santé, transport, nature, sécurité, culture, économie. "
            "Utile pour comparer des villes ou conseiller un prospect sur un lieu de vie."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ville": {"type": "string", "description": "Nom de la ville française"}
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
        elif name == "get_ville_info":
            out = get_ville_info_sync(**tool_input)
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


def render_tool_events(tool_events):
    for event in tool_events:
        with st.expander(f"Outil `{event['tool']}`"):
            col1, col2 = st.columns(2)
            with col1:
                st.caption("Paramètres")
                st.json(event["input"])
            with col2:
                st.caption("Résultat")
                st.json(event["output"])


# ── Tab 1 : Agent ─────────────────────────────────────────────────────────────


def render_agent_tab(api_key: str):
    if "history" not in st.session_state:
        st.session_state.history = []
    if "display" not in st.session_state:
        st.session_state.display = []

    if not st.session_state.display:
        with st.chat_message("assistant"):
            st.markdown(
                """
**Bonjour ! Je suis votre agent de prospection immobilière.**

Je peux vous aider à :
- Rechercher des biens par ville et critères (prix, surface, type)
- Analyser le marché local (prix m², tendances, délais de vente)
- Consulter les scores de qualité de vie d'une ville (villesavivre.fr)
- Enregistrer et consulter vos prospects dans le CRM

*Exemples :*
> "Analyse le marché à Lyon"
> "Cherche des appartements à Nantes entre 200k et 350k€"
> "Enregistre : Jean Dupont, jean@mail.com, budget 400k, maison, Bordeaux"
> "Liste mes prospects"
> "Qualité de vie à Nantes ?"
> "Compare Bordeaux et Toulouse pour s'installer"
            """
            )

    for msg in st.session_state.display:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("tools"):
                render_tool_events(msg["tools"])

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


# ── Affichage scores ville ────────────────────────────────────────────────────


def _render_ville_scores(ville_stats: dict):
    """Affiche les scores villesavivre.fr sous forme de barres de progression."""
    source = ville_stats.get("source", "villesavivre.fr")
    url = ville_stats.get("url", "")
    note = ville_stats.get("note", "")
    scores = ville_stats.get("scores", {})
    score_global = ville_stats.get("score_global")

    title = f"**Qualité de vie — {ville_stats.get('ville', '')}**"
    if url:
        title = f"**[Qualité de vie — {ville_stats.get('ville', '')}]({url})**"
    st.markdown(title)

    if score_global:
        color = "#2ecc71" if score_global >= 7 else "#f39c12" if score_global >= 5 else "#e74c3c"
        st.markdown(
            f"<span style='font-size:1.3em;font-weight:bold;color:{color}'>"
            f"Score global : {score_global} / 10</span>",
            unsafe_allow_html=True,
        )

    if scores:
        cols = st.columns(min(4, len(scores)))
        for i, (label, score) in enumerate(scores.items()):
            with cols[i % len(cols)]:
                color = "#2ecc71" if score >= 7 else "#f39c12" if score >= 5 else "#e74c3c"
                short = label.split("&")[0].split("(")[0].strip()
                st.markdown(
                    f"<small>{short}</small><br>"
                    f"<span style='color:{color};font-weight:bold'>{score}/10</span>",
                    unsafe_allow_html=True,
                )
                st.progress(score / 10)

    infos = ville_stats.get("infos", {})
    if infos:
        parts = []
        if infos.get("population"):
            parts.append(f"Pop. {int(infos['population']):,}".replace(",", " "))
        if infos.get("taux_chomage"):
            parts.append(f"Chômage {infos['taux_chomage']}")
        if infos.get("espaces_verts_pct"):
            parts.append(f"Espaces verts {infos['espaces_verts_pct']}")
        if parts:
            st.caption(" · ".join(parts))

    caption = f"Source : {source}"
    if note:
        caption += f" — {note}"
    st.caption(caption)


# ── Tab 2 : Pipeline ──────────────────────────────────────────────────────────


def render_pipeline_tab():
    st.header("Pipeline de surveillance immobilière")

    config = load_config()


    # ── Résumé des filtres actifs ──────────────────────────────────────────────
    pf_summary = PropertyFilter(config.__dict__)
    active_filters = pf_summary.active_filters_summary()

    with st.expander("🔎 Filtres actifs", expanded=bool(active_filters)):
        if active_filters:
            for f in active_filters:
                st.write(f"• {f}")
        else:
            st.write("Aucun filtre actif — toutes les annonces passent.")
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("⚙️ Modifier les filtres"):
                st.info("Allez dans l'onglet **⚙️ Configuration** pour modifier les critères.")
        with col_b:
            if st.button("🔄 Réinitialiser aux valeurs par défaut"):
                cfg_file = DATA_DIR / "pipeline_config.json"
                if cfg_file.exists():
                    cfg_file.unlink()
                st.success("Configuration réinitialisée — tous les filtres sont désactivés.")
                st.rerun()

    st.subheader("Lancer une analyse")
    if st.button("▶ Analyser maintenant", type="primary"):
        with st.spinner("Scraping et analyse en cours..."):
            try:
                result = run_pipeline_sync(config)
                st.session_state["last_pipeline_result"] = result
                st.session_state["last_pipeline_time"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                if result.get("fluximmo_listings"):
                    st.session_state["fluximmo_live"] = result["fluximmo_listings"]
            except Exception as e:
                st.error(f"Erreur lors du pipeline : {e}")
                result = None

        if result:
            col1, col2, col3 = st.columns(3)
            col1.metric("Annonces scrapées", result["total_scraped"])
            col2.metric("Après filtrage", result["after_filter"])
            col3.metric("Nouvelles annonces", result["new_listings"])

            fluximmo_count = result.get("fluximmo_count", 0)
            fluximmo_after = result.get("fluximmo_after_filter", 0)
            fluximmo_error = result.get("fluximmo_error")
            if fluximmo_count:
                if fluximmo_after == fluximmo_count:
                    st.success(f"Fluximmo : **{fluximmo_count} annonces** récupérées, toutes ont passé les filtres.")
                elif fluximmo_after > 0:
                    st.success(f"Fluximmo : **{fluximmo_count} annonces** récupérées → **{fluximmo_after} ont passé les filtres**.")
                else:
                    st.warning(
                        f"Fluximmo : **{fluximmo_count} annonces** récupérées mais **0 ont passé vos filtres**. "
                        "Réinitialisez les filtres (bouton ci-dessus) ou augmentez **Prix max** et réduisez **Surface min** "
                        "dans l'onglet **⚙️ Configuration**."
                    )
            elif fluximmo_error:
                st.error(f"Fluximmo API : {fluximmo_error}")
            elif not getattr(load_config(), "fluximmo_api_key", ""):
                st.info(
                    "Configurez votre **clé API Fluximmo** dans l'onglet Configuration "
                    "pour obtenir de vraies annonces (essai gratuit 6 jours / 250 crédits)."
                )

            if result["after_filter"] == 0 and result["total_scraped"] > 0:
                st.warning(
                    "0 annonce après filtrage. Vérifiez vos critères dans les **Filtres actifs** "
                    "ci-dessus, ou cliquez **Réinitialiser aux valeurs par défaut**."
                )

    st.divider()
    col_title, col_clear = st.columns([4, 1])
    with col_title:
        st.subheader("Dernières annonces trouvées")
    with col_clear:
        if st.button("🗑️ Vider le cache", help="Efface les annonces vues et le cache local pour tout réafficher au prochain pipeline"):
            seen_file = DATA_DIR / "seen_ids.json"
            listings_file = DATA_DIR / "listings.json"
            if seen_file.exists():
                seen_file.unlink()
            if listings_file.exists():
                listings_file.unlink()
            st.success("Cache vidé. Relancez le pipeline.")
            st.rerun()

    storage = ListingStorage(DATA_DIR)
    stored = storage.load_listings()

    # Annonces Fluximmo live (dernière exécution du pipeline) — affichées en priorité
    fluximmo_live = st.session_state.get("fluximmo_live", [])
    nb_stored_real = sum(1 for l in stored if not l.get("is_mock") and not l.get("is_manual"))
    only_mock_in_store = stored and all(l.get("is_mock") for l in stored)

    if fluximmo_live and only_mock_in_store:
        # Les annonces Fluximmo n'ont pas pu être enregistrées (filtrées ou déjà vues)
        # → les afficher directement depuis la session
        st.info(
            f"**{len(fluximmo_live)} annonces Fluximmo** récupérées lors du dernier pipeline "
            "(non sauvegardées car filtrées ou déjà vues). Cliquez **🗑️ Vider le cache** puis relancez pour les sauvegarder."
        )
        listings = fluximmo_live + stored
    else:
        listings = stored

    if not listings:
        st.info("Aucune annonce stockée. Lancez une analyse pour commencer.")
        return

    water_kw = PropertyFilter.WATER_KEYWORDS
    country_kw = PropertyFilter.COUNTRYSIDE_KEYWORDS

    nb_mock = sum(1 for l in listings if l.get("is_mock"))
    nb_fluximmo = sum(1 for l in listings if l.get("source") == "fluximmo" or l.get("id", "").startswith("fluximmo-"))
    nb_manual = sum(1 for l in listings if l.get("is_manual"))

    if nb_fluximmo:
        st.success(f"{nb_fluximmo} annonce(s) Fluximmo (réelles) dans le cache.")
    if nb_manual:
        st.info(f"{nb_manual} annonce(s) saisie(s) manuellement.")
    if nb_mock > 0 and not nb_fluximmo:
        st.warning(
            f"{nb_mock}/{len(listings)} annonces sont des **données de démonstration**. "
            "Configurez la clé API Fluximmo ou saisissez une annonce manuellement ci-dessous."
        )

    rows = []
    for l in listings:
        text = f"{l.get('title', '')} {l.get('description', '')}".lower()
        has_water = any(kw in text for kw in water_kw)
        is_countryside = any(kw in text for kw in country_kw)
        if l.get("is_mock"):
            type_label = "Démo"
        elif l.get("is_manual"):
            type_label = "Manuel"
        elif l.get("source") == "fluximmo" or l.get("id", "").startswith("fluximmo-"):
            website = l.get("website", "")
            type_label = f"Fluximmo/{website}" if website else "Fluximmo"
        else:
            type_label = "Réel"
        rows.append({
            "Source": (l.get("website") or l.get("source", "")).upper() if (l.get("source") == "fluximmo" or l.get("id", "").startswith("fluximmo-")) else l.get("source", "").upper(),
            "Titre": l.get("title", ""),
            "Prix (€)": l.get("price", 0),
            "Surface (m²)": l.get("surface_m2") or "",
            "Terrain (m²)": l.get("terrain_m2") or "",
            "Lieu": l.get("location", ""),
            "Eau": "💧" if has_water else "—",
            "Campagne": "🌿" if is_countryside else "—",
            "Type": type_label,
            "_id": l.get("id", ""),
        })

    df = pd.DataFrame(rows)
    display_df = df.drop(columns=["_id"])
    try:
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    except Exception:
        # Fallback si pyarrow/numpy incompatibles — rendu HTML sans dépendance Arrow
        st.markdown(
            display_df.to_html(index=False, classes="dataframe", border=0),
            unsafe_allow_html=True,
        )

    # ── Saisie manuelle d'annonce ──────────────────────────────────────────
    st.divider()
    with st.expander("Ajouter une annonce manuellement (coller un texte)", expanded=False):
        st.caption(
            "Collez le texte complet d'une annonce (titre, prix, surface, adresse, description). "
            "Le système extrait les informations automatiquement et génère des liens de recherche "
            "pour retrouver l'annonce en ligne."
        )
        manual_text = st.text_area(
            "Texte de l'annonce",
            height=200,
            placeholder=(
                "Exemple :\n"
                "Ferme rénovée avec source et pré — 145 000 €\n"
                "Magnifique ferme en pierre de 160 m², terrain 2,5 ha, puits fonctionnel.\n"
                "Source captée, grange attenante. Secteur calme.\n"
                "Proche Périgueux (24000) — 5 pièces\n"
                "Contact : 06 12 34 56 78"
            ),
            key="manual_listing_text",
        )
        if st.button("Extraire et ajouter à mes annonces", key="manual_extract_btn"):
            if manual_text.strip():
                extracted = extract_from_text(manual_text)
                storage = ListingStorage(DATA_DIR)
                storage.save_listing(extracted)
                storage.mark_seen(extracted["id"])
                st.success(
                    f"Annonce ajoutée : **{extracted['title']}** — "
                    f"{extracted['price']:,} € — {extracted['location'] or 'lieu non détecté'}"
                )
                if extracted.get("surface_m2"):
                    st.write(f"Surface détectée : {extracted['surface_m2']} m²")
                if extracted.get("terrain_m2"):
                    st.write(f"Terrain détecté : {extracted['terrain_m2']:,} m²")
                if extracted.get("search_links"):
                    st.write("**Liens pour retrouver l'annonce en ligne :**")
                    for label, href in extracted["search_links"].items():
                        st.markdown(f"- [{label}]({href})")
                st.rerun()
            else:
                st.warning("Collez d'abord un texte d'annonce.")

    st.subheader("Détails des annonces")
    for listing in listings[-20:]:
        dvf = listing.get("dvf_stats", {})
        ville_stats = listing.get("ville_stats", {})
        score_global = ville_stats.get("score_global")
        is_mock = listing.get("is_mock", False)
        is_manual = listing.get("is_manual", False)
        score_label = f" · {score_global}/10" if score_global else ""
        is_fluximmo = listing.get("source") == "fluximmo" or listing.get("id", "").startswith("fluximmo-")
        if is_mock:
            tag = " 〔Démo〕"
        elif is_manual:
            tag = " 〔Manuel〕"
        elif is_fluximmo:
            website = listing.get("website", "")
            tag = f" 〔Fluximmo/{website}〕" if website else " 〔Fluximmo〕"
        else:
            tag = ""
        source_label = (listing.get("website") or listing.get("source", "")).upper() if is_fluximmo else listing.get("source", "").upper()
        with st.expander(
            f"{source_label}{tag} — {listing.get('title', '')} — {listing.get('price', 0):,} €{score_label}"
        ):
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**Lieu :** {listing.get('location', 'N/A')}")
                surface = listing.get("surface_m2")
                terrain = listing.get("terrain_m2")
                st.write(f"**Surface :** {surface} m²" if surface else "**Surface :** N/A")
                st.write(f"**Terrain :** {terrain:,} m²" if terrain else "**Terrain :** N/A")
                url = listing.get("url", "")
                if url and not is_mock:
                    link_label = (listing.get("website") or listing.get("source", "")).upper() if is_fluximmo else listing.get("source", "").upper()
                    st.markdown(f"[Voir l'annonce sur {link_label}]({url})")
                elif is_mock:
                    st.caption("Données de démonstration — lien non disponible")
                # Liens de recherche pour annonces manuelles (ou sans URL)
                search_links = listing.get("search_links", {})
                if search_links:
                    st.caption("Rechercher cette annonce en ligne :")
                    link_cols = st.columns(min(3, len(search_links)))
                    for i, (label, href) in enumerate(search_links.items()):
                        with link_cols[i % len(link_cols)]:
                            st.markdown(f"[{label}]({href})")
            with col2:
                if dvf:
                    st.write(f"**Analyse DVF :** {dvf.get('analyse', 'N/A')}")
                    if dvf.get("prix_m2_median"):
                        st.write(f"**Prix médian DVF :** {dvf['prix_m2_median']:,} €/m²")
                    if dvf.get("estimation_prix"):
                        st.write(f"**Estimation :** {dvf['estimation_prix']:,} €")
            st.write(f"**Description :** {listing.get('description', '')}")

            if ville_stats.get("scores"):
                st.divider()
                _render_ville_scores(ville_stats)

            if st.button("Ajouter en prospect", key=f"prospect_{listing.get('id', '')}"):
                st.session_state["prefill_prospect"] = {
                    "notes": f"Annonce : {listing.get('title', '')} — {listing.get('url', '')}",
                    "ville": listing.get("location", "").split("-")[0].strip(),
                    "budget": listing.get("price", 0),
                }
                st.info("Allez dans l'onglet CRM Prospects pour finaliser l'ajout.")


# ── Tab 3 : Configuration ─────────────────────────────────────────────────────


def render_config_tab():
    st.header("Configuration du pipeline")

    config = load_config()

    # ── Diagnostic Fluximmo (hors formulaire pour éviter le bug des form buttons) ──
    st.subheader("API Fluximmo (annonces réelles — recommandé)")
    st.caption(
        "Fluximmo agrège 500 000+ annonces depuis 70 portails (PAP, SeLoger, LeBonCoin…). "
        "Essai gratuit : 6 jours / 250 crédits. Documentation : https://doc.fluximmo.io"
    )
    fluximmo_key_display = st.text_input(
        "Clé API Fluximmo",
        value=getattr(config, "fluximmo_api_key", ""),
        type="password",
        placeholder="trial_default_xxxx-xxxx-xxxx-xxxx",
        key="fluximmo_key_input",
        help="Clé x-api-key pour l'API Fluximmo V2.",
    )
    if st.button("Tester la connexion Fluximmo", type="secondary"):
        key_to_test = fluximmo_key_display.strip() or getattr(config, "fluximmo_api_key", "")
        if not key_to_test:
            st.warning("Entrez d'abord votre clé API Fluximmo.")
        else:
            with st.spinner("Diagnostic en cours — test de tous les endpoints…"):
                report = fluximmo_diagnose(key_to_test)
            ok = [r for r in report if r.get("status") == 200]
            not_10003 = [r for r in report
                         if r.get("status") not in (200,) and "10003" not in r.get("type", "")
                         and "ERR" not in str(r.get("status", ""))
                         and "CONNEXION" not in str(r.get("status", ""))]
            if ok:
                st.success(f"{len(ok)} endpoint(s) ont répondu HTTP 200 !")
            elif not_10003:
                st.warning(
                    f"{len(not_10003)} endpoint(s) existent (erreur API ≠ 10003). "
                    "Cliquez pour voir les détails."
                )
            else:
                st.error("Tous les endpoints testés sont inconnus (code 10003) ou en erreur réseau.")
            for r in report:
                status = r.get("status", "?")
                rtype = r.get("type", "")
                is_known_route = "10003" not in rtype and status != "CONNEXION_REFUSEE"
                with st.expander(
                    f"[{status}] {r['url']}",
                    expanded=(status == 200 or (is_known_route and "ERR" not in str(status)))
                ):
                    st.caption(rtype)
                    detail = r.get("detail", "")
                    if detail:
                        st.code(detail[:800], language="json")

    st.divider()

    with st.form("pipeline_config_form"):
        st.subheader("Sources de scraping classiques (fallback si Fluximmo non configuré)")
        st.caption("Sources RSS ✅ : annonces réelles garanties. Sources ⚠️ : peuvent être bloquées par anti-bot.")
        col1, col2 = st.columns(2)
        with col1:
            src_pap = st.checkbox("PAP.fr ✅ RSS", value="pap" in config.sources,
                                  help="Flux RSS public — toutes annonces particuliers")
            src_seloger = st.checkbox("SeLoger ✅ RSS", value="seloger" in config.sources,
                                      help="Flux RSS public — annonces professionnelles")
        with col2:
            src_rurales = st.checkbox("Propriétés Rurales ✅", value="proprietes-rurales" in config.sources,
                                      help="proprietes-rurales.com — spécialiste rural, campagne, fermes, étangs")
            src_lbc = st.checkbox("LeBonCoin ⚠️", value="leboncoin" in config.sources,
                                  help="Pas de RSS — peut être bloqué par anti-bot")

        st.subheader("Localisation")
        region_options = ["(toute la France)"] + sorted(REGIONS.keys())
        filtre_region_saved = getattr(config, "filtre_region", "")
        region_idx = (
            region_options.index(filtre_region_saved)
            if filtre_region_saved in region_options else 0
        )
        filtre_region_raw = st.selectbox("Région", region_options, index=region_idx)
        filtre_region = "" if filtre_region_raw == "(toute la France)" else filtre_region_raw

        col1, col2 = st.columns(2)
        with col1:
            filtre_departement = st.text_input(
                "Département (nom ou code INSEE)",
                value=getattr(config, "filtre_departement", ""),
                placeholder="ex : Dordogne ou 24",
                help="Filtrer les annonces par département. Laissez vide pour ignorer.",
            )
        with col2:
            filtre_ville = st.text_input(
                "Ville / commune",
                value=getattr(config, "filtre_ville", ""),
                placeholder="ex : Périgueux",
                help="Filtrer les annonces par ville. Laissez vide pour ignorer.",
            )

        st.subheader("Critères de recherche")
        col1, col2 = st.columns(2)
        with col1:
            prix_max = st.number_input("Prix max (€)", min_value=0, value=config.prix_max, step=10000)
            surface_min = st.number_input("Surface min (m²)", min_value=0, value=config.surface_min, step=10)
        with col2:
            prix_min = st.number_input("Prix min (€)", min_value=0, value=config.prix_min, step=10000)
            terrain_min = st.number_input("Terrain min (m²)", min_value=0, value=config.terrain_min, step=100)

        st.subheader("Filtres spéciaux")
        col1, col2 = st.columns(2)
        with col1:
            filtrer_eau = st.checkbox("Propriétés avec eau (puits, source, étang...)", value=config.filtrer_eau)
        with col2:
            filtrer_campagne = st.checkbox("Propriétés en campagne (ferme, hameau...)", value=config.filtrer_campagne)

        mots_cles_requis_str = st.text_input(
            "Mots-clés requis (séparés par virgules)",
            value=", ".join(config.mots_cles_requis),
        )
        mots_cles_exclus_str = st.text_input(
            "Mots-clés exclus (séparés par virgules)",
            value=", ".join(config.mots_cles_exclus),
        )

        st.subheader("Enrichissement")
        col1, col2 = st.columns(2)
        with col1:
            enrichir_dvf = st.checkbox("Enrichir avec données DVF (data.gouv.fr)", value=config.enrichir_dvf)
        with col2:
            enrichir_ville = st.checkbox(
                "Enrichir avec scores de vie (villesavivre.fr)",
                value=getattr(config, "enrichir_ville", True),
            )

        st.subheader("Notifications Slack")
        slack_webhook = st.text_input(
            "URL du webhook Slack",
            value=config.slack_webhook,
            type="password",
            placeholder="https://hooks.slack.com/services/...",
        )

        st.subheader("Notifications Email")
        col1, col2 = st.columns(2)
        with col1:
            smtp_host = st.text_input("Serveur SMTP", value=config.smtp_host, placeholder="smtp.gmail.com")
            smtp_user = st.text_input("Utilisateur SMTP", value=config.smtp_user)
        with col2:
            smtp_port = st.number_input("Port SMTP", min_value=1, max_value=65535, value=config.smtp_port)
            smtp_password = st.text_input("Mot de passe SMTP", value=config.smtp_password, type="password")
        email_destinataire = st.text_input("Email destinataire", value=config.email_destinataire)

        st.subheader("Google Sheets")
        google_sheets_id = st.text_input("ID du spreadsheet Google Sheets", value=config.google_sheets_id)
        google_credentials_file = st.text_input(
            "Chemin vers le fichier credentials (JSON)",
            value=config.google_credentials_file,
        )

        submitted = st.form_submit_button("Sauvegarder la configuration", type="primary")

    if submitted:
        sources = []
        if src_pap:
            sources.append("pap")
        if src_seloger:
            sources.append("seloger")
        if src_rurales:
            sources.append("proprietes-rurales")
        if src_lbc:
            sources.append("leboncoin")

        config.sources = sources
        config.fluximmo_api_key = fluximmo_key_display.strip()
        config.filtre_region = filtre_region
        config.filtre_departement = filtre_departement.strip()
        config.filtre_ville = filtre_ville.strip()
        config.prix_min = int(prix_min)
        config.prix_max = int(prix_max)
        config.surface_min = int(surface_min)
        config.terrain_min = int(terrain_min)
        config.filtrer_eau = filtrer_eau
        config.filtrer_campagne = filtrer_campagne
        config.mots_cles_requis = [k.strip() for k in mots_cles_requis_str.split(",") if k.strip()]
        config.mots_cles_exclus = [k.strip() for k in mots_cles_exclus_str.split(",") if k.strip()]
        config.enrichir_dvf = enrichir_dvf
        config.enrichir_ville = enrichir_ville
        config.slack_webhook = slack_webhook
        config.smtp_host = smtp_host
        config.smtp_port = int(smtp_port)
        config.smtp_user = smtp_user
        config.smtp_password = smtp_password
        config.email_destinataire = email_destinataire
        config.google_sheets_id = google_sheets_id
        config.google_credentials_file = google_credentials_file

        save_config(config)
        st.success("Configuration sauvegardée avec succès.")


# ── Tab 4 : CRM Prospects ─────────────────────────────────────────────────────


def render_crm_tab():
    st.header("CRM Prospects")

    prospects = load_prospects()

    if not prospects:
        st.info("Aucun prospect enregistré. Utilisez l'agent pour en ajouter.")
        return

    statuts = ["tous", "nouveau", "contacté", "qualifié", "signé"]
    selected_statut = st.selectbox("Filtrer par statut", statuts)

    filtered = prospects if selected_statut == "tous" else [
        p for p in prospects if p.get("statut") == selected_statut
    ]

    df = pd.DataFrame(
        [
            {
                "ID": p.get("id", ""),
                "Nom": p.get("nom", ""),
                "Ville": p.get("ville", ""),
                "Budget": f"{p.get('budget', 0):,} €",
                "Type": p.get("type_bien", ""),
                "Statut": p.get("statut", ""),
                "Date": p.get("date_creation", ""),
            }
            for p in filtered
        ]
    )
    try:
        st.dataframe(df, use_container_width=True, hide_index=True)
    except Exception:
        st.markdown(df.to_html(index=False, classes="dataframe", border=0), unsafe_allow_html=True)

    csv_data = pd.DataFrame(filtered).to_csv(index=False, encoding="utf-8")
    st.download_button(
        "Exporter CSV",
        csv_data,
        "prospects.csv",
        "text/csv",
        use_container_width=False,
    )

    st.subheader("Gestion des prospects")
    for p in filtered:
        with st.expander(f"{p.get('nom', '')} — {p.get('ville', '')} — {p.get('statut', '')}"):
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**Email :** {p.get('email', 'N/A')}")
                st.write(f"**Téléphone :** {p.get('telephone', 'N/A')}")
                st.write(f"**Budget :** {p.get('budget', 0):,} €")
            with col2:
                st.write(f"**Type de bien :** {p.get('type_bien', 'N/A')}")
                st.write(f"**Statut :** {p.get('statut', 'N/A')}")
                st.write(f"**Créé le :** {p.get('date_creation', 'N/A')}")
            if p.get("notes"):
                st.write(f"**Notes :** {p['notes']}")

            new_statut = st.selectbox(
                "Changer le statut",
                ["nouveau", "contacté", "qualifié", "signé"],
                index=["nouveau", "contacté", "qualifié", "signé"].index(p.get("statut", "nouveau")),
                key=f"statut_{p.get('id', '')}",
            )
            if st.button("Mettre à jour le statut", key=f"update_{p.get('id', '')}"):
                all_prospects = load_prospects()
                for prospect in all_prospects:
                    if prospect.get("id") == p.get("id"):
                        prospect["statut"] = new_statut
                save_prospects_to_file(all_prospects)
                st.success(f"Statut mis à jour : {new_statut}")
                st.rerun()

    prefill = st.session_state.get("prefill_prospect")
    if prefill:
        st.subheader("Ajouter un prospect depuis une annonce")
        with st.form("add_prospect_form"):
            nom = st.text_input("Nom complet")
            email = st.text_input("Email")
            telephone = st.text_input("Téléphone")
            budget = st.number_input("Budget (€)", min_value=0, value=prefill.get("budget", 0), step=5000)
            type_bien = st.text_input("Type de bien", value="maison")
            ville = st.text_input("Ville", value=prefill.get("ville", ""))
            notes = st.text_area("Notes", value=prefill.get("notes", ""))

            if st.form_submit_button("Enregistrer le prospect"):
                if nom and email:
                    save_prospect(nom, email, int(budget), type_bien, ville, telephone, notes)
                    del st.session_state["prefill_prospect"]
                    st.success("Prospect enregistré.")
                    st.rerun()
                else:
                    st.error("Nom et email requis.")


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    st.title("Agent de Prospection Immobilière")

    with st.sidebar:
        st.header("Configuration")
        api_key = st.text_input(
            "Clé API Anthropic",
            type="password",
            value=os.environ.get("ANTHROPIC_API_KEY", ""),
            help="Obtenez votre clé sur console.anthropic.com",
        )
        if not api_key:
            st.warning("Clé API requise pour utiliser l'agent")

        st.divider()
        st.subheader("Statut pipeline")
        last_time = st.session_state.get("last_pipeline_time")
        last_result = st.session_state.get("last_pipeline_result")
        if last_time and last_result:
            st.write(f"Dernière exécution : {last_time}")
            st.write(f"Nouvelles annonces : {last_result.get('new_listings', 0)}")
        else:
            st.write("Aucune exécution récente")

        st.divider()
        if st.button("Nouvelle conversation", use_container_width=True):
            st.session_state.history = []
            st.session_state.display = []
            st.rerun()

    tab1, tab2, tab3, tab4 = st.tabs([
        "Agent",
        "Pipeline de surveillance",
        "Configuration pipeline",
        "CRM Prospects",
    ])

    with tab1:
        render_agent_tab(api_key)

    with tab2:
        render_pipeline_tab()

    with tab3:
        render_config_tab()

    with tab4:
        render_crm_tab()


if __name__ == "__main__":
    main()
