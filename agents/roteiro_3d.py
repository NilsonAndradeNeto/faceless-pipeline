"""Roteirista do formato 3D "E se...?": escolhe a ideia e escreve o storyboard que o estúdio 3D anima.

Gemini primeiro; se estiver no limite, Groq na hora (perfil "flex"): esse formato não pode parar.
Uso: uv run python -m agents.roteiro_3d --lang pt
Saída: storage/e_se/pendentes/{id}.json
"""
import argparse
import json
import logging
import random

from agents.common import STORAGE, agora_iso, anexar_jsonl, ler_json, salvar_json
from agents.llm_client import chat

log = logging.getLogger("roteiro_3d")

PASTA = STORAGE / "e_se"
HISTORICO = PASTA / "historico.jsonl"

CENARIOS = {"cidade_noite": "cidade à noite, prédios com janelas acesas", "espaco": "espaço sideral, estrelas, planeta ao fundo",
            "estudio": "quarto/escritório aconchegante à noite (bom pra explicar)",
            "campo": "fazenda ao pôr do sol: plantação, celeiro, árvores (natureza, comida, animais, clima)",
            "oceano": "ilhota no mar com coqueiro (oceanos, praia, água, clima)"}
ACOES = {"fala": "explicando", "surpreso": "susto/espanto (bom pro gancho)", "aponta": "apontando pro objeto",
         "pensa": "mão no queixo, pensativo", "comemora": "pulando de alegria", "medo": "tremendo de medo",
         "acena": "acenando (bom pro final)", "anda": "entrando andando em cena"}
OBJETOS = ["terra", "lua", "sol", "foguete", "predio", "carro", "arvore", "dinheiro", "celular", "relogio", "meteoro",
           "pergunta"]
CAMERAS = {"frente": "plano médio", "close": "rosto bem perto (emoção forte)", "aberto": "plano geral do cenário",
           "baixo": "de baixo pra cima (dramático)", "orbita": "câmera girando", "destaque": "foco no objeto"}

IDIOMA = {"pt": "português do Brasil", "en": "English (US)", "es": "español latino"}

PROMPT = """Você é roteirista de um canal viral de Shorts chamado "E se...?" (vídeo vertical, 50–60s, animação 3D
em blocos com um personagem explorador e um robozinho-cubo chamado Bit).

Escreva UM vídeo novo em {idioma}. Temas que JÁ foram feitos (não repita nem faça variação próxima):
{historico}

Sugestões de território (pode ir além): ciência do cotidiano, espaço, corpo humano, Terra/clima, dinheiro e
economia, tecnologia, animais, "e se todo mundo fizesse X ao mesmo tempo". Prefira premissas absurdas mas com
consequências REAIS e surpreendentes, explicadas em cadeia. Tema-semente pra variar: "{semente}".

REGRAS DO ROTEIRO
- Cena 1 = gancho: a pergunta "E se...?" em até 10 palavras, que dá vontade de ver até o fim.
- 9 a 13 cenas, cada uma com UMA frase curta (6 a 18 palavras). Total de 130 a 160 palavras.
- Estrutura: gancho → primeira consequência (segundos/minutos) → piora em cadeia → virada surpreendente →
  pergunta final pro público comentar.
- Números e fatos têm que ser VERDADEIROS (distâncias, velocidades, quantidades). Nada inventado.
- Linguagem falada, frases simples, ritmo rápido. Sem emojis, sem hashtags no texto falado.

PARA CADA CENA ESCOLHA
- "cenario": {cenarios}
- "acao" do personagem: {acoes}
- "objeto" que aparece ao lado (ou null; aí o Bit reage no lugar): {objetos}
- "camera": {cameras}
- "texto_topo" (opcional, em ~40% das cenas): faixa curta no topo, até 5 palavras, ex. "Em 5 segundos" ou
  "Passo 2 · as marés", com "destaque" = trecho dele que fica colorido. Ou null.
- "contador" (opcional, só quando a fala cita um número real): {{"de": 0, "ate": 384400, "rotulo": "quilômetros",
  "prefixo": "", "sufixo": "", "casas": 0}}. prefixo/sufixo são SÓ símbolos curtos ("%", "x", "R$", "°C");
  o texto vai em "rotulo" (até 3 palavras). Ou null.
- Escolha o cenário que combina com o ASSUNTO da frase (comida/plantas → campo; mar/água → oceano;
  planetas/estrelas → espaco; cidade/economia/pessoas → cidade_noite; explicação → estudio).
Varie câmeras e ações; não use o mesmo cenário mais de 3 cenas seguidas.

Responda só JSON:
{{"tema": "...", "titulo": "título do post, até 70 caracteres, com curiosidade",
  "descricao": "1–2 frases pro post + pergunta", "hashtags": ["5 a 7 sem #"],
  "cenas": [{{"fala": "...", "cenario": "...", "acao": "...", "objeto": null, "camera": "...",
             "texto_topo": null, "contador": null}}]}}"""

