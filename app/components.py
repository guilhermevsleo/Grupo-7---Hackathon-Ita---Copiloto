"""Componentes da interface do colaborador e do painel de governança."""
from __future__ import annotations

import json
from decimal import Decimal

import altair as alt
import pandas as pd
import streamlit as st

from labels import AI_STATE, SIGNAL_TONE, VIOLATION_PT
from theme import CASE_STATUS, QUALITY_WORD, chip, e, ev_tags

from copiloto.features.common import fmt_date, fmt_month
from copiloto.money import fmt_brl

CHART_BLUE, CHART_ORANGE = "#2456C9", "#D96500"  # validados: CVD, contraste ≥ 3:1 (dataviz)


def html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def brl_compact(cents: int | None) -> str:
    if cents is None:
        return "—"
    reais = int(Decimal(cents) / 100 + Decimal("0.5"))
    return "R$ " + f"{reais:,}".replace(",", ".")


def short(text: str, n: int = 90) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


# ---------------------------------------------------------------------- evidência
def render_evidence(ev) -> None:
    if ev.period_start and ev.period_end and ev.period_start != ev.period_end:
        period = f"{fmt_date(ev.period_start)} a {fmt_date(ev.period_end)}"
    elif ev.period_end:
        period = fmt_date(ev.period_end)
    else:
        period = "posição na data de referência (01/09/2026)"
    q = ev.quality_status
    html(f'<div class="small muted" style="font-family:ui-monospace,Consolas,monospace">{e(ev.evidence_id)}</div>'
         f'<div style="font-weight:600;color:#15181D">{e(ev.label)}</div>'
         f'<div style="font-size:22px;font-weight:700;margin:2px 0 4px">{e(ev.value_display)}</div>'
         f'{chip("Qualidade " + QUALITY_WORD[q].lower(), {"SUFFICIENT": "c-ok", "PARTIAL": "c-warn", "INSUFFICIENT": "c-crit"}[q])}')
    st.markdown(f"**Fonte:** {e(ev.source)}  \n**Período:** {e(period)}  \n"
                f"**Cálculo:** {e(ev.formula)} · `{e(ev.formula_version)}`")
    if ev.limitations:
        st.caption(" · ".join(ev.limitations))
    if ev.source_row_ids:
        more = f" (+{len(ev.source_row_ids) - 8})" if len(ev.source_row_ids) > 8 else ""
        st.caption(f"Linhas de origem ({len(ev.source_row_ids)}): {', '.join(ev.source_row_ids[:8])}{more}")
    if ev.detail:
        st.dataframe(detail_frame(ev.detail), hide_index=True, use_container_width=True, height=240)


def detail_frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    names = {"mes": "Mês", "entradas_externas": "Entradas externas", "resgates": "Resgates",
             "despesas_debito": "Débitos de consumo", "compras_cartao": "Compras no cartão",
             "despesa_economica": "Despesa econômica", "pagamento_fatura": "Pagamento de fatura",
             "parcelas_emprestimo": "Parcelas", "saques": "Saques", "saldo_do_mes": "Saldo do mês",
             "fontes_visiveis": "Fontes visíveis", "compras": "Compras", "fatura": "Fatura", "residuo": "Resíduo",
             "pago_na_conta": "Pago (conta)", "pago_na_fatura": "Pago (fatura)", "minimo": "Mínimo",
             "dias_atraso": "Dias de atraso"}
    for col in df.columns:
        if col in ("mes", "fontes_visiveis", "dias_atraso"):
            continue
        df[col] = df[col].map(lambda v: fmt_brl(v) if isinstance(v, int) else v)
    if "fontes_visiveis" in df:
        df["fontes_visiveis"] = df["fontes_visiveis"].map({True: "sim", False: "não — não ler como zero"})
    return df.rename(columns=names)


def evidence_popover(ids: list[str], evidence: dict, key: str, label: str = "Evidência") -> None:
    ids = [i for i in ids if i in evidence]
    if not ids:
        return
    with st.popover(label, icon=":material/manage_search:", type="tertiary", key=key):
        for n, eid in enumerate(ids):
            if n:
                st.divider()
            render_evidence(evidence[eid])


