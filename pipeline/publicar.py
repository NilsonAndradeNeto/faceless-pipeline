"""Publicação nas redes. Cada plataforma é ligada quando a conta for conectada (scripts/conectar.py).

publicar(plataforma, meta, video) → {"url": ..., "id": ...}
Enquanto a conta não estiver conectada, levanta ContaNaoConectada (o ciclo registra e segue).
"""
import logging
import os
import time
from pathlib import Path

import requests

from agents.common import ROOT, config, ler_json, salvar_json

log = logging.getLogger("publicar")

PLATAFORMAS = ("youtube", "instagram", "tiktok")
ESCOPOS_YT = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
IG_API = "https://graph.instagram.com/v23.0"
FB_API = "https://graph.facebook.com/v23.0"


class ContaNaoConectada(Exception):
    pass


def _legenda(meta: dict) -> str:
    tags = " ".join(f"#{h}" for h in meta.get("hashtags", []))
    return f"{meta['descricao']}\n\n{tags}".strip()


# ---------- YouTube ----------

def youtube_cliente(lang: str):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    arq = ROOT / config("channels")[lang]["youtube"]["token_file"]
    if not arq.exists():
        raise ContaNaoConectada(f"YouTube ({lang.upper()}) não conectado — rode: python -m scripts.conectar youtube {lang}")
    cred = Credentials.from_authorized_user_file(str(arq), ESCOPOS_YT)
    if not cred.valid:
        cred.refresh(Request())
        arq.write_text(cred.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=cred, cache_discovery=False)


def publicar_youtube(meta: dict, video: Path) -> dict:
    from googleapiclient.http import MediaFileUpload

    yt = youtube_cliente(meta["lang"])
    corpo = {
        "snippet": {"title": meta["titulo"][:95], "description": _legenda(meta) + "\n#Shorts",
                    "tags": meta.get("hashtags", [])[:15], "categoryId": "27",
                    "defaultLanguage": meta["lang"], "defaultAudioLanguage": meta["lang"]},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True},
    }
    pedido = yt.videos().insert(part="snippet,status", body=corpo,
                                media_body=MediaFileUpload(str(video), mimetype="video/mp4", resumable=True))
    resposta = None
    while resposta is None:
        _, resposta = pedido.next_chunk()
    vid = resposta["id"]
    privacidade = resposta.get("status", {}).get("privacyStatus")
    if privacidade != "public":
        log.warning("YouTube deixou o vídeo como '%s' (app ainda não auditado pelo Google)", privacidade)
    return {"id": vid, "url": f"https://youtube.com/shorts/{vid}", "privacidade": privacidade}


# ---------- Instagram ----------

def ig_token(lang: str) -> dict:
    """Dois tipos de token:
    EAA… (login unificado, usuário do sistema): nunca expira; usa graph.facebook.com + ig_user_id do channels.yaml.
    IG…  (login do Instagram): vale 60 dias; renovado toda semana e guardado em credentials/."""
    cfg = config("channels")[lang]["instagram"]
    token = os.getenv(cfg["token_env"], "").strip()
    if token.startswith("EAA"):
        uid = str(cfg.get("ig_user_id") or "")
        if not uid:
            raise ContaNaoConectada(f"Instagram ({lang.upper()}): falta ig_user_id em config/channels.yaml")
        r = requests.get(f"{FB_API}/{uid}", params={"fields": "username", "access_token": token}, timeout=30)
        if not r.ok:
            raise ContaNaoConectada(f"Token do Instagram ({lang.upper()}) recusado: {r.text[:200]}")
        return {"token": token, "user_id": uid, "username": r.json()["username"], "api": FB_API}

    arq = ROOT / "credentials" / f"instagram_{lang}.token.json"
    dados = ler_json(arq) if arq.exists() else {}
    if not dados.get("token"):
        env = config("channels")[lang]["instagram"]["token_env"]
        token = os.getenv(env, "").strip()
        if not token:
            raise ContaNaoConectada(f"Instagram ({lang.upper()}) não conectado — falta {env} no .env")
        dados = {"token": token, "renovado": 0}
    # Token de longa duração vale 60 dias: renova toda semana pra nunca expirar
    if time.time() - dados.get("renovado", 0) > 7 * 86400:
        r = requests.get("https://graph.instagram.com/refresh_access_token", timeout=30,
                         params={"grant_type": "ig_refresh_token", "access_token": dados["token"]})
        if r.ok:
            dados.update(token=r.json()["access_token"], renovado=time.time())
        else:
            log.warning("Não consegui renovar o token do Instagram: %s", r.text[:200])
    if "user_id" not in dados:
        r = requests.get(f"{IG_API}/me", params={"fields": "user_id,username", "access_token": dados["token"]}, timeout=30)
        if not r.ok:
            raise ContaNaoConectada(f"Token do Instagram ({lang.upper()}) recusado: {r.text[:200]}")
        dados.update(user_id=r.json()["user_id"], username=r.json()["username"])
    salvar_json(arq, dados)
    return {**dados, "api": IG_API}


