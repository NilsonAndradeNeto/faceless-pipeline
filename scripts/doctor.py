"""Checa a saúde do pipeline: chaves, ferramentas e espaço em disco.

Uso: uv run python scripts/doctor.py
Nunca imprime o valor das chaves.
"""
import os
import shutil
import sys
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
SETTINGS = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))

OK, FALHA, PULADO = "✅", "❌", "⏭️ "
resultados = []


def registrar(nome, status, detalhe=""):
    resultados.append((status, nome, detalhe))
    print(f"{status} {nome}" + (f" — {detalhe}" if detalhe else ""))


def chave(nome):
    return os.getenv(nome, "").strip()


def checar_groq():
    k = chave("GROQ_API_KEY")
    if not k:
        return registrar("Groq", PULADO, "GROQ_API_KEY vazia")
    try:
        from groq import Groq

        modelo = SETTINGS["llm"]["primario"]["model"]
        r = Groq(api_key=k).chat.completions.create(
            model=modelo,
            messages=[{"role": "user", "content": "Responda em português, numa frase curta: qual é a capital do Peru?"}],
            max_completion_tokens=300,
        )
        registrar("Groq", OK, f"{modelo} respondeu: {r.choices[0].message.content.strip()!r}")
    except Exception as e:
        registrar("Groq", FALHA, f"{type(e).__name__}: {str(e)[:150]}")


def checar_openai():
    k = chave("OPENAI_API_KEY")
    if not k:
        return registrar("OpenAI (fallback)", PULADO, "OPENAI_API_KEY vazia")
    try:
        from openai import OpenAI

        OpenAI(api_key=k).chat.completions.create(
            model="gpt-4o-mini", messages=[{"role": "user", "content": "ok"}], max_tokens=2
        )
        registrar("OpenAI (fallback)", OK)
    except Exception as e:
        registrar("OpenAI (fallback)", FALHA, f"{type(e).__name__}: {str(e)[:150]}")


def checar_pexels():
    k = chave("PEXELS_API_KEY")
    if not k:
        return registrar("Pexels", PULADO, "PEXELS_API_KEY vazia")
    r = requests.get("https://api.pexels.com/videos/search", params={"query": "ocean", "per_page": 1},
                     headers={"Authorization": k}, timeout=15)
    registrar("Pexels", OK if r.ok else FALHA, "" if r.ok else f"HTTP {r.status_code}")


def checar_pixabay():
    k = chave("PIXABAY_API_KEY")
    if not k:
        return registrar("Pixabay", PULADO, "PIXABAY_API_KEY vazia")
    r = requests.get("https://pixabay.com/api/videos/", params={"key": k, "q": "ocean", "per_page": 3}, timeout=15)
    registrar("Pixabay", OK if r.ok else FALHA, "" if r.ok else f"HTTP {r.status_code}")


def checar_elevenlabs():
    k = chave("ELEVENLABS_API_KEY")
    if not k:
        return registrar("ElevenLabs", PULADO, "ELEVENLABS_API_KEY vazia")
    r = requests.get("https://api.elevenlabs.io/v1/user/subscription", headers={"xi-api-key": k}, timeout=15)
    if r.ok:
        d = r.json()
        restante = d.get("character_limit", 0) - d.get("character_count", 0)
        registrar("ElevenLabs", OK, f"plano {d.get('tier')}, {restante} caracteres restantes")
    else:
        registrar("ElevenLabs", FALHA, f"HTTP {r.status_code}")


def checar_ferramentas():
    for t in ("ffmpeg", "docker"):
        registrar(t, OK if shutil.which(t) else FALHA)
    livre = shutil.disk_usage(ROOT).free / 1e9
    registrar("Espaço livre no disco do projeto", OK if livre >= 20 else FALHA, f"{livre:.0f} GB")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print("🩺 Doctor — saúde do pipeline\n")
    checar_ferramentas()
    checar_groq()
    checar_openai()
    checar_pexels()
    checar_pixabay()
    checar_elevenlabs()
    falhas = sum(1 for s, *_ in resultados if s == FALHA)
    print(f"\n{'Tudo certo.' if not falhas else f'{falhas} problema(s) encontrado(s).'}")
    sys.exit(1 if falhas else 0)
