"""Monta o Short 1080x1920: cenas com movimento + narração + música + legenda palavra por palavra.

Uso: uv run python -m pipeline.video_builder --id ID
Saída: storage/shorts/ready/{id}.mp4

Proteção do PC: um ffmpeg por vez, prioridade baixa, threads limitadas, codificação na NVENC.
"""
import argparse
import logging
import random
import shutil
import subprocess
import sys

from PIL import Image, ImageFilter, ImageEnhance

from agents.common import ROOT, STORAGE, config, ler_json, salvar_json

log = logging.getLogger("video_builder")

W, H, FPS = 1080, 1920, 30
SEG = config("settings")["seguranca_pc"]
PRIORIDADE_BAIXA = 0x00004000 if sys.platform == "win32" else 0  # BELOW_NORMAL_PRIORITY_CLASS
COR = "eq=saturation=0.8:contrast=1.06:brightness=-0.03,vignette=PI/5"  # clima sombrio de mistério

_encoder = None


def encoder_args() -> list[str]:
    """NVENC (chip de vídeo da GPU, leve) se funcionar; senão libx264 em CPU."""
    global _encoder
    if _encoder is None:
        teste = subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.2",
                                "-c:v", "h264_nvenc", "-f", "null", "-"], capture_output=True)
        _encoder = "nvenc" if teste.returncode == 0 and SEG["encoder"] == "h264_nvenc" else "x264"
        log.info("Encoder: %s", _encoder)
    if _encoder == "nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p"]


def ffmpeg(args: list[str], cwd=None):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-threads", str(SEG["ffmpeg_threads"]), *args]
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, creationflags=PRIORIDADE_BAIXA)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou: {r.stderr[-800:]}")


# ---------- cenas ----------

