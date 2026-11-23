"""Détection de nudité (gratuite, NudeNet, sur le processeur) : TikTok et YouTube interdisent la nudité,
même dans un jeu vidéo. Une vidéo signalée n'est jamais publiée automatiquement.

Usage : python -m musique.nudite fichier1.mp4 [fichier2.mp4 …]
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

INTERDIT = {"FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED", "MALE_GENITALIA_EXPOSED",
            "BUTTOCKS_EXPOSED", "ANUS_EXPOSED"}
SEUIL = 0.45          # confiance minimale d'une détection
IMAGES_DOUTE = 2      # 2 à 4 images signalées : doute → Claude regarde les images à la synchro, puis débloque ou bloque
IMAGES_SUR = 5        # 5 images ou plus (ou une détection très nette) : nudité certaine → bloquée
SCORE_SUR = 0.70
PAS = 1.0             # une image analysée chaque seconde

_detecteur = None


def analyser(video: Path) -> dict:
    """Retourne {"nudite": bool, "images": n, "details": [(seconde, label, score), …]}."""
    global _detecteur
    from nudenet import NudeDetector
    _detecteur = _detecteur or NudeDetector()
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(video), "-vf", f"fps={1 / PAS},scale=640:-2",
                        f"{tmp}/i_%04d.jpg"], check=True)
        details = []
        for img in sorted(Path(tmp).glob("i_*.jpg")):
            sec = (int(img.stem.split("_")[1]) - 1) * PAS
            for d in _detecteur.detect(str(img)):
                if d["class"] in INTERDIT and d["score"] >= SEUIL:
                    details.append((sec, d["class"], round(d["score"], 2)))
    images = len({s for s, _, _ in details})
    nette = any(sc >= SCORE_SUR for _, _, sc in details)
    niveau = "sur" if images >= IMAGES_SUR or nette else "doute" if images >= IMAGES_DOUTE else "non"
    return {"nudite": niveau == "sur", "doute": niveau == "doute", "niveau": niveau, "images": images,
            "secondes": sorted({s for s, _, _ in details})[:6], "details": details[:10]}


if __name__ == "__main__":
    for f in sys.argv[1:]:
        r = analyser(Path(f))
        print(f"NUDITE {r['niveau']} {r['images']} image(s) {Path(f).name} {r['details'][:4]}")
