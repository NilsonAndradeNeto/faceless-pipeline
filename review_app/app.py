"""Painel de aprovação — http://localhost:3200

Rodar: uv run streamlit run review_app/app.py --server.port 3200
"""
import shutil
import subprocess
import sys
import time
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agents.common import ROOT, STORAGE, ler_json, salvar_json  # noqa: E402

PENDENTES = STORAGE / "scripts" / "pending"
APROVADOS = STORAGE / "scripts" / "approved"
REJEITADOS = STORAGE / "scripts" / "rejected"
PRONTOS = STORAGE / "shorts" / "ready"
JOBS = STORAGE / "jobs"
BANDEIRA = {"pt": "🇧🇷", "es": "🇪🇸"}

# Processos em segundo plano: prioridade baixa e sem janela
FLAGS = (0x00004000 | 0x00000008 | 0x00000200) if sys.platform == "win32" else 0


def em_segundo_plano(*args):
    log = open(STORAGE / "logs" / "painel_processos.log", "a", encoding="utf-8")
    subprocess.Popen([sys.executable, "-m", *args], cwd=ROOT, stdout=log, stderr=log, creationflags=FLAGS)


def mover(script_id: str, origem: Path, destino: Path):
    for ext in (".md", ".meta.json"):
        shutil.move(origem / f"{script_id}{ext}", destino / f"{script_id}{ext}")


def caracteres_elevenlabs():
    try:
        from pipeline.tts import caracteres_restantes
        return caracteres_restantes()
    except Exception:
        return None


@st.fragment(run_every="2s")
def barra_progresso(meta_path: Path):
    """Relê o status a cada 2s e mostra a porcentagem; quando termina, recarrega a página."""
    prod = ler_json(meta_path).get("producao", {})
    etapa = prod.get("etapa", "na fila")
    if etapa in ("pronto", "erro"):
        st.rerun()
    if etapa.startswith("aguardando"):
        st.warning(f"⏸️ Pausado em {prod.get('progresso', 0):.0%} — cota grátis de imagens acabou hoje. "
                   "Continua sozinho às 21h30.")
        return
    if etapa == "na fila":
        st.info("⏳ Na fila — começa assim que o vídeo anterior terminar.")
        return
    pct = prod.get("progresso", 0)
    st.progress(pct, text=f"**{pct:.0%}** · {prod.get('detalhe') or etapa}")


@st.fragment(run_every="2s")
def roteiros_em_andamento():
    """Barra de cada roteiro sendo escrito; quando termina, recarrega pra mostrar o roteiro novo."""
    jobs = JOBS.glob("roteiro_*.json") if JOBS.exists() else []
    for arq in sorted(jobs):
        try:
            job = ler_json(arq)
        except Exception:
            continue  # arquivo sendo escrito neste instante
        if job["estado"] == "pronto":
            arq.unlink(missing_ok=True)
            st.rerun()
        with st.container(border=True):
            minutos = (time.time() - job["inicio"]) / 60
            if job["estado"] == "erro":
                st.error(f"❌ {job['titulo']} falhou: {job.get('erro')}")
                if st.button("Fechar aviso", key=f"fechar_{arq.stem}"):
                    arq.unlink(missing_ok=True)
                    st.rerun()
            elif time.time() - job["atualizado"] > 20 * 60:
                st.warning(f"⚠️ {job['titulo']} parou de responder há mais de 20 min.")
                if st.button("Fechar aviso", key=f"fechar_{arq.stem}"):
                    arq.unlink(missing_ok=True)
                    st.rerun()
            else:
                st.caption(f"✍️ {job['titulo']} · {minutos:.0f} min")
                st.progress(job["progresso"], text=f"**{job['progresso']:.0%}** · {job['detalhe']}")


st.set_page_config(page_title="Arquivo Sombrio — Painel", page_icon="🕯️", layout="centered")
st.title("🕯️ Painel de aprovação")

pendentes = sorted(PENDENTES.glob("*.meta.json"))
aprovados = sorted(APROVADOS.glob("*.meta.json"), reverse=True)

with st.sidebar:
    st.metric("Roteiros esperando você", len(pendentes))
    st.metric("Vídeos prontos", len(list(PRONTOS.glob("*.mp4"))))
    restantes = caracteres_elevenlabs()
    if restantes is not None:
        st.metric("Voz ElevenLabs (caracteres)", f"{restantes:,}".replace(",", "."),
                  help="Cada Short gasta ~1.100. Quando acabar, renova no próximo mês.")
    st.divider()
    lang = st.selectbox("Gerar roteiro em", ["pt", "es"], format_func=lambda l: f"{BANDEIRA[l]} {l.upper()}")
    if st.button("✍️ Gerar 1 roteiro novo agora", use_container_width=True):
        em_segundo_plano("scripts.novo_roteiro", "--lang", lang, "--job", f"roteiro_{int(time.time())}")
        st.success("Começou! Acompanhe a barra na aba Roteiros.")
    if st.button("🔄 Atualizar", use_container_width=True):
        st.rerun()