# ---------------------------------------------------------------------- faixa do caso e indicadores
def case_strip(c, emp_name: str, ai_state: str, facts_ms: int | None, llm_ms: int | None) -> None:
    status_label, status_cls = CASE_STATUS[c.status]
    ai_label, ai_cls = AI_STATE[ai_state]
    model = c.versions.get("model_version", "")
    timing = f"fatos {facts_ms} ms" if facts_ms is not None else "—"
    if llm_ms:
        timing += f" · IA {llm_ms / 1000:.1f} s".replace(".", ",")
    html(f"""<div class="cs">
  <div><div class="cs-ref">Cliente {e(c.customer_ref)}</div>
       <div class="cs-case">{e(c.case_id)} · pseudônimo de exibição</div></div>
  <div class="cs-sep"></div>
  <div class="cs-item"><small>Dados</small>{chip(status_label, status_cls)}</div>
  <div class="cs-item"><small>IA</small>{chip(ai_label, ai_cls, title=model)}</div>
  <div class="cs-item"><small>Tempo</small><b>{e(timing)}</b></div>
  <div class="cs-item"><small>Colaborador</small><b>{e(emp_name)}</b></div>
</div>""")


def _kpi(label: str, value: str, *, suffix: str = "", delta: str = "", delta_cls: str = "d-neutral",
         foot: str = "", quality: str = "SUFFICIENT", reason: str = "", meter: float | None = None,
         meter_color: str = CHART_BLUE, na: bool = False) -> str:
    meter_html = ""
    if meter is not None:
        meter_html = f'<div class="meter"><i style="width:{max(0, min(100, meter)):.0f}%;background:{meter_color}"></i></div>'
    title = f"Qualidade da métrica: {QUALITY_WORD[quality]}" + (f" — {reason}" if reason else "")
    return (f'<div class="kpi"><div class="kpi-top"><span class="kpi-label">{e(label)}</span>'
            f'<span class="qdot q-{quality}" title="{e(title)}" aria-label="{e(title)}"></span></div>'
            f'<div class="kpi-value{" na" if na else ""}">{e(value)}{f"<small>{e(suffix)}</small>" if suffix else ""}</div>'
            f'{meter_html}{f"<div class={chr(34)}kpi-delta {delta_cls}{chr(34)}>{e(delta)}</div>" if delta else ""}'
            f'<div class="kpi-foot">{e(foot)}</div></div>')


def _delta(ev, *, up_is: str) -> tuple[str, str]:
    """Seta + valor + referência. Cor = direção × se subir é bom; nunca só cor (seta e texto)."""
    v = ev.value
    if v is None:
        return "", "d-neutral"
    arrow = "↑" if v > 0 else "↓" if v < 0 else "→"
    text = f"{arrow} {ev.value_display.lstrip('+−')} vs mar–mai"
    if v == 0:
        return text, "d-neutral"
    good = (v > 0) == (up_is == "good")
    if good:
        return text, "d-good"
    return text, "d-bad" if abs(v) >= 20 else "d-warn"


