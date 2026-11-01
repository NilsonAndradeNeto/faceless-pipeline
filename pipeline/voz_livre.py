"""Narração grátis e sem cota: vozes neurais da Microsoft (Edge TTS), com o tempo de cada palavra.

O texto inteiro é falado de uma vez (entonação natural) e depois cada palavra é ligada de volta
à sua cena e à pontuação original (o Edge devolve as palavras sem pontuação e junta "384 mil").
"""
import asyncio
import logging
import re
import subprocess
from pathlib import Path

log = logging.getLogger("voz_livre")

VOZES = {"pt": "pt-BR-AntonioNeural", "en": "en-US-AndrewMultilingualNeural", "es": "es-MX-JorgeNeural"}


async def _falar(texto: str, voz: str, velocidade: str):
    import edge_tts
    com = edge_tts.Communicate(texto, voz, rate=velocidade, boundary="WordBoundary")
    audio, marcas = bytearray(), []
    async for pedaco in com.stream():
        if pedaco["type"] == "audio":
            audio += pedaco["data"]
        elif pedaco["type"] == "WordBoundary":
            marcas.append({"texto": pedaco["text"], "inicio": pedaco["offset"] / 1e7,
                           "fim": (pedaco["offset"] + pedaco["duration"]) / 1e7})
    return bytes(audio), marcas


def narrar_cenas(falas: list[str], lang: str, destino: Path, velocidade: str = "+8%", tentativas: int = 3):
    """Fala as cenas em sequência. Devolve (palavras, [(início, fim) de cada cena], duração).

    palavras = [{"palavra": "Lua,", "inicio": 1.2, "fim": 1.5, "cena": 0}, ...]
    """
    texto = " ".join(f.strip() for f in falas)
    for t in range(tentativas):
        try:
            audio, marcas = asyncio.run(_falar(texto, VOZES.get(lang, VOZES["en"]), velocidade))
            if marcas:
                break
        except Exception as e:  # o serviço às vezes derruba a conexão: tenta de novo
            log.warning("Edge TTS falhou (%d/%d): %s", t + 1, tentativas, e)
    else:
        raise RuntimeError("Edge TTS não respondeu")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(audio)

    # Onde começa cada cena dentro do texto inteiro
    limites, pos = [], 0
    for f in falas:
        limites.append(pos)
        pos += len(f.strip()) + 1

    palavras, cursor = [], 0
    for m in marcas:
        achou = texto.find(m["texto"], cursor)
        if achou < 0:  # o Edge às vezes muda a forma (números): segue sem pontuação
            achou, fim_txt = cursor, cursor
        else:
            fim_txt = achou + len(m["texto"])
        pont = re.match(r"[^\w\s]*", texto[fim_txt:]).group(0)  # pontuação colada depois da palavra
        cursor = fim_txt + len(pont)
        cena = max(i for i, ini in enumerate(limites) if ini <= achou)
        palavras.append({"palavra": m["texto"] + pont, "inicio": round(m["inicio"], 3), "fim": round(m["fim"], 3),
                         "cena": cena})

    duracao = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                    str(destino)], capture_output=True, text=True).stdout.strip())
    tempos = []
    for i in range(len(falas)):
        das = [p for p in palavras if p["cena"] == i]
        tempos.append((das[0]["inicio"] if das else (tempos[-1][1] if tempos else 0), das[-1]["fim"] if das else 0))
    # Cada cena vai do começo da sua fala até o começo da próxima (sem buracos)
    cenas = []
    for i, (ini, _) in enumerate(tempos):
        inicio = 0.0 if i == 0 else max(ini - 0.12, 0)
        fim = max(tempos[i + 1][0] - 0.12, inicio + 0.5) if i + 1 < len(tempos) else duracao + 0.7
        cenas.append((round(inicio, 3), round(fim, 3)))
    return palavras, cenas, round(duracao + 0.7, 3)
