"""Crédito: utilização, comprometimento com parcelas, conciliação do cartão e histórico de atrasos.

Indicadores observados; nenhum deles avalia capacidade de contratar ou de pagar no futuro.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from ..money import avg_cents, fmt_brl, ratio_pct
from ..settings import RECENT_WINDOW, REFERENCE_DATE, WINDOW_END, WINDOW_START
from .common import (RECENT_MONTHS, CaseData, Measurement, QualityStatus, TxClass, Unit, fmt_month, ids)
from .quality import DataQualityResult

I = QualityStatus.INSUFFICIENT


def calculate_credit_utilization(data: CaseData, quality: DataQualityResult) -> list[Measurement]:
    mq = quality.metrics["credit_utilization"]
    if mq.status == I:
        return [Measurement("credit_utilization_unavailable", "card_utilization_current", "Utilização do limite do cartão",
                            None, Unit.PCT, None, None, "credit_cards", ids(data.credit_cards),
                            "não calculado", "credit_utilization", (mq.reason,))]
    out = []
    for card in data.credit_cards:
        limit, balance = card.get("credit_limit") or 0, card.get("current_balance")
        if limit <= 0 or balance is None:
            continue
        out.append(Measurement(
            f"card_utilization_{card['card_id']}", "card_utilization_current", "Utilização do limite do cartão (saldo atual)",
            ratio_pct(balance, limit), Unit.PCT, None, REFERENCE_DATE, "credit_cards", (card["card_id"],),
            f"100 × saldo atual ({fmt_brl(balance)}) ÷ limite ({fmt_brl(limit)})", "credit_utilization",
            tuple(mq.limitations)))
    return out


def calculate_debt_service_ratio(data: CaseData, quality: DataQualityResult) -> Measurement:
    mq = quality.metrics["debt_service_ratio"]
    due_recent = [i for i in data.installments if i["due_date"] and RECENT_WINDOW[0] <= i["due_date"] <= RECENT_WINDOW[1]]
    inflows = [t for t in data.transactions if data.tx_class(t) == TxClass.EXTERNAL_INFLOW
               and RECENT_WINDOW[0] <= t["date"] <= RECENT_WINDOW[1]]
    formula = ("100 × média mensal das parcelas de empréstimo com vencimento em jun–ago/2026 ÷ média mensal "
               "das entradas externas observadas em jun–ago/2026")
    if mq.status == I:
        return Measurement("debt_service_unavailable", "debt_service_ratio", "Comprometimento das entradas com parcelas",
                           None, Unit.PCT, *RECENT_WINDOW, "installments + transactions", ids(due_recent),
                           formula, "debt_service_ratio", (mq.reason,))
    numerator = avg_cents(sum(i["amount_due"] or 0 for i in due_recent), len(RECENT_MONTHS))
    denominator = avg_cents(sum(t["amount"] for t in inflows), len(RECENT_MONTHS))
    value = ratio_pct(numerator, denominator)
    lims = tuple(mq.limitations) + ((f"Parcelas: {fmt_brl(numerator)}/mês; entradas: {fmt_brl(denominator)}/mês.",))
    if value is None:
        lims += ("Denominador zero: indicador indisponível.",)
    return Measurement("debt_service_ratio", "debt_service_ratio", "Comprometimento das entradas observadas com parcelas",
                       value, Unit.PCT, *RECENT_WINDOW, "installments + transactions", ids(due_recent) + ids(inflows),
                       formula, "debt_service_ratio", lims)


def reconcile_card_transactions(data: CaseData) -> list[Measurement]:
    """Concilia compras x fatura x pagamento por cartão e mês, sem somar três vezes a mesma despesa.
    O agrupamento por mês é uma convenção observada na base, não prova do ciclo de fechamento."""
    if not data.credit_cards:
        return []
    purchases = defaultdict(int)
    for t in data.card_transactions:
        purchases[(t["card_id"], t["date"].replace(day=1))] += t["amount"]
    payments = defaultdict(int)
    for t in data.transactions:
        if data.tx_class(t) == TxClass.CARD_BILL_PAYMENT:
            payments[(t.get("counterparty_id"), t["date"].replace(day=1))] += t["amount"]
    rows, residual_months, payment_mismatch = [], 0, 0
    for st in data.card_statements:
        key = (st["card_id"], st["reference_month"])
        residual = st["statement_amount"] - purchases.get(key, 0)
        paid_obs = payments.get(key, 0)
        paid_declared = st["paid_amount"] or 0
        residual_months += residual != 0
        payment_mismatch += paid_obs != paid_declared
        rows.append({"mes": fmt_month(st["reference_month"]), "compras": purchases.get(key, 0),
                     "fatura": st["statement_amount"], "residuo": residual,
                     "pago_na_conta": paid_obs, "pago_na_fatura": paid_declared,
                     "minimo": st.get("minimum_payment"), "dias_atraso": st.get("days_late")})
    return [Measurement(
        "card_reconciliation", "card_reconciliation", "Conciliação cartão: compras × fatura × pagamento", None,
        Unit.TABLE, WINDOW_START, WINDOW_END, "card_transactions + card_statements + transactions",
        ids(data.card_statements),
        "por cartão e mês: resíduo = fatura − soma das compras; pagamento observado na conta × pago na fatura",
        "expense_shift",
        (f"{residual_months} mês(es) com resíduo entre compras e fatura; {payment_mismatch} mês(es) com "
         "diferença entre pagamento observado e registrado.",
         "Despesa econômica conta as compras; o pagamento da fatura entra só no fluxo de caixa.",
         "Não há vínculo explícito compra–fatura; o agrupamento por mês é uma convenção da base."),
        detail=tuple(rows))]


@dataclass
class CreditHistoryResult:
    first_late_installment: date | None
    first_card_below_minimum: date | None
    measurements: list[Measurement]


def analyze_credit_history(data: CaseData, quality: DataQualityResult) -> CreditHistoryResult:
    mq = quality.metrics["credit_history"]
    lims = tuple(mq.limitations)
    ms: list[Measurement] = []
    overdue = [i for i in data.installments if not i["paid_date"] and i["due_date"] and i["due_date"] < REFERENCE_DATE]
    paid_late = [i for i in data.installments if i["paid_date"] and (i.get("days_late") or 0) > 0]
    late_all = sorted(overdue + paid_late, key=lambda i: i["due_date"])
    first_late = late_all[0]["due_date"] if late_all else None

    for loan in data.loans:
        ms.append(Measurement(
            f"loan_{loan['contract_id']}", "loan_outstanding_balance",
            f"Saldo devedor do contrato ({(loan.get('product') or 'empréstimo').replace('_', ' ').lower()})",
            loan.get("outstanding_balance"), Unit.BRL, None, REFERENCE_DATE, "loans", (loan["contract_id"],),
            "valor registrado em loans", "credit_history", lims))
    if data.installments:
        ms.append(Measurement(
            "installments_overdue", "installments_overdue_count", "Parcelas vencidas e não pagas", len(overdue),
            Unit.COUNT, WINDOW_START, REFERENCE_DATE, "installments", ids(overdue),
            "parcelas com vencimento anterior a 01/09/2026 e sem data de pagamento", "credit_history",
            lims + ("Parcela ausente da base não equivale a parcela não paga.",)))
        if overdue:
            ms.append(Measurement(
                "installments_overdue_amount", "installments_overdue_amount", "Valor das parcelas vencidas e não pagas",
                sum(i["amount_due"] or 0 for i in overdue), Unit.BRL, WINDOW_START, REFERENCE_DATE, "installments",
                ids(overdue), "soma do valor devido das parcelas vencidas sem pagamento", "credit_history", lims))
        ms.append(Measurement(
            "installments_paid_late", "installments_paid_late_count", "Parcelas pagas com atraso", len(paid_late),
            Unit.COUNT, WINDOW_START, REFERENCE_DATE, "installments", ids(paid_late),
            "parcelas pagas com dias de atraso > 0", "credit_history", lims))
    if first_late:
        ms.append(Measurement(
            "first_late_installment", "first_late_installment_due", "Primeira parcela com atraso na janela",
            first_late, Unit.DATE, first_late, first_late, "installments", ids(late_all[:1]),
            "menor vencimento entre parcelas pagas com atraso ou vencidas sem pagamento", "credit_history", lims))

    below_min = [s for s in data.card_statements
                 if s.get("minimum_payment") is not None and (s["paid_amount"] or 0) < s["minimum_payment"]]
    partial = [s for s in data.card_statements
               if s.get("minimum_payment") is not None and s["minimum_payment"] <= (s["paid_amount"] or 0) < s["statement_amount"]]
    first_card = min((s["reference_month"] for s in below_min), default=None)
    if data.card_statements:
        last3 = sorted(data.card_statements, key=lambda s: s["reference_month"])[-3:]
        not_full = [s for s in last3 if (s["paid_amount"] or 0) < s["statement_amount"]]
        ms.append(Measurement(
            "card_not_full_last3", "card_statements_not_paid_in_full_last3",
            "Faturas não pagas integralmente (últimas 3)", len(not_full), Unit.COUNT,
            last3[0]["reference_month"], last3[-1]["reference_month"], "card_statements", ids(not_full),
            "faturas de jun–ago/2026 com valor pago < valor da fatura", "credit_history", lims))
        if below_min:
            ms.append(Measurement(
                "card_below_minimum", "card_statements_below_minimum", "Faturas com pagamento abaixo do mínimo",
                len(below_min), Unit.COUNT, WINDOW_START, WINDOW_END, "card_statements", ids(below_min),
                "faturas com valor pago < pagamento mínimo", "credit_history", lims))
        if partial:
            ms.append(Measurement(
                "card_partial", "card_statements_partial", "Faturas pagas parcialmente (entre o mínimo e o total)",
                len(partial), Unit.COUNT, WINDOW_START, WINDOW_END, "card_statements", ids(partial),
                "faturas com mínimo ≤ valor pago < valor da fatura", "credit_history", lims))
    for card in data.credit_cards:
        if card.get("days_past_due"):
            ms.append(Measurement(
                f"card_dpd_{card['card_id']}", "card_days_past_due", "Dias em atraso no cartão (posição atual)",
                card["days_past_due"], Unit.COUNT, None, REFERENCE_DATE, "credit_cards", (card["card_id"],),
                "valor registrado em credit_cards", "credit_history", lims))
    return CreditHistoryResult(first_late, first_card, ms)