def kpi_row(bundle, quality_by_metric: dict) -> list[tuple[str, list[str]]]:
    """Desenha os 5 indicadores e devolve (rótulo, evidências) para os botões de evidência."""
    ev = bundle.ev
    tiles, ids_per_tile = [], []

    def q(metric):
        m = quality_by_metric.get(metric)
        return (m.status, m.reason) if m else ("SUFFICIENT", "")

    # 1. Entradas
    qs, qr = q("income_shift")
    key = "recurring" if ev("recurring_change") else "inflow" if ev("inflow_change") else None
    if key:
        d, dc = _delta(ev(f"{key}_change"), up_is="good")
        tiles.append(_kpi("Entradas recorrentes" if key == "recurring" else "Entradas externas",
                          brl_compact(ev(f"{key}_recent").value), suffix="/mês", delta=d, delta_cls=dc,
                          foot=f"antes: {brl_compact(ev(f'{key}_prior').value)}/mês (mar–mai)", quality=qs, reason=qr))
        ids_per_tile.append([bundle.eid(f"{key}_prior"), bundle.eid(f"{key}_recent"), bundle.eid(f"{key}_change")])
    else:
        tiles.append(_kpi("Entradas", "Indisponível", foot=short(qr, 70), quality=qs, reason=qr, na=True))
        ids_per_tile.append([bundle.eid("income_shift_unavailable"), bundle.eid("of_last_sync")])

    # 2. Despesa econômica
    qs, qr = q("expense_shift")
    if ev("expense_change"):
        peak = ev("expense_isolated_peak")
        d, dc = _delta(ev("expense_change"), up_is="bad")
        if peak:
            dc = "d-neutral"
        foot = f"pico isolado em {peak.value_display}" if peak else f"antes: {brl_compact(ev('expense_prior').value)}/mês"
        tiles.append(_kpi("Despesa econômica", brl_compact(ev("expense_recent").value), suffix="/mês", delta=d,
                          delta_cls=dc, foot=foot, quality=qs, reason=qr))
        ids_per_tile.append([bundle.eid(k) for k in ("expense_prior", "expense_recent", "expense_change",
                                                     "expense_isolated_peak") if bundle.eid(k)])
    else:
        tiles.append(_kpi("Despesa econômica", "Indisponível", foot=short(qr, 70), quality=qs, reason=qr, na=True))
        ids_per_tile.append([bundle.eid("expense_shift_unavailable")])

    # 3. Cartão
    qs, qr = q("credit_utilization")
    util_keys = [k for k in bundle.by_key if k.startswith("card_utilization_") and ev(k).value is not None]
    dpd_keys = [k for k in bundle.by_key if k.startswith("card_dpd_")]
    if util_keys:
        u = ev(util_keys[0])
        pct = float(u.value)
        color = CHART_BLUE if pct < 50 else "#D08A00" if pct < 80 else "#C0392B"
        foot = "saldo atual ÷ limite" + (f" · {ev(dpd_keys[0]).value} dias em atraso" if dpd_keys else "")
        tiles.append(_kpi("Uso do limite do cartão", u.value_display, meter=pct, meter_color=color, foot=foot,
                          quality=qs, reason=qr))
        ids_per_tile.append([bundle.eid(util_keys[0])] + [bundle.eid(k) for k in dpd_keys])
    else:
        tiles.append(_kpi("Uso do limite do cartão", "Sem dado", foot=short(qr, 70), quality=qs, reason=qr, na=True))
        ids_per_tile.append([bundle.eid("credit_utilization_unavailable")])

    # 4. Comprometimento com parcelas
    qs, qr = q("debt_service_ratio")
    dsr = ev("debt_service_ratio")
    if dsr and dsr.value is not None:
        pct = float(dsr.value)
        color = CHART_BLUE if pct < 30 else "#D08A00" if pct < 50 else "#C0392B"
        tiles.append(_kpi("Parcelas ÷ entradas", dsr.value_display, meter=pct, meter_color=color,
                          foot="empréstimos do banco, jun–ago", quality=qs, reason=qr))
        ids_per_tile.append([bundle.eid("debt_service_ratio")])
    else:
        tiles.append(_kpi("Parcelas ÷ entradas", "Indisponível", foot=short(qr, 70), quality=qs, reason=qr, na=True))
        ids_per_tile.append([bundle.eid("debt_service_unavailable")])

    # 5. Atrasos
    qs, qr = q("credit_history")
    od, amount = ev("installments_overdue"), ev("installments_overdue_amount")
    below = ev("card_below_minimum")
    if od and od.value:
        value = f"{od.value} parcela{'s' if od.value > 1 else ''}"
        foot = f"{brl_compact(amount.value)} vencidos" if amount else ""
        if dpd_keys:
            foot += f" · cartão {ev(dpd_keys[0]).value} dias"
        tiles.append(_kpi("Em atraso", value, delta="parcelas vencidas sem pagamento", delta_cls="d-bad", foot=foot,
                          quality=qs, reason=qr))
    elif dpd_keys:
        tiles.append(_kpi("Em atraso", f"{ev(dpd_keys[0]).value} dias", delta="no cartão", delta_cls="d-warn",
                          foot=f"{below.value} fatura(s) abaixo do mínimo" if below else "", quality=qs, reason=qr))
    else:
        tiles.append(_kpi("Em atraso", "Nenhum registro", foot="nenhuma parcela vencida na base", quality=qs,
                          reason=qr, na=True))
    ids_per_tile.append([bundle.eid(k) for k in ("installments_overdue", "installments_overdue_amount",
                                                 "first_late_installment", "card_below_minimum") if bundle.eid(k)]
                        + [bundle.eid(k) for k in dpd_keys])

    # Grade responsiva (quebra em 2 linhas em telas médias) + um único acesso às evidências dos indicadores.
    html(f'<div class="kpis-wrap"><div class="kpis">{"".join(tiles)}</div></div>')
    names = ["Entradas", "Despesa econômica", "Cartão", "Parcelas ÷ entradas", "Em atraso"]
    with st.popover("Evidências dos indicadores", icon=":material/manage_search:", type="tertiary",
                    key=f"kpi_ev_{bundle.ctx.correlation_id}"):
        for n, (name, ids) in enumerate(zip(names, ids_per_tile)):
            ids = [i for i in ids if i and i in bundle.evidence]
            if not ids:
                continue
            if n:
                st.divider()
            html(f'<div class="card-h" style="margin:0">{e(name)}</div>')
            for eid in ids:
                render_evidence(bundle.evidence[eid])
    return list(zip(tiles, ids_per_tile))


