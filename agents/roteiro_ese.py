"""Roteirista do formato "E se...?" com imagens REAIS: para cada frase, diz o que filmar e como buscar.

Gemini primeiro; se estiver no limite, Groq na hora (perfil "flex"): esse formato não pode parar.
Uso: uv run python -m agents.roteiro_ese --lang pt
Saída: storage/e_se/pendentes/{id}.json
"""
import argparse
import json
import logging
import random

from agents.common import STORAGE, agora_iso, anexar_jsonl, salvar_json
from agents.llm_client import chat

log = logging.getLogger("roteiro_ese")

PASTA = STORAGE / "e_se"
HISTORICO = PASTA / "historico.jsonl"
IDIOMA = {"pt": "português do Brasil", "en": "English (US)", "es": "español latino"}

PROMPT = """Você é roteirista e editor de um canal viral de Shorts "E se...?" (vertical, 50–60s), estilo documentário:
cada frase narrada aparece coberta por um VÍDEO REAL de banco de imagens (Pixabay) mostrando exatamente o que é dito.

Escreva UM vídeo novo em {idioma}. Temas já feitos (não repita nem faça variação próxima):
{historico}
Território (pode ir além): ciência do cotidiano, espaço, corpo humano, animais, Terra/clima, economia, tecnologia,
"e se todo mundo fizesse X ao mesmo tempo". Premissa absurda, consequências REAIS em cadeia.
Escolha temas que rendem IMAGEM: natureza, animais, oceano, clima, espaço, cidades, comida, corpo humano.
Evite temas cujas cenas seriam só conceito (internet, leis, matemática), que não têm vídeo filmado bom.
TEMA DESTE VÍDEO (obrigatório): "E se {semente}?"

ROTEIRO
- Cena 1 = gancho: a pergunta "E se...?" em até 10 palavras.
- 9 a 12 cenas, uma frase cada (8 a 20 palavras), total 130–160 palavras.
- Gancho → consequência imediata → piora em cadeia → virada surpreendente → pergunta final pro público.
- Números e fatos VERDADEIROS. Linguagem falada, ritmo rápido. Sem emojis/hashtags na fala.

IMAGEM DE CADA CENA (o mais importante)
- "visual": em inglês, o que o espectador tem que VER, concreto e filmável (ex.: "close-up of a honeybee on a flower").
- "busca": 3 buscas em inglês para banco de vídeos, de 1 a 3 palavras, da mais específica à mais genérica
  (ex.: ["honeybee flower", "bee pollen", "bees"]). Só coisas que existem filmadas: nada de conceito abstrato.
  Para ideias abstratas, escolha a imagem concreta que melhor representa (falta de comida → "empty shelves").
- Não repita a mesma imagem em cenas diferentes.
- "texto_topo" (em ~40% das cenas): faixa de até 5 palavras ("Em 5 segundos", "Passo 2 · os mares"),
  com "destaque" = trecho colorido. Ou null.
- "contador" (só quando a fala cita um número real): {{"de": 0, "ate": 75, "rotulo": "das plantações",
  "prefixo": "", "sufixo": "%", "casas": 0}} — prefixo/sufixo só símbolos ("%", "x", "R$", "°C"). Ou null.

Responda só JSON:
{{"tema": "...", "titulo": "título do post, até 70 caracteres, com curiosidade",
  "descricao": "1–2 frases pro post + pergunta", "hashtags": ["5 a 7 sem #"],
  "cenas": [{{"fala": "...", "visual": "...", "busca": ["...", "...", "..."], "texto_topo": null, "contador": null}}]}}"""

PROMPT_CHECAGEM = """Revise este roteiro de Short ("E se...?") como editor de ciência rigoroso.
1. Todo número ou fato apresentado como real tem que estar correto; corrija o que estiver errado ou exagerado
   (mantendo o tamanho da frase). Especulação só como hipótese.
2. Os "contador" têm que bater com o número dito na mesma cena.
3. "visual" e "busca" têm que mostrar o assunto CONCRETO da fala e ser coisas que existem filmadas.
4. Mantenha campos, formato e idioma ({idioma}).
Devolva o JSON completo corrigido + "correcoes": ["o que mudou"] (lista vazia se nada).

{roteiro}"""