PROMPT_CHECAGEM = """Revise este roteiro de Short ("E se...?") como um editor de ciência rigoroso.
1. Todo número ou fato apresentado como real tem que estar correto. Corrija o que estiver errado ou exagerado
   (reescreva a frase mantendo o tamanho). Especulação é permitida só quando apresentada como hipótese.
2. Os "contador" têm que bater com o número dito na fala da mesma cena.
3. Mantenha a estrutura, os campos e o idioma ({idioma}).
Devolva o JSON completo corrigido e acrescente "correcoes": ["o que mudou"] (lista vazia se nada).

{roteiro}"""

SEMENTES = ["a gravidade", "a internet", "os oceanos", "o Sol", "dinheiro", "o sono", "os insetos", "a luz", "o tempo",
            "as cores", "a Lua", "a eletricidade", "a água", "os dinossauros", "o celular", "a velocidade", "o frio",
            "a comida", "os ventos", "o som", "as abelhas", "o petróleo", "as florestas", "os vulcões", "o oxigênio"]


def _historico(lang: str) -> list[str]:
    if not HISTORICO.exists():
        return []
    return [json.loads(l)["tema"] for l in HISTORICO.read_text(encoding="utf-8").splitlines()
            if l.strip() and json.loads(l).get("lang") == lang]


def _validar(sb: dict) -> dict:
    """Garante que só vai pro estúdio o que o estúdio sabe desenhar."""
    cenas = []
    for c in sb.get("cenas", []):
        if not c.get("fala"):
            continue
        c["cenario"] = c.get("cenario") if c.get("cenario") in CENARIOS else "estudio"
        c["acao"] = c.get("acao") if c.get("acao") in ACOES else "fala"
        c["objeto"] = c.get("objeto") if c.get("objeto") in OBJETOS else None
        c["camera"] = c.get("camera") if c.get("camera") in CAMERAS else "frente"
        tt = c.get("texto_topo")
        c["texto_topo"] = tt if isinstance(tt, dict) and tt.get("texto") else None
        ct = c.get("contador")
        if isinstance(ct, dict) and isinstance(ct.get("ate"), (int, float)):
            # prefixo/sufixo são só símbolos ("%", "x", "R$"); texto vai pro rótulo embaixo do número
            for campo in ("prefixo", "sufixo"):
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
        raise ValueError("Roteiro 3D veio com cenas de menos")
    sb["cenas"] = cenas
    return sb


def escrever(lang: str) -> dict:
    lista = lambda d: "; ".join(f"{k} ({v})" for k, v in d.items())
    feitos = _historico(lang)
    prompt = PROMPT.format(idioma=IDIOMA[lang], historico="\n".join(f"- {t}" for t in feitos[-80:]) or "(nenhum)",
                           semente=random.choice(SEMENTES), cenarios=lista(CENARIOS), acoes=lista(ACOES),
                           objetos=", ".join(OBJETOS), cameras=lista(CAMERAS))
    sb = _validar(chat([{"role": "user", "content": prompt}], json_mode=True, temperature=0.9, tarefa="roteiro_3d",
                       perfil="flex"))
    revisado = chat([{"role": "user", "content": PROMPT_CHECAGEM.format(
        idioma=IDIOMA[lang], roteiro=json.dumps(sb, ensure_ascii=False))}],
        json_mode=True, temperature=0.2, tarefa="checagem_3d", perfil="flex")
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
    log.info("Roteiro 3D: %s (%d cenas, %d palavras, %d correções)", sb["titulo"], len(sb["cenas"]), palavras,
             len(correcoes))
    return sb


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="pt", choices=list(IDIOMA))
    a = ap.parse_args()
    r = escrever(a.lang)
    print(json.dumps(r, ensure_ascii=False, indent=2))