# ---------------------------------------------------------------------- visão geral
def summary_card(c, run, ai_state: str, key: str) -> None:
    with st.container(border=True):
        hyp_count = len(c.hypotheses)
        html(f'<div class="card-h">Resumo do caso<span class="count">'
             f'{f"{hyp_count} hipótese(s) a validar em ③" if hyp_count else ""}</span></div>')
        if ai_state == "PENDING":
            html('<div class="note info pulse"><b>A IA está redigindo o resumo.</b> Costuma levar de 10 a 30 segundos. '
                 'Os indicadores, sinais e evidências já estão completos e não dependem da IA.</div>')
        elif ai_state == "VALIDATED":
            body = "".join(f"<p>{e(s.text)}{ev_tags(s.evidence_ids)}</p>" for s in c.executive_summary)
            html(f'<div class="sum">{body}<div class="sum-foot">Redigido por IA ({e(c.versions["model_version"])}) e '
                 f'<b>aprovado pelo validador</b>: cada frase aponta evidências deste cliente e os números vêm do cálculo.'
                 f'</div></div>')
            return
        elif ai_state == "BLOCKED":
            codes = sorted({v["code"] for v in run.validation.get("violations", [])})
            chips = "".join(chip(VIOLATION_PT.get(code, code), "c-crit", title=code) for code in codes)
            html('<div class="note crit"><b>Não foi possível validar o contexto gerado pela IA.</b> A resposta foi '
                 'descartada inteira e não é exibida. Motivos (registrados na auditoria):</div>'
                 f'<div class="reasons">{chips}</div>')
        elif ai_state == "FAILED":
            html('<div class="note warn"><b>A IA não respondeu a tempo ou está indisponível.</b> Nada foi inventado: '
                 'abaixo, os fatos calculados por regras.</div>')
        else:
            html('<div class="note info">IA desligada: abaixo, os fatos calculados por regras.</div>')
        picks, seen = [], set()
        for f in c.facts:
            if f.topic in ("Entradas", "Despesas", "Crédito") and f.topic not in seen:
                picks.append(f)
                seen.add(f.topic)
        body = "".join(f"<p>{e(f.text)}{ev_tags(f.evidence_ids)}</p>" for f in picks)
        html(f'<div class="sum">{body}<div class="sum-foot">Resumo determinístico: principais fatos por tema.</div></div>')


