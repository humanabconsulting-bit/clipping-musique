"""Banques de vidéos (visuels autorisés), chacune dans une Release du dépôt de données privé :

| Release              | Contenu                                         | Utilisable pour                 |
|----------------------|-------------------------------------------------|---------------------------------|
| `banque-generale`    | vidéos lifestyle générales (voitures, ville…)   | TOUS les artistes               |
| `banque-reacts`      | streamers qui réagissent au son d'un artiste    | SEULEMENT l'artiste concerné    |
| `banque-<cle>`       | anciennes vidéos de l'artiste (clips, lives…)   | SEULEMENT cet artiste           |

Noms de fichiers :
- générale / artiste : les mots du nom donnent les tags → `voiture_nuit_ville.mp4` = voiture, nuit, ville ;
- reacts : `<cle-artiste>__<streamer>_<tags>.mp4` → `ninho__kameto_jefe.mp4` (artiste ninho, streamer kameto).
  Un react n'est JAMAIS utilisé pour un autre artiste que celui du nom.

Index : data/banque.json = {release: {fichier: fiche}}. Pour chaque vidéo : durée, orientation,
luminosité, couleurs dominantes, mouvement, position du visage (pour bien recadrer en 9:16), tags.

Usage :
  python -m musique.banque indexer                    # toutes les banques (nouvelles vidéos seulement)
  python -m musique.banque indexer --banque banque-reacts
  python -m musique.banque indexer --dossier D --banque banque-generale   # test sur un dossier
"""
from __future__ import annotations

import argparse
import colorsys
import json
import re
import subprocess
from pathlib import Path

import numpy as np

from . import montage
from .commun import BANQUE, TRAVAIL, ecrire, lire, maintenant

GENERALE = "banque-generale"
REACTS = "banque-reacts"
PREFIXE = "banque-"
DOSSIER = TRAVAIL / "banques"
EXTENSIONS = (".mp4", ".mov", ".m4v", ".webm", ".mkv")


def banque_artiste(cle: str) -> str:
    return f"{PREFIXE}{cle.lower()}"


def type_banque(nom: str) -> str:
    return "generale" if nom in (GENERALE, "banque") else "reacts" if nom == REACTS else "artiste"


def tags_du_nom(nom: str) -> list[str]:
    base = Path(nom).stem.lower().replace("__", "_")
    return [t for t in re.split(r"[_\-\s.]+", base) if t and not t.isdigit() and len(t) > 1]


def infos_react(nom: str) -> tuple[str, str]:
    """`ninho__kameto_jefe.mp4` → ("ninho", "kameto"). ("", "") si le nom ne suit pas la règle."""
    base = Path(nom).stem.lower()
    if "__" not in base:
        return "", ""
    art, reste = base.split("__", 1)
    return art.strip("_- "), re.split(r"[_\-\s]+", reste.strip("_- "))[0]


def analyser(video: Path) -> dict:
    """Mesures d'un plan (10 images réparties sur la durée)."""
    import cv2
    info = montage.infos_video(video)
    cap = cv2.VideoCapture(str(video))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    lum, mouv, pixels, visages = [], [], [], []
    detecteur = None
    try:
        from .cadrage import _Detecteur
        detecteur = _Detecteur()
    except Exception:
        pass
    for k in range(10):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(max(n - 3, 1) * (k + 0.5) / 10))
        ok1, a = cap.read()
        ok2, b = cap.read()
        if not ok1:
            continue
        if detecteur:
            petite = cv2.resize(a, (640, int(a.shape[0] * 640 / a.shape[1])))
            vs = detecteur.visages(petite)
            if vs:
                visages.append(max(vs, key=lambda v: v[2] * v[3])[0] / 640)
        a = cv2.resize(a, (160, 90))
        lum.append(float(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).mean()) / 255)
        if ok2:
            b = cv2.resize(b, (160, 90))
            mouv.append(float(cv2.absdiff(a, b).mean()) / 255)
        pixels.append(a.reshape(-1, 3))
    cap.release()
    couleurs = []
    if pixels:
        px = np.concatenate(pixels).astype(np.float32)
        crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
        _, labels, centres = cv2.kmeans(px, 3, None, crit, 2, cv2.KMEANS_PP_CENTERS)
        parts = np.bincount(labels.ravel(), minlength=3) / len(labels)
        for i in np.argsort(-parts):
            bgr = centres[i]
            couleurs.append({"hex": "#%02x%02x%02x" % (int(bgr[2]), int(bgr[1]), int(bgr[0])),
                             "part": round(float(parts[i]), 2)})
    w, h = info["largeur"], info["hauteur"]
    return {
        "duree": round(info["duree"], 2),
        "largeur": w, "hauteur": h,
        "orientation": "vertical" if h > w * 1.1 else "horizontal" if w > h * 1.1 else "carre",
        "luminosite": round(float(np.mean(lum)) if lum else 0.5, 3),
        # 0 = plan fixe, 1 = très agité
        "mouvement": round(min(1.0, float(np.mean(mouv)) * 25) if mouv else 0.0, 3),
        "couleurs": couleurs,
        # position horizontale habituelle du visage (0 = gauche, 1 = droite), pour recadrer dessus
        "centre_visage": round(float(np.median(visages)), 3) if len(visages) >= 3 else None,
        "son": info["son"],
    }


