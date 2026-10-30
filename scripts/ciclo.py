"""Ciclo automático — roda a cada 15 min (Agendador do Windows) e faz o que estiver na hora.

Rotina (config/settings.yaml → agenda):
  22:30            gera os roteiros do dia seguinte (1 PT + 1 ES), se a fila do idioma estiver vazia
  até 12:00        você valida no painel
  12:00            o que não foi validado é aprovado sozinho (roteiro com frase sem base é refeito;
                   se continuar com problema, o vídeo daquele idioma é pulado no dia)
  depois           produz os vídeos do dia
  17h–22h          publica cada vídeo no horário da plataforma

Se o PC estava desligado, recupera o atraso no mesmo dia. Estado do dia: storage/agenda/AAAA-MM-DD.json
Uso: uv run python -m scripts.ciclo
"""
import logging
import os
import shutil
import time
from datetime import date, datetime, timedelta

from agents import progresso
from agents.common import STORAGE, config, ler_json, salvar_json
from pipeline import produzir as prod
from pipeline.broll_fetcher import SemCotaIA
from pipeline.publicar import PLATAFORMAS, ContaNaoConectada, publicar

log = logging.getLogger("ciclo")

PENDENTES = STORAGE / "scripts" / "pending"
APROVADOS = STORAGE / "scripts" / "approved"
REJEITADOS = STORAGE / "scripts" / "rejected"
AGENDA = STORAGE / "agenda"
TRAVA = STORAGE / "ciclo.lock"
IDIOMAS = ("pt", "es")


def _hora(txt: str, dia: date) -> datetime:
    h, m = map(int, txt.split(":"))
    return datetime.combine(dia, datetime.min.time()).replace(hour=h, minute=m)


def _agenda(dia: date) -> dict:
    arq = AGENDA / f"{dia.isoformat()}.json"
    return ler_json(arq) if arq.exists() else {"data": dia.isoformat()}


def _salvar_agenda(dia: date, ag: dict):
    salvar_json(AGENDA / f"{dia.isoformat()}.json", ag)


def _metas(pasta, lang):
    for arq in sorted(pasta.glob("*.meta.json")):
        meta = ler_json(arq)
        if meta.get("lang") == lang:
            yield arq, meta


def fila(lang: str) -> list[tuple]:
    """Roteiros ainda sem dia marcado: aprovados primeiro (você validou), depois os pendentes."""
    aprovados = [(a, m, "aprovado") for a, m in _metas(APROVADOS, lang) if not m.get("data_post")]
    pendentes = [(a, m, "pendente") for a, m in _metas(PENDENTES, lang) if not m.get("data_post")]
    return aprovados + pendentes


# ---------- 1. gerar roteiros ----------

def gerar_roteiros(agora: datetime):
    cfg = config("settings")["agenda"]
    if agora < _hora(cfg["gerar_roteiros"], agora.date()) and agora >= _hora(cfg["prazo_validacao"], agora.date()):
        return  # entre 12h e 22h30 não gera (o dia já está decidido)
    from agents.researcher import pesquisar
    from agents.scriptwriter import processar_pendentes
    for lang in IDIOMAS:
        if fila(lang):
            continue
        log.info("Fila %s vazia — gerando roteiro", lang.upper())
        progresso.iniciar(f"roteiro_auto_{lang}_{int(time.time())}", f"Roteiro automático ({lang.upper()})")
        try:
            topico = pesquisar(lang)
            processar_pendentes(topico["id"])
            progresso.finalizar()
        except Exception as e:
            log.exception("Falha ao gerar roteiro %s", lang)
            progresso.finalizar(erro=str(e)[:300])


# ---------- 2. definir e aprovar o vídeo do dia ----------

def refazer(meta: dict) -> dict:
    from agents.scriptwriter import escrever
    topico = STORAGE / "topics" / "done" / f"{meta['id']}.json"
    return escrever(ler_json(topico))


def aprovar_automatico(arq, meta) -> bool:
    """Aprova um roteiro pendente. Se tiver frase sem base na fonte, reescreve; se não resolver, recusa."""
    tentativas = config("settings")["agenda"]["tentativas_refazer"]
    for t in range(tentativas + 1):
        if meta.get("checagem", {}).get("confianca") != "baixa":
            meta["aprovacao"] = "automatica"
            salvar_json(arq, meta)
            for ext in (".md", ".meta.json"):
                shutil.move(PENDENTES / f"{meta['id']}{ext}", APROVADOS / f"{meta['id']}{ext}")
            log.info("Aprovado automaticamente: %s", meta["titulo"])
            return True
        if t < tentativas:
            log.warning("'%s' tem frase sem base na fonte — reescrevendo (%d/%d)", meta["titulo"], t + 1, tentativas)
            meta = refazer(meta)
    log.warning("'%s' continuou com frase sem base — pulado", meta["titulo"])
    for ext in (".md", ".meta.json"):
        shutil.move(PENDENTES / f"{meta['id']}{ext}", REJEITADOS / f"{meta['id']}{ext}")
    return False


def em_vigor(dia: date) -> bool:
    return dia >= date.fromisoformat(str(config("settings")["agenda"].get("inicio", "2000-01-01")))


