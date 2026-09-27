"""Evidence Engine (P2): transforma medições em evidências reproduzíveis e monta, de forma
DETERMINÍSTICA, fatos, sinais, linha do tempo, informações ausentes, limitações e perguntas padrão.

Toda afirmação factual exibida aponta para evidências do cliente ativo e pode ser reproduzida
sem perguntar ao LLM como foi calculada (briefing §17–§18).
"""
from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .auth import ActiveCaseContext
from .features.common import MONTH_NAMES, Measurement, QualityStatus, Unit, fmt_date, fmt_month, fmt_period
from .features.engine import FeatureResult
from .money import fmt_brl, fmt_pct
from .schemas import (DataQuality, Evidence, Fact, InteractionSummary, MetricQualityModel, MissingInformation,
                      Signal, SourceQualityModel, TimelineEvent)
from .settings import (FEATURE_ENGINE_VERSION, OPEN_FINANCE_NOTICE, PRIOR_WINDOW, RECENT_WINDOW, REFERENCE_DATE)

I = QualityStatus.INSUFFICIENT


# ---------------------------------------------------------------------- registro global de evidências
class EvidenceRegistry:
    """Guarda a qual cliente pertence cada evidence_id emitido neste processo, para que o validador
    distinga 'evidência inexistente' de 'evidência de outro cliente'."""

    def __init__(self):
        self._owner: dict[str, str] = {}
        self._lock = threading.Lock()

    def register(self, evidence_id: str, customer_id: str) -> None:
        with self._lock:
            self._owner[evidence_id] = customer_id

    def owner(self, evidence_id: str) -> str | None:
        return self._owner.get(evidence_id)


REGISTRY = EvidenceRegistry()


def display_value(m: Measurement) -> str:
    if m.value is None:
        return "indisponível"
    if m.unit == Unit.BRL:
        return fmt_brl(m.value)
    if m.unit == Unit.PCT:
        return fmt_pct(m.value, signed="change" in m.metric)
    if m.unit == Unit.DATE:
        return fmt_date(m.value)
    if m.unit == Unit.MONTH:
        return fmt_month(m.value)
    if m.unit == Unit.TABLE:
        return "tabela"
    return str(m.value)


@dataclass
class EvidenceBundle:
    ctx: ActiveCaseContext
    snapshot_version: str
    evidence: dict[str, Evidence]
    by_key: dict[str, str]  # chave da medição -> evidence_id
    data_quality: DataQuality
    facts: list[Fact]
    signals: list[Signal]
    timeline: list[TimelineEvent]
    missing_information: list[MissingInformation]
    limitations: list[str]
    default_questions: list[str]
    interactions: list[InteractionSummary]
    features: FeatureResult = field(repr=False)

    @property
    def customer_id(self) -> str:
        return self.ctx.active_customer_id

    def eid(self, key: str) -> str | None:
        return self.by_key.get(key)

    def ev(self, key: str) -> Evidence | None:
        eid = self.by_key.get(key)
        return self.evidence.get(eid) if eid else None


def _evidence_id(ctx: ActiveCaseContext, seq: int, key: str) -> str:
    suffix = hashlib.sha256(f"{ctx.correlation_id}:{key}".encode()).hexdigest()[:4].upper()
    return f"E{seq:02d}-{suffix}"


