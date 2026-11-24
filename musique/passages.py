"""Choix des meilleurs passages d'un morceau, calés sur les mesures, sans chevauchement.

Score d'un passage (0 à ~1,6) :
  0,40 × répétition (refrain)  +  0,30 × énergie  +  0,20 × densité de voix
  + jusqu'à 0,25 si un DROP tombe dans la 1ʳᵉ mesure  + jusqu'à 0,20 de punchlines (mots-clés)
  + jusqu'à 0,25 si le passage est un pic de la courbe « moments les plus revus » YouTube (si disponible).
Le début et la fin tombent sur un début de mesure ; on évite de couper un mot (rime) à la fin.
"""
from __future__ import annotations

import unicodedata

import numpy as np

from .analyse_audio import mesures

# Mots qui signalent une punchline / un passage fort (français, anglais, darija en lettres latines)
PUNCHLINES = [
    "jamais", "toujours", "personne", "tout le monde", "billet", "oseille", "money", "cash", "bénéf", "benef",
    "quartier", "tieks", "hood", "frère", "frerot", "khoya", "kho", "wallah", "wesh", "bled", "maman", "mama",
    "rrah", "skrt", "bang", "gang", "chef", "boss", "king", "roi", "zone", "hagra", "sahbi", "drari", "flouss",
    "lmima", "rebeu", "la rue", "street", "loyal", "traître", "traitre", "haters", "jaloux", "succès", "succes",
]


def _norm_txt(t: str) -> str:
    t = unicodedata.normalize("NFKD", (t or "").lower())
    return "".join(ch for ch in t if not unicodedata.combining(ch))


def _moyenne(serie: list[float], beats: list[float], a: float, b: float) -> float:
    idx = [i for i, t in enumerate(beats) if a <= t < b]
    return float(np.mean([serie[i] for i in idx])) if idx else 0.0


def _mot_coupe(mots: list[dict], t: float) -> bool:
    return any(w["debut"] < t - 0.05 and w["fin"] > t + 0.05 for w in mots)


def densite_voix(mots: list[dict], a: float, b: float) -> float:
    """Mots par seconde ramenés à 0–1 (un rap rapide ≈ 3 mots/s)."""
    n = sum(1 for w in mots if a <= w["debut"] < b)
    return min(1.0, n / max(b - a, 1) / 3.0)


def punch(mots: list[dict], a: float, b: float) -> tuple[float, list[str]]:
    texte = _norm_txt(" ".join(w["mot"] for w in mots if a <= w["debut"] < b))
    trouves = [p for p in PUNCHLINES if _norm_txt(p) in texte]
    return min(0.2, 0.05 * len(trouves)), trouves


def choisir(analyse: dict, mots: list[dict], nombre: int, duree_min: float, duree_max: float,
            courbe: list[dict] | None = None, deja: list[tuple[float, float]] | None = None) -> list[dict]:
    """Retourne au plus `nombre` passages {debut, fin, score, details}, du plus fort au plus faible."""
    beats = analyse["beats"]
    bornes = mesures(analyse) + [analyse["duree"]]
    deja = list(deja or [])
    candidats = []
    # Intro et fin de vidéo exclues : écrans de fin (« abonne-toi », « watch and listen now »), fondus, silences
    total = analyse["duree"]
    debut_utile = 3.0 if total > 40 else 0.0
    fin_utile = total - (min(15.0, total * 0.08) if total > 60 else 0.0)
    for i, a in enumerate(bornes[:-1]):
        if a < debut_utile:
            continue
        for j in range(i + 1, len(bornes)):
            b = bornes[j]
            d = b - a
            if d < duree_min:
                continue
            if d > duree_max + 0.01 or b > fin_utile + 0.05:
                break
            # pas de coupe au milieu d'un mot à la fin : on essaie la mesure suivante (ou on garde)
            if mots and _mot_coupe(mots, b) and j + 1 < len(bornes) and bornes[j + 1] - a <= duree_max:
                continue
            rep = _moyenne(analyse["repetition"], beats, a, b)
            ene = _moyenne(analyse["energie"], beats, a, b)
            voix = densite_voix(mots, a, b) if mots else _moyenne(analyse["voix_bande"], beats, a, b)
            premiere = bornes[min(i + 1, len(bornes) - 1)] if i + 1 < len(bornes) else b
            drp = max([analyse["drop"][k] for k, t in enumerate(beats) if a - 0.3 <= t < premiere] or [0])
            bonus_p, mots_p = punch(mots, a, b)
            bonus_c = 0.0
            if courbe:
                bonus_c = 0.25 * max([c.get("value", 0) for c in courbe
                                      if c["start_time"] < b and c["end_time"] > a] or [0])
            score = 0.40 * rep + 0.30 * ene + 0.20 * voix + 0.25 * drp + bonus_p + bonus_c
            score -= 0.03 * abs(d - (duree_min + duree_max) / 2) / max(duree_max, 1)  # léger goût pour le milieu
            candidats.append({
                "debut": round(a, 2), "fin": round(b, 2), "score": round(score, 3),
                "details": {"refrain": round(rep, 2), "energie": round(ene, 2), "voix": round(voix, 2),
                            "drop": round(drp, 2), "punchlines": mots_p, "courbe": round(bonus_c, 2)},
            })
    choisis: list[dict] = []
    for c in sorted(candidats, key=lambda x: x["score"], reverse=True):
        if len(choisis) >= nombre:
            break
        if any(c["debut"] < f - 0.1 and d + 0.1 < c["fin"] for d, f in deja + [(x["debut"], x["fin"]) for x in choisis]):
            continue
        choisis.append(c)
    for c in choisis:
        det = c["details"]
        c["type"] = ("drop" if det["drop"] >= 0.6 else "refrain" if det["refrain"] >= 0.6
                     else "punchline" if det["punchlines"] else "couplet")
    return choisis


def passage_force(debut: float, fin: float, analyse: dict) -> dict:
    """Passage imposé (debut/fin donnés) : recalé sur la mesure la plus proche."""
    bornes = mesures(analyse) + [analyse["duree"]]
    a = min(bornes, key=lambda t: abs(t - debut))
    b = min([t for t in bornes if t > a] or [fin], key=lambda t: abs(t - fin))
    return {"debut": round(a, 2), "fin": round(b, 2), "score": 1.0, "type": "impose", "details": {"impose": True}}


def lire_temps(t: str | float | None) -> float | None:
    """« 1:12 » → 72.0 ; « 72 » → 72.0 ; vide → None."""
    if t in (None, ""):
        return None
    if isinstance(t, (int, float)):
        return float(t)
    s = 0.0
    for part in str(t).strip().split(":"):
        s = s * 60 + float(part.replace(",", "."))
    return s
