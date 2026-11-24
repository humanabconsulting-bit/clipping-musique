"""Montage « en rythme » pour les modes `son` et `lifestyle` : des plans coupés sur les mesures,
recadrés en 9:16 plein écran, avec de légers zooms (option), et le son du passage par-dessus.

Cadence des coupes selon l'énergie de la mesure : forte → toutes les mesures, moyenne → toutes les
2 mesures, faible → toutes les 4 mesures.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from . import montage
from .analyse_audio import mesures
from .montage import HAUTEUR, IPS, LARGEUR, executer


def coupes(analyse: dict, debut: float, fin: float) -> list[tuple[float, float, float]]:
    """Segments (debut, fin, energie) RELATIFS au passage, calés sur les mesures."""
    bornes = [t for t in mesures(analyse) if debut - 0.05 <= t <= fin + 0.05]
    if not bornes or bornes[0] > debut + 0.05:
        bornes = [debut] + bornes
    if bornes[-1] < fin - 0.3:
        bornes.append(fin)
    else:
        bornes[-1] = fin
    beats, ener = analyse["beats"], analyse["energie"]

    def energie(a, b):
        v = [ener[i] for i, t in enumerate(beats) if a <= t < b]
        return float(np.mean(v)) if v else 0.5

    segs = []
    i = 0
    while i < len(bornes) - 1:
        e = energie(bornes[i], bornes[min(i + 1, len(bornes) - 1)])
        pas = 1 if e >= 0.66 else 2 if e >= 0.33 else 4
        j = min(i + pas, len(bornes) - 1)
        if bornes[j] - bornes[i] < 1.2 and j < len(bornes) - 1:  # tempo très rapide : au moins 1,2 s par plan
            j += 1
        segs.append((round(bornes[i] - debut, 3), round(bornes[j] - debut, 3), round(energie(bornes[i], bornes[j]), 2)))
        i = j
    return segs


def rendre_segment(source: Path, depart: float, nb_images: int, sortie: Path, zoom: bool, sens: int,
                   centre: float | None = None, largeur: int = LARGEUR, hauteur: int = HAUTEUR) -> Path:
    """Un plan recadré plein écran 1080×1920, sans son, exactement `nb_images` images.
    `centre` : position habituelle du visage (0–1) → le recadrage 9:16 se centre dessus (reacts, anciens clips)."""
    x = f"min(max(iw*{centre:.3f}-{largeur // 2},0),iw-{largeur})" if centre is not None else f"(iw-{largeur})/2"
    fill = (f"scale={largeur}:{hauteur}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={largeur}:{hauteur}:'{x}':'(ih-{hauteur})/2',setsar=1,fps={IPS}")
    if zoom:
        z = f"1+0.06*on/{max(nb_images, 1)}" if sens > 0 else f"1.06-0.06*on/{max(nb_images, 1)}"
        fill += (f",zoompan=z='{z}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={largeur}x{hauteur}:fps={IPS}")
    # -stream_loop : si le plan est trop court, il reboucle au lieu de figer
    executer(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-ss", f"{depart:.3f}", "-i", str(source),
              "-vf", fill, "-frames:v", str(nb_images), "-an", "-c:v", "libx264", "-preset", "veryfast",
              "-crf", "18", "-pix_fmt", "yuv420p", str(sortie)])
    return sortie


def images_sur_le_beat(choix: list[dict], chemins: list[Path], segs: list[tuple[float, float, float]],
                       dossier: Path, zoom: bool = True, largeur: int = LARGEUR, hauteur: int = HAUTEUR) -> Path:
    """Vidéo muette des plans coupés sur les mesures (taille largeur × hauteur)."""
    dossier.mkdir(parents=True, exist_ok=True)
    morceaux = []
    for k, ((a, b, _), c, src) in enumerate(zip(segs, choix, chemins)):
        nb = int(round(b * IPS)) - int(round(a * IPS))  # cumul exact : pas de décalage avec le beat
        if nb <= 0:
            continue
        morceaux.append(rendre_segment(src, c["depart"], nb, dossier / f"seg{k:03d}.mp4", zoom, 1 if k % 2 == 0 else -1,
                                       c["plan"].get("centre_visage"), largeur, hauteur))
    liste = dossier / "liste.txt"
    liste.write_text("".join(f"file '{m.resolve()}'\n" for m in morceaux), encoding="utf-8")
    images = dossier / "images.mp4"
    executer(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(liste), "-c", "copy",
              str(images)])
    return images


def monter(choix: list[dict], chemins: list[Path], segs: list[tuple[float, float, float]], audio: Path,
           ass: Path, sortie: Path, dossier: Path, zoom: bool = True) -> Path:
    images = images_sur_le_beat(choix, chemins, segs, dossier, zoom)
    duree = segs[-1][1]
    executer(["ffmpeg", "-y", "-loglevel", "error", "-i", str(images), "-i", str(audio),
              "-filter_complex", f"[0:v]subtitles='{montage.chemin_ass(ass)}'[v]", "-map", "[v]", "-map", "1:a",
              "-t", f"{duree:.3f}", "-af", "afade=t=out:st=" + f"{max(duree - 0.4, 0):.2f}" + ":d=0.4",
              *montage.options_encodage(duree), str(sortie)])
    return sortie
