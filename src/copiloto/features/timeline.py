"""build_delinquency_timeline — eventos datados e factuais, cada um apontando para uma medição.

Distingue evento (data registrada) de posição atual (snapshot). Não inventa datas nem motivos."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .common import CaseData, Measurement, fmt_month
from .history import CHANNEL_PT, OUTCOME_PT, RENEG_STATUS_PT


@dataclass(frozen=True)
class TimelineDraft:
    date: date
    kind: str
    title: str
    measurement_keys: tuple[str, ...]
    precision: str = "day"  # "month" quando o evento é um mês de referência, não um dia


def build_delinquency_timeline(data: CaseData, measurements: dict[str, Measurement]) -> list[TimelineDraft]:
    events: list[TimelineDraft] = []

    def add(d, kind, title, *keys, precision="day"):
        keys = tuple(k for k in keys if k in measurements)
        if d and keys:
            events.append(TimelineDraft(d, kind, title, keys, precision))

    if "inflow_drop_start" in measurements:
        m = measurements["inflow_drop_start"].value
        add(m, "entradas", f"Entradas abaixo de 80% da média de mar–mai/2026 a partir de {fmt_month(m)}",
            "inflow_drop_start", "recurring_change", "inflow_change", precision="month")
    if "investment_redemptions" in measurements:
        for t in (t for t in data.transactions if t["transaction_id"] in measurements["investment_redemptions"].source_row_ids):
            add(t["date"], "liquidez", "Resgate de investimento creditado na conta", "investment_redemptions")
    if "first_late_installment" in measurements:
        add(measurements["first_late_installment"].value, "atraso", "Primeira parcela de empréstimo com atraso na janela",
            "first_late_installment")
    below = measurements.get("card_below_minimum")
    if below:
        months = sorted(s["reference_month"] for s in data.card_statements if s["statement_id"] in below.source_row_ids)
        if months:
            add(months[0], "atraso", f"Primeira fatura com pagamento abaixo do mínimo ({fmt_month(months[0])})",
                "card_below_minimum", precision="month")
    if "expense_isolated_peak" in measurements:
        m = measurements["expense_isolated_peak"].value
        add(m, "despesa", f"Despesa pontualmente elevada em {fmt_month(m)}", "expense_isolated_peak",
            precision="month")
    for r in data.renegotiations:
        add(r.get("proposal_date"), "renegociação",
            f"Proposta de renegociação registrada — status: {RENEG_STATUS_PT.get(r['status'], r['status'])}",
            f"renegotiation_{r['agreement_id']}")
    for c in data.contacts:
        add(c["date"], "contato",
            f"Contato por {CHANNEL_PT.get(c.get('channel') or '', c.get('channel') or 'canal não informado')} — "
            f"{OUTCOME_PT.get(c.get('outcome') or '', c.get('outcome') or 'resultado não informado')}",
            "contact_count")
    if "of_last_sync" in measurements and measurements["of_consent_status"].value == "EXPIRED":
        add(measurements["of_last_sync"].value, "visibilidade", "Última sincronização do Open Finance (consentimento expirado)",
            "of_last_sync")
    events.sort(key=lambda e: (e.date, e.kind))
    return events
