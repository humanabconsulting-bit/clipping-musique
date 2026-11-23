"""Paroles mot par mot pour les sous-titres karaoké.

Trois sources, de la plus fiable à la moins fiable :
1. un fichier de paroles fourni (.lrc avec horaires par ligne, ou .txt) → ALIGNÉ sur l'audio :
   on reconnaît les mots avec Whisper puis on cale le texte fourni dessus (alignement de séquences,
   gratuit, sans modèle en plus) ; les mots non reconnus sont placés entre leurs voisins ;
2. Whisper (faster-whisper, modèle `medium` par défaut pour la musique) sur la VOIX SEULE
   si Demucs est activé (réglage `separer_voix`, plus lent) ;
3. Whisper directement sur le morceau.
Les rappeurs mélangent français, anglais et darija : langue détectée automatiquement.
"""
from __future__ import annotations

import difflib
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

from . import montage


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", (t or "").lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"[^\w]", "", t)


# ---------------------------------------------------------------- séparation de la voix (option)
def separer_voix(audio: Path, dossier: Path) -> Path | None:
    """Voix seule avec Demucs (htdemucs, processeur). Retourne None si Demucs n'est pas installé."""
    try:
        import demucs  # noqa: F401
    except ImportError:
        return None
    dossier.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([sys.executable, "-m", "demucs", "--two-stems", "vocals", "-n", "htdemucs", "-d", "cpu",
                        "-o", str(dossier), str(audio)], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    trouves = list(dossier.rglob("vocals.wav"))
    return trouves[0] if trouves else None


# ---------------------------------------------------------------- fichiers de paroles
def lire_paroles(chemin: Path) -> list[dict]:
    """Lignes {debut (s ou None), texte}. Accepte .lrc ([mm:ss.xx] texte) et .txt (une ligne par vers)."""
    lignes = []
    for brut in chemin.read_text(encoding="utf-8", errors="ignore").splitlines():
        brut = brut.strip()
        if not brut or re.match(r"^\[(ar|ti|al|by|offset|length|re|ve):", brut, re.I):
            continue
        temps = re.findall(r"\[(\d+):(\d+(?:[.,]\d+)?)\]", brut)
        texte = re.sub(r"\[[^\]]*\]", "", brut).strip()
        if not texte:
            continue
        if temps:
            for mm, ss in temps:
                lignes.append({"debut": int(mm) * 60 + float(ss.replace(",", ".")), "texte": texte})
        else:
            lignes.append({"debut": None, "texte": texte})
    lignes.sort(key=lambda x: (x["debut"] is None, x["debut"] or 0))
    return lignes


def aligner(lignes: list[dict], reconnus: list[dict], duree: float, decalage: float = 0.0) -> list[dict]:
    """Cale les mots des paroles fournies sur les mots reconnus par Whisper.

    lignes   : paroles fournies (horaires .lrc relatifs au MORCEAU entier)
    reconnus : mots Whisper horodatés (relatifs au PASSAGE)
    decalage : début du passage dans le morceau (pour ramener les horaires .lrc au passage)
    """
    fournis = []
    for k, li in enumerate(lignes):
        fin_ligne = lignes[k + 1]["debut"] if k + 1 < len(lignes) and lignes[k + 1]["debut"] is not None else None
        for j, m in enumerate(li["texte"].split()):
            fournis.append({"mot": m, "phrase": j == 0, "ligne_debut": li["debut"], "ligne_fin": fin_ligne,
                            "rang": j, "nb": len(li["texte"].split())})
    # .lrc : on ne garde que les lignes du passage (avec 2 s de marge)
    if any(f["ligne_debut"] is not None for f in fournis):
        fournis = [f for f in fournis if f["ligne_debut"] is None
                   or (decalage - 2 <= f["ligne_debut"] <= decalage + duree + 2)]
    a = [_norm(f["mot"]) for f in fournis]
    b = [_norm(w["mot"]) for w in reconnus]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for bloc in sm.get_matching_blocks():
        for k in range(bloc.size):
            f, w = fournis[bloc.a + k], reconnus[bloc.b + k]
            f["debut"], f["fin"] = w["debut"], w["fin"]
    # mots non reconnus : horaire de la ligne .lrc si connu, sinon entre les voisins reconnus
    for f in fournis:
        if "debut" not in f and f["ligne_debut"] is not None:
            fin_l = (f["ligne_fin"] if f["ligne_fin"] is not None else f["ligne_debut"] + 3.0)
            pas = (fin_l - f["ligne_debut"]) / max(f["nb"], 1)
            f["debut"] = f["ligne_debut"] - decalage + f["rang"] * pas
            f["fin"] = f["debut"] + pas * 0.9
    connus = [i for i, f in enumerate(fournis) if "debut" in f]
    if not connus:
        return []
    for i, f in enumerate(fournis):
        if "debut" in f:
            continue
        avant = max([k for k in connus if k < i], default=None)
        apres = min([k for k in connus if k > i], default=None)
        if avant is None or apres is None:
            continue  # avant le premier / après le dernier mot reconnu : hors du passage
        t0, t1 = fournis[avant]["fin"], fournis[apres]["debut"]
        pas = max(t1 - t0, 0.05) / (apres - avant)
        f["debut"] = t0 + (i - avant - 0.5) * pas
        f["fin"] = f["debut"] + pas * 0.9
    sortie = [{"debut": round(f["debut"], 2), "fin": round(f["fin"], 2), "mot": f["mot"], "phrase": f["phrase"]}
              for f in fournis if "debut" in f and -0.2 <= f["debut"] <= duree]
    sortie.sort(key=lambda x: x["debut"])
    return sortie


def paroles_passage(audio_passage: Path, dossier: Path, cfg: dict, fichier_paroles: Path | None,
                    debut_dans_morceau: float, langue: str | None = None, log=print) -> tuple[list[dict], str, str]:
    """Mots horodatés (relatifs au passage), langue, source utilisée."""
    duree = montage.duree_video(audio_passage)
    source_audio = audio_passage
    origine = "whisper"
    if cfg.get("separer_voix"):
        voix = separer_voix(audio_passage, dossier / "demucs")
        if voix:
            source_audio, origine = voix, "whisper+demucs"
            log("   voix séparée avec Demucs")
        else:
            log("   Demucs indisponible : transcription sur le morceau complet", "alerte")
    mots, langue_det = montage.transcrire(source_audio, cfg.get("modele_whisper_paroles", "medium"),
                                          langue or cfg.get("langue"))
    if fichier_paroles and fichier_paroles.exists():
        alignes = aligner(lire_paroles(fichier_paroles), mots, duree, debut_dans_morceau)
        if alignes:
            return alignes, langue_det, "fichier_paroles"
        log("   paroles fournies impossibles à caler sur ce passage : transcription Whisper gardée", "alerte")
    return mots, langue_det, origine
