"""check_data_quality — qualidade POR FONTE e POR MÉTRICA, avaliada ANTES da narrativa (briefing §12).

Sem score global. Regra central (DECISIONS.md D-04): uma comparação entre janelas só é válida
se a visibilidade de cada conta relevante for constante nas duas janelas. Visibilidade que muda
(ex.: Open Finance expirado no meio) torna a comparação INSUFFICIENT: a mudança observada
misturaria perda de visibilidade com mudança real.

Comportamentos do MVP sobre status Open Finance representam regras analíticas da base sintética,
não política jurídica ou operacional do Itaú.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..settings import WINDOW_END, WINDOW_START
from .common import (PRIOR_MONTHS, RECENT_MONTHS, WINDOW_MONTHS, CaseData, Measurement, QualityStatus,
                     TxClass, Unit, fmt_date, fmt_month, month_end, worst)

S, P, I = QualityStatus.SUFFICIENT, QualityStatus.PARTIAL, QualityStatus.INSUFFICIENT

_DECLARED = {"COMPLETE": S, "PARTIAL": P, "STALE": P, "MISSING": I}
SOURCE_LABELS = {
    "PRIMARY_ACCOUNT": "Conta principal",
    "EXTERNAL_ACCOUNTS": "Contas externas (Open Finance)",
    "CARDS": "Cartões",
    "CREDIT_HISTORY": "Histórico de crédito",
    "CONTACT_HISTORY": "Histórico de contatos",
}
METRIC_LABELS = {
    "income_shift": "Variação de entradas",
    "expense_shift": "Variação de despesas",
    "credit_utilization": "Utilização de crédito",
    "debt_service_ratio": "Comprometimento com parcelas",
    "credit_history": "Histórico de crédito",
    "contact_history": "Histórico de contatos",
    "renegotiation_history": "Renegociações anteriores",
}
OF_VISIBLE_STATUSES = {"AUTHORISED", "AUTHORISED_PARTIAL", "EXPIRED"}


@dataclass
class SourceQuality:
    source: str
    label: str
    declared_status: str | None
    status: QualityStatus
    reason: str
    coverage_note: object | None = None  # UntrustedText: só exibido na tela, nunca ao LLM


@dataclass
class MetricQuality:
    metric: str
    label: str
    status: QualityStatus
    reason: str
    limitations: list[str] = field(default_factory=list)


@dataclass
class DataQualityResult:
    sources: list[SourceQuality]
    metrics: dict[str, MetricQuality]
    overall: str
    visibility: dict[str, dict[date, bool]]
    open_finance_statement: str
    conflicts: list[str]
    limitations: list[str]
    measurements: list[Measurement]

    def status(self, metric: str) -> QualityStatus:
        return self.metrics[metric].status


# ---------------------------------------------------------------------- visibilidade
def _of_visibility_window(data: CaseData) -> tuple[date | None, date | None, str]:
    consent = data.consent()
    if consent is None:
        return None, None, "sem registro de consentimento Open Finance"
    status = (consent.get("status") or "").upper()
    scope = {s.strip().upper() for s in (consent.get("scope") or "").split(",") if s.strip()}
    if status not in OF_VISIBLE_STATUSES:
        return None, None, f"consentimento Open Finance {status or 'ausente'}"
    if "TRANSACTIONS" not in scope:
        return None, None, "escopo do consentimento não inclui transações"
    until = consent.get("last_sync_date") or consent.get("expiration_date")
    return WINDOW_START, until, status


def compute_visibility(data: CaseData) -> dict[str, dict[date, bool]]:
    of_from, of_until, _ = _of_visibility_window(data)
    primary = data.primary_account()
    primary_q = data.quality_row("PRIMARY_ACCOUNT")
    primary_declared = (primary_q or {}).get("status", "COMPLETE")
    months_with_tx: dict[str, set[date]] = {}
    for t in data.transactions:
        months_with_tx.setdefault(t["account_id"], set()).add(t["date"].replace(day=1))

    vis: dict[str, dict[date, bool]] = {}
    for acc in data.accounts:
        acc_id = acc["account_id"]
        if data.is_open_finance(acc):
            start = acc.get("coverage_start") or of_from
            vis[acc_id] = {
                m: bool(of_from and of_until and start and start <= m and of_until >= month_end(m))
                for m in WINDOW_MONTHS
            }
        elif primary and acc_id == primary["account_id"] and primary_declared != "COMPLETE":
            if primary_declared == "MISSING":
                vis[acc_id] = {m: False for m in WINDOW_MONTHS}
            else:  # PARTIAL/STALE: mês sem nenhum lançamento é tratado como "sem observação", não zero
                observed = months_with_tx.get(acc_id, set())
                vis[acc_id] = {m: m in observed for m in WINDOW_MONTHS}
        else:
            vis[acc_id] = {m: True for m in WINDOW_MONTHS}
    return vis


def _account_label(data: CaseData, acc_id: str) -> str:
    acc = data.account(acc_id) or {}
    if data.is_open_finance(acc):
        return "conta externa via Open Finance"
    primary = data.primary_account()
    if primary and primary["account_id"] == acc_id:
        return "conta principal"
    return "conta do Itaú"


def _comparison_status(data: CaseData, vis, account_ids: set[str]) -> tuple[QualityStatus, list[str]]:
    """Visibilidade constante nas 6 meses (mar–ago/2026) => comparável."""
    status, reasons = S, []
    of_from, of_until, _ = _of_visibility_window(data)
    for acc_id in sorted(account_ids):
        months = PRIOR_MONTHS + RECENT_MONTHS
        flags = [vis.get(acc_id, {}).get(m, False) for m in months]
        if all(flags):
            continue
        acc = data.account(acc_id) or {}
        if not any(flags):
            status = worst(status, P)
            reasons.append(f"{_account_label(data, acc_id)} sem visibilidade em mar–ago/2026")
            continue
        status = worst(status, I)
        if data.is_open_finance(acc) and of_until:
            reasons.append(f"Open Finance sem visibilidade após {of_until.isoformat()}")
        else:
            missing = [fmt_month(m) for m, f in zip(months, flags) if not f]
            reasons.append(f"{_account_label(data, acc_id)} sem observação em {', '.join(missing)}")
    return status, reasons


# ---------------------------------------------------------------------- principal
def check_data_quality(data: CaseData) -> DataQualityResult:
    vis = compute_visibility(data)
    conflicts: list[str] = []
    limitations: list[str] = [
        "Retrato histórico sintético com referência em 01/09/2026; não descreve a situação atual.",
        "Entradas observadas limitam-se às contas visíveis e não representam a renda total do cliente.",
    ]

    # ---- fontes declaradas
    sources: list[SourceQuality] = []
    for logical, label in SOURCE_LABELS.items():
        row = data.quality_row(logical)
        if row is None:
            sources.append(SourceQuality(logical, label, None, I, "sem registro de qualidade para a fonte"))
            continue
        declared = (row.get("status") or "").upper()
        status = _DECLARED.get(declared, I)
        reason = {"COMPLETE": "cobertura declarada completa", "PARTIAL": "cobertura declarada parcial",
                  "STALE": "fonte desatualizada", "MISSING": "fonte ausente"}.get(declared, "status desconhecido")
        sources.append(SourceQuality(logical, label, declared, status, reason, row.get("coverage_note")))

    # ---- Open Finance (§11)
    consent = data.consent()
    c_status = (consent or {}).get("status") or "SEM_REGISTRO"
    scope = (consent or {}).get("scope") or ""
    last_sync = (consent or {}).get("last_sync_date")
    if c_status == "AUTHORISED":
        of_statement = f"Open Finance autorizado; usado somente no escopo disponível ({scope})."
    elif c_status == "AUTHORISED_PARTIAL":
        of_statement = f"Open Finance com autorização parcial; cobertura parcial declarada (escopo: {scope})."
    elif c_status == "EXPIRED":
        of_statement = (f"Open Finance expirado; última sincronização em {fmt_date(last_sync)}. "
                        "Ausência de dados após essa data não significa ausência de renda.")
    elif c_status == "REJECTED":
        of_statement = "Open Finance recusado; não utilizado como fonte atual do contexto."
    else:
        of_statement = "Sem registro de consentimento Open Finance; contas externas não são visíveis."
    summary_status = (data.profile.get("open_finance_status") or "").upper()
    if summary_status and consent and summary_status != c_status.upper():
        conflicts.append(f"Status resumido do cadastro ({summary_status}) difere do consentimento "
                         f"({c_status}); prevaleceu o registro de consentimento.")

    last_tx: dict[str, date] = {}
    for t in data.transactions:
        last_tx[t["account_id"]] = max(last_tx.get(t["account_id"], t["date"]), t["date"])
    for acc in data.accounts:
        end = acc.get("coverage_end")
        observed = last_tx.get(acc["account_id"])
        if end and observed and observed > end:
            conflicts.append(f"Metadado de cobertura da {_account_label(data, acc['account_id'])} termina em "
                             f"{fmt_date(end)}, mas há lançamentos até {fmt_date(observed)}; o metadado não foi "
                             "usado como limite literal.")

    # ---- métricas
    metrics: dict[str, MetricQuality] = {}
    primary = data.primary_account()
    inflow_accounts = {t["account_id"] for t in data.transactions if data.tx_class(t) == TxClass.EXTERNAL_INFLOW}
    of_accounts = {a["account_id"] for a in data.accounts if data.is_open_finance(a)}
    base_accounts = inflow_accounts | of_accounts | ({primary["account_id"]} if primary else set())

    income_status, income_reasons = _comparison_status(data, vis, base_accounts)
    income_lims = []
    ext_q = data.quality_row("EXTERNAL_ACCOUNTS")
    if c_status in ("REJECTED", "SEM_REGISTRO") or (ext_q and ext_q.get("status") == "MISSING"):
        income_status = worst(income_status, P)
        income_lims.append("Sem Open Finance: comparação limitada às contas do Itaú.")
    pq = data.quality_row("PRIMARY_ACCOUNT")
    if pq and pq.get("status") != "COMPLETE":
        income_status = worst(income_status, P)
        income_lims.append("Qualidade da conta principal não é completa; créditos rotulados como salário "
                           "não são tratados como renda comprovada.")
    metrics["income_shift"] = MetricQuality("income_shift", METRIC_LABELS["income_shift"], income_status,
                                            "; ".join(income_reasons) or "visibilidade constante nas duas janelas",
                                            income_lims)

    expense_accounts = {t["account_id"] for t in data.transactions
                        if data.tx_class(t) in (TxClass.ECONOMIC_EXPENSE, TxClass.CASH_WITHDRAWAL)}
    exp_status, exp_reasons = _comparison_status(data, vis, expense_accounts | base_accounts)
    exp_lims = ["Despesa econômica = compras no cartão + débitos de consumo; pagamento de fatura, parcelas, "
                "saques e transferências próprias ficam fora."]
    cards_q = data.quality_row("CARDS")
    if data.credit_cards and cards_q and cards_q.get("status") != "COMPLETE":
        exp_status = worst(exp_status, P)
        exp_lims.append("Detalhamento de compras no cartão incompleto.")
    if not data.credit_cards:
        exp_lims.append("Cliente sem cartão de crédito na base.")
    metrics["expense_shift"] = MetricQuality("expense_shift", METRIC_LABELS["expense_shift"], exp_status,
                                             "; ".join(exp_reasons) or "visibilidade constante nas duas janelas",
                                             exp_lims)

    valid_cards = [c for c in data.credit_cards if (c.get("credit_limit") or 0) > 0]
    if not data.credit_cards:
        metrics["credit_utilization"] = MetricQuality("credit_utilization", METRIC_LABELS["credit_utilization"],
                                                      I, "sem cartão de crédito na base")
    elif not valid_cards:
        metrics["credit_utilization"] = MetricQuality("credit_utilization", METRIC_LABELS["credit_utilization"],
                                                      I, "limite de crédito ausente ou inválido")
    else:
        metrics["credit_utilization"] = MetricQuality(
            "credit_utilization", METRIC_LABELS["credit_utilization"],
            S if not cards_q or cards_q.get("status") == "COMPLETE" else P, "limite válido",
            ["Considera somente cartões do Itaú; limites em outras instituições não são visíveis."])

    # histórico de crédito
    ch = data.quality_row("CREDIT_HISTORY")
    ch_status = _DECLARED.get((ch or {}).get("status", "MISSING"), I)
    ch_reasons = [] if ch_status == S else [f"fonte declarada {(ch or {}).get('status', 'ausente')}"]
    recorded = {(i["contract_id"], i["due_date"].replace(day=1)) for i in data.installments if i["due_date"]}
    unmatched = [t for t in data.transactions if data.tx_class(t) == TxClass.LOAN_PAYMENT
                 and (t.get("counterparty_id"), t["date"].replace(day=1)) not in recorded]
    ch_lims = ["Obrigações em outras instituições não são visíveis nesta base."]
    if unmatched:
        ch_status = worst(ch_status, P)
        ch_lims.append(f"{len(unmatched)} pagamento(s) de empréstimo sem parcela correspondente registrada; "
                       "vencimento e atraso dessas parcelas não podem ser reconstruídos.")
    if c_status == "AUTHORISED_PARTIAL":
        ch_lims.append("Consentimento Open Finance parcial: cartões e empréstimos externos fora do escopo.")
    metrics["credit_history"] = MetricQuality("credit_history", METRIC_LABELS["credit_history"], ch_status,
                                              "; ".join(ch_reasons) or "fonte declarada completa", ch_lims)

    # comprometimento com parcelas
    recent_ok = all(vis.get(a, {}).get(m, False) for a in inflow_accounts for m in RECENT_MONTHS)
    if not data.loans:
        dsr = MetricQuality("debt_service_ratio", METRIC_LABELS["debt_service_ratio"], I,
                            "sem contratos de empréstimo na base; dívidas externas não são visíveis")
    elif not inflow_accounts or not recent_ok:
        dsr = MetricQuality("debt_service_ratio", METRIC_LABELS["debt_service_ratio"], I,
                            "entradas do período recente sem visibilidade completa; denominador indisponível")
    else:
        dsr = MetricQuality("debt_service_ratio", METRIC_LABELS["debt_service_ratio"],
                            worst(S, ch_status, income_status if income_status != I else S),
                            "parcelas do banco e entradas observadas no mesmo período",
                            ["Não inclui cartão nem dívidas externas; não avalia capacidade de pagamento."])
    metrics["debt_service_ratio"] = dsr

    cq = data.quality_row("CONTACT_HISTORY")
    cq_status = _DECLARED.get((cq or {}).get("status", "MISSING"), I)
    metrics["contact_history"] = MetricQuality(
        "contact_history", METRIC_LABELS["contact_history"], cq_status,
        "fonte declarada completa" if cq_status == S else
        f"fonte declarada {(cq or {}).get('status', 'ausente')}; ausência de registro não significa ausência de contato",
        ["Notas de contato são relato registrado no CRM, não comprovação de causa."])
    metrics["renegotiation_history"] = MetricQuality(
        "renegotiation_history", METRIC_LABELS["renegotiation_history"], S, "registros internos",
        ["Somente acordos registrados na base; motivos de rompimento não são registrados."])

    # ---- status do caso (sem score global)
    inc, cred = metrics["income_shift"].status, metrics["credit_history"].status
    if inc == S and cred == S:
        overall = "COMPLETE"
    elif inc == I and cred != S:
        overall = "INSUFFICIENT_DATA"
    else:
        overall = "PARTIAL"

    measurements = [
        Measurement("of_consent_status", "open_finance_consent_status", "Status do consentimento Open Finance",
                    c_status, Unit.STATUS, None, None, "consents", tuple(c["consent_id"] for c in data.consents),
                    "valor registrado em consents.status", "income_shift"),
    ]
    if last_sync:
        measurements.append(Measurement(
            "of_last_sync", "open_finance_last_sync", "Última sincronização Open Finance", last_sync, Unit.DATE,
            None, None, "consents", tuple(c["consent_id"] for c in data.consents),
            "valor registrado em consents.last_sync_date", "income_shift"))

    return DataQualityResult(sources, metrics, overall, vis, of_statement, conflicts, limitations, measurements)
