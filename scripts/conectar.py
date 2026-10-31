"""Conecta as contas de publicação.

  python -m scripts.conectar youtube pt     abre o navegador pra você autorizar o canal
  python -m scripts.conectar instagram pt   confere o token do .env e mostra a conta
"""
import argparse

from agents.common import ROOT, config, idiomas


def youtube(lang: str):
    import os

    from google_auth_oauthlib.flow import InstalledAppFlow

    from pipeline.publicar import ESCOPOS_YT, youtube_cliente

    segredo = ROOT / os.getenv("YOUTUBE_CLIENT_SECRET_FILE", "credentials/client_secret.json")
    if not segredo.exists():
        raise SystemExit(f"Falta o arquivo {segredo} (baixado do Google Cloud).")
    fluxo = InstalledAppFlow.from_client_secrets_file(str(segredo), ESCOPOS_YT)
    cred = fluxo.run_local_server(port=0, prompt="consent", access_type="offline")
    arq = ROOT / config("channels")[lang]["youtube"]["token_file"]
    arq.write_text(cred.to_json(), encoding="utf-8")
    canal = youtube_cliente(lang).channels().list(part="snippet", mine=True).execute()["items"][0]
    print(f"✅ YouTube {lang.upper()} conectado: {canal['snippet']['title']}")


def instagram(lang: str):
    from pipeline.publicar import ig_token
    conta = ig_token(lang)
    print(f"✅ Instagram {lang.upper()} conectado: @{conta['username']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("plataforma", choices=["youtube", "instagram"])
    ap.add_argument("lang", choices=idiomas())
    a = ap.parse_args()
    {"youtube": youtube, "instagram": instagram}[a.plataforma](a.lang)
