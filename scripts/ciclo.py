"""Ciclo automático — faz o que estiver na hora. Roda de hora em hora no GitHub Actions
(.github/workflows/ciclo.yml) ou a cada 15 min no Agendador do Windows.

Rotina (config/settings.yaml → agenda):
  22:30            gera os roteiros do dia seguinte (1 por idioma), se a fila do idioma estiver vazia
  até 12:00        você valida no Telegram (ou no painel, no PC)
  12:00            o que não foi validado é aprovado sozinho (roteiro com frase sem base é refeito;
                   se continuar com problema, o vídeo daquele idioma é pulado no dia)
  depois           produz os vídeos do dia
  17h–22h          publica cada vídeo no horário da plataforma

Se o PC estava desligado, recupera o atraso no mesmo dia. Estado do dia: storage/agenda/AAAA-MM-DD.json
Uso: uv run python -m scripts.ciclo
"""
import html
import logging
import os
import shutil
import time
from datetime import date, datetime, timedelta

from agents import progresso, telegram
from agents.common import BANDEIRA, NUVEM, STORAGE, config, idiomas, ler_json, salvar_json
from pipeline import produzir as prod
from pipeline.publicar import PLATAFORMAS, ContaNaoConectada, publicar

log = logging.getLogger("ciclo")

PENDENTES = STORAGE / "scripts" / "pending"
APROVADOS = STORAGE / "scripts" / "approved"
REJEITADOS = STORAGE / "scripts" / "rejected"
AGENDA = STORAGE / "agenda"
TRAVA = STORAGE / "ciclo.lock"
IDIOMAS = tuple(idiomas())


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
            # Tema já pesquisado numa tentativa que parou (ex.: Gemini no limite) é reaproveitado
            pesquisados = sorted((STORAGE / "topics" / "pending").glob(f"*_{lang}.json"))
            topico_id = pesquisados[0].stem if pesquisados else pesquisar(lang)["id"]
            processar_pendentes(topico_id)
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

def produzir_aprovados():
    """Todo ciclo tenta: vídeo com as imagens já prontas monta mesmo sem cota, e testar a cota
    do Cloudflare quando ela acabou custa só uma chamada recusada."""
    if not prod.pendentes_de_producao():
        return

    def rodar():
        faltou = prod.produzir_fila()
        if faltou == "imagens":
            log.info("Cota de imagens acabou — narração/plano adiantados; tenta de novo no próximo ciclo")
        elif faltou == "gemini":
            log.info("Gemini no limite — produção retoma no próximo ciclo")
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
            if feito.get("estado") == "publicado":
                continue
            # Conta que você conectar depois do horário ainda posta no mesmo dia; erro tenta até 3x
            if feito.get("estado") == "erro" and feito.get("tentativas", 1) >= 3:
                continue
            if not video.exists():
                item["posts"][plataforma] = {"estado": "vídeo ainda não ficou pronto"}
                continue
            try:
                r = publicar(plataforma, ler_json(meta_arq), video)
                item["posts"][plataforma] = {"estado": "publicado", "quando": agora.strftime("%H:%M"), **r}
                log.info("✅ Publicado %s %s: %s", lang.upper(), plataforma, r.get("url"))
                privado = "\n🔒 Entrou como privado: mude para público no app." if r.get("privacidade") == "private" else ""
                telegram.enviar(f"✅ <b>Postado no {plataforma.title()}</b> {BANDEIRA[lang]}\n"
                                f"{html.escape(item['titulo'])}\n{r.get('url', '')}{privado}")
            except ContaNaoConectada as e:
                item["posts"][plataforma] = {"estado": "conta não conectada"}
                log.info("%s", e)
            except Exception as e:
                item["posts"][plataforma] = {"estado": "erro", "erro": str(e)[:300],
                                             "tentativas": feito.get("tentativas", 0) + 1}
                log.exception("Falha ao publicar %s %s", lang, plataforma)
                telegram.enviar(f"❌ <b>Falhou ao postar no {plataforma.title()}</b> {BANDEIRA[lang]} "
                                f"(tentativa {item['posts'][plataforma]['tentativas']}/3)\n{html.escape(str(e)[:300])}")
    _salvar_agenda(hoje, ag)


# ---------- Telegram (aprovação pelo celular) ----------

def mover(sid: str, origem, destino):
    for ext in (".md", ".meta.json"):
        shutil.move(origem / f"{sid}{ext}", destino / f"{sid}{ext}")


