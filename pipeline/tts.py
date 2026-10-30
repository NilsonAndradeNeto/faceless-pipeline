"""Narração: ElevenLabs (principal) → Gemini TTS (reserva grátis) + tempos de cada palavra (para legenda).

ElevenLabs já devolve o tempo de cada caractere. O Gemini não: nesse caso o áudio passa pelo Whisper
do Groq (grátis) e os tempos são alinhados ao texto original do roteiro (mantém a grafia certa).

Uso: uv run python -m pipeline.tts --id ID
Saída: storage/audio/{id}.mp3 + storage/audio/{id}.words.json
"""
import argparse
import base64
import difflib
import logging
import os
import re
import subprocess
import unicodedata
import wave

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


GEMINI_TTS = ["gemini-3.8-flash-tts", "gemini-3.1-flash-tts-preview", "gemini-3.8-flash-lite-tts",
              "gemini-2.5-flash-preview-tts"]
DIRECAO = {"pt": "português do Brasil", "es": "espanhol latino-americano neutro"}


def gemini_tts(texto: str, lang: str, destino_wav) -> None:
    voz = config("voices").get("gemini", {}).get("voz", "Charon")
    # Direção curta no formato "Say ...: texto" — instrução longa o modelo acaba lendo em voz alta
    instrucao = f"Say in a deep, intriguing mystery-documentary narrator voice, natural pace: {texto}"
    ultimo = None
    for modelo in GEMINI_TTS:
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
                          headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"].strip()}, timeout=300, json={
                              "contents": [{"parts": [{"text": instrucao}]}],
                              "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                                  "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voz}}}}})
        if r.ok:
            pcm = base64.b64decode(r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
            with wave.open(str(destino_wav), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(pcm)
            log.info("Gemini TTS: %s, voz %s, %.1fs", modelo, voz, len(pcm) / 48000)
            return
        ultimo = f"{modelo}: {r.status_code} {r.text[:150]}"
        log.warning("Gemini TTS falhou — %s", ultimo)
    raise RuntimeError(f"Nenhuma voz disponível (ElevenLabs e Gemini falharam). Último erro: {ultimo}")


def _norm(p: str) -> str:
    p = unicodedata.normalize("NFKD", p.lower())
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in p if not unicodedata.combining(c)))


def tempos_por_whisper(audio, texto: str, lang: str) -> list[dict]:
    """Transcreve com Whisper (Groq) e alinha os tempos às palavras do roteiro original."""
    from groq import Groq

    with open(audio, "rb") as f:
        tr = Groq(api_key=os.environ["GROQ_API_KEY"]).audio.transcriptions.create(
            file=(os.path.basename(audio), f.read()), model="whisper-large-v3-turbo", language=lang,
            response_format="verbose_json", timestamp_granularities=["word"])
    ouvidas = [w if isinstance(w, dict) else w.model_dump() for w in (tr.words or [])]
    if not ouvidas:
        raise RuntimeError("Whisper não devolveu tempos de palavras")

    roteiro = texto.split()
    tempos: list = [None] * len(roteiro)
    sm = difflib.SequenceMatcher(a=[_norm(p) for p in roteiro], b=[_norm(w["word"]) for w in ouvidas],
                                 autojunk=False)
    for bloco in sm.get_matching_blocks():
        for k in range(bloco.size):
            w = ouvidas[bloco.b + k]
            tempos[bloco.a + k] = (w["start"], w["end"])

    # Palavras que o Whisper ouviu diferente (ex.: "1845" falado por extenso): interpola entre vizinhas
    fim_audio = ouvidas[-1]["end"]
    primeira = next((i for i, t in enumerate(tempos) if t), None)
    if primeira is None:
        raise RuntimeError("Áudio do Gemini não bate com o roteiro")
    # Palavras iniciais não reconhecidas: estima ~0,35s cada antes da primeira reconhecida (não a partir do 0,
    # que pode ter fala indesejada e vai ser cortado)
    for k in range(primeira):
        ini = max(tempos[primeira][0] - 0.35 * (primeira - k), 0.0)
        tempos[k] = (ini, ini + 0.35)
    i = 0
    while i < len(roteiro):
        if tempos[i] is None:
            j = i
            while j < len(roteiro) and tempos[j] is None:
                j += 1
            ini = tempos[i - 1][1] if i > 0 else 0.0
            fim = tempos[j][0] if j < len(roteiro) else fim_audio
            passo = (fim - ini) / (j - i)
            for k in range(i, j):
                tempos[k] = (ini + passo * (k - i), ini + passo * (k - i + 1))
            i = j
        i += 1
    alinhadas = sum(b.size for b in sm.get_matching_blocks())
    log.info("Legenda alinhada: %d de %d palavras batem com o Whisper", alinhadas, len(roteiro))
    return [{"palavra": p, "inicio": round(t[0], 3), "fim": round(t[1], 3)} for p, t in zip(roteiro, tempos)]


def aparar_inicio(audio, palavras: list[dict]) -> list[dict]:
    """Corta qualquer coisa falada antes da 1ª palavra do roteiro e desloca os tempos."""
    corte = max(palavras[0]["inicio"] - 0.15, 0.0)
    if corte < 0.3:
        return palavras
    log.warning("Cortando %.1fs de fala extra no início do áudio do Gemini", corte)
    tmp = audio.with_suffix(".tmp.mp3")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{corte:.3f}", "-i", str(audio),
                    "-b:a", "192k", str(tmp)], check=True)
    tmp.replace(audio)
    return [{**p, "inicio": round(p["inicio"] - corte, 3), "fim": round(p["fim"] - corte, 3)} for p in palavras]


def normalizar_audio(entrada, saida):
    """Loudness padrão de redes sociais (-14 LUFS)."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(entrada),
                    "-af", "loudnorm=I=-14:LRA=11:TP=-1.5", "-ar", "44100", "-b:a", "192k", str(saida)], check=True)


def narrar(script_id: str, pasta_script=None) -> dict:
    pasta_script = pasta_script or STORAGE / "scripts" / "approved"
    meta = ler_json(pasta_script / f"{script_id}.meta.json")
    texto = (pasta_script / f"{script_id}.md").read_text(encoding="utf-8").strip()

    pasta = STORAGE / "audio"
    final = pasta / f"{script_id}.mp3"

    try:
        audio, alinhamento = elevenlabs(texto, meta["lang"])
        bruto = pasta / f"{script_id}.raw.mp3"
        bruto.write_bytes(audio)
        normalizar_audio(bruto, final)
        palavras = palavras_de_alinhamento(alinhamento)
        voz = "elevenlabs"
    except Exception as e:
        log.warning("ElevenLabs indisponível (%s) — usando a voz do Gemini", str(e)[:150])
        bruto = pasta / f"{script_id}.raw.wav"
        gemini_tts(texto, meta["lang"], bruto)
        normalizar_audio(bruto, final)
        palavras = aparar_inicio(final, tempos_por_whisper(final, texto, meta["lang"]))
        voz = "gemini"
    bruto.unlink(missing_ok=True)

    salvar_json(pasta / f"{script_id}.words.json", palavras)
    meta["voz"] = voz
    salvar_json(pasta_script / f"{script_id}.meta.json", meta)
    duracao = palavras[-1]["fim"]
    log.info("Narração pronta (%s): %.1fs, %d palavras", voz, duracao, len(palavras))
    return {"audio": final, "palavras": palavras, "duracao": duracao}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--pasta", default="approved", help="pending | approved")
    a = ap.parse_args()
    narrar(a.id, STORAGE / "scripts" / a.pasta)
