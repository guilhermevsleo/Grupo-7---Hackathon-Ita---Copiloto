"""Interface do Copiloto de Contexto Financeiro.

Executar:  streamlit run app/streamlit_app.py
Um cliente autorizado por vez. O navegador envia apenas o case_id; autorização e cliente ativo são
resolvidos no servidor. Não há busca por cliente. Fluxo em 3 etapas: visão geral → evidências → decisão.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "app"))

import components as ui  # noqa: E402
from theme import CSS, e, topbar  # noqa: E402

from copiloto.agent.narrator import AdkGeminiNarrator, ScriptedNarrator, adversarial_script  # noqa: E402
from copiloto.bootstrap import build_app  # noqa: E402
from copiloto.errors import AccessDenied, AuditUnavailable, SchemaMismatch  # noqa: E402
from copiloto.settings import GOVERNANCE_STATEMENT, PROTOTYPE_NOTICE  # noqa: E402

st.set_page_config(page_title="Copiloto de Contexto — Cobrança", page_icon="🟧", layout="wide",
                   initial_sidebar_state="expanded")
st.markdown(CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------- recursos compartilhados (sem dados de cliente)
class Governance:
    """Interruptor global da IA, controlado pelo papel de risco."""

    def __init__(self):
        self.ai_enabled = True
        self.lock = threading.Lock()


@st.cache_resource
def get_app():
    return build_app()


@st.cache_resource
def get_governance() -> Governance:
    return Governance()


try:
    APP = get_app()
except (SchemaMismatch, FileNotFoundError) as exc:
    st.error(f"Não foi possível abrir a base de dados: {exc}")
    st.info("Gere a base de demonstração com `python tools/build_demo_db.py` ou configure COPILOTO_DB_PATH.")
    st.stop()
GOV = get_governance()
S = APP.settings
NARRATOR = (AdkGeminiNarrator(S.gemini_model, S.gemini_thinking, S.gemini_fallback_models)
            if S.google_api_key_present else None)

ui.html(topbar(S.dataset_label))

# ---------------------------------------------------------------------- identidade simulada e sessão
state = st.session_state
employees = APP.entitlements.all()
with st.sidebar:
    st.markdown("**Identidade simulada**")
    emp = st.selectbox("Colaborador", employees, format_func=lambda x: x.display_name, label_visibility="collapsed")
    st.caption("Sem autenticação corporativa no MVP: a identidade é uma simulação.")

if state.get("employee_id") != emp.employee_id:
    if state.get("case_session") is not None:
        state.case_session.close_case()
    state.employee_id = emp.employee_id
    state.case_session = APP.new_session(emp.employee_id)
    for k in ("run", "run_label", "decision_event", "ai_pending", "facts_ms"):
        state[k] = None
session = state.case_session


def ai_available() -> bool:
    return NARRATOR is not None and GOV.ai_enabled


def open_and_build(case_id: str, *, narrator=None, label: str | None = None) -> None:
    try:
        session.open_case(case_id)
    except AccessDenied as exc:
        state.run = None
        st.error(str(exc))
        return
    state.run_label, state.decision_event, state.ai_pending = label, None, None
    if narrator is not None:  # teste adversarial: resposta roteirizada, instantânea
        run = ui_build(narrator, ai=True)
        state.facts_ms = run.metrics.get("time_to_context_ms") if run else None
        return
    # Fatos determinísticos primeiro (milissegundos); a redação da IA vem em seguida, sem travar a tela.
    run = ui_build(None, ai=False)
    state.facts_ms = run.metrics.get("time_to_context_ms") if run else None
    if run and run.context is not None and ai_available() and state.get("use_ai", True):
        state.ai_pending = run.context.correlation_id


def ui_build(narrator, *, ai: bool):
    from copiloto.pipeline import ContextService
    run = ContextService(APP, narrator).build(session, ai_enabled=ai)
    state.run = None if run.discarded else run
    return state.run


def complete_ai_if_pending() -> None:
    """Chamada no fim da página: os fatos já estão na tela enquanto o Gemini redige.
    Se o colaborador trocar de caso nesse meio-tempo, a resposta antiga é descartada (eval 10)."""
    ctx = session.context
    if not state.get("ai_pending") or ctx is None or state.ai_pending != ctx.correlation_id:
        return
    from copiloto.pipeline import ContextService
    run = ContextService(APP, NARRATOR).build(session, ai_enabled=True)
    state.ai_pending = None
    if not run.discarded:
        state.run = run
    st.rerun()


# ---------------------------------------------------------------------- tela do colaborador
def analyst_view() -> None:
    cases = session.authorized_cases()
    refs = {c.case_id: c.customer_ref for c in cases}
    with st.sidebar:
        st.markdown(f"**Sua fila** · {len(cases)} casos")
        choice = st.radio("Casos autorizados", [c.case_id for c in cases], index=None,
                          format_func=lambda i: f"{refs[i]} · {i}", label_visibility="collapsed",
                          key=f"queue_{emp.employee_id}")
        st.caption("Ordem por número do caso. Sem busca e sem priorização de clientes.")
        st.divider()
        st.markdown("**Inteligência artificial**")
        if NARRATOR is None:
            st.caption("Chave não configurada: modo sem IA (somente fatos calculados).")
        elif not GOV.ai_enabled:
            st.caption("IA desligada pela área de risco.")
        else:
            use_ai = st.toggle("Resumo e hipóteses com IA", value=state.get("use_ai", True),
                               help="Google ADK + Gemini, sem ferramentas, sobre um pacote de evidências minimizado.")
            if use_ai != state.get("use_ai", True):
                state.use_ai = use_ai
                if session.context:
                    open_and_build(session.context.case_id)
        with st.expander("Privacidade e dados"):
            st.caption(S.llm_tier_notice)
            st.caption(f"Base: {S.dataset_label}. Snapshot `{APP.snapshot_version}`.")

    if choice and (session.context is None or session.context.case_id != choice):
        open_and_build(choice)

    run = state.get("run")
    if not choice or run is None or run.context is None:
        ui.html("""<div class="empty"><h3>Selecione um caso da sua fila</h3>
