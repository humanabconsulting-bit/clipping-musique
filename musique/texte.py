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
Y_MILIEU = 960                                # paroles « au milieu » (style deux couleurs)
Y_NEON = 880                                  # style néon : un peu au-dessus du milieu, comme l'exemple

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


def couleur_ass(hexa: str) -> str:
    """« #33B5FF » → « &H00FFB533& » (ASS écrit les couleurs en bleu-vert-rouge)."""
    h = hexa.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def _groupes(mots: list[dict], duree: float, par_groupe: int) -> list[list[dict]]:
    ms = [w for w in mots if w["fin"] > 0 and w["debut"] < duree and nettoyer(w["mot"])]
    groupes, cour = [], []
    for w in ms:
        if cour and (len(cour) >= par_groupe or (w.get("phrase") and len(cour) >= 2)
                     or w["debut"] - cour[-1]["fin"] > 1.2):
            groupes.append(cour)
            cour = []
        cour.append(w)
    if cour:
        groupes.append(cour)
    return groupes


def _deux_couleurs(mots: list[dict], duree: float, couleurs: tuple, y: int, par_groupe: int = 3) -> list[str]:
    """Paroles qui défilent au MILIEU de l'écran : les mots apparaissent au moment où ils sont chantés,
    un mot sur deux en couleur 1 (blanc) / couleur 2 (bleu brillant, avec un halo lumineux)."""
    c1, c2 = couleur_ass(couleurs[0]), couleur_ass(couleurs[1])
    halo = couleur_ass(couleurs[2]) if len(couleurs) > 2 else "&H00913D0B&"  # contour bleu foncé flouté = halo lisible
    ev = []
    groupes = _groupes(mots, duree, par_groupe)
    rang = 0
    for g_i, groupe in enumerate(groupes):
        suivant_g = groupes[g_i + 1][0]["debut"] if g_i + 1 < len(groupes) else duree
        rangs = list(range(rang, rang + len(groupe)))
        rang += len(groupe)
        for j, w in enumerate(groupe):
            fin_w = groupe[j + 1]["debut"] if j + 1 < len(groupe) else min(suivant_g, w["fin"] + 0.8)
            morceaux = []
            for k, x in enumerate(groupe):
                t = majuscules(nettoyer(x["mot"]))
                bleu = rangs[k] % 2 == 1
                style = ("{\\c" + c2 + "\\3c" + halo + "\\blur3}") if bleu else ("{\\c" + c1 + "\\3c&H000000&\\blur0}")
                if k > j:  # pas encore chanté : invisible mais garde sa place (le texte ne saute pas)
                    style = style[:-1] + "\\alpha&HFF&}"
                elif k == j:  # mot chanté : petit « pop »
                    style = style[:-1] + "\\fscx108\\fscy108}"
                morceaux.append(style + t)
            ev.append(f"Dialogue: 2,{_t(max(w['debut'], 0))},{_t(min(max(fin_w, w['debut'] + 0.1), duree))},Paroles,,0,0,0,,"
                      f"{{\\an5\\pos({CENTRE_X},{y})}}" + " ".join(morceaux))
    return ev


POLICE_NEON = "Montserrat Black"


def _taille_mot(mot: str, base: int = 190, largeur_max: int = 900) -> int:
    """Taille de police pour qu'un mot tienne en largeur (Montserrat Black ≈ 0,78 × taille par lettre)."""
    return int(max(70, min(base, largeur_max / max(len(mot), 1) / 0.78)))


def _neon(mots: list[dict], duree: float, couleurs: tuple, y: int) -> list[str]:
    """Style de l'exemple (« vibe lyrics ») : UN mot à la fois au milieu de l'écran, énorme et très gras,
    un mot sur deux blanc / couleur (rose néon par défaut), avec un halo lumineux et une petite apparition.
    Les mots très courts (de, la, le…) sont collés au mot suivant, plus petits (comme « DE QUATRE »)."""
    c1, c2 = couleur_ass(couleurs[0]), couleur_ass(couleurs[1])
    ms = [w for w in mots if w["fin"] > 0 and w["debut"] < duree and nettoyer(w["mot"])]
    # on regroupe les petits mots avec le suivant
    blocs, att = [], []
    for w in ms:
        t = majuscules(nettoyer(w["mot"]))
        if len(t) <= 2 and not att:
            att = [dict(w, mot=t)]
            continue
        bloc = {"debut": (att[0]["debut"] if att else w["debut"]), "fin": w["fin"],
                "petit": att[0]["mot"] if att else "", "mot": t}
        blocs.append(bloc)
        att = []
    if att:
        blocs.append({"debut": att[0]["debut"], "fin": att[0]["fin"], "petit": "", "mot": att[0]["mot"]})
    ev = []
    for i, b in enumerate(blocs):
        fin = blocs[i + 1]["debut"] if i + 1 < len(blocs) and blocs[i + 1]["debut"] - b["fin"] < 0.8 else b["fin"] + 0.35
        fin = min(max(fin, b["debut"] + 0.12), duree)
        couleur = c2 if i % 2 == 1 else c1
        taille = _taille_mot(b["mot"])
        texte_mot = b["mot"]
        if b["petit"]:
            texte_mot = f"{{\\fs{int(taille * 0.42)}}}{b['petit']}\\N{{\\fs{taille}}}{b['mot']}"
        apparition = "\\fscx118\\fscy118\\t(0,90,\\fscx100\\fscy100)"
        debut_t, fin_t = _t(max(b["debut"], 0)), _t(fin)
        # couche 1 : halo (même couleur, flouté, transparent) ; couche 2 : le mot net
        ev.append(f"Dialogue: 3,{debut_t},{fin_t},Neon,,0,0,0,,{{\\an5\\pos(540,{y})\\fs{taille}"
                  f"\\c{couleur}\\3c{couleur}\\bord14\\blur22\\alpha&H48&{apparition}}}{texte_mot}")
        ev.append(f"Dialogue: 4,{debut_t},{fin_t},Neon,,0,0,0,,{{\\an5\\pos(540,{y})\\fs{taille}"
                  f"\\c{couleur}\\3c&H101010&\\bord1.5\\blur0.6{apparition}}}{texte_mot}")
    return ev


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
                y_paroles: int | None = None, y_credit: int | None = None,
                style_paroles: str = "karaoke", couleurs: tuple = ("#FFFFFF", "#33B5FF", "#0B3D91")) -> Path:
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
        f"Style: Neon,Montserrat Black,150,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,2,0,5,40,{MARGE_DROITE},0,1",
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
    if mots and style_paroles == "neon":
        lignes += _neon(mots, duree, couleurs, y_paroles or Y_NEON)
    elif mots and style_paroles == "deux_couleurs":
        lignes += _deux_couleurs(mots, duree, couleurs, y_paroles or Y_MILIEU)
    elif mots:
        lignes += _karaoke(mots, duree, y=y_paroles, ancre=5) if y_paroles else _karaoke(mots, duree)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return chemin


def decaler(mots: list[dict], decalage: float) -> list[dict]:
    """Ramène des mots horodatés sur le morceau entier au début du passage."""
    return [dict(w, debut=w["debut"] - decalage, fin=w["fin"] - decalage) for w in mots]
