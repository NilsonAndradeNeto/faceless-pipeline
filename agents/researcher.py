"""Pesquisador: escolhe o próximo tema do niches.yaml e junta fatos da Wikipedia.

Uso: uv run python -m agents.researcher --lang pt [--tema "texto livre"]
Saída: storage/topics/pending/{timestamp}_{lang}.json
"""
import argparse
import logging

import requests

from agents.common import STORAGE, agora_iso, anexar_jsonl, config, idiomas, salvar_json
from agents.llm_client import chat

log = logging.getLogger("researcher")

HISTORICO = STORAGE / "topics" / "history.jsonl"
WIKI_HEADERS = {"User-Agent": "faceless-pipeline/0.1 (pesquisa educacional)"}
MAX_CHARS_FONTE = 10000


def temas_usados() -> set[str]:
    if not HISTORICO.exists():
        return set()
    import json
    return {json.loads(l)["tema"] for l in HISTORICO.read_text(encoding="utf-8").splitlines() if l.strip()}


def escolher_tema(lang: str) -> str:
    usados = temas_usados()
    candidatos = [t for t in config("niches")[lang] if not t.get("banido") and t["tema"] not in usados]
    if not candidatos:
        raise RuntimeError(f"Acabaram os temas de '{lang}' no niches.yaml. Adicione mais.")
    # Maior score primeiro; empate mantém a ordem do arquivo
    return max(candidatos, key=lambda t: t.get("score", 0))["tema"]


def termos_de_busca(tema: str, lang: str) -> dict:
    return chat([
        {"role": "system", "content": "Você ajuda a pesquisar na Wikipedia. Responda só JSON."},
        {"role": "user", "content": (
            f'Tema: "{tema}"\n'
            f'Dê o título mais provável do artigo da Wikipedia sobre isso em inglês e em "{lang}". '
            'Formato: {"en": "...", "local": "..."}'
        )},
    ], json_mode=True, temperature=0.2, tarefa="termos_busca")


def buscar_wikipedia(termo: str, lang: str) -> dict | None:
    api = f"https://{lang}.wikipedia.org/w/api.php"
    try:
        r = requests.get(api, headers=WIKI_HEADERS, timeout=20, params={
            "action": "query", "format": "json", "list": "search", "srsearch": termo, "srlimit": 1})
        hits = r.json().get("query", {}).get("search", [])
        if not hits:
            return None
        titulo = hits[0]["title"]
        r = requests.get(api, headers=WIKI_HEADERS, timeout=20, params={
            "action": "query", "format": "json", "prop": "extracts|info", "explaintext": 1,
            "inprop": "url", "titles": titulo, "redirects": 1})
        pagina = next(iter(r.json()["query"]["pages"].values()))
        texto = pagina.get("extract", "")
        if len(texto) < 300:
            return None
        return {"titulo": pagina["title"], "url": pagina.get("fullurl", ""), "lang": lang,
                "texto": texto[:MAX_CHARS_FONTE]}
    except Exception as e:
        log.warning("Falha ao buscar '%s' na Wikipedia %s: %s", termo, lang, e)
        return None


def pesquisar(lang: str, tema: str | None = None) -> dict:
    tema = tema or escolher_tema(lang)
    log.info("Tema escolhido (%s): %s", lang, tema)

    termos = termos_de_busca(tema, lang)
    fontes = [buscar_wikipedia(termos.get("en", tema), "en")]
    if lang != "en":  # em inglês a fonte local é a mesma
        fontes.append(buscar_wikipedia(termos.get("local", tema), lang))
    fontes = [f for f in fontes if f]
    if not fontes:
        raise RuntimeError(f"Não achei fonte na Wikipedia para: {tema}")
    log.info("Fontes: %s", ", ".join(f"{f['titulo']} ({f['lang']})" for f in fontes))

    topico = {"id": f"{agora_iso()}_{lang}", "lang": lang, "tema": tema, "fontes": fontes}
    salvar_json(STORAGE / "topics" / "pending" / f"{topico['id']}.json", topico)
    anexar_jsonl(HISTORICO, {"tema": tema, "lang": lang, "id": topico["id"]})
    return topico


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=idiomas(), required=True)
    ap.add_argument("--tema", help="força um tema específico (ignora o niches.yaml)")
    a = ap.parse_args()
    t = pesquisar(a.lang, a.tema)
    print(f"✅ Tópico salvo: storage/topics/pending/{t['id']}.json")
