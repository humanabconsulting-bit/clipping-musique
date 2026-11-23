"""Recadrage 9:16 qui suit le visage du rappeur (gratuit : PySceneDetect + MediaPipe, sur le processeur).

1. Changements de plan détectés avec PySceneDetect.
2. Dans chaque plan, visages détectés 5 fois par seconde (MediaPipe ; OpenCV en secours) ;
   on suit le visage principal (le plus grand).
3. Position lissée (pas de saccades), recalée à chaque changement de plan, transmise à ffmpeg
   (filtre `crop` piloté par `sendcmd`).
Si presque aucun visage n'est trouvé : vidéo centrée sur fond flou (mode du stream).
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

import numpy as np

MODELE_URL = ("https://storage.googleapis.com/mediapipe-models/face_detector/"
              "blaze_face_short_range/float16/latest/blaze_face_short_range.tflite")
MODELE = Path.home() / ".cache" / "clipping-musique" / "blaze_face_short_range.tflite"
ECHANTILLONS_PAR_S = 5


def plans(video: Path, debut: float, fin: float) -> list[float]:
    """Instants (relatifs au passage) des changements de plan."""
    try:
        from scenedetect import ContentDetector, detect
        scenes = detect(str(video), ContentDetector(threshold=27.0), start_time=debut, end_time=fin)
        return [round(s[0].get_seconds() - debut, 2) for s in scenes[1:]]
    except Exception:
        return []


class _Detecteur:
    def __init__(self):
        self.mp = None
        self.haar = None
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mpt
            from mediapipe.tasks.python import vision
            if not MODELE.exists():
                MODELE.parent.mkdir(parents=True, exist_ok=True)
                urllib.request.urlretrieve(MODELE_URL, MODELE)
            opts = vision.FaceDetectorOptions(base_options=mpt.BaseOptions(model_asset_path=str(MODELE)),
                                              min_detection_confidence=0.5)
            self.mp = (mp, vision.FaceDetector.create_from_options(opts))
        except Exception:
            self.mp = None
        try:
            import cv2
            self.haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        except Exception:
            self.haar = None

    def visages(self, img_bgr) -> list[tuple[float, float, float, float]]:
        """[(cx, cy, w, h)] en pixels."""
        import cv2
        h, w = img_bgr.shape[:2]
        res = []
        if self.mp:
            mp, det = self.mp
            # le modèle « courte distance » voit mieux les visages sur une image réduite et carrée-ish
            img = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
            r = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=img))
            for d in r.detections:
                b = d.bounding_box
                res.append((b.origin_x + b.width / 2, b.origin_y + b.height / 2, b.width, b.height))
        if not res and self.haar is not None:
            gris = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
            for (x, y, fw, fh) in self.haar.detectMultiScale(gris, 1.1, 6, minSize=(int(h * 0.08), int(h * 0.08))):
                res.append((x + fw / 2, y + fh / 2, fw, fh))
        return res


def trajectoire(video: Path, debut: float, duree: float) -> dict:
    """Positions horizontales du centre de recadrage, échantillonnées 5×/s, lissées par plan.

    Retour : {"largeur", "hauteur", "crop_l", "temps": [...], "x": [...], "taux_visages", "plans": [...]}.
    """
    import cv2
    cap = cv2.VideoCapture(str(video))
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    ips = cap.get(cv2.CAP_PROP_FPS) or 30
    crop_l = min(W, int(round(H * 9 / 16 / 2)) * 2)
    det = _Detecteur()
    temps, centres = [], []
    cap.set(cv2.CAP_PROP_POS_MSEC, debut * 1000)
    pas = max(1, int(round(ips / ECHANTILLONS_PAR_S)))
    k = 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000 - debut
        if t > duree:
            break
        if k % pas == 0:
            # analyse sur une image réduite (plus rapide)
            echelle = 640 / max(W, 1)
            petite = cv2.resize(img, (640, int(H * echelle))) if W > 640 else img
            vs = det.visages(petite)
            if vs:
                cx, cy, fw, fh = max(vs, key=lambda v: v[2] * v[3])
                centres.append(cx / (echelle if W > 640 else 1))
            else:
                centres.append(None)
            temps.append(max(t, 0.0))
        k += 1
    cap.release()
    coupes = plans(video, debut, debut + duree)
    taux = sum(1 for c in centres if c is not None) / max(len(centres), 1)
    xs = _lisser_par_plan(temps, centres, coupes, W, crop_l)
    return {"largeur": W, "hauteur": H, "crop_l": crop_l, "temps": temps, "x": xs,
            "taux_visages": round(taux, 2), "plans": coupes}


def _lisser_par_plan(temps: list[float], centres: list, coupes: list[float], W: int, crop_l: int) -> list[int]:
    """Bouche les trous, lisse dans chaque plan (moyenne glissante ~1 s), saute net aux changements de plan."""
    n = len(temps)
    if n == 0:
        return []
    bornes = [0.0] + list(coupes) + [1e9]
    xs = [0.0] * n
    for p in range(len(bornes) - 1):
        idx = [i for i in range(n) if bornes[p] <= temps[i] < bornes[p + 1]]
        if not idx:
            continue
        vals = [centres[i] for i in idx]
        connus = [v for v in vals if v is not None]
        if not connus:
            vals = [W / 2] * len(vals)
        else:
            # trous : dernière position connue (ou la première du plan)
            der = connus[0]
            for j, v in enumerate(vals):
                if v is None:
                    vals[j] = der
                else:
                    der = v
        arr = np.array(vals, dtype=float)
        # médiane puis moyenne glissante : supprime les sauts parasites, mouvement doux
        if len(arr) >= 5:
            arr = np.array([np.median(arr[max(0, j - 2):j + 3]) for j in range(len(arr))])
        fen = min(len(arr), ECHANTILLONS_PAR_S)
        if fen > 1:
            arr = np.convolve(np.pad(arr, (fen // 2, fen - 1 - fen // 2), mode="edge"), np.ones(fen) / fen, mode="valid")
        # zone morte : on ne bouge pas pour moins de 4 % de la largeur (image stable)
        stable = arr[0]
        for j in range(len(arr)):
            if abs(arr[j] - stable) > W * 0.04:
                stable = stable + (arr[j] - stable) * 0.5
            arr[j] = stable
        for j, i in enumerate(idx):
            xs[i] = arr[j]
    return [int(min(max(x - crop_l / 2, 0), W - crop_l)) for x in xs]


def commandes(traj: dict, chemin: Path) -> Path:
    """Fichier sendcmd : position x du recadrage au fil du temps."""
    lignes = [f"{t:.2f} crop@suivi x {x};" for t, x in zip(traj["temps"], traj["x"])]
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return chemin


def filtre(traj: dict | None, cmd: Path | None, entree: str = "[0:v]", sortie: str = "[cadre]") -> str:
    """Filtre ffmpeg qui produit une image 1080×1920 (suivi du visage, ou fond flou en secours)."""
    from .montage import HAUTEUR, LARGEUR, chemin_ass, filtre_fond_flou
    if not traj or traj["largeur"] <= traj["crop_l"] or not traj["x"]:
        return filtre_fond_flou(entree, sortie)
    x0 = traj["x"][0]
    return (f"{entree}sendcmd=f='{chemin_ass(cmd)}',crop@suivi={traj['crop_l']}:{traj['hauteur']}:{x0}:0,"
            f"scale={LARGEUR}:{HAUTEUR}:flags=lanczos,setsar=1{sortie}")