def definir_videos_do_dia(agora: datetime):
    hoje = agora.date()
    if not em_vigor(hoje):
        return
    prazo = _hora(config("settings")["agenda"]["prazo_validacao"], hoje)
    ag = _agenda(hoje)
    for lang in IDIOMAS:
        if lang in ag:
            continue
        candidatos = fila(lang)
        # Antes do prazo só entra o que você já aprovou; no prazo, entra o primeiro da fila
        if agora < prazo:
            candidatos = [c for c in candidatos if c[2] == "aprovado"]
        for arq, meta, situacao in candidatos:
            if situacao == "pendente" and not aprovar_automatico(arq, meta):
                continue
            meta = ler_json(APROVADOS / f"{meta['id']}.meta.json")
            meta["data_post"] = hoje.isoformat()
            salvar_json(APROVADOS / f"{meta['id']}.meta.json", meta)
            ag[lang] = {"script": meta["id"], "titulo": meta["titulo"], "aprovacao": meta.get("aprovacao", "voce"),
                        "posts": {}}
            log.info("Vídeo %s de hoje: %s", lang.upper(), meta["titulo"])
            break
        else:
            if agora >= prazo:
                ag[lang] = {"script": None, "motivo": "nenhum roteiro válido na fila", "posts": {}}
                log.warning("Sem vídeo %s hoje", lang.upper())
    _salvar_agenda(hoje, ag)


# ---------- 3. produzir ----------

COTA_ESGOTADA = STORAGE / "cota_imagens_esgotada.txt"


def _cota_renovou() -> bool:
    """A cota do Cloudflare renova 00:00 UTC (21h Brasília). Depois disso, pode tentar de novo."""
    if not COTA_ESGOTADA.exists():
        return True
    esgotou = datetime.fromtimestamp(COTA_ESGOTADA.stat().st_mtime)
    renova = esgotou.replace(hour=21, minute=5, second=0, microsecond=0)
    if esgotou >= renova:  # esgotou depois das 21h: só renova no dia seguinte
        renova += timedelta(days=1)
    if datetime.now() >= renova:
        COTA_ESGOTADA.unlink(missing_ok=True)
        return True
    return False


def produzir_aprovados():
    if not prod.pendentes_de_producao() or not _cota_renovou():
        return

    def rodar():
        for sid in prod.pendentes_de_producao():
            try:
                prod.produzir(sid)
            except SemCotaIA:
                COTA_ESGOTADA.write_text(datetime.now().isoformat())
                log.info("Cota de imagens acabou — produção continua depois das 21h")
                return
            except Exception:
                log.exception("Falha ao produzir %s (segue para o próximo)", sid)
    prod.com_trava(rodar)


# ---------- 4. publicar ----------

def publicar_no_horario(agora: datetime):
    hoje = agora.date()
    if not em_vigor(hoje):
        return
    ag = _agenda(hoje)
    horarios = config("settings")["agenda"]["postagens"]
    for lang in IDIOMAS:
        item = ag.get(lang)
        if not item or not item.get("script"):
            continue
        video = STORAGE / "shorts" / "ready" / f"{item['script']}.mp4"
        meta_arq = APROVADOS / f"{item['script']}.meta.json"
        for plataforma in PLATAFORMAS:
            if agora < _hora(horarios[lang][plataforma], hoje):
                continue
            feito = item["posts"].get(plataforma, {})
            if feito.get("estado") in ("publicado", "conta não conectada"):
                continue
            if not video.exists():
                item["posts"][plataforma] = {"estado": "vídeo ainda não ficou pronto"}
                continue
            try:
                r = publicar(plataforma, ler_json(meta_arq), video)
                item["posts"][plataforma] = {"estado": "publicado", "quando": agora.strftime("%H:%M"), **r}
                log.info("✅ Publicado %s %s: %s", lang.upper(), plataforma, r.get("url"))
            except ContaNaoConectada as e:
                item["posts"][plataforma] = {"estado": "conta não conectada"}
                log.info("%s", e)
            except Exception as e:
                item["posts"][plataforma] = {"estado": "erro", "erro": str(e)[:300]}
                log.exception("Falha ao publicar %s %s", lang, plataforma)
    _salvar_agenda(hoje, ag)


def ciclo():
    agora = datetime.now()
    log.info("— ciclo %s —", agora.strftime("%d/%m %H:%M"))
    for etapa in (lambda: gerar_roteiros(agora), lambda: definir_videos_do_dia(agora),
                  produzir_aprovados, lambda: publicar_no_horario(datetime.now())):
        try:
            etapa()
        except Exception:
            log.exception("Erro numa etapa do ciclo (as outras continuam)")


if __name__ == "__main__":
    # Ciclos não se sobrepõem (gerar roteiro/vídeo pode levar mais que 15 min)
    if TRAVA.exists() and time.time() - TRAVA.stat().st_mtime < 2 * 3600:
        raise SystemExit(0)
    TRAVA.write_text(str(os.getpid()))
    try:
        ciclo()
    finally:
        TRAVA.unlink(missing_ok=True)
