"""Narração: ElevenLabs com timestamps por caractere → áudio + tempos de cada palavra (para legenda).

Uso: uv run python -m pipeline.tts --id ID
Saída: storage/audio/{id}.mp3 + storage/audio/{id}.words.json
"""
import argparse
import base64
import logging
import os
import subprocess

import requests

from agents.common import STORAGE, config, ler_json, salvar_json

log = logging.getLogger("tts")

API = "https://api.elevenlabs.io/v1"


class CotaEsgotada(Exception):
    pass


def caracteres_restantes() -> int:
    r = requests.get(f"{API}/user/subscription", headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]}, timeout=20)
    r.raise_for_status()
    d = r.json()
    return d["character_limit"] - d["character_count"]


def elevenlabs(texto: str, lang: str) -> tuple[bytes, dict]:
    vozes = config("voices")
    voz = vozes[lang]["principal"]
    restantes = caracteres_restantes()
    if restantes < len(texto):
        raise CotaEsgotada(f"ElevenLabs: faltam {len(texto)} caracteres, restam só {restantes}")
    log.info("ElevenLabs: voz %s, %d caracteres (restam %d)", voz["nome"], len(texto), restantes)
    r = requests.post(
        f"{API}/text-to-speech/{voz['id']}/with-timestamps",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
        json={"text": texto, "model_id": vozes["modelo"], "language_code": lang,
              "voice_settings": vozes["config_voz"]},
        timeout=180,
    )
    if r.status_code in (401, 402, 429) and "quota" in r.text.lower():
        raise CotaEsgotada(r.text[:200])
    r.raise_for_status()
    d = r.json()
    return base64.b64decode(d["audio_base64"]), d.get("normalized_alignment") or d["alignment"]


def palavras_de_alinhamento(al: dict) -> list[dict]:
    """Junta caracteres em palavras com início/fim em segundos."""
    palavras, atual, inicio = [], "", None
    for ch, ini, fim in zip(al["characters"], al["character_start_times_seconds"], al["character_end_times_seconds"]):
        if ch.isspace():
            if atual:
                palavras.append({"palavra": atual, "inicio": inicio, "fim": ultimo_fim})
            atual, inicio = "", None
            continue
        if inicio is None:
            inicio = ini
        atual += ch
        ultimo_fim = fim
    if atual:
        palavras.append({"palavra": atual, "inicio": inicio, "fim": ultimo_fim})
    return palavras


def normalizar_audio(entrada, saida):
    """Loudness padrão de redes sociais (-14 LUFS)."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(entrada),
                    "-af", "loudnorm=I=-14:LRA=11:TP=-1.5", "-ar", "44100", "-b:a", "192k", str(saida)], check=True)


def narrar(script_id: str, pasta_script=None) -> dict:
    pasta_script = pasta_script or STORAGE / "scripts" / "approved"
    meta = ler_json(pasta_script / f"{script_id}.meta.json")
    texto = (pasta_script / f"{script_id}.md").read_text(encoding="utf-8").strip()

    pasta = STORAGE / "audio"
    bruto = pasta / f"{script_id}.raw.mp3"
    final = pasta / f"{script_id}.mp3"

    audio, alinhamento = elevenlabs(texto, meta["lang"])
    bruto.write_bytes(audio)
    normalizar_audio(bruto, final)
    bruto.unlink()

    palavras = palavras_de_alinhamento(alinhamento)
    salvar_json(pasta / f"{script_id}.words.json", palavras)
    duracao = palavras[-1]["fim"]
    log.info("Narração pronta: %.1fs, %d palavras", duracao, len(palavras))
    return {"audio": final, "palavras": palavras, "duracao": duracao}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--pasta", default="approved", help="pending | approved")
    a = ap.parse_args()
    narrar(a.id, STORAGE / "scripts" / a.pasta)
