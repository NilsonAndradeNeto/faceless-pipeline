"""Produz o Short "E se...?" com VÍDEOS REAIS: narração grátis → busca no Pixabay → IA com visão confere se o
clipe mostra mesmo o que a frase diz → edição com movimento e cor de cinema → legenda, faixa e contador → MP4.

Uso: uv run python -m pipeline.produzir_ese --novo pt      (escreve o roteiro e produz)
     uv run python -m pipeline.produzir_ese --id ID        (roteiro já escrito em storage/e_se/)
Saída: storage/shorts/ready/{id}.mp4
"""
import argparse
import base64
import json
import logging
import os
import random
import re
import shutil
import subprocess

import requests

from agents.common import ROOT, STORAGE, ler_json, salvar_json
from pipeline.produzir_3d import _faixa_efeitos
from pipeline.voz_livre import narrar_cenas

log = logging.getLogger("produzir_ese")

PASTA = STORAGE / "e_se"
CLIPES = STORAGE / "clipes"
W, H, FPS = 1080, 1920, 30
FONTES = (ROOT / "assets" / "fonts").as_posix().replace(":", "\\\\:")
GRADE = "eq=contrast=1.07:saturation=1.1:gamma=0.97,colorbalance=rs=-0.03:bs=0.04:rh=0.04:bh=-0.04,vignette=PI/5,noise=alls=5:allf=t"


# ---------- escolha dos clipes ----------

def buscar_pixabay(consulta: str) -> list[dict]:
    r = requests.get("https://pixabay.com/api/videos/", timeout=30, params={
        "key": os.environ["PIXABAY_API_KEY"], "q": consulta, "per_page": 15, "safesearch": "true", "video_type": "film"})
    clipes = []
    for h in r.json().get("hits", []):
        tags = h.get("tags", "").lower()
        if "ai generated" in tags or "animation" in tags or "3d render" in tags:
            continue  # só filmagem de verdade
        v = h["videos"]
        rend = v["large"] if v["large"].get("url") and v["large"]["size"] < 70e6 else v["medium"]
        if not rend.get("url") or min(rend["width"], rend["height"]) < 700:
            continue
        clipes.append({"id": h["id"], "tags": tags, "duracao": h["duration"], "url": rend["url"], "w": rend["width"],
                       "h": rend["height"], "thumb": v["small"].get("thumbnail") or v["tiny"].get("thumbnail"),
                       "consulta": consulta})
    return clipes


def _nota_tags(c: dict, consulta: str, dur: float) -> float:
    palavras = set(re.findall(r"\w+", consulta.lower()))
    pontos = len(palavras & set(re.findall(r"\w+", c["tags"]))) / max(len(palavras), 1)
    pontos += 0.3 if c["h"] > c["w"] else 0                     # já é vertical: não perde nada no corte
    pontos += 0.2 if max(c["w"], c["h"]) >= 3000 else 0          # 4K aguenta o corte vertical sem borrar
    pontos += 0.15 if c["duracao"] >= dur + 1 else 0
    return pontos


def _miniatura(dados: bytes) -> bytes:
    """Reduz a miniatura (gasta menos da cota por minuto da IA com visão)."""
    from io import BytesIO

    from PIL import Image
    img = Image.open(BytesIO(dados)).convert("RGB")
    img.thumbnail((384, 384))
    saida = BytesIO()
    img.save(saida, "JPEG", quality=72)
    return saida.getvalue()


def _visao(prompt: str, imagens: list[bytes]) -> str:
    """Groq (Qwen com visão, grátis); no limite por minuto espera e tenta de novo. Se não der, Gemini."""
    import time

    from groq import Groq, RateLimitError
    conteudo = [{"type": "text", "text": prompt}] + [
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(_miniatura(i)).decode()}}
        for i in imagens]
    msgs = [{"role": "user", "content": conteudo}]
    cliente = Groq(api_key=os.environ["GROQ_API_KEY"], max_retries=0)
    for tentativa in range(2):
        try:
            r = cliente.chat.completions.create(model="qwen/qwen3.8-27b", messages=msgs, max_completion_tokens=200,
                                                temperature=0.1, reasoning_effort="none")  # sem "pensar alto": só a nota
            return r.choices[0].message.content or ""
        except RateLimitError as e:
            espera = min(float(e.response.headers.get("retry-after", 15) or 15) + 1, 40)
            log.info("Visão no limite por minuto; esperando %.0fs", espera)
            time.sleep(espera)
        except Exception as e:
            log.info("Visão no Groq falhou (%s)", str(e)[:100])
            break
    from openai import OpenAI
    cli = OpenAI(api_key=os.environ["GEMINI_API_KEY"].strip(), base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                 max_retries=1, timeout=90)
    for modelo in ("gemini-3.5-flash", "gemini-3-flash-preview", "gemini-3.8-flash"):
        try:
            return cli.chat.completions.create(model=modelo, messages=msgs).choices[0].message.content or ""
        except Exception as e:
            log.info("Visão no %s falhou: %s", modelo, str(e)[:100])
    return ""


