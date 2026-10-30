"""Publicação nas redes. Cada plataforma é ligada quando a conta for conectada.

publicar(plataforma, meta, video) → {"url": ..., "id": ...}
Enquanto a conta não estiver conectada, levanta ContaNaoConectada (o ciclo registra e segue).
"""
import logging

log = logging.getLogger("publicar")

PLATAFORMAS = ("youtube", "instagram", "tiktok")


class ContaNaoConectada(Exception):
    pass


def publicar(plataforma: str, meta: dict, video) -> dict:
    if plataforma not in PLATAFORMAS:
        raise ValueError(f"Plataforma desconhecida: {plataforma}")
    raise ContaNaoConectada(f"Conta {plataforma} ({meta['lang'].upper()}) ainda não conectada")
