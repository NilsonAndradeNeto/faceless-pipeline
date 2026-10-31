"""Gera/baixa o visual de cada cena seguindo o plano do visual_planner.

Ordem: imagem real do artigo-fonte → IA Cloudflare (lucid-origin, vertical) → IA flux-schnell → Pixabay foto.
Uso: uv run python -m pipeline.broll_fetcher --id ID
Atualiza storage/scripts/{id}.scenes.json com "midia" e grava créditos no .meta.json.
"""
import argparse
import base64
import hashlib
import logging
import os
import time
from pathlib import Path

import requests

from agents.common import STORAGE, ler_json, salvar_json

log = logging.getLogger("broll")

CACHE = STORAGE / "broll"
# Wikimedia exige User-Agent identificável e limita downloads em sequência
HEADERS = {"User-Agent": "FacelessHistoryPipeline/0.1 (educational history shorts; python-requests)"}
LICENCAS_OK = ("public domain", "pd", "cc0", "cc by", "cc-by", "attribution")

# Modelos de imagem do Cloudflare Workers AI (plano grátis = 10 mil "neurons"/dia, renova 00:00 UTC).
# lucid-origin é o mais bonito e o mais caro (~30 imagens/dia): só nas cenas do gancho.
# flux-2-klein-4b é barato e também gera na vertical: resto das cenas. flux-1-schnell (quadrado) é reserva.
LUCID = ("@cf/leonardo/lucid-origin", {"width": 768, "height": 1344}, False)
KLEIN = ("@cf/black-forest-labs/flux-2-klein-4b", {"width": "768", "height": "1344"}, True)  # exige multipart
SCHNELL = ("@cf/black-forest-labs/flux-1-schnell", {"steps": 6}, False)
CENAS_PREMIUM = 3


class SemCotaIA(Exception):
    pass


def _cache(chave: str, ext: str):
    return CACHE / f"{hashlib.sha1(chave.encode()).hexdigest()[:16]}.{ext}"


def baixar(url: str, ext: str, tentativas: int = 5):
    destino = _cache(url, ext)
    if destino.exists() and destino.stat().st_size > 10_000:
        return destino
    for t in range(1, tentativas + 1):
        r = requests.get(url, headers=HEADERS, timeout=120)
        if r.status_code == 429 and t < tentativas:
            espera = int(r.headers.get("retry-after", 0) or 0) or 8 * t
            log.info("Limite de download, aguardando %ds", espera)
            time.sleep(espera)
            continue
        r.raise_for_status()
        destino.write_bytes(r.content)
        time.sleep(1.5)  # gentileza com os servidores
        return destino


def imagem_real(real: dict) -> dict | None:
    if not any(l in real.get("licenca", "").lower() for l in LICENCAS_OK):
        return None
    return {"tipo": "imagem", "fonte": "wikimedia", "url": real["url"], "arquivo": str(baixar(real["url"], "jpg")),
            "credito": f"{real['nome']} — {real['autor']} ({real['licenca']})"}


def imagem_ia(prompt: str, modelos_esgotados: set, premium: bool = False) -> dict | None:
    conta, token = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip(), os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
    if not (conta and token):
        return None
    ordem = [LUCID, KLEIN, SCHNELL] if premium else [KLEIN, LUCID, SCHNELL]
    for modelo, extra, multipart in ordem:
        if modelo in modelos_esgotados:
            continue
        destino = _cache(modelo + prompt, "jpg")
        if destino.exists():
            return {"tipo": "imagem", "fonte": "ia", "arquivo": str(destino), "credito": "imagem gerada por IA"}
        for tentativa in range(3):
            campos = {"prompt": prompt, **extra}
            envio = {"files": {k: (None, str(v)) for k, v in campos.items()}} if multipart else {"json": campos}
            r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{conta}/ai/run/{modelo}",
                              headers={"Authorization": f"Bearer {token}"}, timeout=180, **envio)
            if r.ok:
                destino.write_bytes(base64.b64decode(r.json()["result"]["image"]))
                return {"tipo": "imagem", "fonte": "ia", "modelo": modelo, "arquivo": str(destino),
                        "credito": "imagem gerada por IA"}
            texto = r.text.lower()
            if r.status_code == 429 and ("daily" in texto or "allocation" in texto or "neurons" in texto):
                log.warning("Cota grátis diária de %s esgotada", modelo)
                modelos_esgotados.add(modelo)
                break
            log.warning("%s falhou (%s): %s", modelo, r.status_code, r.text[:150])
            time.sleep(5 * (tentativa + 1))
    return None