def conferir(cena: dict, candidatos: list[dict]) -> tuple[int | None, int]:
    """A IA olha a miniatura de cada candidato (até 3) e dá nota 0–10. Devolve (índice do melhor, nota)."""
    imagens = []
    for c in candidatos:
        try:
            imagens.append(requests.get(c["thumb"], timeout=20).content)
        except Exception:
            imagens.append(b"")
    validos = [i for i, im in enumerate(imagens) if im]
    if not validos:
        return None, -1
    prompt = (f"Você é editor de vídeo. A narração diz: \"{cena['fala']}\"\n"
              f"Na tela tem que aparecer: {cena['visual']}\n"
              f"Seguem {len(validos)} imagens (na ordem). Dê nota de 0 a 10 para cada uma: o quanto mostra claramente o "
              "que tem que aparecer. Nota baixa se for outro assunto, desenho/animação/imagem de IA, tiver texto ou "
              "marca d'água, ou estiver feia/escura. Responda só JSON: {\"notas\": [n1, n2, ...]}")
    texto = _visao(prompt, [imagens[i] for i in validos])
    achado = re.search(r"\{.*\}", texto, re.S)
    try:
        notas = json.loads(achado.group(0))["notas"] if achado else []
    except (json.JSONDecodeError, KeyError):
        notas = []
    if len(notas) != len(validos) or not all(isinstance(n, (int, float)) for n in notas):
        return None, -1
    melhor = max(range(len(validos)), key=lambda k: notas[k])
    log.info("Cena '%s…': notas %s", cena["fala"][:40], notas)
    return validos[melhor], notas[melhor]


def _novas_buscas(cena: dict) -> list[str]:
    from agents.llm_client import chat
    r = chat([{"role": "user", "content": (
        f'Nenhum vídeo de banco de imagens serviu para a narração: "{cena["fala"]}" (buscas já tentadas: '
        f'{cena["busca"]}). Sugira 3 buscas NOVAS em inglês, de 1 a 2 palavras, de coisas concretas e muito comuns '
        'em vídeo de banco (natureza, cidade, pessoas, objetos) que representem bem a frase. '
        'Responda só JSON: {"busca": ["...", "...", "..."], "visual": "o que deve aparecer, em inglês"}')}],
        json_mode=True, temperature=0.6, tarefa="busca_alternativa", perfil="flex")
    if r.get("visual"):
        cena["visual"] = r["visual"]
    return [b for b in r.get("busca", []) if isinstance(b, str)][:3]


def _escolher_por_tags(cenas: list[dict], cands: list[list[dict]]) -> list[int | None]:
    """Uma chamada de texto só (barata) escolhe, para todas as cenas, o candidato cujas tags mostram a frase."""
    from agents.llm_client import chat
    blocos = []
    for n, (c, lista) in enumerate(zip(cenas, cands)):
        opcoes = "\n".join(f"   {i}: {x['tags']}" for i, x in enumerate(lista))
        blocos.append(f"CENA {n}: \"{c['fala']}\" (deve mostrar: {c['visual']})\n{opcoes}")
    r = chat([{"role": "user", "content": (
        "Você é editor de vídeo. Para cada cena, escolha o vídeo de banco (pelas tags) que MOSTRA o assunto concreto "
        "da frase. Se nenhum mostra, responda null para a cena. Não repita o mesmo vídeo.\n\n" + "\n\n".join(blocos) +
        '\n\nResponda só JSON: {"escolhas": [indice_ou_null_da_cena_0, ...]}')}],
        json_mode=True, temperature=0.1, tarefa="escolha_clipes", perfil="flex")
    esc = r.get("escolhas", [])
    return [e if isinstance(e, int) and 0 <= e < len(cands[n]) else None
            for n, e in enumerate(esc + [None] * (len(cenas) - len(esc)))]


