"""Outils vidéo/son (copiés de clipping-auto/montage.py puis adaptés à la musique).

Repris tels quels : executer, telecharger, telecharger_section, duree_video, volume_max, plus_long_silence,
transcrire (faster-whisper mot par mot), coupe_precise, encodage ciblé ~16 Mo.
Nouveau : extraire_audio, infos_video, debit_cible, fond_flou (mode « vidéo centrée sur fond flou »), demo_*.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

LARGEUR, HAUTEUR, IPS = 1080, 1920, 30
TAILLE_CIBLE_MO = 16


class ErreurTelechargement(RuntimeError):
    pass


def executer(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} a échoué : {r.stderr[-800:]}")


# ---------------------------------------------------------------- téléchargement (yt-dlp)
def _ytdlp(args: list[str], destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["yt-dlp", "-q", "--no-warnings", *args, "-o", str(destination)],
                       capture_output=True, text=True)
    if not destination.exists():  # yt-dlp peut ajouter une extension
        autres = sorted(destination.parent.glob(destination.stem + ".*"))
        if autres:
            autres[0].rename(destination)
    if r.returncode != 0 or not destination.exists():
        bloque = any(m in (r.stderr or "") for m in ("Sign in to confirm", "bot", "429", "403"))
        raise ErreurTelechargement(
            ("YouTube bloque les serveurs du cloud. " if bloque else "Téléchargement impossible. ")
            + "Dépose le fichier dans la Release « entrees » (ou envoie-le à Claude dans le chat) "
            + f"puis relance avec son nom de fichier. Détail : {(r.stderr or '').strip()[-300:]}")
    return destination


def telecharger(url: str, destination: Path) -> Path:
    return _ytdlp(["-f", "bv*[height<=1080]+ba/b[height<=1080]/b", "--merge-output-format", "mp4"], destination)


def telecharger_section(url: str, debut: int, fin: int, destination: Path) -> Path:
    """Télécharge seulement le passage [debut, fin] d'une vidéo (YouTube…)."""
    return _ytdlp(["-f", "bv*[height<=1080]+ba/b[height<=1080]/b", "--merge-output-format", "mp4",
                   "--download-sections", f"*{debut}-{fin}"], destination)


# ---------------------------------------------------------------- infos
def duree_video(video: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(video)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def infos_video(video: Path) -> dict:
    """Largeur, hauteur, i/s, durée, présence d'image et de son."""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)],
                       capture_output=True, text=True)
    j = json.loads(r.stdout or "{}")
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    a = next((s for s in j.get("streams", []) if s.get("codec_type") == "audio"), None)
    ips = 30.0
    if v and v.get("avg_frame_rate", "0/0") != "0/0":
        n, d = v["avg_frame_rate"].split("/")
        ips = float(n) / float(d or 1)
    rot = 0
    if v:
        for sd in v.get("side_data_list", []) or []:
            rot = int(sd.get("rotation", 0) or 0)
        rot = rot or int((v.get("tags") or {}).get("rotate", 0) or 0)
    w, h = (v or {}).get("width", 0), (v or {}).get("height", 0)
    if abs(rot) in (90, 270):
        w, h = h, w
    return {"largeur": w, "hauteur": h, "ips": ips, "video": bool(v), "son": bool(a),
            "duree": float((j.get("format") or {}).get("duration", 0) or 0)}


def extraire_audio(source: Path, destination: Path, debut: float = 0, duree: float | None = None,
                   taux: int = 44100, mono: bool = False) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(debut, 0):.3f}", "-i", str(source)]
    if duree:
        cmd += ["-t", f"{duree:.3f}"]
    cmd += ["-vn", "-ac", "1" if mono else "2", "-ar", str(taux), str(destination)]
    executer(cmd)
    return destination


def debit_cible(duree: float) -> int:
    """Débit vidéo (kb/s) pour que le fichier reste sous ~16 Mo (lecture directe dans le tableau de bord)."""
    return max(1200, min(6000, int(TAILLE_CIBLE_MO * 8 * 1000 / max(duree, 1)) - 160))