def pixabay_foto(busca: str, usados: set) -> dict | None:
    chave = os.getenv("PIXABAY_API_KEY")
    if not chave:
        return None
    palavras = [p for p in busca.split(",")[0].split() if len(p) > 3][:3]
    for q in (" ".join(palavras), palavras[0] if palavras else "dark history"):
        r = requests.get("https://pixabay.com/api/", timeout=30, params={
            "key": chave, "q": q, "per_page": 20, "safesearch": "true", "min_width": 1080})
        for hit in r.json().get("hits", []):
            url = hit.get("largeImageURL")
            if url and url not in usados:
                return {"tipo": "imagem", "fonte": "pixabay", "url": url,
                        "arquivo": str(baixar(url, "jpg")), "credito": f"Pixabay #{hit['id']}"}
    return None


def buscar(script_id: str, pasta_script=None, progresso=None) -> list[dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    pasta_script = pasta_script or STORAGE / "scripts" / "approved"
    arq_cenas = STORAGE / "scripts" / f"{script_id}.scenes.json"
    cenas = ler_json(arq_cenas)
    usados, esgotados = set(), set()

    for i, c in enumerate(cenas):
        if progresso:
            progresso(i / len(cenas), f"Gerando imagens: cena {c['n']} de {len(cenas)}")
        # Retomada: cena que já tem imagem boa (IA ou real do artigo) não é refeita
        feita = c.get("midia")
        if feita and feita["fonte"] in ("ia", "wikimedia") and Path(feita["arquivo"]).exists():
            usados.add(feita.get("url") or feita["arquivo"])
            continue
        v, midia = c["visual"], None
        fontes = []
        if v.get("real"):
            fontes.append(lambda: imagem_real(v["real"]))
        # Pixabay NÃO entra como reserva: foto genérica sem relação com a fala derruba a retenção.
        fontes.append(lambda: imagem_ia(v["ia"], esgotados, premium=c["n"] <= CENAS_PREMIUM))
        for fonte in fontes:
            try:
                midia = fonte()
            except Exception as e:
                log.warning("Cena %d: erro numa fonte (%s), tentando a próxima", c["n"], str(e)[:120])
            if midia:
                break
        if not midia:
            salvar_json(arq_cenas, cenas)  # guarda o que já foi feito; o cache evita gerar de novo
            if {LUCID[0], KLEIN[0], SCHNELL[0]} <= esgotados:
                raise SemCotaIA("Cota grátis diária de imagens acabou — testa de novo a cada hora")
            raise RuntimeError(f"Cena {c['n']} ficou sem visual")
        usados.add(midia.get("url") or midia["arquivo"])
        c["midia"] = midia
        log.info("Cena %2d (%.1fs): %-9s %s", c["n"], c["duracao"], midia["fonte"], c["texto"][:60])

    salvar_json(arq_cenas, cenas)
    meta_path = pasta_script / f"{script_id}.meta.json"
    meta = ler_json(meta_path)
    meta["creditos_imagens"] = sorted({c["midia"]["credito"] for c in cenas if c["midia"]["fonte"] != "ia"})
    meta["imagens_ia"] = sum(1 for c in cenas if c["midia"]["fonte"] == "ia")
    salvar_json(meta_path, meta)
    return cenas


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--pasta", default="approved")
    a = ap.parse_args()
    buscar(a.id, STORAGE / "scripts" / a.pasta)
