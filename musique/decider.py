"""Valider / rejeter des vidéos par leur code (en attendant le tableau de bord, ou depuis l'appli GitHub).

Usage : python -m musique.decider valider M0001 M0002
        python -m musique.decider rejeter M0003 --raison "mauvais passage"
        python -m musique.decider liste
"""
from __future__ import annotations

import argparse

from .commun import CLIPS, DECISIONS, ecrire, lire, maintenant


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["valider", "rejeter", "liste"])
    p.add_argument("codes", nargs="*")
    p.add_argument("--raison", default="")
    a = p.parse_args()
    clips = lire(CLIPS, [])
    decisions = lire(DECISIONS, {})
    par_code = {c.get("code"): c for c in clips}
    if a.action == "liste":
        for c in clips[-40:]:
            d = decisions.get(c["id"], {})
            print(f"{c.get('code')}  {d.get('statut', c.get('statut')):<10} {c['artiste_nom']} — "
                  f"{c.get('titre_son', '')} {int(c['debut']) // 60}:{int(c['debut']) % 60:02d} "
                  f"({c.get('duree')} s, {c['mode']}) | {c.get('legende', '')}")
        return
    codes = [x.strip().upper() for x in " ".join(a.codes).replace(",", " ").split() if x.strip()]
    for code in codes:
        c = par_code.get(code)
        if not c:
            print(f"✘ {code} introuvable")
            continue
        d = decisions.setdefault(c["id"], {})
        if d.get("statut") == "publie":
            print(f"• {code} déjà programmée/publiée : inchangée")
            continue
        d.update(statut="approuve" if a.action == "valider" else "rejete", maj=maintenant(), maj_page=maintenant())
        if a.action == "rejeter":
            d["raison_texte"] = a.raison
        print(f"✔ {code} {'validée' if a.action == 'valider' else 'rejetée'}")
    ecrire(DECISIONS, decisions)


if __name__ == "__main__":
    main()
