"""Schemas Pydantic do contexto (briefing §18, §21) e da saída do agente.

O campo de decisão existe só no CustomerContext e aceita apenas None: o agente nunca decide.
A saída do LLM (AgentOutput) proíbe campos extras — se o modelo tentar incluir "decision",
"offer" ou qualquer chave fora do contrato, a validação reprova a saída inteira.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

QualityLevel = Literal["SUFFICIENT", "PARTIAL", "INSUFFICIENT"]
CaseStatus = Literal["COMPLETE", "PARTIAL", "INSUFFICIENT_DATA"]
NarrativeStatus = Literal["VALIDATED", "BLOCKED", "FAILED", "DISABLED", "PENDING"]


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)
    evidence_id: str
    customer_id: str
    metric: str
    label: str
    value: Any
    value_display: str
    unit: str
    period_start: date | None
    period_end: date | None
    source: str
    source_row_ids: list[str]
    formula: str
    formula_version: str
    reference_date: date
    limitations: list[str]
    snapshot_version: str
    quality_metric: str
    quality_status: QualityLevel
    sensitive: bool = False
    detail: list[dict] = Field(default_factory=list)


class SourceQualityModel(BaseModel):
    source: str
    label: str
    declared_status: str | None
    status: QualityLevel
    reason: str
    coverage_note: str | None = None  # texto não confiável: só exibido como texto puro


class MetricQualityModel(BaseModel):
    metric: str
    label: str
    status: QualityLevel
    reason: str
    limitations: list[str] = Field(default_factory=list)


class DataQuality(BaseModel):
    overall: CaseStatus
    sources: list[SourceQualityModel]
    metrics: list[MetricQualityModel]
    open_finance_statement: str
    conflicts: list[str]
    limitations: list[str]
    requires_human_legal_privacy_validation: bool = True


class Fact(BaseModel):
    fact_id: str
    topic: str
    text: str
    evidence_ids: list[str] = Field(min_length=1)


class Signal(BaseModel):
    signal_id: str
    code: str
    title: str
    description: str
    method: str
    evidence_ids: list[str] = Field(min_length=1)


class Hypothesis(BaseModel):
    text: str
    evidence_ids: list[str] = Field(min_length=1)
    label: str = "HIPÓTESE — NÃO CONFIRMADA"


class TimelineEvent(BaseModel):
    date: date
    kind: str
    title: str
    evidence_ids: list[str] = Field(min_length=1)
    precision: Literal["day", "month"] = "day"


class InteractionSummary(BaseModel):
    contact_id: str
    date: date | None
    channel: str
    outcome: str
    notes: str | None = None  # texto não confiável: nunca vai ao LLM; exibido como texto puro


class MissingInformation(BaseModel):
    item: str
    reason: str
    metric: str | None = None


class NarrativeSentence(BaseModel):
    text: str
    evidence_ids: list[str] = Field(min_length=1)


class CustomerContext(BaseModel):
    customer_id: str
    customer_ref: str
    case_id: str
    correlation_id: str
    status: CaseStatus
    data_quality: DataQuality
    executive_summary: list[NarrativeSentence]
    narrative_status: NarrativeStatus
    narrative_message: str | None = None
    facts: list[Fact]
    signals: list[Signal]
    timeline: list[TimelineEvent]
    hypotheses: list[Hypothesis]
    missing_information: list[MissingInformation]
    suggested_questions: list[str]
    questions_origin: Literal["IA_VALIDADA", "PADRAO_DETERMINISTICO"]
    previous_interactions: list[InteractionSummary]
    limitations: list[str]
    evidence: dict[str, Evidence]
    versions: dict[str, str]
    decision: None = None


# ---------------------------------------------------------------------- contrato do LLM
class DraftSentence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=400)
    evidence_ids: list[str] = Field(min_length=1, max_length=6)


class AgentOutput(BaseModel):
    """Única forma aceita da resposta do Gemini. Sem campo de decisão, oferta ou canal."""
    model_config = ConfigDict(extra="forbid")
    case_ref: str
    executive_summary: list[DraftSentence] = Field(min_length=1, max_length=5)
    hypotheses: list[DraftSentence] = Field(default_factory=list, max_length=3)
    suggested_questions: list[str] = Field(default_factory=list, max_length=5)
