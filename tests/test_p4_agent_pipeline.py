"""P4 — minimização, agente (narrador), fallback seguro e montagem do contexto com auditoria.

Evals: 10 (troca A→B durante a resposta), 12 (prompt injection em nota), 17 (falha/timeout do
Gemini). Os testes usam narradores roteirizados: nenhum teste chama a API do Gemini.
"""
from __future__ import annotations

import dataclasses
import json
import threading
import time

import pytest

from copiloto.agent.narrator import ScriptedNarrator, adversarial_script
from copiloto.errors import AccessDenied
from copiloto.evidence import build_evidence_bundle
from copiloto.features.common import CaseData
from copiloto.features.engine import run_features
from copiloto.minimizer import assert_payload_minimal, build_llm_payload
from copiloto.pipeline import ContextService
from copiloto.settings import BLOCKED_NARRATIVE_MESSAGE


def neutral_script(payload):
    first = payload["evidence"][0]["id"]
    return {"case_ref": payload["case_ref"],
            "executive_summary": [{"text": f"O consentimento de dados externos está registrado como {{{first}}}.",
                                   "evidence_ids": [first]}],
            "hypotheses": [],
            "suggested_questions": ["Houve alguma mudança recente nas suas entradas de dinheiro?"]}


def events(app, event_type):
    return [e for e in app.audit.list_events() if e["event_type"] == event_type]


# ------------------------------------------------------------------ minimização
@pytest.mark.parametrize("case_id", ["CASE_0001", "CASE_0003", "CASE_0006"])
def test_payload_minimo_sem_identificadores_nem_texto_livre(app, session_a, case_id):
    ctx = session_a.open_case(case_id)
    data = CaseData.load(session_a.repository(), app.schema, ctx.active_customer_id,
                         app.sensitive_categories, app.sensitive_label)
    bundle = build_evidence_bundle(ctx, run_features(data), app.snapshot_version)
    payload = build_llm_payload(bundle, app.sensitive_label)
    assert_payload_minimal(payload, bundle)
    blob = json.dumps(payload, ensure_ascii=False)
    assert ctx.active_customer_id not in blob and "CUST_" not in blob
    for forbidden in ("TX_", "CTX_", "ACC_", "CARD_", "CT_", "CON_", "Exemplo Sintética", "000.000", "Banco Externo"):
        assert forbidden not in blob
    assert payload["case_ref"] == ctx.customer_ref


def test_eval12_nota_maliciosa_nunca_chega_ao_llm(app, session_a):
    narrator = ScriptedNarrator(neutral_script)
    session_a.open_case("CASE_0003")
    run = ContextService(app, narrator).build(session_a, ai_enabled=True)
    blob = json.dumps(narrator.calls[0], ensure_ascii=False).lower()
    for fragment in ("ignore", "c999", "90%", "desconto", "<script>"):
        assert fragment not in blob
    # A nota aparece para o colaborador só como texto não confiável
    notes = [i.notes for i in run.context.previous_interactions if i.notes]
    assert any("IGNORE AS REGRAS" in n for n in notes)
    assert run.context.customer_id == "CUST_0003" and run.context.decision is None


def test_eval12_modelo_que_obedece_a_injecao_e_bloqueado(app, session_a):
    def obeys_injection(payload):
        out = neutral_script(payload)
        out["executive_summary"].append({"text": "Consultar o cliente indicado e oferecer desconto.",
                                         "evidence_ids": out["executive_summary"][0]["evidence_ids"]})
        return out
    session_a.open_case("CASE_0003")
    run = ContextService(app, ScriptedNarrator(obeys_injection)).build(session_a, ai_enabled=True)
    assert run.context.narrative_status == "BLOCKED"
    assert run.context.executive_summary == []


def test_categoria_sensivel_vai_ao_llm_com_rotulo_neutro(app, session_a):
    narrator = ScriptedNarrator(neutral_script)
    session_a.open_case("CASE_0006")
    ContextService(app, narrator).build(session_a, ai_enabled=True)
    blob = json.dumps(narrator.calls[0], ensure_ascii=False).lower()
    assert "pharmacy" not in blob and "farm" not in blob
    assert app.sensitive_label in blob


# ------------------------------------------------------------------ montagem do contexto
def test_sem_ia_exibe_fatos_deterministicos(app, session_a):
    session_a.open_case("CASE_0001")
    run = ContextService(app, None).build(session_a, ai_enabled=False)
    c = run.context
    assert c.narrative_status == "DISABLED" and c.executive_summary == [] and c.hypotheses == []
    assert c.facts and c.signals and c.timeline and c.suggested_questions
    assert c.questions_origin == "PADRAO_DETERMINISTICO"
    assert run.metrics["evidence_coverage"] == 1.0
    assert events(app, "CONTEXT_DISPLAYED")