def signals_card(c) -> None:
    rows = []
    for s in c.signals:
        tone, icon = SIGNAL_TONE.get(s.code, ("info", "•"))
        rows.append(f'<div class="sig"><span class="sig-ic t-{tone}" aria-hidden="true">{e(icon)}</span>'
                    f'<div><b>{e(s.title)}</b><div>{e(s.description)}</div></div></div>')
    body = "".join(rows) or '<div class="small muted">Nenhum padrão atingiu os critérios definidos.</div>'
    html(f'<div class="card"><div class="card-h">Sinais<span class="count">padrões derivados dos fatos</span></div>{body}</div>')


def quality_card(c, key: str) -> None:
    dq = c.data_quality
    label, cls = CASE_STATUS[dq.overall]
    rows = []
    for m in dq.metrics:
        rows.append(f'<div class="qrow"><span class="qdot q-{m.status}"></span><span class="lbl">{e(m.label)}</span>'
                    f'<span class="st st-{m.status}">{QUALITY_WORD[m.status]}</span></div>')
        if m.status != "SUFFICIENT":
            rows.append(f'<div class="qreason">{e(short(m.reason, 120))}</div>')
    with st.container(border=True):
        html(f'<div class="card-h">Confiabilidade dos dados<span class="count">{chip(label, cls)}</span></div>'
             + "".join(rows)
             + f'<div class="qreason" style="margin:8px 0 0">{e(dq.open_finance_statement)}</div>')
        if dq.conflicts:
            with st.popover(f"{len(dq.conflicts)} conflito(s) de metadados", icon=":material/rule:", type="tertiary",
                            key=f"conf_{key}"):
                for conflict in dq.conflicts:
                    st.markdown(f"- {e(conflict)}")


def missing_card(c) -> None:
    if not c.missing_information:
        return
    items = "".join(f'<div class="qrow"><span class="lbl"><b>{e(m.item)}</b><br><span class="small muted">'
                    f'{e(short(m.reason, 130))}</span></span></div>' for m in c.missing_information)
    html(f'<div class="card"><div class="card-h">O que falta saber</div>{items}</div>')


def timeline_card(c) -> None:
    items = []
    for ev in c.timeline:
        when = fmt_month(ev.date) if ev.precision == "month" else fmt_date(ev.date)
        items.append(f'<div class="tl-i k-{e(ev.kind)}"><small>{e(when)} · {e(ev.kind)}</small>'
                     f'<div>{e(ev.title)}</div></div>')
    body = f'<div class="tl">{"".join(items)}</div>' if items else '<div class="small muted">Sem eventos datados.</div>'
    html(f'<div class="card"><div class="card-h">Linha do tempo<span class="count">{len(items)} eventos</span></div>{body}</div>')


