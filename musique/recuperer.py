"""Ramener une vidéo à partir de son code (ex. M0012), même si elle a été supprimée.

- Encore sur GitHub : copiée dans la release « recuperees ».
- Sinon : refaite depuis la source (fichier de la Release « entrees ») avec le même passage, le même mode
  et le même texte, puis mise dans « recuperees ».
Usage : python -m musique.recuperer M0012
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .commun import CLIPS, ecrire, lire, maintenant

TAG = "recuperees"


def gh(*args, check=True) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(r.stderr[-400:])
    return r.stdout


def refaire(c: dict) -> Path:
    """Relance le programme sur le même passage (début/fin imposés)."""
    from . import run
    params = {"mode": c["mode"], "source": c["source"], "artiste": c["artiste"], "titre": c.get("titre_son", ""),
              "nb": "1", "duree": "", "texte": c.get("texte", "tout"), "texte_perso": c.get("texte_perso", ""),
              "paroles": c.get("paroles_fichier", ""), "debut": str(c["debut"]), "fin": str(c["fin"]),
              "visuels": c.get("visuels") or "", "clip": c.get("clip", ""), "tags": c.get("tags", ""),
              "react": (c.get("react") or {}).get("nom", ""), "demo": False}
    run.etape_recherche(params)
    run.etape_montage()
    etat = run.charger_etat()
    if not etat.get("prets"):
        raise RuntimeError("impossible de refaire la vidéo (voir le journal ci-dessus)")
    return Path(etat["prets"][0]["chemin"])


def main(code: str) -> None:
    code = code.strip().upper()
    clips = lire(CLIPS, [])
    c = next((x for x in clips if x.get("code") == code), None)
    if not c:
        sys.exit(f"Code {code} introuvable")
    if subprocess.run(["gh", "release", "view", TAG], capture_output=True).returncode != 0:
        gh("release", "create", TAG, "--title", "Vidéos récupérées", "--notes", "Vidéos ramenées à la demande (par code).")
    nom = f"{code}_{c['artiste']}.mp4"
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        v = c.get("video") or {}
        ok = v.get("type") == "release" and subprocess.run(
            ["gh", "release", "download", v["tag"], "-p", v["nom"], "-D", str(d)], capture_output=True).returncode == 0
        if ok:
            (d / v["nom"]).rename(d / nom)
            print(f"{code} : copiée depuis GitHub")
        else:
            print(f"{code} : vidéo supprimée, je la refais depuis la source…")
            shutil.move(str(refaire(c)), str(d / nom))
        gh("release", "upload", TAG, str(d / nom), "--clobber")
    c["recuperee_le"] = maintenant()
    ecrire(CLIPS, clips)
    print(f"PRÊT : release « {TAG} », fichier {nom}")


if __name__ == "__main__":
    main(sys.argv[1])