def build_evidence_bundle(ctx: ActiveCaseContext, fr: FeatureResult, snapshot_version: str) -> EvidenceBundle:
    if fr.data.customer_id != ctx.active_customer_id:
        raise ValueError("Features calculadas para um cliente diferente do caso ativo.")
    q = fr.quality
    evidence: dict[str, Evidence] = {}
    by_key: dict[str, str] = {}
    for seq, (key, m) in enumerate(fr.measurements.items(), start=1):
        eid = _evidence_id(ctx, seq, key)
        by_key[key] = eid
        evidence[eid] = Evidence(
            evidence_id=eid, customer_id=ctx.active_customer_id, metric=m.metric, label=m.label, value=m.value,
            value_display=display_value(m), unit=m.unit.value, period_start=m.period_start,
            period_end=m.period_end, source=m.source, source_row_ids=list(m.source_row_ids), formula=m.formula,
            formula_version=m.formula_version, reference_date=REFERENCE_DATE, limitations=list(m.limitations),
            snapshot_version=snapshot_version, quality_metric=m.quality_metric,
            quality_status=q.metrics[m.quality_metric].status.value if m.quality_metric in q.metrics else "SUFFICIENT",
            sensitive=m.sensitive, detail=list(m.detail))
        REGISTRY.register(eid, ctx.active_customer_id)

    dq = DataQuality(
        overall=q.overall,
        sources=[SourceQualityModel(source=s.source, label=s.label, declared_status=s.declared_status,
                                    status=s.status.value, reason=s.reason,
                                    coverage_note=str(s.coverage_note) if s.coverage_note else None)
                 for s in q.sources],
        metrics=[MetricQualityModel(metric=mq.metric, label=mq.label, status=mq.status.value, reason=mq.reason,
                                    limitations=list(mq.limitations)) for mq in q.metrics.values()],
        open_finance_statement=q.open_finance_statement, conflicts=list(q.conflicts),
        limitations=list(q.limitations))

    bundle = EvidenceBundle(ctx=ctx, snapshot_version=snapshot_version, evidence=evidence, by_key=by_key,
                            data_quality=dq, facts=[], signals=[], timeline=[], missing_information=[],
                            limitations=[], default_questions=[], interactions=[], features=fr)
    bundle.facts = _facts(bundle)
    bundle.signals = _signals(bundle)
    bundle.timeline = [TimelineEvent(date=e.date, kind=e.kind, title=e.title, precision=e.precision,
                                     evidence_ids=[by_key[k] for k in e.measurement_keys])
                       for e in fr.timeline]
    bundle.missing_information = _missing(bundle)
    bundle.limitations = _limitations(bundle)
    bundle.default_questions = _default_questions(bundle)
    bundle.interactions = [InteractionSummary(contact_id=i["contact_id"], date=i["date"], channel=i["channel"],
                                              outcome=i["outcome"], notes=str(i["notes"]) if i["notes"] else None)
                           for i in fr.contacts.interactions]
    return bundle


