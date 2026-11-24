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
    # 1) mots non reconnus ENTRE deux mots reconnus : répartis entre leurs voisins
    connus = [i for i, f in enumerate(fournis) if "debut" in f]
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
    # 2) les autres : horaire de leur ligne .lrc si on le connaît
    for f in fournis:
        if "debut" not in f and f["ligne_debut"] is not None:
            fin_l = (f["ligne_fin"] if f["ligne_fin"] is not None else f["ligne_debut"] + 3.0)
            pas = (fin_l - f["ligne_debut"]) / max(f["nb"], 1)
            f["debut"] = f["ligne_debut"] - decalage + f["rang"] * pas
            f["fin"] = f["debut"] + pas * 0.9
    if not any("debut" in f for f in fournis):
        return []
    sortie = [{"debut": round(f["debut"], 2), "fin": round(f["fin"], 2), "mot": f["mot"], "phrase": f["phrase"]}
              for f in fournis if "debut" in f and -0.2 <= f["debut"] < duree - 0.2]
    sortie.sort(key=lambda x: x["debut"])
    return sortie


# ---------------------------------------------------------------- paroles trouvées sur internet (gratuit)
def chercher_en_ligne(artiste: str, titre: str, dossier: Path, log=print) -> Path | None:
    """Son déjà sorti : cherche les paroles sur LRCLIB (base libre et gratuite, souvent avec les horaires
    ligne par ligne), puis lyrics.ovh. Retourne un fichier .lrc / .txt, ou None."""
    import requests
    if not (artiste and titre):
        return None
    dossier.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get("https://lrclib.net/api/search", params={"artist_name": artiste, "track_name": titre},
                         headers={"User-Agent": "clipping-musique (logiciel libre)"}, timeout=20)
        res = r.json() if r.ok else []
        res = sorted(res, key=lambda x: (not x.get("syncedLyrics"), not x.get("plainLyrics")))
        if res and (res[0].get("syncedLyrics") or res[0].get("plainLyrics")):
            synchro = bool(res[0].get("syncedLyrics"))
            f = dossier / ("paroles_lrclib" + (".lrc" if synchro else ".txt"))
            f.write_text(res[0].get("syncedLyrics") or res[0]["plainLyrics"], encoding="utf-8")
            log(f"   paroles trouvées sur LRCLIB ({'avec horaires' if synchro else 'texte seul'}) : "
                f"« {res[0].get('trackName')} » — {res[0].get('artistName')}")
            return f
    except Exception as e:
        log(f"   LRCLIB indisponible ({e})", "alerte")
    try:
        r = requests.get(f"https://api.lyrics.ovh/v1/{artiste}/{titre}", timeout=20)
        if r.ok and r.json().get("lyrics"):
            f = dossier / "paroles_lyricsovh.txt"
            f.write_text(r.json()["lyrics"], encoding="utf-8")
            log("   paroles trouvées sur lyrics.ovh (texte seul)")
            return f
    except Exception:
        pass
    log("   paroles introuvables en ligne (son pas encore sorti ?) : reconnaissance automatique")
    return None


def taux_accord(alignes: list[dict], reconnus: list[dict]) -> float:
    """Double vérification : part des mots reconnus par Whisper qu'on retrouve dans les paroles calées."""
    if not reconnus:
        return 0.0
    a = [_norm(w["mot"]) for w in alignes]
    b = [_norm(w["mot"]) for w in reconnus]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return sum(x.size for x in sm.get_matching_blocks()) / max(len(b), 1)


def corriger(mots: list[dict], corrections: dict) -> list[dict]:
    """Corrections notées une fois pour toutes (réglage `corrections`, général et par artiste) :
    {"refraiement": "rafraîchissement", "la fouine": "La Fouine"}."""
    if not corrections:
        return mots
    table = {_norm(k): v for k, v in corrections.items()}
    return [dict(w, mot=table.get(_norm(w["mot"]), w["mot"])) for w in mots]


def paroles_passage(audio_passage: Path, dossier: Path, cfg: dict, fichier_paroles: Path | None,
                    debut_dans_morceau: float, langue: str | None = None, log=print,
                    fiche: dict | None = None, titre: str = "") -> tuple[list[dict], str, str]:
    """Mots horodatés (relatifs au passage), langue, source utilisée.

    Ordre : 1) paroles fournies ; 2) paroles trouvées en ligne (son déjà sorti) ; 3) reconnaissance automatique
    améliorée (voix séparée, modèle plus précis, consigne avec le nom de l'artiste et son vocabulaire).
    Les paroles 1) et 2) sont VÉRIFIÉES contre ce qui est entendu (double vérification) avant d'être utilisées.
    """
    fiche = fiche or {}
    duree = montage.duree_video(audio_passage)
    source_audio = audio_passage
    origine = "whisper"
    if cfg.get("separer_voix", True):
        voix = separer_voix(audio_passage, dossier / "demucs")
        if voix:
            source_audio, origine = voix, "whisper+voix_separee"
            log("   voix séparée de la musique (Demucs)")
        else:
            log("   séparation de la voix indisponible : reconnaissance sur le morceau complet", "alerte")
    vocab = " ".join(cfg.get("vocabulaire", []) + fiche.get("vocabulaire", []))
    consigne = f"{fiche.get('nom', '')}. Rap français. {vocab}".strip()
    mots, langue_det = montage.transcrire(source_audio, cfg.get("modele_whisper_paroles", "large-v3-turbo"),
                                          langue or fiche.get("langue") or cfg.get("langue"), consigne,
                                          int(cfg.get("faisceau_whisper", 5)))
    corrections = {**cfg.get("corrections", {}), **fiche.get("corrections", {})}
    # 1) fichier fourni, 2) paroles en ligne
    sources = []
    if fichier_paroles and fichier_paroles.exists():
        sources.append(("fichier_paroles", fichier_paroles))
    elif cfg.get("paroles_en_ligne", True):
        f = chercher_en_ligne(fiche.get("nom", ""), titre, dossier, log)
        if f:
            sources.append(("paroles_en_ligne", f))
    for nom_source, f in sources:
        lignes = lire_paroles(f)
        if nom_source == "paroles_en_ligne":
            # les horaires en ligne sont ceux du son ENTIER : la vidéo peut n'en être qu'un extrait (ou un live)
            # → on ignore les horaires et on cherche le passage chanté dans tout le texte
            lignes = [{"debut": None, "texte": x["texte"]} for x in lignes]
        alignes = aligner(lignes, mots, duree, debut_dans_morceau)
        accord = taux_accord(alignes, mots) if alignes else 0.0
        if alignes and (nom_source == "fichier_paroles" or accord >= 0.35):
            log(f"   double vérification : {int(accord * 100)} % des mots entendus correspondent aux paroles")
            return corriger(alignes, corrections), langue_det, nom_source
        log(f"   paroles {nom_source} écartées : elles ne correspondent pas à ce qui est chanté "
            f"({int(accord * 100)} % seulement)", "alerte")
    # 3) reconnaissance automatique : on cache les mots trop incertains plutôt que d'afficher une faute
    seuil = float(cfg.get("seuil_mots_douteux", 0.3))
    douteux = [w for w in mots if w.get("proba", 1) < seuil]
    if douteux and cfg.get("masquer_mots_douteux", True):
        log(f"   {len(douteux)} mot(s) trop incertain(s) caché(s) : " + ", ".join(w["mot"] for w in douteux[:8]))
        mots = [w for w in mots if w.get("proba", 1) >= seuil]
    return corriger(mots, corrections), langue_det, origine
