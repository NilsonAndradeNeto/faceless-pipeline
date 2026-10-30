"""Planejador visual: divide a narração em cenas curtas e decide o que mostrar em cada uma.

Estratégia (o visual SEMPRE tem que bater com o que está sendo falado):
  1. Foto/gravura REAL tirada do próprio artigo da Wikipedia usado como fonte (nunca de busca solta,
     que traz homônimos) — só quando a cena cita aquela pessoa/navio/lugar/documento.
  2. Imagem gerada por IA que mostra exatamente a frase narrada, com estilo visual fixo.

Uso: uv run python -m agents.visual_planner --id ID
Saída: storage/scripts/{id}.scenes.json
"""
import argparse
import logging
import re

import requests

from agents.common import STORAGE, ler_json, salvar_json
from agents.llm_client import chat

log = logging.getLogger("visual_planner")

MIN_CENA, MAX_CENA = 2.0, 5.0
WIKI_HEADERS = {"User-Agent": "FacelessHistoryPipeline/0.1 (educational history shorts; python-requests)"}

# Estilo fixo acrescentado a todo prompt de IA: dá unidade visual ao vídeo
ESTILO_IA = ("cinematic still, dark moody atmosphere, muted desaturated colors, dramatic low-key lighting, "
             "film grain, highly detailed, historically accurate, vertical composition, no text, no watermark, "
             "no gore, no modern objects, no screens, no tattoos")

PROMPT = """Você é diretor de arte de um canal de mistérios históricos (vídeo vertical 9:16).
Tema: {tema}
Época/lugar: deduza do tema e das cenas.

IMAGENS REAIS DISPONÍVEIS (tiradas do artigo da Wikipedia sobre o tema):
{reais}

Para cada cena numerada abaixo:
- "real": número da imagem real SÓ se ela mostra exatamente o que a cena cita (a pessoa citada, o navio
  citado, o mapa do lugar citado, o documento citado). Use cada imagem real no máximo uma vez. Senão null.
  Nunca use bandeiras, brasões ou mapas de localização genéricos.
- "ia": prompt em inglês (25–45 palavras) para gerar uma imagem que mostre LITERALMENTE o que a frase narra,
  com elementos concretos da época (roupas, objetos, lugar, clima). Se a frase é abstrata ("ninguém sabe",
  "e você?"), mostre um detalhe simbólico concreto ligado ao tema. Pessoas: sem rosto em close de pessoas reais
  identificáveis. Sem sangue, sem cadáveres explícitos (as redes punem) — sugira pelo contexto
  (sombras, objetos deixados, pegadas, ossos discretos ao longe).
  Sempre preencha "ia", mesmo quando escolher "real" (é o plano B).

CENAS:
{cenas}

Responda em JSON:
{{"epoca": "época e lugar em inglês, curto, ex.: 'Canadian Arctic, 1840s, Royal Navy expedition'",
  "cenas": [{{"n": 1, "real": null, "ia": "..."}}]}}"""


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
    resultado[0]["inicio"] = 0.0
    for c in resultado:
        c["duracao"] = round(c["fim"] - c["inicio"], 3)
    return resultado


def imagens_do_artigo(fontes: list[dict], limite: int = 25) -> list[dict]:
    """Imagens usadas dentro dos artigos-fonte, com descrição (garante que são do tema certo)."""
    imagens, vistos = [], set()
    for f in fontes:
        lang = f.get("lang") or f["url"].split("//")[1].split(".")[0]
        try:
            r = requests.get(f"https://{lang}.wikipedia.org/w/api.php", headers=WIKI_HEADERS, timeout=30,
                             params={"action": "query", "format": "json", "titles": f["titulo"], "generator": "images",
                                     "gimlimit": 50, "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
                                     "iiurlwidth": 1280})
            paginas = r.json().get("query", {}).get("pages", {}).values()
        except Exception as e:
            log.warning("Não consegui listar imagens de %s: %s", f["titulo"], e)
            continue
        for p in paginas:
            info = (p.get("imageinfo") or [{}])[0]
            nome = p.get("title", "")
            if nome in vistos or info.get("mime") not in ("image/jpeg", "image/png"):
                continue
            if info.get("width", 0) < 500 or re.search(r"(?i)icon|logo|flag|symbol|commons-|wiki", nome):
                continue
            meta = info.get("extmetadata", {})
            desc = re.sub(r"<[^>]+>", "", meta.get("ImageDescription", {}).get("value", "")).strip()
            # Bandeira/brasão/mapa de localização não ilustram cena nenhuma
            if re.search(r"(?i)\bflag\b|bandeira|coat of arms|bras[ãa]o|locator|location map|mapa de localiza", f"{nome} {desc}"):
                continue
            licenca = re.sub(r"<[^>]+>", "", meta.get("LicenseShortName", {}).get("value", "")).strip()
            vistos.add(nome)
            imagens.append({"nome": nome.split(":", 1)[-1], "descricao": desc[:160], "licenca": licenca,
                            "url": info.get("thumburl") or info.get("url"),
                            "autor": re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "?")).strip()[:80]})
    return imagens[:limite]


def planejar(script_id: str, pasta_script=None) -> list[dict]:
    pasta_script = pasta_script or STORAGE / "scripts" / "approved"
    meta = ler_json(pasta_script / f"{script_id}.meta.json")
    palavras = ler_json(STORAGE / "audio" / f"{script_id}.words.json")
    cenas = dividir_cenas(palavras)

    reais = imagens_do_artigo(meta["fontes"])
    log.info("%d imagens reais disponíveis nos artigos-fonte", len(reais))
    lista_reais = "\n".join(f"{i}. {r['nome']} — {r['descricao']}" for i, r in enumerate(reais, 1)) or "(nenhuma)"
    lista_cenas = "\n".join(f"{c['n']}. ({c['duracao']:.1f}s) {c['texto']}" for c in cenas)

    r = chat([{"role": "user", "content": PROMPT.format(tema=meta["tema"], reais=lista_reais, cenas=lista_cenas)}],
             json_mode=True, temperature=0.5, tarefa="visual", perfil="roteiro")  # qualidade: Gemini primeiro
    por_n = {c["n"]: c for c in r.get("cenas", [])}
    # A época vai na frente de todo prompt: sem isso a IA mistura navio moderno, tela, tatuagem...
    epoca = r.get("epoca") or meta["tema"]
    usados = set()
    for c in cenas:
        v = por_n.get(c["n"], {})
        real = v.get("real")
        escolhida = None
        if isinstance(real, int) and 1 <= real <= len(reais) and real not in usados:
            escolhida = reais[real - 1]
            usados.add(real)
        c["visual"] = {"real": escolhida,
                       "ia": f"{epoca}, period-accurate clothing and technology. {v.get('ia') or meta['tema']}, {ESTILO_IA}"}

    salvar_json(STORAGE / "scripts" / f"{script_id}.scenes.json", cenas)
    log.info("%d cenas (média %.1fs): %d com imagem real, %d com IA", len(cenas),
             sum(c["duracao"] for c in cenas) / len(cenas), len(usados), len(cenas) - len(usados))
    return cenas


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--pasta", default="approved")
    a = ap.parse_args()
    planejar(a.id, STORAGE / "scripts" / a.pasta)
