"""Monta o CustomerContext do caso ativo (P4): qualidade → features → evidências → (IA) → validação
→ contexto → auditoria.

Falha, timeout ou saída inválida do LLM nunca derrubam o fluxo: o colaborador vê os fatos
determinísticos e um aviso. Resposta de um caso anterior (troca durante a chamada) é descartada.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .agent.narrator import Narrator
from .bootstrap import App
from .errors import NarrationFailed
from .evidence import EvidenceBundle, build_evidence_bundle
from .features.common import CaseData
from .features.engine import run_features
from .minimizer import PayloadViolation, assert_payload_minimal, build_llm_payload
from .schemas import CustomerContext, Hypothesis, NarrativeSentence
from .session import CaseSession
from .settings import BLOCKED_NARRATIVE_MESSAGE, CONTEXT_SCHEMA_VERSION, FEATURE_ENGINE_VERSION, PROMPT_VERSION
from .validator import ValidationResult, validate_agent_output

MESSAGES = {
    "DISABLED": "IA desativada: exibindo somente fatos e sinais calculados por regras determinísticas.",
    "FAILED": "A IA não respondeu dentro do limite ou falhou. Exibindo somente fatos determinísticos; "
              "nenhum contexto foi inventado.",
    "BLOCKED": BLOCKED_NARRATIVE_MESSAGE + " A resposta foi descartada; exibindo somente fatos determinísticos.",
}


@dataclass
class ContextRun:
    context: CustomerContext | None
    discarded: bool = False
    context_version: str | None = None
    validation: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    bundle: EvidenceBundle | None = None


def _evidence_coverage(ctx: CustomerContext) -> float:
    items = ctx.facts + ctx.signals + ctx.timeline + ctx.executive_summary + ctx.hypotheses
    if not items:
        return 1.0
    ok = sum(1 for i in items if i.evidence_ids and all(e in ctx.evidence for e in i.evidence_ids))
    return round(ok / len(items), 3)


def _audit_payload(context: CustomerContext) -> dict[str, Any]:
    """Versão exata exibida, sem notas livres (referenciadas por id) nem tabelas detalhadas
    (reprodutíveis a partir do snapshot + versões)."""
    data = context.model_dump(mode="json")
    for inter in data["previous_interactions"]:
        inter["notes"] = f"<nota {inter['contact_id']}>" if inter.get("notes") else None
    for src in data["data_quality"]["sources"]:
        src["coverage_note"] = None
    for ev in data["evidence"].values():
        ev["detail"] = f"<{len(ev['detail'])} linhas>" if ev["detail"] else []
    return data


class ContextService:
    def __init__(self, app: App, narrator: Narrator | None):
        self.app = app
        self.narrator = narrator

    def build(self, session: CaseSession, *, ai_enabled: bool) -> ContextRun:
        start = time.perf_counter()
        ctx = session.require_context()
        data = CaseData.load(session.repository(), self.app.schema, ctx.active_customer_id,
                             self.app.sensitive_categories, self.app.sensitive_label)
        bundle = build_evidence_bundle(ctx, run_features(data), self.app.snapshot_version)
        if not session.put(ctx.correlation_id, "bundle", bundle):
            return ContextRun(None, discarded=True)

        status, model_version = "DISABLED", "nenhum (IA desativada)"
        validation: dict[str, Any] = {"ok": None, "violations": [], "mode": "sem_ia"}
        result: ValidationResult | None = None
        llm_ms = 0
        if ai_enabled and self.narrator is not None:
            model_version = self.narrator.model_version
            try:
                payload = build_llm_payload(bundle, self.app.sensitive_label)
                assert_payload_minimal(payload, bundle)
                narration = self.narrator.narrate(payload, timeout_s=self.app.settings.llm_timeout_s)
                llm_ms = narration.duration_ms
                model_version = narration.model_version  # modelo que de fato respondeu
            except (NarrationFailed, PayloadViolation) as exc:
                status = "FAILED"
                validation = {"ok": False, "violations": [{"code": type(exc).__name__, "where": "provedor"}]}
                self.app.audit.record_llm_failure(ctx, model_version=model_version, reason=str(exc))
            else:
                if not session.is_current(ctx.correlation_id):
                    self.app.audit.record_stale_response_discarded(
                        stale_correlation_id=ctx.correlation_id, session_id=session.session_id,
                        employee_id=session.employee.employee_id)
                    return ContextRun(None, discarded=True)
                result = validate_agent_output(narration.raw, bundle, ctx)
                validation = result.as_audit()
                status = "VALIDATED" if result.ok else "BLOCKED"

        validated = result is not None and result.ok
        summary: list[NarrativeSentence] = result.summary if validated else []
        hypotheses: list[Hypothesis] = result.hypotheses if validated else []
        questions = result.questions if validated and result.questions else bundle.default_questions
        versions = {
            "data_snapshot_version": self.app.snapshot_version,
            "feature_engine_version": FEATURE_ENGINE_VERSION,
            "prompt_version": PROMPT_VERSION if ai_enabled else "n/a",
            "model_version": model_version,
            "schema_version": CONTEXT_SCHEMA_VERSION,
        }
        context = CustomerContext(
            customer_id=ctx.active_customer_id, customer_ref=ctx.customer_ref, case_id=ctx.case_id,
            correlation_id=ctx.correlation_id, status=bundle.data_quality.overall, data_quality=bundle.data_quality,
            executive_summary=summary, narrative_status=status, narrative_message=MESSAGES.get(status),
            facts=bundle.facts, signals=bundle.signals, timeline=bundle.timeline, hypotheses=hypotheses,
            missing_information=bundle.missing_information, suggested_questions=questions,
            questions_origin="IA_VALIDADA" if validated and result.questions else "PADRAO_DETERMINISTICO",
            previous_interactions=bundle.interactions, limitations=bundle.limitations, evidence=bundle.evidence,
            versions=versions, decision=None)
        if not session.put(ctx.correlation_id, "context", context):
            return ContextRun(None, discarded=True)

        metrics = {"time_to_context_ms": int((time.perf_counter() - start) * 1000), "llm_ms": llm_ms,
                   "evidence_coverage": _evidence_coverage(context), "facts": len(context.facts),
                   "signals": len(context.signals), "narrative_status": status}
        used = sorted(set(result.evidence_ids_used if result else []) |
                      {e for f in context.facts for e in f.evidence_ids})
        context_version = self.app.audit.record_context_displayed(
            ctx, context_payload=_audit_payload(context), versions=versions, evidence_ids=used,
            validation=validation, metrics=metrics)
        session.put(ctx.correlation_id, "context_version", context_version)
        return ContextRun(context, False, context_version, validation, metrics, bundle)
