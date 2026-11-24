"""Déposer des fichiers dans un dossier (Release) du dépôt de données, sans rien faire à la main sur GitHub.

Sources acceptées :
- un lien WeTransfer (we.tl/… ou wetransfer.com/downloads/…) — le .zip est décompressé ;
- un lien Google Drive public (« Tous les utilisateurs disposant du lien ») : fichier ou dossier ;
- un lien Dropbox ;
- un lien direct vers un fichier ;
- sans lien : les fichiers poussés par Claude dans le dossier `a-deposer/<dossier>/` du dépôt de données
  (ils sont ensuite retirés de Git pour ne pas l'alourdir).
Le lien est donné à Claude dans le chat, qui l'écrit dans `a-deposer/<dossier>/lien.txt` (dépôt privé) :
il ne passe JAMAIS par un champ du workflow, car les journaux du dépôt public sont visibles par tous.

Les noms sont nettoyés (minuscules, sans accents ni espaces) et, pour `sons` / `entrees` / `banque-<artiste>`,
préfixés par la clé de l'artiste si elle manque (ex. « 1981 COLORS.mp4 » → « lafouine_1981-colors.mp4 »).

Usage : python -m musique.deposer --dossier banque-lafouine --artiste lafouine --lien "https://we.tl/t-XXXX"
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import unicodedata
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import requests

from .commun import DONNEES, TRAVAIL

EXTENSIONS = (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg",
              ".txt", ".lrc")
NAVIGATEUR = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0 Safari/537.36"}


def nom_propre(nom: str, artiste: str = "", dossier: str = "") -> str:
    p = Path(nom)
    base = unicodedata.normalize("NFKD", p.stem.lower())
    base = "".join(ch for ch in base if not unicodedata.combining(ch))
    base = re.sub(r"__+", "\0", base)                      # garde le « __ » des reacts
    base = re.sub(r"[^a-z0-9_\0]+", "-", base).strip("-_")
    base = base.replace("\0", "__")
    cle = (artiste or "").lower()
    if cle and dossier not in ("banque-reacts", "banque-generale") and not base.startswith(cle + "_"):
        base = f"{cle}_{base}"
    return f"{base or 'fichier'}{p.suffix.lower()}"


def _telecharger(url: str, dest: Path, session: requests.Session | None = None) -> Path:
    s = session or requests.Session()
    with s.get(url, stream=True, timeout=600, headers=NAVIGATEUR, allow_redirects=True) as r:
        r.raise_for_status()
        if dest.is_dir():
            cd = r.headers.get("content-disposition", "")
            m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', cd)
            nom = requests.utils.unquote(m.group(1)) if m else Path(urlparse(r.url).path).name or "fichier"
            dest = dest / nom
        with open(dest, "wb") as f:
            for bloc in r.iter_content(1 << 20):
                f.write(bloc)
    return dest


def wetransfer(url: str, dossier: Path) -> Path:
    """Lien WeTransfer → fichier téléchargé (souvent un .zip)."""
    s = requests.Session()
    s.headers.update(NAVIGATEUR)
    page = s.get(url, timeout=60, allow_redirects=True)
    finale = page.url
    parties = [x for x in urlparse(finale).path.split("/") if x]
    if "downloads" not in parties:
        raise RuntimeError("lien WeTransfer non reconnu")  # le lien n'est jamais affiché (journaux publics)
    ids = parties[parties.index("downloads") + 1:]
    if len(ids) < 2:
        raise RuntimeError("lien WeTransfer incomplet")
    transfert, hachage = ids[0], ids[-1]
    corps = {"security_hash": hachage, "intent": "entire_transfer"}
    if len(ids) == 3:
        corps["recipient_id"] = ids[1]
    entetes = {"x-requested-with": "XMLHttpRequest", "Content-Type": "application/json", "Origin": "https://wetransfer.com",
               "Referer": finale}
    m = re.search(r'name="csrf-token" content="([^"]+)"', page.text)
    if m:
        entetes["x-csrf-token"] = m.group(1)
    r = s.post(f"https://wetransfer.com/api/v4/transfers/{transfert}/download", json=corps, headers=entetes, timeout=60)
    lien = (r.json() if r.ok else {}).get("direct_link")
    if not lien:
        raise RuntimeError(f"WeTransfer a refusé le téléchargement ({r.status_code}). Le lien a peut-être expiré "
                           "(7 jours). Sinon : Google Drive en « Tous les utilisateurs disposant du lien ».")
    return _telecharger(lien, dossier, s)


def google_drive(url: str, dossier: Path) -> list[Path]:
    import gdown
    if "/folders/" in url:
        fichiers = gdown.download_folder(url=url, output=str(dossier), quiet=True, use_cookies=False) or []
        return [Path(f) for f in fichiers]
    f = gdown.download(url=url, output=str(dossier) + "/", quiet=True, fuzzy=True)
    if not f:
        raise RuntimeError("Google Drive : téléchargement impossible (le partage doit être « Tous les "
                           "utilisateurs disposant du lien »)")
    return [Path(f)]


def recuperer(lien: str, dossier: Path) -> list[Path]:
    dossier.mkdir(parents=True, exist_ok=True)
    hote = urlparse(lien).netloc.lower()
    if "we.tl" in hote or "wetransfer" in hote:
        fichiers = [wetransfer(lien, dossier)]
    elif "drive.google" in hote or "docs.google" in hote:
        fichiers = google_drive(lien, dossier)
    elif "dropbox" in hote:
        fichiers = [_telecharger(re.sub(r"dl=0", "dl=1", lien) if "dl=" in lien else lien + ("&" if "?" in lien else "?") + "dl=1",
                                 dossier)]
    else:
        fichiers = [_telecharger(lien, dossier)]
    sortie = []
    for f in fichiers:
        if f.suffix.lower() == ".zip" or zipfile.is_zipfile(f):
            with zipfile.ZipFile(f) as z:
                for info in z.infolist():
                    nom = Path(info.filename).name
                    if info.is_dir() or nom.startswith((".", "__MACOSX")) or "__MACOSX" in info.filename:
                        continue
                    cible = dossier / nom
                    with z.open(info) as src, open(cible, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    sortie.append(cible)
            f.unlink()
        else:
            sortie.append(f)
    return sortie


def deposer(fichiers: list[Path], release: str, artiste: str) -> list[str]:
    if subprocess.run(["gh", "release", "view", release], capture_output=True).returncode != 0:
        raise RuntimeError(f"le dossier « {release} » n'existe pas : lance « Installation » avec l'artiste pour le créer")
    deposes = []
    for f in fichiers:
        if f.suffix.lower() not in EXTENSIONS:
            print(f"– {f.name} : ignoré (type non pris en charge)")
            continue
        if f.stat().st_size > 1_900_000_000:
            print(f"✘ {f.name} : trop gros pour GitHub (plus de 2 Go)")
            continue
        propre = f.with_name(nom_propre(f.name, artiste, release))
        if propre != f:
            f.rename(propre)
        r = subprocess.run(["gh", "release", "upload", release, str(propre), "--clobber"], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"✘ {propre.name} : {r.stderr.strip()[-200:]}")
            continue
        deposes.append(propre.name)
        print(f"✔ {propre.name} ({propre.stat().st_size / 1e6:.1f} Mo) → {release}")
    return deposes


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dossier", required=True, help="sons | entrees | banque-generale | banque-reacts | banque-<artiste>")
    p.add_argument("--artiste", default="")
    p.add_argument("--lien", default="")
    a = p.parse_args()
    dossier = a.dossier.strip().lower()
    travail = TRAVAIL / "depot"
    if travail.exists():
        shutil.rmtree(travail)
    git = DONNEES / "a-deposer" / dossier
    # Le lien est écrit par Claude dans le dépôt PRIVÉ (a-deposer/<dossier>/lien.txt) : il n'apparaît jamais
    # dans les journaux publics des workflows (sinon n'importe qui pourrait télécharger les fichiers).
    lien = a.lien.strip()
    if not lien and (git / "lien.txt").exists():
        lien = (git / "lien.txt").read_text(encoding="utf-8").strip()
    if lien:
        print("::add-mask::" + lien)
        fichiers = recuperer(lien, travail)
    else:  # fichiers poussés par Claude dans le dépôt de données
        if not git.exists():
            print(f"Rien à déposer (ni lien, ni fichiers dans a-deposer/{dossier})")
            return 1
        travail.mkdir(parents=True)
        fichiers = []
        for f in sorted(git.iterdir()):
            if f.is_file() and f.name != "lien.txt":
                shutil.copy2(f, travail / f.name)
                fichiers.append(travail / f.name)
    print(f"{len(fichiers)} fichier(s) récupéré(s)")
    deposes = deposer(fichiers, dossier, a.artiste.strip())
    if git.exists() and deposes:
        shutil.rmtree(git)  # le workflow retire ensuite ces fichiers (et le lien) de Git
    print(f"Terminé : {len(deposes)} fichier(s) dans « {dossier} »")
    return 0 if deposes else 1


if __name__ == "__main__":
    sys.exit(main())
