"""Planning + publication TikTok via Buffer (gratuit) — reprend la logique de pack.py et publier.py du stream.

Pour la musique il n'y a qu'une chaîne TikTok : pas de « paires » ni de pack à importer à la main.
À chaque passage (workflow « Publier », toutes les 4 h) :
  1. PLANNING : les vidéos VALIDÉES dans le tableau de bord (statut « approuve ») et publiables
     (accord de l'artiste, pas de nudité, pas de passage muet) reçoivent un créneau
     (`heures` de la chaîne, `par_jour` max, heure de France, au plus 1 clip par son et par jour) ;
  2. PROGRAMMATION : quand le créneau est dans moins de `fenetre_heures` (6 h), la vidéo est déposée sur
     le dépôt public tampon puis programmée sur Buffer (file gratuite : 10 posts max par chaîne) ;
  3. NETTOYAGE : retirée du dépôt public dès que Buffer l'a publiée (ou 12 h après le créneau),
     supprimée des Releases GitHub 72 h après publication.
Rien ne part sans validation (auto_approuver = false par défaut).

Usage : python -m musique.publier            (planning + programmation + nettoyage)
        python -m musique.publier planning   (planning seulement, sans rien envoyer)
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import buffer, cloud, controles
from .commun import CLIPS, DECISIONS, artiste, ecrire, lire, maintenant, reglages

ALERTE_MARQUE = ("⚠ {code} : {artiste} est en « contenu de marque » : l'API Buffer ne permet pas (à notre "
                 "connaissance) de cocher l'option TikTok « contenu de marque ». Coche-la à la main dans "
                 "TikTok après publication (… > Paramètres de la publication > Divulgation du contenu).")


def statut(c: dict, decisions: dict) -> str:
    return decisions.get(c["id"], {}).get("statut", c.get("statut", "en_attente"))


def planifier(cfg: dict, clips: list[dict], decisions: dict, maintenant_utc: datetime) -> int:
    tz = ZoneInfo(cfg.get("fuseau", "Europe/Paris"))
    faits = 0
    for ch in [c for c in cfg.get("chaines", []) if c.get("actif")]:
        heures = sorted(ch.get("heures") or [18])
        par_jour = ch.get("par_jour", len(heures))
        pris = {}  # jour → [heures prises]
        sons = {}  # jour → {titres}
        for d in decisions.values():
            if d.get("chaine") == ch["nom"] and d.get("prevu_le"):
                q = datetime.fromisoformat(d["prevu_le"]).astimezone(tz)
                pris.setdefault(q.date(), []).append(q.hour)
                sons.setdefault(q.date(), set()).add(d.get("son", ""))
        a_placer = [c for c in clips if statut(c, decisions) == "approuve"
                    and not decisions.get(c["id"], {}).get("prevu_le")
                    and (c.get("video") or {}).get("type") == "release"]
        a_placer.sort(key=lambda c: (-(c.get("score") or 0)))
        for c in a_placer:
            fiche = artiste(cfg, c["artiste"])
            pb = controles.publiable(c, fiche, decisions.get(c["id"], {}))
            if pb:
                decisions.setdefault(c["id"], {})["bloque"] = pb
                print(f"• {c.get('code')} non planifiée : {' ; '.join(pb)}")
                continue
            son = f"{c['artiste']}/{c.get('titre_son', '')}"
            place = None
            for j in range(0, 14):
                jour = (maintenant_utc.astimezone(tz) + timedelta(days=j)).date()
                if len(pris.get(jour, [])) >= par_jour or son in sons.get(jour, set()):
                    continue
                for h in heures:
                    quand = datetime.combine(jour, datetime.min.time(), tz).replace(hour=h)
                    if h in pris.get(jour, []) or quand < maintenant_utc + timedelta(minutes=40):
                        continue
                    place = quand
                    break
                if place:
                    break
            if not place:
                print(f"• {c.get('code')} : plus de créneau libre sur 14 jours")
                continue
            pris.setdefault(place.date(), []).append(place.hour)
            sons.setdefault(place.date(), set()).add(son)
            decisions.setdefault(c["id"], {}).update(
                chaine=ch["nom"], son=son, prevu_le=place.astimezone(timezone.utc).isoformat(timespec="seconds"),
                legende=decisions.get(c["id"], {}).get("legende") or c.get("legende", ""), maj=maintenant())
            decisions[c["id"]].pop("bloque", None)
            faits += 1
            print(f"✔ {c.get('code')} planifiée sur {ch['nom']} le {place:%d/%m à %Hh} (heure de France)")
    return faits


def programmer(cfg: dict, clips: dict, decisions: dict, maintenant_utc: datetime) -> int:
    chaines = {ch["nom"]: ch for ch in cfg.get("chaines", []) if ch.get("actif") and ch.get("buffer_id")}
    total = 0
    for cid, d in sorted(decisions.items(), key=lambda x: x[1].get("prevu_le", "")):
        c = clips.get(cid)
        ch = chaines.get(d.get("chaine", ""))
        if not c or not ch or not d.get("prevu_le") or ch["buffer_id"] in (d.get("buffer") or {}):
            continue
        quand = datetime.fromisoformat(d["prevu_le"])
        if quand < maintenant_utc + timedelta(minutes=10) or quand > maintenant_utc + timedelta(hours=cfg.get("fenetre_heures", 6)):
            continue
        fiche = artiste(cfg, c["artiste"])
        pb = controles.publiable(c, fiche, d)  # revérifié juste avant (accord retiré entre-temps ?)
        if pb:
            print(f"✘ {c.get('code')} bloquée : {' ; '.join(pb)}")
            continue
        en_file = sum(1 for x in decisions.values() for b, info in (x.get("buffer") or {}).items()
                      if b == ch["buffer_id"] and info.get("prevu", "") > maintenant_utc.isoformat())
        if en_file >= cfg.get("buffer_file_max", 10):
            print(f"• file Buffer pleine ({en_file}) : {c.get('code')} attend le prochain passage")
            break
        try:
            if not d.get("cloud_url") or d.get("cloud_supprime"):
                v = c["video"]
                with tempfile.TemporaryDirectory() as tmp:
                    subprocess.run(["gh", "release", "download", v["tag"], "-p", v["nom"], "-D", tmp],
                                   check=True, capture_output=True)
                    d["cloud_url"] = cloud.envoyer(Path(tmp) / v["nom"], c["code"])
                d.update(cloud_id=c["code"], cloud_le=maintenant())
                d.pop("cloud_supprime", None)
            buffer.CLE = ch.get("buffer_cle", "BUFFER_API_KEY_MUSIQUE")
            texte = d.get("legende") or c.get("legende", "")
            pid = buffer.programmer(ch["buffer_id"], "tiktok", texte, d["cloud_url"],
                                    quand.strftime("%Y-%m-%dT%H:%M:%S.000Z"))
            d.setdefault("buffer", {})[ch["buffer_id"]] = {"post": pid, "chaine": ch["nom"], "le": maintenant(),
                                                           "prevu": quand.isoformat()}
            d.update(statut="publie", publie_le=quand.isoformat())
            total += 1
            print(f"✔ {c['code']} programmée sur {ch['nom']}")
            if fiche.get("contenu_de_marque"):
                d["marque_a_cocher"] = True
                print(ALERTE_MARQUE.format(code=c["code"], artiste=fiche["nom"]))
        except Exception as e:
            print(f"✘ {c.get('code')} : {e}")
    return total


def nettoyer(cfg: dict, clips: list[dict], decisions: dict, maintenant_utc: datetime) -> None:
    # 1. Dépôt public : retrait dès que Buffer a publié (ou 12 h après le créneau)
    statuts = {}
    for ch in [c for c in cfg.get("chaines", []) if c.get("actif") and c.get("buffer_id")]:
        try:
            buffer.CLE = ch.get("buffer_cle", "BUFFER_API_KEY_MUSIQUE")
            org = buffer.organisations()[0]["id"]
            for p in buffer.posts(org, [ch["buffer_id"]]):
                statuts[p["id"]] = p["status"]
        except Exception as e:
            print(f"Buffer (statuts) : {e}")
    for d in decisions.values():
        if not d.get("cloud_id") or d.get("cloud_supprime"):
            continue
        infos = [i for i in (d.get("buffer") or {}).values() if i.get("post")]
        fini = bool(infos) and all(statuts.get(i["post"]) == "sent" for i in infos)
        vieux = all(datetime.fromisoformat(i["prevu"]) < maintenant_utc - timedelta(hours=12) for i in infos) \
            if infos else datetime.fromisoformat(d["cloud_le"]) < maintenant_utc - timedelta(hours=12)
        if fini or vieux:
            try:
                if cloud.supprimer(d["cloud_id"]):
                    d["cloud_supprime"] = maintenant()
                    print(f"Dépôt public : {d['cloud_id']} retirée")
            except Exception as e:
                print(f"Suppression {d['cloud_id']} : {e}")
    # 2. Releases : suppression 72 h après publication
    limite = maintenant_utc - timedelta(hours=cfg.get("supprimer_apres_heures", 72))
    for c in clips:
        d, v = decisions.get(c["id"], {}), c.get("video") or {}
        if d.get("statut") != "publie" or not d.get("publie_le") or v.get("type") != "release":
            continue
        if datetime.fromisoformat(d["publie_le"].replace("Z", "+00:00")) > limite:
            continue
        r = subprocess.run(["gh", "release", "delete-asset", v["tag"], v["nom"], "-y"], capture_output=True, text=True)
        if r.returncode == 0 or "not found" in (r.stderr or "").lower():
            c["video"] = {"type": "supprime", "nom": v["nom"], "supprime_le": maintenant()}
            print(f"Release : {c.get('code')} supprimée (publiée depuis plus de 72 h)")


def main(planning_seul: bool = False) -> None:
    cfg = reglages()
    clips_l = lire(CLIPS, [])
    decisions = lire(DECISIONS, {})
    maintenant_utc = datetime.now(timezone.utc)
    n = planifier(cfg, clips_l, decisions, maintenant_utc)
    print(f"Planning : {n} nouvelle(s) vidéo(s) planifiée(s)")
    if not planning_seul:
        if not cfg.get("publication_auto"):
            print("Publication automatique désactivée (publication_auto = false) : planning seulement")
        else:
            t = programmer(cfg, {c["id"]: c for c in clips_l}, decisions, maintenant_utc)
            print(f"Programmation : {t} post(s) Buffer")
            nettoyer(cfg, clips_l, decisions, maintenant_utc)
    ecrire(DECISIONS, decisions)
    ecrire(CLIPS, clips_l)


if __name__ == "__main__":
    main(planning_seul=sys.argv[1:2] == ["planning"])
