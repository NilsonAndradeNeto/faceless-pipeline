"""Cliente de LLM com perfis, retry e log de custo.

Perfis (config/settings.yaml → llm):
  padrao   → Groq (grátis) → OpenAI
  roteiro  → Gemini Flash (grátis, escreve melhor) → Groq → OpenAI
"""
import json
import logging
import os
import time

from agents import progresso
from agents.common import STORAGE, anexar_jsonl, config

log = logging.getLogger("llm")

# US$ por 1M tokens (entrada, saída). Groq no plano grátis custa 0; valores de referência do pago.
PRECOS = {
    "openai/gpt-oss-120b": (0.15, 0.60),
    "gpt-4o-mini": (0.15, 0.60),
}
PROVEDORES_GRATIS = {"groq", "gemini"}
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _chamar_groq(messages, model, json_mode, temperature):
    from groq import Groq

    kwargs = dict(model=model, messages=messages, temperature=temperature,
                  max_completion_tokens=8000, reasoning_effort="medium")
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    return Groq(api_key=os.environ["GROQ_API_KEY"], max_retries=0).chat.completions.create(**kwargs)


def _chamar_openai(messages, model, json_mode, temperature):
    from openai import OpenAI

    kwargs = dict(model=model, messages=messages, temperature=temperature)
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"], max_retries=0).chat.completions.create(**kwargs)


def _chamar_gemini(messages, model, json_mode, temperature):
    from openai import OpenAI

    kwargs = dict(model=model, messages=messages, temperature=temperature)
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    cliente = OpenAI(api_key=os.environ["GEMINI_API_KEY"].strip(), base_url=GEMINI_BASE, max_retries=0, timeout=90)
    return cliente.chat.completions.create(**kwargs)


CHAMADAS = {
    "groq": ("GROQ_API_KEY", _chamar_groq),
    "openai": ("OPENAI_API_KEY", _chamar_openai),
    "gemini": ("GEMINI_API_KEY", _chamar_gemini),
}


def _provedores(perfil: str):
    cfg = config("settings")["llm"]
    ordem = [cfg["primario"], cfg["fallback"]]
    if perfil == "roteiro":
        ordem = [cfg["roteirista"], *ordem]
    provs = []
    for p in ordem:
        if not os.getenv(CHAMADAS[p["provider"]][0]):
            continue
        modelos = p["model"] if isinstance(p["model"], list) else [p["model"]]
        provs += [(p["provider"], m, CHAMADAS[p["provider"]][1]) for m in modelos]
    if not provs:
        raise RuntimeError("Nenhuma chave de LLM no .env (GEMINI_API_KEY, GROQ_API_KEY ou OPENAI_API_KEY).")
    return provs


def _espera_limite(erro) -> float | None:
    """Se for limite de taxa (429), devolve quantos segundos o provedor pede para esperar."""
    resp = getattr(erro, "response", None)
    if getattr(erro, "status_code", None) not in (429, 503) or resp is None:
        return None
    try:
        return min(float(resp.headers.get("retry-after", 30)) + 2, 90)
    except ValueError:
        return 30


def _extrair_json(texto: str):
    """Aceita JSON puro ou dentro de bloco ```json```."""
    texto = texto.strip()
    if texto.startswith("```"):
        texto = texto.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(texto)


def chat(messages, json_mode=False, temperature=0.7, tarefa="geral", perfil="padrao",
         tentativas=3, esperas_limite=6):
    """Envia mensagens ao LLM. Com json_mode=True devolve dict; senão, texto.

    Limite de taxa (429) e sobrecarga (503) do plano grátis não contam como falha:
    espera e tenta de novo.
    """
    ultimo_erro = None
    provedores = _provedores(perfil)
    for i, (nome, model, fn) in enumerate(provedores):
        # Se o próximo da lista é outro modelo do mesmo provedor (cota separada), troca em vez de esperar
        tem_irmao = i + 1 < len(provedores) and provedores[i + 1][0] == nome
        falhas = limites = 0
        while falhas < tentativas:
            inicio = time.time()
            try:
                r = fn(messages, model, json_mode, temperature)
                texto = r.choices[0].message.content or ""
                _registrar(nome, model, tarefa, r.usage, time.time() - inicio)
                return _extrair_json(texto) if json_mode else texto
            except json.JSONDecodeError as e:
                ultimo_erro, falhas = e, falhas + 1
                log.warning("%s devolveu JSON inválido (tentativa %d)", nome, falhas)
            except Exception as e:
                ultimo_erro = e
                espera = _espera_limite(e)
                travou = "timed out" in str(e).lower() or "timeout" in type(e).__name__.lower()
                if (espera is not None or travou) and tem_irmao:
                    log.info("%s/%s %s, trocando para %s", nome, model,
                             "travou" if travou else "no limite", provedores[i + 1][1])
                    break
                if espera is not None and limites < esperas_limite:
                    limites += 1
                    log.info("%s: limite por minuto atingido, aguardando %.0fs (%d/%d)",
                             nome, espera, limites, esperas_limite)
                    progresso.atualizar(detalhe=f"Esperando o limite grátis do {nome.title()} liberar (~{espera:.0f}s)…")
                    time.sleep(espera)
                    continue
                falhas += 1
                espera = 2 ** falhas * 5
                log.warning("%s falhou (tentativa %d/%d): %s", nome, falhas, tentativas, str(e)[:120])
                if falhas < tentativas:
                    time.sleep(espera)
        else:
            log.warning("Desistindo de %s/%s, tentando o próximo", nome, model)
    raise RuntimeError(f"Todos os provedores de LLM falharam: {ultimo_erro}")


def _registrar(provedor, model, tarefa, usage, segundos):
    entrada = getattr(usage, "prompt_tokens", 0) or 0
    saida = getattr(usage, "completion_tokens", 0) or 0
    p_in, p_out = PRECOS.get(model, (0, 0))
    custo = 0.0 if provedor in PROVEDORES_GRATIS else (entrada * p_in + saida * p_out) / 1e6
    anexar_jsonl(STORAGE / "logs" / "llm.jsonl", {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "provedor": provedor, "modelo": model,
        "tarefa": tarefa, "tokens_entrada": entrada, "tokens_saida": saida,
        "custo_usd": round(custo, 6), "segundos": round(segundos, 1),
    })
    log.info("%s/%s [%s] %d→%d tokens, US$%.4f, %.1fs", provedor, model, tarefa, entrada, saida, custo, segundos)
