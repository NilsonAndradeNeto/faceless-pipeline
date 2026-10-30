"""Cliente de LLM: Groq primeiro, OpenAI como fallback, com retry e log de custo."""
import json
import logging
import os
import time

from agents.common import STORAGE, anexar_jsonl, config

log = logging.getLogger("llm")

# US$ por 1M tokens (entrada, saída). Groq no plano grátis custa 0; valores de referência do pago.
PRECOS = {
    "openai/gpt-oss-120b": (0.15, 0.60),
    "gpt-4o-mini": (0.15, 0.60),
}
GROQ_GRATIS = True


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


def _provedores():
    cfg = config("settings")["llm"]
    provs = []
    if os.getenv("GROQ_API_KEY"):
        provs.append(("groq", cfg["primario"]["model"], _chamar_groq))
    if os.getenv("OPENAI_API_KEY"):
        provs.append(("openai", cfg["fallback"]["model"], _chamar_openai))
    if not provs:
        raise RuntimeError("Nenhuma chave de LLM no .env (GROQ_API_KEY ou OPENAI_API_KEY).")
    return provs


def chat(messages, json_mode=False, temperature=0.7, tarefa="geral", tentativas=3):
    """Envia mensagens ao LLM. Com json_mode=True devolve dict; senão, texto."""
    ultimo_erro = None
    for nome, model, fn in _provedores():
        for tentativa in range(1, tentativas + 1):
            inicio = time.time()
            try:
                r = fn(messages, model, json_mode, temperature)
                texto = r.choices[0].message.content or ""
                _registrar(nome, model, tarefa, r.usage, time.time() - inicio)
                return json.loads(texto) if json_mode else texto
            except json.JSONDecodeError as e:
                ultimo_erro = e
                log.warning("%s devolveu JSON inválido (tentativa %d)", nome, tentativa)
            except Exception as e:
                ultimo_erro = e
                espera = 2 ** tentativa * 5
                log.warning("%s falhou (tentativa %d/%d): %s — aguardando %ds",
                            nome, tentativa, tentativas, str(e)[:120], espera)
                if tentativa < tentativas:
                    time.sleep(espera)
        log.warning("Desistindo de %s, tentando próximo provedor", nome)
    raise RuntimeError(f"Todos os provedores de LLM falharam: {ultimo_erro}")


def _registrar(provedor, model, tarefa, usage, segundos):
    entrada = getattr(usage, "prompt_tokens", 0) or 0
    saida = getattr(usage, "completion_tokens", 0) or 0
    p_in, p_out = PRECOS.get(model, (0, 0))
    custo = 0.0 if (provedor == "groq" and GROQ_GRATIS) else (entrada * p_in + saida * p_out) / 1e6
    anexar_jsonl(STORAGE / "logs" / "llm.jsonl", {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "provedor": provedor, "modelo": model,
        "tarefa": tarefa, "tokens_entrada": entrada, "tokens_saida": saida,
        "custo_usd": round(custo, 6), "segundos": round(segundos, 1),
    })
    log.info("%s/%s [%s] %d→%d tokens, US$%.4f, %.1fs", provedor, model, tarefa, entrada, saida, custo, segundos)
