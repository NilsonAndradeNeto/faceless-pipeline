"""Roteirista: transforma um tópico pesquisado em roteiro de Short (45–60s) + checagem de fatos.

Uso: uv run python -m agents.scriptwriter            (processa todos os tópicos pendentes)
     uv run python -m agents.scriptwriter --id ID    (só um)
Saída: storage/scripts/pending/{id}.md + {id}.meta.json
"""
import argparse
import logging
import re
import shutil

from agents.common import STORAGE, ler_json, salvar_json
from agents.llm_client import chat

log = logging.getLogger("scriptwriter")

IDIOMA = {"pt": "português do Brasil", "es": "espanhol latino-americano neutro"}

PROMPT_ROTEIRO = """Você é o roteirista-chefe de um canal de vídeos verticais de História e Mistérios reais
com milhões de views. Seu único objetivo: a pessoa NÃO consegue sair do vídeo antes do fim.
Escreva em {idioma}, como um contador de histórias falando com UMA pessoa, à noite, em voz baixa.

TEMA: {tema}

FONTES (todo fato concreto precisa estar aqui):
{fontes}

ANTES DE ESCREVER, escolha nas fontes:
- o detalhe mais perturbador/estranho/inacreditável → ele vai ser o CLÍMAX (perto do fim, não no começo);
- 1 detalhe humano concreto (um nome, um objeto, uma frase escrita, um número exato) que torna real;
- a pergunta que até hoje não tem resposta.

ESTRUTURA (165 a 190 palavras ≈ 65–75 segundos — obrigatório passar de 60s):
1. GANCHO (0–3s, máx. 12 palavras): joga a pessoa no meio da cena ou numa contradição.
   Ex.: "Em 1848, 105 homens saíram andando pelo gelo. Nenhum voltou."
   Proibido: "Você sabia", "Hoje vou contar", "Neste vídeo", perguntas genéricas.
2. PROMESSA (3–8s): uma frase que abre um ciclo que só fecha no fim ("E o que encontraram depois é pior.").
3. HISTÓRIA em ordem cronológica, em cenas, não em lista de fatos. A cada 2–3 frases, uma virada
   ("Mas...", "Só que...", "E então...") que deixa a situação mais grave ou mais estranha.
4. CLÍMAX: revela o detalhe mais forte com uma frase curta e seca, sozinha.
5. FINAL: fecha o ciclo da promessa e termina com a pergunta sem resposta, dirigida a quem assiste
   — deve fazer a pessoa querer comentar a opinião dela.

ESTILO:
- Frases de 4 a 14 palavras. Uma ideia por frase. Ritmo variado (curta. curta. uma mais longa.)
- Detalhes sensoriais que estão nas fontes (frio, escuridão, silêncio, o que foi encontrado).
- Números por extenso só se ficar natural para narração.
- Nada de adjetivos vazios ("incrível", "chocante", "misterioso") — mostre, não diga.
- Lendas e teorias só como "dizem que" / "uma teoria afirma". Nunca invente fato, data ou nome.
- Só o texto falado. Sem indicações de cena, emojis ou hashtags.

Responda em JSON:
{{
  "titulo": "até 55 caracteres; curiosidade específica, sem clickbait mentiroso",
  "roteiro": "texto completo para narração",
  "descricao": "1-2 frases para o post, termina com uma pergunta ao público",
  "hashtags": ["5 a 8 hashtags sem #, no idioma do vídeo"]
}}"""

PROMPT_CRITICA = """Você é editor de retenção de um canal viral de vídeos curtos. Avalie e MELHORE o roteiro abaixo.
Idioma: {idioma}. Ele deve ter 165–190 palavras.

ROTEIRO:
{roteiro}

Dê nota 0–10 para: gancho (os 3 primeiros segundos), ritmo, viradas, clímax, final que gera comentário.
Depois reescreva para chegar a 9+ em tudo:
- Se o gancho não for específico e chocante, troque por um melhor usando um fato que já está no roteiro.
- Corte qualquer frase que soe como enciclopédia ou lista.
- Garanta que o fato mais forte está no clímax e não foi entregue cedo demais.
- NÃO adicione fatos novos que não estejam no roteiro original.

Responda em JSON:
{{
  "notas": {{"gancho": 0, "ritmo": 0, "viradas": 0, "climax": 0, "final": 0}},
  "roteiro_melhorado": "..."
}}"""

PROMPT_PROVAS = """Liste CADA afirmação factual do ROTEIRO (nomes, datas, números, eventos, causas, objetos,
o que foi encontrado, quem fez o quê). Para cada uma, copie das FONTES a frase que a comprova,
EXATAMENTE como está escrita na fonte (copiar e colar, sem traduzir, sem resumir, 8 a 40 palavras).
Se nenhuma frase da fonte comprova, use "citacao": null. Seja rigoroso: detalhe dramatizado
que não está na fonte (ex.: "marcas de dentes" quando a fonte diz "marcas de faca") = null.

FONTES:
{fontes}

ROTEIRO:
{roteiro}

Responda em JSON: {{"afirmacoes": [{{"trecho": "trecho do roteiro", "citacao": "frase exata da fonte ou null"}}]}}"""