def compor_imagem(origem, destino):
    """Imagem em 2x (2160x3840): fundo desfocado + imagem inteira centralizada. Nada fica cortado."""
    img = Image.open(origem).convert("RGB")
    W2, H2 = W * 2, H * 2
    escala_fundo = max(W2 / img.width, H2 / img.height)
    fundo = img.resize((int(img.width * escala_fundo) + 1, int(img.height * escala_fundo) + 1))
    fundo = fundo.crop(((fundo.width - W2) // 2, (fundo.height - H2) // 2,
                        (fundo.width - W2) // 2 + W2, (fundo.height - H2) // 2 + H2))
    fundo = ImageEnhance.Brightness(fundo.filter(ImageFilter.GaussianBlur(40))).enhance(0.45)

    proporcao = img.width / img.height
    if proporcao < 0.75:  # já é vertical: preenche a tela
        frente = img.resize((int(img.width * escala_fundo), int(img.height * escala_fundo)))
    else:  # horizontal: ocupa a largura, levemente maior pra ter presença
        largura = int(W2 * 1.15)
        frente = img.resize((largura, int(largura / proporcao)))
    fundo.paste(frente, ((W2 - frente.width) // 2, (H2 - frente.height) // 2))
    fundo.save(destino, quality=92)


def cena_imagem(midia, duracao, saida, n):
    composta = saida.with_suffix(".jpg")
    compor_imagem(midia["arquivo"], composta)
    frames = int(duracao * FPS) + 1
    # Ken Burns alternando: zoom in / zoom out, com leve deriva
    if n % 2:
        z = "min(1.0+0.0009*on,1.25)"
    else:
        z = f"max(1.22-0.0009*on,1.0)"
    deriva = random.choice(["iw/2-(iw/zoom/2)", "iw/2-(iw/zoom/2)+on*0.4", "iw/2-(iw/zoom/2)-on*0.4"])
    ffmpeg(["-loop", "1", "-i", str(composta), "-t", f"{duracao:.3f}",
            "-vf", f"zoompan=z='{z}':x='{deriva}':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS},{COR},setsar=1",
            "-an", *encoder_args(), str(saida)])
    composta.unlink()


def cena_video(midia, duracao, saida):
    ffmpeg(["-stream_loop", "-1", "-i", midia["arquivo"], "-t", f"{duracao:.3f}",
            "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},{COR},setsar=1",
            "-an", *encoder_args(), str(saida)])


# ---------- legenda ----------

def _ts(s: float) -> str:
    h, s = divmod(max(s, 0), 3600)
    m, s = divmod(s, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def gerar_ass(palavras, titulo, destino):
    """Legenda estilo Shorts: 1–3 palavras grandes, palavra atual em amarelo. Título no topo nos 3s iniciais."""
    cab = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Legenda,Arial Black,92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,100,100,0,0,1,7,4,2,60,60,560,1
Style: Titulo,Arial Black,64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,100,100,0,0,3,18,0,8,70,70,260,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    linhas = [f"Dialogue: 1,{_ts(0)},{_ts(3.0)},Titulo,,0,0,0,,{{\\fad(150,250)}}{titulo.upper()}"]

    # Agrupa em blocos de até 3 palavras, quebrando em pontuação
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
            partes = []
            for j, q in enumerate(bloco):
                txt = q["palavra"].upper().rstrip(",;:")
                partes.append(f"{{\\c&H00D7FF&\\fscx108\\fscy108}}{txt}{{\\r}}" if j == i else txt)
            linhas.append(f"Dialogue: 0,{_ts(p['inicio'])},{_ts(fim)},Legenda,,0,0,0,,{' '.join(partes)}")
    destino.write_text(cab + "\n".join(linhas) + "\n", encoding="utf-8")


# ---------- montagem ----------

def escolher_musica():
    musicas = [p for p in (ROOT / "assets" / "music").glob("*") if p.suffix.lower() in (".mp3", ".wav", ".m4a")]
    return random.choice(musicas) if musicas else None


def montar(script_id: str, pasta_script=None) -> dict:
    pasta_script = pasta_script or STORAGE / "scripts" / "approved"
    meta = ler_json(pasta_script / f"{script_id}.meta.json")
    cenas = ler_json(STORAGE / "scripts" / f"{script_id}.scenes.json")
    palavras = ler_json(STORAGE / "audio" / f"{script_id}.words.json")
    narracao = STORAGE / "audio" / f"{script_id}.mp3"

    trab = STORAGE / "work" / script_id
    shutil.rmtree(trab, ignore_errors=True)
    trab.mkdir(parents=True)

    for c in cenas:
        saida = trab / f"cena_{c['n']:03d}.mp4"
        log.info("Cena %d/%d (%s, %.1fs)", c["n"], len(cenas), c["midia"]["tipo"], c["duracao"])
        if c["midia"]["tipo"] == "video":
            cena_video(c["midia"], c["duracao"], saida)
        else:
            cena_imagem(c["midia"], c["duracao"], saida, c["n"])

    (trab / "lista.txt").write_text("".join(f"file 'cena_{c['n']:03d}.mp4'\n" for c in cenas), encoding="utf-8")
    ffmpeg(["-f", "concat", "-safe", "0", "-i", "lista.txt", "-c", "copy", "visual.mp4"], cwd=trab)
    gerar_ass(palavras, meta["titulo"], trab / "legenda.ass")

    duracao = cenas[-1]["fim"]
    musica = escolher_musica()
    entradas = ["-i", "visual.mp4", "-i", str(narracao)]
    if musica:
        log.info("Música: %s", musica.name)
        entradas += ["-stream_loop", "-1", "-i", str(musica)]
        audio = ("[2:a]volume=0.35,afade=t=out:st={f}:d=1.5[m];"
                 "[m][1:a]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[md];"
                 "[md][1:a]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]").format(f=max(duracao - 1.5, 0))
    else:
        log.warning("Sem música em assets/music/ — vídeo sai só com narração")
        audio = "[1:a]apad[a]"

    destino = STORAGE / "shorts" / "ready" / f"{script_id}.mp4"
    ffmpeg([*entradas, "-filter_complex", f"[0:v]subtitles=legenda.ass[v];{audio}",
            "-map", "[v]", "-map", "[a]", "-t", f"{duracao:.3f}", *encoder_args(),
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(destino)], cwd=trab)

    meta["video"] = str(destino)
    meta["duracao_seg"] = round(duracao, 1)
    salvar_json(pasta_script / f"{script_id}.meta.json", meta)
    shutil.rmtree(trab, ignore_errors=True)
    log.info("✅ Short pronto: %s (%.1fs)", destino, duracao)
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--pasta", default="approved")
    a = ap.parse_args()
    montar(a.id, STORAGE / "scripts" / a.pasta)