def options_encodage(duree: float) -> list[str]:
    kbps = debit_cible(duree)
    return ["-c:v", "libx264", "-preset", "veryfast", "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.3)}k",
            "-bufsize", f"{kbps * 2}k", "-pix_fmt", "yuv420p", "-r", str(IPS),
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-movflags", "+faststart"]


def chemin_ass(ass: Path) -> str:
    return str(ass).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


# ---------------------------------------------------------------- transcription (faster-whisper)
def transcrire(audio: Path, modele: str = "small", langue: str | None = None) -> tuple[list[dict], str]:
    """Liste de mots {debut, fin, mot, phrase} + langue détectée. Vide si Whisper n'est pas installé.
    Pour la musique : pas de filtre VAD (il coupe les voix sur un beat fort)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return [], ""
    import numpy as np
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(audio), "-vn", "-ac", "1", "-ar", "16000",
                        "-f", "f32le", "-"], capture_output=True)
    son = np.frombuffer(r.stdout, dtype=np.float32)
    if son.size == 0:
        return [], ""
    m = WhisperModel(modele, device="cpu", compute_type="int8", cpu_threads=4)
    segments, info = m.transcribe(son, language=langue or None, word_timestamps=True, vad_filter=False,
                                  beam_size=1, condition_on_previous_text=False)
    mots: list[dict] = []
    for seg in segments:
        for k, w in enumerate(seg.words or []):
            t = w.word.strip()
            if not t:
                continue
            # « c » + « 'est », « ? », « , » … : recollés au mot précédent (sinon « 'EST » s'affiche seul)
            colle = mots and (t[0] in "'’,.;:!?…)»-" or mots[-1]["mot"][-1:] in "'’-" or all(not ch.isalnum() for ch in t))
            if colle and k > 0:
                mots[-1]["mot"] += t
                mots[-1]["fin"] = w.end
            else:
                mots.append({"debut": w.start, "fin": w.end, "mot": t, "phrase": k == 0,
                             "proba": round(getattr(w, "probability", 1.0), 2)})
    for x in mots:
        x["mot"] = x["mot"].lstrip(",.;:!?…") or x["mot"]
    # Whisper « hallucine » parfois des génériques sur la musique : on les retire
    mots = [x for x in mots if not re.search(r"(sous-titr|amara|merci d'avoir regard|subtitles by)", x["mot"].lower())]
    return mots, getattr(info, "language", "") or ""


def coupe_precise(mots: list[dict], duree: float, duree_min: float, marge: float = 10.0) -> tuple[float, float]:
    """Début/fin « propres » : début d'une phrase, fin après une phrase, jamais au milieu d'un mot."""
    if not mots:
        return 0.0, duree
    debut = 0.0
    starts = [w["debut"] for w in mots if w.get("phrase") and w["debut"] <= marge]
    if starts:
        debut = max(0.0, starts[0] - 0.25)
    elif 1.5 < mots[0]["debut"] <= marge:
        debut = max(0.0, mots[0]["debut"] - 0.4)
    fin = duree
    for i in range(len(mots) - 1, -1, -1):
        w = mots[i]
        if w["fin"] < duree - marge:
            break
        suivant = mots[i + 1] if i + 1 < len(mots) else None
        if suivant is None or suivant.get("phrase"):
            fin = min(duree, w["fin"] + 0.6)
            break
    if fin - debut < duree_min:
        return 0.0, duree
    return debut, fin


# ---------------------------------------------------------------- contrôles son
def volume_max(video: Path) -> float:
    """Volume le plus fort de la piste son, en dB (-91 = silence total ou pas de son)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(video), "-vn", "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"max_volume:\s*(-?[\d.]+) dB", r.stderr)
    return float(m.group(1)) if m else -91.0


def plus_long_silence(video: Path, seuil_db: int = -45) -> float:
    """Durée (s) du plus long passage sans son."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(video), "-vn", "-af", f"silencedetect=n={seuil_db}dB:d=2",
                        "-f", "null", "-"], capture_output=True, text=True)
    durees = [float(x) for x in re.findall(r"silence_duration:\s*([\d.]+)", r.stderr)]
    debut_ouvert = re.findall(r"silence_start:\s*([\d.]+)", r.stderr)
    if len(debut_ouvert) > len(durees):
        durees.append(max(0.0, duree_video(video) - float(debut_ouvert[-1])))
    return max(durees, default=0.0)


# ---------------------------------------------------------------- mode « fond flou » (repris du stream)
def filtre_fond_flou(entree: str = "[0:v]", sortie: str = "[cadre]") -> str:
    """Vidéo entière au centre sur un fond flou (même vidéo agrandie + flou)."""
    return (f"{entree}split=2[ff_a][ff_b];"
            f"[ff_a]scale={LARGEUR}:{HAUTEUR}:force_original_aspect_ratio=increase,crop={LARGEUR}:{HAUTEUR},boxblur=25:2[ff_fond];"
            f"[ff_b]scale={LARGEUR}:-2[ff_avant];"
            f"[ff_fond][ff_avant]overlay=(W-w)/2:(H-h)/2,setsar=1{sortie}")


# ---------------------------------------------------------------- mode démo (sans aucune clé ni fichier)
def demo_son(destination: Path, secondes: int = 96, bpm: int = 90) -> Path:
    """Fabrique un « morceau » de synthèse avec couplets calmes et refrains forts (qui reviennent),
    pour tester la détection du refrain et du drop sans fichier réel."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    import numpy as np
    import soundfile as sf
    sr = 44100
    t = np.arange(int(secondes * sr)) / sr
    beat = 60 / bpm
    son = np.zeros_like(t)
    rng = np.random.default_rng(7)
    mesure = 4 * beat
    for k in range(int(secondes / beat)):
        d = k * beat
        i0, i1 = int(d * sr), min(len(t), int((d + 0.25) * sr))
        tt = t[i0:i1] - d
        num_mesure = int(d / mesure)
        refrain = (num_mesure // 4) % 2 == 1          # 4 mesures couplet, 4 mesures refrain…
        force = 1.0 if refrain else 0.35
        if k % 2 == 0:                                 # grosse caisse (plus forte sur le 1er temps)
            son[i0:i1] += force * (1.0 if k % 4 == 0 else 0.6) * np.sin(2 * np.pi * (60 + 80 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 12)
        else:                                          # caisse claire
            son[i0:i1] += 0.4 * force * rng.normal(0, 1, i1 - i0) * np.exp(-tt * 25)
    for m in range(int(secondes / mesure)):            # mélodie : le refrain répète toujours la même
        refrain = (m // 4) % 2 == 1
        notes = [440, 523, 587, 523] if refrain else [220 + 20 * ((m * 7) % 5), 247, 262 + 10 * (m % 3), 233]
        for j, f in enumerate(notes):
            d = m * mesure + j * beat
            i0, i1 = int(d * sr), min(len(t), int((d + beat) * sr))
            tt = t[i0:i1] - d
            son[i0:i1] += (0.25 if refrain else 0.1) * np.sin(2 * np.pi * f * tt) * np.exp(-tt * 2)
    son = 0.8 * son / max(1e-6, np.abs(son).max())
    sf.write(str(destination), np.stack([son, son], axis=1), sr)
    return destination


def demo_video(destination: Path, secondes: int = 20, couleur: str = "testsrc2") -> Path:
    """Fausse vidéo 16:9 (mode démo)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    executer(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
              "-i", f"{couleur}=size=1280x720:rate=30:duration={secondes}",
              "-f", "lavfi", "-i", f"sine=frequency=330:duration={secondes}",
              "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(destination)])
    return destination