def ig_enviar_video(conta: dict, meta: dict, video: Path) -> str:
    """Cria o Reel, sobe o arquivo e espera o Instagram processar. Devolve o id do contêiner (ainda não publicado)."""
    token, uid, api = conta["token"], conta["user_id"], conta["api"]
    r = requests.post(f"{api}/{uid}/media", timeout=60, data={
        "media_type": "REELS", "upload_type": "resumable", "caption": _legenda(meta)[:2100],
        "share_to_feed": "true", "access_token": token})
    _ok(r, "criar o Reel")
    container = r.json()["id"]
    dados = video.read_bytes()
    # Não usar a "uri" devolvida (vem com outra versão da API). O primeiro envio sempre volta
    # "ProcessingFailedError" e o seguinte, no mesmo contêiner, passa: por isso tenta até 5 vezes.
    for tentativa in range(5):
        up = requests.post(f"https://rupload.facebook.com/ig-api-upload/v23.0/{container}",
                           headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(dados))},
                           data=dados, timeout=600)
        if up.ok or "not in the status to upload" in up.text:  # este = um envio anterior já entrou
            break
        time.sleep(5)
    else:
        _ok(up, "enviar o vídeo")
    # O Instagram processa o vídeo antes de deixar publicar
    for _ in range(60):
        s = requests.get(f"{api}/{container}", params={"fields": "status_code,status", "access_token": token},
                         timeout=30).json()
        if s.get("status_code") == "FINISHED":
            return container
        if s.get("status_code") == "ERROR":
            raise RuntimeError(f"Instagram recusou o vídeo: {s.get('status')}")
        time.sleep(10)
    raise RuntimeError("Instagram demorou demais para processar o vídeo")


def _ok(r, etapa: str):
    if not r.ok:
        raise RuntimeError(f"Instagram ao {etapa}: {r.status_code} {r.text[:300]}")


def publicar_instagram(meta: dict, video: Path) -> dict:
    conta = ig_token(meta["lang"])
    token, api = conta["token"], conta["api"]
    container = ig_enviar_video(conta, meta, video)
    p = requests.post(f"{api}/{conta['user_id']}/media_publish", timeout=60,
                      data={"creation_id": container, "access_token": token})
    _ok(p, "publicar")
    mid = p.json()["id"]
    link = requests.get(f"{api}/{mid}", params={"fields": "permalink", "access_token": token}, timeout=30).json()
    return {"id": mid, "url": link.get("permalink", f"https://instagram.com/{conta['username']}")}


def publicar(plataforma: str, meta: dict, video) -> dict:
    if plataforma not in PLATAFORMAS:
        raise ValueError(f"Plataforma desconhecida: {plataforma}")
    if plataforma == "youtube":
        return publicar_youtube(meta, Path(video))
    if plataforma == "instagram":
        return publicar_instagram(meta, Path(video))
    raise ContaNaoConectada(f"Conta {plataforma} ({meta['lang'].upper()}) ainda não conectada")
