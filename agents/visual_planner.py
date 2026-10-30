"""Planejador visual: divide a narração em cenas curtas e escolhe o que mostrar em cada uma.

Cortes rápidos (2–5s) seguram retenção em vídeo vertical.
Uso: uv run python -m agents.visual_planner --id ID
Saída: storage/scripts/{id}.scenes.json
"""
import argparse
import logging

from agents.common import STORAGE, ler_json, salvar_json
from agents.llm_client import chat

log = logging.getLogger("visual_planner")

MIN_CENA, MAX_CENA = 2.0, 5.0

PROMPT = """Você é editor de vídeo de um canal de mistérios históricos (vídeo vertical 9:16).
Tema: {tema}

Para cada cena numerada abaixo, escolha o visual. Regras:
- "wikimedia": busca em inglês para o Wikimedia Commons quando a cena cita algo REAL e específico
  (pessoa, navio, lugar, objeto, documento, mapa). Inclua ano/época ou contexto para evitar homônimos.
  Ex.: "HMS Erebus 1845 Franklin", "John Franklin portrait", "King William Island map".
  Use null se a cena não cita nada específico.
- "pixabay": busca de VÍDEO em inglês, 1–3 palavras, de clima/atmosfera para a cena
  (ex.: "arctic ice", "dark ocean storm", "old ship", "candle dark"). Sempre preencha.
- "ia": prompt em inglês para gerar imagem quando nada real existir: cinematic, dark, historically
  accurate, 19th century style, sem texto. Sempre preencha.
- Varie: não repita a mesma busca em cenas seguidas. Priorize wikimedia em cenas com nomes/objetos reais.

CENAS:
{cenas}

Responda em JSON: {{"cenas": [{{"n": 1, "wikimedia": "... ou null", "pixabay": "...", "ia": "..."}}]}}"""


def dividir_cenas(palavras: list[dict]) -> list[dict]:
    """Agrupa palavras em cenas: quebra em fim de frase/vírgula, respeitando 2–5s."""
    cenas, atual = [], []
    for i, p in enumerate(palavras):
        atual.append(p)
        dur = p["fim"] - atual[0]["inicio"]
        fim_frase = p["palavra"][-1] in ".!?"
        pausa = p["palavra"][-1] in ",;:"
        ultima = i == len(palavras) - 1
        if ultima or (fim_frase and dur >= MIN_CENA) or (pausa and dur >= 3.0) or dur >= MAX_CENA:
            cenas.append(atual)
            atual = []
    if atual:
        cenas.append(atual)

    resultado = []
    for n, ws in enumerate(cenas, 1):
        resultado.append({"n": n, "texto": " ".join(w["palavra"] for w in ws), "inicio": ws[0]["inicio"]})
    # Cada cena vai do seu início até o início da próxima (sem buracos)
    for atual, prox in zip(resultado, resultado[1:]):
        atual["fim"] = prox["inicio"]
    resultado[-1]["fim"] = palavras[-1]["fim"] + 0.6
    for c in resultado:
        c["duracao"] = round(c["fim"] - c["inicio"], 3)
    return resultado


def planejar(script_id: str, pasta_script=None) -> list[dict]:
    pasta_script = pasta_script or STORAGE / "scripts" / "approved"
    meta = ler_json(pasta_script / f"{script_id}.meta.json")
    palavras = ler_json(STORAGE / "audio" / f"{script_id}.words.json")
    cenas = dividir_cenas(palavras)
    if cenas[0]["inicio"] > 0:
        cenas[0]["inicio"], cenas[0]["duracao"] = 0.0, round(cenas[0]["fim"], 3)

    lista = "\n".join(f"{c['n']}. ({c['duracao']:.1f}s) {c['texto']}" for c in cenas)
    r = chat([{"role": "user", "content": PROMPT.format(tema=meta["tema"], cenas=lista)}],
             json_mode=True, temperature=0.5, tarefa="visual")
    por_n = {c["n"]: c for c in r.get("cenas", [])}
    for c in cenas:
        v = por_n.get(c["n"], {})
        c["busca"] = {"wikimedia": v.get("wikimedia") or None,
                      "pixabay": v.get("pixabay") or meta["tema"],
                      "ia": v.get("ia") or f"cinematic dark historical scene, {meta['tema']}"}

    salvar_json(STORAGE / "scripts" / f"{script_id}.scenes.json", cenas)
    log.info("%d cenas planejadas (média %.1fs)", len(cenas), sum(c["duracao"] for c in cenas) / len(cenas))
    return cenas


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--pasta", default="approved")
    a = ap.parse_args()
    planejar(a.id, STORAGE / "scripts" / a.pasta)