def teinte(hexa: str) -> tuple[float, float, float]:
    r, g, b = (int(hexa[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hsv(r, g, b)


def proximite_couleurs(a: dict, b: dict) -> float:
    """0 (très différentes) à 1 (même ambiance), sur la couleur dominante et la luminosité."""
    if not a.get("couleurs") or not b.get("couleurs"):
        return 0.5
    ha, sa, va = teinte(a["couleurs"][0]["hex"])
    hb, sb, vb = teinte(b["couleurs"][0]["hex"])
    dh = min(abs(ha - hb), 1 - abs(ha - hb)) * 2
    return float(max(0.0, 1 - (0.5 * dh * min(sa, sb) * 2 + 0.3 * abs(va - vb) + 0.2 * abs(sa - sb))))


# ---------------------------------------------------------------- Releases
def releases_banques() -> list[str]:
    r = subprocess.run(["gh", "release", "list", "--limit", "100", "--json", "tagName", "-q", ".[].tagName"],
                       capture_output=True, text=True)
    return [t for t in r.stdout.split() if t.startswith(PREFIXE) or t == "banque"]


def fichiers_release(tag: str) -> list[str]:
    r = subprocess.run(["gh", "release", "view", tag, "--json", "assets", "-q", ".assets[].name"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Release « {tag} » introuvable")
    return [n for n in r.stdout.split("\n") if n.lower().endswith(EXTENSIONS)]


def chemin_local(banque: str, nom: str) -> Path:
    """Télécharge (si besoin) une vidéo d'une banque et retourne son chemin."""
    d = DOSSIER / banque
    f = d / nom
    if not f.exists():
        d.mkdir(parents=True, exist_ok=True)
        subprocess.run(["gh", "release", "download", banque, "-p", nom, "-D", str(d), "--clobber"],
                       check=True, capture_output=True)
    return f


def _ancien_format(index: dict) -> dict:
    """data/banque.json de la 1ʳᵉ version ({fichier: fiche}) → {release: {fichier: fiche}}."""
    if index and all(isinstance(v, dict) and "duree" in v for v in index.values()):
        return {GENERALE: index}
    return index


def lire_index() -> dict:
    return _ancien_format(lire(BANQUE, {}))


def indexer(banque: str | None = None, dossier: Path | None = None) -> dict:
    index = lire_index()
    banques = [banque] if banque else releases_banques()
    if not banques:
        print("Aucune banque : lance le workflow « Installation » pour créer les Releases banque-…")
    for b in banques:
        deja = index.setdefault(b, {})
        if dossier:
            fichiers = [(f.name, f) for f in sorted(dossier.iterdir()) if f.suffix.lower() in EXTENSIONS]
        else:
            try:
                noms = [n for n in fichiers_release(b) if n not in deja]
            except RuntimeError as e:
                print(f"✘ {e}")
                continue
            fichiers = [(n, None) for n in noms]
        print(f"{b} : {len(fichiers)} nouvelle(s) vidéo(s)")
        for nom, f in fichiers:
            fiche = {"tags": tags_du_nom(nom), "ajoute_le": maintenant(), "type": type_banque(b)}
            if fiche["type"] == "reacts":
                art, streamer = infos_react(nom)
                if not art:
                    print(f"✘ {nom} : nom invalide pour un react (attendu : cle-artiste__streamer_….mp4) → ignorée")
                    continue
                fiche.update(artiste=art, streamer=streamer)
            elif fiche["type"] == "artiste":
                fiche["artiste"] = b[len(PREFIXE):]
            try:
                chemin = f or chemin_local(b, nom)
                fiche.update(analyser(chemin))
            except Exception as e:
                print(f"✘ {nom} : analyse impossible ({e})")
                continue
            if f:
                fiche["chemin"] = str(f)
            elif chemin.exists():
                chemin.unlink()  # on libère la place : la vidéo sera retéléchargée au montage si choisie
            deja[nom] = fiche
            print(f"✔ {nom} : {fiche['duree']} s, {fiche['orientation']}, lum {fiche['luminosite']}, "
                  f"mouvement {fiche['mouvement']}, visage {fiche['centre_visage']}, tags {fiche['tags']}"
                  + (f", react de {fiche['streamer']} sur {fiche['artiste']}" if fiche.get("streamer") else ""))
        # vidéos retirées de la Release : retirées de l'index
        if not dossier:
            try:
                presents = set(fichiers_release(b))
                for nom in [n for n in deja if n not in presents]:
                    del deja[nom]
                    print(f"– {nom} : retirée de la banque")
            except RuntimeError:
                pass
    ecrire(BANQUE, index)
    print("Banques : " + ", ".join(f"{b} {len(v)}" for b, v in index.items()))
    return index


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["indexer", "liste"])
    p.add_argument("--banque", default="")
    p.add_argument("--dossier", type=Path)
    a = p.parse_args()
    if a.action == "liste":
        print(json.dumps({b: sorted(v) for b, v in lire_index().items()}, ensure_ascii=False, indent=1))
    else:
        indexer(a.banque or None, a.dossier)
