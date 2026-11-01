"""Gera as trilhas animadas e os efeitos sonoros do formato 3D (síntese própria, sem direitos autorais).

Uso: uv run python -m scripts.gerar_sons_3d
Saída: assets/music3d/alegre_NN.mp3 e assets/sfx/{pop,whoosh,tick}.wav
"""
import subprocess

import numpy as np
from scipy.io import wavfile

from agents.common import ROOT

SR = 44100
NOTAS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def freq(semitom_de_a4: float) -> float:
    return 440.0 * 2 ** (semitom_de_a4 / 12)


def nota(nome: str, oitava: int) -> float:
    return freq(NOTAS[nome] - 9 + (oitava - 4) * 12)


def marimba(f: float, dur: float, vol: float = 0.5) -> np.ndarray:
    t = np.arange(int(SR * dur)) / SR
    som = np.sin(2 * np.pi * f * t) * np.exp(-t * 7) + 0.35 * np.sin(2 * np.pi * f * 4 * t) * np.exp(-t * 22)
    return vol * som * np.minimum(1, t / 0.004)


def baixo(f: float, dur: float, vol: float = 0.4) -> np.ndarray:
    t = np.arange(int(SR * dur)) / SR
    som = np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * 2 * f * t)
    return vol * som * np.exp(-t * 3.5) * np.minimum(1, t / 0.01)


def bumbo(vol: float = 0.8) -> np.ndarray:
    t = np.arange(int(SR * 0.35)) / SR
    f = 50 + 90 * np.exp(-t * 30)
    return vol * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)


def chimbal(rng, vol: float = 0.12) -> np.ndarray:
    t = np.arange(int(SR * 0.06)) / SR
    ruido = rng.standard_normal(len(t))
    ruido = np.diff(ruido, prepend=0)  # tira o grave: fica "tss"
    return vol * ruido * np.exp(-t * 70)


def colocar(faixa: np.ndarray, som: np.ndarray, inicio: float):
    i = int(inicio * SR)
    fim = min(len(faixa), i + len(som))
    if i < len(faixa):
        faixa[i:fim] += som[: fim - i]


def trilha(semente: int, bpm: int, tom: str, progressao: list[str], duracao: float = 80.0) -> np.ndarray:
    rng = np.random.default_rng(semente)
    faixa = np.zeros(int(SR * duracao))
    batida = 60 / bpm
    compasso = 4 * batida
    graus = {"I": [0, 4, 7], "IV": [5, 9, 12], "V": [7, 11, 14], "vi": [9, 12, 16], "ii": [2, 5, 9], "iii": [4, 7, 11]}
    raiz = NOTAS[tom]
    padrao = rng.permutation([0, 1, 2, 1, 2, 0, 2, 1])  # ordem do arpejo
    c = 0
    while c * compasso < duracao:
        acorde = graus[progressao[c % len(progressao)]]
        base = c * compasso
        for i in range(8):  # arpejo em colcheias
            semitom = raiz + acorde[padrao[i]] + 12
            if rng.random() < 0.88:
                colocar(faixa, marimba(freq(semitom - 9), batida * 1.6, 0.32), base + i * batida / 2)
        colocar(faixa, baixo(freq(raiz + acorde[0] - 9 - 24), compasso * 0.5), base)
        colocar(faixa, baixo(freq(raiz + acorde[0] - 9 - 24), compasso * 0.45), base + 2 * batida + batida / 2)
        if c >= 1:  # batida entra depois do primeiro compasso
            for b in range(4):
                if b in (0, 2):
                    colocar(faixa, bumbo(0.55), base + b * batida)
                colocar(faixa, chimbal(rng), base + b * batida + batida / 2)
        c += 1
    faixa *= np.minimum(1, np.arange(len(faixa)) / (SR * 1.5))
    faixa /= np.max(np.abs(faixa)) * 1.12
    return faixa


def efeitos(destino):
    rng = np.random.default_rng(3)
    t = np.arange(int(SR * 0.18)) / SR
    pop = np.sin(2 * np.pi * np.cumsum(300 + 900 * np.exp(-t * 40)) / SR) * np.exp(-t * 28)
    t2 = np.arange(int(SR * 0.45)) / SR
    ruido = rng.standard_normal(len(t2))
    corte = np.convolve(ruido, np.ones(18) / 18, mode="same")  # ruído abafado
    whoosh = corte * np.sin(np.pi * t2 / t2[-1]) ** 2 * 1.8
    t3 = np.arange(int(SR * 0.05)) / SR
    tick = np.sin(2 * np.pi * 1800 * t3) * np.exp(-t3 * 90)
    for nome, som in (("pop", pop), ("whoosh", whoosh), ("tick", tick)):
        som = som / np.max(np.abs(som)) * 0.8
        wavfile.write(destino / f"{nome}.wav", SR, (som * 32767).astype(np.int16))


def main():
    pasta = ROOT / "assets" / "music3d"
    pasta.mkdir(parents=True, exist_ok=True)
    receitas = [(11, 108, "C", ["I", "V", "vi", "IV"]), (22, 100, "G", ["vi", "IV", "I", "V"]),
                (33, 112, "F", ["I", "iii", "IV", "V"]), (44, 104, "D", ["I", "vi", "ii", "V"])]
    for n, (sem, bpm, tom, prog) in enumerate(receitas, 1):
        wav = pasta / f"alegre_{n:02d}.wav"
        wavfile.write(wav, SR, (trilha(sem, bpm, tom, prog) * 32767).astype(np.int16))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-b:a", "160k",
                        str(wav.with_suffix(".mp3"))], check=True)
        wav.unlink()
    sfx = ROOT / "assets" / "sfx"
    sfx.mkdir(parents=True, exist_ok=True)
    efeitos(sfx)
    print("trilhas e efeitos prontos")


if __name__ == "__main__":
    main()