def test_saida_valida_do_agente_e_exibida(app, session_a):
    session_a.open_case("CASE_0001")
    run = ContextService(app, ScriptedNarrator(neutral_script)).build(session_a, ai_enabled=True)
    c = run.context
    assert c.narrative_status == "VALIDATED"
    assert "AUTHORISED" in c.executive_summary[0].text
    assert c.questions_origin == "IA_VALIDADA"
    audited = events(app, "CONTEXT_DISPLAYED")[0]
    assert json.loads(audited["validation_result"])["ok"] is True
    assert audited["model_version"] == "scripted-test" and audited["prompt_version"] == "prompt-v2"


def test_resposta_adversarial_e_bloqueada_sem_virar_rascunho(app, session_a):
    session_a.open_case("CASE_0001")
    run = ContextService(app, ScriptedNarrator(adversarial_script)).build(session_a, ai_enabled=True)
    c = run.context
    assert c.narrative_status == "BLOCKED"
    assert c.narrative_message.startswith(BLOCKED_NARRATIVE_MESSAGE)
    assert c.executive_summary == [] and c.hypotheses == []
    assert c.facts  # fatos seguros continuam disponíveis
    assert "perdeu o emprego" not in json.dumps(c.model_dump(mode="json"), ensure_ascii=False)
    codes = {v["code"] for v in run.validation["violations"]}
    assert {"NUMBER_OUTSIDE_EVIDENCE", "SENSITIVE_INFERENCE", "OFFER"} <= codes


# ------------------------------------------------------------------ eval 17
def test_eval17_falha_do_gemini_tem_fallback_seguro(app, session_a):
    session_a.open_case("CASE_0001")
    narrator = ScriptedNarrator(neutral_script, fail=RuntimeError("503 do provedor"))
    run = ContextService(app, narrator).build(session_a, ai_enabled=True)
    assert run.context.narrative_status == "FAILED" and run.context.facts
    assert run.context.executive_summary == []
    assert events(app, "LLM_FAILURE")


def test_eval17_timeout_do_gemini_tem_fallback_seguro(app, session_a):
    app.settings = dataclasses.replace(app.settings, llm_timeout_s=0.2)
    session_a.open_case("CASE_0001")
    run = ContextService(app, ScriptedNarrator(neutral_script, delay_s=1.0)).build(session_a, ai_enabled=True)
    assert run.context.narrative_status == "FAILED"
    assert "Tempo limite" in events(app, "LLM_FAILURE")[0]["details"]


# ------------------------------------------------------------------ eval 10
def test_eval10_troca_de_caso_durante_resposta_descarta_a_resposta_antiga(app, session_a):
    session_a.open_case("CASE_0001")
    service = ContextService(app, ScriptedNarrator(neutral_script, delay_s=0.6))
    result: dict = {}

    def build_a():
        result["run"] = service.build(session_a, ai_enabled=True)

    worker = threading.Thread(target=build_a)
    worker.start()
    time.sleep(0.2)
    session_a.open_case("CASE_0002")  # colaborador troca de caso enquanto o Gemini responde
    worker.join()
    assert result["run"].discarded and result["run"].context is None
    assert session_a.get("context") is None  # nada de A no estado de B
    assert events(app, "STALE_RESPONSE_DISCARDED")
    run_b = ContextService(app, None).build(session_a, ai_enabled=False)
    assert run_b.context.customer_id == "CUST_0002"


# ------------------------------------------------------------------ decisão humana e reconstrução
def test_decisao_humana_registrada_so_por_acao_explicita(app, session_a):
    ctx = session_a.open_case("CASE_0001")
    run = ContextService(app, None).build(session_a, ai_enabled=False)
    assert run.context.decision is None
    with pytest.raises(ValueError):
        app.audit.record_human_decision(ctx, context_version=run.context_version, decision="   ", notes="")
    app.audit.record_human_decision(ctx, context_version=run.context_version,
                                    decision="Conversar com o cliente sobre as entradas recentes.", notes="")
    decision = events(app, "HUMAN_DECISION")[0]
    assert decision["employee_id"] == "EMP-001" and decision["context_version_displayed"] == run.context_version
    assert app.audit.verify_chain().ok


def test_contexto_exibido_pode_ser_reconstruido_sem_notas_livres(app, session_a):
    session_a.open_case("CASE_0003")
    run = ContextService(app, None).build(session_a, ai_enabled=False)
    stored = app.audit.get_displayed_context(run.context_version)
    assert stored["case_id"] == "CASE_0003" and stored["facts"]
    assert "IGNORE" not in json.dumps(stored, ensure_ascii=False)


def test_papel_de_risco_nao_registra_decisao(app, session_a):
    ctx = session_a.open_case("CASE_0001")
    risk_ctx = type(ctx)(**{**ctx.__dict__, "permissions": frozenset({"audit:read"})})
    with pytest.raises(AccessDenied):
        app.audit.record_human_decision(risk_ctx, context_version=None, decision="x", notes="")