# ---------------------------------------------------------------------- fatos
def _facts(b: EvidenceBundle) -> list[Fact]:
    facts: list[Fact] = []

    def v(key):
        e = b.ev(key)
        return e.value_display if e else None

    def add(topic, text, *keys):
        ids = [b.eid(k) for k in keys if b.eid(k)]
        if ids:
            facts.append(Fact(fact_id=f"F{len(facts) + 1:02d}", topic=topic, text=text, evidence_ids=ids))

    prior, recent = fmt_period(*PRIOR_WINDOW), fmt_period(*RECENT_WINDOW)
    if b.ev("inflow_change"):
        add("Entradas", f"Entradas externas observadas: média de {v('inflow_prior')}/mês em {prior} e "
                        f"{v('inflow_recent')}/mês em {recent} (variação de {v('inflow_change')}).",
            "inflow_prior", "inflow_recent", "inflow_change")
    if b.ev("recurring_change"):
        add("Entradas", f"Entradas recorrentes identificáveis: {v('recurring_prior')}/mês em {prior} e "
                        f"{v('recurring_recent')}/mês em {recent} (variação de {v('recurring_change')}).",
            "recurring_prior", "recurring_recent", "recurring_change")
    if b.ev("third_party_pix"):
        add("Entradas", f"Entradas de pessoas físicas (Pix de terceiros) somaram {v('third_party_pix')} em 12 meses; "
                        "não são tratadas como renda recorrente.", "third_party_pix")
    if b.ev("investment_redemptions"):
        add("Entradas", f"Resgates de investimento somaram {v('investment_redemptions')}; são movimentação "
                        "patrimonial, não renda.", "investment_redemptions")
    if b.ev("declared_income"):
        add("Entradas", f"Renda declarada no cadastro: {v('declared_income')} (sem data de atualização; "
                        "não tratada como renda atual).", "declared_income")
    if b.ev("own_transfer_pairs"):
        extra = f"; {v('own_transfer_unmatched')} sem contrapartida observada" if b.ev("own_transfer_unmatched") else ""
        add("Transferências", f"{v('own_transfer_pairs')} par(es) de transferência entre contas próprias foram "
                              f"excluídos de entradas e despesas{extra}.", "own_transfer_pairs", "own_transfer_unmatched")
    if b.ev("expense_change"):
        add("Despesas", f"Despesa econômica observada (compras no cartão + débitos de consumo): {v('expense_prior')}/mês "
                        f"em {prior} e {v('expense_recent')}/mês em {recent} (variação de {v('expense_change')}).",
            "expense_prior", "expense_recent", "expense_change")
    if b.ev("expense_isolated_peak"):
        add("Despesas", f"Despesa pontualmente elevada em {v('expense_isolated_peak')}; os outros meses de {recent} "
                        "ficaram próximos da média anterior.", "expense_isolated_peak")
    for key, m in b.features.measurements.items():
        if m.metric == "expense_category_change_3m":
            tail = " Mudança financeira observada; não indica condição pessoal." if m.sensitive else ""
            add("Despesas", f"{m.label}: variação de {v(key)} entre {prior} e {recent}.{tail}", key)
    if b.ev("cash_withdrawals"):
        add("Despesas", f"Saques em dinheiro somaram {v('cash_withdrawals')} em 12 meses (destino não identificado).",
            "cash_withdrawals")
    for key, m in b.features.measurements.items():
        if m.metric == "card_utilization_current" and m.value is not None:
            add("Crédito", f"Utilização do limite do cartão: {v(key)} (saldo atual ÷ limite).", key)
    if b.ev("debt_service_ratio") and b.ev("debt_service_ratio").value is not None:
        add("Crédito", f"Parcelas de empréstimo do banco equivalem a {v('debt_service_ratio')} das entradas externas "
                       f"observadas em {recent}.", "debt_service_ratio")
    for key, m in b.features.measurements.items():
        if m.metric == "loan_outstanding_balance" and m.value is not None:
            add("Crédito", f"{m.label}: {v(key)}.", key)
    if b.ev("installments_overdue"):
        amount = f", somando {v('installments_overdue_amount')}" if b.ev("installments_overdue_amount") else ""
        add("Crédito", f"Parcelas de empréstimo vencidas e não pagas: {v('installments_overdue')}{amount}.",
            "installments_overdue", "installments_overdue_amount")
    if b.ev("installments_paid_late") and b.ev("installments_paid_late").value:
        add("Crédito", f"Parcelas pagas com atraso na janela: {v('installments_paid_late')}.", "installments_paid_late")
    if b.ev("first_late_installment"):
        add("Crédito", f"Primeira parcela com atraso na janela: vencimento em {v('first_late_installment')}.",
            "first_late_installment")
    if b.ev("card_not_full_last3"):
        add("Crédito", f"Faturas do cartão não pagas integralmente em jun–ago/2026: {v('card_not_full_last3')} de 3.",
            "card_not_full_last3")
    if b.ev("card_below_minimum"):
        add("Crédito", f"Faturas com pagamento abaixo do mínimo na janela: {v('card_below_minimum')}.", "card_below_minimum")
    for key, m in b.features.measurements.items():
        if m.metric == "card_days_past_due":
            add("Crédito", f"Cartão com {v(key)} dia(s) em atraso na posição de 01/09/2026.", key)
    for key, m in b.features.measurements.items():
        if m.metric == "renegotiation_status":
            add("Renegociações", f"{m.label}: status {m.value} (motivo não registrado na base).", key)
    if b.ev("renegotiation_count") and not b.ev("renegotiation_count").value:
        add("Renegociações", "Nenhuma proposta de renegociação registrada nesta base.", "renegotiation_count")
    if b.ev("contact_count") and b.ev("contact_count").value is not None:
        add("Contatos", f"Contatos registrados: {v('contact_count')} ({b.ev('contact_count').formula}).", "contact_count")
    add("Fontes", f"Consentimento Open Finance: {v('of_consent_status')}"
                  + (f"; última sincronização em {v('of_last_sync')}." if b.ev("of_last_sync") else "."),
        "of_consent_status", "of_last_sync")
    return facts


