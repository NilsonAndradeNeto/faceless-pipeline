"""Grava o estúdio 3D (studio3d/) quadro a quadro com um Chromium sem janela e junta no ffmpeg.

O motor desenha qualquer instante t sob demanda (window.quadro(t)), então a gravação é exata
mesmo se cada quadro demorar: não depende de tempo real.

Uso (prévia de quadros soltos):  uv run python -m pipeline.estudio3d --exemplo
"""
import argparse
import functools
import logging
import subprocess
import threading
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agents.common import ROOT, STORAGE

log = logging.getLogger("estudio3d")

W, H, FPS = 1080, 1920, 30
# Na nuvem não há GPU: o Chromium desenha o WebGL na CPU (SwiftShader)
ARGS_CHROMIUM = ["--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--enable-webgl", "--use-angle=swiftshader"]


class _Silencioso(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@contextmanager
def servidor():
    """Serve a pasta do projeto em localhost (módulos JS não carregam via file://)."""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Silencioso, directory=str(ROOT)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


@contextmanager
def estudio(storyboard: dict, gpu: bool = False):
    from playwright.sync_api import sync_playwright
    with servidor() as url, sync_playwright() as pw:
        nav = pw.chromium.launch(args=[] if gpu else ARGS_CHROMIUM)
        pagina = nav.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        erros = []
        pagina.on("pageerror", lambda e: erros.append(str(e)))
        pagina.goto(f"{url}/studio3d/index.html")
        pagina.wait_for_function("window.pronto === true", timeout=30000)
        if erros:
            raise RuntimeError(f"Erro no motor 3D: {erros[0]}")
        pagina.evaluate("sb => window.preparar(sb)", storyboard)
        try:
            yield pagina
        finally:
            if erros:
                log.warning("Erros no motor 3D: %s", erros[:3])
            nav.close()


def quadro(pagina, t: float) -> bytes:
    pagina.evaluate(f"window.quadro({t:.4f})")
    return pagina.screenshot(type="jpeg", quality=92)


def gravar(storyboard: dict, destino: Path, progresso=None, gpu: bool = False) -> Path:
    """Grava o vídeo mudo (H.264) do storyboard inteiro."""
    duracao = storyboard["duracao"]
    total = int(duracao * FPS) + 1
    destino.parent.mkdir(parents=True, exist_ok=True)
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS),
                           "-c:v", "mjpeg", "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                           "-pix_fmt", "yuv420p", str(destino)], stdin=subprocess.PIPE)
    with estudio(storyboard, gpu=gpu) as pagina:
        for i in range(total):
            ff.stdin.write(quadro(pagina, i / FPS))
            if progresso and i % 30 == 0:
                progresso(i / total, f"Gravando a animação 3D: {i // FPS}s de {duracao:.0f}s")
    ff.stdin.close()
    if ff.wait() != 0:
        raise RuntimeError("ffmpeg falhou ao gravar a animação 3D")
    return destino


# ---------- exemplo para testar o visual ----------

def _palavras_falsas(cenas):
    """Tempo de fala aproximado (2,6 palavras/s) só pra prévia sem narração."""
    palavras, t = [], 0.3
    for c in cenas:
        c["inicio"] = max(t - 0.3, 0)
        for w in c["fala"].split():
            palavras.append({"palavra": w, "inicio": round(t, 3), "fim": round(t + 0.34, 3)})
            t += 0.385
        t += 0.25
        c["fim"] = t - 0.1
    for a, b in zip(cenas, cenas[1:]):
        a["fim"] = b["inicio"]
    return palavras, t


EXEMPLO = {
    "lang": "pt", "titulo": "E se a Lua sumisse?",
    "cenas": [
        {"fala": "E se a Lua sumisse hoje à noite?", "cenario": "cidade_noite", "acao": "surpreso",
         "camera": "frente", "texto_topo": {"texto": "E se... a Lua sumisse?", "destaque": "a Lua"}},
        {"fala": "Ela está a trezentos e oitenta e quatro mil quilômetros daqui.", "cenario": "espaco",
         "acao": "aponta", "objeto": "lua", "camera": "frente",
         "contador": {"de": 0, "ate": 384400, "rotulo": "quilômetros", "sufixo": ""}},
        {"fala": "Sem ela, as marés quase parariam.", "cenario": "estudio", "acao": "pensa", "camera": "close",
         "texto_topo": {"texto": "Passo 1 · as marés", "destaque": "as marés"}},
        {"fala": "E os dias ficariam mais curtos. Bem mais curtos.", "cenario": "estudio", "acao": "medo",
         "objeto": "relogio", "camera": "destaque"},
        {"fala": "Você ia perceber? Comenta aí.", "cenario": "cidade_noite", "acao": "acena", "camera": "baixo"},
    ],
}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--exemplo", action="store_true", help="grava quadros soltos do exemplo (sem áudio)")
    ap.add_argument("--video", action="store_true", help="grava o exemplo inteiro em vídeo")
    ap.add_argument("--gpu", action="store_true", help="usa a placa de vídeo (no PC; na nuvem não existe)")
    ap.add_argument("--escala", type=float, default=1.0, help="resolução interna do 3D (0.67 = 720p esticado)")
    a = ap.parse_args()
    sb = {**EXEMPLO, "cenas": [dict(c) for c in EXEMPLO["cenas"]], "escala_3d": a.escala}
    sb["palavras"], sb["duracao"] = _palavras_falsas(sb["cenas"])
    saida = STORAGE / "work" / "estudio3d"
    saida.mkdir(parents=True, exist_ok=True)
    if a.video:
        import time
        inicio = time.time()
        gravar(sb, saida / "exemplo.mp4", gpu=a.gpu)
        print(f"vídeo: {saida / 'exemplo.mp4'} ({time.time() - inicio:.0f}s para {sb['duracao']:.1f}s de vídeo)")
    else:
        with estudio(sb, gpu=a.gpu) as pagina:
            for c in sb["cenas"]:
                t = c["inicio"] + 0.9
                (saida / f"cena_{sb['cenas'].index(c) + 1}.jpg").write_bytes(quadro(pagina, t))
        print("quadros em", saida)
