"""Hébergement public TEMPORAIRE des vidéos pour que Buffer puisse les lire (repris de clipping-auto/cloud.py).

Dépôt GitHub public tampon (réglage `depot_public`, release `media`), partagé avec le programme stream :
les fichiers de ce programme sont préfixés `musique-` (ex. `musique-M0012.mp4`) pour ne jamais toucher
à ceux du stream. Une vidéo n'y est déposée que quelques heures avant son créneau et retirée dès que
Buffer l'a publiée. Secret : PUBLIC_REPO_TOKEN (écriture sur ce dépôt public seulement).
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

import requests

from .commun import reglages

TAG_PUBLIC = "media"


def _nom(code: str) -> str:
    prefixe = reglages().get("prefixe_public", "musique-")
    return f"{prefixe}{code}.mp4"


def _depot_public() -> tuple[str, dict]:
    depot = reglages().get("depot_public", "")
    jeton = os.environ.get("PUBLIC_REPO_TOKEN", "").strip()
    if not depot or not jeton:
        raise RuntimeError("dépôt public non configuré (réglage depot_public ou secret PUBLIC_REPO_TOKEN manquant)")
    return depot, {"Authorization": f"Bearer {jeton}", "Accept": "application/vnd.github+json"}


def _release_publique() -> tuple[str, dict, dict]:
    depot, h = _depot_public()
    r = requests.get(f"https://api.github.com/repos/{depot}/releases/tags/{TAG_PUBLIC}", headers=h, timeout=60)
    if r.status_code == 404:
        r = requests.post(f"https://api.github.com/repos/{depot}/releases", headers=h, timeout=60,
                          json={"tag_name": TAG_PUBLIC, "name": TAG_PUBLIC, "body": ""})
        if r.status_code == 422:  # dépôt vide : il faut un premier fichier avant de créer la release
            requests.put(f"https://api.github.com/repos/{depot}/contents/README.md", headers=h, timeout=60,
                         json={"message": "init", "content": base64.b64encode(b"media\n").decode()})
            r = requests.post(f"https://api.github.com/repos/{depot}/releases", headers=h, timeout=60,
                              json={"tag_name": TAG_PUBLIC, "name": TAG_PUBLIC, "body": ""})
    r.raise_for_status()
    return depot, h, r.json()


def _assets(depot: str, h: dict, rel: dict) -> list[dict]:
    """Tous les fichiers de la release (la réponse de base est limitée à 30)."""
    out, page = [], 1
    while True:
        r = requests.get(f"https://api.github.com/repos/{depot}/releases/{rel['id']}/assets",
                         headers=h, params={"per_page": 100, "page": page}, timeout=60)
        r.raise_for_status()
        out += r.json()
        if len(r.json()) < 100:
            return out
        page += 1


def envoyer(fichier: Path, code: str) -> str:
    """Dépose la vidéo et retourne son lien public direct."""
    depot, h, rel = _release_publique()
    nom = _nom(code)
    for a in _assets(depot, h, rel):
        if a["name"] == nom:
            requests.delete(a["url"], headers=h, timeout=60)
    with open(fichier, "rb") as f:
        r = requests.post(f"https://uploads.github.com/repos/{depot}/releases/{rel['id']}/assets",
                          params={"name": nom}, headers={**h, "Content-Type": "video/mp4"}, data=f, timeout=900)
    if not r.ok:
        raise RuntimeError(f"GitHub (dépôt public) a refusé l'envoi : {r.status_code} {r.text[:200]}")
    return r.json()["browser_download_url"]


def supprimer(code: str) -> bool:
    depot, h, rel = _release_publique()
    ok = True
    for a in _assets(depot, h, rel):
        if a["name"] == _nom(code):
            ok = requests.delete(a["url"], headers=h, timeout=60).status_code in (204, 404)
    return ok


def lister() -> list[str]:
    """Fichiers de CE programme encore en ligne (jamais ceux du stream)."""
    depot, h, rel = _release_publique()
    prefixe = reglages().get("prefixe_public", "musique-")
    return [a["name"] for a in _assets(depot, h, rel) if a["name"].startswith(prefixe)]


def verifier_lien(url: str) -> bool:
    r = requests.head(url, timeout=60, allow_redirects=True)
    return r.status_code == 200
