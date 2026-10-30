"""Roteirista: transforma um tópico pesquisado em roteiro de Short (45–60s) + checagem de fatos.

Uso: uv run python -m agents.scriptwriter            (processa todos os tópicos pendentes)
     uv run python -m agents.scriptwriter --id ID    (só um)
Saída: storage/scripts/pending/{id}.md + {id}.meta.json
"""
import argparse
import logging
import shutil

from agents.common import STORAGE, ler_json, salvar_json
from agents.llm_client import chat

log = logging.getLogger("scriptwriter")

IDIOMA = {"pt": "português do Brasil", "es": "espanhol latino-americano neutro"}

PROMPT_ROTEIRO = """Você é roteirista de um canal de Shorts sobre História e Mistérios reais.
Escreva em {idioma}, tom de narrador intrigante, frases curtas, fáceis de ouvir.

TEMA: {tema}

FONTES (use APENAS fatos que estejam aqui):
{fontes}

REGRAS DO ROTEIRO:
- 120 a 150 palavras no total (≈ 50 segundos narrados).
- Frase 1 = gancho de no máximo 12 palavras que crie curiosidade imediata. Nada de "Você sabia".
- Depois: contexto rápido → 2 ou 3 fatos que aumentam o mistério → virada ou pergunta em aberto.
- Última frase deve conectar com o começo (loop) ou provocar comentário.
- Datas, números e nomes só se estiverem nas fontes. Nada inventado.
- Lendas e teorias só como "dizem que" / "uma teoria afirma", nunca como fato.
- Só o texto falado. Sem indicações de cena, sem emojis, sem hashtags no roteiro.

Responda em JSON:
{{
  "titulo": "título do Short, até 60 caracteres, gera curiosidade",
  "hook": "a primeira frase do roteiro",
  "roteiro": "texto completo para narração",
  "descricao": "descrição curta para o post (1-2 frases) terminando com uma pergunta ao público",
  "hashtags": ["5 a 8 hashtags sem #, no idioma do vídeo"],
  "afirmacoes": ["cada fato concreto do roteiro, um por item"]
}}"""

PROMPT_CHECAGEM = """Você é checador de fatos rigoroso. Compare o ROTEIRO com as FONTES.

FONTES:
{fontes}

ROTEIRO:
{roteiro}

Para cada afirmação factual do roteiro, verifique se as fontes sustentam.
Se algo não for sustentado ou estiver exagerado, reescreva o roteiro corrigindo SÓ o necessário,
mantendo idioma, tom, tamanho (120–150 palavras) e o gancho.

Responda em JSON:
{{
  "problemas": [{{"trecho": "...", "motivo": "..."}}],
  "roteiro_corrigido": "roteiro final (igual ao original se não houver problemas)",
  "confianca": "alta | media | baixa"
}}"""


def formatar_fontes(fontes):
    return "\n\n".join(f"[{f['titulo']} — Wikipedia {f['lang']}]\n{f['texto']}" for f in fontes)


def escrever(topico: dict) -> dict:
    fontes_txt = formatar_fontes(topico["fontes"])
    log.info("Escrevendo roteiro: %s", topico["tema"])
    r = chat([{"role": "user", "content": PROMPT_ROTEIRO.format(
        idioma=IDIOMA[topico["lang"]], tema=topico["tema"], fontes=fontes_txt)}],
        json_mode=True, temperature=0.8, tarefa="roteiro")

    log.info("Checando fatos...")
    c = chat([{"role": "user", "content": PROMPT_CHECAGEM.format(fontes=fontes_txt, roteiro=r["roteiro"])}],
             json_mode=True, temperature=0.1, tarefa="checagem")

    roteiro = c.get("roteiro_corrigido") or r["roteiro"]
    meta = {
        "id": topico["id"], "lang": topico["lang"], "tema": topico["tema"],
        "titulo": r["titulo"], "hook": roteiro.split(".")[0].strip() + ".",
        "descricao": r["descricao"], "hashtags": r["hashtags"],
        "palavras": len(roteiro.split()), "caracteres": len(roteiro),
        "checagem": {"problemas": c.get("problemas", []), "confianca": c.get("confianca", "?"),
                     "roteiro_original": r["roteiro"] if roteiro != r["roteiro"] else None},
        "fontes": [{"titulo": f["titulo"], "url": f["url"]} for f in topico["fontes"]],
    }
    pasta = STORAGE / "scripts" / "pending"
    (pasta / f"{topico['id']}.md").write_text(roteiro.strip() + "\n", encoding="utf-8")
    salvar_json(pasta / f"{topico['id']}.meta.json", meta)
    log.info("Roteiro salvo: %d palavras, %d caracteres, confiança %s, %d correção(ões)",
             meta["palavras"], meta["caracteres"], meta["checagem"]["confianca"], len(meta["checagem"]["problemas"]))
    return meta


def processar_pendentes(somente_id: str | None = None):
    pendentes = STORAGE / "topics" / "pending"
    feitos = STORAGE / "topics" / "done"
    feitos.mkdir(exist_ok=True)
    arquivos = sorted(pendentes.glob(f"{somente_id or '*'}.json"))
    if not arquivos:
        log.info("Nenhum tópico pendente.")
    for arq in arquivos:
        try:
            escrever(ler_json(arq))
            shutil.move(arq, feitos / arq.name)
        except Exception:
            log.exception("Falha ao escrever roteiro de %s (tópico fica pendente)", arq.name)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--id")
    processar_pendentes(ap.parse_args().id)
