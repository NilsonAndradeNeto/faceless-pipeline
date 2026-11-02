"""Roteirista do formato 3D "E se...?": escolhe a ideia e escreve o storyboard que o estúdio 3D anima.

Regra de ouro: cada plano MOSTRA o assunto da frase (abelhas falando de abelha, prateleira vazia falando de
mercado). O que não existe na biblioteca de modelos (studio3d/modelos.js), a IA desenha em blocos no próprio
roteiro ("modelos_novos").

Gemini primeiro; se estiver no limite, Groq na hora (perfil "flex"): esse formato não pode parar.
Uso: uv run python -m agents.roteiro_3d --lang pt
Saída: storage/e_se/pendentes/{id}.json
"""
import argparse
import json
import logging
import random
import re

from agents.common import ROOT, STORAGE, agora_iso, anexar_jsonl, salvar_json
from agents.llm_client import chat

log = logging.getLogger("roteiro_3d")

PASTA = STORAGE / "e_se"
HISTORICO = PASTA / "historico.jsonl"

CENARIOS = {
    "campo": "fazenda ao pôr do sol (natureza, comida, plantas, animais, clima)",
    "oceano": "ilhota no mar com coqueiro (praia, água, ondas, clima)",
    "fundo_mar": "embaixo d'água com algas e raios de luz (peixes, baleias, oceano profundo)",
    "cidade_noite": "cidade grande à noite (pessoas, trânsito, economia, tecnologia, energia)",
    "supermercado": "corredor de mercado (comida, preços, consumo)",
    "espaco": "espaço sideral (planetas, Sol, Lua, astronautas, meteoros)",
    "estudio": "quarto aconchegante à noite (explicação, curiosidade, internet, celular)",
}
ACOES_ELENCO = {
    "parado": "parado em destaque", "gira": "girando como vitrine", "enxame": "vários voando em volta (insetos, peixes, pássaros)",
    "voa": "atravessando a tela voando", "anda": "atravessando a tela no chão", "cai": "caindo do céu e quicando",
    "cresce": "crescendo do nada", "some": "sumindo um por um (perfeito pra 'e se X sumisse')", "orbita": "girando em órbita",
    "pula": "pulando (multidão)", "pulsa": "pulsando (coração, alerta)", "treme": "tremendo (perigo)",
    "espalhado": "espalhado pelo cenário (flores, árvores, pessoas, casas)",
}
LUGARES = ["centro", "direita", "esquerda", "fundo", "ceu", "chao"]
ACOES_PERSONAGEM = ["fala", "surpreso", "aponta", "pensa", "comemora", "medo", "acena", "anda", "olha"]
CAMERAS = {"aproxima": "aproxima devagar (padrão)", "afasta": "abre revelando a escala", "orbita": "gira em volta",
           "grua": "sobe como grua", "close": "bem perto (emoção)", "geral": "plano geral do alto", "lateral": "desliza de lado",
           "baixo": "de baixo pra cima (grandioso)"}

IDIOMA = {"pt": "português do Brasil", "en": "English (US)", "es": "español latino"}


def biblioteca() -> list[str]:
    """Nomes dos modelos prontos em studio3d/modelos.js."""
    js = (ROOT / "studio3d" / "modelos.js").read_text(encoding="utf-8")
    bloco = js.split("export const MODELOS = {", 1)[1]
    return re.findall(r"^\s{2}(\w+): \{", bloco, flags=re.M)


