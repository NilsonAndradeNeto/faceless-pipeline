"""Telegram: aprovação pelo celular (substitui o painel quando roda na nuvem).

O robô manda cada roteiro novo com botões ✅ 🔁 ❌, o vídeo pronto e os links das postagens.
Só obedece ao seu chat (TELEGRAM_CHAT_ID). Sem TELEGRAM_BOT_TOKEN, tudo aqui fica em silêncio.

Descobrir o chat: mande /start pro bot e rode  python -m agents.telegram --chat
"""
import argparse
import html
import logging
import os
import subprocess
import tempfile
from pathlib import Path

import requests

from agents.common import BANDEIRA, STORAGE, ler_json, salvar_json

log = logging.getLogger("telegram")

ESTADO = STORAGE / "telegram.json"
LIMITE_VIDEO = 45 * 1024 * 1024  # bots enviam até 50 MB


def _token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def _chat() -> str:
    return os.getenv("TELEGRAM_CHAT_ID", "").strip()


def ativo() -> bool:
    return bool(_token() and _chat())


def _chamar(metodo: str, arquivos=None, **dados) -> dict:
    r = requests.post(f"https://api.telegram.org/bot{_token()}/{metodo}", data=dados, files=arquivos, timeout=120)
    resposta = r.json()
    if not resposta.get("ok"):
        raise RuntimeError(f"Telegram {metodo}: {resposta.get('description')}")
    return resposta["result"]


def enviar(texto: str, botoes: list[list[tuple[str, str]]] | None = None):
    """Texto em HTML. botoes = linhas de (rótulo, dado devolvido no clique)."""
    if not ativo():
        return
    extra = {}
    if botoes:
        import json
        extra["reply_markup"] = json.dumps({"inline_keyboard": [
            [{"text": rotulo, "callback_data": dado} for rotulo, dado in linha] for linha in botoes]})
    try:
        _chamar("sendMessage", chat_id=_chat(), text=texto[:4096], parse_mode="HTML",
                disable_web_page_preview="true", **extra)
    except Exception as e:
        log.warning("Não consegui avisar no Telegram: %s", e)


def enviar_video(video: Path, legenda: str):
    """Manda o vídeo pronto pra você assistir no celular (versão leve se passar do limite do bot)."""
    if not ativo():
        return
    with tempfile.TemporaryDirectory() as tmp:
        arq = Path(video)
        if arq.stat().st_size > LIMITE_VIDEO:
            leve = Path(tmp) / "previa.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(arq), "-vf", "scale=720:-2",
                            "-c:v", "libx264", "-crf", "28", "-preset", "fast", "-c:a", "aac", "-b:a", "96k",
                            "-movflags", "+faststart", str(leve)], check=True)
            arq = leve
        try:
            with open(arq, "rb") as f:
                _chamar("sendVideo", arquivos={"video": f}, chat_id=_chat(), caption=legenda[:1024],
                        parse_mode="HTML", supports_streaming="true")
        except Exception as e:
            log.warning("Não consegui mandar o vídeo no Telegram: %s", e)


def avisar_roteiro(meta: dict, texto: str):
    chk = meta.get("checagem", {})
    avisos = "".join(f"\n❌ <b>Sem base na fonte:</b> {html.escape(f)}" for f in chk.get("sem_comprovacao", []))
    avisos += "".join(f"\n⚠️ <b>Conferir:</b> {html.escape(f)}" for f in chk.get("conferir", []))
    palavras = len(texto.split())
    msg = (f"{BANDEIRA.get(meta['lang'], '')} <b>Roteiro novo: {html.escape(meta['titulo'])}</b>\n"
           f"<i>{html.escape(meta['tema'])} · {palavras} palavras · ~{palavras / 2.4:.0f}s</i>\n\n"
           f"{html.escape(texto)}{avisos}\n\n"
           "Se você não responder até o prazo, ele é aprovado sozinho.")
    sid = meta["id"]
    enviar(msg, [[("✅ Aprovar", f"ap:{sid}"), ("🔁 Refazer", f"rf:{sid}"), ("❌ Rejeitar", f"rj:{sid}")]])


def ler_respostas() -> list[tuple[str, str]]:
    """Cliques e comandos recebidos desde a última leitura: [("ap", id), ("status", ""), ...]."""
    if not ativo():
        return []
    estado = ler_json(ESTADO) if ESTADO.exists() else {}
    try:
        updates = _chamar("getUpdates", offset=estado.get("offset", 0), timeout=0)
    except Exception as e:
        log.warning("Não consegui ler o Telegram: %s", e)
        return []
    acoes = []
    for u in updates:
        estado["offset"] = u["update_id"] + 1
        clique = u.get("callback_query")
        msg = u.get("message") or {}
        de = str((clique or {}).get("message", {}).get("chat", {}).get("id") or msg.get("chat", {}).get("id"))
        if de != _chat():
            continue  # só obedece a você
        if clique:
            acao, _, sid = clique.get("data", "").partition(":")
            acoes.append((acao, sid))
            try:
                _chamar("answerCallbackQuery", callback_query_id=clique["id"], text="Recebido! Já cuido disso.")
            except Exception:
                pass  # clique antigo demais pra responder; a ação vale do mesmo jeito
        elif msg.get("text", "").startswith("/"):
            acoes.append((msg["text"].split()[0][1:].split("@")[0].lower(), ""))
    salvar_json(ESTADO, estado)
    return acoes


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat", action="store_true", help="mostra o id do chat de quem mandou /start pro bot")
    a = ap.parse_args()
    if a.chat:
        for u in _chamar("getUpdates"):
            c = (u.get("message") or {}).get("chat")
            if c:
                print(c["id"], c.get("first_name", ""), c.get("username", ""))
