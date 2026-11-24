"""Textes incrustés (fichier ASS lu par ffmpeg) : paroles karaoké mot par mot, accroche, crédit.

Style repris du stream : gros, blanc, MAJUSCULES, contour noir épais + ombre, mot chanté en JAUNE.
Tout est placé dans la ZONE SÛRE TikTok :
- jamais dans les 320 px du bas (légende, musique, barre) ;
- jamais dans la colonne de droite (boutons j'aime / commentaires / partage, ~150 px) ;
- pas tout en haut (onglets « Abonnements / Pour toi », ~180 px).
Polices : Noto Sans (latin) ; les lettres arabes passent automatiquement par Noto Sans Arabic (fontconfig).
"""
from __future__ import annotations

import re
from pathlib import Path

POLICE = "Noto Sans"
# Zone sûre (en pixels, image 1080 × 1920)
MARGE_BAS = 320
MARGE_DROITE = 150
MARGE_HAUT = 180
CENTRE_X = (1080 - MARGE_DROITE) // 2 + 20     # centre décalé vers la gauche, loin des boutons
Y_PAROLES = 1920 - MARGE_BAS - 180            # bas des paroles (ancrage en bas) : 1420
Y_ACCROCHE = MARGE_HAUT + 40                  # haut de l'accroche : 220

JAUNE = "&H0000FFFF&"
BLANC = "&HFFFFFF&"

EMOJIS = re.compile(r"[\U0001F000-\U0001FAFF☀-➿️‍]")


def _t(s: float) -> str:
    h, rest = divmod(max(s, 0), 3600)
    m, sec = divmod(rest, 60)
    return f"{int(h)}:{int(m):02d}:{sec:05.2f}"


def nettoyer(t: str) -> str:
    """Sans émojis (la police vidéo ne les a pas) ni caractères spéciaux ASS."""
    t = EMOJIS.sub("", t or "")
    return re.sub(r"\s+", " ", t.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")).strip()


def majuscules(t: str) -> str:
    return t.upper()  # sans effet sur l'arabe, qui n'a pas de majuscules


def decouper(texte: str, largeur: int = 24, lignes_max: int = 3) -> str:
    mots, lignes, cour = texte.split(), [], ""
    for m in mots:
        if len(cour) + len(m) + 1 > largeur and cour:
            lignes.append(cour)
            cour = m
        else:
            cour = f"{cour} {m}".strip()
    lignes.append(cour)
    return "\\N".join(lignes[:lignes_max])


def _karaoke(mots: list[dict], duree: float, par_groupe: int = 3, y: int = Y_PAROLES, ancre: int = 2) -> list[str]:
    """Paroles mot par mot : groupes de 2 à 4 mots, mot chanté en jaune."""
    ev = []
    ms = [w for w in mots if w["fin"] > 0 and w["debut"] < duree and nettoyer(w["mot"])]
    # groupes : on coupe aussi en début de vers (phrase) pour ne pas mélanger deux vers
    groupes, cour = [], []
    for w in ms:
        if cour and (len(cour) >= par_groupe or (w.get("phrase") and len(cour) >= 2)
                     or w["debut"] - cour[-1]["fin"] > 1.2):
            groupes.append(cour)
            cour = []
        cour.append(w)
    if cour:
        groupes.append(cour)
    for g_i, groupe in enumerate(groupes):
        suivant_g = groupes[g_i + 1][0]["debut"] if g_i + 1 < len(groupes) else duree
        for j, w in enumerate(groupe):
            fin_w = groupe[j + 1]["debut"] if j + 1 < len(groupe) else min(suivant_g, w["fin"] + 0.6)
            morceaux = []
            for k, x in enumerate(groupe):
                t = majuscules(nettoyer(x["mot"]))
                morceaux.append("{\\c" + JAUNE + "}" + t + "{\\c" + BLANC + "}" if k == j else t)
            ev.append(f"Dialogue: 2,{_t(max(w['debut'], 0))},{_t(min(max(fin_w, w['debut'] + 0.1), duree))},Paroles,,0,0,0,,"
                      f"{{\\an{ancre}\\pos({CENTRE_X},{y})}}" + " ".join(morceaux))
    return ev


def fichier_ass(chemin: Path, duree: float, accroche: str = "", credit: str = "",
                mots: list[dict] | None = None, couleur_cadre: str = "&H00CF4F5A",
                y_paroles: int | None = None, y_credit: int | None = None) -> Path:
    """y_paroles : centre des paroles (mise en page react : au milieu, sur la jointure haut/bas) ;
    y_credit : position du crédit (sinon sous l'accroche)."""
    """Accroche (cadre coloré, en haut) + crédit @artiste (petit, sous l'accroche) + paroles karaoké."""
    accroche = nettoyer(accroche)
    y_credit_force = y_credit
    lignes = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920", "WrapStyle: 2",
        "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Accroche,{POLICE},56,&H00FFFFFF,&H00FFFFFF,{couleur_cadre},{couleur_cadre},-1,0,0,0,100,100,0,0,3,14,0,8,70,{MARGE_DROITE},0,1",
        f"Style: Credit,{POLICE},38,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,8,60,{MARGE_DROITE},0,1",
        f"Style: Paroles,{POLICE},84,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3,2,60,{MARGE_DROITE},0,1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    y_credit = Y_ACCROCHE
    if accroche:
        lignes.append(f"Dialogue: 1,{_t(0)},{_t(duree)},Accroche,,0,0,0,,{{\\an8\\pos({CENTRE_X},{Y_ACCROCHE})}}"
                      f"{decouper(accroche)}")
        y_credit = Y_ACCROCHE + 56 * min(3, decouper(accroche).count("\\N") + 1) + 70
    if y_credit_force is not None:
        y_credit = y_credit_force
    if credit:
        lignes.append(f"Dialogue: 0,{_t(0)},{_t(duree)},Credit,,0,0,0,,{{\\an8\\pos({CENTRE_X},{y_credit})}}"
                      f"{nettoyer(credit)}")
    if mots:
        lignes += _karaoke(mots, duree, y=y_paroles, ancre=5) if y_paroles else _karaoke(mots, duree)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return chemin


def decaler(mots: list[dict], decalage: float) -> list[dict]:
    """Ramène des mots horodatés sur le morceau entier au début du passage."""
    return [dict(w, debut=w["debut"] - decalage, fin=w["fin"] - decalage) for w in mots]
