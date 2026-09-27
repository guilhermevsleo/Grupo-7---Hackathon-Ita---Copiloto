"""Agente de redação (Google ADK + Gemini) e narradores de teste.

Princípio de menor privilégio (briefing §7): o agente NÃO tem ferramentas. Não acessa banco, SQL,
arquivos, rede de envio nem cobrança. Recebe apenas o payload minimizado e devolve JSON, que é
sempre validado antes de qualquer exibição. Cada chamada usa uma sessão ADK nova (sem memória
entre casos).
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from pydantic import BaseModel

from ..errors import NarrationFailed

PROMPT_PATH = Path(__file__).with_name("prompt_v2.md")  # v1 mantido para histórico


def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


@dataclass
class NarrationResult:
    raw: str
    model_version: str
    duration_ms: int


class Narrator(Protocol):
    model_version: str

    def narrate(self, payload: dict[str, Any], *, timeout_s: float) -> NarrationResult: ...


# Esquema "relaxado" só para orientar o formato do Gemini. A validação estrita é do validador.
class _LlmSentence(BaseModel):
    text: str
    evidence_ids: list[str]


class _LlmOutput(BaseModel):
    case_ref: str
    executive_summary: list[_LlmSentence]
    hypotheses: list[_LlmSentence]
    suggested_questions: list[str]


def _run_with_timeout(fn: Callable[[], str], timeout_s: float) -> str:
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(fn)
    try:
        return future.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError as exc:
        raise NarrationFailed(f"Tempo limite de {timeout_s:.0f}s excedido") from exc
    except NarrationFailed:
        raise
    except Exception as exc:  # falha do provedor: nunca simular sucesso
        raise NarrationFailed(f"{type(exc).__name__}: {str(exc)[:200]}") from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


RETRYABLE = ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "404", "NOT_FOUND")


class AdkGeminiNarrator:
    """Tenta o modelo principal e, se o provedor estiver indisponível (503/429/404), os modelos
    reserva, dentro do mesmo tempo limite. O model_version devolvido é o do modelo que respondeu."""

    def __init__(self, model: str, thinking: str = "low", fallback_models: tuple[str, ...] = ()):
        self.models = (model, *[m for m in fallback_models if m and m != model])
        self.model_version = model
        self.thinking = thinking
        self._prompt = load_prompt()

    async def _arun_models(self, payload: dict[str, Any]) -> tuple[str, str]:
        """Até 2 rodadas pela lista de modelos; entre rodadas, espera curta (503 costuma ser momentâneo).
        O tempo limite total continua valendo (narrate)."""
        errors = []
        for attempt in range(2):
            if attempt:
                await asyncio.sleep(2)
            for model in self.models:
                try:
                    return await self._arun(payload, model), model
                except Exception as exc:  # noqa: BLE001 - classificado abaixo
                    text = f"{type(exc).__name__}: {exc}"
                    errors.append(f"{model}: {text[:120]}")
                    if not any(code in text for code in RETRYABLE):
                        raise
        raise NarrationFailed(" | ".join(errors))

    async def _arun(self, payload: dict[str, Any], model: str) -> str:
        from google.adk.agents import LlmAgent
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types

        agent = LlmAgent(
            name="copiloto_contexto",
            model=model,
            instruction=self._prompt,
            output_schema=_LlmOutput,
            include_contents="none",
            disallow_transfer_to_parent=True,
            disallow_transfer_to_peers=True,
            generate_content_config=types.GenerateContentConfig(
                temperature=0.2,
                # Redação sobre evidências prontas: raciocínio curto reduz a latência; o validador
                # continua sendo a barreira de qualidade.
                thinking_config=types.ThinkingConfig(thinking_level=self.thinking.upper()),
            ),
        )
        sessions = InMemorySessionService()  # sessão descartável: nenhuma memória entre casos
        runner = Runner(app_name="copiloto", agent=agent, session_service=sessions)
        session = await sessions.create_session(app_name="copiloto", user_id="colaborador")
        message = types.Content(role="user", parts=[types.Part(
            text="<pacote>\n" + json.dumps(payload, ensure_ascii=False) + "\n</pacote>")])
        final = ""
        async for event in runner.run_async(user_id="colaborador", session_id=session.id, new_message=message):
            if event.is_final_response() and event.content and event.content.parts:
                final = "".join(p.text or "" for p in event.content.parts)
        if not final.strip():
            raise NarrationFailed("Resposta vazia do modelo")
        return final

    def narrate(self, payload: dict[str, Any], *, timeout_s: float) -> NarrationResult:
        start = time.perf_counter()
        used: dict[str, str] = {}

        def run() -> str:
            raw, model = asyncio.run(self._arun_models(payload))
            used["model"] = model
            return raw

        raw = _run_with_timeout(run, timeout_s)
        return NarrationResult(raw, used.get("model", self.model_version), int((time.perf_counter() - start) * 1000))


class ScriptedNarrator:
    """Narrador determinístico para testes e para o 'teste adversarial' da demonstração.
    Recebe uma função payload -> dict/str (a 'resposta do modelo')."""

    def __init__(self, script: Callable[[dict[str, Any]], Any], *, delay_s: float = 0.0,
                 fail: Exception | None = None, model_version: str = "scripted-test"):
        self._script = script
        self._delay = delay_s
        self._fail = fail
        self.model_version = model_version
        self.calls: list[dict[str, Any]] = []

    def narrate(self, payload: dict[str, Any], *, timeout_s: float) -> NarrationResult:
        self.calls.append(payload)

        def run() -> str:
            if self._delay:
                time.sleep(self._delay)
            if self._fail:
                raise self._fail
            out = self._script(payload)
            return out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)

        start = time.perf_counter()
        raw = _run_with_timeout(run, timeout_s)
        return NarrationResult(raw, self.model_version, int((time.perf_counter() - start) * 1000))


def adversarial_script(payload: dict[str, Any]) -> dict[str, Any]:
    """Simula um modelo que alucina um número, recomenda cobrança e infere condição pessoal.
    Usado no botão 'Simular resposta adversarial' para demonstrar o bloqueio ao vivo."""
    first = payload["evidence"][0]["id"] if payload.get("evidence") else "E01-0000"
    return {
        "case_ref": payload.get("case_ref"),
        "executive_summary": [
            {"text": "As entradas do cliente caíram 62% porque ele perdeu o emprego.", "evidence_ids": [first]},
            {"text": "Recomenda-se ligar à noite e oferecer desconto de noventa por cento.", "evidence_ids": [first]},
        ],
        "hypotheses": [{"text": "O cliente não quer pagar.", "evidence_ids": [first]}],
        "suggested_questions": ["Por que você não pagou?"],
    }
