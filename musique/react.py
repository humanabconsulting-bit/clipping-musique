"""Mise en page « react » (mode `react`) :

    ┌──────────────────────┐
    │  streamer qui réagit │  1/3 haut (1080 × 640) : recadré sur sa caméra / son visage
    ├──── PAROLES ─────────┤  paroles karaoké au milieu, sur la jointure
    │  clip / vidéos de    │  2/3 bas (1080 × 1280) : clip de l'artiste, ses anciennes vidéos
    │  l'artiste, lifestyle│  et/ou la banque générale, coupés sur le beat
    └──────────────────────┘
Le son est celui du morceau (le son du react est coupé).

Règle : le react doit être un react sur l'artiste du son (n'importe lequel de ses sons) — fichier
`<cle-artiste>__<streamer>_….mp4` dans `banque-reacts`. Jamais un react sur un autre artiste (ça ferait
croire que le streamer a réagi à un son qu'il n'a pas écouté). Le streamer est crédité dans la légende.
"""
from __future__ import annotations

import random
from pathlib import Path

from . import montage
from .montage import IPS, LARGEUR, executer

H_HAUT = 640
H_BAS = 1920 - H_HAUT
Y_PAROLES_REACT = H_HAUT + 110       # centre des paroles : juste sous la jointure
Y_CREDIT_REACT = 1920 - 320 - 60     # crédit @artiste en bas, dans la zone sûre


class ReactRefuse(RuntimeError):
    pass


def cadre_camera(video: Path, depart: float, duree: float, echantillons: int = 9) -> tuple[int, int, int, int] | None:
    """Cadre (x, y, w, h) au format 1080:640 autour du visage du streamer (repris de detecter_camera du stream :
    un visage qui reste au même endroit = la caméra du streamer). None si aucun visage stable."""
    import cv2
    from .cadrage import _Detecteur
    cap = cv2.VideoCapture(str(video))
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = (cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) / (cap.get(cv2.CAP_PROP_FPS) or 30)
    det = _Detecteur()
    visages = []
    for k in range(echantillons):
        t = depart + duree * (k + 0.5) / echantillons
        if total:
            t = t % total
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, img = cap.read()
        if not ok:
            continue
        ech = 640 / max(W, 1)
        petite = cv2.resize(img, (640, int(H * ech)))
        for (cx, cy, fw, fh) in det.visages(petite):
            visages.append((cx / ech, cy / ech, fw / ech, fh / ech))
    cap.release()
    meilleur, groupe = None, []
    for v in visages:
        g = [u for u in visages if abs(u[0] - v[0]) < W * 0.05 and abs(u[1] - v[1]) < H * 0.06]
        if len(g) > len(groupe) or (len(g) == len(groupe) and meilleur and v[2] > meilleur[2]):
            meilleur, groupe = v, g
    if not meilleur or len(groupe) < max(3, echantillons // 3):
        return None
    cx = sum(u[0] for u in groupe) / len(groupe)
    cy = sum(u[1] for u in groupe) / len(groupe)
    fh = sum(u[3] for u in groupe) / len(groupe)
    ch = min(H, int(fh * 3.2))                     # tête + épaules
    cw = min(W, int(ch * LARGEUR / H_HAUT))
    ch = min(H, int(cw * H_HAUT / LARGEUR))
    x = int(min(max(cx - cw / 2, 0), W - cw))
    y = int(min(max(cy - ch * 0.45, 0), H - ch))
    return (x, y, cw - cw % 2, ch - ch % 2)


def choisir_react(plans_reacts: list[dict], duree: float, graine: str, impose: str = "") -> dict:
    if impose:
        p = next((p for p in plans_reacts if p["nom"] == impose), None)
        if not p:
            raise ReactRefuse(f"react « {impose} » absent de banque-reacts, ou pas sur cet artiste "
                              "(nom attendu : <cle-artiste>__<streamer>_….mp4)")
        return p
    if not plans_reacts:
        raise ReactRefuse("aucun react sur cet artiste dans banque-reacts (nom : <cle-artiste>__<streamer>_….mp4)")
    rng = random.Random(graine)
    longs = [p for p in plans_reacts if p.get("duree", 0) >= duree + 1] or plans_reacts
    return rng.choice(longs)


def monter(react_chemin: Path, react_depart: float, cadre: tuple | None, bas: Path, audio: Path, ass: Path,
           duree: float, sortie: Path) -> Path:
    """Assemble haut (react) + bas (images sur le beat) + paroles + son du morceau."""
    if cadre:
        x, y, w, h = cadre
        haut = f"[0:v]crop={w}:{h}:{x}:{y},scale={LARGEUR}:{H_HAUT}:flags=lanczos,setsar=1,fps={IPS}[haut]"
    else:  # pas de visage stable : le react entier, recadré au centre
        haut = (f"[0:v]scale={LARGEUR}:{H_HAUT}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={LARGEUR}:{H_HAUT},setsar=1,fps={IPS}[haut]")
    filtre = (f"{haut};[1:v]setsar=1,fps={IPS}[bas];[haut][bas]vstack=inputs=2,"
              f"drawbox=x=0:y={H_HAUT - 3}:w={LARGEUR}:h=6:color=black@0.9:t=fill,"
              f"{montage.sous_titres(ass)}[v]")
    executer(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-ss", f"{react_depart:.3f}",
              "-i", str(react_chemin), "-i", str(bas), "-i", str(audio),
              "-filter_complex", filtre, "-map", "[v]", "-map", "2:a", "-t", f"{duree:.3f}",
              "-af", f"afade=t=out:st={max(duree - 0.4, 0):.2f}:d=0.4",
              *montage.options_encodage(duree), str(sortie)])
    return sortie
