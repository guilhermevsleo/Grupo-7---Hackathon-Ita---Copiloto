"""Regressão a partir do teste real com o Gemini (26/09/2026).

No teste real, o validador aprovou duas perguntas e uma hipótese que violam o briefing. As regras foram
reforçadas e as frases literais do modelo viraram casos de teste. As frases legítimas do mesmo teste
continuam sendo aceitas (para não trocar um erro por excesso de bloqueio).
"""
from __future__ import annotations

import pytest

from copiloto.evidence import build_evidence_bundle
from copiloto.features.common import CaseData
from copiloto.features.engine import run_features
from copiloto.validator import validate_agent_output


@pytest.fixture()
def case(app, session_a):
    def make(case_id):
        ctx = session_a.open_case(case_id)
        data = CaseData.load(session_a.repository(), app.schema, ctx.active_customer_id,
                             app.sensitive_categories, app.sensitive_label)
        return ctx, build_evidence_bundle(ctx, run_features(data), app.snapshot_version)
    return make


def output(ctx, b, *, hypotheses=(), questions=()):
    return {"case_ref": ctx.customer_ref,
            "executive_summary": [{"text": f"Há registro de faturas não pagas integralmente ({{{b.eid('card_not_full_last3')}}}).",
                                   "evidence_ids": [b.eid("card_not_full_last3")]}],
            "hypotheses": [{"text": h, "evidence_ids": [b.eid("card_not_full_last3")]} for h in hypotheses],
            "suggested_questions": list(questions)}


@pytest.mark.parametrize("question", [
    "Existe algum canal de comunicação de sua preferência para receber informações sobre sua conta?",
    "Como podemos ajudar a ajustar o vencimento ou as condições de pagamento às suas necessidades atuais?",
    "Você teria interesse em uma proposta de acordo?",
    "Gostaria de renegociar as parcelas em aberto?",
    "Podemos propor um novo acordo para regularizar a situação?",
])
def test_perguntas_que_escaparam_no_teste_real_agora_sao_bloqueadas(case, question):
    ctx, b = case("CASE_0002")
    result = validate_agent_output(output(ctx, b, questions=[question]), b, ctx)
    assert not result.ok


def test_hipotese_apoiada_em_dado_ausente_agora_e_bloqueada(case):
    ctx, b = case("CASE_0002")
    text = ("É possível que o atraso recente esteja relacionado a mudanças no fluxo de caixa que não são "
            "visíveis devido à ausência de dados atualizados.")
    result = validate_agent_output(output(ctx, b, hypotheses=[text]), b, ctx)
    assert "HYPOTHESIS_ON_MISSING_DATA" in {v.code for v in result.violations}


def test_frases_legitimas_do_teste_real_continuam_aceitas(case):
    ctx, b = case("CASE_0001")
    out = output(ctx, b,
                 hypotheses=["É possível que a diminuição no fluxo de entradas observada a partir de junho esteja "
                             "relacionada a oscilações no cronograma de recebimentos."],
                 questions=["Houve alteração recente no recebimento de seus rendimentos que impactou seu "
                            "planejamento financeiro?",
                            "Os gastos observados no período recente refletem seu padrão habitual de despesas?",
                            "Poderia confirmar se houve alguma alteração recente em suas fontes de receita ou despesas?",
                            # mencionar o histórico de renegociação é legítimo (teste real, CASE_0003)
                            "Houve alguma dificuldade que impediu a continuidade das renegociações anteriores?"])
    result = validate_agent_output(out, b, ctx)
    assert result.ok, result.violations


def test_data_de_referencia_e_valores_das_notas_da_evidencia_sao_aceitos(case):
    ctx, b = case("CASE_0003")
    dsr = b.eid("debt_service_ratio")
    out = {"case_ref": ctx.customer_ref,
           "executive_summary": [{"text": "Na posição de 01/09/2026 as parcelas do empréstimo, de R$ 740,00 por mês, "
                                          f"equivalem a {{{dsr}}} das entradas observadas.", "evidence_ids": [dsr]}],
           "hypotheses": [], "suggested_questions": []}
    result = validate_agent_output(out, b, ctx)
    assert result.ok, result.violations


def test_data_inventada_continua_bloqueada(case):
    ctx, b = case("CASE_0003")
    out = {"case_ref": ctx.customer_ref,
           "executive_summary": [{"text": "O atraso começou em 03/01/2026.", "evidence_ids": [b.eid("first_late_installment")]}],
           "hypotheses": [], "suggested_questions": []}
    assert not validate_agent_output(out, b, ctx).ok


def test_marcador_abreviado_resolve_so_no_pacote_do_cliente_ativo(case, app):
    ctx, b = case("CASE_0001")
    full = b.eid("recurring_change")
    short_id = full.split("-")[0]
    out = {"case_ref": ctx.customer_ref,
           "executive_summary": [{"text": f"As entradas recorrentes identificáveis caíram {{{short_id}}}.",
                                  "evidence_ids": [short_id]}],
           "hypotheses": [], "suggested_questions": []}
    result = validate_agent_output(out, b, ctx)
    assert result.ok, result.violations
    assert "−40,4%" in result.summary[0].text and result.summary[0].evidence_ids == [full]
