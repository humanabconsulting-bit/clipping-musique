"""Récupération des fichiers d'entrée (vidéos, sons, paroles).

Ordre d'essai pour une source :
1. chemin d'un fichier qui existe déjà (test) ;
2. lien http(s) → téléchargement yt-dlp (YouTube bloque souvent les serveurs du cloud : message clair) ;
3. nom de fichier → téléchargé depuis la Release `sons` (morceaux) ou `entrees` (le reste) du dépôt de données.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from . import montage
from .commun import TRAVAIL

TAG = "entrees"
TAGS = ("sons", "entrees")   # les morceaux dans « sons », le reste (paroles, vidéos) dans « entrees »
DOSSIER = TRAVAIL / "entrees"


class EntreeIntrouvable(RuntimeError):
    pass


def lister() -> list[str]:
    noms = []
    for tag in TAGS:
        r = subprocess.run(["gh", "release", "view", tag, "--json", "assets", "-q", ".assets[].name"],
                           capture_output=True, text=True)
        noms += [n for n in r.stdout.split("\n") if n.strip()] if r.returncode == 0 else []
    return noms


def recuperer(source: str, nom_local: str | None = None) -> Path:
    source = (source or "").strip()
    if not source:
        raise EntreeIntrouvable("aucune source donnée")
    p = Path(source).expanduser()
    if p.exists():
        return p.resolve()
    DOSSIER.mkdir(parents=True, exist_ok=True)
    if source.startswith(("http://", "https://")):
        return montage.telecharger(source, DOSSIER / (nom_local or "source.mp4"))
    f = DOSSIER / source
    for tag in TAGS:
        subprocess.run(["gh", "release", "download", tag, "-p", source, "-D", str(DOSSIER), "--clobber"],
                       capture_output=True, text=True)
        if f.exists():
            return f
    if not f.exists():
        dispo = lister()
        proches = [n for n in dispo if source.lower().split(".")[0][:6] in n.lower()]
        raise EntreeIntrouvable(
            f"« {source} » introuvable dans les Releases « sons » et « entrees ». "
            + (f"Fichiers proches : {', '.join(proches[:5])}. " if proches else "")
            + (f"Fichiers disponibles : {', '.join(dispo[:15])}" if dispo else
               "La Release est vide ou n'existe pas : dépose le fichier dedans (glisser-déposer sur github.com)."))
    return f