PROMPT = """Você é roteirista e diretor de um canal viral de Shorts "E se...?" (vertical, 50–60s) feito em animação 3D
de blocos, com visual de cinema. Escreva UM vídeo novo em {idioma}.

Temas já feitos (não repita nem faça variação próxima):
{historico}
Território sugerido (pode ir além): ciência do cotidiano, espaço, corpo humano, animais, Terra/clima, economia,
tecnologia, "e se todo mundo fizesse X ao mesmo tempo". Premissa absurda, consequências REAIS em cadeia.
Tema-semente pra variar: "{semente}".

ROTEIRO
- Cena 1 = gancho: a pergunta "E se...?" em até 10 palavras.
- 9 a 13 cenas, uma frase curta cada (6 a 18 palavras), total 130–160 palavras.
- Gancho → consequência imediata → piora em cadeia → virada surpreendente → pergunta final pro público.
- Números e fatos VERDADEIROS. Linguagem falada, ritmo rápido. Sem emojis/hashtags na fala.

DIREÇÃO (o mais importante): cada cena MOSTRA o assunto concreto da frase.
- "elenco": 1 a 3 itens. O PRIMEIRO é o assunto principal (a câmera foca nele). Use quantidade pra dar escala
  (enxame de 15 abelhas, multidão de 25 pessoas, 8 carros andando).
  Cada item: {{"modelo": "...", "qtd": 1-40, "acao": "...", "onde": "...", "escala": 0.5-2}}
  Modelos prontos: {modelos}
  Se o assunto NÃO está na lista, crie em "modelos_novos" (até 3 por vídeo) e use o nome no elenco.
- "acao" do elenco: {acoes}
- "onde": {lugares}
- "personagem" (o explorador de moletom): só em ~30% das cenas (gancho, reação forte, final). Nas outras, null.
  Formato: {{"acao": "{acoes_p}", "onde": "esquerda|centro"}}. Com personagem, o elenco vai pra "direita".
- "cenario": {cenarios}  — escolha pelo assunto da frase; não repita o mesmo mais de 3 cenas seguidas.
- "camera": {cameras}  — varie.
- "texto_topo" (em ~40%): faixa de até 5 palavras, ex. "Em 5 segundos" / "Passo 2 · os mares",
  com "destaque" = trecho colorido. Ou null.
- "contador" (só quando a fala cita um número real): {{"de": 0, "ate": 75, "rotulo": "das plantações",
  "prefixo": "", "sufixo": "%", "casas": 0}} — prefixo/sufixo só símbolos ("%", "x", "R$", "°C"). Ou null.

MODELOS NOVOS: em blocos (caixas), estilo brinquedo, cores vivas, com olhos se for ser vivo. Até 30 caixas.
Caixa = [largura, altura, profundidade, "#cor", x, y, z, marca] (unidades ~0,1–1,5; y=0 é o chão se "chao": true).
Marcas opcionais: "asa" (bate), "brilho" (emite luz), "chama" (fogo), "vidro". Ex.:
"pinguim": {{"tamanho": 1.0, "chao": true, "caixas": [[0.6,0.8,0.5,"#1d1d1d",0,0.45,0],[0.45,0.6,0.1,"#f4f4f4",0,0.4,0.25],
 [0.15,0.08,0.15,"#ffa94d",0,0.75,0.3],[0.08,0.1,0.03,"#ffffff",-0.1,0.85,0.26],[0.08,0.1,0.03,"#ffffff",0.1,0.85,0.26],
 [0.2,0.06,0.25,"#ffa94d",-0.15,0.03,0.05],[0.2,0.06,0.25,"#ffa94d",0.15,0.03,0.05]]}}

Responda só JSON:
{{"tema": "...", "titulo": "título do post, até 70 caracteres, com curiosidade",
  "descricao": "1–2 frases pro post + pergunta", "hashtags": ["5 a 7 sem #"],
  "modelos_novos": {{}},
  "cenas": [{{"fala": "...", "cenario": "...", "elenco": [...], "personagem": null, "camera": "...",
             "texto_topo": null, "contador": null}}]}}"""

PROMPT_CHECAGEM = """Revise este roteiro de Short ("E se...?") como editor de ciência e diretor de arte.
1. Todo número ou fato apresentado como real tem que estar correto; corrija o que estiver errado ou exagerado
   (mantendo o tamanho da frase). Especulação só como hipótese.
2. Os "contador" têm que bater com o número dito na mesma cena.
3. Cada cena tem que MOSTRAR no "elenco" o assunto concreto da fala. Se não mostra, troque o elenco
   (use os modelos prontos: {modelos}; ou acrescente em "modelos_novos").
4. Mantenha campos, formato e idioma ({idioma}).
Devolva o JSON completo corrigido + "correcoes": ["o que mudou"] (lista vazia se nada).

{roteiro}"""

SEMENTES = ["a gravidade", "a internet", "os oceanos", "o Sol", "dinheiro", "o sono", "os insetos", "a luz", "o tempo",
            "as cores", "a Lua", "a eletricidade", "a água", "os dinossauros", "o celular", "a velocidade", "o frio",
            "a comida", "os ventos", "o som", "as abelhas", "o petróleo", "as florestas", "os vulcões", "o oxigênio",
            "os gatos", "os carros", "o café", "as nuvens", "os tubarões", "o coração", "o cérebro", "as formigas"]


