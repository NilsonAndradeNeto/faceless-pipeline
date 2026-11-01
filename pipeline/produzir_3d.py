"""Produz um Short do formato 3D "E se...?": narração grátis → animação → efeitos e trilha → MP4.

Uso: uv run python -m pipeline.produzir_3d --id ID     (roteiro em storage/e_se/pendentes ou aprovados)
     uv run python -m pipeline.produzir_3d --novo pt   (escreve um roteiro e já produz)
Saída: storage/shorts/ready/{id}.mp4
"""
import argparse
import logging
import random
import shutil
import subprocess
import time

import numpy as np
from scipy.io import wavfile

from agents.common import NUVEM, ROOT, STORAGE, ler_json, salvar_json
from pipeline.estudio3d import gravar
from pipeline.voz_livre import narrar_cenas

log = logging.getLogger("produzir_3d")

PASTA = STORAGE / "e_se"
SR = 44100


def _achar(sid: str):
    for sub in ("aprovados", "pendentes", "prontos"):
        arq = PASTA / sub / f"{sid}.json"
        if arq.exists():
            return arq
    raise FileNotFoundError(sid)


def _faixa_efeitos(cenas: list[dict], duracao: float, destino):
    """Whoosh em cada corte e pop quando um objeto aparece, numa faixa só."""
    sons = {n: wavfile.read(ROOT / "assets" / "sfx" / f"{n}.wav")[1].astype(np.float32) / 32767
            for n in ("whoosh", "pop")}
    faixa = np.zeros(int(SR * (duracao + 1)), dtype=np.float32)

    def por(nome, t, vol):
        s, i = sons[nome] * vol, int(max(t, 0) * SR)
        faixa[i:i + len(s)] += s[: len(faixa) - i]

    for i, c in enumerate(cenas):
        if i:
            por("whoosh", c["inicio"] - 0.12, 0.35)
        if c.get("objeto"):
            por("pop", c["inicio"] + 0.08, 0.5)
    wavfile.write(destino, SR, (np.clip(faixa, -1, 1) * 32767).astype(np.int16))


def produzir(sid: str, progresso=None) -> dict:
    avisar = progresso or (lambda *_: None)
    arq = _achar(sid)
    sb = ler_json(arq)
    trab = STORAGE / "work" / sid
    trab.mkdir(parents=True, exist_ok=True)
    # Retomada: voz e animação já feitas numa tentativa anterior são reaproveitadas
    tempos_arq = trab / "tempos.json"
    if tempos_arq.exists() and (trab / "voz.mp3").exists():
        palavras, tempos, duracao = (lambda d: (d["palavras"], d["tempos"], d["duracao"]))(ler_json(tempos_arq))
    else:
        avisar(0.02, "Gravando a narração")
        palavras, tempos, duracao = narrar_cenas([c["fala"] for c in sb["cenas"]], sb["lang"], trab / "voz.mp3")
        salvar_json(tempos_arq, {"palavras": palavras, "tempos": tempos, "duracao": duracao})
    for c, (ini, fim) in zip(sb["cenas"], tempos):
        c["inicio"], c["fim"] = ini, fim
    storyboard = {**sb, "palavras": palavras, "duracao": duracao, "escala_3d": 0.67}
    log.info("▶ 3D: %s (%.1fs, %d cenas)", sb["titulo"], duracao, len(sb["cenas"]))

    if not (trab / "animacao.mp4").exists():
        inicio = time.time()
        gravar(storyboard, trab / "animacao.parcial.mp4", gpu=not NUVEM,
               progresso=lambda f, txt: avisar(0.05 + 0.85 * f, txt))
        (trab / "animacao.parcial.mp4").rename(trab / "animacao.mp4")
        log.info("Animação gravada em %.0fs", time.time() - inicio)

    avisar(0.92, "Mixando voz, trilha e efeitos")
    _faixa_efeitos(sb["cenas"], duracao, trab / "efeitos.wav")
    musica = random.choice(sorted((ROOT / "assets" / "music3d").glob("*.mp3")))
    destino = STORAGE / "shorts" / "ready" / f"{sid}.mp4"
    destino.parent.mkdir(parents=True, exist_ok=True)
    filtro = (f"[1:a]loudnorm=I=-16:TP=-1.5,apad,asplit=2[voz][guia];"
              f"[2:a]volume=0.22,afade=t=out:st={max(duracao - 1.5, 0):.2f}:d=1.5[m];"
              f"[m][guia]sidechaincompress=threshold=0.04:ratio=6:attack=15:release=350[md];"
              f"[voz][md][3:a]amix=inputs=3:duration=first:normalize=0,alimiter=limit=0.95[a]")
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(trab / "animacao.mp4"), "-i", str(trab / "voz.mp3"),
                        "-stream_loop", "-1", "-i", str(musica), "-i", str(trab / "efeitos.wav"),
                        "-filter_complex", filtro, "-map", "0:v", "-map", "[a]", "-t", f"{duracao:.3f}",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(destino)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg (mixagem 3D) falhou: {r.stderr[-600:]}")

    sb.update(duracao_seg=round(duracao, 1), video=str(destino), producao={"etapa": "pronto", "progresso": 1.0})
    salvar_json(PASTA / "prontos" / f"{sid}.json", sb)
    if arq.parent.name != "prontos":
        arq.unlink()
    shutil.rmtree(trab, ignore_errors=True)
    log.info("✅ 3D pronto: %s (%.1fs)", destino, duracao)
    return sb


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--id")
    g.add_argument("--novo", choices=["pt", "en", "es"])
    a = ap.parse_args()
    if a.novo:
        from agents.roteiro_3d import escrever
        a.id = escrever(a.novo)["id"]
    print(produzir(a.id)["video"])
