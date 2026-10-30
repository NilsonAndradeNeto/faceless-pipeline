"""Pesquisa o próximo tema e escreve o roteiro (usado pelo painel e pelo agendador).

Uso: uv run python -m scripts.novo_roteiro --lang pt [--job ID]
     uv run python -m scripts.novo_roteiro --refazer TOPICO_ID [--job ID]   (reescreve um tema já pesquisado)
"""
import argparse
import time

from agents import progresso
from agents.common import STORAGE, idiomas, ler_json
from agents.researcher import pesquisar
from agents.scriptwriter import processar_pendentes

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--lang", choices=idiomas())
    g.add_argument("--refazer")
    ap.add_argument("--job", default=f"roteiro_{int(time.time())}")
    a = ap.parse_args()

    progresso.iniciar(a.job, f"Novo roteiro ({(a.lang or 'refazer').upper()})")
    try:
        if a.refazer:
            topico_id = a.refazer
            progresso.atualizar(0.10, f"Tema: {ler_json(STORAGE / 'topics' / 'pending' / f'{topico_id}.json')['tema']}")
        else:
            progresso.atualizar(0.02, "Escolhendo o tema e pesquisando na Wikipedia")
            topico = pesquisar(a.lang)
            topico_id = topico["id"]
            progresso.atualizar(0.12, f"Tema: {topico['tema']}")
        processar_pendentes(topico_id)
        if not (STORAGE / "scripts" / "pending" / f"{topico_id}.md").exists():
            raise RuntimeError("O roteiro não foi salvo — veja storage/logs/pipeline.log")
        progresso.finalizar()
    except Exception as e:
        progresso.finalizar(erro=str(e)[:300])
        raise