# ---------------------------------------------------------------------- sinais (determinísticos)
def _signals(b: EvidenceBundle) -> list[Signal]:
    out: list[Signal] = []
    fr = b.features

    def add(code, title, description, method, *keys):
        ids = [b.eid(k) for k in keys if b.eid(k)]
        if ids:
            out.append(Signal(signal_id=f"S{len(out) + 1:02d}", code=code, title=title, description=description,
                              method=method, evidence_ids=ids))

    inc_key = "recurring_change" if b.ev("recurring_change") else "inflow_change"
    inc = b.ev(inc_key)
    if inc and inc.value is not None and inc.value <= Decimal("-20"):
        kind = "recorrentes identificáveis" if inc_key == "recurring_change" else "externas observadas"
        add("INFLOW_REDUCTION", "Redução das entradas observadas",
            f"As entradas {kind} variaram {inc.value_display} entre mar–mai e jun–ago/2026.",
            "variação ≤ −20% entre as médias mensais das duas janelas, com visibilidade constante", inc_key, "inflow_drop_start")
        first_delinquency = min([d for d in (fr.credit.first_late_installment, fr.credit.first_card_below_minimum) if d],
                                default=None)
        if fr.income.drop_start_month and first_delinquency and fr.income.drop_start_month <= first_delinquency:
            add("INFLOW_REDUCTION_BEFORE_DELINQUENCY", "A redução das entradas precedeu o primeiro atraso",
                f"O primeiro mês com entradas abaixo de 80% da média anterior ({fmt_month(fr.income.drop_start_month)}) "
                f"é anterior ao primeiro atraso registrado ({fmt_date(first_delinquency)}). Precedência no tempo não "
                "demonstra causa.",
                "comparação de datas entre o início da redução e o primeiro atraso registrado",
                "inflow_drop_start", "first_late_installment", "card_below_minimum")
    exp = b.ev("expense_change")
    if b.ev("expense_isolated_peak"):
        add("EXPENSE_ISOLATED_PEAK", "Pico isolado de despesa",
            f"Despesa concentrada em {b.ev('expense_isolated_peak').value_display}; os demais meses mantiveram o padrão "
            "anterior. Um pico isolado não indica, sozinho, mudança de padrão.",
            "um único mês > 150% da média anterior e os outros dois a ±20%", "expense_isolated_peak", "expense_change")
    elif exp and exp.value is not None and exp.value >= Decimal("20"):
        add("EXPENSE_INCREASE", "Aumento da despesa econômica observada",
            f"A despesa econômica observada variou {exp.value_display} entre mar–mai e jun–ago/2026.",
            "variação ≥ +20% entre as médias mensais, sem pico isolado", "expense_change")
    for key, m in fr.measurements.items():
        if m.metric == "expense_category_change_3m" and m.sensitive:
            add("SENSITIVE_CATEGORY_CHANGE", "Mudança relevante em categoria potencialmente sensível",
                "Despesas observadas nessa categoria mudaram de forma relevante. Trata-se apenas de mudança financeira; "
                "nenhuma condição pessoal é inferida.", "variação ≥ 30% e ≥ R$ 100/mês", key)
    for key, m in fr.measurements.items():
        if m.metric == "card_utilization_current" and m.value is not None and m.value >= 80:
            add("HIGH_CARD_UTILIZATION", "Utilização elevada do limite do cartão",
                f"O saldo atual corresponde a {b.ev(key).value_display} do limite.", "utilização ≥ 80%", key)
    nf = b.ev("card_not_full_last3")
    if nf and nf.value and nf.value >= 2:
        add("CARD_PAYMENTS_BELOW_FULL", "Faturas recentes não pagas integralmente",
            f"{nf.value} das 3 faturas de jun–ago/2026 não foram pagas integralmente.",
            "≥ 2 das últimas 3 faturas com valor pago < valor da fatura", "card_not_full_last3", "card_below_minimum")
    od = b.ev("installments_overdue")
    if od and od.value:
        add("OVERDUE_INSTALLMENTS", "Parcelas de empréstimo vencidas",
            f"{od.value} parcela(s) vencida(s) sem pagamento na posição de 01/09/2026.",
            "parcelas com vencimento anterior à data de referência e sem pagamento",
            "installments_overdue", "installments_overdue_amount")
    for key, m in fr.measurements.items():
        if m.metric == "renegotiation_status" and m.value == "rompido":
            add("PRIOR_AGREEMENT_BROKEN", "Acordo anterior rompido",
                f"{m.label} consta como rompida. A base não registra o motivo.", "status registrado", key)
    redemptions = [t for t in fr.transfers.redemptions_in if t["date"] >= RECENT_WINDOW[0]]
    if redemptions:
        add("LIQUIDITY_FROM_INVESTMENT", "Uso de reserva financeira",
            "Houve resgate de investimento em jun–ago/2026 (movimentação patrimonial, não renda).",
            "resgate de aplicação própria creditado na janela recente", "investment_redemptions")
    if b.ev("of_consent_status") and b.ev("of_consent_status").value == "EXPIRED":
        add("VISIBILITY_LOSS", "Perda de visibilidade de fonte externa",
            f"O consentimento Open Finance expirou; última sincronização em "
            f"{b.ev('of_last_sync').value_display if b.ev('of_last_sync') else 'data não informada'}. "
            "Ausência de dados posterior não significa ausência de renda.",
            "status do consentimento", "of_consent_status", "of_last_sync")
    return out