def cashflow_chart(c, bundle) -> None:
    ev = bundle.ev("monthly_cashflow")
    if not ev or not ev.detail:
        return
    rows = ev.detail
    labels = [r["mes"].split("/")[0] + ("/" + r["mes"].split("/")[1][2:] if i == 0 or r["mes"].startswith("jan")
                                        else "") for i, r in enumerate(rows)]
    points, seg = [], 0
    for i, r in enumerate(rows):
        if not r.get("fontes_visiveis", True):
            seg += 1
            continue
        for serie, key in (("Entradas externas", "entradas_externas"), ("Despesa econômica", "despesa_economica")):
            points.append({"i": i, "mes": r["mes"], "serie": serie, "valor": r[key] / 100,
                           "rotulo": fmt_brl(r[key]), "seg": f"{serie}-{seg}"})
    domain = alt.Scale(domain=[-0.5, len(rows) - 0.5], nice=False)
    gap_idx = [i for i, r in enumerate(rows) if not r.get("fontes_visiveis", True)]
    gaps = [{"x0": i - 0.5, "x1": i + 0.5, "mes": r["mes"], "txt": "Sem visibilidade completa das fontes — não é zero"}
            for i, r in enumerate(rows) if i in gap_idx]
    clusters, run_ = [], []
    for i in gap_idx:  # grupos contíguos recebem um único rótulo
        if run_ and i != run_[-1] + 1:
            clusters.append(run_)
            run_ = []
        run_.append(i)
    if run_:
        clusters.append(run_)
    bands = pd.DataFrame([{"x0": 5.5, "x1": 8.5, "nome": "mar–mai", "cor": "#F1F2F4"},
                          {"x0": 8.5, "x1": 11.5, "nome": "jun–ago", "cor": "#EAF0FD"}])
    df = pd.DataFrame(points)
    label_expr = "[" + ",".join(f"'{l}'" for l in labels) + "][datum.value]"
    x = alt.X("i:Q", scale=domain,
              axis=alt.Axis(values=list(range(len(rows))), labelExpr=label_expr, title=None, grid=False,
                            labelColor="#6B7280", labelFontSize=11, domainColor="#E5E7EB", tickColor="#E5E7EB"))
    height = 230
    layers = [alt.Chart(bands).mark_rect().encode(
        x=alt.X("x0:Q", scale=domain), x2="x1:Q", color=alt.Color("cor:N", scale=None),
        tooltip=[alt.Tooltip("nome:N", title="Janela de comparação")])]
    if gaps:
        layers.append(alt.Chart(pd.DataFrame(gaps)).mark_rect(color="#FBEFD9").encode(
            x=alt.X("x0:Q", scale=domain), x2="x1:Q",
            tooltip=[alt.Tooltip("mes:N", title="Mês"), alt.Tooltip("txt:N", title="Aviso")]))
    color = alt.Color("serie:N", scale=alt.Scale(domain=["Entradas externas", "Despesa econômica"],
                                                 range=[CHART_BLUE, CHART_ORANGE]),
                      legend=alt.Legend(title=None, orient="top", direction="horizontal", labelFontSize=12,
                                        labelColor="#3D4450", symbolType="stroke", symbolStrokeWidth=2))
    y = alt.Y("valor:Q", title=None, scale=alt.Scale(zero=True), axis=alt.Axis(
        labelExpr="'R$ ' + replace(format(datum.value, ',.0f'), ',', '.')", tickCount=4, gridColor="#EEF0F3",
        domain=False, ticks=False, labelColor="#6B7280", labelFontSize=11))
    tooltip = [alt.Tooltip("mes:N", title="Mês"), alt.Tooltip("serie:N", title="Série"),
               alt.Tooltip("rotulo:N", title="Valor")]
    if not df.empty:
        base = alt.Chart(df).encode(x=x, y=y, color=color)
        layers += [
            base.mark_line(strokeWidth=2, strokeCap="round", strokeJoin="round").encode(detail="seg:N"),
            base.mark_circle(size=64, opacity=1, stroke="white", strokeWidth=2),
            base.mark_circle(size=420, opacity=0).encode(tooltip=tooltip),  # área de hover maior que o ponto
        ]
    # Rótulos das janelas na linha do zero (dentro da área do gráfico: posição absoluta em pixels
    # fora do plot faz o Vega encolher o gráfico para caber o texto).
    layers.append(alt.Chart(bands).mark_text(align="center", baseline="bottom", dy=-5, fontSize=10.5,
                                             color="#6B7280", fontWeight=600).encode(
        x=alt.X("xm:Q", scale=domain), y=alt.Y("zero:Q"), text="nome:N").transform_calculate(
        xm="(datum.x0 + datum.x1) / 2", zero="0"))
    if clusters:
        marks = pd.DataFrame([{"xm": (c[0] + c[-1]) / 2, "txt": "sem visibilidade"} for c in clusters])
        layers.append(alt.Chart(marks).mark_text(baseline="top", dy=4, fontSize=10.5, color="#8A5300",
                                                 fontWeight=700).encode(
            x=alt.X("xm:Q", scale=domain), y=alt.value(0), text="txt:N"))
    chart = alt.layer(*layers).properties(height=height).configure_view(stroke=None).configure(
        font="Inter, Segoe UI, Roboto, Arial, sans-serif", background="#FFFFFF")
    with st.container(border=True):
        html('<div class="card-h">Entradas e despesa econômica por mês<span class="count">'
             'tabela completa em ② Evidências</span></div>')
        st.altair_chart(chart, use_container_width=True, theme=None)
        note = "Faixas cinza e azul: janelas base (mar–mai) e recente (jun–ago) usadas nas variações."
        if gaps:
            note += (" Faixa bege: mês sem visibilidade completa das fontes — o valor não é desenhado porque "
                     "ausência de dado não é zero.")
        st.caption(note)


