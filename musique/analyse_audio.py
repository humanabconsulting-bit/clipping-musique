"""Analyse d'un morceau (gratuite, librosa, sans IA) : tempo, beats, mesures, énergie, refrain, drop.

Résultat par BEAT (un « temps ») :
- energie   : volume (RMS) normalisé 0–1 ;
- basses    : énergie sous 150 Hz normalisée 0–1 ;
- repetition: à quel point ce passage revient ailleurs dans le morceau (matrice d'auto-similarité
              chroma + MFCC, diagonales renforcées) → le REFRAIN a la répétition la plus forte ;
- drop      : montée brusque d'énergie / de basses juste après un creux ;
- voix      : part d'énergie dans la bande de la voix (300–3400 Hz) — remplacée par la densité
              de mots quand la transcription existe.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

SR = 22050
HOP = 512


def _norm(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return x
    bas, haut = np.percentile(x, 5), np.percentile(x, 95)
    return np.clip((x - bas) / max(haut - bas, 1e-9), 0, 1)


def _lisser(x: np.ndarray, n: int) -> np.ndarray:
    if n <= 1 or x.size < n:
        return x
    return np.convolve(x, np.ones(n) / n, mode="same")


def analyser(audio: Path) -> dict:
    import librosa
    from scipy.ndimage import median_filter

    y, sr = librosa.load(str(audio), sr=SR, mono=True)
    duree = len(y) / sr
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP)
    tempo, beats = librosa.beat.beat_track(onset_envelope=onset, sr=sr, hop_length=HOP, trim=False)
    tempo = float(np.atleast_1d(tempo)[0])
    if len(beats) < 16:  # morceau sans beat net : grille régulière à 90 BPM
        tempo = tempo or 90.0
        beats = librosa.time_to_frames(np.arange(0, duree, 60 / tempo), sr=sr, hop_length=HOP)
    temps_beats = librosa.frames_to_time(beats, sr=sr, hop_length=HOP)

    # Premier temps de la mesure : la phase (0–3) où la grosse caisse (basses) frappe le plus fort,
    # + les changements d'énergie (les sections changent presque toujours sur un 1er temps)
    S_mel = librosa.feature.melspectrogram(y=y, sr=sr, hop_length=HOP, fmax=200, n_mels=16)
    attaque_basse = librosa.onset.onset_strength(S=librosa.power_to_db(S_mel), sr=sr, hop_length=HOP)
    rms_f = librosa.feature.rms(y=y, hop_length=HOP)[0]
    saut = np.abs(np.diff(np.log(rms_f + 1e-6), prepend=0))
    saut = np.convolve(saut, np.ones(5) / 5, mode="same")
    forces = [float(attaque_basse[beats[p::4]].sum() / max(attaque_basse.sum(), 1e-9)
                    + saut[beats[p::4]].sum() / max(saut.sum(), 1e-9)) for p in range(4)]
    phase = int(np.argmax(forces))

    S = np.abs(librosa.stft(y, hop_length=HOP, n_fft=2048))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    rms = librosa.feature.rms(S=S, frame_length=2048)[0]
    basses = S[freqs < 150].sum(axis=0)
    bande_voix = S[(freqs >= 300) & (freqs <= 3400)].sum(axis=0) / np.maximum(S.sum(axis=0), 1e-9)

    def par_beat(x: np.ndarray) -> np.ndarray:
        # pad=True : un segment avant le 1er temps puis un par temps → on garde « du temps i au suivant »
        return librosa.util.sync(x[np.newaxis, :], beats, aggregate=np.mean, pad=True)[0][1: len(beats) + 1]

    e_b, b_b, v_b = par_beat(rms), par_beat(basses), par_beat(bande_voix)

    # Auto-similarité (chroma + timbre), diagonales renforcées par un filtre en « lag »
    chroma = librosa.feature.chroma_stft(S=S ** 2, sr=sr)
    mfcc = librosa.feature.mfcc(S=librosa.power_to_db(librosa.feature.melspectrogram(S=S ** 2, sr=sr)), n_mfcc=13)
    feats = np.vstack([librosa.util.normalize(chroma, axis=0), librosa.util.normalize(mfcc, axis=0) * 0.25])
    fb = librosa.util.sync(feats, beats, aggregate=np.median, pad=True)[:, 1: len(beats) + 1]
    n = fb.shape[1]
    if n >= 24:
        R = librosa.segment.recurrence_matrix(fb, mode="affinity", k=max(2, int(n * 0.07)), sym=True,
                                              width=8)
        L = librosa.segment.recurrence_to_lag(R, pad=False)
        L = median_filter(L, size=(1, 9))
        R = librosa.segment.lag_to_recurrence(L)
        rep = np.asarray(R.sum(axis=1)).ravel()
    else:
        rep = np.zeros(n)
    rep = _lisser(_norm(rep), 8)

    e_n, b_n = _norm(e_b), _norm(b_b)
    # Drop : énergie (et basses) des 8 temps suivants nettement plus forte que des 8 précédents
    drop = np.zeros(n)
    force = 0.6 * e_n + 0.4 * b_n
    for i in range(8, n - 4):
        avant, apres = force[max(0, i - 8):i].mean(), force[i:i + 8].mean()
        drop[i] = max(0.0, apres - avant) * (1.0 if avant < 0.55 else 0.6)
    drop = _norm(drop) if drop.max() > 0.15 else drop

    return {
        "duree": round(duree, 2),
        "tempo": round(tempo, 1),
        "beats": [round(float(t), 3) for t in temps_beats],
        "phase_mesure": phase,
        "energie": [round(float(x), 3) for x in e_n],
        "basses": [round(float(x), 3) for x in b_n],
        "repetition": [round(float(x), 3) for x in rep],
        "drop": [round(float(x), 3) for x in drop],
        "voix_bande": [round(float(x), 3) for x in _norm(v_b)],
    }


def mesures(analyse: dict) -> list[float]:
    """Instants des débuts de mesure (toutes les 4 temps, en partant du premier temps détecté)."""
    b = analyse["beats"]
    return [b[i] for i in range(analyse.get("phase_mesure", 0), len(b), 4)]


if __name__ == "__main__":
    import json
    import sys
    a = analyser(Path(sys.argv[1]))
    print(json.dumps({k: v for k, v in a.items() if not isinstance(v, list)}, ensure_ascii=False))
    print(f"{len(a['beats'])} temps, {len(mesures(a))} mesures")
