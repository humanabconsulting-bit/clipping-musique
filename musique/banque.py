"""Banque de vidéos lifestyle : index des plans disponibles (data/banque.json).

Les vidéos sont déposées dans la Release GitHub `banque` (glisser-déposer sur github.com).
Le nom du fichier donne les tags : `voiture_nuit_ville.mp4` → ["voiture", "nuit", "ville"].

Usage :
  python -m musique.banque indexer            # télécharge les nouvelles vidéos de la Release et les analyse
  python -m musique.banque indexer --dossier D # analyse les vidéos d'un dossier (test)
Pour chaque vidéo : durée, orientation, luminosité, couleurs dominantes, score de mouvement, tags.
"""
from __future__ import annotations

import argparse
import colorsys
import re
import subprocess
from pathlib import Path

import numpy as np

from .commun import BANQUE, TRAVAIL, ecrire, lire, maintenant
from . import montage

TAG = "banque"
DOSSIER = TRAVAIL / "banque"
EXTENSIONS = (".mp4", ".mov", ".m4v", ".webm", ".mkv")


def tags_du_nom(nom: str) -> list[str]:
    base = Path(nom).stem.lower()
    return [t for t in re.split(r"[_\-\s.]+", base) if t and not t.isdigit() and len(t) > 1]


def analyser(video: Path) -> dict:
    """Mesures d'un plan (10 images réparties sur la durée)."""
    import cv2
    info = montage.infos_video(video)
    cap = cv2.VideoCapture(str(video))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    lum, mouv, pixels = [], [], []
    for k in range(10):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(max(n - 3, 1) * (k + 0.5) / 10))
        ok1, a = cap.read()
        ok2, b = cap.read()
        if not ok1:
            continue
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
        # 0 = plan fixe, 1 = très agité (différence moyenne entre 2 images × 25, plafonnée)
        "mouvement": round(min(1.0, float(np.mean(mouv)) * 25) if mouv else 0.0, 3),
        "couleurs": couleurs,
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


def telecharger_release(dossier: Path, deja: set[str]) -> list[Path]:
    dossier.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["gh", "release", "view", TAG, "--json", "assets", "-q", ".assets[].name"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("Release « banque » introuvable : crée-la sur GitHub et dépose les vidéos dedans")
    noms = [n for n in r.stdout.split("\n") if n.lower().endswith(EXTENSIONS) and n not in deja]
    for n in noms:
        subprocess.run(["gh", "release", "download", TAG, "-p", n, "-D", str(dossier), "--clobber"],
                       check=True, capture_output=True)
    return [dossier / n for n in noms]


def chemin_local(nom: str) -> Path:
    """Télécharge (si besoin) une vidéo de la banque et retourne son chemin."""
    f = DOSSIER / nom
    if not f.exists():
        DOSSIER.mkdir(parents=True, exist_ok=True)
        subprocess.run(["gh", "release", "download", TAG, "-p", nom, "-D", str(DOSSIER), "--clobber"],
                       check=True, capture_output=True)
    return f


def indexer(dossier: Path | None = None) -> dict:
    index = lire(BANQUE, {})
    if dossier:
        fichiers = [f for f in sorted(dossier.iterdir()) if f.suffix.lower() in EXTENSIONS]
    else:
        fichiers = telecharger_release(DOSSIER, set(index))
    for f in fichiers:
        try:
            fiche = analyser(f)
        except Exception as e:
            print(f"✘ {f.name} : analyse impossible ({e})")
            continue
        fiche.update(tags=tags_du_nom(f.name), ajoute_le=maintenant(),
                     source="dossier" if dossier else "release")
        if dossier:
            fiche["chemin"] = str(f)
        index[f.name] = fiche
        print(f"✔ {f.name} : {fiche['duree']} s, {fiche['orientation']}, lum {fiche['luminosite']}, "
              f"mouvement {fiche['mouvement']}, tags {fiche['tags']}")
    ecrire(BANQUE, index)
    print(f"Banque : {len(index)} vidéo(s) indexée(s)")
    return index


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["indexer"])
    p.add_argument("--dossier", type=Path)
    a = p.parse_args()
    indexer(a.dossier)
