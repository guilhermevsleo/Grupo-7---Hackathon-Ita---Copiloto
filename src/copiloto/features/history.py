"""Renegociações anteriores e histórico de contatos: fatos registrados, sem motivos inventados."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ..settings import WINDOW_END, WINDOW_START
from .common import CaseData, Measurement, QualityStatus, Unit, fmt_date
from .quality import DataQualityResult

RENEG_STATUS_PT = {"ACTIVE": "ativo", "BROKEN": "rompido", "NOT_ACCEPTED": "não aceito", "SETTLED": "quitado"}
CHANNEL_PT = {"PHONE": "telefone", "APP": "app", "SMS": "SMS", "EMAIL": "e-mail", "WHATSAPP": "WhatsApp",
              "LETTER": "carta", "BRANCH": "agência"}
OUTCOME_PT = {"NO_ANSWER": "não atendeu", "ANSWERED": "atendeu", "MESSAGE_READ": "mensagem lida",
              "NO_RESPONSE": "sem resposta", "DELIVERED": "entregue"}


def analyze_previous_renegotiations(data: CaseData) -> list[Measurement]:
    """Histórico factual. Não recomenda repetir oferta e não infere motivo de rompimento."""
    ms = []
    counts = Counter(r["status"] for r in data.renegotiations)
    ms.append(Measurement(
        "renegotiation_count", "renegotiation_count", "Propostas de renegociação registradas",
        len(data.renegotiations), Unit.COUNT, WINDOW_START, WINDOW_END, "renegotiations",
        tuple(r["agreement_id"] for r in data.renegotiations),
        "contagem de registros; " + (", ".join(f"{RENEG_STATUS_PT.get(k, k)}: {v}" for k, v in counts.items()) or "nenhum"),
        "renegotiation_history",
        ("Somente registros desta base; nenhum registro não prova que nunca houve negociação.",
         "Motivos de rompimento não são registrados e não são inferidos.")))
    for r in data.renegotiations:
        ms.append(Measurement(
            f"renegotiation_{r['agreement_id']}", "renegotiation_status",
            f"Proposta de renegociação de {fmt_date(r.get('proposal_date'))}",
            RENEG_STATUS_PT.get(r["status"], r["status"]), Unit.STATUS, r.get("proposal_date"), r.get("proposal_date"),
            "renegotiations", (r["agreement_id"],), "status registrado em renegotiations", "renegotiation_history",
            ("Status registrado; motivo não consta na base.",)))
    return ms


@dataclass
class ContactSummary:
    status: QualityStatus
    measurements: list[Measurement]
    interactions: list[dict]  # para a tela; notas são UntrustedText


def summarize_contact_history(data: CaseData, quality: DataQualityResult) -> ContactSummary:
    mq = quality.metrics["contact_history"]
    interactions = [{"contact_id": c["contact_id"], "date": c["date"],
                     "channel": CHANNEL_PT.get(c.get("channel") or "", c.get("channel") or "não informado"),
                     "outcome": OUTCOME_PT.get(c.get("outcome") or "", c.get("outcome") or "não informado"),
                     "notes": c.get("notes")} for c in data.contacts]
    if mq.status == QualityStatus.INSUFFICIENT and not data.contacts:
        return ContactSummary(mq.status, [Measurement(
            "contacts_unavailable", "contact_count", "Contatos registrados", None, Unit.COUNT, None, None,
            "contacts + data_quality", (), "não calculado", "contact_history", (mq.reason,))], [])
    by_channel = Counter(i["channel"] for i in interactions)
    by_outcome = Counter(i["outcome"] for i in interactions)
    ms = [Measurement(
        "contact_count", "contact_count", "Contatos registrados", len(interactions), Unit.COUNT,
        min((c["date"] for c in data.contacts), default=None), max((c["date"] for c in data.contacts), default=None),
        "contacts", tuple(c["contact_id"] for c in data.contacts),
        "por canal: " + (", ".join(f"{k} {v}" for k, v in by_channel.items()) or "nenhum")
        + "; por resultado: " + (", ".join(f"{k} {v}" for k, v in by_outcome.items()) or "nenhum"),
        "contact_history", tuple(mq.limitations) + ("Histórico de canais é fato registrado, não recomendação de canal.",))]
    return ContactSummary(mq.status, ms, interactions)