def respostas_telegram():
    """Aplica os botões que você apertou no Telegram desde o último ciclo."""
    for acao, sid in telegram.ler_respostas():
        if acao in ("ap", "rf", "rj"):
            if not (PENDENTES / f"{sid}.meta.json").exists():
                telegram.enviar("ℹ️ Esse roteiro já tinha sido decidido (aprovado no prazo ou refeito).")
                continue
            meta = ler_json(PENDENTES / f"{sid}.meta.json")
        if acao == "ap":
            meta["aprovacao"] = "voce"
            salvar_json(PENDENTES / f"{sid}.meta.json", meta)
            mover(sid, PENDENTES, APROVADOS)
            telegram.enviar(f"✅ Aprovado: <b>{html.escape(meta['titulo'])}</b>. Te mando o vídeo quando ficar pronto.")
        elif acao == "rj":
            mover(sid, PENDENTES, REJEITADOS)
            telegram.enviar(f"❌ Rejeitado: {html.escape(meta['titulo'])}. Outro tema entra na fila.")
        elif acao == "rf":
            mover(sid, PENDENTES, REJEITADOS)
            telegram.enviar(f"🔁 Reescrevendo: {html.escape(meta['titulo'])}…")
            try:
                refazer(meta)  # o novo roteiro vai pros pendentes e é avisado no fim do ciclo
            except Exception as e:
                log.exception("Falha ao refazer %s", sid)
                telegram.enviar(f"❌ Não consegui reescrever agora ({html.escape(str(e)[:200])}). "
                                "Um tema novo entra no próximo ciclo.")
        elif acao in ("status", "start"):
            telegram.enviar(resumo())


def resumo() -> str:
    hoje = date.today()
    linhas = [f"📅 <b>Hoje ({hoje.strftime('%d/%m')})</b>"]
    ag = _agenda(hoje)
    for lang in IDIOMAS:
        item = ag.get(lang)
        if not item or not item.get("script"):
            linhas.append(f"{BANDEIRA[lang]} a definir")
            continue
        posts = " · ".join(f"{p}: {v.get('estado')}" for p, v in item["posts"].items()) or "ainda não postado"
        linhas.append(f"{BANDEIRA[lang]} {html.escape(item['titulo'])}\n   {posts}")
    linhas.append(f"\n📝 Roteiros esperando você: {len(list(PENDENTES.glob('*.meta.json')))}")
    return "\n".join(linhas)


def avisos_telegram():
    """Manda o que ainda não foi avisado: roteiros novos e vídeos que ficaram prontos."""
    for arq in sorted(PENDENTES.glob("*.meta.json")):
        meta = ler_json(arq)
        if not meta.get("avisado_telegram") and telegram.ativo():
            telegram.avisar_roteiro(meta, (PENDENTES / f"{meta['id']}.md").read_text(encoding="utf-8").strip())
            meta["avisado_telegram"] = True
            salvar_json(arq, meta)
    for arq in sorted(APROVADOS.glob("*.meta.json")):
        meta = ler_json(arq)
        video = STORAGE / "shorts" / "ready" / f"{meta['id']}.mp4"
        if meta.get("producao", {}).get("etapa") == "pronto" and not meta.get("video_enviado") and video.exists() \
                and telegram.ativo():
            dia = meta.get("data_post")
            quando = f"Posta em {date.fromisoformat(dia).strftime('%d/%m')}" if dia else "Ainda sem dia de postagem"
            telegram.enviar_video(video, f"🎬 <b>Vídeo pronto</b> {BANDEIRA[meta['lang']]}\n"
                                         f"{html.escape(meta['titulo'])}\n{quando}.")
            meta["video_enviado"] = True
            salvar_json(arq, meta)


def garantir_painel():
    """Se o painel (porta 3200) caiu, sobe de novo pela tarefa agendada."""
    if NUVEM:
        return  # na nuvem o painel é o Telegram
    import socket
    import subprocess
    with socket.socket() as s:
        s.settimeout(2)
        if s.connect_ex(("127.0.0.1", 3200)) == 0:
            return
    log.warning("Painel fora do ar — reiniciando")
    subprocess.run(["schtasks", "/Run", "/TN", "Faceless - Painel"], capture_output=True,
                   creationflags=0x08000000)


def ciclo():
    agora = datetime.now()
    log.info("— ciclo %s —", agora.strftime("%d/%m %H:%M"))
    for etapa in (garantir_painel, respostas_telegram, lambda: gerar_roteiros(agora),
                  lambda: definir_videos_do_dia(agora), avisos_telegram, produzir_aprovados, avisos_telegram,
                  lambda: publicar_no_horario(datetime.now())):
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