# Premissas com imagem filmada farta (o tema sai desta lista; a IA só escreve)
PREMISSAS = ["as abelhas sumissem", "a Lua sumisse", "os oceanos secassem", "a Terra parasse de girar",
             "todos os vulcões entrassem em erupção juntos", "o gelo da Antártida derretesse inteiro",
             "os tubarões sumissem", "a Amazônia desaparecesse", "chovesse sem parar por um ano",
             "todos os carros sumissem", "o Sol se apagasse", "as árvores parassem de produzir oxigênio",
             "os mosquitos fossem extintos", "um asteroide gigante atingisse o oceano", "as baleias voltassem a ser milhões",
             "a Terra ficasse sem nuvens", "todos os rios corressem ao contrário", "o planeta esquentasse 5 graus",
             "os dinossauros não tivessem sido extintos", "as formigas sumissem", "a água do mar virasse doce",
             "todo mundo parasse de comer carne", "as cidades apagassem as luzes por um mês", "os pássaros sumissem",
             "a Terra tivesse anéis como Saturno", "o deserto do Saara virasse floresta", "os corais morressem todos",
             "a neve caísse no mundo inteiro no mesmo dia", "os gatos sumissem", "o vento parasse de soprar"]


def _historico(lang: str) -> list[str]:
    if not HISTORICO.exists():
        return []
    return [json.loads(l)["tema"] for l in HISTORICO.read_text(encoding="utf-8").splitlines()
            if l.strip() and json.loads(l).get("lang") == lang]


def _validar(sb: dict) -> dict:
    cenas = []
    for c in sb.get("cenas", []):
        busca = [b for b in (c.get("busca") or []) if isinstance(b, str) and b.strip()][:4]
        if not c.get("fala") or not busca:
            continue
        c["busca"] = busca
        c["visual"] = str(c.get("visual") or busca[0])
        tt = c.get("texto_topo")
        c["texto_topo"] = tt if isinstance(tt, dict) and tt.get("texto") else None
        ct = c.get("contador")
        if isinstance(ct, dict) and isinstance(ct.get("ate"), (int, float)):
            for campo in ("prefixo", "sufixo"):  # só símbolos; texto vai pro rótulo
                if len(str(ct.get(campo) or "")) > 3:
                    ct["rotulo"] = f"{ct.get('rotulo') or ''} {ct[campo]}".strip()
                    ct[campo] = ""
            if not ct.get("sufixo") and str(ct.get("rotulo") or "").strip() in ("%", "x"):
                ct["sufixo"], ct["rotulo"] = ct["rotulo"].strip(), ""
            ct["rotulo"] = str(ct.get("rotulo") or "")[:30]
            c["contador"] = ct
        else:
            c["contador"] = None
        cenas.append(c)
    if len(cenas) < 5:
        raise ValueError("Roteiro veio com cenas de menos")
    sb["cenas"] = cenas
    return sb


def escrever(lang: str) -> dict:
    feitos = _historico(lang)
    prompt = PROMPT.format(idioma=IDIOMA[lang], historico="\n".join(f"- {t}" for t in feitos[-80:]) or "(nenhum)",
                           semente=random.choice([p for p in PREMISSAS if not any(p in f for f in feitos)] or PREMISSAS))
    sb = _validar(chat([{"role": "user", "content": prompt}], json_mode=True, temperature=0.9, tarefa="roteiro_ese",
                       perfil="flex"))
    revisado = chat([{"role": "user", "content": PROMPT_CHECAGEM.format(idioma=IDIOMA[lang],
                                                                        roteiro=json.dumps(sb, ensure_ascii=False))}],
                    json_mode=True, temperature=0.2, tarefa="checagem_ese", perfil="flex")
    try:
        correcoes = revisado.pop("correcoes", [])
        sb = _validar({**sb, **revisado})
    except Exception as e:
        log.warning("Revisão veio quebrada (%s); fica a versão original", e)
        correcoes = []
    palavras = sum(len(c["fala"].split()) for c in sb["cenas"])
    sid = f"{agora_iso()}_{lang}_ese"
    sb.update(id=sid, lang=lang, formato="e_se", palavras=palavras, correcoes=correcoes, criado=agora_iso())
    salvar_json(PASTA / "pendentes" / f"{sid}.json", sb)
    anexar_jsonl(HISTORICO, {"tema": sb.get("tema", sb.get("titulo")), "lang": lang, "id": sid})
    log.info("Roteiro E se: %s (%d cenas, %d palavras, %d correções)", sb["titulo"], len(sb["cenas"]), palavras,
             len(correcoes))
    return sb


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="pt", choices=list(IDIOMA))
    a = ap.parse_args()
    print(json.dumps(escrever(a.lang), ensure_ascii=False, indent=2))
