"""Visuels AUTORISÉS pour les modes `son` et `lifestyle` (droits d'auteur) :

- `banque`       : ta banque lifestyle (Release `banque` + data/banque.json) ;
- `clip_artiste` : le clip officiel du MÊME artiste que le son (fichier dans `entrees`, son nom
                   doit commencer par la clé de l'artiste, ex. `ninho_jefe_clip.mp4`) ;
- `pexels`       : vidéos libres de droits Pexels (API gratuite, secret PEXELS_API_KEY).
Jamais d'images du clip d'un autre artiste, jamais d'autre musique (le son des plans est coupé).
"""
from __future__ import annotations

import os
import random
from pathlib import Path

import requests

from . import banque as bq
from .commun import BANQUE, TRAVAIL, ecrire, lire

PEXELS = "https://api.pexels.com/videos/search"
MOTS_PEXELS = ["city night", "luxury car", "street", "neon lights", "highway night", "skyline", "rain city",
               "money", "sports car", "urban"]


class VisuelsRefuses(RuntimeError):
    pass


def verifier_clip_artiste(nom_fichier: str, cle_artiste: str) -> None:
    """Le clip doit être celui du même artiste : son nom de fichier commence par la clé de l'artiste."""
    base = Path(nom_fichier).name.lower()
    cle = (cle_artiste or "").lower()
    if not cle or not (base.startswith(cle + "_") or base.startswith(cle + "-") or base.startswith(cle + ".")):
        raise VisuelsRefuses(
            f"« {nom_fichier} » : pour utiliser un clip comme visuel, son nom doit commencer par la clé de "
            f"l'artiste du son (« {cle}_… »). Les images du clip d'un autre artiste sont interdites.")


def plans_banque(tags: list[str] | None = None) -> list[dict]:
    """Plans de la banque (filtrés par tags si demandé), avec leur fiche d'analyse."""
    index = lire(BANQUE, {})
    plans = []
    for nom, f in index.items():
        if f.get("duree", 0) < 1.5:
            continue
        if tags and not set(t.lower() for t in tags) & set(f.get("tags", [])):
            continue
        plans.append(dict(f, nom=nom, origine="banque"))
    return plans


def plans_pexels(mots: list[str] | None, combien: int = 12, log=print) -> list[dict]:
    """Télécharge des vidéos verticales libres de droits depuis Pexels (gratuit, clé requise)."""
    cle = os.environ.get("PEXELS_API_KEY", "").strip()
    if not cle:
        raise VisuelsRefuses("clé Pexels absente : ajoute le secret GitHub PEXELS_API_KEY (gratuit sur pexels.com/api)")
    dossier = TRAVAIL / "pexels"
    dossier.mkdir(parents=True, exist_ok=True)
    cache = lire(dossier / "index.json", {})
    rng = random.Random(" ".join(mots or []))
    requetes = list(mots or MOTS_PEXELS)
    rng.shuffle(requetes)
    plans: list[dict] = []
    for q in requetes:
        if len(plans) >= combien:
            break
        r = requests.get(PEXELS, params={"query": q, "orientation": "portrait", "size": "medium", "per_page": 6},
                         headers={"Authorization": cle}, timeout=30)
        if r.status_code != 200:
            log(f"   Pexels « {q} » : erreur {r.status_code}", "alerte")
            continue
        for v in r.json().get("videos", []):
            if len(plans) >= combien:
                break
            fichiers = sorted([f for f in v.get("video_files", []) if f.get("height") and f.get("file_type") == "video/mp4"],
                              key=lambda f: abs(f["height"] - 1920))
            if not fichiers:
                continue
            nom = f"pexels_{v['id']}.mp4"
            chemin = dossier / nom
            if not chemin.exists():
                with requests.get(fichiers[0]["link"], stream=True, timeout=120) as dl:
                    dl.raise_for_status()
                    with open(chemin, "wb") as out:
                        for bloc in dl.iter_content(1 << 20):
                            out.write(bloc)
            fiche = cache.get(nom) or bq.analyser(chemin)
            fiche.update(tags=q.split(), credit=f"Pexels — {v.get('user', {}).get('name', '')}", url=v.get("url"))
            cache[nom] = fiche
            plans.append(dict(fiche, nom=nom, chemin=str(chemin), origine="pexels"))
    ecrire(dossier / "index.json", cache)
    if not plans:
        raise VisuelsRefuses("aucune vidéo Pexels trouvée")
    return plans


def plans_clip(chemin: Path) -> list[dict]:
    fiche = bq.analyser(chemin)
    return [dict(fiche, nom=chemin.name, chemin=str(chemin), origine="clip_artiste")]


def chemin_plan(p: dict) -> Path:
    if p.get("chemin"):
        return Path(p["chemin"])
    return bq.chemin_local(p["nom"])


def choisir_plans(plans: list[dict], coupes: list[tuple[float, float, float]], graine: str) -> list[dict]:
    """Associe un plan à chaque segment (debut, fin, energie du segment).

    - énergie forte → plans qui bougent ; énergie faible → plans calmes ;
    - couleurs : on garde l'ambiance du premier plan choisi (couleur dominante / luminosité proches) ;
    - jamais deux fois de suite le même plan ; dans un même plan long, on prend des moments différents.
    """
    if not plans:
        raise VisuelsRefuses("aucun plan disponible")
    rng = random.Random(graine)
    choix, utilises, ref = [], {}, None
    for (a, b, energie) in coupes:
        d = b - a
        possibles = [p for p in plans if p["duree"] >= d + 0.2] or plans
        def note(p):
            s = 1 - abs(p.get("mouvement", 0.5) - energie)
            if ref is not None:
                s += 0.6 * bq.proximite_couleurs(ref, p)
            s -= 0.5 * utilises.get(p["nom"], 0)
            if choix and choix[-1]["nom"] == p["nom"] and len(plans) > 1:
                s -= 5
            if p.get("orientation") == "vertical":
                s += 0.2  # pas de perte en recadrant
            return s + rng.random() * 0.3
        p = max(possibles, key=note)
        ref = ref or p
        n = utilises.get(p["nom"], 0)
        marge = max(p["duree"] - d, 0)
        # moments différents du même plan : on avance dans la vidéo à chaque réutilisation
        depart = (marge * ((n * 0.37 + rng.random() * 0.2) % 1.0)) if marge > 0 else 0.0
        utilises[p["nom"]] = n + 1
        choix.append({"nom": p["nom"], "plan": p, "depart": round(depart, 2), "duree": round(d, 3),
                      "origine": p["origine"]})
    return choix
