"""Programme principal « Clipping Musique » : clips verticaux TikTok (1080×1920) à partir de morceaux de rappeurs.

Usage :
    python -m musique.run --mode clip --source clip.mp4 --artiste ninho --titre "Jefe"
    python -m musique.run --mode son  --source son.mp3  --artiste ninho --titre "Jefe" --visuels pexels
    python -m musique.run --mode lifestyle --source son.mp3 --artiste ninho --tags nuit,voiture
    python -m musique.run --demo                       # test complet sans fichier ni clé

Modes :
    clip      : un clip officiel (fichier, ou lien — souvent bloqué depuis le cloud)
    video     : une vidéo fournie (même traitement que clip)
    son       : seulement le morceau → visuels autorisés (banque | clip_artiste | pexels) montés sur le beat
    lifestyle : le morceau + la banque lifestyle (plans choisis selon l'énergie, les couleurs, le mouvement)
    react     : le morceau ; en haut (1/3) un streamer qui réagit à cet artiste, en bas (2/3) ses vidéos /
                la banque, paroles au milieu

Étapes (comme le programme stream) : recherche → montage → envoi → sauvegarde ; état dans travail/etat.json.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from . import (analyse_audio, cadrage, controles, entrees, legende, montage, montage_beat, paroles, passages, react,
               texte, visuels)
from .commun import (CLIPS, DATA, EN_DIRECT, ETAT, PASSAGES, PREFIXE_CODE, SORTIE, TRAVAIL, Journal, artiste,
                     ecrire, lire, maintenant, reglages, sur_github)

MODES = ("clip", "video", "son", "lifestyle", "react")
# Visuels pris dans les banques : `banque` = anciennes vidéos de l'artiste + banque générale
VISUELS_BANQUES = {"banque": ["artiste", "generale"], "artiste": ["artiste"], "generale": ["generale"],
                   "reacts": ["reacts"], "tout": ["artiste", "generale", "reacts"]}
TEXTES = ("tout", "paroles", "accroche", "perso", "aucun")


def slug(t: str, n: int = 24) -> str:
    t = unicodedata.normalize("NFKD", (t or "").lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:n] or "son"


def mmss(s: float) -> str:
    return f"{int(s // 60)}:{int(s % 60):02d}"


# ---------------------------------------------------------------- état
def charger_etat() -> dict:
    return lire(ETAT, {})


def sauver_etat(etat: dict) -> None:
    ecrire(ETAT, etat)


def nouvel_etat(params: dict) -> dict:
    if TRAVAIL.exists():
        shutil.rmtree(TRAVAIL)
    TRAVAIL.mkdir(parents=True)
    etat = {
        "id": os.environ.get("GITHUB_RUN_ID") or datetime.now().strftime("%Y%m%d-%H%M%S"),
        "debut": maintenant(), "params": params, "demo": params.get("demo", False),
        "declencheur": os.environ.get("GITHUB_EVENT_NAME", "manuel"),
        "etape": "recherche", "candidats": [], "prets": [], "erreurs": 0,
        "progression": {"fait": 0, "total": 0},
    }
    sauver_etat(etat)
    return etat


def duree_bornes(texte_duree: str | None, cfg: dict) -> tuple[float, float]:
    """« 15-30 » → (15, 30)."""
    if texte_duree:
        m = re.match(r"\s*(\d+(?:\.\d+)?)\s*[-–à]\s*(\d+(?:\.\d+)?)", str(texte_duree))
        if m:
            return float(m.group(1)), float(m.group(2))
        if str(texte_duree).strip().replace(".", "").isdigit():
            d = float(texte_duree)
            return max(5.0, d - 3), d + 3
    return float(cfg.get("duree_min_secondes", 15)), float(cfg.get("duree_max_secondes", 30))


# ---------------------------------------------------------------- étape 1 : recherche des passages
def etape_recherche(params: dict) -> None:
    etat = nouvel_etat(params)
    log = Journal(etat)
    cfg = reglages()
    mode = params["mode"]
    fiche = artiste(cfg, params["artiste"])
    log(f"Passage {etat['id']} — mode « {mode} », artiste {fiche['nom']}"
        + (f", son « {params['titre']} »" if params.get("titre") else ""))
    if fiche.get("accord") is not True:
        log(f"⚠ {fiche['nom']} n'a pas `accord: true` dans les réglages : les clips seront fabriqués pour "
            "validation mais leur publication sera REFUSÉE tant que l'accord n'est pas noté.", "alerte")

    # 1. Fichier source
    if params.get("demo"):
        if mode in ("clip", "video"):
            src = montage.demo_son(TRAVAIL / "demo_son.wav")
            video = montage.demo_video(TRAVAIL / "demo_clip_muet.mp4", 96)
            source = TRAVAIL / "demo_clip.mp4"
            montage.executer(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(src), "-map", "0:v",
                              "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-shortest", str(source)])
        else:
            source = montage.demo_son(TRAVAIL / "demo_son.wav")
        log("Mode démo : morceau de synthèse (couplets calmes / refrains forts)")
    else:
        source = entrees.recuperer(params["source"])
    info = montage.infos_video(source)
    if not info["son"]:
        raise RuntimeError(f"{source.name} n'a pas de son")
    if mode in ("clip", "video") and not info["video"]:
        raise RuntimeError(f"{source.name} n'a pas d'image : utilise le mode « son » ou « lifestyle »")
    log(f"Source : {source.name} ({mmss(info['duree'])}"
        + (f", {info['largeur']}×{info['hauteur']}" if info["video"] else ", audio seul") + ")")

    # 2. Analyse du morceau
    audio = montage.extraire_audio(source, TRAVAIL / "morceau.wav", taux=22050, mono=True)
    analyse = analyse_audio.analyser(audio)
    ecrire(TRAVAIL / "analyse.json", analyse)
    log(f"Analyse : tempo {analyse['tempo']:.0f} BPM, {len(analyse['beats'])} temps")

    # 3. Transcription rapide du morceau entier (densité de voix + punchlines)
    mots = []
    if cfg.get("transcrire_morceau", True) and not params.get("demo"):
        try:
            mots, langue = montage.transcrire(audio, cfg.get("modele_whisper", "small"), cfg.get("langue"))
            etat["langue"] = langue
            log(f"Transcription rapide : {len(mots)} mot(s), langue détectée « {langue or '?'} »")
        except Exception as e:
            log(f"Transcription rapide impossible ({e}) : choix sur l'audio seul", "alerte")
    ecrire(TRAVAIL / "mots_morceau.json", mots)

    # 4. Choix des passages
    dmin, dmax = duree_bornes(params.get("duree"), cfg)
    d0, d1 = passages.lire_temps(params.get("debut")), passages.lire_temps(params.get("fin"))
    if d0 is not None and d1 is not None and d1 > d0:
        choisis = [passages.passage_force(d0, d1, analyse)]
        log(f"Passage imposé : {mmss(choisis[0]['debut'])} → {mmss(choisis[0]['fin'])} (recalé sur la mesure)")
    else:
        deja = [(c["debut"], c["fin"]) for c in lire(CLIPS, [])
                if c.get("artiste") == fiche["cle"] and c.get("titre_son") == params.get("titre") and params.get("titre")]
        choisis = passages.choisir(analyse, mots, int(params.get("nb") or cfg.get("nb_clips", 4)), dmin, dmax,
                                   deja=deja)
    if not choisis:
        log(f"Aucun passage de {dmin:.0f}–{dmax:.0f} s trouvé (morceau trop court ?)", "erreur")
        etat["erreurs"] += 1
    for k, p in enumerate(choisis):
        cid = f"{fiche['cle']}_{slug(params.get('titre') or source.stem)}_{int(p['debut'])}"
        etat["candidats"].append({
            "id": cid, "artiste": fiche["cle"], "artiste_nom": fiche["nom"], "titre_son": params.get("titre", ""),
            "mode": mode, "source": params.get("source") or ("demo" if params.get("demo") else source.name),
            "source_fichier": str(source), "debut": p["debut"], "fin": p["fin"],
            "duree": round(p["fin"] - p["debut"], 2), "score": p["score"], "type": p["type"],
            "details": p["details"], "texte": params.get("texte", "tout"),
            "texte_perso": params.get("texte_perso", ""), "visuels": params.get("visuels"),
            "paroles_fichier": params.get("paroles", ""), "clip": params.get("clip", ""), "tags": params.get("tags", ""),
            "react_impose": params.get("react", ""),
            "demo": bool(params.get("demo")),
        })
        d = p["details"]
        log(f"  {k + 1}. {mmss(p['debut'])} → {mmss(p['fin'])} ({p['fin'] - p['debut']:.0f} s) — {p['type']}, "
            f"score {p['score']:.2f} (refrain {d.get('refrain', '-')}, énergie {d.get('energie', '-')}, "
            f"voix {d.get('voix', '-')}, drop {d.get('drop', '-')})")
    etat["progression"] = {"fait": 0, "total": len(etat["candidats"])}
    sauver_etat(etat)


# ---------------------------------------------------------------- étape 2 : montage
def _visuels_pour(c: dict, params: dict, cfg: dict, fiche: dict, log) -> list[dict]:
    mode = c["mode"]
    if c.get("demo"):  # plans de synthèse (couleurs et mouvements différents), rien n'est téléchargé
        plans = []
        for k, src in enumerate(["testsrc2", "smptehdbars", "rgbtestsrc", "yuvtestsrc"]):
            f = montage.demo_video(TRAVAIL / f"plan_demo_{k}.mp4", 12, src)
            plans.append(dict(visuels.bq.analyser(f), nom=f.name, chemin=str(f), origine="demo"))
        return plans
    choix_v = params.get("visuels") or ("banque" if mode == "lifestyle" else cfg.get("visuels_defaut", "banque"))
    if mode == "lifestyle" and choix_v not in VISUELS_BANQUES:
        choix_v = "banque"
    if choix_v in VISUELS_BANQUES:
        sources = VISUELS_BANQUES[choix_v]
        tags = [t for t in (params.get("tags") or "").split(",") if t.strip()]
        plans = visuels.plans_banque(fiche["cle"], sources, tags) or visuels.plans_banque(fiche["cle"], sources)
        if not plans:
            raise visuels.VisuelsRefuses(
                f"aucune vidéo pour {fiche['nom']} dans : {', '.join(sources)}. Dépose des vidéos dans les Releases "
                f"(banque-generale, banque-{fiche['cle']}, banque-reacts) puis lance « Banque : indexer »")
        log(f"   visuels : {len(plans)} plan(s) disponibles ({', '.join(sources)})")
        return plans
    if choix_v == "clip_artiste":
        nom = params.get("clip") or ""
        visuels.verifier_clip_artiste(nom, fiche["cle"])
        return visuels.plans_clip(entrees.recuperer(nom))
    if choix_v == "pexels":
        mots = [t for t in (params.get("tags") or "").split(",") if t.strip()] or fiche.get("pexels_mots")
        return visuels.plans_pexels(mots, log=log)
    raise visuels.VisuelsRefuses(f"visuels « {choix_v} » inconnus (banque | clip_artiste | pexels)")


def monter_un(c: dict, params: dict, cfg: dict, etat: dict, log) -> Path:
    fiche = artiste(cfg, c["artiste"])
    source = Path(c["source_fichier"])
    analyse = lire(TRAVAIL / "analyse.json", {})
    d = TRAVAIL / c["id"]
    d.mkdir(parents=True, exist_ok=True)
    duree = c["fin"] - c["debut"]
    audio_p = montage.extraire_audio(source, d / "passage.wav", c["debut"], duree)

    # Texte
    mots = []
    if c["texte"] in ("tout", "paroles"):
        f_paroles = None
        if params.get("paroles"):
            try:
                f_paroles = entrees.recuperer(params["paroles"])
            except Exception as e:
                log(f"   fichier de paroles introuvable ({e}) : transcription Whisper", "alerte")
        if c.get("demo"):
            mots = [{"debut": 0.8 + 0.6 * i, "fin": 1.3 + 0.6 * i, "mot": m, "phrase": i % 4 == 0}
                    for i, m in enumerate("ceci est un test du mode démo sans paroles réelles".split())]
            origine, langue = "demo", "fr"
        else:
            mots, langue, origine = paroles.paroles_passage(audio_p, d, cfg, f_paroles, c["debut"], log=log)
        c.update(paroles_source=origine, langue=langue, paroles=" ".join(w["mot"] for w in mots))
        log(f"   paroles : {len(mots)} mot(s) ({origine}{', ' + langue if langue else ''})")
    # en mise en page react, le haut est le visage du streamer : pas d'accroche sauf si demandée exprès
    avec_accroche = ("accroche", "perso") if c["mode"] == "react" else ("tout", "accroche", "perso")
    c["accroche"] = (c["texte_perso"] if c["texte"] == "perso" else legende.choisir_accroche(c, cfg)) \
        if c["texte"] in avec_accroche else ""
    if c["mode"] == "react":
        ass = texte.fichier_ass(d / "texte.ass", duree, c["accroche"], legende.mention(fiche), mots,
                                y_paroles=react.Y_PAROLES_REACT, y_credit=react.Y_CREDIT_REACT)
    else:
        ass = texte.fichier_ass(d / "texte.ass", duree, c["accroche"], legende.mention(fiche), mots)

    fichier = d / f"{c['artiste']}_{slug(c['titre_son'] or 'son', 16)}_{int(c['debut'])}.mp4"
    if c["mode"] in ("clip", "video"):
        traj = None
        try:
            t = cadrage.trajectoire(source, c["debut"], duree)
            c["cadrage"] = {"taux_visages": t["taux_visages"], "plans": len(t["plans"]) + 1}
            if t["taux_visages"] >= cfg.get("taux_visages_min", 0.25):
                traj = t
                log(f"   cadrage : visage suivi ({int(t['taux_visages'] * 100)} % des images, "
                    f"{len(t['plans']) + 1} plan(s))")
            else:
                log(f"   cadrage : peu de visages ({int(t['taux_visages'] * 100)} %) → vidéo centrée sur fond flou")
        except Exception as e:
            log(f"   cadrage impossible ({e}) → fond flou", "alerte")
        c["mise_en_page"] = "suivi_visage" if traj else "flou"
        cmd = cadrage.commandes(traj, d / "cadrage.txt") if traj else None
        filtre = (cadrage.filtre(traj, cmd, "[0:v]", "[cadre]")
                  + f";[cadre]subtitles='{montage.chemin_ass(ass)}'[v]")
        montage.executer(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{c['debut']:.3f}", "-i", str(source),
                          "-t", f"{duree:.3f}", "-filter_complex", filtre, "-map", "[v]", "-map", "0:a",
                          "-af", f"afade=t=in:d=0.08,afade=t=out:st={max(duree - 0.4, 0):.2f}:d=0.4",
                          *montage.options_encodage(duree), str(fichier)])
        c["visuels_source"] = "clip_artiste" if c["mode"] == "clip" else "video_fournie"
    else:
        plans = _visuels_pour(c, params, cfg, fiche, log)
        segs = montage_beat.coupes(analyse, c["debut"], c["fin"])
        choix = visuels.choisir_plans(plans, segs, c["id"])
        chemins = [visuels.chemin_plan(x["plan"]) for x in choix]
        c["visuels_source"] = choix[0]["origine"] if choix else ""
        c["plans"] = [{"nom": x["nom"], "depart": x["depart"], "duree": x["duree"], "origine": x["origine"]}
                      for x in choix]
        credits = sorted({x["plan"].get("credit") for x in choix if x["plan"].get("credit")})
        if credits:
            c["credits_visuels"] = credits
        c["sources_visuels"] = sorted({x["origine"] for x in choix})
        log(f"   montage sur le beat : {len(segs)} plan(s) ({c['visuels_source']})")
        if c["mode"] == "react":
            if c.get("demo"):
                r = {"nom": "react_demo.mp4", "chemin": str(montage.demo_video(TRAVAIL / "react_demo.mp4", 30, "smptehdbars")),
                     "duree": 30.0, "streamer": "streamer_demo", "origine": "reacts"}
            else:
                reacts = visuels.plans_banque(fiche["cle"], ["reacts"])
                r = react.choisir_react(reacts, duree, c["id"], params.get("react", ""))
            r_chemin = visuels.chemin_plan(r)
            r_depart = round(max(0.0, min(r.get("duree", duree) - duree - 0.5, r.get("duree", duree) * 0.2)), 2)
            cadre = react.cadre_camera(r_chemin, r_depart, duree)
            bas = montage_beat.images_sur_le_beat(choix, chemins, segs, d / "segments", cfg.get("zooms", True),
                                                  montage.LARGEUR, react.H_BAS)
            react.monter(r_chemin, r_depart, cadre, bas, audio_p, ass, duree, fichier)
            credit = f"react @{r.get('streamer') or '?'}"
            c["react"] = {"nom": r["nom"], "streamer": r.get("streamer"), "depart": r_depart,
                          "camera_trouvee": bool(cadre)}
            c["credits_visuels"] = sorted(set(c.get("credits_visuels", [])) | {credit})
            log(f"   react : {r['nom']} ({credit}, " + ("caméra du streamer trouvée" if cadre else
                "pas de caméra fixe : react entier recadré") + ")")
        else:
            montage_beat.monter(choix, chemins, segs, audio_p, ass, fichier, d / "segments",
                                zoom=cfg.get("zooms", True))
    return fichier


def etape_montage() -> None:
    etat = charger_etat()
    etat["etape"] = "montage"
    log = Journal(etat)
    cfg = reglages()
    params = etat.get("params", {})
    import time
    debut = time.time()
    budget = cfg.get("budget_montage_minutes", 50) * 60
    dmin, _ = duree_bornes(params.get("duree"), cfg)
    for i, c in enumerate(etat["candidats"]):
        if time.time() - debut > budget:
            log(f"Temps de montage dépassé : {len(etat['candidats']) - i} passage(s) non monté(s)", "alerte")
            break
        try:
            log(f"[{i + 1}/{len(etat['candidats'])}] {c['artiste_nom']} — {mmss(c['debut'])} → {mmss(c['fin'])}")
            fini = monter_un(c, params, cfg, etat, log)
            pb = controles.son_et_duree(fini, min(dmin, c["duree"]) if c.get("type") == "impose" else dmin)
            if pb:
                raise RuntimeError("contrôle échoué : " + " ; ".join(pb))
            c["silence_max"] = round(montage.plus_long_silence(fini), 1)
            c.update(controles.nudite(fini, log))
            fiche = artiste(cfg, c["artiste"])
            c["legende"] = legende.legende(c, fiche, cfg)
            c.update(fichier=fini.name, chemin=str(fini), duree=round(montage.duree_video(fini), 1),
                     taille_mo=round(fini.stat().st_size / 1e6, 2), format="1080x1920")
            etat["prets"].append(c)
            log(f"   ✔ prêt : {fini.name} ({c['taille_mo']} Mo) — légende : {c['legende']}")
        except Exception as e:
            etat["erreurs"] += 1
            log(f"   ✘ échec : {e}", "erreur")
        etat["progression"] = {"fait": i + 1, "total": len(etat["candidats"])}
        sauver_etat(etat)


# ---------------------------------------------------------------- étape 3 : envoi
def etape_envoi() -> None:
    etat = charger_etat()
    etat["etape"] = "envoi"
    log = Journal(etat)
    if not etat["prets"]:
        log("Aucun clip à envoyer")
        sauver_etat(etat)
        return
    if sur_github() and not etat.get("demo"):
        tag = "clips-" + datetime.now(timezone.utc).strftime("%Y-%m")
        if subprocess.run(["gh", "release", "view", tag], capture_output=True).returncode != 0:
            subprocess.run(["gh", "release", "create", tag, "--title", f"Clips musique {tag[6:]}",
                            "--notes", "Clips générés automatiquement."], check=True, capture_output=True)
        for c in etat["prets"]:
            subprocess.run(["gh", "release", "upload", tag, c["chemin"], "--clobber"], check=True, capture_output=True)
            c["video"] = {"type": "release", "tag": tag, "nom": c["fichier"]}
            log(f"Envoyé sur GitHub : {c['fichier']}")
    else:
        SORTIE.mkdir(exist_ok=True)
        for c in etat["prets"]:
            shutil.copy2(c["chemin"], SORTIE / c["fichier"])
            c["video"] = {"type": "local", "chemin": f"sortie/{c['fichier']}"}
        log(f"{len(etat['prets'])} clip(s) copié(s) dans sortie/")
    sauver_etat(etat)


# ---------------------------------------------------------------- étape 4 : sauvegarde
def etape_sauvegarde() -> None:
    etat = charger_etat()
    etat["etape"] = "sauvegarde"
    log = Journal(etat)
    cfg = reglages()
    if etat.get("demo"):
        log(f"Mode démo : {len(etat['prets'])} clip(s) dans sortie/, rien n'est enregistré dans data/")
        return
    clips = lire(CLIPS, [])
    statut = "approuve" if cfg.get("auto_approuver") else "en_attente"
    numero = max([int(str(x.get("code", "M0"))[1:] or 0) for x in clips] + [0])
    for c in etat["prets"]:
        numero += 1
        c["code"] = f"{PREFIXE_CODE}{numero:04d}"
        c["statut"] = statut
        c["traite_le"] = maintenant()
        for k in ("chemin", "source_fichier"):
            c.pop(k, None)
        clips = [x for x in clips if x["id"] != c["id"]] + [c]
    ecrire(CLIPS, clips)
    passages_ = lire(PASSAGES, [])
    fin = maintenant()
    passages_.append({
        "id": etat["id"], "debut": etat["debut"], "fin": fin, "params": etat.get("params", {}),
        "trouves": len(etat["candidats"]), "prets": len(etat["prets"]), "erreurs": etat["erreurs"],
        "statut": "ok" if etat["erreurs"] == 0 else ("partiel" if etat["prets"] else "echec"),
        "codes": [c["code"] for c in etat["prets"]], "journal": etat.get("journal", []),
    })
    ecrire(PASSAGES, passages_[-200:])
    log(f"Passage terminé : {len(etat['prets'])} clip(s) ajouté(s) "
        f"({', '.join(c['code'] for c in etat['prets'])}), {etat['erreurs']} erreur(s)")
    ecrire(EN_DIRECT, {"passage": etat["id"], "etape": "termine", "statut": "termine", "maj": fin,
                       "dernier_message": f"{len(etat['prets'])} clip(s) ajouté(s)",
                       "progression": etat["progression"]})


def main() -> int:
    p = argparse.ArgumentParser(description="Clipping Musique")
    p.add_argument("etape", nargs="?", default="tout", choices=["tout", "recherche", "montage", "envoi", "sauvegarde"])
    p.add_argument("--mode", choices=MODES, default="clip")
    p.add_argument("--source", default="", help="fichier (Release « entrees ») ou lien")
    p.add_argument("--artiste", default="", help="clé de l'artiste dans config/reglages.json")
    p.add_argument("--titre", default="", help="titre du son")
    p.add_argument("--nb", default="", help="nombre de clips (défaut 4)")
    p.add_argument("--duree", default="", help="durée, ex. 15-30")
    p.add_argument("--texte", choices=TEXTES, default="tout")
    p.add_argument("--texte-perso", dest="texte_perso", default="")
    p.add_argument("--paroles", default="", help="fichier .txt ou .lrc (Release « entrees »)")
    p.add_argument("--debut", default="", help="forcer un passage, ex. 1:12")
    p.add_argument("--fin", default="", help="forcer un passage, ex. 1:40")
    p.add_argument("--visuels", default="", choices=["", "banque", "artiste", "generale", "reacts", "tout", "clip_artiste", "pexels"])
    p.add_argument("--clip", default="", help="clip du même artiste pour --visuels clip_artiste")
    p.add_argument("--react", default="", help="mode react : fichier précis de banque-reacts (sinon choisi seul)")
    p.add_argument("--tags", default="", help="tags de la banque / mots Pexels, séparés par des virgules")
    p.add_argument("--demo", action="store_true")
    # options supplémentaires du workflow (champ « options »), ex. --paroles jefe.lrc --debut 1:12 --fin 1:40
    import shlex
    a = p.parse_args(sys.argv[1:] + shlex.split(os.environ.get("OPTIONS_SUPP", "")))
    demo = a.demo or os.environ.get("MODE_DEMO", "").lower() in ("1", "true")
    params = {k: v for k, v in vars(a).items() if k != "etape"}
    params["demo"] = demo
    if demo and not params["artiste"]:
        params.update(artiste="demo", titre="Son de démo")
    if a.etape in ("tout", "recherche"):
        if not demo and not (params["source"] and params["artiste"]):
            p.error("--source et --artiste sont obligatoires (ou --demo)")
        etape_recherche(params)
    if a.etape in ("tout", "montage"):
        etape_montage()
    if a.etape in ("tout", "envoi"):
        etape_envoi()
    if a.etape in ("tout", "sauvegarde"):
        etape_sauvegarde()
    etat = charger_etat()
    return 0 if etat.get("prets") or etat.get("etape") != "sauvegarde" else 1


if __name__ == "__main__":
    sys.exit(main())