def escolher_clipes(cenas: list[dict], conferir_visao: bool = True):
    """Busca candidatos de todas as cenas, escolhe pelas tags numa chamada só e, se a IA com visão estiver
    disponível, confere a miniatura (nota < 6 → tenta o próximo candidato / buscas novas)."""
    def candidatos(c, buscas, usados):
        dur = c["fim"] - c["inicio"]
        vistos, lista = set(), []
        for q in buscas:
            for x in sorted(buscar_pixabay(q), key=lambda x: _nota_tags(x, q, dur), reverse=True)[:5]:
                if x["id"] not in vistos and x["id"] not in usados:
                    vistos.add(x["id"])
                    lista.append(x)
        return lista[:8]

    usados = set()
    cands = [candidatos(c, c["busca"], usados) for c in cenas]
    escolhas = _escolher_por_tags(cenas, cands)
    for n, c in enumerate(cenas):
        lista, i = cands[n], escolhas[n]
        if i is None or not lista:  # nada servia: buscas novas e escolhe de novo só essa cena
            lista = candidatos(c, _novas_buscas(c), usados)
            i = _escolher_por_tags([c], [lista])[0] if lista else None
            log.info("Cena '%s…': buscas novas → %s", c["fala"][:40], "achou" if i is not None else "nada")
        if i is None and lista:
            i = 0
        if i is None:
            raise RuntimeError(f"Sem vídeo para a cena: {c['fala'][:60]}")
        if conferir_visao:
            ordem = [i] + [k for k in range(len(lista)) if k != i][:2]
            k, nota = conferir(c, [lista[j] for j in ordem])
            if k is not None and nota >= 6:
                i = ordem[k]
            elif k is not None and nota >= 0:
                log.warning("Cena '%s…': melhor nota da visão foi %s", c["fala"][:40], nota)
            else:
                conferir_visao = False  # IA de visão sem cota: segue só pelas tags (não trava o vídeo)
                log.info("IA de visão indisponível; escolhendo só pelas tags")
        c["clipe"] = lista[i]
        usados.add(lista[i]["id"])


def baixar(clipe: dict):
    CLIPES.mkdir(parents=True, exist_ok=True)
    destino = CLIPES / f"{clipe['id']}_{clipe['w']}.mp4"
    if not destino.exists() or destino.stat().st_size < 50_000:
        with requests.get(clipe["url"], stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(destino, "wb") as f:
                for parte in r.iter_content(1 << 20):
                    f.write(parte)
    return destino


# ---------- edição ----------

def _ffmpeg(args: list[str], cwd=None):
    for tentativa in range(2):  # no Windows o ffmpeg às vezes cai sem mensagem: uma segunda tentativa resolve
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], cwd=cwd, capture_output=True, text=True)
        if r.returncode == 0:
            return
        log.warning("ffmpeg saiu com código %s (tentativa %d): %s", r.returncode, tentativa + 1, r.stderr[-300:])
    raise RuntimeError(f"ffmpeg falhou (código {r.returncode}): {r.stderr[-700:]}")


def editar_cena(c: dict, arquivo, saida, n: int):
    dur = c["fim"] - c["inicio"]
    fonte = c["clipe"]["duracao"]
    lento = min(max(dur / max(fonte - 0.5, 0.5), 1.0), 1.6)   # clipe curto: câmera lenta (até 1,6x)
    inicio = max(0.0, min((fonte - dur / lento) * 0.35, fonte - dur / lento - 0.2))
    # câmera deslizando devagar (alterna o sentido a cada cena). Zoom quadro a quadro derruba este ffmpeg.
    mover = f"(iw-ow)*t/{dur:.3f}" if n % 2 == 0 else f"(iw-ow)*(1-t/{dur:.3f})"
    vf = (f"setpts={lento:.3f}*PTS,fps={FPS},scale={int(W * 1.1)}:{int(H * 1.1)}:force_original_aspect_ratio=increase,"
          f"crop={W}:{H}:x='{mover}':y='(ih-oh)/2',{GRADE},setsar=1")
    _ffmpeg(["-ss", f"{inicio:.2f}", "-stream_loop", "-1", "-i", str(arquivo), "-t", f"{dur:.3f}", "-vf", vf, "-an",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(saida)])


