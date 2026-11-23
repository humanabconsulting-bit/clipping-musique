"""Outils partagés : chemins, lecture/écriture JSON, journal (copié de clipping-auto, adapté).

Le code et les données peuvent vivre dans deux dépôts différents :
- le CODE (ce dépôt) ;
- les DONNÉES (config/reglages.json, data/*.json, Releases des vidéos) dans un dépôt privé,
  récupéré par les workflows dans le dossier indiqué par la variable d'environnement DONNEES.
Sans DONNEES, tout est lu dans ce dépôt (pratique pour tester).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DONNEES = Path(os.environ["DONNEES"]).resolve() if os.environ.get("DONNEES") else RACINE
CONFIG = DONNEES / "config" / "reglages.json"
CONFIG_EXEMPLE = RACINE / "config" / "reglages.exemple.json"
DATA = DONNEES / "data"
TRAVAIL = RACINE / "travail"          # fichiers temporaires (non versionnés)
SORTIE = RACINE / "sortie"            # clips finis hors GitHub (non versionnés)
ETAT = TRAVAIL / "etat.json"          # état partagé entre les étapes d'un passage

CLIPS = DATA / "clips.json"
DECISIONS = DATA / "decisions.json"
PASSAGES = DATA / "passages.json"
EN_DIRECT = DATA / "en_direct.json"
BANQUE = DATA / "banque.json"

PREFIXE_CODE = "M"                    # codes courts M0001, M0002…


def maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def lire(chemin: Path, defaut):
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return defaut


def ecrire(chemin: Path, donnees) -> None:
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(chemin.suffix + ".tmp")
    tmp.write_text(json.dumps(donnees, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(chemin)


def reglages() -> dict:
    """Réglages réels (dépôt de données) ou, à défaut, le modèle d'exemple."""
    cfg = lire(CONFIG, None)
    return cfg if cfg is not None else lire(CONFIG_EXEMPLE, {})


def sur_github() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def artiste(cfg: dict, cle: str) -> dict:
    """Fiche d'un artiste (par sa clé ou son nom), ou une fiche minimale sans accord."""
    cle_n = (cle or "").strip().lower()
    for a in cfg.get("artistes", []):
        if a.get("cle", "").lower() == cle_n or a.get("nom", "").lower() == cle_n:
            return a
    return {"cle": cle_n, "nom": cle or "?", "accord": False, "accord_note": "", "contenu_de_marque": False}


class Journal:
    """Journal du passage en cours : écrit dans l'état et affiché dans la console."""

    def __init__(self, etat: dict):
        self.etat = etat
        self.etat.setdefault("journal", [])

    def __call__(self, message: str, niveau: str = "info") -> None:
        ligne = {"t": maintenant(), "niveau": niveau, "msg": message}
        self.etat["journal"].append(ligne)
        print(f"[{niveau.upper():5}] {message}", flush=True)
        ecrire(EN_DIRECT, {
            "passage": self.etat.get("id"),
            "etape": self.etat.get("etape"),
            "statut": "en_cours",
            "maj": ligne["t"],
            "dernier_message": message,
            "progression": self.etat.get("progression", {}),
        })