def _historico(lang: str) -> list[str]:
    if not HISTORICO.exists():
        return []
    return [json.loads(l)["tema"] for l in HISTORICO.read_text(encoding="utf-8").splitlines()
            if l.strip() and json.loads(l).get("lang") == lang]


def _cor(c) -> bool:
    return isinstance(c, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", c) is not None


def _modelos_novos(brutos) -> dict:
    """Só passa modelo novo bem formado (caixas numéricas, cor válida, tamanho razoável)."""
    ok = {}
    for nome, d in (brutos or {}).items() if isinstance(brutos, dict) else []:
        if not isinstance(d, dict) or not re.fullmatch(r"[a-z_]{2,30}", str(nome)):
            continue
        caixas = []
        for c in d.get("caixas", [])[:40]:
            if (isinstance(c, list) and len(c) in (7, 8) and all(isinstance(v, (int, float)) for v in c[:3] + c[4:7])
                    and _cor(c[3]) and all(0 < v <= 6 for v in c[:3]) and all(abs(v) <= 6 for v in c[4:7])):
                caixas.append(c[:7] + ([c[7]] if len(c) == 8 and c[7] in ("asa", "brilho", "chama", "vidro") else []))
        if len(caixas) >= 3:
            tam = d.get("tamanho", 1)
            ok[nome] = {"tamanho": tam if isinstance(tam, (int, float)) and 0.2 <= tam <= 8 else 1,
                        "chao": bool(d.get("chao")), "caixas": caixas}
    return ok


def _validar(sb: dict) -> dict:
    """Garante que só vai pro estúdio o que o estúdio sabe desenhar."""
    sb["modelos_novos"] = _modelos_novos(sb.get("modelos_novos"))
    disponiveis = set(biblioteca()) | set(sb["modelos_novos"])
    cenas = []
    for c in sb.get("cenas", []):
        if not c.get("fala"):
            continue
        c["cenario"] = c.get("cenario") if c.get("cenario") in CENARIOS else "estudio"
        c["camera"] = c.get("camera") if c.get("camera") in CAMERAS else "aproxima"
        elenco = []
        for it in c.get("elenco") or []:
            if not isinstance(it, dict) or it.get("modelo") not in disponiveis:
                continue
            qtd = it.get("qtd") if isinstance(it.get("qtd"), int) else 1
            esc = it.get("escala") if isinstance(it.get("escala"), (int, float)) else 1
            elenco.append({"modelo": it["modelo"], "qtd": max(1, min(qtd, 40)),
                           "acao": it.get("acao") if it.get("acao") in ACOES_ELENCO else "parado",
                           "onde": it.get("onde") if it.get("onde") in LUGARES else None,
                           "escala": max(0.4, min(esc, 2.5))})
        c["elenco"] = elenco[:3]
        pers = c.get("personagem")
        if isinstance(pers, dict):
            pers = {"acao": pers.get("acao") if pers.get("acao") in ACOES_PERSONAGEM else "fala",
                    "onde": pers.get("onde") if pers.get("onde") in ("esquerda", "centro") else None}
        elif not c["elenco"]:
            pers = {"acao": "fala", "onde": "centro"}  # nada pra mostrar: pelo menos o explorador fala
        else:
            pers = None
        c["personagem"] = pers
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
    modelos = ", ".join(biblioteca())
    feitos = _historico(lang)
    prompt = PROMPT.format(idioma=IDIOMA[lang], historico="\n".join(f"- {t}" for t in feitos[-80:]) or "(nenhum)",
                           semente=random.choice(SEMENTES), modelos=modelos, acoes=lista(ACOES_ELENCO),
                           lugares=", ".join(LUGARES), acoes_p="|".join(ACOES_PERSONAGEM), cenarios=lista(CENARIOS),
                           cameras=lista(CAMERAS))
    sb = _validar(chat([{"role": "user", "content": prompt}], json_mode=True, temperature=0.9, tarefa="roteiro_3d",
                       perfil="flex"))
    revisado = chat([{"role": "user", "content": PROMPT_CHECAGEM.format(
        idioma=IDIOMA[lang], modelos=modelos, roteiro=json.dumps(sb, ensure_ascii=False))}],
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
    log.info("Roteiro 3D: %s (%d cenas, %d palavras, %d modelos novos, %d correções)", sb["titulo"], len(sb["cenas"]),
             palavras, len(sb["modelos_novos"]), len(correcoes))
    return sb


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="pt", choices=list(IDIOMA))
    a = ap.parse_args()
    print(json.dumps(escrever(a.lang), ensure_ascii=False, indent=2))