<div class="muted">O copiloto reúne os dados de <b>um cliente autorizado por vez</b> e mostra o que se pode — e o que
não se pode — concluir. O agente prepara o contexto. <b>Você decide.</b></div>
<div class="steps">
 <div class="step"><i>1</i><b>Visão geral</b><span>Indicadores, confiabilidade dos dados, sinais e linha do tempo.</span></div>
 <div class="step"><i>2</i><b>Evidências</b><span>Cada número com fonte, período e cálculo reproduzíveis.</span></div>
 <div class="step"><i>3</i><b>Conversa e decisão</b><span>Hipóteses a validar, perguntas neutras e o registro da sua decisão.</span></div>
</div></div>""")
        return

    c, bundle = run.context, run.bundle
    key = c.correlation_id
    ai_state = "PENDING" if state.get("ai_pending") == key else c.narrative_status

    ui.case_strip(c, emp.display_name.split(" (")[0] + " (simulada)", ai_state, state.get("facts_ms"),
                  run.metrics.get("llm_ms") if c.narrative_status in ("VALIDATED", "BLOCKED") else None)
    with st.sidebar:
        st.divider()
        st.markdown("**Ações do caso**")
        if st.button("Remontar contexto", icon=":material/refresh:", use_container_width=True,
                     help="Reabre o caso com um novo identificador de execução"):
            open_and_build(c.case_id)
            st.rerun()
        if st.button("Testar o validador", icon=":material/science:", use_container_width=True,
                     help="Envia ao validador uma resposta propositalmente inválida (número inventado, oferta, "
                          "inferência sensível). Não usa o Gemini."):
            open_and_build(c.case_id, narrator=ScriptedNarrator(adversarial_script, model_version="teste-adversarial"),
                           label="Teste do validador: resposta adversarial simulada, não veio do Gemini.")
            st.rerun()
    if state.get("run_label"):
        ui.html(f'<div class="note warn" style="margin:0">{e(state.run_label)}</div>')

    quality = {m.metric: m for m in c.data_quality.metrics}
    ui.kpi_row(bundle, quality)

    tabs = st.tabs(["① Visão geral", f"② Evidências · {len(c.facts)} fatos", "③ Conversa e decisão"],
                   key=f"tabs_{key}")
    with tabs[0], st.container(key="overview"):
        left, right = st.columns([1.6, 1], gap="medium")
        with left:
            ui.summary_card(c, run, ai_state, key)
            ui.signals_card(c)
            ui.cashflow_chart(c, bundle)
        with right:
            ui.quality_card(c, key)
            ui.timeline_card(c)
    with tabs[1]:
        ui.facts_tab(c, bundle, key)
    with tabs[2]:
        with st.container(key="conversa"):
            ui.conversation_tab(c, ai_state)
        decision_form(c, run)

    complete_ai_if_pending()


def decision_form(c, run) -> None:
    with st.form(key=f"decision_{c.correlation_id}", clear_on_submit=False, border=True):
        ui.html('<div class="card-h">Sua decisão<span class="count">registrar não executa cobrança, não envia mensagem '
                'e não altera nenhum sistema</span></div>')
        a, b = st.columns([1.3, 1], gap="medium")
        with a:
            decision = st.text_area("Decisão do colaborador", value="", height=96,
                                    placeholder="Escreva com suas palavras. O agente não sugere decisões.")
        with b:
            notes = st.text_area("Observações (opcional)", value="", height=96)
        submitted = st.form_submit_button("Registrar decisão do colaborador", type="primary", icon=":material/task_alt:")
    if submitted:
        if not decision.strip():
            st.warning("Escreva a decisão antes de registrar.")
        else:
            try:
                ctx = session.require_context()
                state.decision_event = APP.audit.record_human_decision(
                    ctx, context_version=run.context_version, decision=decision, notes=notes)
            except (AuditUnavailable, AccessDenied) as exc:
                st.error(f"Decisão NÃO registrada: {exc}")
    if state.get("decision_event"):
        st.success(f"Decisão registrada na trilha de auditoria (evento {state.decision_event[:8]}…), vinculada à versão "
                   f"{run.context_version} do contexto exibido.", icon=":material/verified:")


# ---------------------------------------------------------------------- painel de governança (papel de risco)
def governance_view() -> None:
    check = APP.audit.verify_chain()
    events = APP.audit.list_events(500)
    ui.html(f'<div class="cs"><div><div class="cs-ref">Governança da IA</div><div class="cs-case">'
            f'{e(emp.display_name)} · este papel audita, não abre casos de clientes</div></div></div>')
    ui.governance_kpis(events, check)
    tabs = st.tabs(["Trilha de auditoria", "Reconstruir contexto", "Controles e política"])
    with tabs[0]:
        rows = []
        for ev in events:
            val = json.loads(ev["validation_result"] or "{}")
            rows.append({"Quando": ev["ts"][:19].replace("T", " "), "Evento": ev["event_type"],
                         "Colaborador": ev["employee_id"], "Caso": ev["case_id"],
                         "Validação": {True: "aprovada", False: "bloqueada"}.get(val.get("ok"), "—"),
                         "Motivos": ", ".join(sorted({v["code"] for v in val.get("violations", [])})),
                         "Modelo": ev["model_version"] or "", "Contexto": ev["context_version_displayed"] or "",
                         "Decisão humana": ev["human_decision"] or ""})
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, height=420)
    with tabs[1]:
        displayed = [ev for ev in events if ev["event_type"] == "CONTEXT_DISPLAYED"]
        if not displayed:
            st.info("Nenhum contexto exibido ainda.")
        else:
            chosen = st.selectbox("Versão do contexto exibido", [ev["context_version_displayed"] for ev in displayed],
                                  format_func=lambda v: next(f"{ev['ts'][11:19]} · {ev['case_id']} · {v}"
                                                             for ev in displayed if ev["context_version_displayed"] == v))
            stored = APP.audit.get_displayed_context(chosen)
            if stored:
                a, b = st.columns([1.4, 1], gap="large")
                with a:
                    ui.html(f'<div class="card"><div class="card-h">O que o colaborador viu</div>'
                            f'<div class="small muted">Caso {e(stored["case_id"])} · cliente {e(stored["customer_ref"])} · '
                            f'narrativa {e(stored["narrative_status"])}</div>'
                            + "".join(f"<p style='margin:8px 0 0'>{e(s['text'])}</p>" for s in stored["executive_summary"])
                            + "".join(f"<p class='small' style='margin:8px 0 0'><b>Hipótese:</b> {e(h['text'])}</p>"
                                      for h in stored["hypotheses"]) + "</div>")
                    st.json({"fatos": [f["text"] for f in stored["facts"]]}, expanded=False)
                with b:
                    st.json(stored["versions"])
    with tabs[2]:
        a, b = st.columns([1, 1.3], gap="large")
        with a:
            new = st.toggle("IA habilitada para todos os colaboradores", value=GOV.ai_enabled)
            if new != GOV.ai_enabled:
                with GOV.lock:
                    GOV.ai_enabled = new
                APP.audit.record_ai_toggle(employee_id=emp.employee_id, session_id=session.session_id, enabled=new)
                st.rerun()
            st.caption("Desligar a IA mantém o copiloto funcionando só com fatos determinísticos.")
            st.info(S.llm_tier_notice)
            if NARRATOR is None:
                st.warning("Chave do Gemini não configurada: o sistema opera em modo sem IA.")
        with b:
            with st.expander("Política técnica do MVP (config/privacy_policy.yaml)", expanded=True):
                st.code((S.config_dir / "privacy_policy.yaml").read_text(encoding="utf-8"), language="yaml")
        st.caption(GOVERNANCE_STATEMENT)


# ---------------------------------------------------------------------- roteamento por papel
if "audit:read" in emp.permissions:
    governance_view()
elif "case:open" in emp.permissions:
    analyst_view()
else:
    st.warning("Seu papel não tem permissões nesta aplicação.")

ui.html(f'<div class="foot">{e(PROTOTYPE_NOTICE)} {e(GOVERNANCE_STATEMENT)}</div>')