# ---------------------------------------------------------------------- evidências
def facts_tab(c, bundle, key: str) -> None:
    topics = list(dict.fromkeys(f.topic for f in c.facts))
    left, right = st.columns([1.6, 1], gap="large")
    with left:
        for topic in topics:
            html(f'<div class="topic">{e(topic)}</div>')
            for f in (f for f in c.facts if f.topic == topic):
                a, b = st.columns([5, 1], vertical_alignment="center", gap="small")
                with a:
                    html(f'<div class="fact">{e(f.text)}</div>')
                with b:
                    evidence_popover(f.evidence_ids, c.evidence, key=f"fact_{key}_{f.fact_id}", label="Ver")
    with right:
        cash = bundle.ev("monthly_cashflow")
        with st.container(border=True):
            html('<div class="card-h">Fluxo mensal (tabela do gráfico)</div>')
            if cash and cash.detail:
                df = detail_frame([{k: r[k] for k in ("mes", "entradas_externas", "despesa_economica",
                                                        "fontes_visiveis")} for r in cash.detail])
                st.dataframe(df, hide_index=True, use_container_width=True, height=250)
                evidence_popover([cash.evidence_id], c.evidence, key=f"cash_{key}", label="Cálculo completo")
        rec = bundle.ev("card_reconciliation")
        if rec:
            with st.container(border=True):
                html('<div class="card-h">Cartão: compras × fatura × pagamento</div>')
                st.caption(rec.limitations[0] if rec.limitations else "")
                evidence_popover([rec.evidence_id], c.evidence, key=f"rec_{key}", label="Ver conciliação")
        with st.container(border=True):
            html(f'<div class="card-h">Limitações desta análise<span class="count">{len(c.limitations)}</span></div>')
            for lim in c.limitations:
                html(f'<div class="qreason" style="margin:0 0 6px">• {e(lim)}</div>')