# ---------------------------------------------------------------------- lacunas, limitações e perguntas padrão
def _missing(b: EvidenceBundle) -> list[MissingInformation]:
    out = []
    for mq in b.data_quality.metrics:
        if mq.status == "INSUFFICIENT":
            out.append(MissingInformation(item=mq.label, reason=mq.reason, metric=mq.metric))
    if b.ev("declared_income"):
        out.append(MissingInformation(item="Renda atual comprovada",
                                      reason="a renda declarada não tem data de atualização nem fonte", metric="income_shift"))
    status = b.ev("of_consent_status").value if b.ev("of_consent_status") else None
    if status in ("REJECTED", "SEM_REGISTRO", "EXPIRED", "AUTHORISED_PARTIAL"):
        out.append(MissingInformation(item="Situação em outras instituições",
                                      reason="contas, cartões ou empréstimos externos não estão (totalmente) visíveis",
                                      metric="credit_history"))
    for mq in b.data_quality.metrics:
        for lim in mq.limitations:
            if "sem parcela correspondente" in lim:
                out.append(MissingInformation(item="Parcelas anteriores do empréstimo", reason=lim, metric=mq.metric))
    return out


def _limitations(b: EvidenceBundle) -> list[str]:
    lims = list(b.data_quality.limitations)
    lims.append(OPEN_FINANCE_NOTICE)
    lims.append("Fatos e sinais são calculados por regras determinísticas; hipóteses são possibilidades a validar, "
                "não conclusões.")
    lims += b.data_quality.conflicts
    for mq in b.data_quality.metrics:
        if mq.status == "PARTIAL":
            lims.append(f"{mq.label}: cobertura parcial — {mq.reason}.")
    seen, out = set(), []
    for l in lims:
        if l not in seen:
            seen.add(l)
            out.append(l)
    return out


_DEFAULT_Q = {
    "INFLOW_REDUCTION": "Houve alguma mudança recente nas suas entradas de dinheiro?",
    "VISIBILITY_LOSS": "Existem outras contas ou fontes de entrada que não aparecem nos registros do banco?",
    "CARD_PAYMENTS_BELOW_FULL": "Como tem sido a organização dos pagamentos do cartão nos últimos meses?",
    "OVERDUE_INSTALLMENTS": "Há alguma informação sobre as parcelas em aberto que você queira compartilhar?",
    "PRIOR_AGREEMENT_BROKEN": "Se quiser compartilhar, o que dificultou a continuidade do acordo anterior?",
    "EXPENSE_ISOLATED_PEAK": "Houve alguma despesa pontual recente que você queira comentar?",
    "EXPENSE_INCREASE": "Houve mudanças recentes nas suas despesas do dia a dia?",
    "LIQUIDITY_FROM_INVESTMENT": "Houve uso recente de reservas financeiras que você queira comentar?",
}


def _default_questions(b: EvidenceBundle) -> list[str]:
    qs = [_DEFAULT_Q[s.code] for s in b.signals if s.code in _DEFAULT_Q]
    if not qs:
        qs = ["Há alguma mudança recente na sua situação financeira que você queira compartilhar?"]
    return list(dict.fromkeys(qs))[:5]


def month_word(d: date) -> str:
    return MONTH_NAMES[d.month - 1]