aba_roteiros, aba_videos = st.tabs([f"📝 Roteiros ({len(pendentes)})", f"🎬 Vídeos ({len(aprovados)})"])

with aba_roteiros:
    roteiros_em_andamento()
    if not pendentes:
        st.info("Nenhum roteiro esperando. Use **Gerar 1 roteiro novo** na barra lateral.")
    for meta_path in pendentes:
        meta = ler_json(meta_path)
        sid = meta["id"]
        texto = (PENDENTES / f"{sid}.md").read_text(encoding="utf-8").strip()
        with st.container(border=True):
            st.caption(f"{BANDEIRA.get(meta['lang'], '')} {meta['tema']}")
            titulo = st.text_input("Título", meta["titulo"], key=f"t_{sid}")

            chk = meta.get("checagem", {})
            for frase in chk.get("sem_comprovacao", []):
                st.error(f"❌ **Sem base na fonte — corrija ou apague:** {frase}")
            for frase in chk.get("conferir", []):
                st.warning(f"⚠️ **Conferir:** {frase}")

            novo = st.text_area("Roteiro (é exatamente o que vai ser narrado)", texto, height=330, key=f"r_{sid}")
            palavras = len(novo.split())
            segundos = palavras / 2.4
            cor = "🟢" if 61 <= segundos <= 85 else "🟠"
            st.caption(f"{cor} {palavras} palavras · ~{segundos:.0f}s · {len(novo)} caracteres de voz "
                       f"(precisa passar de 60s para o TikTok pagar)")
            descricao = st.text_area("Descrição do post", meta["descricao"], height=80, key=f"d_{sid}")
            st.caption("Fontes: " + " · ".join(f"[{f['titulo']}]({f['url']})" for f in meta.get("fontes", [])))

            c1, c2, c3 = st.columns(3)
            if c1.button("✅ Aprovar e produzir", key=f"a_{sid}", type="primary", use_container_width=True):
                (PENDENTES / f"{sid}.md").write_text(novo.strip() + "\n", encoding="utf-8")
                meta.update({"titulo": titulo, "descricao": descricao, "palavras": palavras,
                             "caracteres": len(novo), "editado_no_painel": novo.strip() != texto})
                salvar_json(meta_path, meta)
                mover(sid, PENDENTES, APROVADOS)
                em_segundo_plano("pipeline.produzir", "--todos")
                st.success("Aprovado! O vídeo fica pronto em ~5 minutos na aba Vídeos.")
                st.rerun()
            if c2.button("🔁 Refazer roteiro", key=f"f_{sid}", use_container_width=True,
                         help="Descarta este texto e escreve outro sobre o mesmo tema"):
                topico = STORAGE / "topics" / "done" / f"{sid}.json"
                if topico.exists():
                    shutil.move(topico, STORAGE / "topics" / "pending" / topico.name)
                mover(sid, PENDENTES, REJEITADOS)
                em_segundo_plano("scripts.novo_roteiro", "--refazer", sid, "--job", f"roteiro_{int(time.time())}")
                st.info("Reescrevendo — acompanhe a barra no topo desta aba.")
                st.rerun()
            if c3.button("❌ Rejeitar", key=f"x_{sid}", use_container_width=True):
                mover(sid, PENDENTES, REJEITADOS)
                st.rerun()

with aba_videos:
    if not aprovados:
        st.info("Nenhum roteiro aprovado ainda.")
    for meta_path in aprovados:
        meta = ler_json(meta_path)
        prod = meta.get("producao", {})
        etapa = prod.get("etapa", "na fila")
        with st.container(border=True):
            st.subheader(f"{BANDEIRA.get(meta['lang'], '')} {meta['titulo']}")
            video = PRONTOS / f"{meta['id']}.mp4"
            if etapa == "pronto" and video.exists():
                col_v, col_i = st.columns([1, 1])
                col_v.video(str(video))
                col_i.markdown(f"**Duração:** {meta.get('duracao_seg', '?')}s")
                col_i.markdown(f"**Descrição:** {meta['descricao']}")
                col_i.markdown("**Hashtags:** " + " ".join(f"#{h}" for h in meta.get("hashtags", [])))
                col_i.caption(f"Arquivo: {video}")
            elif etapa == "erro":
                st.error(f"Falhou — {prod.get('erro')}")
                if st.button("Tentar de novo", key=f"re_{meta['id']}"):
                    em_segundo_plano("pipeline.produzir", "--todos")
                    st.rerun()
            else:
                barra_progresso(meta_path)
