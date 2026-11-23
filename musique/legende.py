"""Accroches (texte en haut de la vidéo) et légendes TikTok — toujours vraies, en français.

Légende = accroche courte + @artiste + 3 à 5 hashtags (#NomArtiste #NomDuSon #RapFR …).
Pas de mention « publicité » (fan, aucun avantage reçu)… sauf si l'artiste a `contenu_de_marque: true` :
alors « Publicité » est ajouté en tête de légende et l'option contenu de marque doit être activée.
"""
from __future__ import annotations

import hashlib
import re

# Formules par type de passage. {a} = artiste, {s} = titre du son. Toujours vraies par rapport au passage.
ACCROCHES = {
    "refrain": ["Le refrain que tout le monde chante…", "Ce refrain de {a} reste dans la tête",
                "Le refrain de « {s} » 🔁", "Tu connais ce refrain de {a} ?"],
    "drop": ["Attends le drop…", "Le moment où « {s} » explose", "Ce passage de {a} 🔥",
             "Monte le son pour ce passage"],
    "punchline": ["Cette punchline de {a}…", "{a} a vraiment dit ça", "La phrase de « {s} » qui reste",
                  "Écoute bien les paroles de {a}"],
    "couplet": ["Ce passage de {a}…", "Ce couplet de « {s} »", "{a} sur « {s} »", "Écoute bien ce passage"],
    "impose": ["Ce passage de {a}…", "« {s} » — {a}", "Le meilleur moment de « {s} » ?"],
}


def _tag(t: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", t or "")
    return "#" + "".join(ch for ch in t if ch.isalnum() and not unicodedata.combining(ch))


def choisir_accroche(c: dict, cfg: dict) -> str:
    perso = (c.get("texte_perso") or "").strip()
    if perso:
        return perso
    choix = ACCROCHES.get(c.get("type") or "couplet", ACCROCHES["couplet"])
    if not c.get("titre_son"):
        choix = [x for x in choix if "{s}" not in x] or ["Ce passage de {a}…"]
    n = int(hashlib.md5(str(c.get("id", "")).encode()).hexdigest(), 16) % len(choix)
    t = choix[n].format(a=c.get("artiste_nom", ""), s=c.get("titre_son", ""))
    return re.sub(r"\b([Dd])e ([AEIOUYÉaeiouyé])", r"\1'\2", t)  # « de Ashe » → « d'Ashe »


def mention(fiche: dict) -> str:
    """@compte TikTok de l'artiste (réglage `tiktok`), sinon @NomSansEspaces."""
    t = (fiche.get("tiktok") or "").strip()
    if t:
        return t if t.startswith("@") else f"@{t}"
    return "@" + "".join(ch for ch in fiche.get("nom", "") if ch.isalnum())


def legende(c: dict, fiche: dict, cfg: dict) -> str:
    accroche = c.get("accroche") or choisir_accroche(c, cfg)
    tags = [_tag(fiche.get("nom", ""))]
    if c.get("titre_son"):
        tags.append(_tag(c["titre_son"]))
    tags += (fiche.get("hashtags") or "").split() + cfg.get("hashtags", "#RapFR #Rap").split()
    vus, propres = set(), []
    for h in tags:
        if len(h) > 1 and h.lower() not in vus:
            vus.add(h.lower())
            propres.append(h)
    texte = f"{accroche} {mention(fiche)} {' '.join(propres[:5])}".strip()
    if fiche.get("contenu_de_marque"):
        texte = f"Publicité · {texte}"
    return texte
