"""P1 — motor de features determinístico e qualidade de dados.

Evals no nível dos cálculos: 01 queda real de entradas, 02 Open Finance expirado,
03 transferência própria, 04 cartão + fatura, 05 categoria sensível, 06 renegociação rompida,
07 dados insuficientes, 18 padrão estável com pico isolado.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from copiloto.features.common import CaseData, QualityStatus, TxClass
from copiloto.features.engine import run_features
from copiloto.money import fmt_brl, fmt_pct, pct_change, to_cents

S, P, I = QualityStatus.SUFFICIENT, QualityStatus.PARTIAL, QualityStatus.INSUFFICIENT


@pytest.fixture()
def features(app, session_a):
    cache = {}

    def load(case_id: str):
        if case_id not in cache:
            ctx = session_a.open_case(case_id)
            data = CaseData.load(session_a.repository(), app.schema, ctx.active_customer_id,
                                 app.sensitive_categories, app.sensitive_label)
            cache[case_id] = run_features(data)
        return cache[case_id]
    return load


def all_text(fr) -> str:
    parts = []
    for m in fr.measurements.values():
        parts += [m.label, m.formula, *m.limitations]
    for mq in fr.quality.metrics.values():
        parts += [mq.reason, *mq.limitations]
    parts += [e.title for e in fr.timeline]
    return " ".join(parts).lower()


# ------------------------------------------------------------------ dinheiro
def test_centavos_sem_float_e_ausencia_nao_vira_zero():
    assert to_cents(0.1) + to_cents(0.2) == to_cents(0.3) == 30
    assert to_cents(None) is None and to_cents("") is None
    assert pct_change(100, 0) is None  # denominador zero => indisponível
    assert pct_change(66, 100) == Decimal("-34.0")
    assert fmt_brl(123456) == "R$ 1.234,56" and fmt_brl(None) == "indisponível"
    assert fmt_pct(Decimal("-34.0")) == "−34,0%"


# ------------------------------------------------------------------ eval 01
def test_eval01_queda_real_de_entradas_detectada_sem_afirmar_desemprego(features):
    fr = features("CASE_0001")
    assert fr.quality.status("income_shift") == S
    assert fr.measurements["recurring_change"].value == Decimal("-40.4")
    assert fr.measurements["inflow_change"].value < Decimal("-30")
    assert fr.measurements["inflow_drop_start"].value == date(2026, 6, 1)
    assert fr.measurements["inflow_change"].source_row_ids  # reproduzível pelas linhas de origem
    text = all_text(fr)
    assert "desempreg" not in text and "demiti" not in text
    assert "não prova perda de emprego" in text


# ------------------------------------------------------------------ eval 02
def test_eval02_open_finance_expirado_declara_perda_de_visibilidade(features):
    fr = features("CASE_0002")
    mq = fr.quality.metrics["income_shift"]
    assert mq.status == I
    assert "Open Finance sem visibilidade após 2026-05-31" in mq.reason
    assert "inflow_change" not in fr.measurements and "inflow_recent" not in fr.measurements
    unavailable = fr.measurements["income_shift_unavailable"]
    assert unavailable.value is None  # indisponível, nunca zero nem −100%
    assert "não significa ausência de renda" in fr.quality.open_finance_statement
    assert any("PARTIAL" in c and "EXPIRED" in c for c in fr.quality.conflicts)


# ------------------------------------------------------------------ eval 03
def test_eval03_transferencia_propria_nao_e_renda_nem_consumo(features):
    fr = features("CASE_0001")
    data = fr.data
    own_ids = {t["transaction_id"] for t in data.transactions if data.tx_class(t) == TxClass.OWN_TRANSFER}
    redemption_ids = {t["transaction_id"] for t in data.transactions if data.tx_class(t) == TxClass.INVESTMENT_MOVEMENT}
    assert len(fr.transfers.pairs) == 9 and len(fr.transfers.unmatched) == 1
    for key in ("inflow_prior", "inflow_recent", "recurring_prior", "recurring_recent",
                "expense_prior", "expense_recent"):
        rows = set(fr.measurements[key].source_row_ids)
        assert not rows & own_ids, key
        assert not rows & redemption_ids, key
    assert fr.measurements["investment_redemptions"].value == 200_000
    assert "não é renda recorrente" in " ".join(fr.measurements["investment_redemptions"].limitations)


# ------------------------------------------------------------------ eval 04
def test_eval04_compra_no_cartao_e_pagamento_de_fatura_nao_duplicam(features):
    fr = features("CASE_0001")
    data = fr.data
    bill_ids = {t["transaction_id"] for t in data.transactions if data.tx_class(t) == TxClass.CARD_BILL_PAYMENT}
    card_ids = {t["card_transaction_id"] for t in data.card_transactions}
    expense_rows = set(fr.measurements["expense_prior"].source_row_ids) | set(fr.measurements["expense_recent"].source_row_ids)
    assert expense_rows & card_ids  # compras entram na despesa econômica
    assert not expense_rows & bill_ids  # pagamento da fatura não entra
    cashflow = fr.measurements["monthly_cashflow"].detail
    assert any(row["pagamento_fatura"] > 0 for row in cashflow)  # mas aparece no fluxo de caixa
    reconciliation = fr.measurements["card_reconciliation"]
    residuals = [row["residuo"] for row in reconciliation.detail]
    assert sorted(set(residuals)) == [0, 1]  # resíduo de 1 centavo documentado, não escondido


# ------------------------------------------------------------------ eval 05
def test_eval05_categoria_sensivel_so_como_mudanca_financeira(features):
    fr = features("CASE_0006")
    sensitive = [m for m in fr.measurements.values() if m.sensitive]
    assert [m.key for m in sensitive] == ["category_change_pharmacy"]
    assert "não indica condição pessoal" in " ".join(sensitive[0].limitations)
    text = all_text(fr)
    for word in ("doen", "enferm", "diagnóst", "tratamento"):
        assert word not in text


# ------------------------------------------------------------------ eval 06
def test_eval06_renegociacao_rompida_mostra_status_sem_motivo(features):
    fr = features("CASE_0003")
    statuses = [m.value for k, m in fr.measurements.items() if m.metric == "renegotiation_status"]
    assert statuses == ["rompido", "não aceito"]
    text = all_text(fr)
    assert "motivo" in text and "não consta" in text or "não são registrados" in text
    for word in ("porque", "devido a", "desistiu", "não quis"):
        assert word not in text
    assert any(e.kind == "renegociação" and "rompido" in e.title for e in fr.timeline)


# ------------------------------------------------------------------ eval 07
def test_eval07_dados_insuficientes(features):
    fr = features("CASE_0004")
    assert fr.quality.overall == "INSUFFICIENT_DATA"
    assert fr.quality.status("income_shift") == I
    assert "sem observação em mar/2026, abr/2026" in fr.quality.metrics["income_shift"].reason
    assert fr.quality.status("contact_history") == I
    assert "ausência de registro não significa ausência de contato" in fr.quality.metrics["contact_history"].reason
    assert fr.measurements["contacts_unavailable"].value is None
    assert "recurring_change" not in fr.measurements  # renda de classificação incerta não vira "recorrente"
    assert any("sem parcela correspondente" in l for l in fr.quality.metrics["credit_history"].limitations)


# ------------------------------------------------------------------ eval 18
def test_eval18_padrao_estavel_com_pico_isolado(features):
    fr = features("CASE_0005")
    assert fr.measurements["recurring_change"].value == Decimal("0.0")
    peak = fr.measurements["expense_isolated_peak"]
    assert peak.value == date(2026, 7, 1)
    assert "não indica, sozinho, mudança de padrão" in " ".join(peak.limitations)
    assert "category_change_electronics" not in fr.measurements
    text = all_text(fr)
    assert "crise" not in text and "descontrole" not in text


# ------------------------------------------------------------------ qualidade antes da narrativa
@pytest.mark.parametrize("case_id,overall", [("CASE_0001", "COMPLETE"), ("CASE_0002", "PARTIAL"),
                                             ("CASE_0003", "PARTIAL"), ("CASE_0004", "INSUFFICIENT_DATA"),
                                             ("CASE_0005", "COMPLETE")])
def test_status_do_caso_por_regra_sem_score_global(features, case_id, overall):
    fr = features(case_id)
    assert fr.quality.overall == overall
    for mq in fr.quality.metrics.values():
        assert mq.status in (S, P, I) and mq.reason


def test_toda_medicao_tem_proveniencia(features):
    for case_id in ("CASE_0001", "CASE_0003", "CASE_0006"):
        for m in features(case_id).measurements.values():
            assert m.formula and m.source and m.formula_version and m.quality_metric
            if m.value is not None and m.unit.value not in ("status",):
                assert m.source_row_ids or m.unit.value == "count", m.key