# ---------------------------------------------------------------------- conversa e decisão
def conversation_tab(c, ai_state: str) -> None:
    left, right = st.columns([1.35, 1], gap="large")
    with left:
        if c.hypotheses:
            body = "".join(f'<div class="hyp"><small>{e(h.label)}</small><div>{e(h.text)}{ev_tags(h.evidence_ids)}</div></div>'
                           for h in c.hypotheses)
        elif c.status == "INSUFFICIENT_DATA":
            body = '<div class="note warn">Dados insuficientes: nenhuma hipótese é apresentada.</div>'
        elif ai_state == "PENDING":
            body = '<div class="note info pulse">A IA está redigindo as hipóteses…</div>'
        elif ai_state == "DISABLED":
            body = ('<div class="small muted">Hipóteses são redigidas pela IA e só aparecem depois de aprovadas pelo '
                    'validador. Com a IA desligada, use os sinais e as perguntas abaixo.</div>')
        elif ai_state in ("BLOCKED", "FAILED"):
            body = ('<div class="small muted">A resposta da IA não foi exibida (bloqueada ou indisponível). '
                    'Nenhuma hipótese é mostrada sem validação.</div>')
        else:
            body = '<div class="small muted">A IA não propôs hipóteses sustentadas pelas evidências deste caso.</div>'
        html(f'<div class="card"><div class="card-h">Hipóteses a validar<span class="count">possibilidades, não conclusões'
             f'</span></div>{body}</div>')
        origin = ("redigidas pela IA e validadas" if c.questions_origin == "IA_VALIDADA"
                  else "perguntas padrão da equipe (sem IA)")
        qs = "".join(f'<div class="q"><span>{n}</span><div>{e(q)}</div></div>'
                     for n, q in enumerate(c.suggested_questions, start=1))
        html(f'<div class="card"><div class="card-h">Perguntas para a conversa<span class="count">{e(origin)}</span></div>'
             f'{qs}<div class="qreason" style="margin:8px 0 0">Perguntas neutras para validar informações. '
             f'Não são roteiro de cobrança nem proposta.</div></div>')
    with right:
        rows = "".join(f"<tr><td>{fmt_date(i.date)}</td><td>{e(i.channel)}</td><td>{e(i.outcome)}</td></tr>"
                       for i in c.previous_interactions)
        table = (f'<table class="mini"><tr><th>Data</th><th>Canal</th><th>Resultado</th></tr>{rows}</table>' if rows else
                 '<div class="small muted">Sem interações registradas ou fonte indisponível (ausência de registro '
                 'não significa ausência de contato).</div>')
        html(f'<div class="card"><div class="card-h">Interações anteriores<span class="count">'
             f'{len(c.previous_interactions)}</span></div>{table}</div>')
        notes = [i for i in c.previous_interactions if i.notes]
        if notes:
            with st.expander(f"Notas do CRM ({len(notes)}) — texto não confiável"):
                st.caption("Exibidas como dado, nunca como instrução. Não são enviadas à IA.")
                for i in notes:
                    st.markdown(f"**{fmt_date(i.date)} · {e(i.channel)}**")
                    st.text(i.notes)
        missing_card(c)


# ---------------------------------------------------------------------- governança
def governance_kpis(events: list[dict], check) -> None:
    displayed = [ev for ev in events if ev["event_type"] == "CONTEXT_DISPLAYED"]
    # Taxa só sobre respostas reais do Gemini; testes adversariais simulados contam à parte.
    def provider_failure(ev) -> bool:  # 503/timeout não é bloqueio do validador
        codes = {v["code"] for v in json.loads(ev["validation_result"] or "{}").get("violations", [])}
        return bool(codes & {"NarrationFailed", "PayloadViolation"})

    real = [ev for ev in displayed if (ev["model_version"] or "").startswith("gemini")
            and json.loads(ev["validation_result"] or "{}").get("ok") is not None and not provider_failure(ev)]
    blocked = [ev for ev in real if json.loads(ev["validation_result"] or "{}").get("ok") is False]
    tests = sum(ev["model_version"] == "teste-adversarial" for ev in displayed)
    fails = sum(ev["event_type"] == "LLM_FAILURE" for ev in events)
    denied = sum(ev["event_type"] == "ACCESS_DENIED" for ev in events)
    rate = f"{len(blocked) / len(real):.0%} de {len(real)}" if real else "sem respostas ainda"
    tiles = [
        _kpi("Trilha de auditoria", "Íntegra" if check.ok else "Alterada", foot=f"{check.events} eventos encadeados",
             quality="SUFFICIENT" if check.ok else "INSUFFICIENT"),
        _kpi("Contextos exibidos", str(len(displayed)), foot=f"{len(real)} com resposta real do Gemini"),
        _kpi("Respostas do Gemini bloqueadas", str(len(blocked)), delta=f"taxa {rate}", delta_cls="d-neutral",
             foot=f"descartadas inteiras · + {tests} teste(s) adversarial(is) simulado(s)"),
        _kpi("Falhas do provedor", str(fails), foot="fallback para fatos determinísticos"),
        _kpi("Acessos negados", str(denied), foot="registrados sem dados do cliente"),
    ]
    for col, tile in zip(st.columns(5, gap="small"), tiles):
        with col:
            html(tile)
