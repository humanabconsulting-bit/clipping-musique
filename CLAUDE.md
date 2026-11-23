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

## Codes et réglages
- Codes courts `M0001`… dans `data/clips.json`. Clips 1080×1920, 30 i/s, ~16 Mo, 15–30 s par défaut.
- `auto_approuver: false` : rien ne part sans validation (tableau de bord, ou workflow « Valider ou rejeter »).
- Publication : TikTok seul pour commencer, compte Buffer « musique » (secret `BUFFER_API_KEY_MUSIQUE`),
  dépôt public tampon `media-temp` partagé avec le stream, fichiers préfixés `musique-`.
