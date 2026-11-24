# Clipping Musique — règles pour Claude

## Règle d'or (demandée par le propriétaire)
**Rien de payant sans son accord explicite, AVANT de le faire.** Aucune API d'IA payante, aucun abonnement,
aucune option payante (Buffer, Pexels, GitHub, hébergeurs…). En cas de doute : demander d'abord, ne rien lancer.
Tout tourne avec des outils gratuits : librosa, faster-whisper, MediaPipe, PySceneDetect, NudeNet, ffmpeg,
API Pexels gratuite, plan gratuit Buffer, GitHub Actions gratuit.

## Tout dans le cloud (le propriétaire ne veut RIEN sur son ordinateur)
- Le CODE est dans le dépôt **public** `humanabconsulting-bit/clipping-musique` → minutes GitHub Actions
  **gratuites et illimitées** (les 2 000 min/mois des dépôts privés sont déjà presque toutes utilisées par le stream).
- Les DONNÉES sont dans le dépôt **privé** `humanabconsulting-bit/clipping-musique-donnees` :
  `config/reglages.json`, `data/*.json`, et les Releases (`entrees`, `banque`, `clips-AAAA-MM`, `recuperees`).
  Les workflows le récupèrent avec le secret `DONNEES_TOKEN` dans le dossier `donnees/` (variable `DONNEES`).
- Ne jamais écrire de données privées (accords, buffer_id, légendes à venir) dans le dépôt public.
- Les journaux des workflows sont publics : ne jamais y afficher de secret.
- Liens YouTube : YouTube bloque les serveurs du cloud → le propriétaire dépose les FICHIERS dans la Release
  `entrees` (ou les envoie à Claude dans le chat, et Claude les dépose).
- NE JAMAIS modifier le dépôt `clipping-auto` (programme stream) : on copie, on n'importe pas.

## Façon de travailler avec le propriétaire
- Français simple (il écrit souvent en darija). Une seule étape à la fois (deux au maximum), puis attendre « c'est fait ».
- Ne jamais lui demander de coller des clés ou mots de passe dans le chat (secrets GitHub uniquement).
- Horaires toujours en heure de France (Europe/Paris).

## Droits d'auteur (important)
- Visuels autorisés UNIQUEMENT : banque lifestyle du propriétaire, clip officiel du MÊME artiste que le son
  (nom de fichier commençant par la clé de l'artiste), vidéos libres de droits Pexels. Jamais le clip d'un autre
  artiste, jamais une autre musique.
- Chaque artiste a `accord` (true/false) + `accord_note` dans `config/reglages.json` : **publication refusée**
  tant que `accord` n'est pas `true` (vérifié au planning ET juste avant l'envoi à Buffer).
- `contenu_de_marque` (false par défaut) : si true → « Publicité » dans la légende + rappel de cocher l'option
  « contenu de marque » à la main dans TikTok (l'API Buffer ne le permet pas à notre connaissance).

## Dossiers et mode react
- Releases : `sons` (morceaux), `entrees` (paroles, vidéos à découper), `banque-generale` (lifestyle, tous les artistes),
  `banque-reacts` (`<cle>__<streamer>_….mp4`, seulement pour cet artiste), `banque-<cle>` (anciennes vidéos de l'artiste).
- Mode `react` : streamer en haut (1/3, recadré sur sa caméra), vidéos de l'artiste / lifestyle en bas (2/3) sur le beat,
  paroles au milieu, son du morceau. Jamais le react d'un autre artiste ; streamer crédité dans la légende.

## Mode `base` (demandé le 24/11 — à retenir)
- Le propriétaire donne UNE vidéo (souvent par WeTransfer) : elle sert de BASE, avec SON PROPRE SON.
- Montage : la base reste le fil conducteur, images synchronisées avec le son ; ~30 % des mesures (`part_extraits`)
  sont remplacées par de petits extraits (banque de l'artiste + banque générale), jamais deux extraits de suite,
  jamais sur le 1er plan ; paroles de la vidéo au MILIEU, style néon blanc / turquoise, image assombrie.
- Lancement : workflow « Clips musique », mode `base`, source = le fichier déposé dans `entrees`.

## Crédit sur la vidéo
- 24/11 : plus de @artiste écrit sur la vidéo (`credit_sur_video: ""`) ; il sera remplacé par le nom de la chaîne
  quand elle existera (mettre "@nomdelachaine"). La légende TikTok garde la mention @artiste.

## Codes et réglages
- Codes courts `M0001`… dans `data/clips.json`. Clips 1080×1920, 30 i/s, ~16 Mo, 15–30 s par défaut.
- `auto_approuver: false` : rien ne part sans validation (tableau de bord, ou workflow « Valider ou rejeter »).
- Publication : TikTok seul pour commencer, compte Buffer « musique » (secret `BUFFER_API_KEY_MUSIQUE`),
  dépôt public tampon `media-temp` partagé avec le stream, fichiers préfixés `musique-`.

## Dépôt de fichiers
- Le propriétaire donne la matière par artiste (clips, vidéos) : lien WeTransfer / Drive dans le chat, ou fichiers.
- Claude écrit le lien dans `a-deposer/<dossier>/lien.txt` du dépôt PRIVÉ (ou les fichiers dans ce dossier),
  pousse, puis lance le workflow « Déposer des fichiers » (dossier + artiste). Jamais de lien dans un champ de
  workflow : les journaux du dépôt public sont visibles par tous.

## Retours du propriétaire (24/11) — à faire
- ✅ Typographie : style « neon » d'après son exemple (vibe lyrics) : UN mot à la fois, Montserrat Black énorme,
  blanc / bleu turquoise (turquoise #1FE5E0, choisi le 24/11) en alternance avec halo, images assombries (étalonnage « sombre »), pas d'accroche.
  Réglages : styles_paroles, couleurs_neon, etalonnage. Pas encore fait : la texture « usée » des lettres.
- Paroles (24/11) : 1) fichier fourni ; 2) son déjà sorti → paroles cherchées sur LRCLIB / lyrics.ovh (gratuits) ;
  les deux sont VÉRIFIÉES contre ce qui est entendu (≥ 35 % de mots communs) ; 3) sinon Whisper large-v3-turbo sur la
  voix séparée (Demucs), consigne avec le nom de l'artiste + `vocabulaire`, mots incertains cachés, `corrections`
  (général et par artiste) appliquées. Claude peut relire la transcription et proposer des corrections.
- Qualité (24/11) : « de bonnes vidéos ou rien » → `qualite_min_px` (720) écarte les sources trop petites ;
  encodage CRF 17 preset slow (plus de plafond 16 Mo) ; pas de zoom (tremblements) ; texte néon sans contour sombre.
  Les vidéos WhatsApp et les clips 640×360 de La Fouine sont SOUS ce seuil.
- Façon de travailler : il annonce l'artiste, donne la matière (vidéos, clips), puis Claude lance le montage.
