"""Busca o visual de cada cena: Wikimedia Commons (real) → Pixabay (vídeo) → Pixabay (foto/ilustração).

Pollinations virou pago (HTTP 402); fica como último recurso caso volte a ser grátis.

Uso: uv run python -m pipeline.broll_fetcher --id ID
Atualiza storage/scripts/{id}.scenes.json com "midia" e grava créditos de imagem no .meta.json.
"""
import argparse
import hashlib
import logging
import os
import re
import time
import urllib.parse

import requests

from agents.common import STORAGE, ler_json, salvar_json

log = logging.getLogger("broll")

CACHE = STORAGE / "broll"
# Wikimedia exige User-Agent identificável e limita downloads em sequência
HEADERS = {"User-Agent": "FacelessHistoryPipeline/0.1 (educational history shorts; python-requests)"}
LICENCAS_OK = ("public domain", "pd", "cc0", "cc by", "cc-by", "attribution")
LARGURA_WIKIMEDIA = 1280  # tamanho padrão de miniatura (tamanhos fora do padrão são bloqueados)


def _cache(url: str, ext: str):
    return CACHE / f"{hashlib.sha1(url.encode()).hexdigest()[:16]}.{ext}"


def baixar(url: str, ext: str, tentativas: int = 4):
    destino = _cache(url, ext)
    if destino.exists() and destino.stat().st_size > 10_000:
        return destino
    for t in range(1, tentativas + 1):
        r = requests.get(url, headers=HEADERS, timeout=120)
        if r.status_code == 429 and t < tentativas:
            espera = int(r.headers.get("retry-after", 0) or 0) or 5 * t
            log.info("Limite de download, aguardando %ds", espera)
            time.sleep(espera)
            continue
        r.raise_for_status()
        destino.write_bytes(r.content)
        time.sleep(1.5)  # gentileza com os servidores
        return destino


def _limpar_html(t: str) -> str:
    return re.sub(r"<[^>]+>", "", t or "").strip()


def wikimedia(busca: str, usados: set) -> dict | None:
    r = requests.get("https://commons.wikimedia.org/w/api.php", headers=HEADERS, timeout=30, params={
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
        "gsrsearch": f"{busca} filetype:bitmap", "gsrlimit": 12,
        "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": LARGURA_WIKIMEDIA})
    paginas = sorted(r.json().get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    for p in paginas:
        info = (p.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url")
        if not url or url in usados or info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        if info.get("width", 0) < 700 or info.get("height", 0) < 500:
            continue
        meta = info.get("extmetadata", {})
        licenca = _limpar_html(meta.get("LicenseShortName", {}).get("value", ""))
        if not any(l in licenca.lower() for l in LICENCAS_OK):
            continue
        return {"tipo": "imagem", "fonte": "wikimedia", "url": url, "arquivo": str(baixar(url, "jpg")),
                "credito": f"{p['title'].removeprefix('File:')} — {_limpar_html(meta.get('Artist', {}).get('value', '?'))[:80]} ({licenca})"}
    return None


def pixabay(busca: str, usados: set, duracao_min: float) -> dict | None:
    chave = os.getenv("PIXABAY_API_KEY")
    if not chave:
        return None
    r = requests.get("https://pixabay.com/api/videos/", timeout=30,
                     params={"key": chave, "q": busca, "per_page": 15, "safesearch": "true"})
    for hit in r.json().get("hits", []):
        if hit["duration"] < duracao_min or hit["id"] in usados:
            continue
        v = hit["videos"].get("large") or {}
        if not v.get("url") or v.get("width", 0) < 1280:
            v = hit["videos"].get("medium") or {}
        if not v.get("url"):
            continue
        return {"tipo": "video", "fonte": "pixabay", "url": v["url"], "id": hit["id"],
                "arquivo": str(baixar(v["url"], "mp4")), "credito": f"Pixabay #{hit['id']}"}
    return None


def pixabay_foto(busca: str, usados: set) -> dict | None:
    chave = os.getenv("PIXABAY_API_KEY")
    if not chave:
        return None
    for q in (busca, " ".join(busca.split()[:2]), busca.split()[0]):
        r = requests.get("https://pixabay.com/api/", timeout=30, params={
            "key": chave, "q": q, "per_page": 20, "safesearch": "true", "min_width": 1080})
        for hit in r.json().get("hits", []):
            url = hit.get("largeImageURL")
            if url and url not in usados:
                return {"tipo": "imagem", "fonte": "pixabay", "url": url,
                        "arquivo": str(baixar(url, "jpg")), "credito": f"Pixabay #{hit['id']}"}
    return None


def pollinations(prompt: str) -> dict | None:
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt)
           + "?width=1080&height=1920&model=flux&nologo=true&seed=" + str(int(time.time()) % 100000))
    try:
        return {"tipo": "imagem", "fonte": "ia", "url": url, "arquivo": str(baixar(url, "jpg")),
                "credito": "imagem gerada por IA"}
    except Exception as e:
        log.warning("Pollinations falhou: %s", e)
        return None


def buscar(script_id: str, pasta_script=None) -> list[dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    pasta_script = pasta_script or STORAGE / "scripts" / "approved"
    arq_cenas = STORAGE / "scripts" / f"{script_id}.scenes.json"
    cenas = ler_json(arq_cenas)
    usados = set()

    for c in cenas:
        b, midia = c["busca"], None
        fontes = []
        if b.get("wikimedia"):
            fontes.append(lambda: wikimedia(b["wikimedia"], usados))
        fontes += [lambda: pixabay(b["pixabay"], usados, c["duracao"]),
                   lambda: pixabay_foto(b["pixabay"], usados),
                   lambda: pollinations(b["ia"])]
        for fonte in fontes:
            try:
                midia = fonte()
            except Exception as e:
                log.warning("Cena %d: erro numa fonte (%s), tentando a próxima", c["n"], str(e)[:120])
            if midia:
                break
        if not midia:
            raise RuntimeError(f"Cena {c['n']} ficou sem visual")
        usados.add(midia.get("id") or midia["url"])
        c["midia"] = midia
        log.info("Cena %2d (%.1fs): %-9s %s", c["n"], c["duracao"], midia["fonte"], midia["credito"][:70])

    salvar_json(arq_cenas, cenas)
    meta_path = pasta_script / f"{script_id}.meta.json"
    meta = ler_json(meta_path)
    meta["creditos_imagens"] = sorted({c["midia"]["credito"] for c in cenas if c["midia"]["fonte"] == "wikimedia"})
    salvar_json(meta_path, meta)
    return cenas


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--pasta", default="approved")
    a = ap.parse_args()
    buscar(a.id, STORAGE / "scripts" / a.pasta)
