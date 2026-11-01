"""Produz o Short de um roteiro aprovado: narração → plano visual → imagens → montagem.

Uso: uv run python -m pipeline.produzir --id ID      (um roteiro)
     uv run python -m pipeline.produzir --todos      (todos os aprovados que ainda não viraram vídeo)

Só roda um por vez (trava em storage/producao.lock) pra não pesar o PC.
"""
import argparse
import logging
import os
import shutil
import time

from agents.common import STORAGE, ler_json, salvar_json
from agents.visual_planner import planejar
from agents.llm_client import CotaEsgotada
from pipeline.broll_fetcher import SemCotaIA, buscar
from pipeline.tts import narrar
from pipeline.video_builder import montar

log = logging.getLogger("produzir")

APROVADOS = STORAGE / "scripts" / "approved"
TRAVA = STORAGE / "producao.lock"


def espaco_ok() -> bool:
    from agents.common import config
    minimo = config("settings")["limpeza"]["espaco_minimo_livre_gb"]
    livre = shutil.disk_usage(STORAGE).free / 1e9
    if livre < minimo:
        log.error("Só %.0f GB livres (mínimo %d). Produção pausada.", livre, minimo)
    return livre >= minimo


def status(script_id: str, etapa: str, erro: str | None = None, progresso: float | None = None,
           detalhe: str = ""):
    meta_path = APROVADOS / f"{script_id}.meta.json"
    meta = ler_json(meta_path)
    anterior = meta.get("producao", {}).get("progresso", 0)
    meta["producao"] = {"etapa": etapa, "erro": erro, "detalhe": detalhe,
                        "progresso": round(progresso if progresso is not None else anterior, 3),
                        "atualizado": time.strftime("%Y-%m-%d %H:%M:%S")}
    salvar_json(meta_path, meta)


# Fatia da barra de progresso de cada etapa (imagens e montagem são as demoradas)
FAIXAS = {"narração": (0.00, 0.10), "plano visual": (0.10, 0.18), "imagens": (0.18, 0.60), "montagem": (0.60, 1.00)}


def reportar(script_id: str, etapa: str):
    """Callback que as etapas chamam com (fração 0–1, texto) para atualizar a barra."""
    ini, fim = FAIXAS[etapa]

    def _cb(fracao: float, detalhe: str = ""):
        status(script_id, etapa, progresso=ini + (fim - ini) * min(max(fracao, 0), 1), detalhe=detalhe)
    return _cb


def produzir(script_id: str, ate: str | None = None):
    """Produz o vídeo. Com ate="plano visual", só adianta narração e plano (quando não há cota de imagens)."""
    meta = ler_json(APROVADOS / f"{script_id}.meta.json")
    if (STORAGE / "shorts" / "ready" / f"{script_id}.mp4").exists() and meta.get("producao", {}).get("etapa") == "pronto":
        log.info("%s já está pronto", script_id)
        return
    log.info("▶ Produzindo: %s", meta["titulo"])
    ja_narrado = (STORAGE / "audio" / f"{script_id}.words.json").exists()  # não gasta ElevenLabs duas vezes
    etapas = [("narração", lambda: None if ja_narrado else narrar(script_id)),
              ("plano visual", lambda: None if (STORAGE / "scripts" / f"{script_id}.scenes.json").exists()
               else planejar(script_id)),
              ("imagens", lambda: buscar(script_id, progresso=reportar(script_id, "imagens"))),
              ("montagem", lambda: montar(script_id, progresso=reportar(script_id, "montagem")))]
    textos = {"narração": "Gravando narração", "plano visual": "Planejando as cenas",
              "imagens": "Gerando imagens", "montagem": "Montando o vídeo"}
    for nome, fn in etapas:
        status(script_id, nome, progresso=FAIXAS[nome][0], detalhe=textos[nome])
        try:
            fn()
        except SemCotaIA as e:
            # Não é erro: o agendador retoma depois que a cota renova (narração já feita é reaproveitada)
            log.warning("%s", e)
            status(script_id, "aguardando cota grátis de imagens (testa de novo a cada hora, retoma sozinho)")
            raise
        except CotaEsgotada as e:
            log.warning("%s", e)
            status(script_id, "aguardando cota do Gemini (qualidade em primeiro — retoma sozinho)")
            raise
        except Exception as e:
            log.exception("Falhou na etapa %s", nome)
            status(script_id, "erro", f"{nome}: {str(e)[:300]}")
            raise
        if nome == ate:
            status(script_id, "aguardando cota grátis de imagens (testa de novo a cada hora, retoma sozinho)")
            log.info("Adiantado até '%s': %s", ate, meta["titulo"])
            return
    status(script_id, "pronto", progresso=1.0)
    log.info("✅ Pronto: %s", meta["titulo"])


def pendentes_de_producao() -> list[str]:
    """A cota grátis de imagens dá para poucos vídeos por dia: primeiro os que já têm dia de
    postagem hoje ou adiante, depois os sem dia; os de dia que já passou ficam por último."""
    hoje = time.strftime("%Y-%m-%d")
    fila = []
    for m in sorted(APROVADOS.glob("*.meta.json")):
        meta = ler_json(m)
        if meta.get("producao", {}).get("etapa") not in ("pronto",):
            dia = meta.get("data_post")
            ordem = 0 if dia and dia >= hoje else (1 if not dia else 2)
            fila.append((ordem, dia or "", meta["id"]))
    return [sid for *_, sid in sorted(fila)]


def produzir_fila() -> str | None:
    """Produz todos os aprovados. Devolve o que faltou: "imagens", "gemini" ou None (tudo certo)."""
    sem_imagens = False
    for sid in pendentes_de_producao():
        try:
            produzir(sid, ate="plano visual" if sem_imagens else None)
        except SemCotaIA:
            sem_imagens = True  # os próximos só adiantam narração e plano
        except CotaEsgotada:
            return "gemini"     # sem Gemini os próximos também param no plano visual
        except Exception:
            log.exception("Falha ao produzir %s (segue para o próximo)", sid)
    return "imagens" if sem_imagens else None


def com_trava(fn):
    if TRAVA.exists() and time.time() - TRAVA.stat().st_mtime < 3 * 3600:
        log.info("Já existe uma produção rodando (storage/producao.lock). Saindo.")
        return
    TRAVA.write_text(str(os.getpid()))
    try:
        fn()
    finally:
        TRAVA.unlink(missing_ok=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--id")
    g.add_argument("--todos", action="store_true")
    a = ap.parse_args()

    def rodar():
        if not espaco_ok():
            return
        if a.id:
            try:
                produzir(a.id)
            except (SemCotaIA, CotaEsgotada):
                pass  # status já registrado; retoma sozinho
        else:
            produzir_fila()

    com_trava(rodar)
