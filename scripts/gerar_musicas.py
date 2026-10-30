"""Compõe trilhas originais de suspense/mistério (dark ambient) por síntese — zero direito autoral.

Uso: uv run python scripts/gerar_musicas.py [--quantidade 8] [--duracao 100]
Saída: assets/music/trilha_XX.mp3
"""
import argparse
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve, lfilter

SR = 44100
ROOT = Path(__file__).resolve().parent.parent
PASTA = ROOT / "assets" / "music"

# Progressões em graus da escala menor natural (i, VI, iv, v, VII, III)
PROGRESSOES = [[0, 5, 3, 4], [0, 3, 5, 6], [0, 6, 5, 4], [0, 2, 5, 3], [0, 5, 2, 6]]
MENOR = [0, 2, 3, 5, 7, 8, 10]
PENTA_MENOR = [0, 3, 5, 7, 10]


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def lowpass(x, corte):
    a = np.exp(-2 * np.pi * corte / SR)
    return lfilter([1 - a], [1, -a], x)


def reverb(x, rng, segundos=3.5, mix=0.45):
    n = int(SR * segundos)
    ir = rng.standard_normal(n) * np.exp(-np.linspace(0, 7, n))
    ir = lowpass(ir, 4000)
    molhado = fftconvolve(x, ir)[: len(x)]
    molhado /= np.max(np.abs(molhado)) + 1e-9
    return (1 - mix) * x / (np.max(np.abs(x)) + 1e-9) + mix * molhado


def acorde(grau, tonica):
    notas = [MENOR[(grau + i) % 7] + 12 * ((grau + i) // 7) for i in (0, 2, 4)]
    return [tonica + n for n in notas]


def pad(t, freqs, rng):
    s = np.zeros_like(t)
    for f in freqs:
        for detune in (-0.12, 0.0, 0.11):
            fase = rng.uniform(0, 2 * np.pi)
            ff = f * 2 ** (detune / 12)
            s += np.sin(2 * np.pi * ff * t + fase) + 0.25 * np.sin(4 * np.pi * ff * t + fase)
    return s


def compor(seed: int, duracao: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    tonica = int(rng.choice([45, 46, 47, 48, 50, 52]))  # A2..E3
    prog = PROGRESSOES[seed % len(PROGRESSOES)]
    tempo_acorde = rng.uniform(7, 11)
    n = int(SR * duracao)
    t = np.arange(n) / SR
    mix = np.zeros(n)

    # Drone grave contínuo (tônica + quinta), respira devagar
    drone = np.sin(2 * np.pi * hz(tonica - 12) * t) + 0.5 * np.sin(2 * np.pi * hz(tonica - 5) * t)
    mix += 0.35 * drone * (0.75 + 0.25 * np.sin(2 * np.pi * t / 13))

    # Pads de acordes com crossfade longo
    xf = int(SR * 2.5)
    i = 0
    while i * tempo_acorde < duracao:
        ini = int(i * tempo_acorde * SR)
        fim = min(int((i + 1) * tempo_acorde * SR) + xf, n)
        seg_t = t[ini:fim]
        som = pad(seg_t, [hz(m) for m in acorde(prog[i % len(prog)], tonica)], rng)
        env = np.ones(fim - ini)
        r = min(xf, len(env) // 2)
        env[:r] = np.linspace(0, 1, r)
        env[-r:] = np.linspace(1, 0, r)
        mix[ini:fim] += 0.12 * lowpass(som, 900) * env
        i += 1

    # Vento: ruído filtrado com abertura lenta
    vento = lowpass(rng.standard_normal(n), 500) * (0.5 + 0.5 * np.sin(2 * np.pi * t / rng.uniform(9, 17)))
    mix += 0.5 * vento / (np.max(np.abs(vento)) + 1e-9) * 0.25

    # Sinos esparsos (pentatônica menor, oitava alta)
    for _ in range(int(duracao / rng.uniform(4, 7))):
        ini = int(rng.uniform(2, duracao - 4) * SR)
        f = hz(tonica + 24 + int(rng.choice(PENTA_MENOR)))
        k = np.arange(int(SR * 4)) / SR
        sino = (np.sin(2 * np.pi * f * k) + 0.3 * np.sin(2 * np.pi * f * 2.76 * k)) * np.exp(-k * 1.4)
        fim = min(ini + len(sino), n)
        mix[ini:fim] += 0.07 * sino[: fim - ini]

    # Batida grave de tensão (em metade das trilhas)
    if seed % 2 == 0:
        k = np.arange(int(SR * 1.2)) / SR
        boom = np.sin(2 * np.pi * 48 * k * np.exp(-k * 2)) * np.exp(-k * 4)
        periodo = rng.uniform(3.5, 5.5)
        for s in np.arange(periodo * 2, duracao - 2, periodo):
            ini = int(s * SR)
            fim = min(ini + len(boom), n)
            mix[ini:fim] += 0.45 * boom[: fim - ini]

    mix = reverb(mix, rng)
    fade = int(SR * 3)
    mix[:fade] *= np.linspace(0, 1, fade)
    mix[-fade:] *= np.linspace(1, 0, fade)
    return (mix / (np.max(np.abs(mix)) + 1e-9) * 0.9).astype(np.float32)


def salvar(audio: np.ndarray, destino: Path):
    tmp = destino.with_suffix(".wav")
    estereo = np.stack([audio, np.roll(audio, int(SR * 0.012))], axis=1)  # leve abertura estéreo
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((estereo * 32767).astype(np.int16).tobytes())
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp),
                    "-af", "loudnorm=I=-20:TP=-2", "-b:a", "192k", str(destino)], check=True)
    tmp.unlink()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--quantidade", type=int, default=8)
    ap.add_argument("--duracao", type=float, default=100)
    a = ap.parse_args()
    PASTA.mkdir(parents=True, exist_ok=True)
    for s in range(1, a.quantidade + 1):
        destino = PASTA / f"trilha_{s:02d}.mp3"
        salvar(compor(s, a.duracao), destino)
        print(f"🎵 {destino.name}")
