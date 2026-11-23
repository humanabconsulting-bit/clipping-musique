"""Contrôles avant stockage et avant publication.

Au montage  : pas de son → rejet ; vidéo trop courte → rejet ; nudité certaine → bloquée, doute → à vérifier.
À la publication : l'artiste DOIT avoir `accord: true` dans config/reglages.json, sinon publication refusée.
"""
from __future__ import annotations

from pathlib import Path

from . import montage


def son_et_duree(video: Path, duree_min: float) -> list[str]:
    """Liste des problèmes bloquants (vide = OK)."""
    pb = []
    info = montage.infos_video(video)
    if not info["son"]:
        pb.append("pas de piste son")
    else:
        vol = montage.volume_max(video)
        silence = montage.plus_long_silence(video)
        if vol < -35 or silence >= 8:
            pb.append(f"pas de son ({silence:.0f} s sans son, volume max {vol:.0f} dB)")
    if info["duree"] < duree_min - 0.5:
        pb.append(f"trop courte ({info['duree']:.1f} s < {duree_min:.0f} s)")
    if (info["largeur"], info["hauteur"]) != (montage.LARGEUR, montage.HAUTEUR):
        pb.append(f"mauvais format {info['largeur']}×{info['hauteur']}")
    return pb


def nudite(video: Path, log=print) -> dict:
    try:
        from . import nudite as nd
        r = nd.analyser(video)
        if r["nudite"]:
            log(f"   ⚠ nudité certaine ({r['images']} image(s)) → jamais publiée", "alerte")
        elif r["doute"]:
            log(f"   ? nudité possible ({r['images']} image(s)) → à vérifier à l'œil avant publication", "alerte")
        return {"nudite": r["nudite"], "nudite_doute": r["doute"], "nudite_images": r["images"],
                "nudite_secondes": r["secondes"]}
    except Exception as e:
        log(f"   vérification nudité impossible ({e}) → à vérifier à l'œil", "alerte")
        return {"nudite": False, "nudite_doute": True, "nudite_images": 0, "nudite_secondes": []}


def publiable(c: dict, fiche: dict, decision: dict) -> list[str]:
    """Raisons qui empêchent la publication (vide = publiable)."""
    pb = []
    if fiche.get("accord") is not True:
        pb.append(f"pas d'accord de l'artiste {fiche.get('nom', '?')} (accord ≠ true dans les réglages)")
    if c.get("nudite"):
        pb.append("nudité certaine")
    if c.get("nudite_doute") and not decision.get("nudite_ok"):
        pb.append("nudité possible, pas encore vérifiée")
    if (c.get("silence_max") or 0) >= 8:
        pb.append("passage muet")
    if c.get("visuels_autorises") is False:
        pb.append("visuels non autorisés")
    return pb