PROMPT_CORRECAO = """Reescreva o ROTEIRO removendo ou corrigindo os trechos SEM COMPROVAÇÃO listados abaixo.
Use só o que as FONTES dizem. Mantenha idioma ({idioma}), estilo, ritmo, gancho e 165–190 palavras.
Se o gancho ou o clímax dependiam de um trecho sem comprovação, troque por outro fato forte das fontes.

FONTES:
{fontes}

ROTEIRO:
{roteiro}

TRECHOS SEM COMPROVAÇÃO:
{problemas}

Responda em JSON: {{"roteiro_corrigido": "..."}}"""


def _normalizar(t: str) -> str:
    return re.sub(r"\W+", " ", t.lower()).strip()


def citacao_existe(citacao: str | None, fontes_norm: str) -> bool:
    """A citação precisa existir de verdade na fonte (tolera pontuação; exige 6+ palavras seguidas)."""
    if not citacao:
        return False
    palavras = _normalizar(citacao).split()
    if len(palavras) < 6:
        return False
    # Aceita se qualquer janela de 6 palavras seguidas da citação estiver na fonte
    return any(" ".join(palavras[i:i + 6]) in fontes_norm for i in range(len(palavras) - 5))


def checar_fatos(roteiro: str, fontes_txt: str, lang: str, rodadas: int = 2) -> tuple[str, list]:
    fontes_norm = _normalizar(fontes_txt)
    problemas = []
    for rodada in range(1, rodadas + 1):
        p = chat([{"role": "user", "content": PROMPT_PROVAS.format(fontes=fontes_txt, roteiro=roteiro)}],
                 json_mode=True, temperature=0, tarefa="provas")
        problemas = [a for a in p.get("afirmacoes", []) if not citacao_existe(a.get("citacao"), fontes_norm)]
        log.info("Checagem %d: %d afirmações, %d sem comprovação", rodada, len(p.get("afirmacoes", [])), len(problemas))
        if not problemas:
            return roteiro, []
        lista = "\n".join(f"- {a['trecho']}" for a in problemas)
        log.info("Corrigindo:\n%s", lista)
        roteiro = chat([{"role": "user", "content": PROMPT_CORRECAO.format(
            idioma=IDIOMA[lang], fontes=fontes_txt, roteiro=roteiro, problemas=lista)}],
            json_mode=True, temperature=0.3, tarefa="correcao")["roteiro_corrigido"]
    return roteiro, problemas


def formatar_fontes(fontes):
    return "\n\n".join(f"[{f['titulo']} — Wikipedia {f['lang']}]\n{f['texto']}" for f in fontes)


def escrever(topico: dict) -> dict:
    fontes_txt = formatar_fontes(topico["fontes"])
    log.info("Escrevendo roteiro: %s", topico["tema"])
    r = chat([{"role": "user", "content": PROMPT_ROTEIRO.format(
        idioma=IDIOMA[topico["lang"]], tema=topico["tema"], fontes=fontes_txt)}],
        json_mode=True, temperature=0.8, tarefa="roteiro")

    log.info("Editando para retenção...")
    e = chat([{"role": "user", "content": PROMPT_CRITICA.format(
        idioma=IDIOMA[topico["lang"]], roteiro=r["roteiro"])}],
        json_mode=True, temperature=0.6, tarefa="critica")
    editado = e.get("roteiro_melhorado") or r["roteiro"]
    log.info("Notas do editor (antes de reescrever): %s", e.get("notas"))

    log.info("Checando fatos (cada afirmação precisa de citação real da fonte)...")
    roteiro, pendentes = checar_fatos(editado, fontes_txt, topico["lang"])
    meta = {
        "id": topico["id"], "lang": topico["lang"], "tema": topico["tema"],
        "titulo": r["titulo"], "hook": roteiro.split(".")[0].strip() + ".",
        "descricao": r["descricao"], "hashtags": r["hashtags"],
        "palavras": len(roteiro.split()), "caracteres": len(roteiro),
        "notas_editor_antes": e.get("notas"),
        # Se sobrar algo sem comprovação após as rodadas, o painel de revisão destaca em vermelho
        "checagem": {"sem_comprovacao": [a["trecho"] for a in pendentes],
                     "confianca": "alta" if not pendentes else "baixa"},
        "versoes": {"rascunho": r["roteiro"], "editado": editado},
        "fontes": [{"titulo": f["titulo"], "url": f["url"]} for f in topico["fontes"]],
    }
    pasta = STORAGE / "scripts" / "pending"
    (pasta / f"{topico['id']}.md").write_text(roteiro.strip() + "\n", encoding="utf-8")
    salvar_json(pasta / f"{topico['id']}.meta.json", meta)
    log.info("Roteiro salvo: %d palavras, %d caracteres, confiança %s",
             meta["palavras"], meta["caracteres"], meta["checagem"]["confianca"])
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