def _ts(s: float) -> str:
    h, s = divmod(max(s, 0), 3600)
    m, s = divmod(s, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _num(v: float, casas: int, lang: str) -> str:
    txt = f"{v:,.{casas}f}"
    return txt if lang == "en" else txt.replace(",", "X").replace(".", ",").replace("X", ".")


def gerar_ass(palavras: list[dict], cenas: list[dict], lang: str, destino):
    """Legenda palavra por palavra + faixa de papel no topo + contador animado (tudo em ASS, desenhado pelo ffmpeg)."""
    cab = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Legenda,Archivo Black,86,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,7,3,2,60,60,520,1
Style: Faixa,Archivo Black,54,&H002E1A1D,&H002E1A1D,&H00D2EAF4,&H64000000,1,0,0,0,100,100,1,-1.2,3,16,0,8,80,80,200,1
Style: Numero,Archivo Black,150,&H003FD2FF,&H003FD2FF,&H00000000,&H96000000,1,0,0,0,100,100,0,0,1,6,4,8,60,60,330,1
Style: Rotulo,Archivo Black,42,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,100,100,0,0,1,4,2,8,60,60,500,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    linhas = []
    for c in cenas:
        tt = c.get("texto_topo")
        if tt:
            txt, d = tt["texto"].upper(), (tt.get("destaque") or "").upper()
            if d and d in txt:
                txt = txt.replace(d, "{\\c&H0F48D9&}" + d + "{\\c&H2E1A1D&}")
            linhas.append(f"Dialogue: 2,{_ts(c['inicio'] + 0.05)},{_ts(c['fim'])},Faixa,,0,0,0,,"
                          f"{{\\fad(120,120)\\t(0,180,\\fscx100\\fscy100)\\fscx70\\fscy70}}{txt}")
        ct = c.get("contador")
        if ct:
            dur = c["fim"] - c["inicio"]
            passos = max(int(dur * 15), 2)
            for k in range(passos):
                t0, t1 = c["inicio"] + k / 15, c["inicio"] + (k + 1) / 15
                x = min(1.0, (k / 15) / max(dur * 0.7, 0.3))
                valor = ct.get("de", 0) + (ct["ate"] - ct.get("de", 0)) * (x * x * (3 - 2 * x))
                num = f"{ct.get('prefixo', '')}{_num(valor, int(ct.get('casas') or 0), lang)}{ct.get('sufixo', '')}"
                linhas.append(f"Dialogue: 3,{_ts(t0)},{_ts(t1)},Numero,,0,0,0,,{num}")
            if ct.get("rotulo"):
                linhas.append(f"Dialogue: 3,{_ts(c['inicio'])},{_ts(c['fim'])},Rotulo,,0,0,0,,{ct['rotulo'].upper()}")
    blocos, atual = [], []
    for p in palavras:
        atual.append(p)
        if len(atual) == 3 or p["palavra"][-1] in ".,!?;:":
            blocos.append(atual)
            atual = []
    if atual:
        blocos.append(atual)
    for b_i, bloco in enumerate(blocos):
        fim_bloco = blocos[b_i + 1][0]["inicio"] if b_i + 1 < len(blocos) else bloco[-1]["fim"] + 0.5
        for i, p in enumerate(bloco):
            fim = bloco[i + 1]["inicio"] if i + 1 < len(bloco) else fim_bloco
            partes = [("{\\c&H00D7FF&\\fscx108\\fscy108}" + q["palavra"].upper().rstrip(",;:") + "{\\r}") if j == i
                      else q["palavra"].upper().rstrip(",;:") for j, q in enumerate(bloco)]
            linhas.append(f"Dialogue: 1,{_ts(p['inicio'])},{_ts(fim)},Legenda,,0,0,0,,{' '.join(partes)}")
    destino.write_text(cab + "\n".join(linhas) + "\n", encoding="utf-8")


def produzir(sid: str, progresso=None) -> dict:
    avisar = progresso or (lambda *_: None)
    arq = next((PASTA / s / f"{sid}.json" for s in ("aprovados", "pendentes", "prontos") if (PASTA / s / f"{sid}.json").exists()), None)
    if not arq:
        raise FileNotFoundError(sid)
    sb = ler_json(arq)
    trab = STORAGE / "work" / sid
    trab.mkdir(parents=True, exist_ok=True)

    tempos_arq = trab / "tempos.json"
    if tempos_arq.exists() and (trab / "voz.mp3").exists():
        d = ler_json(tempos_arq)
        palavras, tempos, duracao = d["palavras"], d["tempos"], d["duracao"]
    else:
        avisar(0.03, "Gravando a narração")
        palavras, tempos, duracao = narrar_cenas([c["fala"] for c in sb["cenas"]], sb["lang"], trab / "voz.mp3")
        salvar_json(tempos_arq, {"palavras": palavras, "tempos": tempos, "duracao": duracao})
    for c, (ini, fim) in zip(sb["cenas"], tempos):
        c["inicio"], c["fim"] = ini, fim
    log.info("▶ E se (real): %s (%.1fs, %d cenas)", sb["titulo"], duracao, len(sb["cenas"]))

    avisar(0.1, "Escolhendo os vídeos de cada cena")
    if not all(c.get("clipe") for c in sb["cenas"]):
        escolher_clipes(sb["cenas"])
        salvar_json(arq, sb)
    for n, c in enumerate(sb["cenas"]):
        avisar(0.3 + 0.55 * n / len(sb["cenas"]), f"Editando cena {n + 1} de {len(sb['cenas'])}")
        saida = trab / f"cena_{n:02d}.mp4"
        if not saida.exists():
            editar_cena(c, baixar(c["clipe"]), saida, n)
    (trab / "lista.txt").write_text("".join(f"file 'cena_{n:02d}.mp4'\n" for n in range(len(sb["cenas"]))), encoding="utf-8")
    _ffmpeg(["-f", "concat", "-safe", "0", "-i", "lista.txt", "-c", "copy", "visual.mp4"], cwd=trab)

    avisar(0.9, "Legenda, trilha e mixagem")
    gerar_ass(palavras, sb["cenas"], sb["lang"], trab / "legenda.ass")
    _faixa_efeitos(sb["cenas"], duracao, trab / "efeitos.wav")
    musica = random.choice(sorted(p for p in (ROOT / "assets" / "music").glob("*.mp3")))
    destino = STORAGE / "shorts" / "ready" / f"{sid}.mp4"
    destino.parent.mkdir(parents=True, exist_ok=True)
    filtro = (f"[0:v]subtitles=legenda.ass:fontsdir={FONTES}[v];"
              f"[1:a]loudnorm=I=-16:TP=-1.5,apad,asplit=2[voz][guia];"
              f"[2:a]volume=0.3,afade=t=out:st={max(duracao - 1.5, 0):.2f}:d=1.5[m];"
              f"[m][guia]sidechaincompress=threshold=0.04:ratio=6:attack=15:release=350[md];"
              f"[voz][md][3:a]amix=inputs=3:duration=first:normalize=0,alimiter=limit=0.95[a]")
    _ffmpeg(["-i", "visual.mp4", "-i", "voz.mp3", "-stream_loop", "-1", "-i", str(musica), "-i", "efeitos.wav",
             "-filter_complex", filtro, "-map", "[v]", "-map", "[a]", "-t", f"{duracao:.3f}",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", str(destino)], cwd=trab)

    sb.update(duracao_seg=round(duracao, 1), video=str(destino), producao={"etapa": "pronto", "progresso": 1.0},
              creditos=sorted({f"Pixabay #{c['clipe']['id']}" for c in sb["cenas"]}))
    salvar_json(PASTA / "prontos" / f"{sid}.json", sb)
    if arq.parent.name != "prontos":
        arq.unlink()
    shutil.rmtree(trab, ignore_errors=True)
    log.info("✅ E se pronto: %s (%.1fs)", destino, duracao)
    return sb


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--id")
    g.add_argument("--novo", choices=["pt", "en", "es"])
    a = ap.parse_args()
    if a.novo:
        from agents.roteiro_ese import escrever
        a.id = escrever(a.novo)["id"]
    print(produzir(a.id)["video"])
