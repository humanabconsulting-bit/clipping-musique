# Clipping Musique

Fabrique des clips verticaux TikTok (1080×1920) à partir de morceaux de rappeurs.
**Tout tourne dans le cloud (GitHub Actions), gratuitement** : rien à installer sur ton ordinateur.

## Comment ça marche
1. Tu déposes tes fichiers (clip, vidéo, son, paroles) dans la **Release `entrees`** du dépôt privé
   `clipping-musique-donnees` (sur github.com : Releases → `entrees` → ✏️ Modifier → glisser-déposer → Mettre à jour).
   Ou tu les envoies à Claude dans le chat, il les dépose pour toi.
2. Tu lances **Actions → « Clips musique » → Run workflow** (marche aussi dans l'appli GitHub du téléphone).
3. Le programme analyse le son (tempo, refrain, drop, voix), choisit les meilleurs passages, monte les clips
   et les range dans la Release `clips-AAAA-MM` avec un code `M0001`, `M0002`…
4. Tu regardes et tu valides (**Actions → « Valider ou rejeter »**, ou le tableau de bord).
5. **« Publier »** (toutes les 4 h) programme les vidéos validées sur TikTok via Buffer.

## Les 4 modes
| Mode | Tu donnes | Le programme fait |
|---|---|---|
| `clip` | le clip officiel (fichier) | trouve les meilleurs passages, recadre en 9:16 en suivant le visage du rappeur |
| `video` | une vidéo à toi | pareil que `clip` |
| `son` | seulement le son (mp3/wav/m4a) | choisit le passage, puis monte des visuels autorisés coupés sur le beat |
| `lifestyle` | le son + ta banque de vidéos | choisit les plans de la banque qui collent (énergie, couleurs, mouvement) |

Champs du workflow « Clips musique » :
- `source` : nom du fichier dans `entrees` (ex. `ninho_jefe_clip.mp4`) ;
- `artiste` : la clé de l'artiste dans `config/reglages.json` (ex. `ninho`) ;
- `titre` : titre du son (pour la légende et les hashtags) ;
- `nb_clips` (4), `duree` (15-30) ;
- `texte` : `tout` (accroche + paroles), `paroles`, `accroche`, `perso` (+ `texte_perso`), `aucun` ;
- `paroles_fichier` : `.txt` ou `.lrc` dans `entrees` (plus fiable que Whisper sur l'argot et la darija) ;
- `debut_fin` : forcer un passage, ex. `1:12-1:40` ;
- `visuels` (mode `son`) : `pexels`, `banque` ou `clip_artiste` (+ `--clip artiste_xxx.mp4` dans `options`) ;
- `options` : avancé, ex. `--tags nuit,voiture` (tags de la banque ou mots de recherche Pexels).

## Visuels autorisés (droits d'auteur)
Uniquement : ta banque lifestyle (Release `banque` + workflow « Banque : indexer »), le clip officiel du
**même** artiste (nom de fichier qui commence par sa clé, ex. `ninho_…`), ou Pexels (libre de droits).
Un artiste sans `"accord": true` dans les réglages n'est **jamais publié**.

## Mise en place (une seule fois)
1. Dépôt **public** `clipping-musique` (le code — minutes GitHub gratuites illimitées).
2. Dépôt **privé** `clipping-musique-donnees` (réglages, données, vidéos).
3. Secrets du dépôt public (Settings → Secrets and variables → Actions) :
   - `DONNEES_TOKEN` : jeton GitHub « fine-grained », accès *Contents : Read and write* aux dépôts
     `clipping-musique-donnees` et `media-temp` ;
   - `PEXELS_API_KEY` : clé gratuite sur pexels.com/api (pour les modes `son`) ;
   - `BUFFER_API_KEY_MUSIQUE` et `PUBLIC_REPO_TOKEN` : pour la publication (plus tard).

## Tester
- Sans aucun fichier ni clé : workflow « Test (mode démo) », ou « Clips musique » avec `demo` coché.
- Sur une machine (optionnel, pour développer) : Python 3.12, ffmpeg, polices Noto, puis
  `pip install -r requirements.txt` et `python -m musique.run --demo --mode clip`.

## Commandes
```
python -m musique.run --mode clip --source ninho_jefe_clip.mp4 --artiste ninho --titre "Jefe"
python -m musique.run --mode son --source ninho_jefe.mp3 --artiste ninho --titre "Jefe" --visuels pexels --tags "city night,car"
python -m musique.run --mode lifestyle --source ninho_jefe.mp3 --artiste ninho --tags nuit,voiture
python -m musique.run --mode clip --source x.mp4 --artiste ninho --debut 1:12 --fin 1:40 --paroles jefe.lrc
python -m musique.banque indexer
python -m musique.decider valider M0001 M0002
python -m musique.publier planning
python -m musique.recuperer M0012
```
