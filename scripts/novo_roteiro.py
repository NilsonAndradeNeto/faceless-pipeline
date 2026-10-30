"""Pesquisa o próximo tema e escreve o roteiro (usado pelo painel e pelo agendador).

Uso: uv run python -m scripts.novo_roteiro --lang pt
"""
import argparse

from agents.researcher import pesquisar
from agents.scriptwriter import processar_pendentes

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=["pt", "es"], required=True)
    topico = pesquisar(ap.parse_args().lang)
    processar_pendentes(topico["id"])
