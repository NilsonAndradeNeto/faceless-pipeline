"""Progresso de tarefas longas, lido pelo painel (storage/jobs/{job}.json).

Uso: progresso.iniciar(job, titulo) → progresso.atualizar(0.4, "Checando fatos") → progresso.finalizar()
Fora de um job (rodando pelo terminal), atualizar() não faz nada.
"""
import time

from agents.common import STORAGE, ler_json, salvar_json

JOBS = STORAGE / "jobs"
_job: str | None = None


def _arq(job):
    return JOBS / f"{job}.json"


def iniciar(job: str, titulo: str):
    global _job
    _job = job
    salvar_json(_arq(job), {"titulo": titulo, "estado": "rodando", "progresso": 0.0, "detalhe": "Começando…",
                            "inicio": time.time(), "atualizado": time.time()})


def atualizar(fracao: float | None = None, detalhe: str | None = None):
    if not _job or not _arq(_job).exists():
        return
    d = ler_json(_arq(_job))
    if fracao is not None:
        d["progresso"] = round(max(d["progresso"], min(fracao, 1.0)), 3)
    if detalhe is not None:
        d["detalhe"] = detalhe
    d["atualizado"] = time.time()
    salvar_json(_arq(_job), d)


def finalizar(erro: str | None = None):
    if not _job or not _arq(_job).exists():
        return
    d = ler_json(_arq(_job))
    d.update(estado="erro" if erro else "pronto", erro=erro, progresso=d["progresso"] if erro else 1.0,
             atualizado=time.time())
    salvar_json(_arq(_job), d)
